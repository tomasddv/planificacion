from __future__ import annotations

import json
import io
import os
import re
import shutil
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle

import app as sales_app


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
OBJECTIVE_CODE_FOCUS = {
    "2218": "TOTAL CERVEZAS",
    "19341": "TOTAL UNG",
    "18743": "AGUAS",
    "16667": "VOLUMEN ABOVE CORE",
}

FOCUS_ORDER = ["TOTAL CERVEZAS", "VOLUMEN ABOVE CORE", "TOTAL UNG", "AGUAS"]
SALES_FOCUS_MAP = {
    "TOTAL CERVEZAS": "Foco 1 - Total Cervezas 2026",
    "VOLUMEN ABOVE CORE": "Foco 2 - Above core 2026",
    "TOTAL UNG": "Foco 3 - Total UNG 2026",
    "AGUAS": "Foco 4 - Total Aguas 2026",
}
FOCUS_COLORS = {
    "TOTAL CERVEZAS": "#0b63ce",
    "VOLUMEN ABOVE CORE": "#7a5af8",
    "TOTAL UNG": "#16a34a",
    "AGUAS": "#06b6d4",
}
PROMOTER_ALIASES = {"ENZO VILLAGRA": "VILLAGRA ENZO"}
SUPERVISOR_ALIASES = {
    "VITI ANIBAL": "ANIBAL VITI",
}


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


def normalize_supervisor(value: object) -> str:
    text = clean_text(value)
    return SUPERVISOR_ALIASES.get(text, text)


def normalize_focus(value: object) -> str:
    text = clean_text(value)
    return FOCUS_ALIASES.get(text, "")


def normalize_objective_focus(description: object, code_value: object = "") -> str:
    focus = normalize_focus(description)
    if focus:
        return focus
    code_match = re.search(r"(\d+)", clean_text(code_value))
    if not code_match:
        return ""
    return OBJECTIVE_CODE_FOCUS.get(code_match.group(1), "")


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


def resolve_google_drive_folder(url: str, folder_name: str = "planificacion", force_refresh: bool = False) -> Path | None:
    if not url:
        return None
    target = PROJECT_ROOT / ".cloud_data" / folder_name
    refresh = force_refresh or str(secret_or_env("FORCE_GDRIVE_REFRESH", "false")).lower() in {"1", "true", "si", "sí", "yes"}
    if target.exists() and any(target.iterdir()) and not refresh:
        return target
    try:
        import gdown
    except ImportError:
        return target if target.exists() else None

    target.parent.mkdir(parents=True, exist_ok=True)
    download_target = target
    if refresh:
        download_target = PROJECT_ROOT / ".cloud_data" / f"{folder_name}_tmp_{int(time.time())}"
        if download_target.exists():
            shutil.rmtree(download_target, ignore_errors=True)
    download_target.mkdir(parents=True, exist_ok=True)

    try:
        gdown.download_folder(url=url, output=str(download_target), quiet=True, use_cookies=False)
    except Exception:
        return target if target.exists() and any(target.iterdir()) else None

    if refresh and download_target.exists() and any(download_target.iterdir()):
        try:
            if target.exists():
                shutil.rmtree(target)
            download_target.rename(target)
            return target
        except Exception:
            return download_target
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
                focus = normalize_objective_focus(row.iloc[1] if len(row) > 1 else "", row.iloc[0] if len(row) > 0 else "")
                if not focus:
                    continue
                for col, promoter in vendor_columns.items():
                    objective = parse_number(row.get(col))
                    if not pd.isna(objective):
                        rows.append({"promotor": promoter, "foco": focus, "objetivo_drive": objective})
            return pd.DataFrame(rows, columns=["promotor", "foco", "objetivo_drive"])

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
def load_drive_objectives(drive_url: str, refresh_nonce: float = 0.0) -> tuple[pd.DataFrame, str]:
    folder = resolve_google_drive_folder(drive_url, force_refresh=refresh_nonce > 0)
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


