from __future__ import annotations

import html
import io
import shutil
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

import app as sales_app


APP_TITLE = "Control de frescura"
DEFAULT_DRIVE_URL = "https://drive.google.com/drive/folders/1cukgXLUaPsEDK_yD7tSwgaBFZAbiDUot?usp=drive_link"
LOT_BLOCK_WIDTH = 6
LOCAL_FALLBACK_DIRS = [
    Path.home() / "Downloads",
    sales_app.PROJECT_ROOT / ".cloud_data" / "planificacion",
]


def clean_name(value: object) -> str:
    return sales_app.clean_name("" if pd.isna(value) else str(value))


def city_from_name(name: str) -> str:
    text = clean_name(name)
    if "madryn" in text:
        return "Madryn"
    if "trelew" in text:
        return "Trelew"
    return Path(name).stem.replace("plantillafrescura", "").strip(" -_").title() or "Sin ciudad"


def inject_style() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #101828;
            --muted: #475467;
            --blue: #155eef;
            --cyan: #06aed4;
            --green: #12b76a;
            --orange: #f79009;
            --red: #f04438;
            --line: #d0d5dd;
        }
        .stApp {
            background:
                radial-gradient(circle at top right, rgba(6,174,212,.18), transparent 28rem),
                linear-gradient(180deg, #f8fbff 0%, #eef4ff 100%);
            color: var(--ink);
        }
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #101828 0%, #12326f 100%);
        }
        section[data-testid="stSidebar"] * { color: #f8fafc !important; }
        div[data-testid="stAlert"] * { color: var(--ink) !important; font-weight: 750; }
        .hero {
            background: linear-gradient(135deg, #12326f 0%, #155eef 55%, #06aed4 100%);
            color: white;
            padding: 1.55rem 1.7rem;
            border-radius: 8px;
            box-shadow: 0 18px 45px rgba(21,94,239,.22);
            margin-bottom: 1.15rem;
        }
        .hero h1 { color: white; margin: 0; font-size: 2.1rem; }
        .hero p { color: white; margin: .65rem 0 0; font-weight: 650; }
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: .85rem;
            margin: .9rem 0 1.1rem;
        }
        .kpi-card {
            background: #fff;
            border: 1px solid rgba(16,24,40,.10);
            border-top: 5px solid var(--blue);
            border-radius: 8px;
            padding: 1rem;
            box-shadow: 0 14px 35px rgba(16,24,40,.10);
        }
        .kpi-card.red { border-top-color: var(--red); }
        .kpi-card.orange { border-top-color: var(--orange); }
        .kpi-card.green { border-top-color: var(--green); }
        .kpi-label {
            color: var(--muted);
            font-weight: 850;
            font-size: .78rem;
            letter-spacing: .04em;
            text-transform: uppercase;
        }
        .kpi-value {
            color: var(--ink);
            font-size: 2rem;
            font-weight: 950;
            margin-top: .25rem;
        }
        .kpi-sub { color: var(--muted); font-weight: 700; margin-top: .2rem; }
        .table-wrap {
            background: #fff;
            border: 1px solid rgba(16,24,40,.16);
            border-radius: 8px;
            padding: .85rem;
            box-shadow: 0 14px 35px rgba(16,24,40,.10);
            overflow-x: auto;
        }
        table.fresh-table {
            border-collapse: collapse;
            width: 100%;
            min-width: 1180px;
            font-size: .88rem;
        }
        .fresh-table th {
            background: #28549a;
            color: white;
            padding: .55rem;
            border: 1px solid #111827;
            text-align: center;
            white-space: nowrap;
        }
        .fresh-table td {
            color: var(--ink);
            padding: .48rem .55rem;
            border: 1px solid #111827;
            font-weight: 750;
            text-align: right;
        }
        .fresh-table td:nth-child(1),
        .fresh-table td:nth-child(2),
        .fresh-table td:nth-child(3),
        .fresh-table td:nth-child(12) { text-align: left; }
        .bad { background: #ffe4e8; color: #b42318 !important; }
        .warn { background: #fef3c7; color: #b54708 !important; }
        .ok { background: #dcfce7; color: #027a48 !important; }
        .mobile-lots { display: none; }
        .lot-card {
            background: #fff;
            border: 1px solid rgba(16,24,40,.14);
            border-left: 6px solid var(--green);
            border-radius: 8px;
            padding: .9rem;
            margin-bottom: .75rem;
            box-shadow: 0 10px 26px rgba(16,24,40,.10);
        }
        .lot-card.warn-card { border-left-color: var(--orange); }
        .lot-card.bad-card { border-left-color: var(--red); }
        .lot-top {
            display: flex;
            justify-content: space-between;
            gap: .7rem;
            align-items: flex-start;
        }
        .lot-title {
            color: var(--ink);
            font-size: 1rem;
            font-weight: 900;
            line-height: 1.2;
            margin-top: .2rem;
        }
        .lot-code {
            color: var(--muted);
            font-weight: 850;
            font-size: .8rem;
        }
        .lot-badge {
            border-radius: 999px;
            padding: .32rem .52rem;
            font-size: .76rem;
            font-weight: 900;
            white-space: nowrap;
        }
        .lot-meta {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: .55rem;
            margin-top: .8rem;
        }
        .lot-meta div {
            background: #f8fafc;
            border: 1px solid rgba(16,24,40,.08);
            border-radius: 8px;
            padding: .55rem;
        }
        .lot-meta span {
            display: block;
            color: var(--muted);
            font-size: .72rem;
            font-weight: 850;
            text-transform: uppercase;
        }
        .lot-meta strong {
            display: block;
            color: var(--ink);
            font-size: .98rem;
            margin-top: .18rem;
        }
        @media (max-width: 760px) {
            .block-container { padding-left: .7rem !important; padding-right: .7rem !important; }
            .hero { padding: 1rem; margin-bottom: .8rem; }
            .hero h1 { font-size: 1.45rem; }
            .hero p { font-size: .92rem; }
            .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .55rem; }
            .kpi-card { padding: .75rem; }
            .kpi-label { font-size: .65rem; }
            .kpi-value { font-size: 1.35rem; }
            .kpi-sub { font-size: .75rem; }
            .desktop-table { display: none; }
            .mobile-lots { display: block; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_num(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    amount = float(value)
    if abs(amount) >= 100:
        text = f"{amount:,.0f}"
    else:
        text = f"{amount:,.1f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def format_date(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return pd.Timestamp(value).strftime("%d/%m/%Y")


def escape_html(value: object) -> str:
    return html.escape("" if value is None or pd.isna(value) else str(value), quote=True)


def status_class(status: object, days_block: object) -> str:
    text = clean_name(status)
    days = pd.to_numeric(days_block, errors="coerce")
    if "eliminar" in text or "bloqueado" in text or (not pd.isna(days) and days <= 0):
        return "bad"
    if "accionar" in text or (not pd.isna(days) and days <= 30):
        return "warn"
    return "ok"


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
    tmp_path.unlink(missing_ok=True)
    try:
        import gdown

        gdown.download(id=item.id, output=str(tmp_path), quiet=True, use_cookies=False)
        if tmp_path.exists() and tmp_path.stat().st_size > 0:
            target_path.unlink(missing_ok=True)
            tmp_path.rename(target_path)
            return target_path
    except Exception:
        tmp_path.unlink(missing_ok=True)
    return target_path if target_path.exists() else None


def prepare_drive_sources(drive_url: str, force_refresh: bool = False) -> Path | None:
    target = sales_app.PROJECT_ROOT / ".cloud_data" / "frescura"
    if target.exists() and any(target.iterdir()) and not force_refresh:
        return target
    items = drive_folder_items(drive_url)
    if not items:
        return target if target.exists() and any(target.iterdir()) else None
    tmp_target = sales_app.PROJECT_ROOT / ".cloud_data" / f"frescura_tmp_{int(time.time())}"
    if tmp_target.exists():
        shutil.rmtree(tmp_target, ignore_errors=True)
    tmp_target.mkdir(parents=True, exist_ok=True)
    matches = [
        item
        for item in items
        if Path(str(item.path)).suffix.lower() in {".xlsx", ".xls"}
        and "plantillafrescura" in clean_name(Path(str(item.path)).stem)
    ]
    downloaded = [download_drive_item(item, tmp_target) for item in matches]
    if not any(path is not None for path in downloaded):
        shutil.rmtree(tmp_target, ignore_errors=True)
        return target if target.exists() and any(target.iterdir()) else None
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    tmp_target.rename(target)
    return target


def local_template_files() -> list[Path]:
    files: list[Path] = []
    for folder in LOCAL_FALLBACK_DIRS:
        if not folder.exists():
            continue
        files.extend(
            path
            for path in folder.iterdir()
            if path.is_file()
            and path.suffix.lower() in {".xlsx", ".xls"}
            and "plantillafrescura" in clean_name(path.stem)
        )
    unique = {str(path.resolve()).lower(): path for path in files}
    return sorted(unique.values(), key=lambda path: path.stat().st_mtime, reverse=True)


def template_files(folder: Path | None) -> list[Path]:
    files: list[Path] = []
    if folder is not None and folder.exists():
        files.extend(
            path
            for path in folder.iterdir()
            if path.is_file()
            and path.suffix.lower() in {".xlsx", ".xls"}
            and "plantillafrescura" in clean_name(path.stem)
        )
    if not files:
        files = local_template_files()
    return sorted(files, key=lambda path: path.name.lower())


def find_header_row(raw: pd.DataFrame) -> int | None:
    for idx, row in raw.iterrows():
        values = [clean_name(value) for value in row.tolist()]
        if any(value in {"cod", "codigo"} for value in values) and any("descripcion" == value for value in values):
            return int(idx)
    return None


def read_freshness_file(path: Path | None = None, uploaded=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    name = uploaded.name if uploaded is not None else path.name if path is not None else ""
    city = city_from_name(name)
    content = io.BytesIO(uploaded.getvalue()) if uploaded is not None else path
    raw = pd.read_excel(content, sheet_name=0, header=None)
    header_row = find_header_row(raw)
    if header_row is None:
        raise ValueError(f"No encontre encabezado Cod / Descripcion en {name}.")

    header = [str(value).strip() if not pd.isna(value) else "" for value in raw.iloc[header_row].tolist()]
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = range(data.shape[1])
    data = data[data[0].notna()].copy()

    products = pd.DataFrame(
        {
            "ciudad": city,
            "codigo": pd.to_numeric(data[0], errors="coerce").astype("Int64").astype("string"),
            "descripcion": data[1].fillna("").astype(str).str.strip(),
            "politica_stock_dias": pd.to_numeric(data[2], errors="coerce"),
            "bultos_pallet": pd.to_numeric(data[3], errors="coerce"),
            "bultos_piso": pd.to_numeric(data[4], errors="coerce"),
            "stock_total": pd.to_numeric(data[5], errors="coerce"),
            "venta_promedio": pd.to_numeric(data[6], errors="coerce"),
            "dias_stock": pd.to_numeric(data[9], errors="coerce"),
            "archivo": name,
        }
    )
    products = products[products["codigo"].notna()].copy()

    lot_rows = []
    lot_starts = [idx for idx, value in enumerate(header) if clean_name(value) == "stock_lote"]
    for lot_number, start in enumerate(lot_starts, start=1):
        if start + LOT_BLOCK_WIDTH - 1 >= data.shape[1]:
            continue
        lot = pd.DataFrame(
            {
                "ciudad": city,
                "codigo": pd.to_numeric(data[0], errors="coerce").astype("Int64").astype("string"),
                "descripcion": data[1].fillna("").astype(str).str.strip(),
                "lote_nro": lot_number,
                "stock_lote": pd.to_numeric(data[start], errors="coerce"),
                "fecha_vencimiento": pd.to_datetime(data[start + 1], errors="coerce"),
                "dias_bloqueo": pd.to_numeric(data[start + 2], errors="coerce"),
                "dias_vta_bloqueo": pd.to_numeric(data[start + 3], errors="coerce"),
                "dias_stock_lote": pd.to_numeric(data[start + 4], errors="coerce"),
                "estado": data[start + 5].fillna("").astype(str).str.strip(),
                "archivo": name,
            }
        )
        lot = lot[lot["codigo"].notna() & (lot["stock_lote"].fillna(0) > 0)].copy()
        lot_rows.append(lot)

    lots = pd.concat(lot_rows, ignore_index=True) if lot_rows else pd.DataFrame()
    return products, lots


def load_sources(files: list[Path], uploaded_files) -> tuple[pd.DataFrame, pd.DataFrame]:
    product_frames = []
    lot_frames = []
    for uploaded in uploaded_files or []:
        products, lots = read_freshness_file(uploaded=uploaded)
        product_frames.append(products)
        lot_frames.append(lots)
    if not uploaded_files:
        for path in files:
            products, lots = read_freshness_file(path=path)
            product_frames.append(products)
            lot_frames.append(lots)
    products = pd.concat(product_frames, ignore_index=True) if product_frames else pd.DataFrame()
    lots = pd.concat(lot_frames, ignore_index=True) if lot_frames else pd.DataFrame()
    return products, lots


def apply_filters(products: pd.DataFrame, lots: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    st.sidebar.markdown("### Filtros")
    cities = sorted(products["ciudad"].dropna().unique().tolist()) if not products.empty else []
    selected_cities = st.sidebar.multiselect("Ciudad", cities, default=cities)
    search = st.sidebar.text_input("Buscar codigo o producto", value="", placeholder="Ej: 2218 o Quilmes")
    status_options = ["Todos", "ACCIONAR", "OK", "ELIMINAR/BLOQUEADO"]
    selected_status = st.sidebar.selectbox("Estado lote", status_options)

    product_view = products[products["ciudad"].isin(selected_cities)].copy()
    lot_view = lots[lots["ciudad"].isin(selected_cities)].copy()
    if search.strip():
        terms = [clean_name(term) for term in search.replace(";", " ").replace(",", " ").split() if term.strip()]
        if terms:
            product_text = (
                product_view["codigo"].fillna("").astype(str) + " " + product_view["descripcion"].fillna("").astype(str).map(clean_name)
            )
            lot_text = lot_view["codigo"].fillna("").astype(str) + " " + lot_view["descripcion"].fillna("").astype(str).map(clean_name)
            product_view = product_view[product_text.apply(lambda value: all(term in value for term in terms))]
            lot_view = lot_view[lot_text.apply(lambda value: all(term in value for term in terms))]
    if selected_status == "ACCIONAR":
        lot_view = lot_view[lot_view["estado"].map(clean_name).str.contains("accionar", na=False)]
    elif selected_status == "OK":
        lot_view = lot_view[lot_view["estado"].map(clean_name).eq("ok")]
    elif selected_status == "ELIMINAR/BLOQUEADO":
        state = lot_view["estado"].map(clean_name)
        lot_view = lot_view[state.str.contains("eliminar|bloqueado", na=False) | lot_view["dias_bloqueo"].fillna(99999).le(0)]
    return product_view, lot_view


def render_kpis(products: pd.DataFrame, lots: pd.DataFrame) -> None:
    accion = lots["estado"].map(clean_name).str.contains("accionar", na=False).sum() if not lots.empty else 0
    blocked = (
        lots["estado"].map(clean_name).str.contains("eliminar|bloqueado", na=False).sum()
        + lots["dias_bloqueo"].fillna(99999).le(0).sum()
        if not lots.empty
        else 0
    )
    next_expiry = lots["fecha_vencimiento"].min() if not lots.empty else pd.NaT
    cards = [
        ("Productos", format_num(products["codigo"].nunique() if not products.empty else 0), "codigos filtrados", ""),
        ("Stock total", format_num(products["stock_total"].sum() if not products.empty else 0), "bultos filtrados", "green"),
        ("Lotes a accionar", format_num(accion), "requieren seguimiento", "orange"),
        ("Proximo vencimiento", format_date(next_expiry), f"bloqueados/eliminar: {blocked}", "red"),
    ]
    html = "<div class='kpi-grid'>"
    for label, value, sub, klass in cards:
        html += f"<div class='kpi-card {klass}'><div class='kpi-label'>{label}</div><div class='kpi-value'>{value}</div><div class='kpi-sub'>{sub}</div></div>"
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_lot_table(lots: pd.DataFrame) -> None:
    if lots.empty:
        st.info("No hay lotes para los filtros seleccionados.")
        return
    table = lots.sort_values(["fecha_vencimiento", "ciudad", "descripcion"]).copy()
    rows = []
    cards = []
    for _, row in table.iterrows():
        klass = status_class(row["estado"], row["dias_bloqueo"])
        card_class = "bad-card" if klass == "bad" else "warn-card" if klass == "warn" else ""
        status_text = row["estado"] or "-"
        city = escape_html(row["ciudad"])
        code = escape_html(row["codigo"])
        description = escape_html(row["descripcion"])
        status_display = escape_html(status_text)
        file_name = escape_html(row["archivo"])
        rows.append(
            "<tr>"
            f"<td>{city}</td>"
            f"<td>{code}</td>"
            f"<td>{description}</td>"
            f"<td>{int(row['lote_nro'])}</td>"
            f"<td>{format_num(row['stock_lote'])}</td>"
            f"<td>{format_date(row['fecha_vencimiento'])}</td>"
            f"<td class='{klass}'>{format_num(row['dias_bloqueo'])}</td>"
            f"<td>{format_num(row['dias_vta_bloqueo'])}</td>"
            f"<td>{format_num(row['dias_stock_lote'])}</td>"
            f"<td class='{klass}'>{status_display}</td>"
            f"<td>{file_name}</td>"
            "</tr>"
        )
        cards.append(
            f"<div class='lot-card {card_class}'>"
            "<div class='lot-top'>"
            "<div>"
            f"<div class='lot-code'>{city} - Cod {code} - Lote {int(row['lote_nro'])}</div>"
            f"<div class='lot-title'>{description}</div>"
            "</div>"
            f"<div class='lot-badge {klass}'>{status_display}</div>"
            "</div>"
            "<div class='lot-meta'>"
            f"<div><span>Vence</span><strong>{format_date(row['fecha_vencimiento'])}</strong></div>"
            f"<div><span>Stock lote</span><strong>{format_num(row['stock_lote'])}</strong></div>"
            f"<div><span>Dias bloqueo</span><strong>{format_num(row['dias_bloqueo'])}</strong></div>"
            f"<div><span>Dias stock</span><strong>{format_num(row['dias_stock_lote'])}</strong></div>"
            "</div>"
            "</div>"
        )
    html_body = (
        "<div class='mobile-lots'>"
        + "".join(cards)
        + "</div>"
        + "<div class='table-wrap desktop-table'>"
        + "<table class='fresh-table'>"
        + "<thead><tr>"
        + "<th>Ciudad</th><th>Codigo</th><th>Producto</th><th>Lote</th>"
        + "<th>Stock lote</th><th>Fecha venc.</th><th>Dias p/bloqueo</th>"
        + "<th>Dias vta p/bloqueo</th><th>Dias stock lote</th><th>Estado</th><th>Archivo</th>"
        + "</tr></thead>"
        + f"<tbody>{''.join(rows)}</tbody>"
        + "</table></div>"
    )
    st.markdown(html_body, unsafe_allow_html=True)


def export_excel(products: pd.DataFrame, lots: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    product_export = products.rename(
        columns={
            "ciudad": "Ciudad",
            "codigo": "Codigo",
            "descripcion": "Producto",
            "politica_stock_dias": "Politica stock dias",
            "bultos_pallet": "Bultos pallet",
            "bultos_piso": "Bultos piso",
            "stock_total": "Stock total",
            "venta_promedio": "Venta promedio",
            "dias_stock": "Dias stock",
            "archivo": "Archivo",
        }
    )
    lot_export = lots.rename(
        columns={
            "ciudad": "Ciudad",
            "codigo": "Codigo",
            "descripcion": "Producto",
            "lote_nro": "Lote nro",
            "stock_lote": "Stock lote",
            "fecha_vencimiento": "Fecha vencimiento",
            "dias_bloqueo": "Dias p/bloqueo",
            "dias_vta_bloqueo": "Dias vta p/bloqueo",
            "dias_stock_lote": "Dias stock lote",
            "estado": "Estado",
            "archivo": "Archivo",
        }
    )
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        product_export.to_excel(writer, sheet_name="Productos", index=False)
        lot_export.to_excel(writer, sheet_name="Lotes", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            for cell in sheet[1]:
                cell.font = cell.font.copy(bold=True, color="FFFFFF")
                cell.fill = cell.fill.copy(fill_type="solid", fgColor="28549A")
            for column_cells in sheet.columns:
                max_length = max(len(str(cell.value or "")) for cell in column_cells)
                sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 10), 42)
    buffer.seek(0)
    return buffer.getvalue()


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon=":calendar:", layout="wide")
    inject_style()
    st.markdown(
        """
        <div class="hero">
            <h1>Control de frescura</h1>
            <p>Productos por ciudad, fecha de vencimiento y estado de accion.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.header("Datos")
    if "frescura_refresh" not in st.session_state:
        st.session_state["frescura_refresh"] = 0.0
    drive_url = sales_app.secret_or_env("GOOGLE_DRIVE_PLANIFICACION_URL", DEFAULT_DRIVE_URL)
    if st.sidebar.button("Actualizar datos", width="stretch"):
        st.session_state["frescura_refresh"] = time.time()
        st.cache_data.clear()

    folder = prepare_drive_sources(drive_url, force_refresh=bool(st.session_state["frescura_refresh"]))
    files = template_files(folder)
    st.sidebar.caption(f"Carpeta usada: {folder if folder else 'Downloads/local'}")
    if files:
        st.sidebar.success("Archivos: " + ", ".join(path.name for path in files))

    uploaded = st.sidebar.file_uploader(
        "Carga manual si falla Drive",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
    )

    try:
        products, lots = load_sources(files, uploaded)
    except Exception as exc:
        st.error(f"No pude leer las plantillas de frescura: {exc}")
        return
    if products.empty:
        st.warning("No encontre plantillas de frescura. Subilas al Drive o cargalas manualmente.")
        return

    product_view, lot_view = apply_filters(products, lots)
    render_kpis(product_view, lot_view)

    st.subheader("Lotes por vencimiento")
    render_lot_table(lot_view)

    st.download_button(
        "Exportar Excel",
        data=export_excel(product_view, lot_view),
        file_name="control_frescura.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        st.error(f"Error controlado en {APP_TITLE}: {type(exc).__name__}: {exc}")
        st.code(traceback.format_exc())
