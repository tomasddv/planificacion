from __future__ import annotations

import json
import io
import os
import re
import shutil
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle


APP_TITLE = "Planificador de promotores"
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/15ITRhsY5mvK3NSHeOKV2MymC078pT9TPAwKUdZDfjnI/edit?usp=sharing"
DEFAULT_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbwDlxEbBN2kmy5oVtb4LJiPFN0KtAZw-nI9TolDtfOIVuMxQqIZprMB1pquTesPGYHe/exec"
DEFAULT_BIG_DASH_URL = "https://planificacionddv.streamlit.app/"
DEFAULT_SMALL_DASH_URL = "https://planificacion-ifeevprb7is4zwjk6k5suo.streamlit.app/"
DEFAULT_DRIVE_URL = "https://drive.google.com/drive/folders/1cukgXLUaPsEDK_yD7tSwgaBFZAbiDUot?usp=drive_link"
PROJECT_ROOT = Path(__file__).resolve().parent

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
    text = re.sub(r"^\d+\s+", "", text)
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


def resolve_google_drive_folder(url: str, folder_name: str = "planificacion") -> Path | None:
    if not url:
        return None
    target = PROJECT_ROOT / ".cloud_data" / folder_name
    refresh = str(secret_or_env("FORCE_GDRIVE_REFRESH", "false")).lower() in {"1", "true", "si", "sí", "yes"}
    if target.exists() and any(target.iterdir()) and not refresh:
        return target
    try:
        import gdown
    except ImportError:
        return target if target.exists() else None
    if target.exists() and refresh:
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    try:
        gdown.download_folder(url=url, output=str(target), quiet=True, use_cookies=False)
    except Exception:
        return target if any(target.iterdir()) else None
    return target


