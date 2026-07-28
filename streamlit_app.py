import json
from pathlib import Path

import pandas as pd
import streamlit as st

from edf_importer import DRIVE_URL, import_data


ROOT = Path(__file__).parent
DATA_PATH = ROOT / "data" / "db.json"


st.set_page_config(page_title="EDF Repago", page_icon="EDF", layout="wide")


def load_db_from_disk():
    if not DATA_PATH.exists():
        return None
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def load_db_from_upload(uploaded_file):
    if uploaded_file is None:
        return None
    return json.loads(uploaded_file.getvalue().decode("utf-8"))


def band_label(pct, hl):
    if hl <= 0:
        return "Venta 0"
    if pct < 25:
        return "0%-25%"
    if pct < 50:
        return "25%-50%"
    if pct < 75:
        return "50%-75%"
    if pct < 100:
        return "75%-99%"
    return "100%+"


def get_repayment(edf):
    repayment = edf.get("repayment") or {}
    return {
        "hl": repayment.get("hl") or 0,
        "pct": repayment.get("pct") or 0,
        "target": repayment.get("target") or 0,
        "minimum": repayment.get("minimum") or 0,
        "band": (repayment.get("band") or {}).get("label") or "",
    }


def available_periods(db):
    periods = set()
    for customer in db.get("customers", []):
        monthly = customer.get("monthlySalesByBusiness") or {}
        for business_data in monthly.values():
            periods.update((business_data or {}).keys())
    return sorted(periods)


def selected_periods(db, period_mode):
    periods = available_periods(db)
    if not periods:
        return []
    if period_mode == "Total cargado":
        return periods
    if period_mode == "Mes corriente":
        return [periods[-1]]
    return periods[-3:]


def business_hl_for_period(customer, business, periods, average=False):
    monthly = customer.get("monthlySalesByBusiness") or {}
    values = monthly.get(business) or {}
    total = sum(float(values.get(period, 0) or 0) for period in periods)
    if average and periods:
        return round(total / len(periods), 3)
    return round(total, 3)


def repayment_for_values(hl, target):
    pct = round((hl / target) * 100) if target else 0
    return {
        "hl": round(hl, 3),
        "pct": pct,
        "target": target,
        "minimum": round(target * 0.75, 3),
        "band": band_label(pct, hl),
    }


def period_repayment_map(db, periods, average):
    edfs = db.get("edfs", [])
    customers = {str(customer.get("id")): customer for customer in db.get("customers", [])}
    repayment = {}
    grouped = {}
    for edf in edfs:
        if edf.get("status") != "PDV" or not edf.get("customerId"):
            continue
        key = (str(edf.get("customerId")), edf.get("business") or "OTROS")
        grouped.setdefault(key, []).append(edf)

    for group in grouped.values():
        group.sort(key=lambda item: (item.get("asset") or "", item.get("serial") or ""))

    for (customer_id, business), group in grouped.items():
        customer = customers.get(customer_id) or {}
        available_hl = business_hl_for_period(customer, business, periods, average=average)
        for edf in group:
            base = get_repayment(edf)
            target = base["target"] or 1.6
            assigned = min(available_hl, target)
            available_hl = max(0, round(available_hl - assigned, 3))
            repayment[edf.get("id")] = repayment_for_values(assigned, target)
    return repayment


def status_label(status):
    labels = {
        "PDV": "En PDV",
        "DEPOSITO": "Deposito",
        "STOCK": "Stock",
        "REPARACION": "Reparacion",
        "BAJA DEFINITIVA": "Baja definitiva",
    }
    return labels.get(status or "", status or "-")


def build_edf_rows(db, period_mode="Total cargado"):
    periods = selected_periods(db, period_mode)
    use_period = period_mode != "Total cargado"
    period_map = period_repayment_map(db, periods, average=period_mode == "Trimestre promedio") if use_period else {}
    rows = []
    for edf in db.get("edfs", []):
        customer = edf.get("customer") or {}
        repayment = period_map.get(edf.get("id"), get_repayment(edf))
        rows.append({
            "Cliente": customer.get("name") or "",
            "Nombre fantasia": customer.get("fantasyName") or customer.get("name") or "",
            "Razon social": customer.get("legalName") or "",
            "Codigo cliente": customer.get("id") or edf.get("customerId") or "",
            "Negocio": edf.get("business") or "OTROS",
            "Supervisor": customer.get("supervisor") or "Sin supervisor",
            "Promotor": customer.get("promoter") or customer.get("seller") or "Sin promotor",
            "Ruta": customer.get("route") or "",
            "Activo": edf.get("asset") or "",
            "Serie": edf.get("serial") or "",
            "Modelo": edf.get("model") or "",
            "Estado": status_label(edf.get("status")),
            "Deposito": edf.get("deposit") or "",
            "HL": repayment["hl"],
            "Objetivo": repayment["target"],
            "Minimo": repayment["minimum"],
            "% Repago": repayment["pct"],
            "Banda": repayment["band"],
            "Periodo": period_mode,
            "Meses usados": ", ".join(periods) if periods else "Sin ventas",
        })
    return pd.DataFrame(rows)


def build_customer_rows(db):
    rows = []
    for customer in db.get("customers", []):
        sales = customer.get("salesByBusiness") or {}
        rows.append({
            "Codigo": customer.get("id") or "",
            "Cliente": customer.get("name") or "",
            "Nombre fantasia": customer.get("fantasyName") or customer.get("name") or "",
            "Razon social": customer.get("legalName") or "",
            "Direccion": customer.get("address") or "",
            "Localidad": customer.get("city") or "",
            "Ruta": customer.get("route") or "",
            "Promotor": customer.get("promoter") or customer.get("seller") or "Sin promotor",
            "Supervisor": customer.get("supervisor") or "Sin supervisor",
            "PI": "Si" if customer.get("pi") else "No",
            "PI tipos": ", ".join(customer.get("piTypes") or []),
            "HL CZA": sales.get("CZA") or 0,
            "HL UNG": sales.get("UNG") or 0,
            "HL AGUAS": sales.get("AGUAS") or 0,
            "HL RB": sales.get("RB") or 0,
        })
    return pd.DataFrame(rows)


