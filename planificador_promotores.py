from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.error
import urllib.request

import numpy as np
import pandas as pd
import streamlit as st


APP_TITLE = "Planificador de promotores"
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/15ITRhsY5mvK3NSHeOKV2MymC078pT9TPAwKUdZDfjnI/edit?usp=sharing"
DEFAULT_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbwDlxEbBN2kmy5oVtb4LJiPFN0KtAZw-nI9TolDtfOIVuMxQqIZprMB1pquTesPGYHe/exec"

FOCUS_ALIASES = {
    "TOTAL CERVEZAS": "TOTAL CERVEZAS",
    "TOTAL CZA": "TOTAL CERVEZAS",
    "TOTAL CVZA": "TOTAL CERVEZAS",
    "VOLUMEN ABOVE CORE": "VOLUMEN ABOVE CORE",
    "ABOVE CORE": "VOLUMEN ABOVE CORE",
    "TOTAL UNG": "TOTAL UNG",
    "UNG": "TOTAL UNG",
    "AGUAS": "AGUAS",
    "TOTAL AGUAS": "AGUAS",
}

FOCUS_ORDER = ["TOTAL CERVEZAS", "VOLUMEN ABOVE CORE", "TOTAL UNG", "AGUAS"]
FOCUS_COLORS = {
    "TOTAL CERVEZAS": "#0b63ce",
    "VOLUMEN ABOVE CORE": "#7a5af8",
    "TOTAL UNG": "#16a34a",
    "AGUAS": "#06b6d4",
}
PROMOTER_ALIASES = {"ENZO VILLAGRA": "VILLAGRA ENZO"}


def secret_or_env(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, default)).strip()


def strip_accents(value: object) -> str:
    text = str(value or "")
    return "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )


def clean_text(value: object) -> str:
    text = strip_accents(value).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_promoter(value: object) -> str:
    text = clean_text(value)
    return PROMOTER_ALIASES.get(text, text)


def normalize_focus(value: object) -> str:
    text = clean_text(value)
    return FOCUS_ALIASES.get(text, "")


def parse_number(value: object) -> float:
    if value is None or pd.isna(value):
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    text = str(value).strip()
    if not text:
        return np.nan
    text = text.replace(".", "").replace(",", ".")
    return float(pd.to_numeric(text, errors="coerce"))


def google_sheet_export_url(raw_url: str) -> str:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", raw_url)
    if match:
        return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=xlsx"
    return raw_url


def col_letter(col_number: int) -> str:
    letters = ""
    while col_number > 0:
        col_number, remainder = divmod(col_number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def cell_name(row_index: int, col_index: int) -> str:
    return f"{col_letter(col_index + 1)}{row_index + 1}"


@st.cache_data(show_spinner=False, ttl=120)
def load_sheet(sheet_url: str) -> pd.DataFrame:
    workbook = pd.read_excel(google_sheet_export_url(sheet_url), sheet_name=None, header=None)
    rows: list[dict[str, object]] = []
    for sheet_name, sheet in workbook.items():
        if sheet.empty or clean_text(sheet_name) == "BD PLANIFICACION":
            continue
        raw = sheet.fillna("")
        for row_idx in range(len(raw)):
            for col_idx in range(len(raw.columns)):
                focus = normalize_focus(raw.iat[row_idx, col_idx])
                if not focus:
                    continue

                header_idx = None
                for candidate in range(row_idx, min(row_idx + 8, len(raw))):
                    values = [clean_text(value) for value in raw.iloc[candidate].tolist()]
                    if any("PROMOTOR" in value for value in values) and any("PLANIFIC" in value for value in values):
                        header_idx = candidate
                        break
                if header_idx is None:
                    continue

                header = [clean_text(value) for value in raw.iloc[header_idx].tolist()]
                search_from = max(0, col_idx - 1)
                search_to = min(len(header), col_idx + 5)
                scoped = list(enumerate(header[search_from:search_to], start=search_from))
                promoter_col = next((i for i, value in scoped if "PROMOTOR" in value), None)
                objective_col = next((i for i, value in scoped if "OBJET" in value), None)
                plan_col = next((i for i, value in scoped if "PLANIFIC" in value), None)
                if promoter_col is None or plan_col is None:
                    continue

                for detail_idx in range(header_idx + 1, len(raw)):
                    promoter = normalize_promoter(raw.iat[detail_idx, promoter_col])
                    if not promoter:
                        continue
                    promoter_clean = clean_text(promoter)
                    if "TOTAL" in promoter_clean or "PROMOTOR" in promoter_clean:
                        break
                    rows.append(
                        {
                            "supervisor": str(sheet_name),
                            "foco": focus,
                            "promotor": promoter,
                            "objetivo": parse_number(raw.iat[detail_idx, objective_col]) if objective_col is not None else np.nan,
                            "planificado": parse_number(raw.iat[detail_idx, plan_col]),
                            "celda_planificacion": cell_name(detail_idx, plan_col),
                        }
                    )

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=["supervisor", "foco", "promotor", "objetivo", "planificado", "celda_planificacion"])
    return result.drop_duplicates(["supervisor", "foco", "promotor"], keep="last")


