from __future__ import annotations

import base64
import io
import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image

import app as sales_app


APP_TITLE = "Control bultos Core / Value"
TRUCK_ICON_PATH = Path(__file__).resolve().parent / "assets" / "distribuidora_del_valle_truck.png"
DEFAULT_DRIVE_URL = "https://drive.google.com/drive/folders/1cukgXLUaPsEDK_yD7tSwgaBFZAbiDUot?usp=drive_link"
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/15ITRhsY5mvK3NSHeOKV2MymC078pT9TPAwKUdZDfjnI/edit?usp=sharing"
DEFAULT_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbwDlxEbBN2kmy5oVtb4LJiPFN0KtAZw-nI9TolDtfOIVuMxQqIZprMB1pquTesPGYHe/exec"
EXTENSION_SHEET_NAME = "BD_EXTENSION_TOPES"
TOPES_CANAL = {
    "K+T": 200.0,
    "AUTOSERVICIO": 500.0,
    "AS": 500.0,
}
EXTENSION_ACTION_BY_CHANNEL = {
    "K+T": {
        "codigo": "23056",
        "accion": "CORE Escala 3 KT EXCEPCION",
        "descripcion": "EXCEPCION RGB/473--> KT SUR - Drop 3era escala",
    },
    "AS": {
        "codigo": "23057",
        "accion": "CORE Escala 3 AS EXCEPCION",
        "descripcion": "EXCEPCION CORE RGB/473--> AS SUR- Drop 3era escala",
    },
}
SEGMENTOS_ACCION = {
    "CVZA CORE": "CORE",
    "CVZA VALUE": "VALUE",
}
CORE_BRAND_TERMS = ("QUILMES", "BRAHMA", "BUDWEISER")
VALUE_BRAND_TERMS = ("QUILMES 1890", "1890")
TARGET_QUANTITY_COLUMN = "Cantidades Totales"


def page_icon():
    try:
        return Image.open(TRUCK_ICON_PATH)
    except Exception:
        return "🚚"


def truck_icon_data_uri() -> str:
    try:
        encoded = base64.b64encode(TRUCK_ICON_PATH.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return ""


def loading_truck_html() -> str:
    src = truck_icon_data_uri()
    truck = f"<img src='{src}' alt='Distribuidora del Valle'>" if src else "<span>🚚</span>"
    return f"""
    <div class="loading-road" aria-label="Cargando datos">
        <div class="loading-truck">{truck}</div>
    </div>
    """


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
        div[data-testid="stAlert"] * {
            color: #101828 !important;
            font-weight: 750;
        }
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
        .loading-road {
            position: relative;
            height: 78px;
            margin: .4rem 0 1rem;
            overflow: hidden;
            border-radius: 8px;
            background:
                linear-gradient(90deg, rgba(20,99,255,.10), rgba(18,183,106,.14)),
                repeating-linear-gradient(90deg, transparent 0 58px, rgba(16,24,40,.12) 58px 82px);
            border: 1px solid rgba(16,24,40,.10);
            box-shadow: 0 12px 26px rgba(16,24,40,.08);
        }
        .loading-road::after {
            content: "";
            position: absolute;
            left: 0;
            right: 0;
            bottom: 14px;
            border-bottom: 5px dashed rgba(15,23,42,.28);
        }
        .loading-truck {
            position: absolute;
            z-index: 1;
            right: -120px;
            bottom: 8px;
            width: 96px;
            animation: drive-across 2.8s linear infinite;
        }
        .loading-truck img {
            width: 96px;
            height: 96px;
            object-fit: contain;
            display: block;
        }
        .loading-truck span {
            font-size: 56px;
            display: block;
        }
        @keyframes drive-across {
            from { transform: translateX(120px); }
            to { transform: translateX(calc(-100vw - 180px)); }
        }
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
            min-width: 1540px;
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


def extension_action_for_channel(channel: object, field: str) -> str:
    key = str(channel or "").strip().upper().replace("AUTOSERVICIO", "AS")
    return EXTENSION_ACTION_BY_CHANNEL.get(key, {}).get(field, "")


def parse_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "si", "sí", "yes", "y", "activo", "activa"}


def clean_name(value: object) -> str:
    return sales_app.clean_name("" if pd.isna(value) else str(value))


def google_sheet_export_url(raw_url: str) -> str:
    return sales_app.google_sheet_export_url(raw_url)


def extensions_sheet_url() -> str:
    return sales_app.secret_or_env("BULTOS_EXTENSION_SHEET_URL", sales_app.secret_or_env("PLANNER_GOOGLE_SHEET_URL", DEFAULT_SHEET_URL))


