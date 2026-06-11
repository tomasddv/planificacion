from __future__ import annotations

import io
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

try:
    import holidays
except ImportError:  # pragma: no cover
    holidays = None


APP_TITLE = "Venta diaria HL"
PROJECT_ROOT = Path(__file__).resolve().parent
VALID_EXTENSIONS = {".txt", ".csv"}
EXTRA_EXTENSIONS = {".txt", ".csv", ".xlsx", ".xls"}
PLANNER_STORE_FILE_NAME = "planificador_diario_guardado.csv"

DATA_DIR_CANDIDATES = [
    PROJECT_ROOT / "planificacion",
    PROJECT_ROOT / "data",
    Path(os.environ.get("DASHBOARDS_ROOT", "N:/Tomas/DASHBOARDS")) / "planificacion",
    Path("N:/tomas/dashboards/planificacion"),
    Path.home() / "Desktop" / "planificacion",
]

PROMOTER_MESA_MAP = {
    "NICASTRO LUCAS": "ismael bruno",
    "SIRI MARTIN": "ismael bruno",
    "MATIAS GARCIA": "ismael bruno",
    "GASTON FABRE": "ismael bruno",
    "NICOLAS POCHETINO": "ismael bruno",
    "VILLAGRA ENZO": "ismael bruno",
    "FEDERICO BISS": "anibal viti",
    "PABLO ALVAREZ": "casco hernan",
    "ALEXANDER ROJAS": "casco hernan",
    "FERNANDO FIELG": "casco hernan",
    "JUAN MANUEL GIMENEZ": "casco hernan",
    "MENDEZ CARLOS": "casco hernan",
    "MARIANO HERRERA": "casco hernan",
}

PLANNER_FOCUS_RULES = {
    "Foco 1 - Total Cervezas 2026": {
        "title": "TOTAL CZA",
        "caption": "CERVEZAS, GIFTPACK CERVEZAS, POP",
        "unidad_negocio": {"CZA"},
    },
    "Foco 2 - Above core 2026": {
        "title": "ABOVE CORE",
        "caption": "CERVEZAS, GIFTPACK CERVEZAS, SIDRAS, POP",
        "division_informe": {"CVZA HE", "CVZA CORE +"},
    },
    "Foco 3 - Total UNG 2026": {
        "title": "TOTAL UNG",
        "caption": "UNG",
        "unidad_negocio": {"UNG"},
    },
    "Foco 4 - Total Aguas 2026": {
        "title": "TOTAL AGUAS",
        "caption": "GASEOSAS, AGUAS, POP AGUAS",
        "division_informe": {"AGUAS ECO"},
    },
}

PLANNER_OBJECTIVE_ALIASES = {
    "TOTAL CZA": "Foco 1 - Total Cervezas 2026",
    "TOTAL CVZA": "Foco 1 - Total Cervezas 2026",
    "TOTAL CERVEZAS": "Foco 1 - Total Cervezas 2026",
    "ABOVE CORE": "Foco 2 - Above core 2026",
    "TOTAL UNG": "Foco 3 - Total UNG 2026",
    "UNG": "Foco 3 - Total UNG 2026",
    "AGUAS": "Foco 4 - Total Aguas 2026",
    "TOTAL AGUAS": "Foco 4 - Total Aguas 2026",
    "AGUAS ECO": "Foco 4 - Total Aguas 2026",
}

DIVISION_ORDER = [
    "HL TOTALES",
    "TOTAL CVZA",
    "TOTAL UNG",
    "CVZA CORE + VALUE",
    "CVZA CORE",
    "CVZA VALUE",
    "CVZA CORE +",
    "CVZA HE",
    "UNG SIN TOP",
    "UNG TOP",
    "AGUAS ECO",
    "VINO",
    "ADYACENCIAS",
]

DEFAULT_OBJECTIVES = {
    "TOTAL CVZA": 3633.51,
    "TOTAL CZA": 3633.51,
    "TOTAL UNG": 2923.65,
    "CVZA HE": 952.22,
    "CVZA CORE + VALUE": 2681.29,
    "AGUAS ECO": 240.84,
}


@dataclass(frozen=True)
class SourceInfo:
    label: str
    path: str | None = None
    modified: str | None = None


def clean_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def secret_or_env(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, default)).strip()


def truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "y"}


def resolve_google_drive_folder(secret_name: str, folder_name: str) -> Path | None:
    url = secret_or_env(secret_name)
    if not url:
        return None

    target = PROJECT_ROOT / ".cloud_data" / folder_name
    refresh = truthy(secret_or_env("FORCE_GDRIVE_REFRESH", "false"))
    if target.exists() and any(target.iterdir()) and not refresh:
        return target

    try:
        import gdown
    except ImportError:
        st.sidebar.warning("Falta instalar gdown para leer datos desde Google Drive.")
        return target if target.exists() and any(target.iterdir()) else None

    tmp_target = PROJECT_ROOT / ".cloud_data" / f"{folder_name}_tmp"
    if tmp_target.exists():
        shutil.rmtree(tmp_target)
    tmp_target.parent.mkdir(parents=True, exist_ok=True)

    try:
        files = gdown.download_folder(url=url, output=str(tmp_target), quiet=True, use_cookies=False)
    except Exception as exc:
        st.sidebar.warning(
            "No pude descargar la carpeta de Google Drive. "
            "Revisa que el link sea publico: Cualquier persona con el enlace puede ver. "
            f"Detalle: {exc}"
        )
        return target if target.exists() and any(target.iterdir()) else None

    if tmp_target.exists() and any(tmp_target.iterdir()) and files is not None:
        if target.exists():
            shutil.rmtree(target)
        tmp_target.rename(target)
        return target
    return target if target.exists() and any(target.iterdir()) else None


