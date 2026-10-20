"""Seguimiento mensual: ventas netas, padrón de grupo y ruta comercial."""
from pathlib import Path
import re
import unicodedata

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
INVALID_ROUTES = {"", "0", "999", "9999"}


def key(value):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower())


def code(values):
    return values.fillna("").astype(str).str.strip().str.replace(r"\.0$", "", regex=True).str.lstrip("0").replace("", "0")


def number(values):
    return pd.to_numeric(values.astype(str).str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")


def prepare_sales(raw, parse_dates):
    """Read original export; do not discard Sundays or infer units from HL."""
    required = ["Cod. Cliente", "Código", "Descripción Período", "Pr Neto", "Importes Netos"]
    missing = set(required) - set(raw.columns)
    if missing:
        raise ValueError(f"Faltan columnas en ventadiaria: {sorted(missing)}")
    result = pd.DataFrame({
        "cliente": code(raw["Cod. Cliente"]), "sku": code(raw["Código"]),
        "fecha": parse_dates(raw["Descripción Período"]),
        "importe": number(raw["Importes Netos"]), "precio": number(raw["Pr Neto"]),
    })
    catalog = pd.read_csv(ROOT / "combos_catalogo.csv", dtype=str)
    result = result.merge(catalog, on="sku", how="inner", validate="many_to_one")
    invalid = result["fecha"].isna() | result["importe"].isna() | result["precio"].isna() | result["precio"].eq(0)
    if invalid.any():
        raise ValueError(f"{invalid.sum()} movimientos de combos sin fecha, importe o precio válido. Revisar la fuente.")
    result["unidades"] = result["importe"] / result["precio"]
    # Exported amounts have two decimals: tolerate monetary rounding at integer units.
    rounded = result["unidades"].round()
    result["unidades"] = result["unidades"].where((result["unidades"] - rounded).abs() > 0.001, rounded)
    return result


def read_routes(path):
    source = pd.read_excel(path, dtype=str)
    columns = {key(c): c for c in source.columns}
    client = columns.get("cliente")
    route = columns.get("fuerzadeventa1rutadeventa")
    name = columns.get("razonsocial")
    if client is None or route is None:
        raise ValueError("El maestro debe tener Cliente y Fuerza de venta 1 Ruta de venta (CD).")
    result = pd.DataFrame({"cliente": code(source[client]), "ruta": code(source[route]),
                           "nombre": source[name].fillna("") if name else ""})
    if result.groupby("cliente")["ruta"].nunique().gt(1).any():
        raise ValueError("El maestro tiene clientes con rutas contradictorias.")
    return result.drop_duplicates("cliente")


def calculate(sales, routes, members, catalog, cutoff, route_filter=None):
    cutoff = pd.Timestamp(cutoff).normalize()
    monthly = sales[sales.fecha.between(cutoff.replace(day=1), cutoff)].copy()
    eligible = members.merge(routes, on="cliente", how="inner", validate="many_to_one")
    eligible = eligible[~eligible.ruta.isin(INVALID_ROUTES)]
    if route_filter is not None:
        eligible = eligible[eligible.ruta.isin(route_filter)]
    definitions = catalog.drop_duplicates("combo")[["combo", "categoria", "descripcion", "grupo"]]
    population = definitions.merge(eligible, on="grupo", how="inner")
    net = monthly.groupby(["combo", "cliente"], as_index=False)[["unidades", "importe"]].sum()
    detail = population.merge(net, on=["combo", "cliente"], how="left", validate="one_to_one")
    detail[["unidades", "importe"]] = detail[["unidades", "importe"]].fillna(0)
    detail["comprador"] = detail.unidades.gt(0)
    summary = detail.groupby("combo").agg(objetivo=("cliente", "nunique"), ccc=("comprador", "sum"), unidades_validas=("unidades", "sum")).reset_index()
    summary = definitions.merge(summary, on="combo", how="left")
    summary[["objetivo", "ccc", "unidades_validas"]] = summary[["objetivo", "ccc", "unidades_validas"]].fillna(0)
    summary["pendientes"] = summary.objetivo - summary.ccc
    summary["cumplimiento"] = summary.ccc / summary.objetivo.replace(0, np.nan)
    # Exclusions are evaluated against the full eligible population, independent of route display filters.
    all_population = definitions.merge(members.merge(routes[~routes.ruta.isin(INVALID_ROUTES)], on="cliente"), on="grupo")
    excluded = net[net.unidades.gt(0)].merge(all_population[["combo", "cliente"]], on=["combo", "cliente"], how="left", indicator=True)
    excluded = excluded[excluded._merge.eq("left_only")].drop(columns="_merge")
    return summary, detail, excluded, monthly


def render(folder, daily_file, read_raw, parse_dates):
    import streamlit as st
    import plotly.express as px

    st.subheader("Usabilidad de combos")
    st.caption("CCC = clientes del grupo con ruta y compra neta positiva en el mes. 900445 + 900460 cuentan como un combo.")
    if daily_file is None:
        st.warning("No se encontró ventadiaria. Actualizá los datos.")
        return
    try:
        catalog = pd.read_csv(ROOT / "combos_catalogo.csv", dtype=str)
        members_path = folder / "combos_grupos.csv"
        members = pd.read_csv(members_path if members_path.exists() else ROOT / "combos_grupos.csv", dtype=str).drop_duplicates(["grupo", "cliente"])
        members["grupo"] = code(members["grupo"])
        members["cliente"] = code(members["cliente"])
        missing_groups = set(catalog.grupo) - set(members.grupo)
        if missing_groups:
            raise ValueError(f"Faltan padrones de los grupos {sorted(missing_groups)}.")
        master = next((p for p in folder.iterdir() if key(p.stem) == "reportedeclientes" and p.suffix.lower() == ".xlsx"), None)
        if master is None:
            st.warning("Falta REPORTE DE CLIENTES.xlsx con la ruta comercial. Actualizá Drive.")
            return
        routes = read_routes(master)
        raw = read_raw(daily_file)
        dates = parse_dates(raw["Descripción Período"])
        latest = dates.max()
        if pd.isna(latest):
            raise ValueError("Venta diaria no contiene fechas válidas.")
        sales = prepare_sales(raw, parse_dates)
        st.caption(f"Fuente: {daily_file.name} · Última venta: {latest:%d/%m/%Y} · Maestro: {master.name}")
        st.caption("Padrón de grupos inicial: octubre 2026. Para cambiarlo, reemplazar combos_grupos.csv en la carpeta de datos (grupo, cliente).")
        cutoff = st.date_input("Corte del seguimiento", value=latest.date(), min_value=dates.min().date(), max_value=latest.date(), key="combos_cutoff")
        available = sorted(set(routes.ruta) - INVALID_ROUTES)
        route_filter = st.multiselect("Rutas comerciales (vacío = todas)", available, key="combos_routes")
        summary, detail, excluded, monthly = calculate(sales, routes, members, catalog, cutoff, route_filter or None)
        selection = st.multiselect("Combos (vacío = todos)", summary.combo.tolist(), key="combos_selection")
        if selection:
            summary = summary[summary.combo.isin(selection)]
            detail = detail[detail.combo.isin(selection)]
            excluded = excluded[excluded.combo.isin(selection)]
        cols = st.columns(3)
        cols[0].metric("Combos en seguimiento", len(summary))
        cols[1].metric("Clientes únicos con compra válida", detail.loc[detail.comprador, "cliente"].nunique())
        cols[2].metric("Clientes únicos objetivo", detail.cliente.nunique())
        view = summary.rename(columns={"combo":"Combo", "descripcion":"Descripción", "categoria":"Categoría", "grupo":"Grupo", "objetivo":"Objetivo con ruta", "ccc":"CCC válidos", "pendientes":"Clientes pendientes", "cumplimiento":"Cumplimiento", "unidades_validas":"Unidades netas válidas"})
        st.dataframe(view, hide_index=True, width="stretch", column_config={"Cumplimiento": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)})
        st.caption("Los objetivos y CCC de distintos combos se superponen; no se suman como clientes únicos.")
        days = pd.date_range(pd.Timestamp(cutoff).replace(day=1), cutoff)
        evolution = []
        chosen = set(summary.combo)
        for day in days:
            net = monthly[monthly.fecha.le(day)].groupby(["combo", "cliente"], as_index=False).unidades.sum()
            valid = detail[["combo", "cliente"]].merge(net, on=["combo", "cliente"])
            counts = valid[valid.unidades.gt(0)].groupby("combo").cliente.nunique()
            evolution.extend({"Fecha": day, "Combo": combo, "CCC": int(counts.get(combo, 0))} for combo in chosen)
        if evolution:
            st.plotly_chart(px.line(pd.DataFrame(evolution), x="Fecha", y="CCC", color="Combo", title="Evolución del CCC neto mensual"), width="stretch")
        state = st.radio("Detalle de clientes", ["Pendientes", "Compradores", "Todos"], horizontal=True, key="combos_state")
        shown = detail if state == "Todos" else detail[detail.comprador.eq(state == "Compradores")]
        st.dataframe(shown, hide_index=True, width="stretch")
        st.download_button("Descargar detalle CSV", shown.to_csv(index=False).encode("utf-8-sig"), "seguimiento_combos.csv", "text/csv", key="combos_csv")
        with st.expander(f"Compras fuera del objetivo: {len(excluded)} combinaciones combo/cliente"):
            st.caption("Compra positiva fuera del grupo o sin ruta válida. Se excluye del CCC. Este control abarca todas las rutas.")
            st.dataframe(excluded, hide_index=True, width="stretch")
    except Exception as exc:
        st.error(f"No se pudo calcular el seguimiento de combos: {exc}")
