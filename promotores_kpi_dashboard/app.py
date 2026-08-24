from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import shutil
import time
import urllib.request
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard_data import (
    DAY_COLS,
    DAY_GROUPS,
    EXCLUDED_VENDORS,
    KPI_FOCUSES,
    filter_client_activations_by_focus_range,
    filter_sales_by_focus,
    filter_sales_by_focus_range,
    focus_sales,
    load_auxiliares,
    load_dataset,
    load_ventas,
    only_new_sku_activations_range,
    summarize,
    trend_by_focus,
)


DEFAULT_DATA_DIR = r"C:\Users\triesgo\Desktop\CCC"
DEFAULT_DRIVE_URL = "https://drive.google.com/drive/folders/1cukgXLUaPsEDK_yD7tSwgaBFZAbiDUot?usp=drive_link"
DEFAULT_DRIVE_FILE_IDS = {
    "20260519122321plantillaClientesAR.xlsx": "1GuRrGKlb7SLjI9h81XssZTpWzgPUrpRb",
    "AUXILIARES.xlsx": "1zXhbWtT7K1tY43MmYz7oTTYifMgmLyFT",
    "RUTAS 7-26.xlsx": "12REZlhQOVsQVIEIAKJ6mFSsrtNCSK7s8",
    "reporte de clientes.xlsx": "1ZR9WOeqpaq9t-mJZM4f9AlUV7BIrKVo-",
    "venta anual.txt": "16-AIn2Sp0TODYXKXaM2duX2pEw4TRPAV",
    "ventadiaria.txt": "12c7hy-bTbg7P_1QYUyKKcooNLo4iog1x",
}
DEFAULT_ANNUAL_SALES_FILE_ID = "16-AIn2Sp0TODYXKXaM2duX2pEw4TRPAV"
DEFAULT_MONTHLY_CLOSED_FILE_IDS = {
    "VENTA JUNIO 2026.txt": "1t3Qck9PMkvq4qp6XNynVUAGV1REP8NqD",
    "VENTA JULIO.txt": "1nMCKcAXe7n_ROsJtbtgSuqik5pR4VdCW",
}
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/15ITRhsY5mvK3NSHeOKV2MymC078pT9TPAwKUdZDfjnI/edit?usp=sharing"
DEFAULT_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbwDlxEbBN2kmy5oVtb4LJiPFN0KtAZw-nI9TolDtfOIVuMxQqIZprMB1pquTesPGYHe/exec"
PROJECT_ROOT = Path(__file__).resolve().parent
PLAN_FILE = Path("planificacion_promotores.csv")
PLANIFICADOR_PROMOTORES_URL = "https://planificacion-ifeevprb7is4zwjk6k5suo.streamlit.app/"
COMBO_OPTION_PREFIX = "COMBO/PROMO: "