def data_dir() -> Path:
    drive = resolve_google_drive_folder("GOOGLE_DRIVE_PLANIFICACION_URL", "planificacion")
    if drive is not None and drive.exists():
        return drive
    return next((path for path in DATA_DIR_CANDIDATES if path.exists()), DATA_DIR_CANDIDATES[0])


def excel_col_to_index(letter: str) -> int:
    value = 0
    for char in letter.upper():
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def make_unique_columns(columns: list[object]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for index, column in enumerate(columns):
        base = clean_name(column) or f"col_{index}"
        seen[base] = seen.get(base, 0) + 1
        result.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return result


def read_tabular(path_or_file, name: str | None = None) -> pd.DataFrame:
    suffix = Path(name or str(path_or_file)).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path_or_file, dtype="string")
    for encoding in ("utf-8-sig", "latin1", "cp1252"):
        try:
            return pd.read_csv(path_or_file, sep="\t", dtype="string", encoding=encoding, engine="python", on_bad_lines="skip")
        except Exception:
            continue
    return pd.read_csv(path_or_file, sep=None, dtype="string", engine="python", on_bad_lines="skip")


def parse_argentine_number(series: pd.Series) -> pd.Series:
    text = series.astype("string").fillna("").str.strip()
    text = text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    text = text.str.replace(r"[^0-9.\-]", "", regex=True)
    return pd.to_numeric(text, errors="coerce")


def parse_objective_cell(value: object) -> float:
    if value is None or pd.isna(value):
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    text = str(value).strip()
    if not text:
        return np.nan
    if "," in text:
        return float(parse_argentine_number(pd.Series([text])).iloc[0])
    return float(pd.to_numeric(text, errors="coerce"))


def parse_period_date(series: pd.Series) -> pd.Series:
    text = series.astype("string").fillna("").str.strip()
    parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    numeric = text.str.replace(r"[^0-9]", "", regex=True)
    mask = parsed.isna() & numeric.str.len().between(6, 8)
    if mask.any():
        parsed.loc[mask] = pd.to_datetime(numeric.loc[mask], format="%Y%m%d", errors="coerce")
        still = parsed.isna() & mask
        parsed.loc[still] = pd.to_datetime(numeric.loc[still], format="%d%m%Y", errors="coerce")
    return parsed.dt.normalize()


def first_present(df: pd.DataFrame, patterns: list[str], fallback_letter: str | None = None) -> pd.Series:
    for pattern in patterns:
        for col in df.columns:
            if pattern in col:
                return df[col]
    if fallback_letter:
        idx = excel_col_to_index(fallback_letter)
        if idx < len(df.columns):
            return df.iloc[:, idx]
    return pd.Series(pd.NA, index=df.index, dtype="string")


def latest_matching_file(folder: Path, include: tuple[str, ...], exclude: tuple[str, ...], extensions=EXTRA_EXTENSIONS) -> Path | None:
    if not folder.exists():
        return None
    files = []
    for path in folder.iterdir():
        name = clean_name(path.stem)
        if path.is_file() and not path.name.startswith("~$") and path.suffix.lower() in extensions:
            if all(term in name for term in include) and not any(term in name for term in exclude):
                files.append(path)
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def latest_daily_file(folder: Path) -> Path | None:
    return latest_matching_file(folder, ("venta",), ("anual",), VALID_EXTENSIONS) or latest_matching_file(folder, tuple(), ("anual",), VALID_EXTENSIONS)


def latest_annual_file(folder: Path) -> Path | None:
    return latest_matching_file(folder, ("anual",), tuple(), VALID_EXTENSIONS)


def latest_customer_file(folder: Path) -> Path | None:
    return latest_matching_file(folder, ("cliente",), tuple())


def latest_aux_file(folder: Path) -> Path | None:
    return latest_matching_file(folder, ("auxiliar",), tuple())


def latest_objectives_file(folder: Path) -> Path | None:
    return latest_matching_file(folder, ("objet",), tuple())


def normalize_vendor_name(value: object) -> str:
    text = str(value or "").strip()
    if "-" in text:
        text = text.split("-", 1)[1]
    return re.sub(r"\s+", " ", text).strip().upper()


def normalize_business(value: object) -> str:
    text = clean_name(value).upper()
    if "UNG" in text:
        return "UNG"
    if "CZA" in text or "CVZA" in text or "CERVE" in text:
        return "CZA"
    if "AGUA" in text or "GASE" in text:
        return "AGUAS ECO"
    if "VINO" in text:
        return "VINO"
    return str(value or "Sin negocio").strip().upper()


@st.cache_data(show_spinner=False)
def load_source_from_path(path_text: str, modified_ns: int) -> tuple[pd.DataFrame, SourceInfo]:
    path = Path(path_text)
    raw = read_tabular(path)
    df = normalize(raw)
    info = SourceInfo(path.name, str(path), pd.to_datetime(modified_ns, unit="ns").strftime("%d/%m/%Y %H:%M"))
    return df, info


