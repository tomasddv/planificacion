from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import shutil
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard_data import (
    DAY_COLS,
    DAY_GROUPS,
    EXCLUDED_VENDORS,
    KPI_FOCUSES,
    filter_sales_by_focus,
    filter_sales_by_focus_range,
    focus_sales,
    load_auxiliares,
    load_dataset,
    load_ventas,
    summarize,
    trend_by_focus,
)


DEFAULT_DATA_DIR = r"C:\Users\triesgo\Desktop\CCC"
DEFAULT_DRIVE_URL = "https://drive.google.com/drive/folders/1cukgXLUaPsEDK_yD7tSwgaBFZAbiDUot?usp=drive_link"
DEFAULT_DRIVE_FILE_IDS = {
    "20260519122321plantillaClientesAR.xlsx": "1GuRrGKlb7SLjI9h81XssZTpWzgPUrpRb",
    "AUXILIARES.xlsx": "1zXhbWtT7K1tY43MmYz7oTTYifMgmLyFT",
    "RUTAS 7-26.xlsx": "12REZlhQOVsQVIEIAKJ6mFSsrtNCSK7s8",
    "VENTA DIARIA.txt": "1nMCKcAXe7n_ROsJtbtgSuqik5pR4VdCW",
}
DEFAULT_ANNUAL_SALES_FILE_ID = "16-AIn2Sp0TODYXKXaM2duX2pEw4TRPAV"
DEFAULT_MONTHLY_CLOSED_FILE_IDS = {
    "VENTA JUNIO 2026.txt": "1t3Qck9PMkvq4qp6XNynVUAGV1REP8NqD",
}
PROJECT_ROOT = Path(__file__).resolve().parent
PLAN_FILE = Path("planificacion_promotores.csv")
PLANIFICADOR_PROMOTORES_URL = "https://planificacion-ifeevprb7is4zwjk6k5suo.streamlit.app/"

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


def is_drive_url(value: str):
    value = str(value or "").strip().lower()
    return value.startswith("http://") or value.startswith("https://")


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
        normalized = name.upper().replace("_", " ").replace("-", " ")
        compact = normalized.replace(" ", "")
        return (
            "RUTAS" in normalized
            or "AUXILIARES" in normalized
            or ("VENTA" in normalized and "DIARIA" in compact and "ANUAL" not in normalized)
            or "PLANTILLACLIENTESAR" in compact
        )

    try:
        if drive_url.strip().rstrip("/") == DEFAULT_DRIVE_URL.rstrip("/"):
            def download_default_file(item):
                local_name, file_id = item
                gdown.download(id=file_id, output=str(tmp / local_name), quiet=True, use_cookies=False)
                return local_name

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(download_default_file, item) for item in DEFAULT_DRIVE_FILE_IDS.items()]
                for future in as_completed(futures):
                    future.result()
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
    if not PLAN_FILE.exists():
        return pd.DataFrame(columns=["fecha", "ruta", "kpi", "promotor", "planificado"])
    plan = pd.read_csv(PLAN_FILE, dtype={"fecha": str, "kpi": str, "promotor": str})
    if "ruta" not in plan.columns:
        plan["ruta"] = "Todas"
    if "planificado" not in plan.columns:
        plan["planificado"] = 0
    plan["planificado"] = pd.to_numeric(plan["planificado"], errors="coerce").fillna(0)
    return plan[["fecha", "ruta", "kpi", "promotor", "planificado"]]


def save_plan(plan: pd.DataFrame):
    clean = plan.copy()
    clean["planificado"] = pd.to_numeric(clean["planificado"], errors="coerce").fillna(0)
    clean.to_csv(PLAN_FILE, index=False)


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
        tmp["cliente_sku"] = tmp["cliente"] + "|" + tmp["producto"]
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
        route_keys = route_scope[["vendedor", "cliente"]].drop_duplicates()
        filtered = filtered.merge(route_keys, on=["vendedor", "cliente"], how="inner")
    return filtered


def apply_promoter_filter(df: pd.DataFrame, promoter: str):
    if promoter == "Todos" or df.empty or "promotor" not in df.columns:
        return df
    return df[df["promotor"].eq(promoter)].copy()


def apply_supervisor_filter(df: pd.DataFrame, supervisor: str):
    if supervisor == "Todos" or df.empty or "supervisor" not in df.columns:
        return df
    return df[df["supervisor"].eq(supervisor)].copy()


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
    ["Acumulado mensual", "Planificación diaria", "No compradores"],
    horizontal=True,
    label_visibility="collapsed",
    key="main_view",
)

