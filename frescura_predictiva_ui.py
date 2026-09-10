from __future__ import annotations

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
    combine_history,
    forecast_summary,
    load_current_bultos,
    load_history_base,
    simulate_fefo,
)


RUNTIME_DIR = sales_app.PROJECT_ROOT / ".cloud_data" / "frescura_predictiva"
HISTORY_CANDIDATES = [
    sales_app.PROJECT_ROOT / "historico_frescura_bultos.csv.gz",
    sales_app.PROJECT_ROOT / "historico_frescura_bultos.csv",
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
    return matches[-1] if matches else None


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

    if customer is None:
        raise RuntimeError("No encontré PlantillaClientesAR en Drive.")
    if current is None:
        raise RuntimeError("No encontré ventadiaria bultos.txt en Drive.")

    customer_path = _download(customer, RUNTIME_DIR)
    current_path = _download(current, RUNTIME_DIR)

    return str(customer_path), str(current_path)


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
        @media(max-width:760px){
            .forecast-kpis { grid-template-columns:repeat(2,minmax(0,1fr)); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_predictive_section(
    products: pd.DataFrame,
    lots: pd.DataFrame,
    drive_url: str,
) -> None:
    """
    Agrega el análisis predictivo al dashboard actual sin modificar
    la lógica vieja de Política de Stock.
    """
    _style()
    hist_file = _history_file()

    st.markdown("## 🔮 Frescura predictiva")
    st.caption(
        "La proyección usa venta real por día de semana y FEFO. "
        "La Política de Stock actual queda como referencia, pero ya no gobierna este semáforo."
    )

    if hist_file is None:
        st.error(
            "Falta `historico_frescura_bultos.csv.gz` en la raíz del repositorio."
        )
        return

    if products.empty or lots.empty:
        st.info("No hay stock/lotes suficientes para calcular el pronóstico.")
        return

    try:
        # Actualización automática cada 30 minutos.
        refresh_slot = int(time.time() // 1800)
        customer_text, sales_text = _operational_sources(
            drive_url, refresh_slot
        )
        customer_path = Path(customer_text)
        sales_path = Path(sales_text)

        hs = hist_file.stat()
        history = _history(str(hist_file), hs.st_mtime_ns, hs.st_size)

        wanted = tuple(
            sorted(
                products["codigo"]
                .dropna()
                .astype(str)
                .str.replace(r"\.0$", "", regex=True)
                .str.lstrip("0")
                .unique()
            )
        )

        ss = sales_path.stat()
        cs = customer_path.stat()
        current = _current(
            str(sales_path), ss.st_mtime_ns, ss.st_size,
            str(customer_path), cs.st_mtime_ns, cs.st_size,
            wanted,
        )

        daily = combine_history(history, current)
        if daily.empty:
            st.warning("No hay historial de ventas utilizable.")
            return

        if current.empty:
            as_of = min(date.today(), daily["date"].max().date())
        else:
            as_of = min(date.today(), current["date"].max().date())

        profiles = build_weekday_profiles(
            daily=daily,
            products=products,
            as_of=as_of,
            recent_occurrences=2,
        )
        forecast = simulate_fefo(
            lots=lots,
            profiles=profiles,
            as_of=as_of,
        )
    except Exception as exc:
        st.error(f"No pude calcular Frescura Predictiva: {type(exc).__name__}: {exc}")
        with st.expander("Ver detalle técnico"):
            st.code(traceback.format_exc())
        return

    if forecast.empty:
        st.info("No se generaron lotes predictivos.")
        return

    # Filtros propios: no dependen del estado viejo.
    c1, c2, c3 = st.columns([1, 1, 2])
    cities = sorted(forecast["ciudad"].dropna().astype(str).unique().tolist())
    with c1:
        city = st.multiselect(
            "Base",
            cities,
            default=cities,
            key="pred_city",
        )
    with c2:
        state = st.selectbox(
            "Estado predictivo",
            ["Todos", "CRITICO", "ACCIONAR", "OK"],
            key="pred_state",
        )
    with c3:
        search = st.text_input(
            "SKU / producto",
            placeholder="Ej.: 30645 o Pepsi",
            key="pred_search",
        )

    view = forecast[forecast["ciudad"].isin(city)].copy()
    if state != "Todos":
        view = view[view["estado_predictivo"].eq(state)].copy()
    if search.strip():
        terms = [_clean(x) for x in search.split() if x.strip()]
        text = (
            view["codigo"].fillna("").astype(str)
            + " "
            + view["descripcion"].fillna("").astype(str).map(_clean)
        )
        view = view[text.apply(lambda x: all(t in x for t in terms))].copy()

    summary = forecast_summary(view)
    cards = [
        ("Bultos en riesgo", _fmt(summary["risk_bultos"]), "proyección", "red"),
        ("Lotes con riesgo", str(summary["risk_lots"]), "a prevenir", "orange"),
        ("Críticos", str(summary["critical_lots"]), "prioridad alta", "red"),
        ("Venta al", as_of.strftime("%d/%m/%Y"), "último día usado", "green"),
    ]
    html = "<div class='forecast-kpis'>"
    for label, value, sub, klass in cards:
        html += (
            f"<div class='forecast-kpi {klass}'>"
            f"<span>{label}</span><strong>{value}</strong><div>{sub}</div></div>"
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)

    pred_tab, rhythm_tab = st.tabs(
        ["Riesgo proyectado", "Venta estimada por día"]
    )

    with pred_tab:
        if view.empty:
            st.info("No hay lotes con esos filtros.")
        else:
            table = view[[
                "ciudad", "codigo", "descripcion", "lote_nro",
                "stock_lote", "fecha_vencimiento",
                "venta_estimada_hasta_vto", "bultos_riesgo",
                "agotamiento_estimado", "margen_frescura_dias",
                "incremento_necesario_pct", "dias_stock_dinamicos",
                "confianza", "estado_predictivo",
            ]].copy()

            table = table.rename(columns={
                "ciudad": "Base",
                "codigo": "Código",
                "descripcion": "Producto",
                "lote_nro": "Lote",
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
                table[col] = pd.to_numeric(
                    table[col], errors="coerce"
                ).round(1)

            table["Incremento necesario"] = table[
                "Incremento necesario"
            ].map(_pct)

            order = {"CRITICO": 0, "ACCIONAR": 1, "OK": 2}
            table["_orden"] = table["Estado"].map(order).fillna(9)
            table = table.sort_values(
                ["_orden", "Vencimiento", "Bultos en riesgo"],
                ascending=[True, True, False],
            ).drop(columns="_orden")

            st.dataframe(
                table,
                hide_index=True,
                width="stretch",
                height=min(700, 55 + len(table) * 35),
                column_config={
                    "Vencimiento": st.column_config.DateColumn(
                        format="DD/MM/YYYY"
                    ),
                    "Agotamiento estimado": st.column_config.DateColumn(
                        format="DD/MM/YYYY"
                    ),
                },
            )

    with rhythm_tab:
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

        if pview.empty:
            st.info("No hay perfiles para esos filtros.")
        else:
            pview["selector"] = (
                pview["sku"].astype(str)
                + " · "
                + pview["description"].astype(str)
                + " · "
                + pview["loc"].astype(str)
            )
            chosen = st.selectbox(
                "Auditar SKU",
                pview.sort_values("selector")["selector"].tolist(),
                key="pred_sku_audit",
            )
            row = pview[pview["selector"].eq(chosen)].iloc[0]

            day_cols = st.columns(6)
            for i, (name, field) in enumerate(zip(DAY_NAMES, DAY_COLS)):
                day_cols[i].metric(
                    name,
                    f"{_fmt(row[field])} bultos",
                )

            st.info(
                f"Venta semanal estimada: {_fmt(row['weekly_bultos'])} bultos · "
                f"Días de stock dinámicos: {_fmt(row['dynamic_coverage_days'], 0)} · "
                f"Confianza: {row['confidence']} · "
                f"Historia propia desde: {row['history_start'] or 'sin historial'}"
            )

    with st.expander("Cómo leer el nuevo cálculo"):
        st.markdown(
            """
**Bultos en riesgo:** stock que, al ritmo natural proyectado, seguiría en el lote al llegar su vencimiento.

**Agotamiento estimado:** día en que ese stock se terminaría si mantuviera el ritmo actual.

**Margen vs vto.:** positivo = se agotaría antes de vencer; negativo = se agotaría después.

**Incremento necesario:** cuánto debería acelerarse la salida natural para consumir el lote antes de vencer.

El algoritmo distribuye la venta futura usando **FEFO**: primero consume el lote con vencimiento más próximo.
            """
        )