def load_source_from_upload(name: str, content: bytes) -> tuple[pd.DataFrame, SourceInfo]:
    raw = read_tabular(io.BytesIO(content), name)
    return normalize(raw), SourceInfo(name)


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df.columns = make_unique_columns(list(df.columns))
    fecha = parse_period_date(first_present(df, ["descripcion_periodo", "desc_periodo"], "C"))
    if fecha.isna().all():
        fecha = parse_period_date(first_present(df, ["cod_periodo", "periodo"], "A"))

    vendedor = first_present(df, ["descripcion_vendedor", "desc_vendedor", "vendedor"], None)
    negocio_raw = first_present(df, ["unidad_negocio", "negocio", "descripcion_12"], None)
    hl = parse_argentine_number(first_present(df, ["cantidades_totales", "cantidad_total", "hl"], "AO"))
    normalized = pd.DataFrame(
        {
            "fecha": fecha,
            "cliente_codigo": first_present(df, ["cod_cliente", "cliente_codigo"], "E").astype("string"),
            "cliente": first_present(df, ["descripcion_cliente", "cliente", "descripcion"], "F").astype("string"),
            "ruta_codigo": first_present(df, ["cod_ruta", "ruta_codigo", "ruta"], "I").astype("string"),
            "ruta": first_present(df, ["descripcion_ruta", "ruta_desc", "descripcion_1"], "J").astype("string"),
            "supervisor": first_present(df, ["supervisor"], None).fillna("Sin supervisor").astype(str).str.strip(),
            "promotor": vendedor.fillna("Sin vendedor").astype(str).map(normalize_vendor_name),
            "calibre": first_present(df, ["calibre", "descripcion_calibre"], "X").fillna("Sin calibre").astype(str).str.strip().str.upper(),
            "marca": first_present(df, ["marca", "descripcion_marca"], None).fillna("").astype(str).str.strip().str.upper(),
            "unidad_negocio": negocio_raw.map(normalize_business),
            "hl": hl.fillna(0.0),
        }
    )
    normalized = normalized.dropna(subset=["fecha"])
    normalized = normalized[normalized["fecha"].dt.weekday <= 5].copy()
    normalized["mesa"] = normalized["promotor"].map(PROMOTER_MESA_MAP).fillna("Sin mesa")
    normalized["canal"] = "NO"
    normalized["division_informe"] = normalized["unidad_negocio"].replace({"CZA": "CVZA CORE", "UNG": "UNG SIN TOP"})
    return normalized


def key_text(value: object) -> str:
    return clean_name(value).replace("_", "")


@st.cache_data(show_spinner=False)
def load_aux_segments(path_text: str, modified_ns: int) -> tuple[dict[str, pd.DataFrame], SourceInfo]:
    path = Path(path_text)
    sheets = pd.read_excel(path, sheet_name=None, dtype="string")
    frames = []
    for sheet, frame in sheets.items():
        frame = frame.copy()
        frame.columns = make_unique_columns(list(frame.columns))
        frames.append(frame)
    all_aux = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return {"all": all_aux}, SourceInfo(path.name, str(path), pd.to_datetime(modified_ns, unit="ns").strftime("%d/%m/%Y %H:%M"))


def apply_aux_segments(df: pd.DataFrame, aux: dict[str, pd.DataFrame] | None) -> pd.DataFrame:
    result = df.copy()
    if not aux or aux.get("all", pd.DataFrame()).empty:
        return result
    table = aux["all"]
    cols = list(table.columns)
    brand_col = next((c for c in cols if "marca" in c), None)
    seg_col = next((c for c in cols if "segmento" in c or "division" in c or "categoria" in c), None)
    if brand_col and seg_col:
        lookup = table[[brand_col, seg_col]].dropna().copy()
        lookup["marca_key"] = lookup[brand_col].map(key_text)
        lookup["segmento"] = lookup[seg_col].astype(str).str.strip().str.upper()
        lookup = lookup.drop_duplicates("marca_key", keep="last").set_index("marca_key")["segmento"]
        result["_marca_key"] = result["marca"].map(key_text)
        mapped = result["_marca_key"].map(lookup)
        result.loc[mapped.notna(), "division_informe"] = mapped.loc[mapped.notna()]
        result = result.drop(columns=["_marca_key"])
    return result


def normalize_planner_focus(value: object) -> str:
    cleaned = clean_name(value).replace("_", " ").upper().strip()
    for alias, focus in PLANNER_OBJECTIVE_ALIASES.items():
        if alias in cleaned:
            return focus
    for focus in PLANNER_FOCUS_RULES:
        if clean_name(focus).replace("_", " ").upper() in cleaned:
            return focus
    return str(value or "").strip()


def parse_cross_planner_objectives(path: Path) -> pd.DataFrame:
    source = pd.read_excel(path, sheet_name=0, header=None)
    header_index = None
    for index, row in source.iterrows():
        values = row.fillna("").astype(str).tolist()
        if any("descripcion" in clean_name(value) for value in values) and sum("-" in value for value in values) >= 2:
            header_index = index
            break
    if header_index is None:
        raise ValueError("No pude detectar la fila de vendedores en objetivos.")
    header = source.loc[header_index]
    vendor_columns = {col: normalize_vendor_name(value) for col, value in header.items() if col >= 2 and "-" in str(value)}
    rows = []
    for _, row in source.loc[header_index + 1 :].iterrows():
        focus = normalize_planner_focus(row.iloc[1] if len(row) > 1 else "")
        if focus not in PLANNER_FOCUS_RULES:
            continue
        for col, vendor in vendor_columns.items():
            value = parse_objective_cell(row.get(col))
            if not pd.isna(value):
                rows.append({"promotor": vendor, "foco": focus, "objetivo_mes": value})
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def load_planner_objectives(path_text: str, modified_ns: int) -> tuple[pd.DataFrame, SourceInfo]:
    path = Path(path_text)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        try:
            result = parse_cross_planner_objectives(path)
        except Exception:
            source = pd.read_excel(path, dtype="string")
            source.columns = make_unique_columns(list(source.columns))
            vendor_col = next((c for c in source.columns if "vendedor" in c or "promotor" in c), None)
            focus_col = next((c for c in source.columns if "foco" in c or "segmento" in c or "division" in c), None)
            obj_col = next((c for c in source.columns if "objetivo" in c or "plan" in c), None)
            if vendor_col is None or obj_col is None:
                raise
            result = pd.DataFrame(
                {
                    "promotor": source[vendor_col].map(normalize_vendor_name),
                    "foco": source[focus_col].map(normalize_planner_focus) if focus_col else "",
                    "objetivo_mes": parse_argentine_number(source[obj_col]),
                }
            )
    else:
        source = read_tabular(path)
        source.columns = make_unique_columns(list(source.columns))
        vendor_col = next((c for c in source.columns if "vendedor" in c or "promotor" in c), None)
        focus_col = next((c for c in source.columns if "foco" in c or "segmento" in c or "division" in c), None)
        obj_col = next((c for c in source.columns if "objetivo" in c or "plan" in c), None)
        result = pd.DataFrame(
            {
                "promotor": source[vendor_col].map(normalize_vendor_name),
                "foco": source[focus_col].map(normalize_planner_focus) if focus_col else "",
                "objetivo_mes": parse_argentine_number(source[obj_col]),
            }
        )
    result = result.dropna(subset=["objetivo_mes"])
    result = result[result["promotor"].astype(str).str.strip() != ""].copy()
    return result, SourceInfo(path.name, str(path), pd.to_datetime(modified_ns, unit="ns").strftime("%d/%m/%Y %H:%M"))