def latest_objectives_file(folder: Path | None) -> Path | None:
    if folder is None or not folder.exists():
        return None
    candidates = [
        path for path in folder.iterdir()
        if path.is_file()
        and not path.name.startswith("~$")
        and path.suffix.lower() in {".xlsx", ".xls", ".csv", ".txt"}
        and "OBJET" in clean_text(path.stem)
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def parse_objectives_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        source = pd.read_excel(path, sheet_name=0, header=None)
        rows: list[dict[str, object]] = []
        header_index = None
        for index, row in source.iterrows():
            values = row.fillna("").astype(str).tolist()
            if any("DESCRIPCION" in clean_text(value) for value in values) and sum("-" in value for value in values) >= 2:
                header_index = index
                break
        if header_index is not None:
            header = source.loc[header_index]
            vendor_columns = {
                col: normalize_promoter(value)
                for col, value in header.items()
                if col >= 2 and "-" in str(value) and normalize_promoter(value)
            }
            for _, row in source.loc[header_index + 1 :].iterrows():
                focus = normalize_focus(row.iloc[1] if len(row) > 1 else "")
                if not focus:
                    continue
                for col, promoter in vendor_columns.items():
                    objective = parse_number(row.get(col))
                    if not pd.isna(objective):
                        rows.append({"promotor": promoter, "foco": focus, "objetivo_drive": objective})
            return pd.DataFrame(rows)

        table = pd.read_excel(path, dtype="string")
    else:
        table = pd.read_csv(path, sep=None, engine="python", dtype="string")

    columns = {clean_text(col): col for col in table.columns}
    promoter_col = next((col for key, col in columns.items() if "VENDEDOR" in key or "PROMOTOR" in key), None)
    focus_col = next((col for key, col in columns.items() if "FOCO" in key or "SEGMENTO" in key or "DIVISION" in key), None)
    objective_col = next((col for key, col in columns.items() if "OBJET" in key), None)
    if promoter_col is None or objective_col is None:
        return pd.DataFrame(columns=["promotor", "foco", "objetivo_drive"])
    return pd.DataFrame(
        {
            "promotor": table[promoter_col].map(normalize_promoter),
            "foco": table[focus_col].map(normalize_focus) if focus_col else "",
            "objetivo_drive": table[objective_col].map(parse_number),
        }
    ).dropna(subset=["objetivo_drive"])


@st.cache_data(show_spinner=False, ttl=300)
def load_drive_objectives(drive_url: str) -> tuple[pd.DataFrame, str]:
    folder = resolve_google_drive_folder(drive_url)
    path = latest_objectives_file(folder)
    if path is None:
        return pd.DataFrame(columns=["promotor", "foco", "objetivo_drive"]), ""
    return parse_objectives_file(path), path.name


def apply_drive_objectives(planning: pd.DataFrame, objectives: pd.DataFrame) -> pd.DataFrame:
    if objectives.empty:
        return planning
    result = planning.copy()
    result["promotor_key"] = result["promotor"].map(normalize_promoter)
    result["foco_key"] = result["foco"].map(normalize_focus)
    lookup = objectives.copy()
    lookup["promotor_key"] = lookup["promotor"].map(normalize_promoter)
    lookup["foco_key"] = lookup["foco"].map(normalize_focus)
    lookup = lookup.drop_duplicates(["promotor_key", "foco_key"], keep="last")
    result = result.merge(
        lookup[["promotor_key", "foco_key", "objetivo_drive"]],
        on=["promotor_key", "foco_key"],
        how="left",
    )
    result["objetivo"] = result["objetivo_drive"].combine_first(result["objetivo"])
    return result.drop(columns=["promotor_key", "foco_key", "objetivo_drive"])


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


@st.cache_data(show_spinner=False, ttl=120)
def load_sheet_days(sheet_url: str) -> pd.DataFrame:
    workbook = pd.read_excel(google_sheet_export_url(sheet_url), sheet_name=None, header=None)
    rows: list[dict[str, object]] = []
    for sheet_name, sheet in workbook.items():
        if sheet.empty or clean_text(sheet_name) == "BD PLANIFICACION":
            continue
        values = sheet.fillna("")
        days = {"dias_laborales": np.nan, "dias_trabajados": np.nan, "restan": np.nan}
        for row_idx in range(min(8, len(values))):
            label = clean_text(values.iat[row_idx, 0] if len(values.columns) else "")
            value = values.iat[row_idx, 1] if len(values.columns) > 1 else np.nan
            if "DIAS LABORALES" in label:
                days["dias_laborales"] = parse_number(value)
            elif "DIAS TRABAJADOS" in label:
                days["dias_trabajados"] = parse_number(value)
            elif "RESTAN" in label:
                days["restan"] = parse_number(value)
        rows.append({"supervisor": str(sheet_name), **days})
    return pd.DataFrame(rows)


def build_summary(edited: pd.DataFrame, days: pd.DataFrame) -> pd.DataFrame:
    work = edited.copy()
    work["objetivo"] = pd.to_numeric(work["objetivo"], errors="coerce").fillna(0.0)
    work["planificado"] = pd.to_numeric(work["planificado"], errors="coerce").fillna(0.0)
    summary = (
        work.groupby("supervisor", as_index=False)
        .agg(
            promotores=("promotor", "nunique"),
            objetivo=("objetivo", "sum"),
            planificado=("planificado", "sum"),
        )
        .merge(days, on="supervisor", how="left")
    )
    summary["avance"] = np.where(summary["objetivo"] > 0, summary["planificado"] / summary["objetivo"] * 100, np.nan)
    summary["media_necesaria"] = np.where(summary["restan"] > 0, summary["objetivo"] / summary["restan"], np.nan)
    summary["vs_media_necesaria"] = np.where(
        summary["media_necesaria"] > 0,
        summary["planificado"] / summary["media_necesaria"] * 100,
        np.nan,
    )
    total = {
        "supervisor": "TOTAL",
        "promotores": summary["promotores"].sum(),
        "objetivo": summary["objetivo"].sum(),
        "planificado": summary["planificado"].sum(),
        "dias_laborales": np.nan,
        "dias_trabajados": np.nan,
        "restan": summary["restan"].max(skipna=True),
    }
    total["avance"] = total["planificado"] / total["objetivo"] * 100 if total["objetivo"] else np.nan
    total["media_necesaria"] = total["objetivo"] / total["restan"] if total["restan"] else np.nan
    total["vs_media_necesaria"] = total["planificado"] / total["media_necesaria"] * 100 if total["media_necesaria"] else np.nan
    return pd.concat([summary, pd.DataFrame([total])], ignore_index=True)


def format_number(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def render_summary(summary: pd.DataFrame) -> None:
    display = summary.copy()
    for column in ["objetivo", "planificado", "media_necesaria"]:
        display[column] = display[column].map(format_number)
    for column in ["avance", "vs_media_necesaria"]:
        display[column] = display[column].map(lambda value: "-" if pd.isna(value) else f"{float(value):.0f}%".replace(".", ","))
    for column in ["dias_laborales", "dias_trabajados", "restan"]:
        display[column] = display[column].map(format_number)
    display = display.rename(
        columns={
            "supervisor": "Supervisor",
            "promotores": "Promotores",
            "objetivo": "Objetivo",
            "planificado": "Planificado",
            "dias_laborales": "Dias laborales",
            "dias_trabajados": "Dias trabajados",
            "restan": "Restan",
            "avance": "Avance",
            "media_necesaria": "Media nec.",
            "vs_media_necesaria": "Vs media nec.",
        }
    )
    st.dataframe(display, hide_index=True, width="stretch")


def planner_pdf_bytes(focus: str, selected_date: pd.Timestamp, edited: pd.DataFrame, summary: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=18,
        rightMargin=18,
        topMargin=18,
        bottomMargin=18,
    )
    elements = []
    title = Table([[f"PLANIFICACION PROMOTORES - {focus} - {selected_date.strftime('%d/%m/%Y')}"]], colWidths=[800])
    title.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(FOCUS_COLORS.get(focus, "#0b63ce"))),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 16),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    elements.extend([title, Spacer(1, 10)])

    summary_rows = [["Supervisor", "Prom.", "Objetivo", "Planificado", "Restan", "Avance", "Media nec.", "Vs media"]]
    for _, row in summary.iterrows():
        summary_rows.append(
            [
                row["supervisor"],
                int(row["promotores"]) if not pd.isna(row["promotores"]) else "",
                format_number(row["objetivo"]),
                format_number(row["planificado"]),
                format_number(row["restan"]),
                "-" if pd.isna(row["avance"]) else f"{row['avance']:.0f}%",
                format_number(row["media_necesaria"]),
                "-" if pd.isna(row["vs_media_necesaria"]) else f"{row['vs_media_necesaria']:.0f}%",
            ]
        )
    summary_table = Table(summary_rows, colWidths=[120, 45, 80, 80, 55, 65, 80, 70], repeatRows=1)
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f5597")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.extend([summary_table, Spacer(1, 12)])

    detail_rows = [["Supervisor", "Promotor", "Objetivo", "Planificado", "Celda"]]
    detail = edited.copy()
    detail["objetivo"] = pd.to_numeric(detail["objetivo"], errors="coerce").fillna(0)
    detail["planificado"] = pd.to_numeric(detail["planificado"], errors="coerce").fillna(0)
    for _, row in detail.sort_values(["supervisor", "promotor"]).iterrows():
        detail_rows.append(
            [
                row["supervisor"],
                row["promotor"],
                format_number(row["objetivo"]),
                format_number(row["planificado"]),
                row["celda_planificacion"],
            ]
        )
    detail_table = Table(detail_rows, colWidths=[120, 180, 80, 80, 70], repeatRows=1)
    detail_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.append(detail_table)
    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()


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
    drive_url = secret_or_env("GOOGLE_DRIVE_PLANIFICACION_URL", DEFAULT_DRIVE_URL)
    big_dash_url = secret_or_env("BIG_DASH_URL", DEFAULT_BIG_DASH_URL)

    st.sidebar.title("Configuracion")
    st.sidebar.link_button("Ir al dash de ventas", big_dash_url, width="stretch")
    selected_date = pd.Timestamp(st.sidebar.date_input("Fecha de planificacion", value=pd.Timestamp.today().date()))
    if st.sidebar.button("Actualizar desde Sheet", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.sidebar.caption("Sheet conectado")
    st.sidebar.code(sheet_url, language=None)

    try:
        planning = load_sheet(sheet_url)
        sheet_days = load_sheet_days(sheet_url)
        drive_objectives, objective_label = load_drive_objectives(drive_url)
    except Exception as exc:
        st.error(f"No pude leer el Sheet de planificacion: {exc}")
        st.stop()

    if planning.empty:
        st.warning("El Sheet no devolvio promotores. Revisa que tenga los cuadros con Promotor / Objetivo / Planificacion.")
        st.stop()

    if not drive_objectives.empty:
        planning = apply_drive_objectives(planning, drive_objectives)
        st.sidebar.success(f"Objetivos: {objective_label}")
    else:
        st.sidebar.warning("No encontre objetivos por promotor en Drive.")

    supervisor_options = ["Todos"] + sorted(planning["supervisor"].dropna().astype(str).unique().tolist())
    supervisor = st.sidebar.selectbox("Supervisor", supervisor_options)
    if supervisor != "Todos":
        planning = planning[planning["supervisor"].eq(supervisor)].copy()
        sheet_days = sheet_days[sheet_days["supervisor"].eq(supervisor)].copy()

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
            summary = build_summary(edited, sheet_days)
            total_row = summary[summary["supervisor"].eq("TOTAL")].iloc[0]
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Promotores", len(edited))
            c2.metric("Objetivo", f"{total_obj:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."))
            c3.metric("Planificado", f"{total_plan:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."))
            c4.metric("Avance", "-" if pd.isna(total_row["avance"]) else f"{total_row['avance']:.0f}%".replace(".", ","))
            c5.metric("Media nec.", format_number(total_row["media_necesaria"]))

            st.markdown("#### Medias y avances")
            render_summary(summary)
            st.download_button(
                "Exportar PDF del foco",
                data=planner_pdf_bytes(focus, selected_date, edited, summary),
                file_name=f"planificacion_{focus.lower().replace(' ', '_')}_{selected_date.strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                width="stretch",
            )

            if st.button("Guardar planificado en Sheet", key=f"save_{focus}", width="stretch"):
                try:
                    result = save_to_sheet(webapp_url, selected_date, focus, edited)
                    st.success(f"Guardado en Sheet. Filas escritas: {result.get('escritos', 0)}")
                    st.cache_data.clear()
                except Exception as exc:
                    st.error(f"No pude guardar en Sheet: {exc}")


if __name__ == "__main__":
    main()
