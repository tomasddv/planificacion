from __future__ import annotations

import html
import io
import time
import traceback
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

import app as sales_app
from forecast_engine import (
    DAY_COLS,
    DAY_NAMES,
    build_weekday_profiles,
    build_supermarket_weekday_profiles,
    combine_normal_and_supermarket_profiles,
    combine_history,
    forecast_summary,
    load_current_bultos,
    load_history_base,
    load_supermarket_dispatches,
    simulate_fefo,
)


RUNTIME_DIR = sales_app.PROJECT_ROOT / ".cloud_data" / "frescura_predictiva"
HISTORY_CANDIDATES = [
    sales_app.PROJECT_ROOT / "historico_frescura_bultos.csv.gz",
    sales_app.PROJECT_ROOT / "historico_frescura_bultos.csv",
]

SUPERMARKET_HISTORY_CANDIDATES = [
    sales_app.PROJECT_ROOT / "historico_supermercados_bultos.csv.gz",
    sales_app.PROJECT_ROOT / "historico_supermercados_bultos.csv",
]


def _clean(value: object) -> str:
    return sales_app.clean_name("" if value is None else str(value))


def _find_item(items, include_words, suffixes=()):
    matches = []
    for item in items:
        name = Path(str(item.path)).name
        clean = _clean(name)
        if all(word in clean for word in include_words):
            if not suffixes or Path(name).suffix.lower() in suffixes:
                matches.append(item)
    if not matches:
        return None
    return sorted(matches, key=lambda item: Path(str(item.path)).name.lower())[-1]


def _drive_items(drive_url: str):
    import gdown
    return gdown.download_folder(
        url=drive_url,
        output=".",
        quiet=True,
        use_cookies=False,
        skip_download=True,
    ) or []


def _download(item, target_folder: Path) -> Path:
    import gdown

    target_folder.mkdir(parents=True, exist_ok=True)
    name = Path(str(item.path)).name
    final = target_folder / name
    tmp = target_folder / f"{name}.tmp"
    tmp.unlink(missing_ok=True)

    gdown.download(
        id=item.id,
        output=str(tmp),
        quiet=True,
        use_cookies=False,
    )
    if not tmp.exists() or tmp.stat().st_size <= 0:
        raise RuntimeError(f"No se pudo descargar {name}")

    final.unlink(missing_ok=True)
    tmp.replace(final)
    return final


@st.cache_data(show_spinner=False, ttl=1800)
def _operational_sources(drive_url: str, refresh_slot: int):
    """
    Se renueva automáticamente cada 30 minutos.
    refresh_slot hace que la caché cambie sin descargar los 238 MB históricos.
    """
    items = _drive_items(drive_url)

    customer = _find_item(
        items,
        ("plantillaclientesar",),
        suffixes=(".xlsx", ".xls"),
    )
    current = _find_item(
        items,
        ("ventadiaria", "bultos"),
        suffixes=(".txt",),
    )
    supermarket_report = _find_item(
        items,
        ("reportecomprobantesdetallado",),
        suffixes=(".xlsx", ".xls"),
    )

    if customer is None:
        raise RuntimeError("No encontré PlantillaClientesAR en Drive.")
    if current is None:
        raise RuntimeError("No encontré ventadiaria bultos.txt en Drive.")

    customer_path = _download(customer, RUNTIME_DIR)
    current_path = _download(current, RUNTIME_DIR)

    supermarket_path = None
    if supermarket_report is not None:
        supermarket_path = _download(supermarket_report, RUNTIME_DIR)

    return (
        str(customer_path),
        str(current_path),
        str(supermarket_path) if supermarket_path else None,
    )


@st.cache_data(show_spinner=False)
def _history(path_text: str, mtime_ns: int, size: int):
    return load_history_base(path_text)


@st.cache_data(show_spinner=False, max_entries=8)
def _current(
    sales_path: str,
    sales_mtime: int,
    sales_size: int,
    customer_path: str,
    customer_mtime: int,
    customer_size: int,
    wanted_key: tuple[str, ...],
):
    return load_current_bultos(
        sales_txt=sales_path,
        customer_xlsx=customer_path,
        wanted_skus=set(wanted_key),
    )


def _history_file() -> Path | None:
    return next((p for p in HISTORY_CANDIDATES if p.exists()), None)