def argentina_holidays_for_years(years: list[int]) -> set[pd.Timestamp]:
    if holidays is None:
        return set()
    return {pd.Timestamp(day).normalize() for day in holidays.country_holidays("AR", years=years).keys()}


def selling_day_weight(date_value: pd.Timestamp, holiday_dates: set[pd.Timestamp]) -> float:
    date_value = pd.Timestamp(date_value).normalize()
    if date_value.weekday() == 6 or date_value in holiday_dates:
        return 0.0
    return 0.5 if date_value.weekday() == 5 else 1.0


def weighted_selling_days(start: pd.Timestamp, end: pd.Timestamp) -> float:
    if pd.isna(start) or pd.isna(end) or end < start:
        return 0.0
    dates = pd.date_range(start.normalize(), end.normalize(), freq="D")
    hols = argentina_holidays_for_years(sorted(set(dates.year.tolist())))
    return float(sum(selling_day_weight(date, hols) for date in dates))


def selling_days_in_month(date_value: pd.Timestamp) -> float:
    start = pd.Timestamp(date_value).normalize().replace(day=1)
    return weighted_selling_days(start, start + pd.offsets.MonthEnd(0))


def selling_days_remaining_from(date_value: pd.Timestamp) -> float:
    date_value = pd.Timestamp(date_value).normalize()
    return weighted_selling_days(date_value, date_value.replace(day=1) + pd.offsets.MonthEnd(0))