@st.cache_data(show_spinner=False, ttl=300)
def load_sales_from_drive(drive_url: str, refresh_nonce: float = 0.0) -> tuple[pd.DataFrame, str]:
    folder = resolve_google_drive_folder(drive_url, force_refresh=refresh_nonce > 0)
    if folder is None:
        return pd.DataFrame(), ""
    daily_file = sales_app.latest_daily_file_in_folder(folder)
    if daily_file is None:
        return pd.DataFrame(), ""
    df, _ = sales_app.load_source_from_path(str(daily_file), daily_file.stat().st_mtime_ns)

    customer_file = sales_app.latest_customer_file_in_folder(folder)
    if customer_file is not None:
        try:
            customer_channels, _ = sales_app.load_customer_channels(str(customer_file), customer_file.stat().st_mtime_ns)
            df = sales_app.apply_customer_channels(df, customer_channels)
        except Exception:
            pass

    aux_file = sales_app.latest_auxiliary_file_in_folder(folder)
    if aux_file is not None:
        try:
            aux_segments, _ = sales_app.load_auxiliary_segments(str(aux_file), aux_file.stat().st_mtime_ns)
            df = sales_app.apply_auxiliary_segments(df, aux_segments)
        except Exception:
            df = sales_app.apply_auxiliary_segments(df, None)
    else:
        df = sales_app.apply_auxiliary_segments(df, None)

    return sales_app.ensure_analysis_columns(df), daily_file.name


def focus_sales(sales: pd.DataFrame, focus: str) -> pd.DataFrame:
    focus_name = SALES_FOCUS_MAP[focus]
    result = sales.copy()
    for column, allowed in sales_app.PLANNER_FOCUS_RULES[focus_name].items():
        if column in {"title", "caption"}:
            continue
        if column in result.columns:
            result = result[result[column].astype(str).isin(allowed)]
    return result


def sales_metrics(sales: pd.DataFrame, focus: str, selected_date: pd.Timestamp) -> pd.DataFrame:
    if sales.empty:
        return pd.DataFrame(columns=["promotor", "real", "media_real", "acum_ant"])
    selected_date = pd.Timestamp(selected_date).normalize()
    df = focus_sales(sales, focus)
    real = (
        df[df["fecha"].eq(selected_date)]
        .groupby("promotor", as_index=False)["hl"]
        .sum()
        .rename(columns={"hl": "real"})
    )
    month_start = selected_date.replace(day=1)
    accum = (
        df[(df["fecha"] >= month_start) & (df["fecha"] <= selected_date)]
        .groupby("promotor", as_index=False)["hl"]
        .sum()
        .rename(columns={"hl": "acum_actual"})
    )
    accum_ant = (
        df[(df["fecha"] >= month_start) & (df["fecha"] < selected_date)]
        .groupby("promotor", as_index=False)["hl"]
        .sum()
        .rename(columns={"hl": "acum_ant"})
    )
    media = (
        df[df["fecha"] < selected_date]
        .groupby(["promotor", "fecha"], as_index=False)["hl"]
        .sum()
        .sort_values("fecha")
        .groupby("promotor", as_index=False)
        .tail(28)
        .groupby("promotor", as_index=False)["hl"]
        .mean()
        .rename(columns={"hl": "media_real"})
    )
    vendors = df[["promotor"]].drop_duplicates()
    result = (
        vendors.merge(real, on="promotor", how="left")
        .merge(accum, on="promotor", how="left")
        .merge(accum_ant, on="promotor", how="left")
        .merge(media, on="promotor", how="left")
    )
    result["promotor"] = result["promotor"].map(normalize_promoter)
    return result.fillna({"real": 0.0, "acum_actual": 0.0, "acum_ant": 0.0})