def _supermarket_history_file() -> Path | None:
    return next(
        (p for p in SUPERMARKET_HISTORY_CANDIDATES if p.exists()),
        None,
    )


@st.cache_data(show_spinner=False, max_entries=8)
def _supermarket_current(
    report_path: str,
    report_mtime: int,
    report_size: int,
    wanted_key: tuple[str, ...],
):
    return load_supermarket_dispatches(
        report_xlsx=report_path,
        wanted_skus=set(wanted_key),
    )


def _fmt(value: object, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "-"
    number = float(value)
    if not np.isfinite(number):
        return "-"
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    value = float(value)
    if not np.isfinite(value):
        return "Sin venta natural"
    return f"{value:.1f}%".replace(".", ",")


def _escape(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return html.escape(str(value), quote=True)


def _date(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return pd.Timestamp(value).strftime("%d/%m/%Y")


def _state_class(state: object) -> str:
    value = str(state or "").upper()
    if value == "CRITICO":
        return "bad"
    if value == "ACCIONAR":
        return "warn"
    return "ok"



def _render_source_breakdown(row: pd.Series) -> None:
    headers = "".join(f"<th>{_escape(day)}</th>" for day in DAY_NAMES)
    rows = []

    sources = [
        ("Venta normal", [row.get(f"normal_{c}", 0.0) for c in DAY_COLS]),
        ("Supermercados", [row.get(f"super_{c}", 0.0) for c in DAY_COLS]),
        ("Salida total", [row.get(c, 0.0) for c in DAY_COLS]),
    ]

    for label, values in sources:
        klass = "total-source" if label == "Salida total" else ""
        cells = "".join(f"<td>{_fmt(v)}</td>" for v in values)
        rows.append(
            f"<tr class='{klass}'><td>{_escape(label)}</td>{cells}</tr>"
        )

    st.markdown(
        "<div class='table-wrap desktop-table'>"
        "<table class='fresh-table source-table'>"
        "<thead><tr><th>Fuente</th>"
        + headers
        + "</tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )



def _render_compact_predictive_table(view: pd.DataFrame, total_mode: bool = False) -> None:
    """Tabla principal resumida: 8 columnas, todo centrado y con filas amplias."""
    if view.empty:
        st.info("No hay lotes con esos filtros.")
        return

    rows = []
    cards = []
    for _, row in view.iterrows():
        state = str(row.get("estado_predictivo", "-") or "-")
        klass = _state_class(state)
        location_html = ""
        location_text = str(row.get("ubicacion_stock", "") or "").strip()
        if total_mode and location_text:
            location_html = (
                "<div class='product-sub'>"
                + _escape(location_text)
                + "</div>"
            )

        rows.append(
            "<tr>"
            f"<td>{_escape(row.get('codigo'))}</td>"
            f"<td><div class='product-main'>{_escape(row.get('descripcion'))}</div>{location_html}</td>"
            f"<td>{_date(row.get('fecha_vencimiento'))}</td>"
            f"<td>{_fmt(row.get('stock_lote'))}</td>"
            f"<td>{_fmt(row.get('venta_estimada_hasta_vto'))}</td>"
            f"<td class='{klass}'>{_fmt(row.get('bultos_riesgo'))}</td>"
            f"<td>{_date(row.get('agotamiento_estimado'))}</td>"
            f"<td class='{klass}'>{_escape(state)}</td>"
            "</tr>"
        )

        cards.append(
            f"<div class='lot-card compact-card'>"
            "<div class='lot-top'>"
            "<div>"
            f"<div class='lot-code'>Código {_escape(row.get('codigo'))}</div>"
            f"<div class='lot-title'>{_escape(row.get('descripcion'))}</div>"
            + (f"<div class='lot-location'>{_escape(location_text)}</div>" if total_mode and location_text else "")
            + "</div>"
            f"<div class='lot-badge {klass}'>{_escape(state)}</div>"
            "</div>"
            "<div class='lot-meta compact-meta'>"
            f"<div><span>Vence</span><strong>{_date(row.get('fecha_vencimiento'))}</strong></div>"
            f"<div><span>Stock lote</span><strong>{_fmt(row.get('stock_lote'))}</strong></div>"
            f"<div><span>Salida estimada</span><strong>{_fmt(row.get('venta_estimada_hasta_vto'))}</strong></div>"
            f"<div><span>Riesgo</span><strong>{_fmt(row.get('bultos_riesgo'))}</strong></div>"
            f"<div><span>Agota aprox.</span><strong>{_date(row.get('agotamiento_estimado'))}</strong></div>"
            "</div></div>"
        )

    header = (
        "<thead><tr>"
        "<th>Código</th><th>Producto</th><th>Vencimiento</th><th>Stock lote</th>"
        "<th>Salida estimada</th><th>Riesgo</th><th>Agota aprox.</th><th>Estado</th>"
        "</tr></thead>"
    )
    st.markdown(
        "<div class='mobile-lots'>" + "".join(cards) + "</div>"
        "<div class='table-wrap desktop-table'>"
        "<table class='fresh-table compact-pred-table'>"
        + header + "<tbody>" + "".join(rows) + "</tbody></table></div>",
        unsafe_allow_html=True,
    )


def _render_lot_detail(rows: pd.DataFrame) -> None:
    if rows.empty:
        return
    body = []
    for _, row in rows.sort_values("fecha_vencimiento").iterrows():
        state = str(row.get("estado_predictivo", "-") or "-")
        klass = _state_class(state)
        body.append(
            "<tr>"
            f"<td>{_date(row.get('fecha_vencimiento'))}</td>"
            f"<td>{_fmt(row.get('stock_lote'))}</td>"
            f"<td>{_fmt(row.get('venta_normal_estimada_hasta_vto'))}</td>"
            f"<td>{_fmt(row.get('super_estimado_hasta_vto'))}</td>"
            f"<td>{_fmt(row.get('venta_estimada_hasta_vto'))}</td>"
            f"<td class='{klass}'>{_fmt(row.get('bultos_riesgo'))}</td>"
            f"<td>{_pct(row.get('incremento_necesario_pct'))}</td>"
            f"<td>{_escape(row.get('confianza'))}</td>"
            "</tr>"
        )
    st.markdown(
        "<div class='table-wrap desktop-table'>"
        "<table class='fresh-table detail-table'>"
        "<thead><tr><th>Vencimiento</th><th>Stock</th><th>Venta normal</th>"
        "<th>Supermercados</th><th>Salida total</th><th>Riesgo</th>"
        "<th>Incremento nec.</th><th>Confianza</th></tr></thead>"
        "<tbody>" + "".join(body) + "</tbody></table></div>",
        unsafe_allow_html=True,
    )


def _style() -> None:
    st.markdown(
        """
        <style>
        .forecast-kpis {
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:.75rem;
            margin:.8rem 0 1.05rem;
        }
        .forecast-kpi {
            border:1px solid rgba(16,24,40,.10);
            border-top:5px solid #155eef;
            border-radius:10px;
            padding:.85rem .9rem;
            background:#fff;
            box-shadow:0 6px 18px rgba(16,24,40,.05);
        }
        .forecast-kpi.red { border-top-color:#f04438; }
        .forecast-kpi.orange { border-top-color:#f79009; }
        .forecast-kpi.green { border-top-color:#12b76a; }
        .forecast-kpi span {
            display:block;
            color:#475467;
            font-size:.70rem;
            font-weight:900;
            text-transform:uppercase;
            letter-spacing:.02em;
        }
        .forecast-kpi strong {
            display:block;
            color:#101828;
            font-size:1.45rem;
            margin-top:.18rem;
        }
        .forecast-kpi div {
            color:#667085;
            font-size:.76rem;
            margin-top:.10rem;
        }

        .table-wrap { width:100%; overflow-x:auto; }
        table.compact-pred-table {
            width:100%;
            min-width:1080px;
            border-collapse:collapse;
            font-family:Arial,sans-serif;
            font-size:.88rem;
            table-layout:fixed;
        }
        table.compact-pred-table th {
            background:#28549a;
            color:#fff !important;
            border:1px solid #111827;
            padding:.68rem .60rem;
            text-align:center !important;
            vertical-align:middle !important;
            font-weight:900;
            line-height:1.35;
        }
        table.compact-pred-table td {
            background:#fff;
            color:#111827 !important;
            border:1px solid #111827;
            padding:.82rem .68rem;
            height:52px;
            text-align:center !important;
            vertical-align:middle !important;
            font-weight:800;
            line-height:1.45;
            white-space:normal;
            overflow-wrap:anywhere;
        }
        table.compact-pred-table th:nth-child(1), table.compact-pred-table td:nth-child(1) { width:8%; }
        table.compact-pred-table th:nth-child(2), table.compact-pred-table td:nth-child(2) { width:28%; }
        table.compact-pred-table th:nth-child(3), table.compact-pred-table td:nth-child(3) { width:11%; }
        table.compact-pred-table th:nth-child(4), table.compact-pred-table td:nth-child(4) { width:10%; }
        table.compact-pred-table th:nth-child(5), table.compact-pred-table td:nth-child(5) { width:12%; }
        table.compact-pred-table th:nth-child(6), table.compact-pred-table td:nth-child(6) { width:9%; }
        table.compact-pred-table th:nth-child(7), table.compact-pred-table td:nth-child(7) { width:12%; }
        table.compact-pred-table th:nth-child(8), table.compact-pred-table td:nth-child(8) { width:10%; }
        .product-main { line-height:1.35; }
        .product-sub {
            margin-top:.28rem;
            color:#667085;
            font-size:.72rem;
            font-weight:700;
            line-height:1.25;
        }

        table.compact-pred-table td.bad,
        table.detail-table td.bad {
            background:#ffe4e8 !important;
            color:#b42318 !important;
            font-weight:950;
        }
        table.compact-pred-table td.warn,
        table.detail-table td.warn {
            background:#fef3c7 !important;
            color:#b54708 !important;
            font-weight:950;
        }
        table.compact-pred-table td.ok,
        table.detail-table td.ok {
            background:#dcfce7 !important;
            color:#027a48 !important;
            font-weight:950;
        }

        table.source-table, table.detail-table {
            width:100%;
            min-width:760px;
            border-collapse:collapse;
            font-family:Arial,sans-serif;
            font-size:.87rem;
        }
        table.source-table th, table.detail-table th {
            background:#28549a;
            color:#fff !important;
            border:1px solid #111827;
            padding:.58rem .58rem;
            text-align:center !important;
            vertical-align:middle !important;
            font-weight:900;
        }
        table.source-table td, table.detail-table td {
            background:#fff;
            color:#111827 !important;
            border:1px solid #111827;
            padding:.65rem .58rem;
            text-align:center !important;
            vertical-align:middle !important;
            font-weight:800;
            line-height:1.4;
        }
        table.source-table tr.total-source td { background:#eef4ff; font-weight:950; }

        .mobile-lots { display:none; }
        .lot-card {
            border:1px solid rgba(16,24,40,.12);
            border-radius:10px;
            background:#fff;
            padding:.85rem;
            margin:.65rem 0;
            box-shadow:0 5px 14px rgba(16,24,40,.05);
        }
        .lot-top { display:flex; justify-content:space-between; gap:.8rem; align-items:flex-start; }
        .lot-code { color:#667085; font-size:.72rem; font-weight:900; text-transform:uppercase; }
        .lot-title { color:#101828; font-weight:950; margin-top:.15rem; line-height:1.3; }
        .lot-location { color:#667085; font-size:.72rem; margin-top:.2rem; }
        .lot-badge { border-radius:999px; padding:.30rem .55rem; font-size:.70rem; font-weight:950; white-space:nowrap; }
        .lot-badge.bad { background:#ffe4e8; color:#b42318; }
        .lot-badge.warn { background:#fef3c7; color:#b54708; }
        .lot-badge.ok { background:#dcfce7; color:#027a48; }
        .lot-meta { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.55rem; margin-top:.72rem; }
        .lot-meta div { border-top:1px solid #eaecf0; padding-top:.45rem; text-align:center; }
        .lot-meta span { display:block; color:#667085; font-size:.68rem; font-weight:800; }
        .lot-meta strong { display:block; color:#101828; margin-top:.12rem; font-size:.86rem; }

        @media(max-width:900px){
            .forecast-kpis { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .desktop-table { display:none; }
            .mobile-lots { display:block; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _filter_scope(forecast: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    c1, c2 = st.columns([1, 2])
    with c1:
        state = st.selectbox(
            "Estado predictivo",
            ["Todos", "CRITICO", "ACCIONAR", "OK"],
            key=f"{key_prefix}_state",
        )
    with c2:
        search = st.text_input(
            "SKU / producto",
            placeholder="Ej.: 30789 o Pure Gold",
            key=f"{key_prefix}_search",
        )

    view = forecast.copy()
    if state != "Todos":
        view = view[view["estado_predictivo"].eq(state)].copy()
    if search.strip():
        terms = [_clean(x) for x in search.split() if x.strip()]
        searchable = (
            view["codigo"].fillna("").astype(str)
            + " "
            + view["descripcion"].fillna("").astype(str).map(_clean)
        )
        view = view[searchable.apply(lambda x: all(t in x for t in terms))].copy()
    return view


def _render_kpis(view: pd.DataFrame, as_of: date) -> None:
    if view.empty:
        risk_bultos = 0.0
        risk_skus = 0
        critical_skus = 0
    else:
        risk = pd.to_numeric(view["bultos_riesgo"], errors="coerce").fillna(0.0)
        risk_codes = view.loc[risk > 0.05, "codigo"].astype(str)
        critical_codes = view.loc[
            view["estado_predictivo"].fillna("").astype(str).eq("CRITICO"),
            "codigo",
        ].astype(str)
        risk_bultos = float(risk.sum())
        risk_skus = int(risk_codes.nunique())
        critical_skus = int(critical_codes.nunique())

    cards = [
        ("Bultos en riesgo", _fmt(risk_bultos), "proyección", "red"),
        ("SKU con riesgo", str(risk_skus), "requieren seguimiento", "orange"),
        ("Críticos", str(critical_skus), "SKU prioridad alta", "red"),
        ("Fecha de cálculo", as_of.strftime("%d/%m/%Y"), "último día usado", "green"),
    ]
    html_cards = "<div class='forecast-kpis'>"
    for label, value, sub, klass in cards:
        html_cards += (
            f"<div class='forecast-kpi {klass}'>"
            f"<span>{label}</span><strong>{value}</strong><div>{sub}</div></div>"
        )
    html_cards += "</div>"
    st.markdown(html_cards, unsafe_allow_html=True)


def _render_detail_panel(
    forecast_scope: pd.DataFrame,
    visible_view: pd.DataFrame,
    profiles_scope: pd.DataFrame,
    as_of: date,
    key_prefix: str,
) -> None:
    if visible_view.empty:
        return

    label_df = (
        visible_view[["codigo", "descripcion"]]
        .drop_duplicates("codigo")
        .sort_values(["codigo", "descripcion"])
    )
    labels = {
        f"{str(r.codigo)} · {str(r.descripcion)}": str(r.codigo)
        for r in label_df.itertuples(index=False)
    }
    if not labels:
        return

    with st.expander("Ver detalle de un SKU"):
        selected_label = st.selectbox(
            "Producto",
            list(labels.keys()),
            key=f"{key_prefix}_detail_sku",
        )
        selected_code = labels[selected_label]
        sku_rows = forecast_scope[
            forecast_scope["codigo"].astype(str).eq(str(selected_code))
        ].copy()
        sku_norm = str(selected_code).lstrip("0")
        pview = profiles_scope[
            profiles_scope["sku"].astype(str).str.lstrip("0").eq(sku_norm)
        ].copy()

        if not pview.empty:
            prow = pview.iloc[0]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Venta normal / semana", f"{_fmt(prow.get('normal_weekly_bultos', 0))} bultos")
            m2.metric("Supermercados / semana", f"{_fmt(prow.get('super_weekly_bultos', 0))} bultos")
            m3.metric("Salida total / semana", f"{_fmt(prow.get('weekly_bultos', 0))} bultos")
            m4.metric("Salida mensual estimada", f"{_fmt(prow.get('total_monthly_bultos', 0))} bultos")

            cutoff = (
                pd.Timestamp(as_of) + pd.DateOffset(months=2)
            ).strftime("%d/%m/%Y")
            st.caption(
                f"Supermercados se incluye en la proyección hasta {cutoff}. "
                "Desde el día siguiente hasta el vencimiento se proyecta sólo venta normal."
            )
            st.markdown("**Distribución estimada por día**")
            _render_source_breakdown(prow)

        st.markdown("**Detalle de los vencimientos analizados**")
        _render_lot_detail(sku_rows)


def _render_scope_workspace(
    forecast_scope: pd.DataFrame,
    profiles_scope: pd.DataFrame,
    as_of: date,
    key_prefix: str,
    total_mode: bool = False,
) -> None:
    if forecast_scope.empty:
        st.info("No hay lotes dentro del horizonte para esta vista.")
        return

    view = _filter_scope(forecast_scope, key_prefix)
    _render_kpis(view, as_of)

    if view.empty:
        st.info("No hay lotes con esos filtros.")
        return

    order = {"CRITICO": 0, "ACCIONAR": 1, "OK": 2}
    view = view.copy()
    view["_orden"] = view["estado_predictivo"].map(order).fillna(9)
    view = view.sort_values(
        ["_orden", "fecha_vencimiento", "bultos_riesgo"],
        ascending=[True, True, False],
    ).drop(columns="_orden")

    _render_compact_predictive_table(view, total_mode=total_mode)
    _render_detail_panel(
        forecast_scope=forecast_scope,
        visible_view=view,
        profiles_scope=profiles_scope,
        as_of=as_of,
        key_prefix=key_prefix,
    )

def render_predictive_section(
    products: pd.DataFrame,
    lots: pd.DataFrame,
    drive_url: str,
) -> None:
    """Frescura Predictiva v11: Trelew, Madryn y TOTAL DDV con cálculo v9 validado."""
    _style()
    hist_file = _history_file()
    super_hist_file = _supermarket_history_file()

    icon_path = sales_app.PROJECT_ROOT / "mini_mentalista.png"
    h1, h2 = st.columns([0.09, 0.91], vertical_alignment="center")
    with h1:
        if icon_path.exists():
            st.image(str(icon_path), width=64)
        else:
            st.markdown("### 🔮")
    with h2:
        st.markdown("## Frescura predictiva")

    st.caption(
        "Cálculo validado: 3 meses completos ponderados 20% / 30% / 50%, "
        "blend 70% histórico + 30% mes actual, FEFO, máximo 2 vencimientos dentro de 120 días. "
        "Supermercados se proyecta sólo hasta +2 meses calendario desde la fecha de cálculo; "
        "después del corte se usa únicamente venta normal."
    )

    if hist_file is None:
        st.error("Falta `historico_frescura_bultos.csv.gz` en la raíz del repositorio.")
        return
    if products.empty or lots.empty:
        st.info("No hay stock/lotes suficientes para calcular el pronóstico.")
        return

    try:
        refresh_slot = int(time.time() // 1800)
        customer_text, sales_text, supermarket_text = _operational_sources(drive_url, refresh_slot)
        customer_path = Path(customer_text)
        sales_path = Path(sales_text)
        supermarket_path = Path(supermarket_text) if supermarket_text else None

        hs = hist_file.stat()
        history = _history(str(hist_file), hs.st_mtime_ns, hs.st_size)

        wanted = tuple(sorted(
            products["codigo"].dropna().astype(str)
            .str.replace(r"\.0$", "", regex=True)
            .str.lstrip("0").unique()
        ))

        ss = sales_path.stat()
        cs = customer_path.stat()
        current = _current(
            str(sales_path), ss.st_mtime_ns, ss.st_size,
            str(customer_path), cs.st_mtime_ns, cs.st_size,
            wanted,
        )
        normal_daily = combine_history(history, current)
        if normal_daily.empty:
            st.warning("No hay historial de venta normal utilizable.")
            return

        if super_hist_file is not None:
            sh = super_hist_file.stat()
            supermarket_history = _history(str(super_hist_file), sh.st_mtime_ns, sh.st_size)
        else:
            supermarket_history = pd.DataFrame(columns=["date", "loc", "sku", "bultos"])

        if supermarket_path is not None and supermarket_path.exists():
            rs = supermarket_path.stat()
            supermarket_live = _supermarket_current(
                str(supermarket_path), rs.st_mtime_ns, rs.st_size, wanted
            )
            supermarket_daily = combine_history(supermarket_history, supermarket_live)
        else:
            supermarket_daily = supermarket_history

        source_dates = []
        if not current.empty:
            source_dates.append(current["date"].max().date())
        if not supermarket_daily.empty:
            source_dates.append(supermarket_daily["date"].max().date())
        if not source_dates:
            source_dates.append(normal_daily["date"].max().date())
        local_today = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires").date()
        as_of = min(local_today, max(source_dates))

        # Vista DDV unificada: misma lógica exacta de v9.
        normal_ddv = build_weekday_profiles(
            normal_daily, products, as_of, recent_occurrences=2, scope="DDV"
        )
        super_ddv = build_supermarket_weekday_profiles(
            supermarket_daily, products, as_of, recent_occurrences=8, scope="DDV"
        )
        profiles_ddv = combine_normal_and_supermarket_profiles(normal_ddv, super_ddv, as_of)
        forecast_ddv = simulate_fefo(lots, profiles_ddv, as_of, scope="DDV")

        # Vista por base: mismo cálculo v9, pero historia, stock y FEFO separados por locación.
        normal_base = build_weekday_profiles(
            normal_daily, products, as_of, recent_occurrences=2, scope="BASE"
        )
        super_base = build_supermarket_weekday_profiles(
            supermarket_daily, products, as_of, recent_occurrences=8, scope="BASE"
        )
        profiles_base = combine_normal_and_supermarket_profiles(normal_base, super_base, as_of)
        forecast_base = simulate_fefo(lots, profiles_base, as_of, scope="BASE")

    except Exception as exc:
        st.error(f"No pude calcular Frescura Predictiva: {type(exc).__name__}: {exc}")
        with st.expander("Ver detalle técnico"):
            st.code(traceback.format_exc())
        return

    if forecast_ddv.empty and forecast_base.empty:
        st.info("No se generaron lotes predictivos.")
        return

    trelew_forecast = forecast_base[
        forecast_base["ciudad"].astype(str).str.upper().eq("TRELEW")
    ].copy() if not forecast_base.empty else pd.DataFrame()
    madryn_forecast = forecast_base[
        forecast_base["ciudad"].astype(str).str.upper().eq("MADRYN")
    ].copy() if not forecast_base.empty else pd.DataFrame()

    trelew_profiles = profiles_base[
        profiles_base["loc"].astype(str).str.upper().eq("TRELEW")
    ].copy() if not profiles_base.empty else pd.DataFrame()
    madryn_profiles = profiles_base[
        profiles_base["loc"].astype(str).str.upper().eq("MADRYN")
    ].copy() if not profiles_base.empty else pd.DataFrame()

    trelew_tab, madryn_tab, ddv_tab = st.tabs(["TRELEW", "MADRYN", "TOTAL DDV"])

    with trelew_tab:
        st.caption(
            "Vista física Trelew: sólo la demanda y el stock de Trelew consumen sus lotes."
        )
        _render_scope_workspace(
            trelew_forecast,
            trelew_profiles,
            as_of,
            key_prefix="pred_trelew",
            total_mode=False,
        )

    with madryn_tab:
        st.caption(
            "Vista física Madryn: sólo la demanda y el stock de Madryn consumen sus lotes."
        )
        _render_scope_workspace(
            madryn_forecast,
            madryn_profiles,
            as_of,
            key_prefix="pred_madryn",
            total_mode=False,
        )

    with ddv_tab:
        st.caption(
            "Vista consolidada: Trelew + Madryn forman un único stock por SKU. "
            "El FEFO consume primero el vencimiento más próximo entre ambas bases."
        )
        _render_scope_workspace(
            forecast_ddv,
            profiles_ddv,
            as_of,
            key_prefix="pred_ddv_total",
            total_mode=True,
        )

    with st.expander("Cómo leer el cálculo"):
        st.markdown(
            """
**Tabla principal:** muestra sólo Código, Producto, Vencimiento, Stock lote, Salida estimada, Riesgo, Agota aprox. y Estado.

**Trelew / Madryn:** cálculo independiente por base física. La demanda de una base no consume stock de la otra.

**TOTAL DDV:** Trelew + Madryn se consolidan por SKU. El stock se consume por FEFO usando la demanda total de ambas bases.

**Horizonte:** máximo **2 vencimientos próximos** por SKU y sólo dentro de **120 días** desde la fecha de cálculo.

**Ritmo:** 3 meses completos previos con pesos **20% / 30% / 50%**, combinados **70% histórico + 30% ritmo del mes actual**.

**Supermercados:** se proyectan como salida de stock sólo hasta **+2 meses calendario** desde la fecha de cálculo (ej.: 10/09 → 10/11). Desde el día siguiente al corte hasta el vencimiento, se proyecta únicamente **venta normal**.

**Detalle del SKU:** despliega el ritmo semanal normal, supermercados, salida total, distribución Lun–Sáb y el detalle completo de los vencimientos analizados.

Se excluye el CD de S.A. Importadora y Exportadora de la Patagonia identificado como cliente 999 / RUTA 25 PQUE.INDUSTRIAL. Los anulados no entran y las devoluciones restan bultos.
            """
        )