def format_hl(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_pct(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.0f}%".replace(".", ",")


def valid_nonzero(value: object) -> bool:
    if value is None or pd.isna(value):
        return False
    try:
        return float(value) != 0
    except Exception:
        return False


def planner_store_path(folder: Path) -> Path:
    return folder / PLANNER_STORE_FILE_NAME


def load_saved_planner(folder: Path) -> pd.DataFrame:
    path = planner_store_path(folder)
    columns = ["fecha", "foco", "promotor", "planificado"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    saved = pd.read_csv(path, sep=";", dtype="string")
    for col in columns:
        if col not in saved.columns:
            saved[col] = np.nan
    saved = saved[columns].copy()
    saved["fecha"] = pd.to_datetime(saved["fecha"], errors="coerce")
    saved["promotor"] = saved["promotor"].map(normalize_vendor_name)
    saved["planificado"] = saved["planificado"].map(parse_objective_cell)
    return saved.dropna(subset=["fecha"])


def save_daily_plan(folder: Path, selected_date: pd.Timestamp, focus_name: str, plan_df: pd.DataFrame) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = planner_store_path(folder)
    saved = load_saved_planner(folder)
    new_rows = plan_df[["promotor", "PLANIFICADO"]].copy()
    new_rows["promotor"] = new_rows["promotor"].map(normalize_vendor_name)
    new_rows["planificado"] = pd.to_numeric(new_rows["PLANIFICADO"], errors="coerce")
    new_rows["fecha"] = pd.Timestamp(selected_date).normalize()
    new_rows["foco"] = focus_name
    new_rows = new_rows[["fecha", "foco", "promotor", "planificado"]]
    if not saved.empty:
        same = (saved["fecha"] == pd.Timestamp(selected_date).normalize()) & (saved["foco"] == focus_name)
        saved = saved.loc[~same].copy()
    output = pd.concat([saved, new_rows], ignore_index=True)
    output["fecha"] = pd.to_datetime(output["fecha"]).dt.strftime("%Y-%m-%d")
    output.to_csv(path, sep=";", index=False)
    return path


def filter_focus(df: pd.DataFrame, focus_name: str) -> pd.DataFrame:
    result = df.copy()
    for column, allowed in PLANNER_FOCUS_RULES[focus_name].items():
        if column in {"title", "caption"}:
            continue
        if column in result.columns:
            result = result[result[column].astype(str).isin(allowed)]
    return result


def build_daily_planner_table(
    current_df: pd.DataFrame,
    selected_date: pd.Timestamp,
    focus_name: str,
    objectives: pd.DataFrame,
    saved_plan: pd.DataFrame,
) -> pd.DataFrame:
    focus_df = filter_focus(current_df, focus_name)
    real = (
        focus_df[focus_df["fecha"] == selected_date]
        .groupby(["mesa", "promotor"], as_index=False)["hl"]
        .sum()
        .rename(columns={"hl": "REAL"})
    )
    vendors = focus_df[["mesa", "promotor"]].drop_duplicates()
    if real.empty:
        real = vendors.assign(REAL=0.0)
    else:
        real = vendors.merge(real, on=["mesa", "promotor"], how="left").fillna({"REAL": 0.0})

    month_start = selected_date.replace(day=1)
    accum = (
        focus_df[(focus_df["fecha"] >= month_start) & (focus_df["fecha"] < selected_date)]
        .groupby("promotor", as_index=False)["hl"]
        .sum()
        .rename(columns={"hl": "ACUM. ANT."})
    )
    media_real = (
        focus_df[focus_df["fecha"] < selected_date]
        .groupby(["promotor", "fecha"], as_index=False)["hl"]
        .sum()
        .sort_values("fecha")
        .groupby("promotor", as_index=False)
        .tail(28)
        .groupby("promotor", as_index=False)["hl"]
        .mean()
        .rename(columns={"hl": "MEDIA REAL"})
    )
    table = real.merge(accum, on="promotor", how="left").merge(media_real, on="promotor", how="left")
    table["ACUM. ANT."] = table["ACUM. ANT."].fillna(0.0)

    obj = objectives[objectives["foco"].map(normalize_planner_focus).eq(focus_name)].copy() if not objectives.empty else pd.DataFrame()
    if not obj.empty:
        obj["promotor_key"] = obj["promotor"].map(normalize_vendor_name)
        table["promotor_key"] = table["promotor"].map(normalize_vendor_name)
        table = table.merge(obj[["promotor_key", "objetivo_mes"]], on="promotor_key", how="left")
    else:
        table["objetivo_mes"] = np.nan

    plan = saved_plan[(saved_plan["fecha"] == selected_date) & (saved_plan["foco"] == focus_name)].copy() if not saved_plan.empty else pd.DataFrame()
    if not plan.empty:
        plan["promotor_key"] = plan["promotor"].map(normalize_vendor_name)
        if "promotor_key" not in table:
            table["promotor_key"] = table["promotor"].map(normalize_vendor_name)
        table = table.merge(plan[["promotor_key", "planificado"]], on="promotor_key", how="left")
    else:
        table["planificado"] = np.nan

    remaining = selling_days_remaining_from(selected_date)
    table["OBJETIVO MES"] = table["objetivo_mes"]
    table["DIAS HABILES MES"] = selling_days_in_month(selected_date)
    table["DIAS RESTANTES"] = remaining
    table["PLANIFICADO"] = table["planificado"]
    table["MEDIA NEC."] = np.where(
        (table["OBJETIVO MES"].fillna(0) != 0) & (remaining > 0),
        (table["OBJETIVO MES"] - table["ACUM. ANT."]) / remaining,
        np.nan,
    )
    table["MEDIA NEC."] = table["MEDIA NEC."].clip(lower=0)
    table["AVANCE"] = np.where(table["PLANIFICADO"].fillna(0) != 0, table["REAL"] / table["PLANIFICADO"] * 100, np.nan)
    table["VS MEDIA NEC."] = np.where(table["MEDIA NEC."].fillna(0) != 0, table["REAL"] / table["MEDIA NEC."] * 100, np.nan)
    table["VS MEDIA REAL"] = np.where(table["MEDIA REAL"].fillna(0) != 0, table["REAL"] / table["MEDIA REAL"] * 100, np.nan)
    columns = [
        "mesa",
        "promotor",
        "OBJETIVO MES",
        "ACUM. ANT.",
        "DIAS HABILES MES",
        "DIAS RESTANTES",
        "PLANIFICADO",
        "REAL",
        "AVANCE",
        "MEDIA NEC.",
        "MEDIA REAL",
        "VS MEDIA NEC.",
        "VS MEDIA REAL",
    ]
    return table[columns].sort_values(["mesa", "REAL"], ascending=[True, False])


def executive_summary_table(df: pd.DataFrame, selected_date: pd.Timestamp, group_col: str, first_col: str, total_label: str | None = None) -> pd.DataFrame:
    month_start = selected_date.replace(day=1)
    accum = df[(df["fecha"] >= month_start) & (df["fecha"] <= selected_date)].groupby(group_col, as_index=False)["hl"].sum().rename(columns={"hl": "ACUM. ACTUAL"})
    ant = df[(df["fecha"] >= month_start) & (df["fecha"] < selected_date)].groupby(group_col, as_index=False)["hl"].sum().rename(columns={"hl": "ACUM ANT."})
    today = df[df["fecha"] == selected_date].groupby(group_col, as_index=False)["hl"].sum().rename(columns={"hl": "HOY"})
    keys = pd.concat([x[[group_col]] for x in (accum, ant, today) if not x.empty], ignore_index=True).drop_duplicates() if not accum.empty or not ant.empty or not today.empty else pd.DataFrame(columns=[group_col])
    if group_col == "division_informe":
        keys = pd.concat([pd.DataFrame({group_col: DIVISION_ORDER[1:]}), keys], ignore_index=True).drop_duplicates()
    table = keys.merge(ant, on=group_col, how="left").merge(accum, on=group_col, how="left").merge(today, on=group_col, how="left")
    for col in ["ACUM ANT.", "ACUM. ACTUAL", "HOY"]:
        table[col] = table[col].fillna(0.0)
    elapsed = weighted_selling_days(month_start, selected_date)
    total_days = selling_days_in_month(selected_date)
    table["TENDENCIA"] = np.where(elapsed > 0, table["ACUM. ACTUAL"] / elapsed * total_days, np.nan)
    table = table.rename(columns={group_col: first_col})
    table["OBJ VTAS"] = table[first_col].astype(str).str.upper().map(DEFAULT_OBJECTIVES)
    table["OBJ VS VENTAS"] = np.where(table["OBJ VTAS"].fillna(0) != 0, table["ACUM. ACTUAL"] / table["OBJ VTAS"] * 100, np.nan)
    table["TEND VS VENTAS"] = np.where(table["OBJ VTAS"].fillna(0) != 0, table["TENDENCIA"] / table["OBJ VTAS"] * 100, np.nan)
    if total_label:
        total_obj = table["OBJ VTAS"].sum(min_count=1)
        total = {
            first_col: total_label,
            "ACUM ANT.": table["ACUM ANT."].sum(),
            "ACUM. ACTUAL": table["ACUM. ACTUAL"].sum(),
            "HOY": table["HOY"].sum(),
            "TENDENCIA": table["TENDENCIA"].sum(),
            "OBJ VTAS": total_obj,
            "OBJ VS VENTAS": table["ACUM. ACTUAL"].sum() / total_obj * 100 if valid_nonzero(total_obj) else np.nan,
            "TEND VS VENTAS": table["TENDENCIA"].sum() / total_obj * 100 if valid_nonzero(total_obj) else np.nan,
        }
        table = pd.concat([pd.DataFrame([total]), table], ignore_index=True)
    return table


def page_setup() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon=":bar_chart:", layout="wide")
    st.markdown(
        """
        <style>
        :root { --ink:#0f172a; --blue:#1463ff; --green:#12b76a; --orange:#f79009; }
        .stApp { background: radial-gradient(circle at top right,#dff7f1 0,#f5f7fb 28%,#eef4ff 100%); color: var(--ink); }
        [data-testid="stSidebar"] { background:#14213d; }
        [data-testid="stSidebar"] * { color:#fff !important; }
        [data-testid="stSidebar"] input, [data-testid="stSidebar"] span, [data-testid="stSidebar"] [data-baseweb="select"] * { color:#111827 !important; -webkit-text-fill-color:#111827 !important; }
        .hero { background:linear-gradient(120deg,#1e3a8a,#1463ff,#00a7c8); padding:28px 32px; border-radius:8px; color:white; margin-bottom:22px; }
        .hero h1 { margin:0; color:#061226; font-size:2.2rem; }
        .hero p { color:white; font-weight:700; }
        .metric-card { background:white; border-radius:8px; box-shadow:0 12px 28px rgba(15,23,42,.12); padding:18px; border-top:5px solid var(--blue); }
        .metric-title { color:#475569; text-transform:uppercase; font-weight:900; font-size:.78rem; }
        .metric-value { color:#0f172a; font-size:2rem; font-weight:900; }
        .exec-wrap { background:white; border:1px solid #111827; border-radius:8px; padding:10px; margin:10px 0 24px; overflow-x:auto; }
        .exec-title { font-weight:900; color:#111827; text-transform:uppercase; margin-bottom:8px; }
        table.exec-table, table.planner-table { border-collapse:collapse; width:100%; min-width:760px; font-size:14px; }
        table.exec-table th, table.planner-table th { background:#28549a; color:white !important; border:1px solid #111827; padding:5px 7px; text-align:center; font-weight:900; }
        table.planner-table th.yellow { background:#ffd966; color:#111827 !important; }
        table.exec-table td, table.planner-table td { border:1px solid #111827; padding:4px 7px; text-align:right; color:#111827 !important; background:white; font-weight:700; }
        table.exec-table td:first-child, table.planner-table td:first-child { background:#2f5ea8; color:white !important; text-align:center; font-weight:900; }
        table.planner-table .good { background:#c6efce !important; color:#006100 !important; }
        table.planner-table .bad { background:#ffc7ce !important; color:#9c0006 !important; }
        .planner-note { background:#e0f2fe; color:#0f172a !important; font-weight:800; padding:8px 12px; border-radius:6px; margin-bottom:8px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def metric_card(title: str, value: str, sub: str = "") -> None:
    st.markdown(f"<div class='metric-card'><div class='metric-title'>{title}</div><div class='metric-value'>{value}</div><div>{sub}</div></div>", unsafe_allow_html=True)


def chart_layout(fig):
    fig.update_layout(template="plotly_white", font=dict(color="#0f172a"), paper_bgcolor="white", plot_bgcolor="white")
    return fig


def render_exec_table(title: str, table: pd.DataFrame, first_col: str) -> None:
    rows = []
    pct_cols = {"OBJ VS VENTAS", "TEND VS VENTAS"}
    for _, row in table.iterrows():
        cells = [f"<td>{row[first_col]}</td>"]
        for col in table.columns:
            if col == first_col:
                continue
            cells.append(f"<td>{format_pct(row[col]) if col in pct_cols else format_hl(row[col])}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    header = "".join(f"<th>{col}</th>" for col in table.columns)
    st.markdown(f"<div class='exec-wrap'><div class='exec-title'>{title}</div><table class='exec-table'><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>", unsafe_allow_html=True)


def render_planner_table(title: str, focus_name: str, table: pd.DataFrame) -> None:
    headers = ["", "PLANIFICADO", "REAL", "AVANCE", "MEDIA NEC.", "MEDIA REAL", "VS MEDIA NEC.", "VS MEDIA REAL"]
    pct_cols = {"AVANCE", "VS MEDIA NEC.", "VS MEDIA REAL"}
    yellow = {"PLANIFICADO", "VS MEDIA NEC.", "VS MEDIA REAL"}
    rows = []
    total = {col: table[col].sum(min_count=1) for col in ["PLANIFICADO", "REAL", "MEDIA NEC.", "MEDIA REAL"]}
    total["AVANCE"] = total["REAL"] / total["PLANIFICADO"] * 100 if valid_nonzero(total["PLANIFICADO"]) else np.nan
    total["VS MEDIA NEC."] = total["REAL"] / total["MEDIA NEC."] * 100 if valid_nonzero(total["MEDIA NEC."]) else np.nan
    total["VS MEDIA REAL"] = total["REAL"] / total["MEDIA REAL"] * 100 if valid_nonzero(total["MEDIA REAL"]) else np.nan
    cells = ["<td>TOTAL</td>"]
    for col in headers[1:]:
        cls = "good" if col in pct_cols and not pd.isna(total[col]) and total[col] >= 100 else "bad" if col in pct_cols and not pd.isna(total[col]) else ""
        cells.append(f"<td class='{cls}'>{format_pct(total[col]) if col in pct_cols else format_hl(total[col])}</td>")
    rows.append(f"<tr>{''.join(cells)}</tr>")
    for mesa, group in table.groupby("mesa", dropna=False):
        rows.append(f"<tr><td colspan='8'>{mesa}</td></tr>")
        for _, row in group.iterrows():
            cells = [f"<td>{row['promotor']}</td>"]
            for col in headers[1:]:
                cls = "good" if col in pct_cols and not pd.isna(row[col]) and row[col] >= 100 else "bad" if col in pct_cols and not pd.isna(row[col]) else ""
                cells.append(f"<td class='{cls}'>{format_pct(row[col]) if col in pct_cols else format_hl(row[col])}</td>")
            rows.append(f"<tr>{''.join(cells)}</tr>")
    header = "".join(f"<th class='{'yellow' if h in yellow else ''}'>{h}</th>" for h in headers)
    caption = PLANNER_FOCUS_RULES[focus_name]["caption"]
    st.markdown(f"<div class='exec-wrap'><div class='exec-title'>{title}</div><div class='planner-note'>{focus_name}<br>{caption}</div><table class='planner-table'><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>", unsafe_allow_html=True)


def planner_pdf_data(table: pd.DataFrame) -> list[list[str]]:
    cols = ["promotor", "OBJETIVO MES", "ACUM. ANT.", "PLANIFICADO", "REAL", "AVANCE", "MEDIA NEC.", "MEDIA REAL", "VS MEDIA NEC.", "VS MEDIA REAL"]
    header = ["VENDEDOR", "OBJ MES", "ACUM ANT", "PLANIF", "REAL", "AVANCE", "MEDIA NEC", "MEDIA REAL", "VS M NEC", "VS M REAL"]
    data = [header]
    for _, row in table[cols].iterrows():
        data.append([str(row["promotor"])] + [format_pct(row[c]) if c in {"AVANCE", "VS MEDIA NEC.", "VS MEDIA REAL"} else format_hl(row[c]) for c in cols[1:]])
    return data


def build_planner_pdf(tables: list[tuple[str, str, pd.DataFrame]], selected_date: pd.Timestamp) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=16, leftMargin=16, topMargin=16, bottomMargin=16)
    page_width, _ = landscape(A4)
    usable = page_width - 32
    elements = [Paragraph(f"Cierre planificador diario - {selected_date.strftime('%d/%m/%Y')}", ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=16, leading=18))]
    for idx, (title, caption, table) in enumerate(tables):
        if table.empty:
            continue
        elements.append(Paragraph(f"{title} - {caption}", ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=9, leading=11, spaceBefore=5, spaceAfter=3)))
        pdf_table = Table(planner_pdf_data(table), colWidths=[usable * 0.22] + [usable * 0.078] * 9, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#28549A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 6.2),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        pdf_table.setStyle(TableStyle(style))
        elements.extend([pdf_table, Spacer(1, 7)])
        if idx == 1:
            elements.append(PageBreak())
    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()


def main() -> None:
    page_setup()
    folder = data_dir()
    st.markdown("<div class='hero'><h1>Venta diaria HL</h1><p>Analisis comercial con ventanas habiles, planificacion por percentiles y comparacion mensual.</p></div>", unsafe_allow_html=True)
    st.sidebar.title("Datos y filtros")
    st.sidebar.caption(f"Carpeta automatica: {folder}")
    if st.sidebar.button("Actualizar datos", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    uploaded = st.sidebar.file_uploader("Carga manual si falla la carpeta", type=["txt", "csv"])

    try:
        if uploaded is not None:
            df, info = load_source_from_upload(uploaded.name, uploaded.getvalue())
        else:
            latest = latest_daily_file(folder)
            if latest is None:
                st.warning("No encontre archivos TXT/CSV en la carpeta automatica. Revise Google Drive o suba los archivos a una carpeta `planificacion` dentro del repo.")
                st.stop()
            df, info = load_source_from_path(str(latest), latest.stat().st_mtime_ns)
    except Exception as exc:
        st.error(f"No pude leer el archivo: {exc}")
        st.stop()

    aux_info = None
    aux_path = latest_aux_file(folder)
    if aux_path is not None:
        try:
            aux, aux_info = load_aux_segments(str(aux_path), aux_path.stat().st_mtime_ns)
            df = apply_aux_segments(df, aux)
        except Exception as exc:
            st.sidebar.warning(f"No pude leer auxiliares: {exc}")

    planner_objectives = pd.DataFrame(columns=["promotor", "foco", "objetivo_mes"])
    obj_info = None
    obj_path = latest_objectives_file(folder)
    if obj_path is not None:
        try:
            planner_objectives, obj_info = load_planner_objectives(str(obj_path), obj_path.stat().st_mtime_ns)
        except Exception as exc:
            st.sidebar.warning(f"No pude leer objetivos por vendedor: {exc}")
    saved_planner = load_saved_planner(folder)

    st.sidebar.success(f"Fuente: {info.label}")
    if info.modified:
        st.sidebar.caption(f"Modificado: {info.modified}")
    if aux_info:
        st.sidebar.success(f"Auxiliares: {aux_info.label}")
    if obj_info:
        st.sidebar.success(f"Objetivos vendedor: {obj_info.label}")
    else:
        st.sidebar.info("Planificador: falta archivo OBJETIVOS.xlsx")

    if df.empty:
        st.warning("No hay filas validas.")
        st.stop()

    selected_date = st.sidebar.date_input("Fecha", value=df["fecha"].max().date())
    selected_date = pd.Timestamp(selected_date)
    filtered = df.copy()
    for col, label in [("mesa", "Mesa"), ("promotor", "Promotor"), ("ruta", "Ruta"), ("unidad_negocio", "Negocio"), ("calibre", "Calibre")]:
        options = sorted(filtered[col].dropna().astype(str).unique().tolist())
        selected = st.sidebar.multiselect(label, options)
        if selected:
            filtered = filtered[filtered[col].astype(str).isin(selected)]

    daily = filtered.groupby("fecha", as_index=False)["hl"].sum().sort_values("fecha")
    current = float(daily.loc[daily["fecha"] == selected_date, "hl"].sum()) if not daily.empty else 0.0
    c1, c2, c3 = st.columns(3)
    with c1:
        metric_card("HL dia actual", format_hl(current), selected_date.strftime("%d/%m/%Y"))
    with c2:
        metric_card("Acum mes", format_hl(filtered[(filtered["fecha"] >= selected_date.replace(day=1)) & (filtered["fecha"] <= selected_date)]["hl"].sum()))
    with c3:
        metric_card("Dias habiles mes", format_hl(selling_days_in_month(selected_date)).replace(",00", ""))

    tab_evo, tab_informe, tab_plan, tab_base = st.tabs(["Evolucion", "Informe", "Planificador diario", "Base normalizada"])

    with tab_evo:
        if not daily.empty:
            fig = px.line(daily, x="fecha", y="hl", markers=True, title="HL diarios")
            st.plotly_chart(chart_layout(fig), width="stretch")
        cols = st.columns(2)
        with cols[0]:
            by_cal = filtered.groupby("calibre", as_index=False)["hl"].sum().sort_values("hl", ascending=False).head(20)
            st.plotly_chart(chart_layout(px.bar(by_cal, x="hl", y="calibre", orientation="h", title="HL por calibre")), width="stretch")
        with cols[1]:
            by_neg = filtered.groupby("unidad_negocio", as_index=False)["hl"].sum().sort_values("hl", ascending=False)
            st.plotly_chart(chart_layout(px.bar(by_neg, x="unidad_negocio", y="hl", title="HL por negocio")), width="stretch")

    with tab_informe:
        st.subheader("Informe de venta del dia")
        report = executive_summary_table(filtered, selected_date, "division_informe", "DIVISION", "HL TOTALES")
        render_exec_table("Division / negocio", report, "DIVISION")
        left, right = st.columns(2)
        with left:
            render_exec_table("X mesa", executive_summary_table(filtered, selected_date, "mesa", "MESA"), "MESA")
        with right:
            render_exec_table("X canal", executive_summary_table(filtered, selected_date, "canal", "CANAL"), "CANAL")

    with tab_plan:
        st.subheader("Planificador diario")
        if planner_objectives.empty:
            st.warning("No encontre objetivos por vendedor/segmento. Cargue OBJETIVOS.xlsx en la carpeta de datos.")
        pdf_tables: list[tuple[str, str, pd.DataFrame]] = []
        focus_tabs = st.tabs([name.replace(" - ", "\n") for name in PLANNER_FOCUS_RULES])
        for focus_tab, focus_name in zip(focus_tabs, PLANNER_FOCUS_RULES):
            with focus_tab:
                table = build_daily_planner_table(filtered, selected_date, focus_name, planner_objectives, saved_planner)
                if table.empty:
                    st.info("No hay vendedores para este foco con los filtros seleccionados.")
                    continue
                editable_cols = ["mesa", "promotor", "OBJETIVO MES", "ACUM. ANT.", "DIAS HABILES MES", "DIAS RESTANTES", "PLANIFICADO"]
                edited = st.data_editor(
                    table[editable_cols],
                    key=f"editor_{focus_name}",
                    width="stretch",
                    hide_index=True,
                    disabled=[c for c in editable_cols if c != "PLANIFICADO"],
                    column_config={"PLANIFICADO": st.column_config.NumberColumn("PLANIFICADO", min_value=0.0, step=0.1, format="%.2f")},
                )
                if st.button("Guardar planificado del dia", key=f"save_{focus_name}", width="stretch"):
                    path = save_daily_plan(folder, selected_date, focus_name, edited)
                    st.success(f"Planificado guardado en {path}")
                    st.rerun()
                display = table.drop(columns=["PLANIFICADO"]).merge(edited[["promotor", "PLANIFICADO"]], on="promotor", how="left")
                display["AVANCE"] = np.where(display["PLANIFICADO"].fillna(0) != 0, display["REAL"] / display["PLANIFICADO"] * 100, np.nan)
                render_planner_table(PLANNER_FOCUS_RULES[focus_name]["title"], focus_name, display)
                pdf_tables.append((PLANNER_FOCUS_RULES[focus_name]["title"], PLANNER_FOCUS_RULES[focus_name]["caption"], display.copy()))
        if pdf_tables:
            st.download_button(
                "Generar PDF cierre del dia",
                data=build_planner_pdf(pdf_tables, selected_date),
                file_name=f"cierre_planificador_{selected_date.strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                width="stretch",
            )

    with tab_base:
        st.caption(f"{len(filtered):,} filas filtradas de {len(df):,} filas normalizadas.".replace(",", "."))
        st.dataframe(filtered.sort_values("fecha", ascending=False), width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