def build_focus_progress(edited: pd.DataFrame, days: pd.DataFrame, sales: pd.DataFrame, focus: str, selected_date: pd.Timestamp) -> pd.DataFrame:
    work = edited.copy()
    work["promotor_key"] = work["promotor"].map(normalize_promoter)
    work["objetivo"] = pd.to_numeric(work["objetivo"], errors="coerce").fillna(0.0)
    work["planificado"] = pd.to_numeric(work["planificado"], errors="coerce").fillna(0.0)

    metrics = sales_metrics(sales, focus, selected_date)
    metrics["promotor_key"] = metrics["promotor"].map(normalize_promoter)
    work = work.merge(metrics[["promotor_key", "real", "media_real", "acum_actual", "acum_ant"]], on="promotor_key", how="left")
    for column in ["real", "media_real", "acum_actual", "acum_ant"]:
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0.0)

    day_lookup = days[["supervisor", "restan"]].drop_duplicates("supervisor") if not days.empty else pd.DataFrame(columns=["supervisor", "restan"])
    work = work.merge(day_lookup, on="supervisor", how="left")
    work["media_necesaria"] = np.where(
        work["restan"].fillna(0) > 0,
        (work["objetivo"] - work["acum_ant"]).clip(lower=0) / work["restan"],
        np.nan,
    )
    work["avance"] = np.where(work["planificado"] > 0, work["real"] / work["planificado"] * 100, np.nan)
    work["avance_objetivo"] = np.where(work["objetivo"] > 0, work["acum_actual"] / work["objetivo"] * 100, np.nan)
    work["media_necesaria"] = pd.to_numeric(work["media_necesaria"], errors="coerce")
    work["vs_media_necesaria"] = np.where(work["media_necesaria"].fillna(0) > 0, work["real"] / work["media_necesaria"] * 100, np.nan)
    work["vs_media_real"] = np.where(work["media_real"].fillna(0) > 0, work["real"] / work["media_real"] * 100, np.nan)
    return work


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
def load_sheet(sheet_url: str, selected_date_key: str = "") -> pd.DataFrame:
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
                            "supervisor": normalize_supervisor(sheet_name),
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
    result = result.drop_duplicates(["supervisor", "foco", "promotor"], keep="last")
    db_plan = parse_planning_db(workbook, selected_date_key)
    if not db_plan.empty:
        result["promotor_key"] = result["promotor"].map(normalize_promoter)
        result["foco_key"] = result["foco"].map(normalize_focus)
        result = result.merge(
            db_plan[["promotor_key", "foco_key", "planificado_db"]],
            on=["promotor_key", "foco_key"],
            how="left",
        )
        result["planificado"] = result["planificado_db"].combine_first(result["planificado"])
        result = result.drop(columns=["promotor_key", "foco_key", "planificado_db"])
    return result


def sheet_date_key(value: object) -> str:
    if pd.isna(value):
        return ""
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=False)
    if pd.isna(parsed):
        parsed = pd.to_datetime(str(value), errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return clean_text(value)
    return pd.Timestamp(parsed).strftime("%Y-%m-%d")


def parse_planning_db(workbook: dict[str, pd.DataFrame], selected_date_key: str = "") -> pd.DataFrame:
    db_sheet = next((sheet for name, sheet in workbook.items() if clean_text(name) == "BD PLANIFICACION"), None)
    if db_sheet is None or db_sheet.empty:
        return pd.DataFrame(columns=["promotor_key", "foco_key", "planificado_db"])
    header = [clean_text(value) for value in db_sheet.iloc[0].tolist()]
    col_map = {name: idx for idx, name in enumerate(header)}
    required = {"FOCO", "PROMOTOR", "PLANIFICADO"}
    if not required.issubset(col_map):
        return pd.DataFrame(columns=["promotor_key", "foco_key", "planificado_db"])
    rows = []
    for _, row in db_sheet.iloc[1:].iterrows():
        if selected_date_key and "FECHA" in col_map and sheet_date_key(row.iloc[col_map["FECHA"]]) != selected_date_key:
            continue
        focus = normalize_focus(row.iloc[col_map["FOCO"]])
        promoter = normalize_promoter(row.iloc[col_map["PROMOTOR"]])
        plan = parse_number(row.iloc[col_map["PLANIFICADO"]])
        if focus and promoter and not pd.isna(plan):
            rows.append(
                {
                    "promotor_key": promoter,
                    "foco_key": focus,
                    "planificado_db": plan,
                }
            )
    if not rows:
        return pd.DataFrame(columns=["promotor_key", "foco_key", "planificado_db"])
    return pd.DataFrame(rows).drop_duplicates(["promotor_key", "foco_key"], keep="last")


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
        rows.append({"supervisor": normalize_supervisor(sheet_name), **days})
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


def complete_days(days: pd.DataFrame, planning: pd.DataFrame, selected_date: pd.Timestamp) -> pd.DataFrame:
    selected_date = pd.Timestamp(selected_date).normalize()
    supervisors = planning[["supervisor"]].drop_duplicates()
    result = supervisors.merge(days, on="supervisor", how="left") if not days.empty else supervisors.copy()
    month_start = selected_date.replace(day=1)
    auto_laborales = sales_app.selling_days_in_month(selected_date)
    auto_trabajados = sales_app.weighted_selling_days(month_start, selected_date - pd.Timedelta(days=1))
    auto_restan = sales_app.selling_days_remaining_from(selected_date)
    for column, value in {
        "dias_laborales": auto_laborales,
        "dias_trabajados": auto_trabajados,
        "restan": auto_restan,
    }.items():
        if column not in result.columns:
            result[column] = value
        else:
            result[column] = pd.to_numeric(result[column], errors="coerce").fillna(value)
    return result


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
            "avance": "Plan / obj.",
            "media_necesaria": "Media nec.",
            "vs_media_necesaria": "Vs media nec.",
        }
    )
    st.dataframe(display, hide_index=True, width="stretch")