def csv_download(df):
    return df.to_csv(index=False, sep=";").encode("utf-8-sig")


def render_filters(df):
    f1, f2, f3, f4, f5 = st.columns(5)
    business = f1.selectbox("Negocio", ["Todos"] + sorted(df["Negocio"].dropna().unique().tolist()))
    supervisor = f2.selectbox("Supervisor", ["Todos"] + sorted(df["Supervisor"].dropna().unique().tolist()))
    promoter = f3.selectbox("Promotor", ["Todos"] + sorted(df["Promotor"].dropna().unique().tolist()))
    search_by = f4.selectbox("Buscar por", ["Todo", "Codigo cliente", "Cliente", "Activo", "Serie"])
    query = f5.text_input("Buscar")

    filtered = df.copy()
    if business != "Todos":
        filtered = filtered[filtered["Negocio"] == business]
    if supervisor != "Todos":
        filtered = filtered[filtered["Supervisor"] == supervisor]
    if promoter != "Todos":
        filtered = filtered[filtered["Promotor"] == promoter]
    if query:
        q = query.lower()
        if search_by == "Codigo cliente":
            normalized = filtered["Codigo cliente"].astype(str).str.replace(r"\.0$", "", regex=True).str.lower()
            filtered = filtered[normalized.str.startswith(q, na=False) | normalized.eq(q)]
        elif search_by == "Cliente":
            filtered = filtered[filtered["Cliente"].astype(str).str.lower().str.contains(q, na=False)]
        elif search_by == "Activo":
            filtered = filtered[filtered["Activo"].astype(str).str.lower().str.contains(q, na=False)]
        elif search_by == "Serie":
            filtered = filtered[filtered["Serie"].astype(str).str.lower().str.contains(q, na=False)]
        else:
            full_match = filtered.apply(lambda row: q in " ".join(map(str, row.values)).lower(), axis=1)
            filtered = filtered[full_match]
    return filtered


st.title("EDF Repago")
st.caption("Dashboard operativo by QπU")

with st.sidebar:
    st.header("Datos")
    uploaded = st.file_uploader("Subir db.json", type=["json"])
    st.caption("Tambien puede existir como data/db.json dentro del repo.")
    st.divider()
    st.header("Google Drive")
    drive_url = st.text_input("Carpeta Drive", value=DRIVE_URL)
    if st.button("Sincronizar Drive e importar"):
        try:
            with st.spinner("Leyendo Drive y generando base..."):
                db = import_data(sync=True, folder_url=drive_url)
            st.success("Base actualizada desde Drive.")
            st.rerun()
        except Exception as exc:
            st.error("No se pudo importar desde Drive.")
            st.exception(exc)

db = load_db_from_upload(uploaded) or load_db_from_disk()

if db is None:
    st.warning("Falta cargar la base del dashboard.")
    st.write("Subi el archivo `db.json` desde la barra lateral, o agregalo al repo en `data/db.json`.")
    st.stop()

period_mode = st.selectbox("Periodo de repago", ["Total cargado", "Trimestre promedio", "Mes corriente"])
edf_df = build_edf_rows(db, period_mode)
customer_df = build_customer_rows(db)

placed = edf_df[edf_df["Estado"] == "En PDV"] if not edf_df.empty else edf_df
available = edf_df[edf_df["Estado"].isin(["Stock", "Deposito"])] if not edf_df.empty else edf_df
under_75 = placed[placed["% Repago"] < 75] if not placed.empty else placed

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total EDF", len(edf_df))
c2.metric("Disponibles", len(available))
c3.metric("En PDV", len(placed))
c4.metric("Bajo 75%", len(under_75))

tab_repago, tab_clientes, tab_rankings = st.tabs(["Repago", "Clientes", "Rankings"])

with tab_repago:
    st.subheader("Listado de repago")
    filtered = render_filters(edf_df)
    st.dataframe(filtered, width="stretch", hide_index=True)
    st.download_button("Exportar listado CSV", csv_download(filtered), "repago_edf.csv", "text/csv")

with tab_clientes:
    st.subheader("Clientes")
    query = st.text_input("Buscar cliente o codigo", key="customer_query")
    filtered_customers = customer_df.copy()
    if query:
        q = query.lower()
        filtered_customers = filtered_customers[filtered_customers.apply(lambda row: q in " ".join(map(str, row.values)).lower(), axis=1)]
    st.dataframe(filtered_customers, width="stretch", hide_index=True)
    st.download_button("Exportar clientes CSV", csv_download(filtered_customers), "clientes_edf.csv", "text/csv")

with tab_rankings:
    st.subheader("Peores clientes por repago")
    if not placed.empty:
        ranking = (
            placed.groupby(["Codigo cliente", "Cliente", "Negocio", "Supervisor", "Promotor"], as_index=False)
            .agg(EDF=("Activo", "count"), RepagoPromedio=("% Repago", "mean"), HL=("HL", "sum"))
            .sort_values(["RepagoPromedio", "EDF"], ascending=[True, False])
            .head(50)
        )
        st.dataframe(ranking, width="stretch", hide_index=True)
        st.bar_chart(ranking.set_index("Cliente")["RepagoPromedio"].head(15))
    else:
        st.info("No hay EDF en PDV para rankear.")