def extensions_webapp_url() -> str:
    return sales_app.secret_or_env("BULTOS_EXTENSION_WEBAPP_URL", sales_app.secret_or_env("PLANNER_WEBAPP_URL", DEFAULT_WEBAPP_URL))


def core_brand_override(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).map(sales_app.strip_accents).str.upper()
    is_value = text.apply(lambda value: any(term in value for term in VALUE_BRAND_TERMS))
    is_core = text.apply(lambda value: any(term in value for term in CORE_BRAND_TERMS))
    return is_core & ~is_value


def value_brand_override(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).map(sales_app.strip_accents).str.upper()
    return text.apply(lambda value: any(term in value for term in VALUE_BRAND_TERMS))


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


def drive_folder_items(drive_url: str) -> list:
    try:
        import gdown

        return gdown.download_folder(url=drive_url, output=".", quiet=True, use_cookies=False, skip_download=True) or []
    except Exception:
        return []


def download_drive_item(item, target_folder: Path) -> Path | None:
    target_folder.mkdir(parents=True, exist_ok=True)
    file_name = Path(str(item.path)).name
    target_path = target_folder / file_name
    tmp_path = target_folder / f"{file_name}.tmp"
    if tmp_path.exists():
        tmp_path.unlink(missing_ok=True)
    try:
        import gdown

        gdown.download(id=item.id, output=str(tmp_path), quiet=True, use_cookies=False)
        if tmp_path.exists() and tmp_path.stat().st_size > 0:
            if target_path.exists():
                target_path.unlink(missing_ok=True)
            tmp_path.rename(target_path)
            return target_path
    except Exception:
        tmp_path.unlink(missing_ok=True)
    return target_path if target_path.exists() else None


def latest_drive_item(items: list, include_terms: tuple[str, ...], suffixes: tuple[str, ...]) -> object | None:
    include_terms = tuple(clean_name(term) for term in include_terms)
    matches = []
    for item in items:
        name = Path(str(item.path)).name
        stem = clean_name(Path(name).stem)
        if Path(name).suffix.lower() in suffixes and all(term in stem for term in include_terms):
            matches.append(item)
    return matches[-1] if matches else None


def prepare_drive_sources(drive_url: str, force_refresh: bool = False) -> Path | None:
    target = sales_app.PROJECT_ROOT / ".cloud_data" / "bultos_accion"
    if target.exists() and any(target.iterdir()) and not force_refresh:
        return target
    items = drive_folder_items(drive_url)
    if not items:
        return target if target.exists() and any(target.iterdir()) else None
    tmp_target = sales_app.PROJECT_ROOT / ".cloud_data" / f"bultos_accion_tmp_{int(time.time())}"
    if tmp_target.exists():
        shutil.rmtree(tmp_target, ignore_errors=True)
    tmp_target.mkdir(parents=True, exist_ok=True)

    needed = [
        latest_drive_item(items, ("venta", "bulto"), (".txt", ".csv")),
        latest_drive_item(items, ("auxiliar",), (".xlsx", ".xls")),
        latest_drive_item(items, ("cliente",), (".xlsx", ".xls", ".txt", ".csv")),
    ]
    downloaded = [download_drive_item(item, tmp_target) for item in needed if item is not None]
    if not any(path is not None for path in downloaded):
        shutil.rmtree(tmp_target, ignore_errors=True)
        return target if target.exists() and any(target.iterdir()) else None
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    tmp_target.rename(target)
    return target


def choose_quantity_column(raw: pd.DataFrame) -> str:
    for column in raw.columns:
        if clean_name(column) == clean_name(TARGET_QUANTITY_COLUMN):
            return str(column)
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
    quantity_index = original_columns.index(quantity_col) if quantity_col in original_columns else -1
    if quantity_index < 0:
        raise ValueError(f"El archivo debe contener la columna '{TARGET_QUANTITY_COLUMN}'.")
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
    normalized["supervisor"] = sales_app.mesa_from_promoter(normalized["vendedor"])
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