def save_to_sheet(webapp_url: str, selected_date: pd.Timestamp, focus: str, data: pd.DataFrame) -> dict[str, object]:
    rows = []
    for _, row in data.iterrows():
        planificado = pd.to_numeric(row.get("planificado"), errors="coerce")
        rows.append(
            {
                "fecha": selected_date.strftime("%Y-%m-%d"),
                "foco": focus,
                "promotor": normalize_promoter(row.get("promotor")),
                "planificado": "" if pd.isna(planificado) else float(planificado),
            }
        )
    payload = {"fecha": selected_date.strftime("%Y-%m-%d"), "foco": focus, "rows": rows}
    request = urllib.request.Request(
        webapp_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No pude conectar con Apps Script: {exc}") from exc
    result = json.loads(body)
    if not result.get("ok"):
        raise RuntimeError(result.get("error", body))
    if rows and int(result.get("escritos", 0)) == 0:
        raise RuntimeError("Apps Script respondio OK pero no escribio filas. Falta redeployar la ultima version del script.")
    return result


def page_style() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon=":memo:", layout="wide")
    st.markdown(
        """
        <style>
        .stApp {
            background: radial-gradient(circle at top right, #d9fbff 0, #f5f8ff 32%, #eef3fb 100%);
            color: #0f172a;
        }
        section[data-testid="stSidebar"] {
            background: #0f1b3d;
            color: #ffffff;
        }
        section[data-testid="stSidebar"] * { color: #ffffff !important; }
        .hero {
            padding: 28px 32px;
            border-radius: 10px;
            color: white;
            background: linear-gradient(120deg, #153e9f, #1463ff 54%, #06a3c7);
            box-shadow: 0 20px 45px rgba(20, 99, 255, .18);
            margin-bottom: 22px;
        }
        .hero h1 { margin: 0 0 8px 0; color: white; font-size: 34px; }
        .hero p { margin: 0; color: white; font-size: 16px; }
        div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 14px 34px rgba(15, 23, 42, .12);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    page_style()
    st.markdown(
        """
        <div class="hero">
            <h1>Planificador de promotores</h1>
            <p>Carga diaria de planificado por foco. El Google Sheet queda como base para que cualquier PC vea el mismo dato desde el dashboard.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    sheet_url = secret_or_env("PLANNER_GOOGLE_SHEET_URL", DEFAULT_SHEET_URL)
    webapp_url = secret_or_env("PLANNER_WEBAPP_URL", DEFAULT_WEBAPP_URL)

    st.sidebar.title("Configuracion")
    selected_date = pd.Timestamp(st.sidebar.date_input("Fecha de planificacion", value=pd.Timestamp.today().date()))
    if st.sidebar.button("Actualizar desde Sheet", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.sidebar.caption("Sheet conectado")
    st.sidebar.code(sheet_url, language=None)

    try:
        planning = load_sheet(sheet_url)
    except Exception as exc:
        st.error(f"No pude leer el Sheet de planificacion: {exc}")
        st.stop()

    if planning.empty:
        st.warning("El Sheet no devolvio promotores. Revisa que tenga los cuadros con Promotor / Objetivo / Planificacion.")
        st.stop()

    supervisor_options = ["Todos"] + sorted(planning["supervisor"].dropna().astype(str).unique().tolist())
    supervisor = st.sidebar.selectbox("Supervisor", supervisor_options)
    if supervisor != "Todos":
        planning = planning[planning["supervisor"].eq(supervisor)].copy()

    tabs = st.tabs(FOCUS_ORDER)
    for tab, focus in zip(tabs, FOCUS_ORDER):
        with tab:
            st.subheader(focus)
            focus_df = planning[planning["foco"].eq(focus)].copy()
            if focus_df.empty:
                st.info("No hay promotores para este foco.")
                continue

            focus_df["planificado"] = pd.to_numeric(focus_df["planificado"], errors="coerce").fillna(0.0)
            focus_df = focus_df.sort_values(["supervisor", "promotor"])
            edited = st.data_editor(
                focus_df[["supervisor", "promotor", "objetivo", "planificado", "celda_planificacion"]],
                key=f"editor_{focus}",
                hide_index=True,
                width="stretch",
                disabled=["supervisor", "promotor", "objetivo", "celda_planificacion"],
                column_config={
                    "supervisor": st.column_config.TextColumn("Supervisor"),
                    "promotor": st.column_config.TextColumn("Promotor"),
                    "objetivo": st.column_config.NumberColumn("Objetivo", format="%.1f"),
                    "planificado": st.column_config.NumberColumn("Planificado", min_value=0.0, step=0.1, format="%.1f"),
                    "celda_planificacion": st.column_config.TextColumn("Celda Sheet"),
                },
            )

            total_plan = float(pd.to_numeric(edited["planificado"], errors="coerce").fillna(0).sum())
            total_obj = float(pd.to_numeric(edited["objetivo"], errors="coerce").fillna(0).sum())
            c1, c2, c3 = st.columns(3)
            c1.metric("Promotores", len(edited))
            c2.metric("Objetivo", f"{total_obj:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."))
            c3.metric("Planificado", f"{total_plan:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."))

            if st.button("Guardar planificado en Sheet", key=f"save_{focus}", width="stretch"):
                try:
                    result = save_to_sheet(webapp_url, selected_date, focus, edited)
                    st.success(f"Guardado en Sheet. Filas escritas: {result.get('escritos', 0)}")
                    st.cache_data.clear()
                except Exception as exc:
                    st.error(f"No pude guardar en Sheet: {exc}")


if __name__ == "__main__":
    main()