if view == "Acumulado mensual":
    month_end = pd.Timestamp(max(fechas))
    month_start = month_end.replace(day=1)
    supervisor_options = ["Todos"] + sorted(promotores["supervisor"].dropna().unique())
    month_cols = st.columns([1.1, 1.3, 1.4, 1.6, 1.8])
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
        st.caption(f"Mes acumulado {month_start.date()} a {month_end.date()} · TBD = SKUs vendidos por cliente.")

    month_focus, month_metric = parse_kpi_option(month_option)
    month_rutas_base = apply_supervisor_filter(rutas_grupo, month_supervisor)
    month_rutas_base = apply_promoter_filter(month_rutas_base, month_promoter)
    month_promotores = apply_supervisor_filter(promotores, month_supervisor)
    month_promotores = apply_promoter_filter(month_promotores, month_promoter)
    month_filtered = filter_sales_by_focus_range(ventas, month_start, month_end, month_focus, month_rutas_base, month_route)
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
    filtered_1 = filter_sales_by_focus_range(ventas, real_date, real_date, focus_1, day_rutas_base, route)
    filtered_1 = apply_promoter_filter(filtered_1, day_promoter)
    summary_1 = summarize(filtered_1, day_rutas_base, day_promotores, real_date, route)
    filtered_1_accum = filter_sales_by_focus_range(ventas, accumulated_start, real_date, focus_1, day_rutas_base, route)
    filtered_1_accum = apply_promoter_filter(filtered_1_accum, day_promoter)
    summary_1_accum = summarize(filtered_1_accum, day_rutas_base, day_promotores, real_date, route)
    summary_1 = apply_accumulated_remaining(summary_1, summary_1_accum)
    filtered_2 = filter_sales_by_focus_range(ventas, real_date, real_date, focus_2, day_rutas_base, route)
    filtered_2 = apply_promoter_filter(filtered_2, day_promoter)
    summary_2 = summarize(filtered_2, day_rutas_base, day_promotores, real_date, route)
    filtered_2_accum = filter_sales_by_focus_range(ventas, accumulated_start, real_date, focus_2, day_rutas_base, route)
    filtered_2_accum = apply_promoter_filter(filtered_2_accum, day_promoter)
    summary_2_accum = summarize(filtered_2_accum, day_rutas_base, day_promotores, real_date, route)
    summary_2 = apply_accumulated_remaining(summary_2, summary_2_accum)
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
        st.toast("Planificacion de tarjeta 1 guardada.")
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
        st.toast("Planificacion de tarjeta 2 guardada.")
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
    nb_cols = st.columns([1.35, 1.35, 1.05, 1.25, 1.35, 1.5, 1.5])
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
                historical_sources, annual_status = resolve_closed_month_sales_files(force_refresh=False)
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
        nb_option = st.selectbox("Foco", options, index=0, key="nb_focus")
    with nb_cols[6]:
        st.caption("Lista clientes de la ruta que no compraron el foco en el período seleccionado.")

    nb_sales_source = ventas
    if nb_period_type == "Mes acumulado actual":
        nb_end = pd.Timestamp(max(fechas))
        nb_start = nb_end.replace(day=1)
        nb_label = f"Mes acumulado {nb_start.date()} a {nb_end.date()}"
    elif nb_period_type == "Mes cerrado histórico":
        nb_sales_source = annual_ventas
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
    if nb_period_type == "Mes cerrado histórico":
        nb_filtered = filter_sales_by_focus_purchase_range(nb_sales_source, nb_start, nb_end, nb_focus, nb_rutas_base, nb_route)
    else:
        nb_filtered = filter_sales_by_focus_range(nb_sales_source, nb_start, nb_end, nb_focus, nb_rutas_base, nb_route)
    nb_filtered = apply_supervisor_filter(nb_filtered, nb_supervisor)
    nb_filtered = apply_promoter_filter(nb_filtered, nb_promoter)
    nb_table = non_buyer_clients(nb_filtered, nb_rutas_base, nb_route)

    st.subheader("Clientes no compradores")
    st.caption(nb_label)
    metric_cols = st.columns(3)
    metric_cols[0].metric("Clientes en ruta", f"{route_customer_count(nb_rutas_base, nb_route):,}")
    metric_cols[1].metric("Compradores foco", f"{nb_filtered[['vendedor', 'cliente']].drop_duplicates().shape[0]:,}")
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
    st.dataframe(nb_view, use_container_width=True, hide_index=True)

with st.expander("Fuentes cargadas"):
    for label, path in dataset["sources"].items():
        st.write(f"{label}: `{path}`")