def load_bultos_customer_channels(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame(columns=["cliente_codigo", "canal"])
    try:
        customers, _ = sales_app.load_customer_channels(str(path), path.stat().st_mtime_ns)
        if not customers.empty and "canal_maestro" in customers.columns:
            return customers.rename(columns={"canal_maestro": "canal"})[["cliente_codigo", "canal"]]
    except Exception:
        pass

    if path.suffix.lower() in {".xlsx", ".xls"}:
        source = pd.read_excel(path, dtype="string")
    else:
        source = sales_app.read_tabular(path)
    source = source.copy()
    source.columns = sales_app.make_unique_columns(list(source.columns))
    customer_col = next((col for col in source.columns if col in {"cliente", "cod_cliente", "codigo_cliente"}), None)
    if customer_col is None:
        return pd.DataFrame(columns=["cliente_codigo", "canal"])
    text_cols = [
        col
        for col in source.columns
        if any(term in col for term in ("descripcion_lista", "lista_de_precios", "descripcion_subcanal", "subcanal", "descripcion_ramo", "ramo"))
    ]
    if not text_cols:
        return pd.DataFrame(columns=["cliente_codigo", "canal"])
    channel_text = source[text_cols].fillna("").astype(str).agg(" ".join, axis=1)
    result = pd.DataFrame(
        {
            "cliente_codigo": pd.to_numeric(source[customer_col], errors="coerce").astype("Int64").astype("string"),
            "canal": channel_text.map(sales_app.classify_customer_channel),
        }
    )
    return result.dropna(subset=["cliente_codigo"]).drop_duplicates("cliente_codigo")


def apply_bultos_customer_channels(data: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    if customers.empty:
        result["canal"] = "NO"
        return result
    result["cliente_codigo"] = pd.to_numeric(result["cliente_codigo"], errors="coerce").astype("Int64").astype("string")
    result = result.merge(customers, on="cliente_codigo", how="left")
    result["canal"] = result["canal"].fillna("NO")
    return result


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
    customers = load_bultos_customer_channels(customer_file)
    data = apply_bultos_customer_channels(data, customers)

    aux_file = sales_app.latest_auxiliary_file_in_folder(folder) if folder is not None else None
    if aux_file is not None:
        aux_segments, _ = sales_app.load_auxiliary_segments(str(aux_file), aux_file.stat().st_mtime_ns)
        data = sales_app.apply_auxiliary_segments(data, aux_segments)
    else:
        data["division_informe"] = "CVZA SIN SEGMENTO"

    data["accion"] = data["division_informe"].map(SEGMENTOS_ACCION).fillna("")
    data.loc[core_brand_override(data["marca"]), "accion"] = "CORE"
    data.loc[value_brand_override(data["marca"]), "accion"] = "VALUE"
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
        ("supervisor", "Supervisor"),
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
    supervisors = data.groupby("cliente_codigo", as_index=False)["supervisor"].agg(
        lambda values: " / ".join(sorted(set(values.dropna().astype(str))))
    )
    pivot = grouped.pivot_table(
        index=["cliente_codigo", "cliente", "canal_accion", "ruta", "vendedor"],
        columns="accion",
        values="bultos",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    pivot = pivot.merge(supervisors, on="cliente_codigo", how="left")
    for action in ["CORE", "VALUE"]:
        if action not in pivot.columns:
            pivot[action] = 0.0
    topes = grouped.groupby(["cliente_codigo", "accion"], as_index=False)["tope"].first().pivot(
        index="cliente_codigo",
        columns="accion",
        values="tope",
    )
    pivot = pivot.merge(topes.add_prefix("tope_").reset_index(), on="cliente_codigo", how="left")
    for column in ["tope_CORE", "tope_VALUE"]:
        if column not in pivot.columns:
            pivot[column] = np.nan
    pivot["tope_CORE"] = pivot["tope_CORE"].fillna(pivot["canal_accion"].map({"K+T": 200.0, "AS": 500.0}))
    pivot["tope_VALUE"] = pivot["tope_VALUE"].fillna(pivot["canal_accion"].map({"K+T": 200.0, "AS": 500.0}))
    pivot["avance_CORE"] = np.where(pivot["tope_CORE"] > 0, pivot["CORE"] / pivot["tope_CORE"] * 100, np.nan)
    pivot["avance_VALUE"] = np.where(pivot["tope_VALUE"] > 0, pivot["VALUE"] / pivot["tope_VALUE"] * 100, np.nan)
    pivot["restante_CORE"] = pivot["tope_CORE"] - pivot["CORE"]
    pivot["restante_VALUE"] = pivot["tope_VALUE"] - pivot["VALUE"]
    pivot["estado"] = np.select(
        [
            (pivot["avance_CORE"] >= 100) & (pivot["avance_VALUE"] >= 100),
            (pivot["avance_CORE"] >= 80) | (pivot["avance_VALUE"] >= 80),
        ],
        ["Completo", "Cerca del tope"],
        default="Pendiente",
    )
    return pivot.sort_values(["estado", "avance_CORE", "avance_VALUE"], ascending=[True, False, False])


def empty_extensions() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "cliente_codigo",
            "cliente",
            "accion",
            "primer_tope",
            "segundo_tope",
            "activa",
            "comentario",
            "actualizado",
        ]
    )


def load_top_extensions(sheet_url: str) -> pd.DataFrame:
    if not sheet_url:
        return empty_extensions()
    try:
        workbook = pd.read_excel(google_sheet_export_url(sheet_url), sheet_name=None, dtype="string")
    except Exception:
        return empty_extensions()
    sheet = next((data for name, data in workbook.items() if clean_name(name) == clean_name(EXTENSION_SHEET_NAME)), None)
    if sheet is None or sheet.empty:
        return empty_extensions()
    sheet = sheet.copy()
    sheet.columns = sales_app.make_unique_columns(list(sheet.columns))
    columns = {clean_name(column): column for column in sheet.columns}
    code_col = columns.get("cliente_codigo") or columns.get("cod_cliente") or columns.get("codigo_cliente")
    action_col = columns.get("accion")
    if code_col is None or action_col is None:
        return empty_extensions()
    result = pd.DataFrame(
        {
            "cliente_codigo": pd.to_numeric(sheet[code_col], errors="coerce").astype("Int64").astype("string"),
            "cliente": sheet[columns.get("cliente", code_col)].fillna("").astype(str).str.strip(),
            "accion": sheet[action_col].fillna("").astype(str).str.strip().str.upper(),
            "primer_tope": sales_app.parse_argentine_number(sheet[columns.get("primer_tope", code_col)])
            if "primer_tope" in columns
            else np.nan,
            "segundo_tope": sales_app.parse_argentine_number(sheet[columns.get("segundo_tope", code_col)])
            if "segundo_tope" in columns
            else np.nan,
            "activa": sheet[columns.get("activa", code_col)].map(parse_bool) if "activa" in columns else True,
            "comentario": sheet[columns.get("comentario", code_col)].fillna("").astype(str).str.strip()
            if "comentario" in columns
            else "",
            "actualizado": sheet[columns.get("actualizado", code_col)].fillna("").astype(str)
            if "actualizado" in columns
            else "",
        }
    )
    result = result[result["cliente_codigo"].notna() & result["accion"].isin(["CORE", "VALUE"])].copy()
    return result.drop_duplicates(["cliente_codigo", "accion"], keep="last")


def merge_top_extensions(summary: pd.DataFrame, extensions: pd.DataFrame) -> pd.DataFrame:
    result = summary.copy()
    for action in ["CORE", "VALUE"]:
        result[f"extension_{action}"] = False
        result[f"segundo_tope_{action}"] = np.nan
        result[f"comentario_extension_{action}"] = ""
        bultos_col = action
        tope_col = f"tope_{action}"
        result[f"primer_tope_comprado_{action}"] = np.minimum(result[bultos_col].fillna(0), result[tope_col].fillna(0))
        result[f"segundo_tramo_comprado_{action}"] = np.maximum(result[bultos_col].fillna(0) - result[tope_col].fillna(0), 0)
        result[f"restante_segundo_{action}"] = np.nan

    if extensions.empty:
        return result

    result["cliente_codigo"] = pd.to_numeric(result["cliente_codigo"], errors="coerce").astype("Int64").astype("string")
    for action in ["CORE", "VALUE"]:
        action_extensions = extensions[(extensions["accion"] == action) & extensions["activa"].fillna(False)].copy()
        if action_extensions.empty:
            continue
        action_extensions = action_extensions[["cliente_codigo", "segundo_tope", "comentario"]].rename(
            columns={
                "segundo_tope": f"segundo_tope_{action}_ext",
                "comentario": f"comentario_extension_{action}_ext",
            }
        )
        result = result.merge(action_extensions, on="cliente_codigo", how="left")
        has_extension = result[f"segundo_tope_{action}_ext"].notna()
        result[f"extension_{action}"] = has_extension
        result[f"segundo_tope_{action}"] = result[f"segundo_tope_{action}_ext"]
        result[f"comentario_extension_{action}"] = result[f"comentario_extension_{action}_ext"].fillna("")
        result[f"restante_segundo_{action}"] = result[f"segundo_tope_{action}"] - result[action].fillna(0)
        result = result.drop(columns=[f"segundo_tope_{action}_ext", f"comentario_extension_{action}_ext"])
    return result


def near_top_or_over(restante: pd.Series, threshold: int) -> pd.Series:
    return restante.notna() & restante.le(float(threshold))


def positive_action(summary: pd.DataFrame, action: str) -> pd.Series:
    return summary[action].fillna(0).gt(0)


def mark_visible_for_threshold(result: pd.DataFrame, threshold: int, mode: str) -> pd.DataFrame:
    core_near = near_top_or_over(result["restante_CORE"], threshold)
    value_near = near_top_or_over(result["restante_VALUE"], threshold)
    if mode == "Core":
        result = result[core_near].copy()
        result["mostrar_CORE"] = positive_action(result, "CORE")
        result["mostrar_VALUE"] = False
    elif mode == "Value":
        result = result[value_near].copy()
        result["mostrar_CORE"] = False
        result["mostrar_VALUE"] = positive_action(result, "VALUE")
    elif mode == "Core y Value":
        result = result[core_near & value_near].copy()
        result["mostrar_CORE"] = positive_action(result, "CORE")
        result["mostrar_VALUE"] = positive_action(result, "VALUE")
    else:
        result = result[core_near | value_near].copy()
        result["mostrar_CORE"] = positive_action(result, "CORE") & near_top_or_over(result["restante_CORE"], threshold)
        result["mostrar_VALUE"] = positive_action(result, "VALUE") & near_top_or_over(result["restante_VALUE"], threshold)
    return result


def apply_summary_filters(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return summary
    result = summary.copy()
    result["mostrar_CORE"] = result["CORE"].fillna(0) > 0
    result["mostrar_VALUE"] = result["VALUE"].fillna(0) > 0
    st.sidebar.markdown("### Control de topes")
    code_search = st.sidebar.text_input("Buscar codigo de cliente", value="", placeholder="Ej: 3270")
    if code_search.strip():
        terms = [term.strip() for term in code_search.replace(";", ",").replace(" ", ",").split(",") if term.strip()]
        if terms:
            code_text = result["cliente_codigo"].fillna("").astype(str)
            result = result[code_text.apply(lambda value: any(term in value for term in terms))]

    tope_filter = st.sidebar.selectbox(
        "Estado de tope",
        [
            "Todos",
            "Llegaron al tope Core",
            "Llegaron al tope Value",
            "Llegaron a algun tope",
            "Llegaron a ambos topes",
            "No llegaron a ningun tope",
            "Faltan <= 50 Core",
            "Faltan <= 50 Value",
            "Faltan <= 50 en alguno",
            "Faltan <= 50 en ambos",
            "Faltan <= 100 Core",
            "Faltan <= 100 Value",
            "Faltan <= 100 en alguno",
            "Faltan <= 100 en ambos",
        ],
    )
    core_done = result["avance_CORE"] >= 100
    value_done = result["avance_VALUE"] >= 100

    st.sidebar.markdown("### Faltante cercano")
    only_near_top = st.sidebar.checkbox("Solo clientes cerca del tope o pasados", value=False)
    near_threshold = st.sidebar.selectbox(
        "Umbral faltante",
        [50, 100],
        index=0,
        disabled=not only_near_top,
        format_func=lambda value: f"{value} bultos",
    )
    near_action = st.sidebar.selectbox(
        "Aplicar faltante a",
        ["Core o Value", "Core", "Value", "Core y Value"],
        disabled=not only_near_top,
    )

    if tope_filter == "Llegaron al tope Core":
        result = result[core_done]
    elif tope_filter == "Llegaron al tope Value":
        result = result[value_done]
    elif tope_filter == "Llegaron a algun tope":
        result = result[core_done | value_done]
    elif tope_filter == "Llegaron a ambos topes":
        result = result[core_done & value_done]
    elif tope_filter == "No llegaron a ningun tope":
        result = result[~core_done & ~value_done]
    elif tope_filter.startswith("Faltan <= "):
        threshold = 100 if "100" in tope_filter else 50
        if "Core" in tope_filter:
            result = mark_visible_for_threshold(result, threshold, "Core")
        elif "Value" in tope_filter:
            result = mark_visible_for_threshold(result, threshold, "Value")
        elif "ambos" in tope_filter:
            result = mark_visible_for_threshold(result, threshold, "Core y Value")
        else:
            result = mark_visible_for_threshold(result, threshold, "Core o Value")

    if only_near_top:
        result = mark_visible_for_threshold(result, int(near_threshold), near_action)
    return result


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


def render_action_table(summary: pd.DataFrame, action: str) -> None:
    if summary.empty:
        st.info("No hay clientes para los filtros seleccionados.")
        return
    action = action.upper()
    bultos_col = action
    tope_col = f"tope_{action}"
    avance_col = f"avance_{action}"
    restante_col = f"restante_{action}"
    visible_col = f"mostrar_{action}"
    extension_col = f"extension_{action}"
    first_col = f"primer_tope_comprado_{action}"
    second_bought_col = f"segundo_tramo_comprado_{action}"
    second_top_col = f"segundo_tope_{action}"
    second_left_col = f"restante_segundo_{action}"
    title = "CORE" if action == "CORE" else "VALUE"
    if visible_col in summary.columns:
        table = summary[summary[visible_col].fillna(False)].copy()
    else:
        table = summary[summary[bultos_col].fillna(0) > 0].copy()
    if table.empty:
        st.info(f"No hay clientes con compra {title} para los filtros seleccionados.")
        return
    table = table.sort_values([avance_col, bultos_col], ascending=[False, False])
    rows = []
    for _, row in table.iterrows():
        extension_text = "EXTENSION PEDIDA" if bool(row.get(extension_col, False)) else "-"
        rows.append(
            "<tr>"
            f"<td>{row['cliente_codigo']}</td>"
            f"<td>{row['cliente']}</td>"
            f"<td>{row['canal_accion']}</td>"
            f"<td>{extension_action_for_channel(row['canal_accion'], 'codigo')}</td>"
            f"<td>{extension_action_for_channel(row['canal_accion'], 'accion')}</td>"
            f"<td>{format_num(row[bultos_col])}</td>"
            f"<td>{format_num(row[tope_col])}</td>"
            f"<td class='{status_class(row[avance_col])}'>{format_pct(row[avance_col])}</td>"
            f"<td>{format_num(row[restante_col])}</td>"
            f"<td class='{'warn' if extension_text != '-' else ''}'>{extension_text}</td>"
            f"<td>{format_num(row.get(first_col))}</td>"
            f"<td>{format_num(row.get(second_bought_col))}</td>"
            f"<td>{format_num(row.get(second_top_col))}</td>"
            f"<td>{format_num(row.get(second_left_col))}</td>"
            f"<td>{row['supervisor']}</td>"
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
                        <th>Cod accion ext.</th><th>Accion extension</th>
                        <th>{title} bultos</th><th>Tope {title}</th><th>Avance {title}</th><th>Restan {title}</th>
                        <th>Extension</th><th>Comprado 1er tope</th><th>Comprado 2do tramo</th><th>2do tope</th><th>Restan 2do</th>
                        <th>Supervisor</th><th>Vendedor</th><th>Ruta</th>
                    </tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def export_action_table(summary: pd.DataFrame, action: str) -> pd.DataFrame:
    action = action.upper()
    bultos_col = action
    tope_col = f"tope_{action}"
    avance_col = f"avance_{action}"
    restante_col = f"restante_{action}"
    visible_col = f"mostrar_{action}"
    extension_col = f"extension_{action}"
    first_col = f"primer_tope_comprado_{action}"
    second_bought_col = f"segundo_tramo_comprado_{action}"
    second_top_col = f"segundo_tope_{action}"
    second_left_col = f"restante_segundo_{action}"
    if visible_col in summary.columns:
        source = summary[summary[visible_col].fillna(False)].copy()
    else:
        source = summary[summary[bultos_col].fillna(0) > 0].copy()
    for column in [extension_col, first_col, second_bought_col, second_top_col, second_left_col]:
        if column not in source.columns:
            source[column] = np.nan if column != extension_col else False
    source["codigo_accion_extension"] = source["canal_accion"].map(lambda value: extension_action_for_channel(value, "codigo"))
    source["accion_extension"] = source["canal_accion"].map(lambda value: extension_action_for_channel(value, "accion"))
    source["descripcion_accion_extension"] = source["canal_accion"].map(lambda value: extension_action_for_channel(value, "descripcion"))
    return (
        source
        .sort_values([avance_col, bultos_col], ascending=[False, False])
        [[
            "cliente_codigo",
            "cliente",
            "canal_accion",
            "codigo_accion_extension",
            "accion_extension",
            "descripcion_accion_extension",
            bultos_col,
            tope_col,
            avance_col,
            restante_col,
            extension_col,
            first_col,
            second_bought_col,
            second_top_col,
            second_left_col,
            "supervisor",
            "vendedor",
            "ruta",
        ]]
        .rename(
            columns={
                "cliente_codigo": "Cod cliente",
                "cliente": "Cliente",
                "canal_accion": "Canal",
                "codigo_accion_extension": "Cod accion extension",
                "accion_extension": "Accion extension",
                "descripcion_accion_extension": "Descripcion accion extension",
                bultos_col: f"{action} bultos",
                tope_col: f"Tope {action}",
                avance_col: f"Avance {action} %",
                restante_col: f"Restan {action}",
                extension_col: "Extension pedida",
                first_col: "Comprado 1er tope",
                second_bought_col: "Comprado 2do tramo",
                second_top_col: "2do tope",
                second_left_col: "Restan 2do",
                "supervisor": "Supervisor",
                "vendedor": "Vendedor",
                "ruta": "Ruta",
            }
        )
    )


def style_excel_sheet(sheet) -> None:
    sheet.freeze_panes = "A2"
    for cell in sheet[1]:
        cell.font = cell.font.copy(bold=True, color="FFFFFF")
        cell.fill = cell.fill.copy(fill_type="solid", fgColor="28549A")
    for column_cells in sheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 10), 38)


def export_summary_excel(core_export: pd.DataFrame, value_export: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        core_export.to_excel(writer, sheet_name="Core", index=False)
        value_export.to_excel(writer, sheet_name="Value", index=False)
        style_excel_sheet(writer.book["Core"])
        style_excel_sheet(writer.book["Value"])
    buffer.seek(0)
    return buffer.getvalue()


def extension_editor_rows(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if summary.empty:
        return pd.DataFrame(columns=["cliente_codigo", "cliente", "canal_accion", "accion", "bultos", "primer_tope", "extension_pedida", "segundo_tope", "comentario"])
    for action in ["CORE", "VALUE"]:
        bultos_col = action
        avance_col = f"avance_{action}"
        tope_col = f"tope_{action}"
        extension_col = f"extension_{action}"
        second_top_col = f"segundo_tope_{action}"
        comment_col = f"comentario_extension_{action}"
        candidates = summary[(summary[avance_col].fillna(0) >= 100) | summary[extension_col].fillna(False)].copy()
        for _, row in candidates.iterrows():
            first_top = float(row.get(tope_col) or 0)
            second_top = row.get(second_top_col)
            if pd.isna(second_top):
                second_top = first_top * 2 if first_top else np.nan
            rows.append(
                {
                    "cliente_codigo": row["cliente_codigo"],
                    "cliente": row["cliente"],
                    "canal_accion": row["canal_accion"],
                    "accion": action,
                    "bultos": float(row.get(bultos_col) or 0),
                    "primer_tope": first_top,
                    "extension_pedida": bool(row.get(extension_col, False)),
                    "segundo_tope": float(second_top) if not pd.isna(second_top) else np.nan,
                    "comentario": str(row.get(comment_col) or ""),
                }
            )
    if not rows:
        return pd.DataFrame(columns=["cliente_codigo", "cliente", "canal_accion", "accion", "bultos", "primer_tope", "extension_pedida", "segundo_tope", "comentario"])
    return pd.DataFrame(rows).sort_values(["accion", "bultos"], ascending=[True, False])


def save_top_extensions(webapp_url: str, rows: pd.DataFrame) -> dict[str, object]:
    payload_rows = []
    for _, row in rows.iterrows():
        primer_tope = pd.to_numeric(row.get("primer_tope"), errors="coerce")
        segundo_tope = pd.to_numeric(row.get("segundo_tope"), errors="coerce")
        payload_rows.append(
            {
                "cliente_codigo": str(row.get("cliente_codigo") or "").strip(),
                "cliente": str(row.get("cliente") or "").strip(),
                "canal": str(row.get("canal_accion") or "").strip(),
                "accion": str(row.get("accion") or "").strip().upper(),
                "primer_tope": 0.0 if pd.isna(primer_tope) else float(primer_tope),
                "segundo_tope": 0.0 if pd.isna(segundo_tope) else float(segundo_tope),
                "activa": bool(row.get("extension_pedida", False)),
                "comentario": str(row.get("comentario") or "").strip(),
            }
        )
    payload = {"tipo": "extension_topes", "rows": payload_rows}
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


def render_extension_manager(summary: pd.DataFrame, webapp_url: str) -> None:
    editor = extension_editor_rows(summary)
    with st.expander("Extensiones de tope pedidas", expanded=False):
        if editor.empty:
            st.info("No hay clientes al tope para pedir extension con los filtros actuales.")
            return
        edited = st.data_editor(
            editor,
            hide_index=True,
            width="stretch",
            disabled=["cliente_codigo", "cliente", "canal_accion", "accion", "bultos", "primer_tope"],
            column_config={
                "cliente_codigo": st.column_config.TextColumn("Cod cliente"),
                "cliente": st.column_config.TextColumn("Cliente"),
                "canal_accion": st.column_config.TextColumn("Canal"),
                "accion": st.column_config.TextColumn("Accion"),
                "bultos": st.column_config.NumberColumn("Bultos", format="%.1f"),
                "primer_tope": st.column_config.NumberColumn("1er tope", format="%.1f"),
                "extension_pedida": st.column_config.CheckboxColumn("Extension pedida"),
                "segundo_tope": st.column_config.NumberColumn("2do tope", min_value=0.0, step=1.0, format="%.1f"),
                "comentario": st.column_config.TextColumn("Comentario"),
            },
            key="extension_topes_editor",
        )
        if st.button("Guardar extensiones en Sheet", width="stretch"):
            try:
                result = save_top_extensions(webapp_url, edited)
                st.cache_data.clear()
                st.success(f"Extensiones guardadas. Filas escritas: {result.get('escritos', 0)}")
            except Exception as exc:
                st.error(f"No pude guardar extensiones: {exc}")


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon=page_icon(), layout="wide")
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
    loading_placeholder = st.empty()
    loading_placeholder.markdown(loading_truck_html(), unsafe_allow_html=True)

    st.sidebar.header("Datos")
    if "bultos_drive_refresh" not in st.session_state:
        st.session_state["bultos_drive_refresh"] = 0.0
    drive_url = sales_app.secret_or_env("GOOGLE_DRIVE_PLANIFICACION_URL", DEFAULT_DRIVE_URL)
    sheet_url = extensions_sheet_url()
    webapp_url = extensions_webapp_url()
    if st.sidebar.button("Actualizar datos", width="stretch"):
        st.session_state["bultos_drive_refresh"] = time.time()
        st.cache_data.clear()

    folder = prepare_drive_sources(
        drive_url,
        force_refresh=bool(st.session_state["bultos_drive_refresh"]),
    )
    if folder is None:
        st.sidebar.warning("No pude leer Google Drive. Use carga manual o revise el link/permiso.")
        folder = fallback_data_folder()
    st.sidebar.caption(f"Drive: {drive_url}")
    st.sidebar.caption("Extensiones: Google Sheet")
    st.sidebar.caption(f"Carpeta usada: {folder if folder else 'sin carpeta'}")

    uploaded_file = st.sidebar.file_uploader("Carga manual ventadiaria bultos", type=["txt", "csv"])
    source_path = latest_bultos_file(folder)
    if source_path is not None:
        st.sidebar.success(f"Fuente: {source_path.name}")
    elif uploaded_file is None:
        loading_placeholder.empty()
        st.warning("No encontre archivo con nombre 'ventadiaria bultos' en la carpeta. Subilo al Drive o cargalo manualmente.")
        return

    raw, source_label = read_raw_source(source_path, uploaded_file)
    if raw.empty:
        loading_placeholder.empty()
        st.warning("No pude leer el archivo de bultos.")
        return
    quantity_col = choose_quantity_column(raw)
    if clean_name(quantity_col) != clean_name(TARGET_QUANTITY_COLUMN):
        loading_placeholder.empty()
        st.error(f"El archivo debe tener la columna '{TARGET_QUANTITY_COLUMN}' para calcular bultos.")
        return
    data, source_label, _, quantity_used = load_enriched_data(folder, uploaded_file, quantity_col)
    st.sidebar.caption(f"Columna usada: {quantity_used}")
    loading_placeholder.empty()

    if data.empty:
        loading_placeholder.empty()
        st.warning("No hay filas Core/Value de CZA para clientes K+T o AS con el archivo seleccionado.")
        return

    filtered = apply_filters(data)
    summary = build_customer_summary(filtered)
    extensions = load_top_extensions(sheet_url)
    summary = merge_top_extensions(summary, extensions)
    summary_view = apply_summary_filters(summary)
    render_kpis(summary_view)
    render_extension_manager(summary_view, webapp_url)

    st.subheader("Detalle CORE")
    render_action_table(summary_view, "CORE")
    st.subheader("Detalle VALUE")
    render_action_table(summary_view, "VALUE")

    core_export = export_action_table(summary_view, "CORE")
    value_export = export_action_table(summary_view, "VALUE")
    st.download_button(
        "Exportar listado Excel",
        data=export_summary_excel(core_export, value_export),
        file_name="clientes_tope_core_value.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )


if __name__ == "__main__":
    main()