def cliente_sku_key(df: pd.DataFrame):
    producto = df.get("producto", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    articulo = df.get("articulo_descripcion", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    sku = producto.where(producto.ne(""), articulo)
    return df["cliente"].fillna("").astype(str) + "|" + sku

st.set_page_config(page_title="Dashboard Promotores", layout="wide")

st.markdown(
    """
    <style>
    html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
        color: #111827;
        background: #FFFFFF;
    }
    .block-container { padding-top: 1.4rem; }
    h1, h2, h3, p, label { color: #111827; }
    button, button p, button span,
    a[data-testid="stBaseLinkButton"], a[data-testid="stBaseLinkButton"] p, a[data-testid="stBaseLinkButton"] span {
        color: #FFFFFF !important;
    }
    [data-baseweb="tooltip"], [data-baseweb="tooltip"] * {
        color: #FFFFFF !important;
        background-color: #111827 !important;
    }
    [data-testid="stTooltipContent"], [data-testid="stTooltipContent"] * {
        color: #FFFFFF !important;
        background-color: #111827 !important;
    }
    div[data-testid="stDataFrame"] button,
    div[data-testid="stDataFrame"] button * {
        color: #FFFFFF !important;
    }
    [data-testid="stMetricValue"] { color: #111827; font-size: 2rem; }
    [data-testid="stMetricLabel"] { color: #111827; }
    div[data-testid="stDataFrame"] { border: 1px solid #D1D5DB; border-radius: 6px; }
    .kpi-card {
        border: 1px solid #D8DEE9;
        border-radius: 8px;
        padding: 16px 18px;
        background: #F9FAFB;
        min-height: 132px;
        margin-bottom: 12px;
    }
    .kpi-label {
        color: #111827;
        font-size: 15px;
        font-weight: 700;
        margin-bottom: 6px;
    }
    .kpi-title {
        color: #1F2937;
        font-size: 13px;
        margin-bottom: 12px;
    }
    .kpi-value {
        color: #111827;
        font-size: 40px;
        line-height: 1;
        font-weight: 800;
    }
    .kpi-sub {
        color: #374151;
        font-size: 12px;
        margin-top: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def cached_load_dataset(base_dir: str, signature: tuple):
    return load_dataset(base_dir)


@st.cache_data(show_spinner=False)
def cached_load_historical_sales(sales_paths: tuple[str, ...], aux_path: str, signature: tuple):
    brand_map, mix_map, caliber_map = load_auxiliares(Path(aux_path))
    frames = [load_ventas(Path(path), brand_map, mix_map, caliber_map) for path in sales_paths]
    if not frames:
        return pd.DataFrame()
    ventas_historicas = pd.concat(frames, ignore_index=True).drop_duplicates()
    return ventas_historicas[~ventas_historicas["vendedor"].isin(EXCLUDED_VENDORS)].copy()


def file_signature(base_dir: str):
    base = Path(base_dir)
    signature = []
    if not base.exists():
        return (str(base), None)
    suffixes = {".xlsx", ".xls", ".txt", ".csv"}
    for path in sorted(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in suffixes):
        name = path.name.upper()
        if any(term in name for term in ["RUTAS", "AUXILIARES", "VENTA", "PLANTILLACLIENTESAR"]):
            signature.append((str(path), path.stat().st_mtime, path.stat().st_size))
    return tuple(signature)


def secret_or_env(name: str, default: str = ""):
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, default)


def planner_sheet_url():
    return secret_or_env("PLANNER_GOOGLE_SHEET_URL", DEFAULT_SHEET_URL)


def planner_webapp_url():
    return secret_or_env("PLANNER_WEBAPP_URL", DEFAULT_WEBAPP_URL)


def google_sheet_export_url(raw_url: str):
    import re

    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", raw_url or "")
    if match:
        return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=xlsx"
    return raw_url


@st.cache_data(show_spinner=False, ttl=120)
def load_plan_from_sheet(sheet_url: str):
    if not sheet_url:
        return pd.DataFrame(columns=["fecha", "ruta", "kpi", "promotor", "planificado"])
    try:
        workbook = pd.read_excel(google_sheet_export_url(sheet_url), sheet_name=None, dtype=str)
    except Exception:
        return pd.DataFrame(columns=["fecha", "ruta", "kpi", "promotor", "planificado"])
    sheet = workbook.get("BD_KPI_PROMOTORES")
    if sheet is None or sheet.empty:
        return pd.DataFrame(columns=["fecha", "ruta", "kpi", "promotor", "planificado"])
    sheet.columns = [str(col).strip().lower() for col in sheet.columns]
    required = ["fecha", "ruta", "kpi", "promotor", "planificado"]
    if not set(required).issubset(sheet.columns):
        return pd.DataFrame(columns=required)
    plan = sheet[required].copy()
    plan["fecha"] = pd.to_datetime(plan["fecha"], errors="coerce").dt.strftime("%Y-%m-%d").fillna(plan["fecha"].astype(str))
    plan["planificado"] = pd.to_numeric(plan["planificado"], errors="coerce").fillna(0)
    return plan.dropna(subset=["fecha", "ruta", "kpi", "promotor"])


def is_drive_url(value: str):
    value = str(value or "").strip().lower()
    return value.startswith("http://") or value.startswith("https://")


def google_drive_folder_id(value: str):
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", str(value or ""))
    return match.group(1) if match else ""


def normalized_drive_name(name: str):
    normalized = str(name or "").upper().replace("_", " ").replace("-", " ")
    return " ".join(normalized.split())


def is_closed_month_sales_file(name: str):
    normalized = normalized_drive_name(Path(str(name)).name)
    compact = normalized.replace(" ", "")
    return (
        ("VENTA" in normalized or "FACTURACION" in normalized or "FACTURACIÓN" in normalized)
        and "ANUAL" not in normalized
        and "DIARIA" not in compact
        and normalized.endswith((".TXT", ".CSV"))
    )


def resolve_google_drive_folder(drive_url: str | None = None, force_refresh: bool = False):
    drive_url = drive_url or secret_or_env("GOOGLE_DRIVE_PLANIFICACION_URL", DEFAULT_DRIVE_URL)
    if not drive_url:
        return None, "Sin URL de Drive configurada"

    cache_root = PROJECT_ROOT / ".cloud_data"
    target = cache_root / "promotores"
    if target.exists() and any(target.rglob("*")) and not force_refresh:
        return target, "Drive cache"

    try:
        import gdown
    except ImportError:
        return (target if target.exists() else None), "Falta instalar gdown"

    cache_root.mkdir(parents=True, exist_ok=True)
    tmp = cache_root / f"promotores_tmp_{int(time.time())}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    def wanted_drive_file(name: str):
        normalized = normalized_drive_name(name)
        compact = normalized.replace(" ", "")
        return (
            "RUTAS" in normalized
            or "AUXILIARES" in normalized
            or ("REPORTE" in normalized and "CLIENTES" in normalized)
            or ("VENTA" in normalized and "DIARIA" in compact and "ANUAL" not in normalized and "BULTOS" not in normalized)
            or "PLANTILLACLIENTESAR" in compact
        )

    try:
        if google_drive_folder_id(drive_url) == google_drive_folder_id(DEFAULT_DRIVE_URL):
            def download_default_file(item):
                local_name, file_id = item
                gdown.download(id=file_id, output=str(tmp / local_name), quiet=True, use_cookies=False)
                return local_name

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(download_default_file, item) for item in DEFAULT_DRIVE_FILE_IDS.items()]
                for future in as_completed(futures):
                    future.result()
            try:
                drive_files = gdown.download_folder(url=drive_url, output=str(tmp), quiet=True, use_cookies=False, skip_download=True)
                selected_files = [
                    file for file in (drive_files or [])
                    if wanted_drive_file(str(file.path))
                ]
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [
                        executor.submit(
                            gdown.download,
                            id=file.id,
                            output=str(tmp / Path(str(file.path)).name),
                            quiet=True,
                            use_cookies=False,
                        )
                        for file in selected_files
                    ]
                    for future in as_completed(futures):
                        future.result()
            except Exception:
                pass
        else:
            drive_files = gdown.download_folder(url=drive_url, output=str(tmp), quiet=True, use_cookies=False, skip_download=True)
            selected_files = [file for file in (drive_files or []) if wanted_drive_file(str(file.path))]
            def download_selected_file(file):
                local_name = Path(str(file.path)).name
                gdown.download(id=file.id, output=str(tmp / local_name), quiet=True, use_cookies=False)
                return local_name

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(download_selected_file, file) for file in selected_files]
                for future in as_completed(futures):
                    future.result()
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        return (target if target.exists() else None), f"No se pudo actualizar Drive: {exc}"

    if not any(tmp.rglob("*")):
        shutil.rmtree(tmp, ignore_errors=True)
        return (target if target.exists() else None), "Drive no devolvio archivos utiles"

    if target.exists():
        shutil.rmtree(target)
    tmp.rename(target)
    return target, "Drive actualizado"


def resolve_annual_sales_file(force_refresh: bool = False):
    target = PROJECT_ROOT / ".cloud_data" / "promotores_historico" / "VENTA ANUAL.txt"
    if target.exists() and target.stat().st_size > 0 and not force_refresh:
        return target, "Venta anual cache"

    try:
        import gdown
    except ImportError:
        return (target if target.exists() else None), "Falta instalar gdown"

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    try:
        gdown.download(id=DEFAULT_ANNUAL_SALES_FILE_ID, output=str(tmp), quiet=True, use_cookies=False)
        tmp.replace(target)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink()
        return (target if target.exists() else None), f"No se pudo bajar venta anual: {exc}"
    return target, "Venta anual actualizada"


def resolve_closed_month_sales_files(force_refresh: bool = False):
    target_dir = PROJECT_ROOT / ".cloud_data" / "promotores_historico"
    target_dir.mkdir(parents=True, exist_ok=True)
    statuses = []
    paths = []

    annual_path, annual_status = resolve_annual_sales_file(force_refresh=force_refresh)
    if annual_path is not None and annual_path.exists():
        paths.append(annual_path)
    statuses.append(annual_status)

    try:
        import gdown
    except ImportError:
        return paths, "; ".join(statuses + ["Falta instalar gdown"])

    for local_name, file_id in DEFAULT_MONTHLY_CLOSED_FILE_IDS.items():
        target = target_dir / local_name
        if target.exists() and target.stat().st_size > 0 and not force_refresh:
            paths.append(target)
            statuses.append(f"{local_name}: cache")
            continue
        tmp = target.with_suffix(".tmp")
        if tmp.exists():
            tmp.unlink()
        try:
            gdown.download(id=file_id, output=str(tmp), quiet=True, use_cookies=False)
            tmp.replace(target)
            paths.append(target)
            statuses.append(f"{local_name}: actualizado")
        except Exception as exc:
            if tmp.exists():
                tmp.unlink()
            statuses.append(f"{local_name}: error {exc}")

    try:
        drive_url = secret_or_env("GOOGLE_DRIVE_PLANIFICACION_URL", DEFAULT_DRIVE_URL)
        drive_files = gdown.download_folder(url=drive_url, output=str(target_dir), quiet=True, use_cookies=False, skip_download=True)
        monthly_files = [file for file in (drive_files or []) if is_closed_month_sales_file(str(file.path))]
        existing_names = {path.name.upper() for path in paths}

        def download_monthly_file(file):
            local_name = Path(str(file.path)).name
            target = target_dir / local_name
            if target.name.upper() in existing_names and target.exists() and target.stat().st_size > 0 and not force_refresh:
                return target, f"{local_name}: cache"
            if target.exists() and target.stat().st_size > 0 and not force_refresh:
                return target, f"{local_name}: cache"
            tmp = target.with_suffix(".tmp")
            if tmp.exists():
                tmp.unlink()
            gdown.download(id=file.id, output=str(tmp), quiet=True, use_cookies=False)
            tmp.replace(target)
            return target, f"{local_name}: actualizado"

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(download_monthly_file, file) for file in monthly_files]
            for future in as_completed(futures):
                try:
                    target, status = future.result()
                    if target.exists() and target.stat().st_size > 0 and target.name.upper() not in existing_names:
                        paths.append(target)
                        existing_names.add(target.name.upper())
                    statuses.append(status)
                except Exception as exc:
                    statuses.append(f"mensual: error {exc}")
    except Exception as exc:
        statuses.append(f"mensuales Drive: error {exc}")

    local_monthlies = sorted(
        [path for path in target_dir.iterdir() if path.is_file() and is_closed_month_sales_file(path.name) and path.stat().st_size > 0],
        key=lambda path: path.name.upper(),
    )
    existing_names = {path.name.upper() for path in paths}
    for path in local_monthlies:
        if path.name.upper() not in existing_names:
            paths.append(path)
            statuses.append(f"{path.name}: cache local")

    return paths, "; ".join(statuses)


def kpi_options():
    return [f"{focus} CCC" for focus in KPI_FOCUSES]


def parse_kpi_option(option: str):
    if option.endswith(" CCC"):
        return option[:-4], "CCC"
    if option.endswith(" TBD"):
        return option[:-4], "TBD"
    return option, "CCC"


def metric_value(summary: pd.DataFrame, metric: str):
    if metric == "CCC":
        return int(summary["clientes_compra"].sum())
    return int(summary["brand_distribution"].sum())


def metric_subtitle(summary: pd.DataFrame, metric: str):
    clientes_ruta = int(summary["clientes_ruta"].sum())
    restantes = int(summary["clientes_restantes"].sum()) if "clientes_restantes" in summary.columns else clientes_ruta
    if metric == "CCC":
        clientes_compra = int(summary["clientes_compra"].sum())
        conversion = clientes_compra / clientes_ruta if clientes_ruta else 0
        return f"{conversion:.1%} activado · {clientes_ruta:,.0f} ruta · {restantes:,.0f} restantes"
    brand_distribution = int(summary["brand_distribution"].sum())
    rate = brand_distribution / clientes_ruta if clientes_ruta else 0
    return f"{rate:.2f} SKUs/cliente · {clientes_ruta:,.0f} ruta · {restantes:,.0f} restantes"


def card_html(title: str, option: str, value: int, subtitle: str):
    focus_name, metric = parse_kpi_option(option)
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{title} · {metric}</div>
        <div class="kpi-title">{focus_name}</div>
        <div class="kpi-value">{value:,.0f}</div>
        <div class="kpi-sub">{subtitle}</div>
    </div>
    """


def load_plan():
    frames = []
    if PLAN_FILE.exists():
        frames.append(pd.read_csv(PLAN_FILE, dtype={"fecha": str, "kpi": str, "promotor": str}))
    sheet_plan = load_plan_from_sheet(planner_sheet_url())
    if not sheet_plan.empty:
        frames.append(sheet_plan)
    if not frames:
        return pd.DataFrame(columns=["fecha", "ruta", "kpi", "promotor", "planificado"])
    plan = pd.concat(frames, ignore_index=True)
    if "ruta" not in plan.columns:
        plan["ruta"] = "Todas"
    if "planificado" not in plan.columns:
        plan["planificado"] = 0
    plan["planificado"] = pd.to_numeric(plan["planificado"], errors="coerce").fillna(0)
    plan = plan.drop_duplicates(["fecha", "ruta", "kpi", "promotor"], keep="last")
    return plan[["fecha", "ruta", "kpi", "promotor", "planificado"]]


def save_plan(plan: pd.DataFrame):
    clean = plan.copy()
    clean["planificado"] = pd.to_numeric(clean["planificado"], errors="coerce").fillna(0)
    clean.to_csv(PLAN_FILE, index=False)


def save_kpi_plan_to_sheet(option: str, fecha, route: str, edited: pd.DataFrame, tarjeta: str):
    url = planner_webapp_url()
    if not url:
        return None
    def number(value):
        parsed = pd.to_numeric(value, errors="coerce")
        return 0.0 if pd.isna(parsed) else float(parsed)

    rows = []
    for _, row in edited.iterrows():
        rows.append(
            {
                "fecha": str(fecha),
                "ruta": route,
                "kpi": option,
                "tarjeta": tarjeta,
                "promotor": row.get("promotor", ""),
                "clientes_ruta": number(row.get("clientes ruta")),
                "restantes": number(row.get("restantes")),
                "planificado": number(row.get("planificado")),
                "real": number(row.get("real")),
                "cumplimiento": number(row.get("cumplimiento")),
            }
        )
    payload = {"tipo": "kpi_promotores", "rows": rows}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def sheet_save_message(result, tarjeta: str):
    if not result:
        st.toast(f"Planificacion de {tarjeta.lower()} guardada localmente.")
        return
    if not result.get("ok", False):
        st.error(f"Guardado local OK, pero Sheet respondio error: {result.get('error')}")
        return
    if result.get("hoja") != "BD_KPI_PROMOTORES":
        st.error(
            "Guardado local OK, pero el Apps Script publicado no es la version nueva. "
            "Actualiza y redeploya el script para crear la hoja BD_KPI_PROMOTORES."
        )
        return
    st.toast(f"Planificacion de {tarjeta.lower()} guardada en Sheet. Filas: {result.get('escritos', 0)}")


def planning_table(summary: pd.DataFrame, option: str, metric: str, fecha, route: str):
    real_col = "clientes_compra" if metric == "CCC" else "brand_distribution"
    table = summary[["promotor", "clientes_ruta", "clientes_restantes", real_col]].rename(
        columns={"promotor": "promotor", "clientes_ruta": "clientes ruta", "clientes_restantes": "restantes", real_col: "real"}
    )
    table["fecha"] = str(fecha)
    table["ruta"] = route
    table["kpi"] = option
    plan = load_plan()
    table = table.merge(plan, on=["fecha", "ruta", "kpi", "promotor"], how="left")
    table["planificado"] = table["planificado"].fillna(0)
    table["cumplimiento"] = table.apply(
        lambda row: row["real"] / row["planificado"] * 100 if row["planificado"] else 0,
        axis=1,
    )
    return table[["promotor", "clientes ruta", "restantes", "planificado", "real", "cumplimiento"]]


def recalculate_performance(edited: pd.DataFrame):
    updated = edited.copy()
    updated["planificado"] = pd.to_numeric(updated["planificado"], errors="coerce").fillna(0)
    updated["real"] = pd.to_numeric(updated["real"], errors="coerce").fillna(0)
    updated["clientes ruta"] = pd.to_numeric(updated["clientes ruta"], errors="coerce").fillna(0)
    updated["cumplimiento"] = updated.apply(
        lambda row: row["real"] / row["planificado"] * 100 if row["planificado"] else 0,
        axis=1,
    )
    return updated


def performance_column():
    return st.column_config.ProgressColumn("cumplimiento", min_value=0, max_value=300, format="%d%%")


def update_plan(option: str, fecha, route: str, edited: pd.DataFrame):
    plan = load_plan()
    current_key = (str(fecha), route, option)
    keep = ~(
        (plan["fecha"].eq(current_key[0]))
        & (plan["ruta"].eq(current_key[1]))
        & (plan["kpi"].eq(current_key[2]))
    )
    new_rows = edited[["promotor", "planificado"]].copy()
    new_rows["fecha"] = current_key[0]
    new_rows["ruta"] = current_key[1]
    new_rows["kpi"] = current_key[2]
    new_rows = new_rows[["fecha", "ruta", "kpi", "promotor", "planificado"]]
    save_plan(pd.concat([plan[keep], new_rows], ignore_index=True))


def monthly_route_table(filtered: pd.DataFrame, rutas_base: pd.DataFrame, route_group: str):
    scope = rutas_base.copy()
    if route_group != "Todas":
        scope = scope[scope["grupo_ruta"].eq(route_group)]
    route_counts = (
        scope.drop_duplicates(["grupo_ruta", "ruta", "vendedor", "cliente"])
        .groupby(["grupo_ruta", "ruta", "promotor", "vendedor"], as_index=False)
        .agg(clientes_ruta=("cliente", "count"))
    )
    if filtered.empty:
        activations = pd.DataFrame(columns=["ruta", "vendedor", "activados", "tbd"])
    else:
        scope_keys = scope[["grupo_ruta", "ruta", "promotor", "vendedor", "cliente"]].drop_duplicates()
        tmp = filtered.merge(scope_keys, on=["vendedor", "cliente"], how="inner", suffixes=("_venta", ""))
        tmp["cliente_sku"] = cliente_sku_key(tmp)
        activations = (
            tmp.groupby(["grupo_ruta", "ruta", "promotor", "vendedor"], as_index=False)
            .agg(activados=("cliente", "nunique"), tbd=("cliente_sku", "nunique"))
        )
    table = route_counts.merge(activations, on=["grupo_ruta", "ruta", "promotor", "vendedor"], how="left")
    table[["activados", "tbd"]] = table[["activados", "tbd"]].fillna(0)
    table["restantes"] = (table["clientes_ruta"] - table["activados"]).clip(lower=0)
    table["avance"] = table.apply(
        lambda row: row["activados"] / row["clientes_ruta"] if row["clientes_ruta"] else 0,
        axis=1,
    )
    return table.sort_values(["grupo_ruta", "promotor", "ruta"])


def non_buyer_clients(filtered: pd.DataFrame, rutas_base: pd.DataFrame, route_group: str):
    scope = rutas_base.copy()
    if route_group != "Todas":
        scope = scope[scope["grupo_ruta"].eq(route_group)]
    scope_cols = ["grupo_ruta", "ruta", "supervisor", "promotor", "vendedor", "cliente", "razon_social", "nombre_fantasia"]
    if "nombre_fantasia" not in scope.columns:
        scope["nombre_fantasia"] = ""
    scope = scope[scope_cols].drop_duplicates()
    if filtered.empty:
        result = scope.copy()
    else:
        buyers = filtered[["vendedor", "cliente"]].drop_duplicates()
        buyers["compro_foco"] = True
        result = scope.merge(buyers, on=["vendedor", "cliente"], how="left")
        result = result[result["compro_foco"].isna()].drop(columns=["compro_foco"])
    return result.sort_values(["grupo_ruta", "promotor", "ruta", "razon_social", "cliente"])


def last_day_client_activations(filtered: pd.DataFrame, target_date=None):
    if filtered.empty or "fecha" not in filtered.columns:
        return pd.DataFrame(), pd.Timestamp(target_date) if target_date is not None else None
    last_date = pd.Timestamp(target_date) if target_date is not None else pd.Timestamp(filtered["fecha"].dropna().max())
    if pd.isna(last_date):
        return pd.DataFrame(), None
    previous_clients = set(
        filtered.loc[filtered["fecha"].lt(last_date), "cliente"].dropna().unique()
    )
    current = filtered[
        filtered["fecha"].eq(last_date)
        & ~filtered["cliente"].isin(previous_clients)
    ].copy()
    if current.empty:
        return current.iloc[0:0].copy(), last_date
    for col in ["producto", "articulo_descripcion", "marca", "division"]:
        if col not in current.columns:
            current[col] = ""
    group_cols = [
        col
        for col in [
            "grupo_ruta",
            "ruta",
            "supervisor",
            "promotor",
            "vendedor",
            "cliente",
            "cliente_nombre",
        ]
        if col in current.columns
    ]
    activation = (
        current.groupby(group_cols, as_index=False)
        .agg(
            productos=("producto", lambda s: ", ".join(sorted(set(x for x in s.fillna("").astype(str) if x))) or "Combo"),
            articulos=("articulo_descripcion", lambda s: ", ".join(sorted(set(x for x in s.fillna("").astype(str) if x)))[:240]),
            marcas=("marca", lambda s: ", ".join(sorted(set(x for x in s.fillna("").astype(str) if x))) or "Combo"),
            skus=("producto", "nunique"),
        )
    )
    sort_cols = [
        col
        for col in ["grupo_ruta", "promotor", "ruta", "cliente"]
        if col in activation.columns
    ]
    if sort_cols:
        activation = activation.sort_values(sort_cols)
    return activation, last_date


def promoter_accumulated_table(rutas_base: pd.DataFrame, filtered: pd.DataFrame, last_activations: pd.DataFrame):
    cartera = (
        rutas_base.drop_duplicates(["vendedor", "cliente"])
        .groupby(["supervisor", "promotor"], as_index=False)
        .agg(cartera=("cliente", "count"))
    )
    if filtered.empty:
        metrics = pd.DataFrame(columns=["supervisor", "promotor", "activados_acum", "tbd_acum"])
    else:
        tmp = filtered.copy()
        tmp["cliente_sku"] = cliente_sku_key(tmp)
        metrics = (
            tmp.groupby(["supervisor", "promotor"], as_index=False)
            .agg(
                activados_acum=("cliente", "nunique"),
                tbd_acum=("cliente_sku", "nunique"),
            )
        )
    if last_activations.empty:
        daily = pd.DataFrame(columns=["supervisor", "promotor", "activaciones_dia"])
    else:
        daily = (
            last_activations.drop_duplicates(["vendedor", "cliente"])
            .groupby(["supervisor", "promotor"], as_index=False)
            .agg(activaciones_dia=("cliente", "count"))
        )
    table = cartera.merge(metrics, on=["supervisor", "promotor"], how="left")
    table = table.merge(daily, on=["supervisor", "promotor"], how="left")
    for col in ["activados_acum", "tbd_acum", "activaciones_dia"]:
        table[col] = table[col].fillna(0).astype(int)
    table["restantes"] = (table["cartera"] - table["activados_acum"]).clip(lower=0)
    table["avance"] = table.apply(lambda row: row["activados_acum"] / row["cartera"] if row["cartera"] else 0, axis=1)
    return table.sort_values(["supervisor", "promotor"])


def route_customer_count(rutas_base: pd.DataFrame, route_group: str):
    scope = rutas_base.copy()
    if route_group != "Todas":
        scope = scope[scope["grupo_ruta"].eq(route_group)]
    return scope[["vendedor", "cliente"]].drop_duplicates().shape[0]


def latest_sales_date_for_route(ventas_df: pd.DataFrame, target_date, rutas_base: pd.DataFrame, route_group: str):
    target_date = pd.Timestamp(target_date)
    scope = rutas_base.copy()
    if route_group != "Todas":
        scope = scope[scope["grupo_ruta"].eq(route_group)]
    if scope.empty:
        return target_date
    route_keys = scope[["vendedor", "cliente"]].drop_duplicates()
    sales_scope = ventas_df.merge(route_keys, on=["vendedor", "cliente"], how="inner")
    dates = sales_scope.loc[sales_scope["fecha"].le(target_date), "fecha"].dropna()
    if dates.empty:
        return target_date
    return pd.Timestamp(dates.max())


def apply_accumulated_remaining(daily_summary: pd.DataFrame, accumulated_summary: pd.DataFrame):
    remaining = accumulated_summary[["vendedor", "clientes_restantes"]].rename(
        columns={"clientes_restantes": "clientes_restantes_acum"}
    )
    summary = daily_summary.merge(remaining, on="vendedor", how="left")
    summary["clientes_restantes"] = summary["clientes_restantes_acum"].fillna(summary["clientes_restantes"])
    return summary.drop(columns=["clientes_restantes_acum"])


def apply_remaining_before_day(daily_summary: pd.DataFrame, prior_month_summary: pd.DataFrame):
    prior = prior_month_summary[["vendedor", "clientes_compra"]].rename(
        columns={"clientes_compra": "clientes_activados_previos"}
    )
    summary = daily_summary.merge(prior, on="vendedor", how="left")
    summary["clientes_activados_previos"] = summary["clientes_activados_previos"].fillna(0)
    summary["clientes_restantes"] = (summary["clientes_ruta"] - summary["clientes_activados_previos"]).clip(lower=0)
    summary["clientes_compra"] = summary[["clientes_compra", "clientes_restantes"]].min(axis=1)
    summary.loc[summary["clientes_restantes"].le(0), "brand_distribution"] = 0
    return summary.drop(columns=["clientes_activados_previos"])


def filter_sales_by_focus_purchase_range(
    ventas_df: pd.DataFrame,
    start_date,
    end_date,
    focus: str,
    rutas_base: pd.DataFrame | None = None,
    route: str = "Todas",
):
    filtered = focus_sales(ventas_df, focus)
    filtered = filtered[(filtered["fecha"].ge(pd.Timestamp(start_date))) & (filtered["fecha"].le(pd.Timestamp(end_date)))]
    if rutas_base is not None and rutas_base.empty:
        return filtered.iloc[0:0].copy()
    if rutas_base is not None and not rutas_base.empty:
        route_scope = rutas_base.copy()
        if route != "Todas":
            route_scope = route_scope[route_scope["grupo_ruta"].eq(route)]
        route_cols = [
            col
            for col in ["grupo_ruta", "ruta", "supervisor", "promotor", "vendedor", "cliente"]
            if col in route_scope.columns
        ]
        route_keys = route_scope[route_cols].drop_duplicates()
        sales_without_route_owner = filtered.drop(
            columns=[
                col
                for col in ["grupo_ruta", "ruta", "supervisor", "promotor", "vendedor"]
                if col in filtered.columns
            ],
            errors="ignore",
        )
        filtered = route_keys.merge(sales_without_route_owner, on="cliente", how="inner")
    return filtered


def apply_route_scope_by_client(filtered: pd.DataFrame, rutas_base: pd.DataFrame | None, route: str = "Todas"):
    if rutas_base is not None and rutas_base.empty:
        return filtered.iloc[0:0].copy()
    if rutas_base is None or rutas_base.empty:
        return filtered
    route_scope = rutas_base.copy()
    if route != "Todas":
        route_scope = route_scope[route_scope["grupo_ruta"].eq(route)]
    route_cols = [
        col
        for col in ["grupo_ruta", "ruta", "supervisor", "promotor", "vendedor", "cliente"]
        if col in route_scope.columns
    ]
    route_keys = route_scope[route_cols].drop_duplicates()
    sales_without_route_owner = filtered.drop(
        columns=[
            col
            for col in ["grupo_ruta", "ruta", "supervisor", "promotor", "vendedor"]
            if col in filtered.columns
        ],
        errors="ignore",
    )
    return route_keys.merge(sales_without_route_owner, on="cliente", how="inner")


def filter_any_purchase_range(
    ventas_df: pd.DataFrame,
    start_date,
    end_date,
    rutas_base: pd.DataFrame | None = None,
    route: str = "Todas",
):
    filtered = ventas_df[(ventas_df["fecha"].ge(pd.Timestamp(start_date))) & (ventas_df["fecha"].le(pd.Timestamp(end_date)))]
    if rutas_base is not None and rutas_base.empty:
        return filtered.iloc[0:0].copy()
    if rutas_base is not None and not rutas_base.empty:
        route_scope = rutas_base.copy()
        if route != "Todas":
            route_scope = route_scope[route_scope["grupo_ruta"].eq(route)]
        route_cols = [
            col
            for col in ["grupo_ruta", "ruta", "supervisor", "promotor", "vendedor", "cliente"]
            if col in route_scope.columns
        ]
        route_keys = route_scope[route_cols].drop_duplicates()
        sales_without_route_owner = filtered.drop(
            columns=[
                col
                for col in ["grupo_ruta", "ruta", "supervisor", "promotor", "vendedor"]
                if col in filtered.columns
            ],
            errors="ignore",
        )
        filtered = route_keys.merge(sales_without_route_owner, on="cliente", how="inner")
    return filtered


def filter_business_sku_purchase_range(
    ventas_df: pd.DataFrame,
    start_date,
    end_date,
    business: str,
    skus,
    rutas_base: pd.DataFrame | None = None,
    route: str = "Todas",
):
    filtered = ventas_df[(ventas_df["fecha"].ge(pd.Timestamp(start_date))) & (ventas_df["fecha"].le(pd.Timestamp(end_date)))].copy()
    if isinstance(skus, str):
        selected_skus = [skus]
    else:
        selected_skus = list(skus or [])
    selected_skus = [sku for sku in selected_skus if sku and sku != "Todos"]
    if selected_skus:
        filtered = filtered[sku_selection_mask(filtered, selected_skus)]
    elif business != "Todos":
        filtered = filtered[business_mask(filtered, business)]
    if rutas_base is not None and rutas_base.empty:
        return filtered.iloc[0:0].copy()
    if rutas_base is not None and not rutas_base.empty:
        route_scope = rutas_base.copy()
        if route != "Todas":
            route_scope = route_scope[route_scope["grupo_ruta"].eq(route)]
        route_cols = [
            col
            for col in ["grupo_ruta", "ruta", "supervisor", "promotor", "vendedor", "cliente"]
            if col in route_scope.columns
        ]
        route_keys = route_scope[route_cols].drop_duplicates()
        sales_without_route_owner = filtered.drop(
            columns=[
                col
                for col in ["grupo_ruta", "ruta", "supervisor", "promotor", "vendedor"]
                if col in filtered.columns
            ],
            errors="ignore",
        )
        filtered = route_keys.merge(sales_without_route_owner, on="cliente", how="inner")
    return filtered


def business_options(ventas_df: pd.DataFrame):
    available = []
    for value in ["CZA", "UNG", "AGUAS", "MKTP", "SPIRITS", "OTROS"]:
        if business_mask(ventas_df, value).any():
            available.append(value)
    return ["Todos"] + available


def sku_options_for_business(ventas_df: pd.DataFrame, business: str):
    scoped = ventas_df.copy()
    if business != "Todos":
        scoped = scoped[business_mask(scoped, business)]
    scoped["_marca_option"] = scoped["marca"].fillna("").str.upper()
    scoped["_producto_option"] = scoped["producto"].fillna("")
    values = []
    for brand_value in sorted(value for value in scoped["_marca_option"].unique() if value):
        values.append(f"{brand_value} TODOS")
        brand_products = sorted(
            value
            for value in scoped.loc[scoped["_marca_option"].eq(brand_value), "_producto_option"].unique()
            if value
        )
        values.extend(brand_products)
    unbranded_products = sorted(
        value
        for value in scoped.loc[scoped["_marca_option"].eq(""), "_producto_option"].unique()
        if value
    )
    values.extend(unbranded_products)
    search_text = scoped.get("sku_search_text", pd.Series("", index=scoped.index)).fillna("").str.upper()
    special_options = []
    if search_text.str.contains("PURE GOLD| SA PG |P GOLD|PORRON PURE GOLD", regex=True, na=False).any():
        special_options.extend(["PURE GOLD 330/PORRON", "PURE GOLD 473 LATA", "PURE GOLD TODOS"])
    if search_text.str.contains("GATORADE|\\bGATO\\b|\\bGAT\\b|\\bGTD\\b", regex=True, na=False).any():
        special_options.append("GATORADE TODOS")
    if search_text.str.contains("PEPSI.*BLACK|PEP BLACK|PEP BL|BLACK 2\\.?500|COMBO BLACK", regex=True, na=False).any():
        special_options.append("PEPSI BLACK TODOS")
    special_options.extend(dynamic_combo_promo_options(ventas_df if business != "Todos" else scoped))
    values = list(dict.fromkeys(special_options + values))
    return ["Todos"] + values


def combo_promo_marker_mask(search_text: pd.Series):
    return search_text.str.contains("\\bCOMBO\\b|\\bPROMO\\b", regex=True, na=False)


def combo_option_label(description: str):
    return f"{COMBO_OPTION_PREFIX}{str(description).strip()}"


def dynamic_combo_promo_options(ventas_df: pd.DataFrame):
    if ventas_df.empty or "articulo_descripcion" not in ventas_df.columns:
        return []
    search_text = ventas_df.get("sku_search_text", pd.Series("", index=ventas_df.index)).fillna("").str.upper()
    combo_rows = ventas_df[combo_promo_marker_mask(search_text)].copy()
    if combo_rows.empty:
        return []
    descriptions = (
        combo_rows["articulo_descripcion"]
        .fillna("")
        .astype(str)
        .str.strip()
        .loc[lambda s: s.ne("")]
        .drop_duplicates()
        .sort_values()
    )
    return [combo_option_label(desc) for desc in descriptions]


def combo_business_guess(search_value: str):
    text = str(search_value or "").upper()
    if re.search(
        r"LATON|LATONES|\b710\b|L710|SA 710|LATA|LATAS|CERVEZA|PATAGONIA|\bPAT\b|"
        r"MICHELOB|PURE GOLD|\b0\.0\b|BRAHMA|QUILMES|BUD|CORONA|STELLA|ANDES|QC|BR",
        text,
    ):
        return "CZA"
    if re.search(r"BIDON|NESTLE|PUREZA|NPV|ECO|GLACIAR|AGUA", text):
        return "AGUAS"
    if re.search(r"PEPSI|\bBLACK\b|MIRINDA|\b7UP\b|GATORADE|\bGTD\b|RED\s*BULL|REDBULL|SABORIZADAS|ENERGIA|ENERGÍA", text):
        return "UNG"
    if re.search(r"\bGIN\b|SPIRITS", text):
        return "SPIRITS"
    return "Revisar"


def combo_promo_inventory(ventas_df: pd.DataFrame):
    if ventas_df.empty or "articulo_descripcion" not in ventas_df.columns:
        return pd.DataFrame(columns=["Descripcion", "Negocio sugerido", "Clientes", "Filas"])
    search_text = ventas_df.get("sku_search_text", pd.Series("", index=ventas_df.index)).fillna("").str.upper()
    combo_rows = ventas_df[combo_promo_marker_mask(search_text)].copy()
    if combo_rows.empty:
        return pd.DataFrame(columns=["Descripcion", "Negocio sugerido", "Clientes", "Filas"])
    combo_rows["_desc_combo"] = combo_rows["articulo_descripcion"].fillna("").astype(str).str.strip()
    combo_rows["_search_combo"] = combo_rows.get("sku_search_text", pd.Series("", index=combo_rows.index)).fillna("").astype(str)
    inventory = (
        combo_rows[combo_rows["_desc_combo"].ne("")]
        .groupby("_desc_combo", as_index=False)
        .agg(
            Clientes=("cliente", "nunique"),
            Filas=("cliente", "size"),
            _search=("_search_combo", "first"),
        )
    )
    inventory["Negocio sugerido"] = inventory["_search"].map(combo_business_guess)
    inventory = inventory.rename(columns={"_desc_combo": "Descripcion"}).drop(columns=["_search"])
    return inventory.sort_values(["Negocio sugerido", "Clientes", "Descripcion"], ascending=[True, False, True])


def selected_combo_descriptions(selected_skus: list[str]):
    descriptions = []
    for sku in selected_skus:
        value = str(sku).strip()
        if value.upper().startswith(COMBO_OPTION_PREFIX):
            descriptions.append(value[len(COMBO_OPTION_PREFIX):].strip())
    return descriptions


def sku_selection_mask(ventas_df: pd.DataFrame, selected_skus: list[str]):
    product = ventas_df["producto"].fillna("")
    brand = ventas_df["marca"].fillna("").str.upper()
    unified_brand = ventas_df.get("marca_unificada", pd.Series("", index=ventas_df.index)).fillna("").str.upper()
    search_text = ventas_df.get("sku_search_text", pd.Series("", index=ventas_df.index)).fillna("").str.upper()
    selected_upper = {str(sku).upper() for sku in selected_skus}
    virtual_prefixes = ("PURE GOLD", "GATORADE", "PEPSI BLACK")
    combo_descriptions = selected_combo_descriptions(selected_skus)
    combo_option_prefix_upper = COMBO_OPTION_PREFIX.upper()
    selected_upper_without_combos = {sku for sku in selected_upper if not sku.startswith(combo_option_prefix_upper)}
    brand_all_selections = {
        sku[:-6].strip()
        for sku in selected_upper_without_combos
        if sku.endswith(" TODOS") and not sku.startswith(virtual_prefixes)
    }
    direct_skus = [
        sku
        for sku in selected_skus
        if not str(sku).upper().startswith(virtual_prefixes)
        and not str(sku).upper().endswith(" TODOS")
        and not str(sku).upper().startswith(COMBO_OPTION_PREFIX)
    ]
    mask = product.isin(direct_skus)
    if combo_descriptions:
        description = ventas_df.get("articulo_descripcion", pd.Series("", index=ventas_df.index)).fillna("").astype(str).str.strip()
        mask = mask | description.isin(combo_descriptions)
    if brand_all_selections:
        mask = mask | brand.isin(brand_all_selections) | unified_brand.isin(brand_all_selections)
        water_combo = water_combo_mask(search_text)
        if any("ECO" in brand_name for brand_name in brand_all_selections):
            mask = mask | (water_combo & search_text.str.contains("ECO", regex=True, na=False))
        if any("NESTLE" in brand_name or "PUREZA" in brand_name for brand_name in brand_all_selections):
            mask = mask | (water_combo & search_text.str.contains("NESTLE|NPV|PUREZA", regex=True, na=False))
        if "GLACIAR" in brand_all_selections:
            mask = mask | (water_combo & search_text.str.contains("GLACIAR", regex=True, na=False))
        brand_combo_aliases = {
            "BRAHMA": r"BRAHMA|\bBR\b",
            "QUILMES": r"QUILMES|\bQC\b",
            "BUDWEISER": r"BUD|BUDWEISER",
            "PATAGONIA": r"PATAGONIA|\bPAT\b",
            "MICHELOB ULTRA": r"MICHELOB",
            "STELLA ARTOIS": r"STELLA",
            "CORONA": r"CORONA",
            "ANDES ORIGEN": r"ANDES",
        }
        beer_combo = beer_combo_mask(search_text)
        for brand_name, pattern in brand_combo_aliases.items():
            if brand_name in brand_all_selections:
                mask = mask | (beer_combo & search_text.str.contains(pattern, regex=True, na=False))
        nabs_combo_aliases = {
            "PEPSI": r"\bPEPSI\b",
            "MIRINDA": r"MIRINDA",
            "7UP": r"\b7UP\b",
            "RED BULL": r"RED\s*BULL|REDBULL",
            "GATORADE": r"GATORADE|\bGTD\b",
        }
        nabs_combo = nabs_combo_mask(search_text)
        for brand_name, pattern in nabs_combo_aliases.items():
            if brand_name in brand_all_selections:
                mask = mask | (nabs_combo & search_text.str.contains(pattern, regex=True, na=False))

    def is_pepsi_black_alias(value: str):
        return bool(re.search(r"PEPSI.*BLACK|PEP BLACK|PEP BL|BLACK 2\.?500", value))

    selected_rows = ventas_df[product.isin(direct_skus)]
    selected_brands = set(selected_rows.get("marca", pd.Series(dtype=str)).fillna("").str.upper())
    gatorade_selected = (
        "GATORADE TODOS" in selected_upper_without_combos
        or "GATORADE" in selected_brands
        or any("GATORADE" in sku or "GATO" in sku or re.search(r"\bGAT\b|\bGT\b", sku) for sku in selected_upper_without_combos)
    )
    pepsi_black_selected = (
        "PEPSI BLACK TODOS" in selected_upper_without_combos
        or "PEPSI BLACK" in selected_brands
        or any(re.search(r"PEPSI.*BLACK|PEP BLACK|PEP BL|BLACK 2\.?500", sku) for sku in selected_upper_without_combos)
    )
    latones_selected = any(re.search(r"LATON|LATONES|\b710\b|L710", sku) for sku in selected_upper_without_combos)
    for sku in selected_upper_without_combos:
        if sku.startswith(("PURE GOLD", "GATORADE", "PEPSI BLACK")):
            continue
        if is_pepsi_black_alias(sku):
            continue
        sku_tokens = [token for token in re.findall(r"[A-Z0-9]+", sku) if len(token) >= 3]
        meaningful_tokens = [
            token for token in sku_tokens
            if token not in {"X6", "X12", "X24", "4X6", "4X4", "2024", "IMP", "CAR", "BOT", "PET", "VIDRIO", "LATAS", "LATA", "CC"}
        ]
        if sku:
            mask = mask | search_text.str.contains(re.escape(sku), regex=True, na=False)
        if len(meaningful_tokens) >= 2:
            token_hits = pd.Series(True, index=ventas_df.index)
            for token in meaningful_tokens[:4]:
                token_hits = token_hits & search_text.str.contains(re.escape(token), regex=True, na=False)
            mask = mask | token_hits

    gatorade_base = search_text.str.contains("GATORADE|\\bGATO\\b|\\bGAT\\b|\\bGTD\\b|COMBO GTD", regex=True, na=False)
    if gatorade_selected:
        mask = mask | gatorade_base

    pepsi_black_base = search_text.str.contains(
        "PEPSI.*BLACK|PEP BLACK|PEP BL|BLACK 2\\.?500|COMBO BLACK",
        regex=True,
        na=False,
    )
    if pepsi_black_selected:
        mask = mask | pepsi_black_base

    if latones_selected:
        mask = mask | latones_combo_mask(search_text)

    pure_gold_base = search_text.str.contains("PURE GOLD| SA PG |P GOLD", regex=True, na=False)
    if "PURE GOLD TODOS" in selected_upper_without_combos:
        mask = mask | pure_gold_base
    if "PURE GOLD 330/PORRON" in selected_upper_without_combos:
        mask = mask | (
            pure_gold_base
            & search_text.str.contains("330|B330|PORRON|SIXPACK", regex=True, na=False)
        )
    if "PURE GOLD 473 LATA" in selected_upper_without_combos:
        mask = mask | (
            pure_gold_base
            & search_text.str.contains("473|L473|LATA|LATAS|CAN", regex=True, na=False)
        )
    for sku in selected_upper_without_combos:
        if "PG" in sku or "P GOLD" in sku or "PURE GOLD" in sku:
            if "330" in sku or "B330" in sku or "PORRON" in sku:
                mask = mask | (
                    pure_gold_base
                    & search_text.str.contains("330|B330|PORRON|SIXPACK", regex=True, na=False)
                )
            if "473" in sku or "L473" in sku or "LATA" in sku:
                mask = mask | (
                    pure_gold_base
                    & search_text.str.contains("473|L473|LATA|LATAS|CAN", regex=True, na=False)
                )
    return mask


def water_combo_mask(search_text: pd.Series):
    return (
        search_text.str.contains("\\bCOMBO\\b|\\bPROMO\\b", regex=True, na=False)
        & search_text.str.contains("BIDON|NESTLE|PUREZA|NPV|ECO|GLACIAR|AGUA", regex=True, na=False)
    )


def beer_combo_mask(search_text: pd.Series):
    return (
        search_text.str.contains("\\bCOMBO\\b|\\bPROMO\\b", regex=True, na=False)
        & search_text.str.contains(
            r"LATON|LATONES|\b710\b|L710|SA 710|LATA|LATAS|CERVEZA|PATAGONIA|\bPAT\b|"
            r"MICHELOB|PURE GOLD|\b0\.0\b|BRAHMA|QUILMES|BUD|CORONA|STELLA|ANDES|QC|BR",
            regex=True,
            na=False,
        )
    )


def latones_combo_mask(search_text: pd.Series):
    return (
        search_text.str.contains("\\bCOMBO\\b|\\bPROMO\\b", regex=True, na=False)
        & search_text.str.contains(r"LATON|LATONES|\b710\b|L710|SA 710|710 OW", regex=True, na=False)
    )


def nabs_combo_mask(search_text: pd.Series):
    return (
        search_text.str.contains("\\bCOMBO\\b|\\bPROMO\\b", regex=True, na=False)
        & search_text.str.contains(
            r"PEPSI|\bBLACK\b|MIRINDA|\b7UP\b|GATORADE|\bGTD\b|RED\s*BULL|REDBULL|SABORIZADAS|ENERGIA|ENERGÍA",
            regex=True,
            na=False,
        )
    )


def spirits_combo_mask(search_text: pd.Series):
    return (
        search_text.str.contains("\\bCOMBO\\b|\\bPROMO\\b", regex=True, na=False)
        & search_text.str.contains(r"\bGIN\b|SPIRITS", regex=True, na=False)
    )


def business_mask(ventas_df: pd.DataFrame, business: str):
    division = ventas_df["division"].fillna("").str.upper()
    unidad = ventas_df["unidad_negocio"].fillna("").str.upper() if "unidad_negocio" in ventas_df.columns else ""
    search_text = ventas_df.get("sku_search_text", pd.Series("", index=ventas_df.index)).fillna("").str.upper()
    if business == "CZA":
        return division.isin(["CERVEZAS", "ENV CERVEZAS"]) | beer_combo_mask(search_text)
    if business == "UNG":
        return division.isin(["GASEOSAS", "BEBIDAS SABORIZADAS", "ISOTONICAS", "BEB ENERGIZANTES"]) | nabs_combo_mask(search_text)
    if business == "AGUAS":
        return division.eq("AGUAS") | water_combo_mask(search_text)
    if business == "MKTP":
        return division.str.contains("MKTPLACE|MARKETPLACE", na=False) | pd.Series(unidad, index=ventas_df.index).str.contains("MARKETPLACE", na=False)
    if business == "SPIRITS":
        return division.str.contains("SPIRITS", na=False) | spirits_combo_mask(search_text)
    if business == "OTROS":
        known = (
            division.isin(["CERVEZAS", "ENV CERVEZAS", "GASEOSAS", "BEBIDAS SABORIZADAS", "ISOTONICAS", "BEB ENERGIZANTES", "AGUAS"])
            | division.str.contains("MKTPLACE|MARKETPLACE|SPIRITS", na=False)
            | pd.Series(unidad, index=ventas_df.index).str.contains("MARKETPLACE", na=False)
        )
        return ~known
    return pd.Series(True, index=ventas_df.index)


def cnc_business_options():
    return ["CZA", "NABS", "MATCH", "AGUAS", "MARKETPLACE", "Todos"]


def cnc_business_mask(ventas_df: pd.DataFrame, business: str):
    division = ventas_df["division"].fillna("").str.upper()
    unidad = ventas_df["unidad_negocio"].fillna("").str.upper() if "unidad_negocio" in ventas_df.columns else pd.Series("", index=ventas_df.index)
    marca = ventas_df["marca"].fillna("").str.upper() if "marca" in ventas_df.columns else pd.Series("", index=ventas_df.index)
    producto = ventas_df["producto"].fillna("").str.upper() if "producto" in ventas_df.columns else pd.Series("", index=ventas_df.index)
    if business == "CZA":
        return division.isin(["CERVEZAS", "ENV CERVEZAS"])
    if business == "NABS":
        return division.isin(["GASEOSAS", "BEBIDAS SABORIZADAS", "ISOTONICAS", "BEB ENERGIZANTES"])
    if business == "MATCH":
        return (
            division.str.contains("MATCH", na=False)
            | unidad.str.contains("MATCH", na=False)
            | marca.str.contains("MATCH", na=False)
            | producto.str.contains("MATCH", na=False)
        )
    if business == "AGUAS":
        return division.eq("AGUAS")
    if business == "MARKETPLACE":
        return division.str.contains("MKTPLACE|MARKETPLACE", na=False) | unidad.str.contains("MARKETPLACE", na=False)
    return pd.Series(True, index=ventas_df.index)


def filter_cnc_purchase_range(
    ventas_df: pd.DataFrame,
    start_date,
    end_date,
    business: str,
    rutas_base: pd.DataFrame | None = None,
    route: str = "Todas",
):
    filtered = ventas_df[(ventas_df["fecha"].ge(pd.Timestamp(start_date))) & (ventas_df["fecha"].le(pd.Timestamp(end_date)))].copy()
    if business != "Todos":
        filtered = filtered[cnc_business_mask(filtered, business)]
    if rutas_base is not None and rutas_base.empty:
        return filtered.iloc[0:0].copy()
    if rutas_base is not None and not rutas_base.empty:
        route_scope = rutas_base.copy()
        if route != "Todas":
            route_scope = route_scope[route_scope["grupo_ruta"].eq(route)]
        route_keys = route_scope[["vendedor", "cliente"]].drop_duplicates()
        filtered = filtered.merge(route_keys, on=["vendedor", "cliente"], how="inner")
    return filtered


def cnc_horizon_start(end_date, horizon: str):
    months = {"U3M": 3, "U6M": 6, "U12M": 12}.get(horizon, 3)
    return pd.Timestamp(end_date) - pd.DateOffset(months=months) + pd.Timedelta(days=1)


def filter_routes_active_at_horizon_start(rutas_df: pd.DataFrame, start_date):
    if rutas_df.empty or "alta_fecha" not in rutas_df.columns:
        return rutas_df.copy(), 0
    scoped = rutas_df.copy()
    alta = pd.to_datetime(scoped["alta_fecha"], errors="coerce")
    eligible = alta.isna() | alta.le(pd.Timestamp(start_date))
    excluded = scoped.loc[~eligible, ["vendedor", "cliente"]].drop_duplicates().shape[0]
    return scoped[eligible].copy(), excluded


def last_purchase_by_business(ventas_df: pd.DataFrame, end_date, business: str, rutas_base: pd.DataFrame, route: str):
    filtered = ventas_df[ventas_df["fecha"].le(pd.Timestamp(end_date))].copy()
    if business != "Todos":
        filtered = filtered[cnc_business_mask(filtered, business)]
    if rutas_base is not None and not rutas_base.empty:
        route_scope = rutas_base.copy()
        if route != "Todas":
            route_scope = route_scope[route_scope["grupo_ruta"].eq(route)]
        route_keys = route_scope[["vendedor", "cliente"]].drop_duplicates()
        filtered = filtered.merge(route_keys, on=["vendedor", "cliente"], how="inner")
    if filtered.empty:
        return pd.DataFrame(columns=["vendedor", "cliente", "ultima_compra_negocio"])
    return (
        filtered.groupby(["vendedor", "cliente"], as_index=False)
        .agg(ultima_compra_negocio=("fecha", "max"))
    )


def cnc_action_fields(horizon: str, business: str):
    if horizon == "U3M" and business in {"CZA", "NABS"}:
        return (
            "Asignar tarea mensual BEES Force/PDA",
            "Relevar motivo de no compra",
            "Mensual",
            "Nivel 1",
            "100%",
        )
    if horizon == "U12M":
        return (
            "Asignar frecuencia de contacto",
            "Mensual 0.25; Censo quincenal 0.50 si corresponde",
            "Mensual",
            "Nivel 1",
            "100%",
        )
    return (
        "Seguimiento mensual de recupero",
        "Identificar motivo y oportunidad de recupero",
        "Mensual",
        "Nivel 1",
        "100%",
    )


def cnc_management_table(cnc_table: pd.DataFrame, ventas_df: pd.DataFrame, end_date, horizon: str, business: str, rutas_base: pd.DataFrame, route: str):
    table = cnc_table.copy()
    if table.empty:
        return table
    last_purchase = last_purchase_by_business(ventas_df, end_date, business, rutas_base, route)
    table = table.merge(last_purchase, on=["vendedor", "cliente"], how="left")
    table["ultima_compra_negocio"] = pd.to_datetime(table["ultima_compra_negocio"], errors="coerce")
    table["dias_sin_compra"] = (pd.Timestamp(end_date) - table["ultima_compra_negocio"]).dt.days
    table["dias_sin_compra"] = table["dias_sin_compra"].fillna(9999).astype(int)
    accion, motivo, frecuencia, nivel, alcance = cnc_action_fields(horizon, business)
    table["negocio"] = business
    table["horizonte"] = horizon
    table["accion_requerida"] = accion
    table["motivo_a_relevar"] = motivo
    table["frecuencia_contacto"] = frecuencia
    table["nivel_auditoria"] = nivel
    table["alcance_objetivo"] = alcance
    table["responsable"] = table["promotor"]
    table["ultima_compra_negocio"] = table["ultima_compra_negocio"].dt.date.astype(str).replace("NaT", "Sin compra")
    return table


def apply_promoter_filter(df: pd.DataFrame, promoter: str):
    if promoter == "Todos" or df.empty or "promotor" not in df.columns:
        return df
    return df[df["promotor"].eq(promoter)].copy()


def apply_supervisor_filter(df: pd.DataFrame, supervisor: str):
    if supervisor == "Todos" or df.empty or "supervisor" not in df.columns:
        return df
    return df[df["supervisor"].eq(supervisor)].copy()


def focus_requires_alcohol_license(option: str):
    if option == "Todos":
        return False
    focus, _metric = parse_kpi_option(option)
    return focus != "Nabs"


def apply_alcohol_license_filter(df: pd.DataFrame, option: str):
    if df.empty or not focus_requires_alcohol_license(option) or "licencia_alcohol" not in df.columns:
        return df
    return df[df["licencia_alcohol"].fillna("").str.upper().eq("SI")].copy()


def apply_license_selection(df: pd.DataFrame, selection: str):
    if df.empty or selection == "Todas" or "licencia_alcohol" not in df.columns:
        return df
    license_values = df["licencia_alcohol"].fillna("").str.upper()
    if selection == "Con licencia":
        return df[license_values.eq("SI")].copy()
    if selection == "Sin licencia":
        return df[~license_values.eq("SI")].copy()
    return df


def promoter_options_for(promotores_df: pd.DataFrame, supervisor: str):
    scoped = apply_supervisor_filter(promotores_df, supervisor)
    return ["Todos"] + sorted(scoped["promotor"].dropna().unique())


def planning_date_bounds(fechas_venta: list):
    today = pd.Timestamp.today().date()
    min_date = min(fechas_venta) if fechas_venta else today
    max_data_date = max(fechas_venta) if fechas_venta else today
    default_date = max(today + timedelta(days=1), max_data_date)
    max_date = max(default_date + timedelta(days=30), max_data_date + timedelta(days=30))
    return min_date, default_date, max_date


def previous_day_route_group(fecha):
    previous_day = pd.Timestamp(fecha).date() - timedelta(days=1)
    if previous_day.weekday() == 6:
        previous_day = previous_day - timedelta(days=1)
    day_label = DAY_COLS[pd.Timestamp(previous_day).weekday()]
    return DAY_GROUPS.get(day_label, "Todas"), day_label, previous_day


def month_label(period):
    fecha = pd.Timestamp(period)
    months = {
        1: "Enero",
        2: "Febrero",
        3: "Marzo",
        4: "Abril",
        5: "Mayo",
        6: "Junio",
        7: "Julio",
        8: "Agosto",
        9: "Septiembre",
        10: "Octubre",
        11: "Noviembre",
        12: "Diciembre",
    }
    return f"{months[int(fecha.month)]} {int(fecha.year)}"


def period_controls(prefix: str, fechas_venta: list, aux_path: str):
    period_type = st.selectbox(
        "Tipo período",
        ["Mes acumulado actual", "Acumulado a fecha", "Mes cerrado histórico"],
        index=0,
        key=f"{prefix}_period_type",
    )
    period_value = "Mes acumulado"
    annual_status = ""
    historical_sales = None
    if period_type == "Mes acumulado actual":
        st.text_input("Período", "Mes acumulado", disabled=True, key=f"{prefix}_period_current_label")
    elif period_type == "Acumulado a fecha":
        period_value = st.selectbox("Período", fechas_venta, index=len(fechas_venta) - 1, key=f"{prefix}_period_date")
    else:
        with st.spinner("Preparando ventas historicas..."):
            historical_sources, annual_status = resolve_closed_month_sales_files(force_refresh=force_drive_refresh)
        if not historical_sources:
            st.error(annual_status)
            st.stop()
        historical_signature = tuple(
            (str(path), path.stat().st_mtime, path.stat().st_size) for path in historical_sources
        )
        historical_sales = cached_load_historical_sales(
            tuple(str(path) for path in historical_sources),
            str(aux_path),
            (
                historical_signature,
                str(aux_path),
                Path(aux_path).stat().st_mtime,
            ),
        )
        current_month = pd.Timestamp(max(fechas_venta)).to_period("M")
        closed_months = sorted(
            [period for period in historical_sales["fecha"].dropna().dt.to_period("M").unique() if period < current_month],
            reverse=True,
        )
        if not closed_months:
            st.error("No hay meses cerrados disponibles en venta anual.")
            st.stop()
        historical_cut = st.selectbox(
            "Corte",
            ["Mes cerrado", "Trimestre"],
            index=0,
            key=f"{prefix}_historical_cut",
        )
        if historical_cut == "Trimestre":
            quarter_periods = closed_months[:3]
            period_value = tuple(reversed(quarter_periods))
            st.caption(" + ".join(month_label(period.start_time) for period in reversed(quarter_periods)))
        else:
            month_options = {month_label(period.start_time): period for period in closed_months}
            month_selected = st.selectbox("Mes cerrado", list(month_options.keys()), index=0, key=f"{prefix}_closed_month")
            period_value = month_options[month_selected]
    sales_source = ventas
    if period_type == "Mes acumulado actual":
        end_date = pd.Timestamp(max(fechas_venta))
        start_date = end_date.replace(day=1)
        label = f"Mes acumulado {start_date.date()} a {end_date.date()}"
    elif period_type == "Mes cerrado histórico":
        sales_source = historical_sales
        if isinstance(period_value, tuple):
            start_date = pd.Timestamp(period_value[0].start_time)
            end_date = pd.Timestamp(period_value[-1].end_time).normalize()
            label = f"Trimestre {month_label(start_date)} a {month_label(end_date)} · {annual_status}"
        else:
            start_date = pd.Timestamp(period_value.start_time)
            end_date = pd.Timestamp(period_value.end_time).normalize()
            label = f"Mes cerrado {month_label(start_date)} · {annual_status}"
    else:
        end_date = pd.Timestamp(period_value)
        start_date = end_date.replace(day=1)
        label = f"Acumulado {start_date.date()} a {end_date.date()}"
    return period_type, sales_source, start_date, end_date, label


st.title("Dashboard Promotores")

with st.sidebar:
    st.header("Datos")
    st.link_button("Ir al planificador de promotores", PLANIFICADOR_PROMOTORES_URL, use_container_width=True)
    force_drive_refresh = bool(st.session_state.pop("force_drive_refresh", False))
    default_source = secret_or_env("GOOGLE_DRIVE_PLANIFICACION_URL", DEFAULT_DRIVE_URL)
    source_input = st.text_input("Carpeta local o URL de Drive", default_source)
    refresh = st.button("Tomar actualizacion de archivos", use_container_width=True, type="primary")
    if refresh:
        st.session_state["force_drive_refresh"] = True
        st.cache_data.clear()
        st.rerun()
    if is_drive_url(source_input):
        with st.spinner("Leyendo archivos desde Drive..."):
            drive_dir, drive_status = resolve_google_drive_folder(source_input, force_refresh=force_drive_refresh)
        data_dir = str(drive_dir) if drive_dir else DEFAULT_DATA_DIR
        if force_drive_refresh:
            with st.spinner("Actualizando cierres mensuales desde Drive..."):
                _closed_paths, closed_status = resolve_closed_month_sales_files(force_refresh=True)
            drive_status = f"{drive_status}; {closed_status}"
    else:
        drive_status = "Carpeta local"
        data_dir = source_input or DEFAULT_DATA_DIR
    st.caption(f"Fuente: {drive_status}")

try:
    dataset = cached_load_dataset(data_dir, file_signature(data_dir))
except Exception as exc:
    st.error(str(exc))
    st.stop()

ventas = dataset["ventas"]
rutas_dia = dataset["rutas_dia"]
rutas_grupo = dataset["rutas_grupo"]
promotores = dataset["promotores"]

fechas = [pd.Timestamp(f).date() for f in dataset["fechas"]]
options = kpi_options()
group_order = ["LUJU", "MAVI", "MISA", "DO", "OTROS"]
route_groups = [g for g in group_order if g in set(rutas_grupo["grupo_ruta"].dropna().unique())]
route_options = ["Todas"] + route_groups

view = st.radio(
    "Vista",
    ["Acumulado mensual", "Acumulado promotores", "Planificación diaria", "No compradores", "No compradores SKU", "Gestión CNC"],
    horizontal=True,
    label_visibility="collapsed",
    key="main_view",
)

if view == "Acumulado mensual":
    month_end = pd.Timestamp(max(fechas))
    month_start = month_end.replace(day=1)
    supervisor_options = ["Todos"] + sorted(promotores["supervisor"].dropna().unique())
    month_cols = st.columns([1.0, 1.15, 1.25, 1.35, 1.15, 1.8, 1.6])
    with month_cols[0]:
        month_route = st.selectbox("Grupo ruta", route_options, index=0, key="month_route")
    with month_cols[1]:
        month_supervisor = st.selectbox("Supervisor", supervisor_options, index=0, key="month_supervisor")
    with month_cols[2]:
        month_promoter_options = promoter_options_for(promotores, month_supervisor)
        month_promoter = st.selectbox("Promotor", month_promoter_options, index=0, key="month_promoter")
    with month_cols[3]:
        month_option = st.selectbox("KPI acumulado", options, index=0, key="month_kpi")
    with month_cols[4]:
        month_license = st.selectbox("Licencia alcohol", ["Todas", "Con licencia", "Sin licencia"], index=0, key="month_license")
    with month_cols[5]:
        month_focus_for_options, _month_metric_for_options = parse_kpi_option(month_option)
        month_sales_for_options = filter_sales_by_focus_range(
            ventas,
            month_start,
            month_end,
            month_focus_for_options,
            None,
            "Todas",
        )
        month_sku_options = sku_options_for_business(month_sales_for_options, "Todos")
        month_skus_selected = st.multiselect("Marca / SKU", month_sku_options, default=["Todos"], key="month_skus")
        if not month_skus_selected:
            month_skus_selected = ["Todos"]
        month_skus_filter = [sku for sku in month_skus_selected if sku != "Todos"]
        if not month_skus_filter:
            month_skus_filter = ["Todos"]
    with month_cols[6]:
        st.caption(f"Mes acumulado {month_start.date()} a {month_end.date()} · TBD = SKUs vendidos por cliente.")

    month_focus, month_metric = parse_kpi_option(month_option)
    month_rutas_base = apply_supervisor_filter(rutas_grupo, month_supervisor)
    month_rutas_base = apply_promoter_filter(month_rutas_base, month_promoter)
    month_rutas_base = apply_license_selection(month_rutas_base, month_license)
    month_promotores = apply_supervisor_filter(promotores, month_supervisor)
    month_promotores = apply_promoter_filter(month_promotores, month_promoter)
    if month_skus_filter != ["Todos"]:
        month_sku_sales = ventas[sku_selection_mask(ventas, month_skus_filter)].copy()
        month_filtered = month_sku_sales[
            month_sku_sales["fecha"].ge(pd.Timestamp(month_start))
            & month_sku_sales["fecha"].le(pd.Timestamp(month_end))
        ].copy()
        month_filtered = apply_route_scope_by_client(month_filtered, month_rutas_base, month_route)
    else:
        month_filtered = filter_sales_by_focus_purchase_range(ventas, month_start, month_end, month_focus, month_rutas_base, month_route)
    month_filtered = apply_supervisor_filter(month_filtered, month_supervisor)
    month_filtered = apply_promoter_filter(month_filtered, month_promoter)
    month_summary = summarize(month_filtered, month_rutas_base, month_promotores, month_end, month_route)
    month_table = monthly_route_table(month_filtered, month_rutas_base, month_route)

    metric_cols = st.columns(4)
    metric_cols[0].metric("Clientes ruta", f"{int(month_summary['clientes_ruta'].sum()):,}")
    metric_cols[1].metric("Activados acumulados", f"{int(month_summary['clientes_compra'].sum()):,}")
    metric_cols[2].metric("TBD acumulado", f"{int(month_summary['brand_distribution'].sum()):,}")
    metric_cols[3].metric("Restantes", f"{int(month_summary['clientes_restantes'].sum()):,}")

    st.subheader("Ruta completa")
    route_view = month_table.rename(
        columns={
            "grupo_ruta": "Grupo",
            "ruta": "Ruta",
            "promotor": "Promotor",
            "vendedor": "Vnd.",
            "clientes_ruta": "Clientes Ruta",
            "activados": "Activados Acum.",
            "tbd": "TBD Acum.",
            "restantes": "Restantes",
            "avance": "Avance",
        }
    )
    st.dataframe(
        route_view.style.format(
            {
                "Clientes Ruta": "{:,.0f}",
                "Activados Acum.": "{:,.0f}",
                "TBD Acum.": "{:,.0f}",
                "Restantes": "{:,.0f}",
                "Avance": "{:.1%}",
            }
        ).bar(subset=["Avance"], color="#94A3B8", vmin=0, vmax=1),
        use_container_width=True,
        hide_index=True,
    )

if view == "Acumulado promotores":
    promoter_end = pd.Timestamp(max(fechas))
    promoter_start = promoter_end.replace(day=1)
    supervisor_options = ["Todos"] + sorted(promotores["supervisor"].dropna().unique())
    promoter_cols = st.columns([1.25, 1.45, 1.25, 1.8, 1.7])
    with promoter_cols[0]:
        acc_supervisor = st.selectbox("Supervisor", supervisor_options, index=0, key="acc_prom_supervisor")
    with promoter_cols[1]:
        acc_option = st.selectbox("KPI acumulado", options, index=0, key="acc_prom_kpi")
    with promoter_cols[2]:
        acc_license = st.selectbox("Licencia alcohol", ["Todas", "Con licencia", "Sin licencia"], index=0, key="acc_prom_license")
    with promoter_cols[3]:
        acc_focus_for_options, _acc_metric_for_options = parse_kpi_option(acc_option)
        acc_sales_for_options = filter_sales_by_focus_range(
            ventas,
            promoter_start,
            promoter_end,
            acc_focus_for_options,
            None,
            "Todas",
        )
        acc_sku_options = sku_options_for_business(acc_sales_for_options, "Todos")
        acc_skus_selected = st.multiselect("Marca / SKU", acc_sku_options, default=["Todos"], key="acc_prom_skus")
        if not acc_skus_selected:
            acc_skus_selected = ["Todos"]
        acc_skus_filter = [sku for sku in acc_skus_selected if sku != "Todos"]
        if not acc_skus_filter:
            acc_skus_filter = ["Todos"]
    with promoter_cols[4]:
        st.caption(f"Mes acumulado {promoter_start.date()} a {promoter_end.date()} · Todas las rutas unificadas por promotor.")

    acc_focus, _acc_metric = parse_kpi_option(acc_option)
    acc_rutas_base = apply_supervisor_filter(rutas_grupo, acc_supervisor)
    acc_rutas_base = apply_license_selection(acc_rutas_base, acc_license)
    if acc_skus_filter != ["Todos"]:
        acc_sku_sales = ventas[sku_selection_mask(ventas, acc_skus_filter)].copy()
        acc_filtered = acc_sku_sales[
            acc_sku_sales["fecha"].ge(pd.Timestamp(promoter_start))
            & acc_sku_sales["fecha"].le(pd.Timestamp(promoter_end))
        ].copy()
        acc_filtered = apply_route_scope_by_client(acc_filtered, acc_rutas_base, "Todas")
    else:
        acc_filtered = filter_sales_by_focus_purchase_range(ventas, promoter_start, promoter_end, acc_focus, acc_rutas_base, "Todas")
    acc_filtered = apply_supervisor_filter(acc_filtered, acc_supervisor)
    acc_last_activations, acc_last_date = last_day_client_activations(acc_filtered, promoter_end)
    acc_table = promoter_accumulated_table(acc_rutas_base, acc_filtered, acc_last_activations)

    st.subheader("Acumulado por promotor")
    if acc_last_date is not None:
        st.caption(f"Activaciones del día = altas nuevas del {acc_last_date.date()} que no habían comprado antes el filtro seleccionado en el mes.")
    total_cartera = int(acc_table["cartera"].sum()) if not acc_table.empty else 0
    total_activados = int(acc_table["activados_acum"].sum()) if not acc_table.empty else 0
    total_dia = int(acc_table["activaciones_dia"].sum()) if not acc_table.empty else 0
    total_tbd = int(acc_table["tbd_acum"].sum()) if not acc_table.empty else 0
    acc_metric_cols = st.columns(4)
    acc_metric_cols[0].metric("Cartera", f"{total_cartera:,}")
    acc_metric_cols[1].metric("Activados acumulados", f"{total_activados:,}")
    acc_metric_cols[2].metric("Activaciones del día", f"{total_dia:,}")
    acc_metric_cols[3].metric("TBD acumulado", f"{total_tbd:,}")

    acc_view = acc_table.rename(
        columns={
            "supervisor": "Supervisor",
            "promotor": "Promotor",
            "cartera": "Cartera",
            "activados_acum": "Activados Acum.",
            "activaciones_dia": "Activaciones Día",
            "tbd_acum": "TBD Acum.",
            "restantes": "Restantes",
            "avance": "Avance",
        }
    )
    st.dataframe(
        acc_view.style.format(
            {
                "Cartera": "{:,.0f}",
                "Activados Acum.": "{:,.0f}",
                "Activaciones Día": "{:,.0f}",
                "TBD Acum.": "{:,.0f}",
                "Restantes": "{:,.0f}",
                "Avance": "{:.1%}",
            }
        ).bar(subset=["Avance"], color="#94A3B8", vmin=0, vmax=1),
        use_container_width=True,
        hide_index=True,
    )

if view == "Planificación diaria":
    supervisor_options = ["Todos"] + sorted(promotores["supervisor"].dropna().unique())
    control_cols = st.columns([1, 1.1, 1.3, 1.4, 1.5, 1.5, 1.6])
    with control_cols[0]:
        min_plan_date, default_plan_date, max_plan_date = planning_date_bounds(fechas)
        fecha = st.date_input(
            "Fecha",
            value=default_plan_date,
            min_value=min_plan_date,
            max_value=max_plan_date,
            key="day_date",
        )
    suggested_route, previous_day_label, previous_day = previous_day_route_group(fecha)
    auto_route_label = f"Dia anterior {previous_day.strftime('%d-%m')} {previous_day_label} ({suggested_route})"
    day_route_options = [auto_route_label, "Todas"] + [r for r in route_groups if r != suggested_route]
    if suggested_route not in route_groups:
        day_route_options = ["Todas"] + route_groups
    with control_cols[1]:
        route_choice = st.selectbox("Grupo ruta", day_route_options, index=0, key=f"day_route_{fecha}")
        route = suggested_route if route_choice == auto_route_label else route_choice
    with control_cols[2]:
        day_supervisor = st.selectbox("Supervisor", supervisor_options, index=0, key="day_supervisor")
    with control_cols[3]:
        day_promoter_options = promoter_options_for(promotores, day_supervisor)
        day_promoter = st.selectbox("Promotor", day_promoter_options, index=0, key="day_promoter")
    with control_cols[4]:
        card_1_option = st.selectbox("Tarjeta 1", options, index=0)
    with control_cols[5]:
        card_2_option = st.selectbox("Tarjeta 2", options, index=1)
    with control_cols[6]:
        st.caption("Real = activaciones nuevas del día. El cumplimiento usa planificado; si está en 0, usa clientes ruta.")

    day_date = pd.Timestamp(fecha)
    plan_period = str(fecha)
    day_rutas_base = apply_supervisor_filter(rutas_grupo, day_supervisor)
    day_rutas_base = apply_promoter_filter(day_rutas_base, day_promoter)
    day_promotores = apply_supervisor_filter(promotores, day_supervisor)
    day_promotores = apply_promoter_filter(day_promotores, day_promoter)
    focus_1, metric_1 = parse_kpi_option(card_1_option)
    focus_2, metric_2 = parse_kpi_option(card_2_option)
    real_date = day_date
    if route != suggested_route and route != "Todas":
        real_date = latest_sales_date_for_route(ventas, day_date, day_rutas_base, route)
    accumulated_start = real_date.replace(day=1)
    prior_accumulated_end = real_date - pd.Timedelta(days=1)
    filtered_1 = filter_client_activations_by_focus_range(
        ventas, real_date, real_date, focus_1, day_rutas_base, route, lookback_start=accumulated_start
    )
    filtered_1 = apply_promoter_filter(filtered_1, day_promoter)
    summary_1 = summarize(filtered_1, day_rutas_base, day_promotores, real_date, route)
    filtered_1_prior = filter_sales_by_focus_purchase_range(ventas, accumulated_start, prior_accumulated_end, focus_1, day_rutas_base, route)
    filtered_1_prior = apply_promoter_filter(filtered_1_prior, day_promoter)
    summary_1_prior = summarize(filtered_1_prior, day_rutas_base, day_promotores, real_date, route)
    summary_1 = apply_remaining_before_day(summary_1, summary_1_prior)
    filtered_2 = filter_client_activations_by_focus_range(
        ventas, real_date, real_date, focus_2, day_rutas_base, route, lookback_start=accumulated_start
    )
    filtered_2 = apply_promoter_filter(filtered_2, day_promoter)
    summary_2 = summarize(filtered_2, day_rutas_base, day_promotores, real_date, route)
    filtered_2_prior = filter_sales_by_focus_purchase_range(ventas, accumulated_start, prior_accumulated_end, focus_2, day_rutas_base, route)
    filtered_2_prior = apply_promoter_filter(filtered_2_prior, day_promoter)
    summary_2_prior = summarize(filtered_2_prior, day_rutas_base, day_promotores, real_date, route)
    summary_2 = apply_remaining_before_day(summary_2, summary_2_prior)
    if real_date.date() != day_date.date():
        st.caption(f"Real tomado de venta {real_date.date()} para la ruta {route}; planificación guardada en {plan_period}.")

    st.markdown(
        card_html("Tarjeta 1", card_1_option, metric_value(summary_1, metric_1), metric_subtitle(summary_1, metric_1)),
        unsafe_allow_html=True,
    )
    st.markdown("**promotor | clientes ruta | restantes | planificado | real | cumplimiento**")
    edited_plan_1 = st.data_editor(
        planning_table(summary_1, card_1_option, metric_1, plan_period, route),
        key=f"plan_1_{plan_period}_{route}_{card_1_option}",
        use_container_width=True,
        hide_index=True,
        disabled=["promotor", "clientes ruta", "restantes", "real", "cumplimiento"],
        column_config={
            "promotor": st.column_config.TextColumn("promotor"),
            "clientes ruta": st.column_config.NumberColumn("clientes ruta", format="%d"),
            "restantes": st.column_config.NumberColumn("restantes", format="%d"),
            "planificado": st.column_config.NumberColumn("planificado", min_value=0, step=1, format="%d"),
            "real": st.column_config.NumberColumn("real", format="%d"),
            "cumplimiento": performance_column(),
        },
    )
    edited_plan_1 = recalculate_performance(edited_plan_1)
    if st.button("Guardar planificacion tarjeta 1", use_container_width=True):
        update_plan(card_1_option, plan_period, route, edited_plan_1)
        result = save_kpi_plan_to_sheet(card_1_option, plan_period, route, edited_plan_1, "Tarjeta 1")
        sheet_save_message(result, "Tarjeta 1")
        st.cache_data.clear()
        st.rerun()

    st.markdown(
        card_html("Tarjeta 2", card_2_option, metric_value(summary_2, metric_2), metric_subtitle(summary_2, metric_2)),
        unsafe_allow_html=True,
    )
    st.markdown("**promotor | clientes ruta | restantes | planificado | real | cumplimiento**")
    edited_plan_2 = st.data_editor(
        planning_table(summary_2, card_2_option, metric_2, plan_period, route),
        key=f"plan_2_{plan_period}_{route}_{card_2_option}",
        use_container_width=True,
        hide_index=True,
        disabled=["promotor", "clientes ruta", "restantes", "real", "cumplimiento"],
        column_config={
            "promotor": st.column_config.TextColumn("promotor"),
            "clientes ruta": st.column_config.NumberColumn("clientes ruta", format="%d"),
            "restantes": st.column_config.NumberColumn("restantes", format="%d"),
            "planificado": st.column_config.NumberColumn("planificado", min_value=0, step=1, format="%d"),
            "real": st.column_config.NumberColumn("real", format="%d"),
            "cumplimiento": performance_column(),
        },
    )
    edited_plan_2 = recalculate_performance(edited_plan_2)
    if st.button("Guardar planificacion tarjeta 2", use_container_width=True):
        update_plan(card_2_option, plan_period, route, edited_plan_2)
        result = save_kpi_plan_to_sheet(card_2_option, plan_period, route, edited_plan_2, "Tarjeta 2")
        sheet_save_message(result, "Tarjeta 2")
        st.cache_data.clear()
        st.rerun()

    focus = focus_1
    filtered = filtered_1
    summary = summary_1
    trend_source = apply_supervisor_filter(ventas, day_supervisor)
    trend_source = apply_promoter_filter(trend_source, day_promoter)
    trend_df = trend_by_focus(trend_source, focus, day_rutas_base, route)

    left, right = st.columns([1.35, 1])
    with left:
        st.subheader("Promotores")
        view = summary[
            [
                "promotor",
                "supervisor",
                "vendedor",
                "clientes_ruta",
                "clientes_compra",
                "% compra",
                "brand_distribution",
                "BD / cliente ruta",
                "importe_neto",
            ]
        ].rename(
            columns={
                "promotor": "Promotor",
                "supervisor": "Supervisor",
                "vendedor": "Vnd.",
                "clientes_ruta": "Clientes Ruta",
                "clientes_compra": "CCC",
                "% compra": "% Compra",
                "brand_distribution": "TBD",
                "BD / cliente ruta": "BD / Cliente Ruta",
                "importe_neto": "Importe Neto",
            }
        )
        st.dataframe(
            view.style.format(
                {
                    "% Compra": "{:.1%}",
                    "BD / Cliente Ruta": "{:.2f}",
                    "Importe Neto": "${:,.0f}",
                    "Clientes Ruta": "{:,.0f}",
                    "CCC": "{:,.0f}",
                    "TBD": "{:,.0f}",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    with right:
        st.subheader("Ranking")
        ranking = (
            summary[["promotor", "clientes_compra", "brand_distribution"]]
            .rename(columns={"promotor": "Promotor", "clientes_compra": "CCC", "brand_distribution": "TBD"})
            .set_index("Promotor")
        )
        st.bar_chart(ranking, height=310)

        st.subheader("Evolucion diaria")
        trend_view = trend_df.rename(
            columns={"fecha": "Fecha", "clientes_compra": "CCC", "brand_distribution": "TBD"}
        )
        if not trend_view.empty:
            trend_view["Fecha"] = pd.to_datetime(trend_view["Fecha"]).dt.date
            st.line_chart(trend_view.set_index("Fecha"), height=260)

    st.subheader("Detalle de ventas en ruta")
    detail_cols = [
        "fecha",
        "promotor",
        "ruta",
        "cliente",
        "cliente_nombre",
        "marca_unificada",
        "segmento",
        "calibre_unificado",
        "division",
        "producto",
        "cantidad",
        "importe_neto",
    ]
    detail = filtered[detail_cols].rename(
        columns={
            "fecha": "Fecha",
            "promotor": "Promotor",
            "ruta": "Ruta",
            "cliente": "Cliente",
            "cliente_nombre": "Razon Social",
            "marca_unificada": "Marca",
            "segmento": "Segmento",
            "calibre_unificado": "Calibre",
            "division": "Division",
            "producto": "Producto",
            "cantidad": "Cantidad",
            "importe_neto": "Importe Neto",
        }
    )
    st.dataframe(detail, use_container_width=True, hide_index=True)

if view == "No compradores":
    supervisor_options = ["Todos"] + sorted(promotores["supervisor"].dropna().unique())
    nb_cols = st.columns([1.25, 1.25, 1.0, 1.15, 1.25, 1.35, 1.15, 1.45])
    with nb_cols[0]:
        nb_period_type = st.selectbox(
            "Tipo período",
            ["Mes acumulado actual", "Acumulado a fecha", "Mes cerrado histórico"],
            index=0,
            key="nb_period_type",
        )
    with nb_cols[1]:
        nb_period = "Mes acumulado"
        annual_status = ""
        annual_source = None
        annual_ventas = None
        if nb_period_type == "Mes acumulado actual":
            st.text_input("Período", "Mes acumulado", disabled=True, key="nb_period_current_label")
        elif nb_period_type == "Acumulado a fecha":
            nb_period = st.selectbox("Período", fechas, index=len(fechas) - 1, key="nb_period_date")
        else:
            with st.spinner("Preparando ventas historicas..."):
                historical_sources, annual_status = resolve_closed_month_sales_files(force_refresh=force_drive_refresh)
            if not historical_sources:
                st.error(annual_status)
                st.stop()
            historical_signature = tuple(
                (str(path), path.stat().st_mtime, path.stat().st_size) for path in historical_sources
            )
            annual_ventas = cached_load_historical_sales(
                tuple(str(path) for path in historical_sources),
                str(dataset["sources"]["auxiliares"]),
                (
                    historical_signature,
                    str(dataset["sources"]["auxiliares"]),
                    Path(dataset["sources"]["auxiliares"]).stat().st_mtime,
                ),
            )
            current_month = pd.Timestamp(max(fechas)).to_period("M")
            closed_months = sorted(
                [period for period in annual_ventas["fecha"].dropna().dt.to_period("M").unique() if period < current_month],
                reverse=True,
            )
            if not closed_months:
                st.error("No hay meses cerrados disponibles en venta anual.")
                st.stop()
            historical_cut = st.selectbox(
                "Corte",
                ["Mes cerrado", "Trimestre"],
                index=0,
                key="nb_historical_cut",
            )
            if historical_cut == "Trimestre":
                quarter_periods = closed_months[:3]
                nb_period = tuple(reversed(quarter_periods))
                st.caption(" + ".join(month_label(period.start_time) for period in reversed(quarter_periods)))
            else:
                month_options = {month_label(period.start_time): period for period in closed_months}
                nb_month_label = st.selectbox("Mes cerrado", list(month_options.keys()), index=0, key="nb_closed_month")
                nb_period = month_options[nb_month_label]
    with nb_cols[2]:
        nb_route = st.selectbox("Grupo ruta", route_options, index=0, key="nb_route")
    with nb_cols[3]:
        nb_supervisor = st.selectbox("Supervisor", supervisor_options, index=0, key="nb_supervisor")
    with nb_cols[4]:
        nb_promoter_options = promoter_options_for(promotores, nb_supervisor)
        nb_promoter = st.selectbox("Promotor", nb_promoter_options, index=0, key="nb_promoter")
    with nb_cols[5]:
        nb_focus_options = ["Todos"] + options
        nb_option = st.selectbox("Foco", nb_focus_options, index=0, key="nb_focus")
    with nb_cols[6]:
        nb_license = st.selectbox("Licencia alcohol", ["Todas", "Con licencia", "Sin licencia"], index=0, key="nb_license")
    with nb_cols[7]:
        st.caption("Lista clientes de la ruta que no compraron el foco en el período seleccionado.")

    nb_sales_source = ventas
    if nb_period_type == "Mes acumulado actual":
        nb_end = pd.Timestamp(max(fechas))
        nb_start = nb_end.replace(day=1)
        nb_label = f"Mes acumulado {nb_start.date()} a {nb_end.date()}"
    elif nb_period_type == "Mes cerrado histórico":
        nb_sales_source = annual_ventas
        if isinstance(nb_period, tuple):
            nb_start = pd.Timestamp(nb_period[0].start_time)
            nb_end = pd.Timestamp(nb_period[-1].end_time).normalize()
            nb_label = f"Trimestre {month_label(nb_start)} a {month_label(nb_end)} · {annual_status}"
        else:
            nb_start = pd.Timestamp(nb_period.start_time)
            nb_end = pd.Timestamp(nb_period.end_time).normalize()
            nb_label = f"Mes cerrado {month_label(nb_start)} · {annual_status}"
    else:
        nb_end = pd.Timestamp(nb_period)
        nb_start = nb_end.replace(day=1)
        nb_label = f"Acumulado {nb_start.date()} a {nb_end.date()}"

    nb_focus, _nb_metric = parse_kpi_option(nb_option)
    nb_rutas_base = apply_supervisor_filter(rutas_grupo, nb_supervisor)
    nb_rutas_base = apply_promoter_filter(nb_rutas_base, nb_promoter)
    nb_rutas_base = apply_license_selection(nb_rutas_base, nb_license)
    if nb_option == "Todos":
        nb_filtered = filter_any_purchase_range(nb_sales_source, nb_start, nb_end, nb_rutas_base, nb_route)
    else:
        nb_filtered = filter_sales_by_focus_purchase_range(nb_sales_source, nb_start, nb_end, nb_focus, nb_rutas_base, nb_route)
    nb_filtered = apply_supervisor_filter(nb_filtered, nb_supervisor)
    nb_filtered = apply_promoter_filter(nb_filtered, nb_promoter)
    nb_table = non_buyer_clients(nb_filtered, nb_rutas_base, nb_route)

    st.subheader("Clientes no compradores")
    st.caption(nb_label)
    metric_cols = st.columns(3)
    metric_cols[0].metric("Clientes en ruta", f"{route_customer_count(nb_rutas_base, nb_route):,}")
    buyer_label = "Clientes con compra" if nb_option == "Todos" else "Compradores foco"
    metric_cols[1].metric(buyer_label, f"{nb_filtered[['vendedor', 'cliente']].drop_duplicates().shape[0]:,}")
    metric_cols[2].metric("No compradores", f"{len(nb_table):,}")

    nb_view = nb_table.rename(
        columns={
            "grupo_ruta": "Grupo",
            "ruta": "Ruta",
            "supervisor": "Supervisor",
            "promotor": "Promotor",
            "vendedor": "Vnd.",
            "cliente": "Cliente",
            "nombre_fantasia": "Nombre Fantasía",
            "razon_social": "Razón Social",
        }
    )
    if "Nombre Fantasía" in nb_view.columns and "Razón Social" in nb_view.columns:
        nb_view["Nombre Fantasía"] = nb_view["Nombre Fantasía"].fillna("")
        nb_view["Nombre Fantasía"] = nb_view["Nombre Fantasía"].where(
            nb_view["Nombre Fantasía"].ne(""),
            nb_view["Razón Social"],
        )
    st.dataframe(nb_view, use_container_width=True, hide_index=True)

if view == "No compradores SKU":
    supervisor_options = ["Todos"] + sorted(promotores["supervisor"].dropna().unique())
    sku_cols = st.columns([1.25, 1.25, 1.0, 1.15, 1.25, 1.05, 1.15, 1.7, 1.45])
    with sku_cols[0]:
        sku_period_type = st.selectbox(
            "Tipo período",
            ["Mes acumulado actual", "Acumulado a fecha", "Mes cerrado histórico"],
            index=0,
            key="sku_period_type",
        )
    with sku_cols[1]:
        sku_period = "Mes acumulado"
        sku_annual_status = ""
        sku_annual_ventas = None
        if sku_period_type == "Mes acumulado actual":
            st.text_input("Período", "Mes acumulado", disabled=True, key="sku_period_current_label")
        elif sku_period_type == "Acumulado a fecha":
            sku_period = st.selectbox("Período", fechas, index=len(fechas) - 1, key="sku_period_date")
        else:
            with st.spinner("Preparando ventas historicas..."):
                sku_historical_sources, sku_annual_status = resolve_closed_month_sales_files(force_refresh=force_drive_refresh)
            if not sku_historical_sources:
                st.error(sku_annual_status)
                st.stop()
            sku_historical_signature = tuple(
                (str(path), path.stat().st_mtime, path.stat().st_size) for path in sku_historical_sources
            )
            sku_annual_ventas = cached_load_historical_sales(
                tuple(str(path) for path in sku_historical_sources),
                str(dataset["sources"]["auxiliares"]),
                (
                    sku_historical_signature,
                    str(dataset["sources"]["auxiliares"]),
                    Path(dataset["sources"]["auxiliares"]).stat().st_mtime,
                ),
            )
            current_month = pd.Timestamp(max(fechas)).to_period("M")
            sku_closed_months = sorted(
                [period for period in sku_annual_ventas["fecha"].dropna().dt.to_period("M").unique() if period < current_month],
                reverse=True,
            )
            if not sku_closed_months:
                st.error("No hay meses cerrados disponibles en venta anual.")
                st.stop()
            sku_historical_cut = st.selectbox(
                "Corte",
                ["Mes cerrado", "Trimestre"],
                index=0,
                key="sku_historical_cut",
            )
            if sku_historical_cut == "Trimestre":
                sku_quarter_periods = sku_closed_months[:3]
                sku_period = tuple(reversed(sku_quarter_periods))
                st.caption(" + ".join(month_label(period.start_time) for period in reversed(sku_quarter_periods)))
            else:
                sku_month_options = {month_label(period.start_time): period for period in sku_closed_months}
                sku_month_label = st.selectbox("Mes cerrado", list(sku_month_options.keys()), index=0, key="sku_closed_month")
                sku_period = sku_month_options[sku_month_label]

    sku_sales_source = ventas
    if sku_period_type == "Mes acumulado actual":
        sku_end = pd.Timestamp(max(fechas))
        sku_start = sku_end.replace(day=1)
        sku_label = f"Mes acumulado {sku_start.date()} a {sku_end.date()}"
    elif sku_period_type == "Mes cerrado histórico":
        sku_sales_source = sku_annual_ventas
        if isinstance(sku_period, tuple):
            sku_start = pd.Timestamp(sku_period[0].start_time)
            sku_end = pd.Timestamp(sku_period[-1].end_time).normalize()
            sku_label = f"Trimestre {month_label(sku_start)} a {month_label(sku_end)} · {sku_annual_status}"
        else:
            sku_start = pd.Timestamp(sku_period.start_time)
            sku_end = pd.Timestamp(sku_period.end_time).normalize()
            sku_label = f"Mes cerrado {month_label(sku_start)} · {sku_annual_status}"
    else:
        sku_end = pd.Timestamp(sku_period)
        sku_start = sku_end.replace(day=1)
        sku_label = f"Acumulado {sku_start.date()} a {sku_end.date()}"

    with sku_cols[2]:
        sku_route = st.selectbox("Grupo ruta", route_options, index=0, key="sku_route")
    with sku_cols[3]:
        sku_supervisor = st.selectbox("Supervisor", supervisor_options, index=0, key="sku_supervisor")
    with sku_cols[4]:
        sku_promoter_options = promoter_options_for(promotores, sku_supervisor)
        sku_promoter = st.selectbox("Promotor", sku_promoter_options, index=0, key="sku_promoter")
    with sku_cols[5]:
        sku_business = st.selectbox("Negocio", business_options(sku_sales_source), index=0, key="sku_business")
    with sku_cols[6]:
        sku_license = st.selectbox("Licencia alcohol", ["Todas", "Con licencia", "Sin licencia"], index=0, key="sku_license")
    with sku_cols[7]:
        period_sales_for_options = sku_sales_source[
            (sku_sales_source["fecha"].ge(pd.Timestamp(sku_start))) & (sku_sales_source["fecha"].le(pd.Timestamp(sku_end)))
        ]
        sku_product_options = sku_options_for_business(period_sales_for_options, sku_business)
        sku_products_selected = st.multiselect("SKU", sku_product_options, default=["Todos"], key="sku_products")
        if not sku_products_selected:
            sku_products_selected = ["Todos"]
        sku_products_filter = [sku for sku in sku_products_selected if sku != "Todos"]
        if not sku_products_filter:
            sku_products_filter = ["Todos"]
    with sku_cols[8]:
        if sku_products_filter == ["Todos"]:
            st.caption("Clientes de la ruta que no compraron el negocio/SKU en el período seleccionado.")
        else:
            st.caption(f"Clientes de la ruta que no compraron ninguno de los {len(sku_products_filter)} SKUs seleccionados.")

    sku_rutas_base = apply_supervisor_filter(rutas_grupo, sku_supervisor)
    sku_rutas_base = apply_promoter_filter(sku_rutas_base, sku_promoter)
    sku_rutas_base = apply_license_selection(sku_rutas_base, sku_license)
    sku_filtered = filter_business_sku_purchase_range(
        sku_sales_source,
        sku_start,
        sku_end,
        sku_business,
        sku_products_filter,
        sku_rutas_base,
        sku_route,
    )
    sku_filtered = apply_supervisor_filter(sku_filtered, sku_supervisor)
    sku_filtered = apply_promoter_filter(sku_filtered, sku_promoter)
    sku_table = non_buyer_clients(sku_filtered, sku_rutas_base, sku_route)
    sku_last_activations, sku_last_activation_date = last_day_client_activations(sku_filtered, sku_end)

    st.subheader("Clientes no compradores por negocio / SKU")
    st.caption(sku_label)
    sku_metric_cols = st.columns(4)
    sku_metric_cols[0].metric("Clientes en ruta", f"{route_customer_count(sku_rutas_base, sku_route):,}")
    sku_metric_cols[1].metric("Clientes con compra", f"{sku_filtered[['vendedor', 'cliente']].drop_duplicates().shape[0]:,}")
    sku_metric_cols[2].metric("No compradores", f"{len(sku_table):,}")
    last_day_label = sku_last_activation_date.date().isoformat() if sku_last_activation_date is not None else "-"
    sku_metric_cols[3].metric("Activados último día", f"{sku_last_activations[['vendedor', 'cliente']].drop_duplicates().shape[0]:,}", last_day_label)

    sku_view = sku_table.rename(
        columns={
            "grupo_ruta": "Grupo",
            "ruta": "Ruta",
            "supervisor": "Supervisor",
            "promotor": "Promotor",
            "vendedor": "Vnd.",
            "cliente": "Cliente",
            "nombre_fantasia": "Nombre Fantasía",
            "razon_social": "Razón Social",
        }
    )
    if "Nombre Fantasía" in sku_view.columns and "Razón Social" in sku_view.columns:
        sku_view["Nombre Fantasía"] = sku_view["Nombre Fantasía"].fillna("")
        sku_view["Nombre Fantasía"] = sku_view["Nombre Fantasía"].where(
            sku_view["Nombre Fantasía"].ne(""),
            sku_view["Razón Social"],
        )
    activation_key_cols = ["Grupo", "Ruta", "Supervisor", "Promotor", "Vnd."]
    if not sku_last_activations.empty:
        last_activation_counts = (
            sku_last_activations.rename(
                columns={
                    "grupo_ruta": "Grupo",
                    "ruta": "Ruta",
                    "supervisor": "Supervisor",
                    "promotor": "Promotor",
                    "vendedor": "Vnd.",
                    "cliente": "Cliente",
                }
            )
            .drop_duplicates(activation_key_cols + ["Cliente"])
            .groupby(activation_key_cols, as_index=False)
            .agg(**{"Activaciones último día": ("Cliente", "count")})
        )
        sku_view = sku_view.merge(last_activation_counts, on=activation_key_cols, how="left")
    else:
        sku_view["Activaciones último día"] = 0
    sku_view["Activaciones último día"] = sku_view["Activaciones último día"].fillna(0).astype(int)
    st.dataframe(sku_view, use_container_width=True, hide_index=True)

    st.subheader("Resumen por promotor")
    sku_summary_scope = sku_rutas_base.copy()
    if sku_route != "Todas":
        sku_summary_scope = sku_summary_scope[sku_summary_scope["grupo_ruta"].eq(sku_route)].copy()
    sku_promoter_base = sku_summary_scope[["promotor"]].drop_duplicates()
    sku_cartera = (
        sku_summary_scope.drop_duplicates(["promotor", "vendedor", "cliente"])
        .groupby("promotor", as_index=False)
        .agg(cartera=("cliente", "count"))
    )
    if sku_filtered.empty:
        sku_accumulated = pd.DataFrame(columns=["promotor", "acumulado"])
    else:
        sku_accumulated = (
            sku_filtered.drop_duplicates(["promotor", "vendedor", "cliente"])
            .groupby("promotor", as_index=False)
            .agg(acumulado=("cliente", "count"))
        )
    if sku_last_activations.empty:
        sku_today = pd.DataFrame(columns=["promotor", "hoy"])
    else:
        sku_today = (
            sku_last_activations.drop_duplicates(["promotor", "vendedor", "cliente"])
            .groupby("promotor", as_index=False)
            .agg(hoy=("cliente", "count"))
        )
    sku_promoter_summary = (
        sku_promoter_base
        .merge(sku_cartera, on="promotor", how="left")
        .merge(sku_accumulated, on="promotor", how="left")
        .merge(sku_today, on="promotor", how="left")
    )
    for col in ["cartera", "acumulado", "hoy"]:
        sku_promoter_summary[col] = sku_promoter_summary[col].fillna(0).astype(int)
    sku_promoter_summary["restan"] = (sku_promoter_summary["cartera"] - sku_promoter_summary["acumulado"]).clip(lower=0)
    sku_promoter_summary = sku_promoter_summary.sort_values("promotor").rename(
        columns={
            "promotor": "Promotor",
            "cartera": "Cartera",
            "acumulado": "Acumulado",
            "hoy": "Hoy",
            "restan": "Restan",
        }
    )
    st.dataframe(sku_promoter_summary, use_container_width=True, hide_index=True)

    st.subheader("Clientes activados último día")
    if sku_last_activation_date is None:
        st.caption("No hay ventas para los filtros seleccionados.")
    else:
        st.caption(
            f"Activaciones nuevas del {sku_last_activation_date.date()}: clientes que no habían comprado antes el negocio/SKU filtrado en el período."
        )
    activation_view = sku_last_activations.rename(
        columns={
            "grupo_ruta": "Grupo",
            "ruta": "Ruta",
            "supervisor": "Supervisor",
            "promotor": "Promotor",
            "vendedor": "Vnd.",
            "cliente": "Cliente",
            "cliente_nombre": "Razón Social",
            "productos": "Producto/SKU",
            "articulos": "Artículo venta",
            "marcas": "Marca",
            "skus": "SKUs",
        }
    )
    st.dataframe(activation_view, use_container_width=True, hide_index=True)

if view == "Gestión CNC":
    supervisor_options = ["Todos"] + sorted(promotores["supervisor"].dropna().unique())
    cnc_cols = st.columns([1.05, 1.15, 1.1, 1.25, 1.35, 1.25, 1.7])
    with cnc_cols[0]:
        cnc_horizon = st.selectbox("Horizonte", ["U3M", "U6M", "U12M"], index=0, key="cnc_horizon")
    with cnc_cols[1]:
        cnc_end = st.date_input("Fecha corte", value=max(fechas), min_value=min(fechas), max_value=max(fechas), key="cnc_end")
    with cnc_cols[2]:
        cnc_route = st.selectbox("Grupo ruta", route_options, index=0, key="cnc_route")
    with cnc_cols[3]:
        cnc_supervisor = st.selectbox("Supervisor", supervisor_options, index=0, key="cnc_supervisor")
    with cnc_cols[4]:
        cnc_promoter_options = promoter_options_for(promotores, cnc_supervisor)
        cnc_promoter = st.selectbox("Promotor", cnc_promoter_options, index=0, key="cnc_promoter")
    with cnc_cols[5]:
        cnc_business = st.selectbox("Negocio", cnc_business_options(), index=0, key="cnc_business")
    with cnc_cols[6]:
        st.caption("CNC = cliente de ruta sin compra del negocio durante el horizonte seleccionado.")

    with st.spinner("Preparando base historica CNC..."):
        cnc_sources, cnc_status = resolve_closed_month_sales_files(force_refresh=force_drive_refresh)
    cnc_history = ventas.copy()
    if cnc_sources:
        cnc_signature = tuple((str(path), path.stat().st_mtime, path.stat().st_size) for path in cnc_sources)
        cnc_historical = cached_load_historical_sales(
            tuple(str(path) for path in cnc_sources),
            str(dataset["sources"]["auxiliares"]),
            (
                cnc_signature,
                str(dataset["sources"]["auxiliares"]),
                Path(dataset["sources"]["auxiliares"]).stat().st_mtime,
            ),
        )
        cnc_history = pd.concat([cnc_historical, ventas], ignore_index=True).drop_duplicates()
    else:
        st.warning(f"No se encontro venta historica completa. Se calcula con la venta cargada actual. {cnc_status}")
    if not cnc_history.empty:
        history_min = pd.Timestamp(cnc_history["fecha"].min()).date()
        history_max = pd.Timestamp(cnc_history["fecha"].max()).date()
        st.caption(f"Histórico usado: {history_min} a {history_max} · {cnc_status}")

    cnc_end_ts = pd.Timestamp(cnc_end)
    cnc_start = cnc_horizon_start(cnc_end_ts, cnc_horizon)
    cnc_rutas_base = apply_supervisor_filter(rutas_grupo, cnc_supervisor)
    cnc_rutas_base = apply_promoter_filter(cnc_rutas_base, cnc_promoter)
    if cnc_business == "CZA":
        cnc_rutas_base = cnc_rutas_base[cnc_rutas_base["licencia_alcohol"].fillna("").str.upper().eq("SI")].copy()
    cnc_rutas_base, excluded_by_alta = filter_routes_active_at_horizon_start(cnc_rutas_base, cnc_start)
    cnc_filtered = filter_cnc_purchase_range(cnc_history, cnc_start, cnc_end_ts, cnc_business, cnc_rutas_base, cnc_route)
    cnc_filtered = apply_supervisor_filter(cnc_filtered, cnc_supervisor)
    cnc_filtered = apply_promoter_filter(cnc_filtered, cnc_promoter)
    cnc_base = non_buyer_clients(cnc_filtered, cnc_rutas_base, cnc_route)
    cnc_table = cnc_management_table(cnc_base, cnc_history, cnc_end_ts, cnc_horizon, cnc_business, cnc_rutas_base, cnc_route)

    st.subheader("Gestión de clientes no compradores")
    st.caption(f"Horizonte {cnc_horizon}: {cnc_start.date()} a {cnc_end_ts.date()} · Negocio {cnc_business}")
    if excluded_by_alta:
        st.caption(f"Excluidos por alta posterior al inicio del horizonte: {excluded_by_alta:,} clientes.")
    cnc_metric_cols = st.columns(5)
    route_total = route_customer_count(cnc_rutas_base, cnc_route)
    buyers_total = cnc_filtered[["vendedor", "cliente"]].drop_duplicates().shape[0]
    cnc_total = len(cnc_table)
    coverage = 1 if cnc_total else 0
    cnc_metric_cols[0].metric("Clientes ruta", f"{route_total:,}")
    cnc_metric_cols[1].metric("Compradores negocio", f"{buyers_total:,}")
    cnc_metric_cols[2].metric("CNC", f"{cnc_total:,}")
    cnc_metric_cols[3].metric("Nivel auditoría", "1" if coverage else "0")
    cnc_metric_cols[4].metric("Alcance objetivo", "100%" if coverage else "0%")

    if cnc_horizon == "U3M" and cnc_business in {"CZA", "NABS"}:
        st.info("Para U3M en CZA/NABS corresponde asignar tarea mensual en BEES Force/PDA y relevar motivo de no compra.")
    if cnc_horizon == "U12M":
        st.info("Para U12M corresponde frecuencia de contacto mensual 0.25; si hay oportunidad por Censo, frecuencia quincenal 0.50.")

    if not cnc_table.empty:
        st.subheader("Resumen por promotor")
        cnc_summary = (
            cnc_table.groupby(["supervisor", "promotor"], as_index=False)
            .agg(cnc=("cliente", "nunique"))
            .sort_values(["supervisor", "cnc", "promotor"], ascending=[True, False, True])
        )
        st.dataframe(
            cnc_summary.rename(columns={"supervisor": "Supervisor", "promotor": "Promotor", "cnc": "CNC"}),
            use_container_width=True,
            hide_index=True,
        )

    cnc_view = cnc_table.rename(
        columns={
            "grupo_ruta": "Grupo",
            "ruta": "Ruta",
            "supervisor": "Supervisor",
            "promotor": "Promotor",
            "vendedor": "Vnd.",
            "cliente": "Cliente",
            "razon_social": "Razón Social",
            "nombre_fantasia": "Nombre Fantasía",
            "alta_fecha": "Fecha Alta",
            "negocio": "Negocio",
            "horizonte": "Horizonte",
            "ultima_compra_negocio": "Última Compra Negocio",
            "dias_sin_compra": "Días Sin Compra",
            "accion_requerida": "Acción Requerida",
            "motivo_a_relevar": "Motivo a Relevar",
            "frecuencia_contacto": "Frecuencia Contacto",
            "nivel_auditoria": "Nivel Auditoría",
            "alcance_objetivo": "Alcance Objetivo",
            "responsable": "Responsable",
        }
    )
    if "Nombre Fantasía" in cnc_view.columns and "Razón Social" in cnc_view.columns:
        cnc_view["Nombre Fantasía"] = cnc_view["Nombre Fantasía"].fillna("")
        cnc_view["Nombre Fantasía"] = cnc_view["Nombre Fantasía"].where(
            cnc_view["Nombre Fantasía"].ne(""),
            cnc_view["Razón Social"],
        )
    if "Fecha Alta" in cnc_view.columns:
        fecha_alta = pd.to_datetime(cnc_view["Fecha Alta"], errors="coerce")
        cnc_view["Fecha Alta"] = fecha_alta.dt.date.astype(str).replace("NaT", "")
    display_cols = [
        "Grupo",
        "Ruta",
        "Supervisor",
        "Promotor",
        "Vnd.",
        "Cliente",
        "Razón Social",
        "Nombre Fantasía",
        "Fecha Alta",
        "Negocio",
        "Horizonte",
        "Última Compra Negocio",
        "Días Sin Compra",
        "Acción Requerida",
        "Motivo a Relevar",
        "Frecuencia Contacto",
        "Nivel Auditoría",
        "Alcance Objetivo",
        "Responsable",
    ]
    st.subheader("Base de gestión CNC")
    st.dataframe(cnc_view[[col for col in display_cols if col in cnc_view.columns]], use_container_width=True, hide_index=True)
    csv_data = cnc_view[[col for col in display_cols if col in cnc_view.columns]].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Descargar base CNC",
        data=csv_data,
        file_name=f"gestion_cnc_{cnc_business}_{cnc_horizon}_{cnc_end_ts.date()}.csv",
        mime="text/csv",
        use_container_width=True,
    )

with st.expander("Fuentes cargadas"):
    for label, path in dataset["sources"].items():
        st.write(f"{label}: `{path}`")
    combo_inventory = combo_promo_inventory(ventas)
    st.write(f"Combos/promos detectados: `{len(combo_inventory)}`")
    if not combo_inventory.empty:
        st.dataframe(combo_inventory, use_container_width=True, hide_index=True)
