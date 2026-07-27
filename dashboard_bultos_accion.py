from __future__ import annotations

import io
import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

import app as sales_app


APP_TITLE = "Control bultos Core / Value"
DEFAULT_DRIVE_URL = "https://drive.google.com/drive/folders/1cukgXLUaPsEDK_yD7tSwgaBFZAbiDUot?usp=drive_link"
TOPES_CANAL = {
    "K+T": 200.0,
    "AUTOSERVICIO": 500.0,
    "AS": 500.0,
}
SEGMENTOS_ACCION = {
    "CVZA CORE": "CORE",
    "CVZA VALUE": "VALUE",
}


def inject_style() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #101828;
            --muted: #475467;
            --line: #d0d5dd;
            --blue: #1463ff;
            --cyan: #00a7c8;
            --green: #12b76a;
            --orange: #f79009;
            --red: #f04438;
            --bg: #eef4ff;
        }
        .stApp {
            background:
                radial-gradient(circle at top right, rgba(0,167,200,.18), transparent 28rem),
                linear-gradient(180deg, #f8fbff 0%, var(--bg) 100%);
            color: var(--ink);
        }
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #172554 100%);
        }
        section[data-testid="stSidebar"] * { color: #f8fafc !important; }
        .hero {
            background: linear-gradient(135deg, #102a6b 0%, #1463ff 54%, #00a7c8 100%);
            color: white;
            padding: 1.5rem 1.7rem;
            border-radius: 8px;
            box-shadow: 0 18px 45px rgba(20,99,255,.22);
            margin-bottom: 1.2rem;
        }
        .hero h1 { margin: 0; font-size: 2rem; color: white; }
        .hero p { margin: .65rem 0 0; color: white; font-weight: 600; }
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: .85rem;
            margin: .9rem 0 1.2rem;
        }
        .kpi-card {
            background: #fff;
            border: 1px solid rgba(16,24,40,.08);
            border-top: 5px solid var(--blue);
            border-radius: 8px;
            padding: 1rem 1.05rem;
            box-shadow: 0 14px 35px rgba(16,24,40,.10);
        }
        .kpi-card.green { border-top-color: var(--green); }
        .kpi-card.orange { border-top-color: var(--orange); }
        .kpi-card.red { border-top-color: var(--red); }
        .kpi-label {
            color: var(--muted);
            font-size: .78rem;
            font-weight: 800;
            letter-spacing: .05em;
            text-transform: uppercase;
        }
        .kpi-value {
            color: var(--ink);
            font-size: 2rem;
            font-weight: 900;
            margin-top: .25rem;
        }
        .kpi-sub { color: var(--muted); font-weight: 700; margin-top: .25rem; }
        .table-wrap {
            background: #fff;
            border: 1px solid rgba(16,24,40,.16);
            border-radius: 8px;
            padding: .8rem;
            box-shadow: 0 14px 35px rgba(16,24,40,.10);
            overflow-x: auto;
        }
        table.control-table {
            border-collapse: collapse;
            width: 100%;
            min-width: 980px;
            font-size: .88rem;
        }
        .control-table th {
            background: #28549a;
            color: white;
            padding: .5rem;
            border: 1px solid #111827;
            text-align: center;
            white-space: nowrap;
        }
        .control-table td {
            color: var(--ink);
            padding: .45rem .5rem;
            border: 1px solid #111827;
            font-weight: 750;
            text-align: right;
        }
        .control-table td:first-child,
        .control-table td:nth-child(2),
        .control-table td:nth-child(3) {
            text-align: left;
        }
        .ok { background: #dcfce7; color: #027a48 !important; }
        .warn { background: #fef3c7; color: #b54708 !important; }
        .bad { background: #ffe4e8; color: #b42318 !important; }
        @media (max-width: 900px) {
            .kpi-grid { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_num(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    amount = float(value)
    if abs(amount) >= 100:
        text = f"{amount:,.0f}"
    else:
        text = f"{amount:,.1f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def format_pct(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):,.0f}%".replace(",", "X").replace(".", ",").replace("X", ".")


def clean_name(value: object) -> str:
    return sales_app.clean_name("" if pd.isna(value) else str(value))


def latest_bultos_file(folder: Path | None) -> Path | None:
    if folder is None or not folder.exists():
        return None
    files = [
        path
        for path in folder.iterdir()
        if path.is_file()
        and not path.name.startswith("~$")
        and path.suffix.lower() in {".txt", ".csv"}
        and all(term in clean_name(path.stem) for term in ("venta", "bulto"))
    ]
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def choose_quantity_column(raw: pd.DataFrame) -> str:
    candidates = []
    for column in raw.columns:
        key = clean_name(column)
        score = 0
        if "bulto" in key and "promedio" not in key:
            score += 5
        if "cantidad" in key and "total" in key:
            score += 3
        if "bulto" in key:
            score += 2
        if score:
            candidates.append((score, str(column)))
    if not candidates:
        return str(raw.columns[-1])
    return sorted(candidates, reverse=True)[0][1]


def normalize_bultos(raw: pd.DataFrame, quantity_col: str) -> pd.DataFrame:
    raw = raw.copy()
    original_columns = list(raw.columns)
    clean_columns = sales_app.make_unique_columns(original_columns)
    quantity_index = original_columns.index(quantity_col) if quantity_col in original_columns else len(original_columns) - 1
    quantity_key = clean_columns[quantity_index]
    raw.columns = clean_columns
    fecha = sales_app.parse_period_date(sales_app.first_present(raw, ["descripcion_periodo"], "C"))
    if fecha.isna().all():
        fecha = sales_app.parse_period_date(sales_app.first_present(raw, ["periodos"], "A"))

    normalized = pd.DataFrame(
        {
            "fecha": fecha,
            "cliente_codigo": sales_app.first_present(raw, ["cod_cliente"], "E"),
            "cliente": sales_app.first_present(raw, ["descripcion"], "F"),
            "ruta_codigo": sales_app.first_present(raw, ["ruta"], "I"),
            "ruta": sales_app.first_present(raw, ["descripcion_1"], "J"),
            "vendedor": sales_app.first_present(raw, ["descripcion_vendedor"], "P"),
            "marca": sales_app.first_present(raw, ["descripcion_3"], "U"),
            "calibre": sales_app.col_by_position(raw, "X"),
            "negocio": sales_app.first_present(raw, ["descripcion_8"], "AJ"),
            "bultos": sales_app.parse_argentine_number(raw[quantity_key]),
        }
    )
    normalized["fecha"] = pd.to_datetime(normalized["fecha"], errors="coerce").dt.normalize()
    normalized["cliente_codigo"] = pd.to_numeric(normalized["cliente_codigo"], errors="coerce").astype("Int64").astype("string")
    normalized["cliente"] = normalized["cliente"].fillna("Sin cliente").astype(str).str.strip()
    normalized["ruta"] = (
        normalized["ruta_codigo"].fillna("").astype(str).str.strip()
        + " - "
        + normalized["ruta"].fillna("").astype(str).str.strip()
    ).str.strip(" -")
    normalized["vendedor"] = normalized["vendedor"].fillna("Sin vendedor").astype(str).str.strip()
    normalized["marca"] = normalized["marca"].fillna("Sin marca").astype(str).str.strip()
    normalized["calibre"] = normalized["calibre"].fillna("Sin calibre").astype(str).str.strip()
    normalized["negocio"] = normalized["negocio"].fillna("Sin negocio").astype(str).str.strip()
    normalized["unidad_negocio"] = np.select(
        [
            normalized["negocio"].str.contains("UNG", case=False, na=False),
            normalized["negocio"].str.contains("CZA|CERVEZ", case=False, na=False),
        ],
        ["UNG", "CZA"],
        default=normalized["negocio"],
    )
    normalized["bultos"] = normalized["bultos"].fillna(0.0)
    normalized = normalized.dropna(subset=["fecha"]).copy()
    return normalized


def read_raw_source(path: Path | None, uploaded_file) -> tuple[pd.DataFrame, str]:
    if uploaded_file is not None:
        return sales_app.read_tabular(io.BytesIO(uploaded_file.getvalue())), uploaded_file.name
    if path is None:
        return pd.DataFrame(), ""
    return sales_app.read_tabular(path), path.name


def fallback_data_folder() -> Path | None:
    for folder in [
        sales_app.PROJECT_ROOT / ".cloud_data" / "planificacion",
        *getattr(sales_app, "DATA_DIR_CANDIDATES", []),
    ]:
        if folder.exists() and any(folder.iterdir()):
            return folder
    return None


def load_enriched_data(folder: Path | None, uploaded_file, quantity_col_override: str | None = None) -> tuple[pd.DataFrame, str, list[str], str]:
    source_path = latest_bultos_file(folder)
    raw, source_label = read_raw_source(source_path, uploaded_file)
    if raw.empty:
        return pd.DataFrame(), "", [], ""

    quantity_options = list(raw.columns)
    quantity_col = quantity_col_override if quantity_col_override in raw.columns else choose_quantity_column(raw)
    data = normalize_bultos(raw, quantity_col)

    customer_file = sales_app.latest_customer_file_in_folder(folder) if folder is not None else None
    if customer_file is not None:
        customers, _ = sales_app.load_customer_channels(str(customer_file), customer_file.stat().st_mtime_ns)
        data = sales_app.apply_customer_channels(data, customers)
    else:
        data["canal"] = "NO"

    aux_file = sales_app.latest_auxiliary_file_in_folder(folder) if folder is not None else None
    if aux_file is not None:
        aux_segments, _ = sales_app.load_auxiliary_segments(str(aux_file), aux_file.stat().st_mtime_ns)
        data = sales_app.apply_auxiliary_segments(data, aux_segments)
    else:
        data["division_informe"] = "CVZA SIN SEGMENTO"

    data["accion"] = data["division_informe"].map(SEGMENTOS_ACCION).fillna("")
    data = data[(data["unidad_negocio"] == "CZA") & data["accion"].isin(["CORE", "VALUE"])].copy()
    data["canal_accion"] = data["canal"].replace({"AUTOSERVICIO": "AS"})
    data["tope"] = data["canal"].map(TOPES_CANAL).fillna(data["canal_accion"].map(TOPES_CANAL))
    data = data[data["tope"].notna()].copy()
    return data, source_label, quantity_options, quantity_col


def apply_filters(data: pd.DataFrame) -> pd.DataFrame:
    filtered = data.copy()
    st.sidebar.markdown("### Filtros")
    if not filtered.empty:
        dates = sorted(filtered["fecha"].dropna().unique())
        selected_dates = st.sidebar.multiselect(
            "Fecha",
            dates,
            default=dates,
            format_func=lambda date: pd.Timestamp(date).strftime("%d/%m/%Y"),
        )
        filtered = filtered[filtered["fecha"].isin(selected_dates)]

    for column, label in [
        ("canal_accion", "Canal accion"),
        ("accion", "Accion"),
        ("vendedor", "Vendedor"),
        ("ruta", "Ruta"),
        ("cliente", "Cliente"),
    ]:
        values = sorted(filtered[column].dropna().astype(str).unique().tolist()) if column in filtered.columns else []
        selected = st.sidebar.multiselect(label, values, default=[])
        if selected:
            filtered = filtered[filtered[column].astype(str).isin(selected)]
    return filtered


def build_customer_summary(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    grouped = data.groupby(
        ["cliente_codigo", "cliente", "canal_accion", "ruta", "vendedor", "accion"],
        as_index=False,
    ).agg(bultos=("bultos", "sum"), tope=("tope", "first"))
    pivot = grouped.pivot_table(
        index=["cliente_codigo", "cliente", "canal_accion", "ruta", "vendedor"],
        columns="accion",
        values="bultos",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    for action in ["CORE", "VALUE"]:
        if action not in pivot.columns:
            pivot[action] = 0.0
    topes = grouped.groupby(["cliente_codigo", "accion"], as_index=False)["tope"].first().pivot(
        index="cliente_codigo",
        columns="accion",
        values="tope",
    )
    pivot = pivot.merge(topes.add_prefix("tope_").reset_index(), on="cliente_codigo", how="left")
    pivot["tope_CORE"] = pivot["tope_CORE"].fillna(pivot["canal_accion"].map({"K+T": 200.0, "AS": 500.0}))
    pivot["tope_VALUE"] = pivot["tope_VALUE"].fillna(pivot["canal_accion"].map({"K+T": 200.0, "AS": 500.0}))
    pivot["avance_CORE"] = np.where(pivot["tope_CORE"] > 0, pivot["CORE"] / pivot["tope_CORE"] * 100, np.nan)
    pivot["avance_VALUE"] = np.where(pivot["tope_VALUE"] > 0, pivot["VALUE"] / pivot["tope_VALUE"] * 100, np.nan)
    pivot["restante_CORE"] = (pivot["tope_CORE"] - pivot["CORE"]).clip(lower=0)
    pivot["restante_VALUE"] = (pivot["tope_VALUE"] - pivot["VALUE"]).clip(lower=0)
    pivot["estado"] = np.select(
        [
            (pivot["avance_CORE"] >= 100) & (pivot["avance_VALUE"] >= 100),
            (pivot["avance_CORE"] >= 80) | (pivot["avance_VALUE"] >= 80),
        ],
        ["Completo", "Cerca del tope"],
        default="Pendiente",
    )
    return pivot.sort_values(["estado", "avance_CORE", "avance_VALUE"], ascending=[True, False, False])


def render_kpis(summary: pd.DataFrame) -> None:
    total_clients = summary["cliente_codigo"].nunique() if not summary.empty else 0
    core = summary["CORE"].sum() if "CORE" in summary else 0.0
    value = summary["VALUE"].sum() if "VALUE" in summary else 0.0
    completed = int(((summary.get("avance_CORE", pd.Series(dtype=float)) >= 100) | (summary.get("avance_VALUE", pd.Series(dtype=float)) >= 100)).sum())
    cards = [
        ("Clientes", format_num(total_clients), "Con compra Core/Value", ""),
        ("Bultos Core", format_num(core), "Acumulado filtrado", "green"),
        ("Bultos Value", format_num(value), "Acumulado filtrado", "orange"),
        ("Clientes al tope", format_num(completed), "Core o Value >= 100%", "red"),
    ]
    html = "<div class='kpi-grid'>"
    for title, value, sub, cls in cards:
        html += f"<div class='kpi-card {cls}'><div class='kpi-label'>{title}</div><div class='kpi-value'>{value}</div><div class='kpi-sub'>{sub}</div></div>"
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def status_class(value: float) -> str:
    if pd.isna(value):
        return ""
    if value >= 100:
        return "ok"
    if value >= 80:
        return "warn"
    return "bad"


def render_summary_table(summary: pd.DataFrame) -> None:
    if summary.empty:
        st.info("No hay clientes para los filtros seleccionados.")
        return
    rows = []
    for _, row in summary.iterrows():
        rows.append(
            "<tr>"
            f"<td>{row['cliente_codigo']}</td>"
            f"<td>{row['cliente']}</td>"
            f"<td>{row['canal_accion']}</td>"
            f"<td>{format_num(row['CORE'])}</td>"
            f"<td>{format_num(row['tope_CORE'])}</td>"
            f"<td class='{status_class(row['avance_CORE'])}'>{format_pct(row['avance_CORE'])}</td>"
            f"<td>{format_num(row['restante_CORE'])}</td>"
            f"<td>{format_num(row['VALUE'])}</td>"
            f"<td>{format_num(row['tope_VALUE'])}</td>"
            f"<td class='{status_class(row['avance_VALUE'])}'>{format_pct(row['avance_VALUE'])}</td>"
            f"<td>{format_num(row['restante_VALUE'])}</td>"
            f"<td>{row['vendedor']}</td>"
            f"<td>{row['ruta']}</td>"
            "</tr>"
        )
    st.markdown(
        f"""
        <div class="table-wrap">
            <table class="control-table">
                <thead>
                    <tr>
                        <th>Cod cliente</th><th>Cliente</th><th>Canal</th>
                        <th>Core bultos</th><th>Tope Core</th><th>Avance Core</th><th>Restan Core</th>
                        <th>Value bultos</th><th>Tope Value</th><th>Avance Value</th><th>Restan Value</th>
                        <th>Vendedor</th><th>Ruta</th>
                    </tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def chart_layout(fig):
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(family="Arial", color="#101828", size=13),
        margin=dict(l=20, r=20, t=48, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(showgrid=False, color="#101828")
    fig.update_yaxes(gridcolor="rgba(16,24,40,.14)", color="#101828")
    return fig


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="📦", layout="wide")
    inject_style()

    st.markdown(
        """
        <div class="hero">
            <h1>Control bultos Core / Value</h1>
            <p>Seguimiento por cliente contra tope de accion: K+T 200 bultos y AS 500 bultos.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.header("Datos")
    if "bultos_drive_refresh" not in st.session_state:
        st.session_state["bultos_drive_refresh"] = 0.0
    drive_url = sales_app.secret_or_env("GOOGLE_DRIVE_PLANIFICACION_URL", DEFAULT_DRIVE_URL)
    if st.sidebar.button("Actualizar datos", width="stretch"):
        st.session_state["bultos_drive_refresh"] = time.time()

    folder = sales_app.resolve_google_drive_folder(
        "GOOGLE_DRIVE_PLANIFICACION_URL",
        "planificacion",
        force_refresh=bool(st.session_state["bultos_drive_refresh"]),
    )
    if folder is None:
        st.sidebar.warning("No pude leer Google Drive. Uso cache local si existe o carga manual.")
        folder = fallback_data_folder()
    st.sidebar.caption(f"Drive: {drive_url}")
    st.sidebar.caption(f"Carpeta usada: {folder if folder else 'sin carpeta'}")

    uploaded_file = st.sidebar.file_uploader("Carga manual ventadiaria bultos", type=["txt", "csv"])
    source_path = latest_bultos_file(folder)
    if source_path is not None:
        st.sidebar.success(f"Fuente: {source_path.name}")
    elif uploaded_file is None:
        st.warning("No encontre archivo con nombre 'ventadiaria bultos' en la carpeta. Subilo al Drive o cargalo manualmente.")
        return

    raw, source_label = read_raw_source(source_path, uploaded_file)
    if raw.empty:
        st.warning("No pude leer el archivo de bultos.")
        return
    quantity_default = choose_quantity_column(raw)
    quantity_options = list(raw.columns)
    quantity_col = st.sidebar.selectbox(
        "Columna de bultos",
        quantity_options,
        index=quantity_options.index(quantity_default),
    )
    data, source_label, _, quantity_used = load_enriched_data(folder, uploaded_file, quantity_col)
    st.sidebar.caption(f"Columna usada: {quantity_used}")

    if data.empty:
        st.warning("No hay filas Core/Value de CZA para clientes K+T o AS con el archivo seleccionado.")
        return

    filtered = apply_filters(data)
    summary = build_customer_summary(filtered)
    render_kpis(summary)

    left, right = st.columns(2)
    with left:
        by_action = filtered.groupby(["fecha", "accion"], as_index=False)["bultos"].sum()
        fig = px.line(
            by_action,
            x="fecha",
            y="bultos",
            color="accion",
            markers=True,
            title="Bultos diarios por accion",
            color_discrete_map={"CORE": "#1463ff", "VALUE": "#f79009"},
        )
        st.plotly_chart(chart_layout(fig), width="stretch")
    with right:
        top_clients = summary.assign(total_bultos=summary["CORE"] + summary["VALUE"]).nlargest(15, "total_bultos")
        fig = px.bar(
            top_clients,
            x="total_bultos",
            y="cliente",
            color="canal_accion",
            orientation="h",
            title="Top clientes por bultos Core + Value",
            color_discrete_map={"K+T": "#1463ff", "AS": "#12b76a"},
        )
        st.plotly_chart(chart_layout(fig), width="stretch")

    st.subheader("Detalle por cliente")
    render_summary_table(summary)

    export = summary.copy()
    export = export.rename(
        columns={
            "cliente_codigo": "Cod cliente",
            "cliente": "Cliente",
            "canal_accion": "Canal",
            "CORE": "Core bultos",
            "tope_CORE": "Tope Core",
            "avance_CORE": "Avance Core %",
            "restante_CORE": "Restan Core",
            "VALUE": "Value bultos",
            "tope_VALUE": "Tope Value",
            "avance_VALUE": "Avance Value %",
            "restante_VALUE": "Restan Value",
            "vendedor": "Vendedor",
            "ruta": "Ruta",
        }
    )
    st.download_button(
        "Descargar detalle CSV",
        data=export.to_csv(index=False).encode("utf-8-sig"),
        file_name="control_bultos_core_value.csv",
        mime="text/csv",
        width="stretch",
    )


if __name__ == "__main__":
    main()
