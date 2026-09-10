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


def _render_predictive_html_table(table: pd.DataFrame, scope_label: str = "DDV") -> None:
    """Tabla predictiva con la misma estética visual del tablero histórico."""
    if table.empty:
        st.info("No hay lotes con esos filtros.")
        return

    rows = []
    cards = []

    for _, row in table.iterrows():
        state = str(row["Estado"] or "-")
        klass = _state_class(state)
        card_class = "bad-card" if klass == "bad" else "warn-card" if klass == "warn" else ""

        rows.append(
            "<tr>"
            f"<td>{_escape(row['Código'])}</td>"
            f"<td>{_escape(row['Producto'])}</td>"
            f"<td>{_escape(row['Lote'])}</td>"
            f"<td>{_escape(row['Ubicación'])}</td>"
            f"<td>{_fmt(row['Stock lote'])}</td>"
            f"<td>{_date(row['Vencimiento'])}</td>"
            f"<td>{_fmt(row['Venta estimada hasta vto.'])}</td>"
            f"<td class='{klass}'>{_fmt(row['Bultos en riesgo'])}</td>"
            f"<td>{_date(row['Agotamiento estimado'])}</td>"
            f"<td class='{klass}'>{_fmt(row['Margen vs vto.'], 0)}</td>"
            f"<td>{_escape(row['Incremento necesario'])}</td>"
            f"<td>{_fmt(row['Días stock dinámicos'], 0)}</td>"
            f"<td>{_escape(row['Confianza'])}</td>"
            f"<td class='{klass}'>{_escape(state)}</td>"
            "</tr>"
        )

        cards.append(
            f"<div class='lot-card {card_class}'>"
            "<div class='lot-top'>"
            "<div>"
            f"<div class='lot-code'>{_escape(scope_label)} · Código {_escape(row['Código'])} · Lote {_escape(row['Lote'])}</div>"
            f"<div class='lot-title'>{_escape(row['Producto'])}</div>"
            "</div>"
            f"<div class='lot-badge {klass}'>{_escape(state)}</div>"
            "</div>"
            "<div class='lot-meta'>"
            f"<div><span>Ubicación</span><strong>{_escape(row['Ubicación'])}</strong></div>"
            f"<div><span>Vence</span><strong>{_date(row['Vencimiento'])}</strong></div>"
            f"<div><span>Stock lote</span><strong>{_fmt(row['Stock lote'])}</strong></div>"
            f"<div><span>Venta estimada</span><strong>{_fmt(row['Venta estimada hasta vto.'])}</strong></div>"
            f"<div><span>Bultos en riesgo</span><strong>{_fmt(row['Bultos en riesgo'])}</strong></div>"
            f"<div><span>Agotamiento</span><strong>{_date(row['Agotamiento estimado'])}</strong></div>"
            f"<div><span>Margen vs vto.</span><strong>{_fmt(row['Margen vs vto.'], 0)} días</strong></div>"
            f"<div><span>Incremento necesario</span><strong>{_escape(row['Incremento necesario'])}</strong></div>"
            f"<div><span>Confianza</span><strong>{_escape(row['Confianza'])}</strong></div>"
            "</div>"
            "</div>"
        )

    header = (
        "<thead><tr>"
        "<th>Código</th><th>Producto</th><th>Lote</th><th>Ubicación</th>"
        "<th>Stock lote</th><th>Vencimiento</th><th>Venta estimada hasta vto.</th>"
        "<th>Bultos en riesgo</th><th>Agotamiento estimado</th>"
        "<th>Margen vs vto.</th><th>Incremento necesario</th>"
        "<th>Días stock dinámicos</th><th>Confianza</th><th>Estado</th>"
        "</tr></thead>"
    )

    st.markdown(
        "<div class='mobile-lots'>" + "".join(cards) + "</div>"
        "<div class='table-wrap desktop-table'>"
        "<table class='fresh-table pred-table'>"
        + header
        + "<tbody>"
        + "".join(rows)
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )


def _style():
    st.markdown(
        """
        <style>
        .forecast-box {
            border:1px solid rgba(16,24,40,.14);
            border-radius:8px;
            padding:1rem;
            background:#ffffff;
            box-shadow:0 12px 28px rgba(16,24,40,.08);
            margin:.5rem 0 1rem;
        }
        .forecast-kpis {
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:.7rem;
            margin:.7rem 0 1rem;
        }
        .forecast-kpi {
            border:1px solid rgba(16,24,40,.10);
            border-top:5px solid #155eef;
            border-radius:8px;
            padding:.8rem;
            background:#fff;
        }
        .forecast-kpi.red { border-top-color:#f04438; }
        .forecast-kpi.orange { border-top-color:#f79009; }
        .forecast-kpi.green { border-top-color:#12b76a; }
        .forecast-kpi span {
            display:block;
            color:#475467;
            font-size:.7rem;
            font-weight:900;
            text-transform:uppercase;
        }
        .forecast-kpi strong {
            display:block;
            color:#101828;
            font-size:1.45rem;
            margin-top:.2rem;
        }

        /* Tabla predictiva: misma familia visual que Lotes por vencimiento */
        table.pred-table {
            min-width: 1780px;
            font-family: Arial, sans-serif;
            font-size: .86rem;
        }
        table.pred-table th {
            background: #28549a;
            color: #ffffff !important;
            border: 1px solid #111827;
            padding: .52rem .55rem;
            text-align: center;
            font-weight: 900;
            white-space: nowrap;
        }
        table.pred-table td {
            background: #ffffff;
            color: #111827 !important;
            border: 1px solid #111827;
            padding: .46rem .55rem;
            text-align: right;
            font-weight: 800;
            white-space: nowrap;
        }
        table.pred-table td:nth-child(1),
        table.pred-table td:nth-child(2),
        table.pred-table td:nth-child(3) {
            text-align: left;
        }
        table.pred-table td:nth-child(2) {
            text-align: center;
        }
        table.pred-table td:nth-child(3) {
            white-space: normal;
            min-width: 285px;
        }
        table.pred-table td.bad {
            background: #ffe4e8 !important;
            color: #b42318 !important;
            font-weight: 950;
        }
        table.pred-table td.warn {
            background: #fef3c7 !important;
            color: #b54708 !important;
            font-weight: 950;
        }
        table.pred-table td.ok {
            background: #dcfce7 !important;
            color: #027a48 !important;
            font-weight: 950;
        }

        table.source-table {
            min-width: 760px;
            font-family: Arial, sans-serif;
            font-size: .88rem;
        }
        table.source-table th {
            background: #28549a;
            color: #ffffff !important;
            border: 1px solid #111827;
            padding: .5rem .55rem;
            text-align: center;
            font-weight: 900;
        }
        table.source-table td {
            background: #ffffff;
            color: #111827 !important;
            border: 1px solid #111827;
            padding: .48rem .55rem;
            text-align: right;
            font-weight: 800;
        }
        table.source-table td:first-child {
            text-align: left;
            font-weight: 900;
        }
        table.source-table tr.total-source td {
            background: #eef4ff;
            font-weight: 950;
        }

        @media(max-width:760px){
            .forecast-kpis { grid-template-columns:repeat(2,minmax(0,1fr)); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_forecast_workspace(
    forecast: pd.DataFrame,
    profiles: pd.DataFrame,
    as_of: date,
    mode: str,
) -> None:
    """Dibuja una vista completa manteniendo la estética v6/v9."""
    is_base = mode.upper() == "BASE"
    key_prefix = "pred_base" if is_base else "pred_ddv"

    c1, c2, c3 = st.columns([1, 1, 2])
    if is_base:
        options = [x for x in ["Trelew", "Madryn"] if x in set(forecast["ciudad"].astype(str))]
        with c1:
            selected_locations = st.multiselect(
                "Base",
                options,
                default=options,
                key=f"{key_prefix}_location",
            )
    else:
        options = ["Trelew", "Madryn"]
        with c1:
            selected_locations = st.multiselect(
                "Stock en",
                options,
                default=options,
                key=f"{key_prefix}_location",
            )

    with c2:
        state = st.selectbox(
            "Estado predictivo",
            ["Todos", "CRITICO", "ACCIONAR", "OK"],
            key=f"{key_prefix}_state",
        )
    with c3:
        search = st.text_input(
            "SKU / producto",
            placeholder="Ej.: 30645 o Pepsi",
            key=f"{key_prefix}_search",
        )

    view = forecast.copy()
    if selected_locations:
        if is_base:
            view = view[view["ciudad"].isin(selected_locations)].copy()
        else:
            loc_pattern = "|".join(selected_locations)
            view = view[
                view["ubicacion_stock"].fillna("").str.contains(
                    loc_pattern, case=False, regex=True
                )
            ].copy()
    else:
        view = view.iloc[0:0].copy()

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

    summary = forecast_summary(view)
    cards = [
        ("Bultos en riesgo", _fmt(summary["risk_bultos"]), "proyección", "red"),
        ("Lotes con riesgo", str(summary["risk_lots"]), "a prevenir", "orange"),
        ("Críticos", str(summary["critical_lots"]), "prioridad alta", "red"),
        ("Venta al", as_of.strftime("%d/%m/%Y"), "último día usado", "green"),
    ]
    html_cards = "<div class='forecast-kpis'>"
    for label, value, sub, klass in cards:
        html_cards += (
            f"<div class='forecast-kpi {klass}'>"
            f"<span>{label}</span><strong>{value}</strong><div>{sub}</div></div>"
        )
    html_cards += "</div>"
    st.markdown(html_cards, unsafe_allow_html=True)

    pred_tab, rhythm_tab = st.tabs(["Riesgo proyectado", "Salida estimada por día"])

    with pred_tab:
        if view.empty:
            st.info("No hay lotes con esos filtros.")
        else:
            table = view[[
                "codigo", "descripcion", "lote_nro", "ubicacion_stock",
                "stock_lote", "fecha_vencimiento",
                "venta_estimada_hasta_vto", "bultos_riesgo",
                "agotamiento_estimado", "margen_frescura_dias",
                "incremento_necesario_pct", "dias_stock_dinamicos",
                "confianza", "estado_predictivo",
            ]].copy()

            table = table.rename(columns={
                "codigo": "Código",
                "descripcion": "Producto",
                "lote_nro": "Lote",
                "ubicacion_stock": "Ubicación",
                "stock_lote": "Stock lote",
                "fecha_vencimiento": "Vencimiento",
                "venta_estimada_hasta_vto": "Venta estimada hasta vto.",
                "bultos_riesgo": "Bultos en riesgo",
                "agotamiento_estimado": "Agotamiento estimado",
                "margen_frescura_dias": "Margen vs vto.",
                "incremento_necesario_pct": "Incremento necesario",
                "dias_stock_dinamicos": "Días stock dinámicos",
                "confianza": "Confianza",
                "estado_predictivo": "Estado",
            })

            for col in [
                "Stock lote", "Venta estimada hasta vto.",
                "Bultos en riesgo", "Días stock dinámicos",
            ]:
                table[col] = pd.to_numeric(table[col], errors="coerce").round(1)

            table["Incremento necesario"] = table["Incremento necesario"].map(_pct)
            order = {"CRITICO": 0, "ACCIONAR": 1, "OK": 2}
            table["_orden"] = table["Estado"].map(order).fillna(9)
            table = table.sort_values(
                ["_orden", "Vencimiento", "Bultos en riesgo"],
                ascending=[True, True, False],
            ).drop(columns="_orden")

            _render_predictive_html_table(
                table,
                scope_label="BASE" if is_base else "DDV",
            )

    with rhythm_tab:
        if is_base:
            selected_upper = {x.upper() for x in selected_locations}
            profile_keys = set(
                zip(
                    view["ciudad"].astype(str).str.upper(),
                    view["codigo"].astype(str).str.lstrip("0"),
                )
            )
            pview = profiles[
                profiles.apply(
                    lambda r: (
                        str(r["loc"]).upper(),
                        str(r["sku"]).lstrip("0"),
                    ) in profile_keys,
                    axis=1,
                )
            ].copy()
        else:
            profile_keys = set(view["codigo"].astype(str).str.lstrip("0"))
            pview = profiles[
                profiles["sku"].astype(str).str.lstrip("0").isin(profile_keys)
            ].copy()

        if pview.empty:
            st.info("No hay perfiles para esos filtros.")
        else:
            if is_base:
                pview["selector"] = (
                    pview["sku"].astype(str)
                    + " · " + pview["description"].astype(str)
                    + " · " + pview["loc"].astype(str).str.title()
                )
            else:
                pview["selector"] = (
                    pview["sku"].astype(str)
                    + " · " + pview["description"].astype(str)
                )

            chosen = st.selectbox(
                "Auditar SKU",
                pview.sort_values("selector")["selector"].tolist(),
                key=f"{key_prefix}_sku_audit",
            )
            row = pview[pview["selector"].eq(chosen)].iloc[0]

            st.markdown("**Salida total estimada por día**")
            day_cols = st.columns(6)
            for i, (name, field) in enumerate(zip(DAY_NAMES, DAY_COLS)):
                day_cols[i].metric(name, f"{_fmt(row[field])} bultos")

            _render_source_breakdown(row)
            st.info(
                f"Venta normal semanal: {_fmt(row.get('normal_weekly_bultos', 0))} bultos · "
                f"Supermercados semanal: {_fmt(row.get('super_weekly_bultos', 0))} bultos · "
                f"Salida total semanal: {_fmt(row['weekly_bultos'])} bultos · "
                f"Salida mensual estimada: {_fmt(row.get('total_monthly_bultos', 0))} bultos · "
                f"Días de stock dinámicos: {_fmt(row['dynamic_coverage_days'], 0)} · "
                f"Confianza de datos: {row['confidence']}"
            )


def render_predictive_section(
    products: pd.DataFrame,
    lots: pd.DataFrame,
    drive_url: str,
) -> None:
    """Frescura Predictiva v10: vista por base + vista DDV unificada."""
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
        "Cálculo v9: ritmo de 3 meses completos ponderados 20% / 30% / 50%, "
        "blend 70% histórico + 30% mes actual, FEFO, máximo 2 vencimientos dentro de 120 días. "
        "Supermercados se proyecta sólo hasta +2 meses calendario desde la fecha de cálculo; "
        "después del corte se usa únicamente venta normal. Podés verlo por base o con Trelew + Madryn unificados."
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

    base_tab, ddv_tab = st.tabs(["Por base", "Trelew + Madryn · DDV"])

    with base_tab:
        st.caption(
            "Vista física: Trelew y Madryn se calculan por separado. Sirve para detectar en qué base está el riesgo."
        )
        if forecast_base.empty:
            st.info("No hay lotes para la vista por base.")
        else:
            _render_forecast_workspace(forecast_base, profiles_base, as_of, mode="BASE")

    with ddv_tab:
        st.caption(
            "Vista consolidada: Trelew + Madryn forman un único stock por SKU y el FEFO puede absorber demanda entre bases."
        )
        if forecast_ddv.empty:
            st.info("No hay lotes para la vista DDV unificada.")
        else:
            _render_forecast_workspace(forecast_ddv, profiles_ddv, as_of, mode="DDV")

    with st.expander("Cómo leer el cálculo"):
        st.markdown(
            """
**Bultos en riesgo:** stock que seguiría en el lote al llegar su vencimiento.

**Vista Por base:** aplica el cálculo v9 a Trelew y Madryn por separado; la demanda de una base no consume stock de la otra.

**Vista DDV:** aplica exactamente el mismo cálculo v9, pero Trelew + Madryn forman un único stock por SKU y se consume el vencimiento más próximo entre ambas bases.

**Horizonte:** máximo **2 vencimientos próximos** por SKU y sólo dentro de **120 días**.

**Ritmo:** 3 meses completos previos con pesos **20% / 30% / 50%**, combinados **70% histórico + 30% ritmo del mes actual**.

**Supermercados:** se proyectan como salida de stock sólo hasta **+2 meses calendario** desde la fecha de cálculo (ej.: 10/09 → 10/11). Después del corte, hasta el vencimiento, sólo se proyecta **venta normal**.

Se excluye el CD de S.A. Importadora y Exportadora de la Patagonia identificado como cliente 999 / RUTA 25 PQUE.INDUSTRIAL. Los anulados no entran y las devoluciones restan bultos.
            """
        )