def pct_class(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return "good" if float(value) >= 100 else "bad"


def render_progress_table(focus: str, progress: pd.DataFrame) -> None:
    headers = ["", "PLANIFICADO", "REAL", "AVANCE", "MEDIA NEC.", "MEDIA REAL", "VS MEDIA NEC.", "VS MEDIA REAL"]
    percent_cols = {"AVANCE", "VS MEDIA NEC.", "VS MEDIA REAL"}
    total = {
        "PLANIFICADO": progress["planificado"].sum(min_count=1),
        "REAL": progress["real"].sum(min_count=1),
        "MEDIA NEC.": progress["media_necesaria"].sum(min_count=1),
        "MEDIA REAL": progress["media_real"].sum(min_count=1),
    }
    total["AVANCE"] = total["REAL"] / total["PLANIFICADO"] * 100 if total["PLANIFICADO"] else np.nan
    total["VS MEDIA NEC."] = total["REAL"] / total["MEDIA NEC."] * 100 if total["MEDIA NEC."] else np.nan
    total["VS MEDIA REAL"] = total["REAL"] / total["MEDIA REAL"] * 100 if total["MEDIA REAL"] else np.nan

    rows = []
    total_cells = ["<td>TOTAL</td>"]
    for column in headers[1:]:
        cls = pct_class(total[column]) if column in percent_cols else ""
        value = f"{total[column]:.0f}%" if column in percent_cols and not pd.isna(total[column]) else format_number(total[column])
        total_cells.append(f"<td class='{cls}'>{value}</td>")
    rows.append(f"<tr class='total-row'>{''.join(total_cells)}</tr>")

    for supervisor, group in progress.groupby("supervisor", dropna=False):
        supervisor_cells = [f"<td>{supervisor}</td>"]
        for column in headers[1:]:
            supervisor_cells.append(f"<td>{column}</td>")
        rows.append(f"<tr class='mesa-row'>{''.join(supervisor_cells)}</tr>")

        supervisor_values = {
            "PLANIFICADO": group["planificado"].sum(min_count=1),
            "REAL": group["real"].sum(min_count=1),
            "MEDIA NEC.": group["media_necesaria"].sum(min_count=1),
            "MEDIA REAL": group["media_real"].sum(min_count=1),
        }
        supervisor_values["AVANCE"] = (
            supervisor_values["REAL"] / supervisor_values["PLANIFICADO"] * 100
            if supervisor_values["PLANIFICADO"]
            else np.nan
        )
        supervisor_values["VS MEDIA NEC."] = (
            supervisor_values["REAL"] / supervisor_values["MEDIA NEC."] * 100
            if supervisor_values["MEDIA NEC."]
            else np.nan
        )
        supervisor_values["VS MEDIA REAL"] = (
            supervisor_values["REAL"] / supervisor_values["MEDIA REAL"] * 100
            if supervisor_values["MEDIA REAL"]
            else np.nan
        )
        supervisor_total_cells = ["<td>TOTAL</td>"]
        for column in headers[1:]:
            cls = pct_class(supervisor_values[column]) if column in percent_cols else ""
            value = (
                f"{supervisor_values[column]:.0f}%"
                if column in percent_cols and not pd.isna(supervisor_values[column])
                else format_number(supervisor_values[column])
            )
            supervisor_total_cells.append(f"<td class='{cls}'>{value}</td>")
        rows.append(f"<tr class='supervisor-total-row'>{''.join(supervisor_total_cells)}</tr>")
        for _, row in group.sort_values("promotor").iterrows():
            values = [
                row["promotor"],
                format_number(row["planificado"]),
                format_number(row["real"]),
                "-" if pd.isna(row["avance"]) else f"{row['avance']:.0f}%",
                format_number(row["media_necesaria"]),
                format_number(row["media_real"]),
                "-" if pd.isna(row["vs_media_necesaria"]) else f"{row['vs_media_necesaria']:.0f}%",
                "-" if pd.isna(row["vs_media_real"]) else f"{row['vs_media_real']:.0f}%",
            ]
            cells = []
            for idx, value in enumerate(values):
                column = headers[idx]
                cls = pct_class(row[{
                    "AVANCE": "avance",
                    "VS MEDIA NEC.": "vs_media_necesaria",
                    "VS MEDIA REAL": "vs_media_real",
                }[column]]) if column in percent_cols else ""
                cells.append(f"<td class='{cls}'>{value}</td>")
            rows.append(f"<tr>{''.join(cells)}</tr>")

    header_cells = "".join(f"<th>{header}</th>" for header in headers)
    color = FOCUS_COLORS.get(focus, "#0b63ce")
    st.markdown(
        f"""
        <style>
        table.progress-table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            color: #0f172a;
            font-size: 14px;
            box-shadow: 0 14px 34px rgba(15,23,42,.12);
        }}
        table.progress-table th {{
            background: #0b78bd;
            color: white;
            border: 1px solid #111827;
            padding: 6px;
            text-align: center;
        }}
        table.progress-table td {{
            border: 1px solid #111827;
            padding: 5px 7px;
            text-align: right;
            font-weight: 700;
        }}
        table.progress-table td:first-child {{ text-align: left; }}
        table.progress-table .total-row td {{
            background: #d9e2f3;
            color: #111827;
            font-weight: 800;
        }}
        table.progress-table .mesa-row td {{
            background: #305caa;
            color: white;
            font-weight: 800;
            text-align: center;
        }}
        table.progress-table .mesa-row td:first-child {{
            text-align: center;
        }}
        table.progress-table .supervisor-total-row td {{
            background: #e8eef9;
            color: #0f172a;
            font-weight: 900;
        }}
        table.progress-table .good {{ background: #c6efce !important; color: #006100 !important; }}
        table.progress-table .bad {{ background: #ffc7ce !important; color: #9c0006 !important; }}
        .progress-title {{
            background: {color};
            color: white;
            padding: 7px;
            text-align: center;
            font-weight: 800;
            border: 1px solid #111827;
        }}
        </style>
        <div class="progress-title">{focus}</div>
        <table class="progress-table">
            <thead><tr>{header_cells}</tr></thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
        """,
        unsafe_allow_html=True,
    )


def planner_pdf_bytes(focus: str, selected_date: pd.Timestamp, edited: pd.DataFrame, summary: pd.DataFrame, progress: pd.DataFrame) -> bytes:
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

    progress_rows = [["Supervisor", "Promotor", "Planif.", "Real", "Avance", "Media nec.", "Media real", "Vs media", "Vs media real"]]
    for _, row in progress.sort_values(["supervisor", "promotor"]).iterrows():
        progress_rows.append(
            [
                row["supervisor"],
                row["promotor"],
                format_number(row["planificado"]),
                format_number(row["real"]),
                "-" if pd.isna(row["avance"]) else f"{row['avance']:.0f}%",
                format_number(row["media_necesaria"]),
                format_number(row["media_real"]),
                "-" if pd.isna(row["vs_media_necesaria"]) else f"{row['vs_media_necesaria']:.0f}%",
                "-" if pd.isna(row["vs_media_real"]) else f"{row['vs_media_real']:.0f}%",
            ]
        )
    progress_table = Table(progress_rows, colWidths=[95, 140, 58, 58, 58, 70, 70, 65, 75], repeatRows=1)
    progress_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b78bd")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
            ]
        )
    )
    elements.extend([progress_table, Spacer(1, 12)])

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


