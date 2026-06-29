from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.request
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


APP_DIR = Path(__file__).parent
DATA_PATH = APP_DIR / "data" / "dashboard-data.json"
XLSX_PATH = APP_DIR / "data" / "CXC_BEESCARE_DelValle_analisis.xlsx"
PPTX_PATH = APP_DIR / "data" / "Capacitacion_JDV_SPV_CXC_BEESCARE_GALAXIA_DelValle.pptx"
ACTION_PLANS_PATH = APP_DIR / "data" / "planes_accion_guardados.json"
DEFAULT_CACHE_SECONDS = 0

COLORS = {
    "violet": "#7c3aed",
    "magenta": "#ec4899",
    "cyan": "#06b6d4",
    "green": "#22c55e",
    "lime": "#a3e635",
    "orange": "#f97316",
    "red": "#ef4444",
    "yellow": "#fde68a",
    "ink": "#172033",
}


st.set_page_config(
    page_title="CXC / BEESCARE - Distribuidora del Valle",
    page_icon=":bar_chart:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_style() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
        html, body, [class*="css"] { font-family: Inter, Segoe UI, sans-serif; }
        .stApp {
          background:
            radial-gradient(circle at 8% 4%, rgba(255,74,111,.18), transparent 26%),
            radial-gradient(circle at 86% 10%, rgba(0,210,255,.16), transparent 30%),
            radial-gradient(circle at 48% 94%, rgba(124,58,237,.18), transparent 32%),
            linear-gradient(135deg, #080d1b 0%, #0d1224 42%, #092638 100%);
          color: #f8fafc;
        }
        .block-container {
          padding-top: 2rem;
          padding-bottom: 2rem;
          max-width: 1500px;
        }
        section[data-testid="stSidebar"] {
          background: linear-gradient(180deg, rgba(7,12,28,.98), rgba(10,22,38,.96));
          border-right: 1px solid rgba(148,163,184,.16);
        }
        section[data-testid="stSidebar"] * {
          color: #e5e7eb;
        }
        .hero {
          padding: 24px 28px;
          border: 1px solid rgba(148,163,184,.22);
          background:
            linear-gradient(135deg, rgba(16,24,48,.88), rgba(12,48,68,.62)),
            radial-gradient(circle at 95% 10%, rgba(255,74,111,.22), transparent 28%);
          backdrop-filter: blur(18px);
          border-radius: 20px;
          box-shadow: 0 24px 70px rgba(0,0,0,.36);
          margin-bottom: 18px;
        }
        .eyebrow {
          color: #ff496d;
          font-weight: 800;
          letter-spacing: .06em;
          text-transform: uppercase;
          font-size: 12px;
        }
        .title {
          color: #f8fafc;
          font-size: 34px;
          font-weight: 850;
          line-height: 1.05;
          margin-top: 4px;
        }
        .subtitle { color: #a9b7ca; font-size: 15px; margin-top: 8px; }
        .kpi-card {
          border: 1px solid rgba(148,163,184,.22);
          background: linear-gradient(145deg, rgba(255,255,255,.11), rgba(255,255,255,.055));
          backdrop-filter: blur(18px);
          border-radius: 16px;
          padding: 18px 18px 16px;
          min-height: 116px;
          box-shadow: 0 18px 46px rgba(0,0,0,.26);
          transition: transform .18s ease, box-shadow .18s ease;
        }
        .kpi-card:hover { transform: translateY(-2px); box-shadow: 0 24px 58px rgba(0,0,0,.38); }
        .kpi-label { color: #91a0b8; font-weight: 800; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
        .kpi-value { color: #f8fafc; font-size: 32px; font-weight: 850; margin-top: 7px; }
        .kpi-note { color: #8493aa; font-size: 12px; margin-top: 4px; }
        .soft-panel {
          border: 1px solid rgba(148,163,184,.18);
          background: linear-gradient(145deg, rgba(15,23,42,.78), rgba(15,44,63,.48));
          backdrop-filter: blur(16px);
          border-radius: 18px;
          padding: 18px;
          box-shadow: 0 20px 58px rgba(0,0,0,.28);
        }
        .section-title { font-size: 20px; font-weight: 850; color: #f8fafc; margin-bottom: 8px; }
        .badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          border-radius: 999px;
          padding: 6px 10px;
          font-size: 12px;
          font-weight: 800;
          background: rgba(255,74,111,.14);
          color: #ff8aa0;
          border: 1px solid rgba(255,74,111,.26);
        }
        .footer-signature {
          text-align: right;
          color: rgba(226,232,240,.34);
          font-weight: 800;
          padding: 24px 4px 4px;
          transition: color .2s ease;
        }
        .footer-signature:hover { color: rgba(255,74,111,.82); }
        div[data-testid="stMetric"] {
          border-radius: 16px;
          padding: 12px;
          background: rgba(255,255,255,.08);
          border: 1px solid rgba(148,163,184,.18);
        }
        .stDownloadButton button, .stButton button {
          border-radius: 12px;
          border: 0;
          background: linear-gradient(135deg, #ff496d, #7c3aed);
          color: white;
          font-weight: 800;
          box-shadow: 0 14px 34px rgba(255,73,109,.22);
        }
        .stTabs [data-baseweb="tab-list"] {
          gap: 18px;
          border-bottom: 1px solid rgba(148,163,184,.18);
        }
        .stTabs [data-baseweb="tab"] {
          color: #dbeafe;
          font-weight: 800;
          padding-left: 0;
          padding-right: 0;
        }
        .stTabs [aria-selected="true"] {
          color: #ff496d !important;
          border-bottom: 2px solid #ff496d;
        }
        div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {
          border: 1px solid rgba(148,163,184,.18);
          border-radius: 16px;
          overflow: hidden;
          box-shadow: 0 18px 46px rgba(0,0,0,.24);
        }
        h1, h2, h3, h4, h5, h6, p, label, span {
          color: inherit;
        }
        div[data-testid="stAlert"] {
          background: rgba(255,73,109,.14);
          color: #fecdd3;
          border: 1px solid rgba(255,73,109,.24);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def secret_or_env(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, default) or "").strip()


def normalize_drive_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if "drive.google.com/drive/folders/" in url:
        raise ValueError("DATA_URL debe ser el link del archivo dashboard-data.json, no el link de la carpeta de Drive.")
    match = re.search(r"/d/([A-Za-z0-9_-]+)", url) or re.search(r"[?&]id=([A-Za-z0-9_-]+)", url)
    if "drive.google.com" in url and match:
        return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return url


def load_remote_data(source_url: str) -> dict:
    url = normalize_drive_url(source_url)
    if "?" in url:
        url = f"{url}&cache_bust={pd.Timestamp.utcnow().timestamp()}"
    else:
        url = f"{url}?cache_bust={pd.Timestamp.utcnow().timestamp()}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Streamlit CXC",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = response.read().decode("utf-8-sig")
    return json.loads(payload)


@st.cache_data(show_spinner=False, ttl=60)
def load_local_data(file_mtime: float) -> dict:
    with DATA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_data() -> tuple[dict, str]:
    source_url = secret_or_env("DATA_URL")
    if source_url:
        try:
            return load_remote_data(source_url), "Google Drive"
        except Exception as exc:
            st.warning(f"No pude leer DATA_URL desde Drive. Uso la copia local. Detalle: {exc}")
    return load_local_data(DATA_PATH.stat().st_mtime), "Archivo local GitHub"


def as_df(data: dict, key: str) -> pd.DataFrame:
    return pd.DataFrame(data.get(key, []))


def pct(value: float | int | None, decimals: int = 1) -> str:
    value = 0 if value is None else float(value)
    return f"{value:.{decimals}f}%".replace(".", ",")


def clean_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.strip().lower()


def status_for(row: pd.Series) -> str:
    if bool(row.get("Cerrado")) and bool(row.get("DentroSLA")):
        return "Cerrado dentro SLA"
    if bool(row.get("Cerrado")) and bool(row.get("FueraSLA")):
        return "Cerrado fuera SLA"
    if bool(row.get("PendienteVencido")):
        return "Pendiente vencido"
    return "Pendiente dentro SLA"


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, sep=";").encode("utf-8-sig")


def action_plan_key(row: pd.Series | dict) -> str:
    mes = str(row.get("Mes", "") or "")
    cliente = str(row.get("Cliente", "") or row.get("ClienteId", "") or "")
    ticket = str(row.get("Ticket", "") or row.get("Motivo", "") or "")
    return f"{mes}__{cliente}__{ticket}"


def load_saved_action_plans() -> dict:
    if not ACTION_PLANS_PATH.exists():
        return {}
    try:
        with ACTION_PLANS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_action_plans(rows: pd.DataFrame) -> None:
    saved = load_saved_action_plans()
    editable_cols = [
        "Responsable",
        "FechaCompromiso",
        "AccionRealizada",
        "ComentarioSeguimiento",
        "Estado",
        "ProximoSeguimiento",
    ]
    for _, row in rows.iterrows():
        key = action_plan_key(row)
        saved[key] = {col: str(row.get(col, "") or "") for col in editable_cols}
    ACTION_PLANS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ACTION_PLANS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(saved, fh, ensure_ascii=False, indent=2)


def import_action_plans(payload: bytes) -> int:
    incoming = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(incoming, dict):
        raise ValueError("El archivo de planes debe ser un JSON con claves de planes.")
    saved = load_saved_action_plans()
    saved.update(incoming)
    ACTION_PLANS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ACTION_PLANS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(saved, fh, ensure_ascii=False, indent=2)
    return len(incoming)


def saved_action_plans_bytes() -> bytes:
    if not ACTION_PLANS_PATH.exists():
        return b"{}"
    return ACTION_PLANS_PATH.read_bytes()


def make_kpi(label: str, value: str, note: str = "", color: str = "#7c3aed") -> None:
    st.markdown(
        f"""
        <div class="kpi-card" style="border-top: 4px solid {color};">
          <div class="kpi-label">{label}</div>
          <div class="kpi-value">{value}</div>
          <div class="kpi-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def filter_tickets(tickets: pd.DataFrame, source_label: str) -> pd.DataFrame:
    with st.sidebar:
        st.markdown("### Datos")
        st.caption(f"Fuente actual: {source_label}")
        st.caption(f"Tickets cargados: {len(tickets)}")
        if st.button("Actualizar / limpiar cache", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        st.divider()
        st.markdown("### Filtros")
        months = ["Todos"] + sorted(tickets["Mes"].dropna().unique().tolist())
        selected_month = st.selectbox("Mes", months, key="filter_month")

        statuses = ["Todos"] + sorted(tickets["EstadoOperativo"].dropna().unique().tolist())
        selected_status = st.selectbox("Estado SLA", statuses)

        scopes = ["Todos"] + sorted(tickets["Alcance"].dropna().unique().tolist())
        selected_scope = st.selectbox("Alcance", scopes)

        reasons = ["Todos"] + sorted(tickets["Motivo"].dropna().unique().tolist())
        selected_reason = st.selectbox("Motivo", reasons)

        search = st.text_input("Buscar cliente / ticket / submotivo", "")

    out = tickets.copy()
    if selected_month != "Todos":
        out = out[out["Mes"] == selected_month]
    if selected_status != "Todos":
        out = out[out["EstadoOperativo"] == selected_status]
    if selected_scope != "Todos":
        out = out[out["Alcance"] == selected_scope]
    if selected_reason != "Todos":
        out = out[out["Motivo"] == selected_reason]
    if search.strip():
        haystack = out[["Ticket", "ClienteId", "Motivo", "Submotivo", "Estado"]].fillna("").astype(str).agg(" ".join, axis=1)
        out = out[haystack.str.lower().str.contains(search.strip().lower(), regex=False)]
    return out


def plot_monthly(monthly: pd.DataFrame) -> None:
    monthly = monthly.copy()
    monthly["ON TIME %"] = monthly["OnTime"] * 100

    fig = go.Figure()
    fig.add_trace(go.Bar(x=monthly["Mes"], y=monthly["Total"], name="Tickets", marker_color=COLORS["cyan"], opacity=.45))
    fig.add_trace(go.Scatter(x=monthly["Mes"], y=monthly["ON TIME %"], name="ON TIME", mode="lines+markers", line=dict(color=COLORS["violet"], width=4)))
    fig.update_layout(
        height=390,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,.35)",
        font=dict(color="#dbeafe"),
        legend=dict(orientation="h", y=1.10),
        xaxis=dict(gridcolor="rgba(148,163,184,.12)"),
        yaxis=dict(title_text="Tickets / porcentaje", gridcolor="rgba(148,163,184,.12)"),
    )
    st.plotly_chart(fig, use_container_width=True)


def plot_adoption(monthly: pd.DataFrame) -> None:
    monthly = monthly.copy()
    monthly["Adopcion CXC %"] = monthly["AdopcionPct"] * 100
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=monthly["Mes"],
            y=monthly["ClientesContactoCXC"],
            name="Clientes con contacto CXC",
            marker_color=COLORS["cyan"],
            opacity=.42,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=monthly["Mes"],
            y=monthly["Adopcion CXC %"],
            name="Adopcion CXC %",
            mode="lines+markers+text",
            text=[pct(v, 2) for v in monthly["Adopcion CXC %"]],
            textposition="top center",
            line=dict(color=COLORS["green"], width=4),
        )
    )
    fig.update_layout(
        height=330,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,.35)",
        font=dict(color="#dbeafe"),
        legend=dict(orientation="h", y=1.12),
        xaxis=dict(gridcolor="rgba(148,163,184,.12)"),
        yaxis=dict(title_text="Clientes / porcentaje", gridcolor="rgba(148,163,184,.12)"),
    )
    st.plotly_chart(fig, use_container_width=True)


def plot_bar(df: pd.DataFrame, name_col: str, value_col: str, title: str, colors: list[str]) -> None:
    if df.empty:
        st.info("Sin datos para mostrar con los filtros actuales.")
        return
    fig = px.bar(df, x=value_col, y=name_col, orientation="h", title=title, color=name_col, color_discrete_sequence=colors)
    fig.update_layout(
        height=390,
        margin=dict(l=10, r=10, t=45, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,.35)",
        font=dict(color="#dbeafe"),
        showlegend=False,
        xaxis=dict(gridcolor="rgba(148,163,184,.12)"),
        yaxis=dict(autorange="reversed", gridcolor="rgba(148,163,184,.12)"),
    )
    st.plotly_chart(fig, use_container_width=True)


def critical_source_for_filter(data: dict) -> tuple[pd.DataFrame, str]:
    selected_month = st.session_state.get("filter_month", "Todos")
    mapping = {
        "2026-03": ("criticosMarzo", "Marzo"),
        "2026-04": ("criticosAbril", "Abril"),
        "2026-05": ("criticosMayo", "Mayo"),
    }
    if selected_month in mapping:
        key, label = mapping[selected_month]
        return as_df(data, key), label
    frames = [as_df(data, key) for key in ["criticosMarzo", "criticosAbril", "criticosMayo"]]
    frames = [frame for frame in frames if not frame.empty]
    if frames:
        return pd.concat(frames, ignore_index=True), "Todos"
    return pd.DataFrame(), "Todos"


def only_critical_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty or "Criticidad" not in rows.columns:
        return rows
    marker = rows["Criticidad"].map(clean_text)
    return rows[marker.str.contains("critico", na=False) & ~marker.str.startswith("no", na=False)].copy()


def add_ticket_details(rows: pd.DataFrame, data: dict) -> pd.DataFrame:
    if rows.empty:
        return rows
    out = rows.copy()
    tickets = as_df(data, "tickets")
    if tickets.empty or "Ticket" not in tickets.columns or "Formulario" not in out.columns:
        return out
    details = tickets[["Ticket", "Motivo", "Submotivo"]].copy()
    details["Ticket"] = details["Ticket"].astype(str).str.strip()
    out["Formulario"] = out["Formulario"].astype(str).str.strip()
    out = out.merge(details.rename(columns={"Ticket": "Formulario", "Motivo": "MotivoReal", "Submotivo": "SubmotivoReal"}), on="Formulario", how="left")
    return out


def plan_rows_from_critical(data: dict, plan_clientes: pd.DataFrame, top5: pd.DataFrame) -> pd.DataFrame:
    critical_rows, label = critical_source_for_filter(data)
    critical_rows = only_critical_rows(critical_rows)
    if critical_rows.empty:
        base = top5.copy()
        if base.empty:
            base = plan_clientes.copy()
        return base

    tickets = as_df(data, "tickets")
    ticket_lookup = {}
    if not tickets.empty and "Ticket" in tickets.columns:
        for _, ticket_row in tickets.iterrows():
            ticket_lookup[str(ticket_row.get("Ticket", "")).strip()] = ticket_row

    rows = []
    for client_id, group in critical_rows.groupby("ClienteId", dropna=False):
        first = group.iloc[0]
        ticket_number = str(first.get("Formulario", "") or "").strip()
        ticket_info = ticket_lookup.get(ticket_number)
        real_motivo = ""
        real_submotivo = ""
        if ticket_info is not None:
            real_motivo = str(ticket_info.get("Motivo", "") or "")
            real_submotivo = str(ticket_info.get("Submotivo", "") or "")
        rows.append(
            {
                "Cliente": str(client_id),
                "Nombre": "",
                "Mes": first.get("Mes", label),
                "TicketsCriticos": len(group),
                "Ticket": ticket_number or first.get("Ticket", ""),
                "Motivo": real_motivo or "Sin motivo encontrado",
                "Submotivo": real_submotivo,
                "Prioridad": "Alta",
                "AccionSugerida": "Contactar cliente; analizar causa raiz; asignar responsable; definir correccion; seguimiento semanal hasta cierre.",
                "Responsable": "JDV / SPV",
                "FechaCompromiso": "",
                "AccionRealizada": "",
                "ComentarioSeguimiento": "",
                "Estado": "Requiere seguimiento",
                "ProximoSeguimiento": "",
            }
        )
    return pd.DataFrame(rows).sort_values(["Mes", "TicketsCriticos", "Cliente"], ascending=[True, False, True])


def action_plan_editor(data: dict, plan_clientes: pd.DataFrame, top5: pd.DataFrame) -> pd.DataFrame:
    base = plan_rows_from_critical(data, plan_clientes, top5)
    wanted = [
        "Cliente",
        "Nombre",
        "Mes",
        "TicketsCriticos",
        "Ticket",
        "Motivo",
        "Submotivo",
        "Prioridad",
        "AccionSugerida",
        "Responsable",
        "FechaCompromiso",
        "AccionRealizada",
        "ComentarioSeguimiento",
        "Estado",
        "ProximoSeguimiento",
    ]
    for col in wanted:
        if col not in base.columns:
            base[col] = ""
    if "EstadoSugerido" in base.columns:
        base["Estado"] = base["Estado"].where(base["Estado"].astype(str).str.len() > 0, base["EstadoSugerido"])
    if "Responsable" not in base.columns or base["Responsable"].astype(str).eq("").all():
        base["Responsable"] = "JDV / SPV"
    saved_plans = load_saved_action_plans()
    for idx, row in base.iterrows():
        saved = saved_plans.get(action_plan_key(row), {})
        for col, value in saved.items():
            if col in base.columns:
                base.at[idx, col] = value
    for text_col in [
        "Cliente",
        "Nombre",
        "Mes",
        "Ticket",
        "Motivo",
        "Submotivo",
        "Prioridad",
        "AccionSugerida",
        "Responsable",
        "AccionRealizada",
        "ComentarioSeguimiento",
        "Estado",
        "FechaCompromiso",
        "ProximoSeguimiento",
    ]:
        base[text_col] = base[text_col].fillna("").astype(str)

    edited = st.data_editor(
        base[wanted],
        use_container_width=True,
        height=430,
        num_rows="dynamic",
        column_config={
            "AccionSugerida": st.column_config.TextColumn("Accion sugerida", width="large"),
            "AccionRealizada": st.column_config.TextColumn("Accion realizada", width="large"),
            "ComentarioSeguimiento": st.column_config.TextColumn("Comentario seguimiento", width="large"),
            "Estado": st.column_config.SelectboxColumn("Estado", options=["Pendiente", "En curso", "Cerrado", "Requiere seguimiento"]),
            "FechaCompromiso": st.column_config.TextColumn("Fecha compromiso", help="Formato sugerido: YYYY-MM-DD"),
            "ProximoSeguimiento": st.column_config.TextColumn("Proximo seguimiento", help="Formato sugerido: YYYY-MM-DD"),
        },
        key=f"planes_accion_{st.session_state.get('filter_month', 'Todos')}",
    )
    return edited


def main() -> None:
    inject_style()
    data, source_label = load_data()

    tickets = as_df(data, "tickets")
    monthly = as_df(data, "monthly")
    plan_motivos = as_df(data, "planMotivos")
    plan_clientes = as_df(data, "planClientes")
    top5 = as_df(data, "top5Criticos")
    checklist = as_df(data, "auditChecklist")
    riesgo = as_df(data, "riesgoTickets")

    tickets["EstadoOperativo"] = tickets.apply(status_for, axis=1)
    filtered = filter_tickets(tickets, source_label)

    st.markdown(
        f"""
        <div class="hero">
          <div class="eyebrow">Manual GALAXIA · Nivel 1 · {data.get("distribuidor", "")}</div>
          <div class="title">Dashboard CXC / BEESCARE</div>
          <div class="subtitle">Periodo analizado: <b>{data.get("periodo", "")}</b> · Generado: {data.get("generado", "")} · Fuente: {source_label} · Tickets: {len(tickets)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    kpis = data.get("kpis", {})
    closed = filtered[filtered["Cerrado"] == True]
    inside = closed[closed["DentroSLA"] == True]
    on_time_filtered = (len(inside) / len(closed) * 100) if len(closed) else 0
    adoption_denominator = int(kpis.get("denominadorAdopcion", 0) or 0)
    adoption_clients = filtered["ClienteId"].astype(str).str[-6:].str.lstrip("0").replace("", pd.NA).dropna().nunique()
    adoption_filtered = (adoption_clients / adoption_denominator * 100) if adoption_denominator else 0

    cols = st.columns(7)
    with cols[0]:
        make_kpi("Tickets filtrados", f"{len(filtered):,}".replace(",", "."), f"Total base: {kpis.get('totalTickets', 0)}", COLORS["cyan"])
    with cols[1]:
        make_kpi("ON TIME", pct(on_time_filtered), f"Acumulado: {pct(kpis.get('onTimeAcumulado', 0))}", COLORS["green"])
    with cols[2]:
        make_kpi("Adopcion CXC", pct(adoption_filtered, 2), f"{adoption_clients} / {adoption_denominator} clientes", COLORS["magenta"])
    with cols[3]:
        make_kpi("Dentro SLA", str(int(filtered["DentroSLA"].sum())), "Cerrados dentro SLA", COLORS["lime"])
    with cols[4]:
        make_kpi("Fuera SLA", str(int(filtered["FueraSLA"].sum())), "Prioridad media", COLORS["red"])
    with cols[5]:
        make_kpi("Pendientes", str(int(filtered["Pendiente"].sum())), "Dentro o vencidos", COLORS["yellow"])
    with cols[6]:
        make_kpi("+10 dias", str(int(filtered["RiesgoMasivo"].sum())), "Riesgo cierre masivo", COLORS["orange"])

    tab_resumen, tab_tickets, tab_criticos, tab_planes, tab_auditoria, tab_descargas = st.tabs(
        ["Resumen", "Tickets", "Criticos", "Planes de accion", "Auditoria 100%", "Descargas"]
    )

    with tab_resumen:
        c1, c2 = st.columns([1.35, 1])
        with c1:
            st.markdown('<div class="soft-panel"><div class="section-title">Evolucion mensual</div>', unsafe_allow_html=True)
            plot_monthly(monthly)
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            status_counts = filtered["EstadoOperativo"].value_counts().reset_index()
            status_counts.columns = ["Estado", "Cantidad"]
            st.markdown('<div class="soft-panel"><div class="section-title">Estado operativo SLA</div>', unsafe_allow_html=True)
            fig = px.pie(status_counts, names="Estado", values="Cantidad", hole=.55, color_discrete_sequence=[COLORS["green"], COLORS["red"], COLORS["yellow"], COLORS["orange"]])
            fig.update_layout(
                height=390,
                margin=dict(l=8, r=8, t=20, b=8),
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#dbeafe"),
                legend=dict(font=dict(color="#dbeafe")),
            )
            st.plotly_chart(fig, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="soft-panel"><div class="section-title">Adopcion CXC mensual</div>', unsafe_allow_html=True)
        plot_adoption(monthly)
        adoption_table = monthly[["Mes", "ClientesContactoCXC", "DenominadorAdopcion", "AdopcionPct"]].copy()
        adoption_table["Adopcion CXC %"] = (adoption_table["AdopcionPct"] * 100).map(lambda value: pct(value, 2))
        adoption_table = adoption_table.rename(
            columns={
                "ClientesContactoCXC": "Clientes con contacto CXC",
                "DenominadorAdopcion": "Cartera clientes",
            }
        )[["Mes", "Clientes con contacto CXC", "Cartera clientes", "Adopcion CXC %"]]
        st.dataframe(adoption_table, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        c3, c4 = st.columns(2)
        with c3:
            reason_counts = filtered["Motivo"].fillna("Sin dato").value_counts().head(10).reset_index()
            reason_counts.columns = ["Motivo", "Cantidad"]
            plot_bar(reason_counts, "Motivo", "Cantidad", "Top motivos", [COLORS["violet"], COLORS["magenta"], COLORS["cyan"], COLORS["orange"]])
        with c4:
            scope_counts = filtered["Alcance"].fillna("Sin dato").value_counts().reset_index()
            scope_counts.columns = ["Alcance", "Cantidad"]
            plot_bar(scope_counts, "Alcance", "Cantidad", "Corresponde / No corresponde", [COLORS["green"], COLORS["orange"], COLORS["red"]])

    with tab_tickets:
        st.markdown('<div class="section-title">Tickets filtrados</div>', unsafe_allow_html=True)
        st.dataframe(filtered, use_container_width=True, height=560)
        st.download_button("Descargar tickets filtrados CSV", csv_bytes(filtered), "tickets_filtrados_cxc.csv", "text/csv")

    with tab_criticos:
        crit_marzo = as_df(data, "criticosMarzo")
        crit_abril = as_df(data, "criticosAbril")
        crit_mayo = as_df(data, "criticosMayo")
        criticos_all = pd.concat([crit_marzo, crit_abril, crit_mayo], ignore_index=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Clientes criticos marzo", crit_marzo["ClienteId"].nunique() if "ClienteId" in crit_marzo else 0)
        c2.metric("Clientes criticos abril", crit_abril["ClienteId"].nunique() if "ClienteId" in crit_abril else 0)
        c3.metric("Clientes criticos mayo", crit_mayo["ClienteId"].nunique() if "ClienteId" in crit_mayo else 0)
        c4, c5, c6 = st.columns(3)
        c4.metric(f"Recurrentes {kpis.get('mesCriticoAnterior', 'Abril')}/{kpis.get('mesCriticoVigente', 'Mayo')}", kpis.get("recurrentes", 0))
        c5.metric(f"Nuevos {kpis.get('mesCriticoVigente', 'Mayo')}", kpis.get("nuevosMayo", 0))
        c6.metric(f"Recuperados {kpis.get('mesCriticoVigente', 'Mayo')}", kpis.get("recuperados", 0))
        st.markdown('<div class="section-title">Base completa de clientes criticos</div>', unsafe_allow_html=True)
        selected_critical_month = st.radio(
            "Mes critico",
            ["Todos", "Marzo", "Abril", "Mayo"],
            index=0,
            horizontal=True,
            key="critical_month",
        )
        critical_view = criticos_all.copy()
        if selected_critical_month != "Todos" and "Mes" in critical_view:
            critical_view = critical_view[critical_view["Mes"] == selected_critical_month]
        if "Criticidad" in critical_view:
            critical_view = only_critical_rows(critical_view)
        critical_view = add_ticket_details(critical_view, data)
        if "Formulario" in critical_view.columns:
            critical_view["TicketNumero"] = critical_view["Formulario"]
        critical_cols = [col for col in ["Mes", "ClienteId", "TicketNumero", "MotivoReal", "SubmotivoReal", "Distribuidor", "Criticidad"] if col in critical_view.columns]
        critical_display = critical_view[critical_cols].rename(columns={"TicketNumero": "Ticket"}) if critical_cols else critical_view
        st.dataframe(critical_display, use_container_width=True, height=360)
        st.download_button(
            "Descargar clientes criticos CSV",
            csv_bytes(critical_display),
            f"clientes_criticos_{selected_critical_month.lower()}.csv",
            "text/csv",
        )
        st.markdown('<div class="section-title">Top clientes criticos para seguimiento</div>', unsafe_allow_html=True)
        st.dataframe(top5, use_container_width=True, height=320)
        st.markdown('<div class="section-title">Tickets en riesgo de cierre masivo</div>', unsafe_allow_html=True)
        st.dataframe(riesgo, use_container_width=True, height=260)

    with tab_planes:
        st.markdown('<span class="badge">Evidencia editable para JDV / SPV</span>', unsafe_allow_html=True)
        st.markdown("#### Planes de accion para clientes criticos")
        saved_count = len(load_saved_action_plans())
        st.caption(f"Planes guardados detectados: {saved_count}")
        import_col, export_col = st.columns([1, 1])
        with import_col:
            uploaded_plans = st.file_uploader("Importar planes guardados JSON", type=["json"], key="import_action_plans")
            if uploaded_plans is not None:
                try:
                    imported_count = import_action_plans(uploaded_plans.getvalue())
                    st.success(f"Importados {imported_count} planes. Recargando...")
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se pudo importar el JSON de planes: {exc}")
        with export_col:
            st.download_button(
                "Descargar respaldo de planes JSON",
                saved_action_plans_bytes(),
                "planes_accion_guardados.json",
                "application/json",
                use_container_width=True,
            )
        edited = action_plan_editor(data, plan_clientes, top5)
        csave, cinfo = st.columns([1, 3])
        with csave:
            if st.button("Guardar planes", use_container_width=True):
                save_action_plans(edited)
                st.success("Planes guardados en esta PC.")
        with cinfo:
            st.caption(f"Guardado local: {ACTION_PLANS_PATH}")
        st.download_button("Descargar planes completados CSV", csv_bytes(edited), "planes_accion_cxc_completados.csv", "text/csv")
        st.markdown("#### Planes sugeridos por motivo")
        st.dataframe(plan_motivos, use_container_width=True, height=360)

    with tab_auditoria:
        st.markdown('<div class="section-title">Checklist Auditoria 100%</div>', unsafe_allow_html=True)
        st.dataframe(checklist, use_container_width=True, height=420)
        st.success("Resultado objetivo: CUMPLE NIVEL 1 - ALCANCE 100% con capacitacion, indicadores, alcance, clientes criticos y planes de accion documentados.")

    with tab_descargas:
        st.markdown('<div class="section-title">Archivos de evidencia</div>', unsafe_allow_html=True)
        st.download_button("Descargar JSON de datos", DATA_PATH.read_bytes(), "dashboard-data.json", "application/json")
        if XLSX_PATH.exists():
            st.download_button("Descargar Excel de analisis", XLSX_PATH.read_bytes(), XLSX_PATH.name)
        if PPTX_PATH.exists():
            st.download_button("Descargar PPT capacitacion", PPTX_PATH.read_bytes(), PPTX_PATH.name)
        st.info("Para actualizar la app en GitHub, reemplaza `data/dashboard-data.json` con la ultima version generada.")

    st.markdown('<div class="footer-signature">by QπU</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