def all_focus_pdf_bytes(selected_date: pd.Timestamp, focus_payloads: list[dict[str, object]]) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=14,
        rightMargin=14,
        topMargin=14,
        bottomMargin=14,
    )
    elements = []
    main_title = Table([[f"PLANIFICACION PROMOTORES - {selected_date.strftime('%d/%m/%Y')}"]], colWidths=[810])
    main_title.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 15),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.extend([main_title, Spacer(1, 8)])

    for index, payload in enumerate(focus_payloads):
        focus = str(payload["focus"])
        progress = payload["progress"].copy()
        title = Table([[focus]], colWidths=[810])
        title.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(FOCUS_COLORS.get(focus, "#0b63ce"))),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 11),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        rows = [["Supervisor", "Promotor", "Planif.", "Real", "Avance", "Media nec.", "Media real", "Vs media", "Vs media real"]]
        for _, row in progress.sort_values(["supervisor", "promotor"]).iterrows():
            rows.append(
                [
                    row["supervisor"],
                    row["promotor"],
                    format_number(row["planificado"]),
                    format_number(row["real"]),
                    "-" if pd.isna(row["avance"]) else f"{row['avance']:.0f}%",
                    format_number(row["media_necesaria"]),
                    format_number(row["media_real"]),
                    "-" if pd.isna(row["vs_media_necesaria"]) else f"{row['vs_media_necesaria']:.0f}%",
                    "-" if pd.isna(row["vs_media_real"]) else f"{row['vs_media_real']:.0f}%",
                ]
            )
        table = Table(rows, colWidths=[95, 150, 60, 60, 55, 75, 75, 70, 80], repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#111827")),
            ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]
        for row_idx, (_, row) in enumerate(progress.sort_values(["supervisor", "promotor"]).iterrows(), start=1):
            for col_idx, col_name in ((4, "avance"), (7, "vs_media_necesaria"), (8, "vs_media_real")):
                value = row[col_name]
                if not pd.isna(value):
                    style.append(("BACKGROUND", (col_idx, row_idx), (col_idx, row_idx), colors.HexColor("#c6efce") if value >= 100 else colors.HexColor("#ffc7ce")))
        table.setStyle(TableStyle(style))
        elements.extend([title, table, Spacer(1, 8)])
        if index == 1 and len(focus_payloads) > 2:
            elements.append(PageBreak())

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
        .stApp, .stApp p, .stApp label, .stApp span, .stApp div, .stApp h1, .stApp h2, .stApp h3, .stApp h4 {
            color: #0f172a;
        }
        section[data-testid="stSidebar"] {
            background: #0f1b3d;
            color: #ffffff;
        }
        section[data-testid="stSidebar"] * { color: #ffffff !important; }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #d8e1ef;
            border-radius: 10px;
            padding: 12px;
            box-shadow: 0 12px 26px rgba(15, 23, 42, .08);
        }
        div[data-testid="stMetric"] * { color: #0f172a !important; }
        div[data-testid="stTabs"] button p { color: #0f172a !important; font-weight: 800; }
        div[data-testid="stTabs"] button[aria-selected="true"] p { color: #1463ff !important; }
        div[data-testid="stDataFrame"] *, div[data-testid="stDataEditor"] * {
            color: #0f172a !important;
        }
        input, textarea, [contenteditable="true"] {
            color: #0f172a !important;
            background: #ffffff !important;
        }
        .hero {
            padding: 28px 32px;
            border-radius: 10px;
            color: white;
            background: linear-gradient(120deg, #153e9f, #1463ff 54%, #06a3c7);
            box-shadow: 0 20px 45px rgba(20, 99, 255, .18);
            margin-bottom: 22px;
        }
        .hero, .hero * { color: #ffffff !important; }
        .hero h1 { margin: 0 0 8px 0; font-size: 34px; }
        .hero p { margin: 0; font-size: 16px; }
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
    if "drive_refresh_nonce" not in st.session_state:
        st.session_state["drive_refresh_nonce"] = 0.0
    if st.sidebar.button("Actualizar Drive y Sheet", width="stretch"):
        st.session_state["drive_refresh_nonce"] = time.time()
        st.cache_data.clear()
        st.sidebar.success("Actualizando desde Drive y Sheet...")
    st.sidebar.caption("Sheet conectado")
    st.sidebar.code(sheet_url, language=None)

    try:
        refresh_nonce = float(st.session_state.get("drive_refresh_nonce", 0.0))
        drive_objectives, objective_label = load_drive_objectives(drive_url, refresh_nonce)
        sales, sales_label = load_sales_from_drive(drive_url, refresh_nonce)
        sheet_days = load_sheet_days(sheet_url)
    except Exception as exc:
        st.error(f"No pude leer las fuentes del planificador: {exc}")
        st.stop()

    if not sales.empty:
        latest_invoice_date = pd.Timestamp(sales["fecha"].dropna().max()).normalize()
        default_date = sales_app.next_selling_day(latest_invoice_date)
        st.sidebar.caption(f"Ultima facturacion: {latest_invoice_date.strftime('%d/%m/%Y')}")
    else:
        default_date = pd.Timestamp.today().normalize()
    selected_date = pd.Timestamp(
        st.sidebar.date_input("Fecha de planificacion", value=pd.Timestamp(default_date).date())
    ).normalize()
    selected_date_key = selected_date.strftime("%Y-%m-%d")

    try:
        planning = load_sheet(sheet_url, selected_date_key)
        st.session_state["drive_refresh_nonce"] = 0.0
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
    if not sales.empty:
        st.sidebar.success(f"Venta diaria: {sales_label}")
    else:
        st.sidebar.warning("No encontre venta diaria para calcular REAL y MEDIA REAL.")
    if not sales.empty and selected_date not in set(sales["fecha"].dropna().dt.normalize()):
        st.sidebar.warning("La fecha seleccionada no existe en venta diaria. REAL se muestra en 0.")

    supervisor_options = ["Todos"] + sorted(planning["supervisor"].dropna().astype(str).unique().tolist())
    supervisor = st.sidebar.selectbox("Supervisor", supervisor_options)
    if supervisor != "Todos":
        planning = planning[planning["supervisor"].eq(supervisor)].copy()
        sheet_days = sheet_days[sheet_days["supervisor"].eq(supervisor)].copy()
    sheet_days = complete_days(sheet_days, planning, selected_date)

    focus_payloads: list[dict[str, object]] = []
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
            progress = build_focus_progress(edited, sheet_days, sales, focus, selected_date)
            total_acum = float(pd.to_numeric(progress["acum_actual"], errors="coerce").fillna(0).sum())
            avance_objetivo = (total_acum / total_obj * 100) if total_obj else np.nan
            media_necesaria_total = float(pd.to_numeric(progress["media_necesaria"], errors="coerce").fillna(0).sum())
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Promotores", len(edited))
            c2.metric("Objetivo", f"{total_obj:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."))
            c3.metric("Planificado", f"{total_plan:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."))
            c4.metric("Avance", "-" if pd.isna(avance_objetivo) else f"{avance_objetivo:.0f}%".replace(".", ","))
            c5.metric("Media nec.", format_number(media_necesaria_total))

            st.markdown("#### Medias y avances")
            render_summary(summary)

            focus_payloads.append({"focus": focus, "edited": edited.copy(), "summary": summary.copy(), "progress": progress.copy()})
            st.markdown("#### Avance del dia")
            render_progress_table(focus, progress)

            if st.button("Guardar planificado en Sheet", key=f"save_{focus}", width="stretch"):
                try:
                    result = save_to_sheet(webapp_url, selected_date, focus, edited)
                    escritos = int(result.get("escritos", 0))
                    if escritos > 0:
                        st.success(f"Guardado en Sheet. Filas escritas: {escritos}")
                    else:
                        st.warning(
                            "Apps Script respondio, pero no escribio filas. "
                            "Pega y redeploya la ultima version de crear_sheet_planificacion.gs."
                        )
                    st.cache_data.clear()
                except Exception as exc:
                    st.error(f"No pude guardar en Sheet: {exc}")

    if focus_payloads:
        st.divider()
        if supervisor != "Todos":
            st.caption("Con filtro de supervisor activo, el guardado global escribe solo los promotores visibles.")
        if st.button("Guardar todos los focos visibles en Sheet", type="primary", width="stretch"):
            try:
                total_escritos = 0
                errores: list[str] = []
                for payload in focus_payloads:
                    result = save_to_sheet(webapp_url, selected_date, str(payload["focus"]), payload["edited"])
                    total_escritos += int(result.get("escritos", 0))
                    errores.extend(str(item) for item in result.get("errores", []) if item)
                if total_escritos > 0:
                    st.success(f"Guardado completo en Sheet. Filas escritas: {total_escritos}")
                    st.cache_data.clear()
                else:
                    st.warning(
                        "Apps Script respondio, pero no escribio filas. "
                        "Pega y redeploya la ultima version de crear_sheet_planificacion.gs."
                    )
                if errores:
                    st.warning("Algunas filas no pudieron reflejarse en las celdas visuales, pero se guardaron en BD_PLANIFICACION.")
                    with st.expander("Detalle de avisos"):
                        st.write(errores)
            except Exception as exc:
                st.error(f"No pude guardar todos los focos en Sheet: {exc}")

        st.download_button(
            "Exportar PDF completo - 4 focos",
            data=all_focus_pdf_bytes(selected_date, focus_payloads),
            file_name=f"planificacion_promotores_{selected_date.strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            width="stretch",
        )


if __name__ == "__main__":
    main()
