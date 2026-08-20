import math
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd


SUPERVISORES = {
    "GASTON FABRE": "ISMAEL BRUNO",
    "MATIAS GARCIA": "ISMAEL BRUNO",
    "NICASTRO LUCAS": "ISMAEL BRUNO",
    "NICOLAS POCHETINO": "ISMAEL BRUNO",
    "SIRI MARTIN": "ISMAEL BRUNO",
    "VILLAGRA ENZO": "ISMAEL BRUNO",
    "PABLO ALVAREZ": "CASCO HERNAN",
    "ALEXANDER ROJAS": "CASCO HERNAN",
    "FERNANDO FIELG": "CASCO HERNAN",
    "JUAN MANUEL GIMENEZ": "CASCO HERNAN",
    "MENDEZ CARLOS": "CASCO HERNAN",
    "MARIANO HERRERA": "CASCO HERNAN",
    "FEDERICO BISS": "ISMAEL BRUNO",
}

EXCLUDED_VENDORS = {"701", "702", "703"}

DAY_COLS = {0: "LU", 1: "MA", 2: "MI", 3: "JU", 4: "VI", 5: "SA", 6: "DO"}
DAY_GROUPS = {"LU": "LUJU", "JU": "LUJU", "MA": "MAVI", "VI": "MAVI", "MI": "MISA", "SA": "MISA", "DO": "DO"}

FILTER_FIELDS = {
    "TOTAL": None,
    "Marca": "marca",
    "Marca Unificada": "marca_unificada",
    "Division": "division",
    "Calibre": "calibre",
    "Calibre Unificado": "calibre_unificado",
    "Segmento": "segmento",
    "Segmento.2": "segmento_2",
    "Segmento.3": "segmento_3",
    "Producto": "producto",
    "Unidad de Negocio": "unidad_negocio",
    "UNG TOP": "ung_top",
    "CALIBRES CPR": "calibres_cpr",
}

KPI_FOCUSES = [
    "Total CZA",
    "Core",
    "Value",
    "Above Core",
    "Premium",
    "Latones 710",
    "Balanced Choices",
    "Nabs",
    "Eficiencia de ventas",
]

BALANCED_BRANDS = {
    "STELLA ARTOIS PURE GOLD",
    "STELLA ARTOIS 0.0%",
    "CORONA CERO",
    "QUILMES 0.0%",
    "MICHELOB ULTRA",
}


def brand_upper(ventas: pd.DataFrame):
    return ventas["marca"].fillna("").str.upper().str.strip()


def clean_text(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", text)


def clean_code(value):
    text = clean_text(value)
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def key(*parts):
    return "|".join(clean_text(part).upper() for part in parts)


def parse_number(value):
    text = clean_text(value)
    if not text:
        return 0.0
    text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_date_from_period(value):
    text = clean_text(value).lower()
    match = re.search(r"(\d{1,2})\s+([a-z]{3})\s+(\d{4})", text)
    if not match:
        return pd.NaT
    months = {
        "ene": 1,
        "feb": 2,
        "mar": 3,
        "abr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "ago": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dic": 12,
    }
    return pd.Timestamp(date(int(match.group(3)), months[match.group(2)], int(match.group(1))))


def load_auxiliares(path: Path):
    aux = pd.read_excel(path, sheet_name="PIVOT", dtype=str)
    brand_rows = []
    mix_rows = []
    caliber_rows = []
    for _, row in aux.iterrows():
        marca = clean_text(row.get("MARCA"))
        if marca:
            brand_rows.append(
                {
                    "marca_key": marca.upper(),
                    "marca_unificada": clean_text(row.get("MARCA UNIFICADA")) or marca,
                    "segmento": clean_text(row.get("SEGMENTO")),
                    "segmento_2": clean_text(row.get("SEGMENTO.2")),
                    "segmento_3": clean_text(row.get("SEGMENTO.3")),
                }
            )
        mix_brand = clean_text(row.get("Marca"))
        mix_div = clean_text(row.get("División"))
        mix_cal = clean_text(row.get("Calibre"))
        if mix_brand and mix_div and mix_cal:
            mix_rows.append(
                {
                    "mix_key": key(mix_brand, mix_div, mix_cal),
                    "ung_top": clean_text(row.get("UNG TOP")),
                    "calibres_cpr": clean_text(row.get("CALIBRES CPR")),
                }
            )
        unidad = clean_text(row.get("Unidad de Negocio"))
        calibre = clean_text(row.get("Calibre.1"))
        if unidad and calibre:
            caliber_rows.append(
                {
                    "calibre_key": key(unidad, calibre),
                    "calibre_unificado": clean_text(row.get("Calibre Unificado")),
                }
            )
    return (
        pd.DataFrame(brand_rows).drop_duplicates("marca_key"),
        pd.DataFrame(mix_rows).drop_duplicates("mix_key"),
        pd.DataFrame(caliber_rows).drop_duplicates("calibre_key"),
    )


def load_rutas(path: Path):
    rutas = pd.read_excel(path, sheet_name="Browser", dtype=str)
    rows = []
    for _, row in rutas.iterrows():
        vendedor = clean_code(row.get("Vnd."))
        cliente = clean_code(row.get("Cliente"))
        if not vendedor or not cliente:
            continue
        rows.append(
            {
                "vendedor": vendedor,
                "ruta": clean_code(row.get("Ruta")),
                "cliente": cliente,
                "razon_social": clean_text(row.get("Razón Social")),
                "lu": clean_text(row.get("LU")),
                "ma": clean_text(row.get("MA")),
                "mi": clean_text(row.get("MI")),
                "ju": clean_text(row.get("JU")),
                "vi": clean_text(row.get("VI")),
                "sa": clean_text(row.get("SA")),
                "do": clean_text(row.get("DO")),
                "alta_fecha": pd.NaT,
            }
        )
    return pd.DataFrame(rows)


def find_clientes_path(base: Path):
    matches = sorted(base.rglob("*plantillaClientesAR*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def normalized_name(path: Path):
    text = clean_text(path.stem).upper()
    text = text.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text)


def find_data_file(base: Path, required_terms: tuple[str, ...], suffixes: tuple[str, ...], excluded_terms: tuple[str, ...] = ()):
    if not base.exists():
        return None
    suffixes = tuple(s.lower() for s in suffixes)
    candidates = []
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        name = normalized_name(path)
        if all(term.upper() in name for term in required_terms) and not any(term.upper() in name for term in excluded_terms):
            candidates.append(path)
    candidates = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None




def excel_col_index(label: str):
    index = 0
    for char in label.upper():
        if not char.isalpha():
            continue
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def first_existing_column(df: pd.DataFrame, patterns: tuple[str, ...]):
    normalized = {str(col).strip().upper(): col for col in df.columns}
    for pattern in patterns:
        pattern = pattern.upper()
        for name, col in normalized.items():
            if pattern in name:
                return col
    return None


def parse_client_date(value):
    return pd.to_datetime(value, errors="coerce")


def route_flags_from_visit_day(value):
    text = clean_text(value).upper()
    flags = {"lu": "", "ma": "", "mi": "", "ju": "", "vi": "", "sa": "", "do": ""}
    if not text:
        return flags
    replacements = {
        "LUNES": "LU",
        "LUN": "LU",
        "MARTES": "MA",
        "MAR": "MA",
        "MIERCOLES": "MI",
        "MIÉRCOLES": "MI",
        "MIE": "MI",
        "JUEVES": "JU",
        "JUE": "JU",
        "VIERNES": "VI",
        "VIE": "VI",
        "SABADO": "SA",
        "SÁBADO": "SA",
        "SAB": "SA",
        "DOMINGO": "DO",
        "DOM": "DO",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    if "LUJU" in text:
        flags["lu"] = "X"
        flags["ju"] = "X"
    if "MAVI" in text:
        flags["ma"] = "X"
        flags["vi"] = "X"
    if "MISA" in text:
        flags["mi"] = "X"
        flags["sa"] = "X"
    day_map = {"LU": "lu", "MA": "ma", "MI": "mi", "JU": "ju", "VI": "vi", "SA": "sa", "DO": "do"}
    for token, col in day_map.items():
        if re.search(rf"(^|[^A-Z]){token}([^A-Z]|$)", text):
            flags[col] = "X"
    return flags


def load_reporte_clientes(path: Path | None, clientes: pd.DataFrame, promotores: pd.DataFrame):
    columns = ["vendedor", "ruta", "cliente", "razon_social", "lu", "ma", "mi", "ju", "vi", "sa", "do", "alta_fecha"]
    if path is None or not path.exists():
        return pd.DataFrame(columns=columns)
    report = pd.read_excel(path, dtype=str)
    if report.empty:
        return pd.DataFrame(columns=columns)
    promotor_col = report.columns[excel_col_index("CG")] if len(report.columns) > excel_col_index("CG") else first_existing_column(report, ("PROMOTOR", "VENDEDOR"))
    dia_col = report.columns[excel_col_index("CH")] if len(report.columns) > excel_col_index("CH") else first_existing_column(report, ("DIA", "DÍA", "VISITA"))
    cliente_col = first_existing_column(report, ("COD. CLIENTE", "COD CLIENTE", "CODIGO CLIENTE", "CÓDIGO CLIENTE", "CLIENTE"))
    razon_col = first_existing_column(report, ("RAZON SOCIAL", "RAZÓN SOCIAL", "DESCRIPCION", "DESCRIPCIÓN", "CLIENTE"))
    ruta_col = first_existing_column(report, ("RUTA DE VENTA", "RUTA"))
    alta_col = first_existing_column(report, ("ALTA FECHA", "FECHA DE ALTA"))
    if promotor_col is None or dia_col is None or cliente_col is None:
        return pd.DataFrame(columns=columns)
    promotores_lookup = promotores.dropna(subset=["promotor"]).drop_duplicates("promotor")
    promotores_lookup = promotores_lookup.assign(promotor_key=promotores_lookup["promotor"].map(lambda value: clean_text(value).upper()))
    promotor_to_vendedor = promotores_lookup.set_index("promotor_key")["vendedor"].to_dict()
    rows = []
    for _, row in report.iterrows():
        cliente = clean_code(row.get(cliente_col))
        promotor = clean_text(row.get(promotor_col)).upper()
        vendedor = promotor_to_vendedor.get(promotor)
        if not cliente or not vendedor:
            continue
        flags = route_flags_from_visit_day(row.get(dia_col))
        if not any(flags.values()):
            continue
        rows.append(
            {
                "vendedor": vendedor,
                "ruta": clean_code(row.get(ruta_col)) if ruta_col is not None else vendedor,
                "cliente": cliente,
                "razon_social": clean_text(row.get(razon_col)) if razon_col is not None else "",
                "alta_fecha": parse_client_date(row.get(alta_col)) if alta_col is not None else pd.NaT,
                **flags,
            }
        )
    reporte = pd.DataFrame(rows, columns=columns)
    if reporte.empty:
        return reporte
    if not clientes.empty:
        reporte = reporte.merge(clientes, on="cliente", how="left")
        reporte["nombre_fantasia"] = reporte["nombre_fantasia"].fillna("")
        reporte["licencia_alcohol"] = reporte["licencia_alcohol"].fillna("")
    else:
        reporte["nombre_fantasia"] = ""
        reporte["licencia_alcohol"] = ""
    reporte["razon_social"] = reporte["razon_social"].where(reporte["razon_social"].ne(""), reporte["nombre_fantasia"])
    return reporte.drop_duplicates(["vendedor", "cliente", "lu", "ma", "mi", "ju", "vi", "sa", "do"])


def load_clientes(path: Path | None):
    columns = ["cliente", "nombre_fantasia", "licencia_alcohol"]
    if path is None or not path.exists():
        return pd.DataFrame(columns=columns)
    clientes = pd.read_excel(path, sheet_name="Clientes", header=1, dtype=str)
    if "Cliente" not in clientes.columns or "Nombre de fantasia" not in clientes.columns:
        return pd.DataFrame(columns=columns)
    licencia_col = "Licencia alcohol" if "Licencia alcohol" in clientes.columns else None
    df = pd.DataFrame(
        {
            "cliente": clientes["Cliente"].map(clean_code),
            "nombre_fantasia": clientes["Nombre de fantasia"].map(clean_text),
            "licencia_alcohol": clientes[licencia_col].map(clean_text).str.upper() if licencia_col else "",
        }
    )
    df = df[df["cliente"].ne("") & df["cliente"].ne("ENTERO")]
    df = df.sort_values("nombre_fantasia").drop_duplicates("cliente", keep="first")
    return df


def load_ventas(path: Path, brand_map: pd.DataFrame, mix_map: pd.DataFrame, caliber_map: pd.DataFrame):
    venta = pd.read_csv(path, sep="\t", encoding="latin1", dtype=str, engine="python")
    df = pd.DataFrame(
        {
            "fecha": venta["Periodos"].map(parse_date_from_period),
            "vendedor": venta["Vendedor"].map(clean_code),
            "promotor": venta["Descripción Vendedor"].map(clean_text),
            "ruta": venta["Ruta"].map(clean_code),
            "cliente": venta["Cod. Cliente"].map(clean_code),
            "cliente_nombre": venta["Descripción"].map(clean_text),
            "articulo_descripcion": venta["Descripción.2"].map(clean_text),
            "marca": venta["Descripción.3"].map(clean_text),
            "calibre": venta["Descripción.4"].map(clean_text),
            "division": venta["Descripción.5"].map(clean_text),
            "producto": venta["Descripción.6"].map(clean_text),
            "unidad_negocio": venta["Descripción.8"].map(clean_text),
            "cantidad": venta["Cantidades Totales"].map(parse_number),
            "importe_neto": venta["Importes Netos"].map(parse_number),
            "facturas": venta["Cantidad de Facturas"].map(parse_number),
        }
    ).dropna(subset=["fecha"])
    df["promotor"] = df.apply(lambda r: r["promotor"] or f"VND {r['vendedor']}", axis=1)
    df["supervisor"] = df["promotor"].map(SUPERVISORES).fillna("OTROS")
    df["marca_key"] = df["marca"].str.upper()
    df = df.merge(brand_map, on="marca_key", how="left")
    df["marca_unificada"] = df["marca_unificada"].fillna(df["marca"])
    for col in ["segmento", "segmento_2", "segmento_3"]:
        df[col] = df[col].fillna("")
    df["mix_key"] = df.apply(lambda r: key(r["marca"], r["division"], r["calibre"]), axis=1)
    df = df.merge(mix_map, on="mix_key", how="left")
    df["calibre_key"] = df.apply(lambda r: key(r["unidad_negocio"], r["calibre"]), axis=1)
    df = df.merge(caliber_map, on="calibre_key", how="left")
    df["calibre_unificado"] = df["calibre_unificado"].fillna(df["calibre"])
    df[["ung_top", "calibres_cpr"]] = df[["ung_top", "calibres_cpr"]].fillna("")
    search_cols = ["articulo_descripcion", "marca", "marca_unificada", "producto", "calibre", "calibre_unificado"]
    df["sku_search_text"] = df[search_cols].fillna("").agg(" ".join, axis=1).str.upper()
    return df


def build_route_days(rutas: pd.DataFrame, fechas: list[pd.Timestamp], promotores: pd.DataFrame):
    promotor_lookup = promotores.set_index("vendedor")["promotor"].to_dict()
    rows = []
    for _, row in rutas.iterrows():
        for fecha in fechas:
            day_col = DAY_COLS[fecha.weekday()].lower()
            if clean_text(row.get(day_col)).upper() != "X":
                continue
            promotor = promotor_lookup.get(row["vendedor"], f"VND {row['vendedor']}")
            rows.append(
                {
                    "fecha": fecha,
                    "vendedor": row["vendedor"],
                    "promotor": promotor,
                    "supervisor": SUPERVISORES.get(promotor, "OTROS"),
                    "ruta": row["ruta"],
                    "cliente": row["cliente"],
                    "razon_social": row["razon_social"],
                    "nombre_fantasia": row.get("nombre_fantasia", ""),
                    "licencia_alcohol": row.get("licencia_alcohol", ""),
                    "dia": DAY_COLS[fecha.weekday()],
                    "grupo_ruta": DAY_GROUPS.get(DAY_COLS[fecha.weekday()], "OTROS"),
                }
            )
    return pd.DataFrame(rows)


def build_route_groups(rutas: pd.DataFrame, promotores: pd.DataFrame):
    promotor_lookup = promotores.set_index("vendedor")["promotor"].to_dict()
    day_cols = {"LU": "lu", "MA": "ma", "MI": "mi", "JU": "ju", "VI": "vi", "SA": "sa", "DO": "do"}
    rows = []
    for _, row in rutas.iterrows():
        for day_label, col in day_cols.items():
            if clean_text(row.get(col)).upper() != "X":
                continue
            promotor = promotor_lookup.get(row["vendedor"], f"VND {row['vendedor']}")
            rows.append(
                {
                    "vendedor": row["vendedor"],
                    "promotor": promotor,
                    "supervisor": SUPERVISORES.get(promotor, "OTROS"),
                    "ruta": row["ruta"],
                    "cliente": row["cliente"],
                    "razon_social": row["razon_social"],
                    "nombre_fantasia": row.get("nombre_fantasia", ""),
                    "licencia_alcohol": row.get("licencia_alcohol", ""),
                    "alta_fecha": row.get("alta_fecha", pd.NaT),
                    "dia": day_label,
                    "grupo_ruta": DAY_GROUPS.get(day_label, "OTROS"),
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "vendedor",
                "promotor",
                "supervisor",
                "ruta",
                "cliente",
                "razon_social",
                "nombre_fantasia",
                "licencia_alcohol",
                "alta_fecha",
                "dia",
                "grupo_ruta",
            ]
        )
    return pd.DataFrame(rows).drop_duplicates(["vendedor", "cliente", "grupo_ruta"])


def apply_route_flag(ventas: pd.DataFrame, rutas_dia: pd.DataFrame):
    if rutas_dia.empty:
        ventas["en_ruta_dia"] = False
        return ventas
    route_keys = rutas_dia[["fecha", "vendedor", "cliente"]].drop_duplicates()
    route_keys["en_ruta_dia"] = True
    return ventas.merge(route_keys, on=["fecha", "vendedor", "cliente"], how="left").assign(
        en_ruta_dia=lambda df: df["en_ruta_dia"].fillna(False)
    )


def load_dataset(base_dir: str):
    base = Path(base_dir)
    rutas_path = find_data_file(base, ("RUTAS",), (".xlsx", ".xls"))
    aux_path = find_data_file(base, ("AUXILIARES",), (".xlsx", ".xls"))
    ventas_path = find_data_file(base, ("VENTA", "DIARIA"), (".txt", ".csv"), ("ANUAL", "BULTOS"))
    ventas_anual_path = find_data_file(base, ("VENTA", "ANUAL"), (".txt", ".csv"))
    reporte_clientes_path = find_data_file(base, ("REPORTE", "CLIENTES"), (".xlsx", ".xls", ".csv", ".txt"))
    clientes_path = find_clientes_path(base)
    missing = []
    if rutas_path is None:
        missing.append("RUTAS *.xlsx")
    if aux_path is None:
        missing.append("AUXILIARES *.xlsx")
    if ventas_path is None:
        missing.append("VENTA DIARIA *.txt")
    if missing:
        raise FileNotFoundError("No se encontraron archivos en " + str(base) + ": " + ", ".join(missing))

    brand_map, mix_map, caliber_map = load_auxiliares(aux_path)
    rutas = load_rutas(rutas_path)
    clientes = load_clientes(clientes_path)
    if not clientes.empty:
        rutas = rutas.merge(clientes, on="cliente", how="left")
        rutas["nombre_fantasia"] = rutas["nombre_fantasia"].fillna("")
        rutas["licencia_alcohol"] = rutas["licencia_alcohol"].fillna("")
    else:
        rutas["nombre_fantasia"] = ""
        rutas["licencia_alcohol"] = ""
    ventas = load_ventas(ventas_path, brand_map, mix_map, caliber_map)
    rutas = rutas[~rutas["vendedor"].isin(EXCLUDED_VENDORS)].copy()
    ventas = ventas[~ventas["vendedor"].isin(EXCLUDED_VENDORS)].copy()
    promotores_venta = ventas[["vendedor", "promotor", "supervisor"]].drop_duplicates("vendedor")
    promotores_ruta = pd.DataFrame({"vendedor": sorted(rutas["vendedor"].dropna().unique())})
    promotores = promotores_ruta.merge(promotores_venta, on="vendedor", how="left")
    promotores["promotor"] = promotores["promotor"].fillna(promotores["vendedor"].map(lambda x: f"VND {x}"))
    promotores["supervisor"] = promotores["promotor"].map(SUPERVISORES).fillna("OTROS")
    reporte_rutas = load_reporte_clientes(reporte_clientes_path, clientes, promotores)
    if not reporte_rutas.empty:
        rutas = pd.concat([rutas, reporte_rutas], ignore_index=True).drop_duplicates(
            ["vendedor", "cliente", "lu", "ma", "mi", "ju", "vi", "sa", "do"],
            keep="last",
        )
    fechas = sorted(ventas["fecha"].dropna().unique())
    rutas_dia = build_route_days(rutas, fechas, promotores)
    rutas_grupo = build_route_groups(rutas, promotores)
    ventas = apply_route_flag(ventas, rutas_dia)
    return {
        "rutas": rutas,
        "rutas_dia": rutas_dia,
        "rutas_grupo": rutas_grupo,
        "ventas": ventas,
        "clientes": clientes,
        "promotores": promotores.sort_values("promotor"),
        "fechas": fechas,
        "sources": {
            "rutas": rutas_path,
            "auxiliares": aux_path,
            "ventas": ventas_path,
            "ventas_anual": ventas_anual_path or "No encontrado",
            "reporte_clientes": reporte_clientes_path or "No encontrado",
            "clientes": clientes_path or "No encontrado",
        },
    }


def filter_sales(ventas: pd.DataFrame, fecha, filter_type: str, filter_value: str):
    filtered = ventas[(ventas["fecha"] == pd.Timestamp(fecha)) & (ventas["en_ruta_dia"])]
    field = FILTER_FIELDS[filter_type]
    if field is None:
        return filtered
    return filtered[filtered[field].fillna("").eq(filter_value)]


def focus_sales(ventas: pd.DataFrame, focus: str):
    filtered = ventas.copy()
    marca = brand_upper(filtered)
    search_text = filtered.get("sku_search_text", pd.Series("", index=filtered.index)).fillna("").str.upper()
    cza = filtered["division"].eq("CERVEZAS")
    combo = search_text.str.contains(r"\bCOMBO\b|\bPROMO\b", regex=True, na=False)
    beer_combo = combo & search_text.str.contains(
        r"LATON|LATONES|\b710\b|L710|SA 710|LATA|LATAS|CERVEZA|PATAGONIA|\bPAT\b|"
        r"MICHELOB|PURE GOLD|\b0\.0\b|BRAHMA|QUILMES|BUD|CORONA|STELLA|ANDES|QC|BR",
        regex=True,
        na=False,
    )
    latones_combo = combo & search_text.str.contains(
        r"LATON|LATONES|\b710\b|L710|SA 710|710 OW",
        regex=True,
        na=False,
    )
    balanced = marca.isin(BALANCED_BRANDS)
    if focus == "Total CZA":
        return filtered[cza | beer_combo]
    if focus == "Core":
        core = (
            marca.eq("BRAHMA")
            | marca.str.startswith("BUDWEISER")
            | (
                marca.str.contains("QUILMES", na=False)
                & ~marca.eq("QUILMES 1890")
                & ~balanced
            )
        )
        return filtered[cza & core]
    if focus == "Value":
        return filtered[cza & marca.eq("QUILMES 1890")]
    if focus == "Above Core":
        above_core = (
            marca.str.startswith("STELLA ARTOIS")
            | marca.str.startswith("ANDES ORIGEN")
        ) & ~balanced
        return filtered[cza & above_core]
    if focus == "Premium":
        premium = (
            marca.str.startswith("CORONA")
            | marca.str.startswith("PATAGONIA")
        ) & ~balanced
        return filtered[cza & premium]
    if focus == "Latones 710":
        return filtered[filtered["calibre_unificado"].eq("LATON 710 CC") | latones_combo]
    if focus == "Balanced Choices":
        return filtered[cza & balanced]
    if focus == "Nabs":
        nabs_divisions = {"AGUAS", "BEB ENERGIZANTES", "BEBIDAS SABORIZADAS", "GASEOSAS", "ISOTONICAS"}
        nabs_combo = combo & search_text.str.contains(
            r"PEPSI|\bBLACK\b|MIRINDA|\b7UP\b|GATORADE|\bGTD\b|RED\s*BULL|REDBULL|SABORIZADAS|ENERGIA|ENERGÍA|"
            r"BIDON|NESTLE|PUREZA|NPV|ECO|GLACIAR|AGUA",
            regex=True,
            na=False,
        )
        return filtered[filtered["division"].isin(nabs_divisions) | nabs_combo]
    if focus == "Eficiencia de ventas":
        return filtered
    return filtered


def only_new_sku_activations(ventas: pd.DataFrame, fecha):
    fecha = pd.Timestamp(fecha)
    current = ventas[ventas["fecha"].eq(fecha)].copy()
    if current.empty:
        return current
    previous_keys = set(
        ventas[ventas["fecha"].lt(fecha)]
        .assign(cliente_producto=lambda df: df["cliente"] + "|" + df["producto"])
        ["cliente_producto"]
        .dropna()
        .unique()
    )
    current["cliente_producto"] = current["cliente"] + "|" + current["producto"]
    return current[~current["cliente_producto"].isin(previous_keys)].drop(columns=["cliente_producto"])


def only_new_sku_activations_range(ventas: pd.DataFrame, start_date, end_date):
    start_date = pd.Timestamp(start_date)
    end_date = pd.Timestamp(end_date)
    current = ventas[(ventas["fecha"].ge(start_date)) & (ventas["fecha"].le(end_date))].copy()
    if current.empty:
        return current
    previous_keys = set(
        ventas[ventas["fecha"].lt(start_date)]
        .assign(cliente_producto=lambda df: df["cliente"] + "|" + df["producto"])
        ["cliente_producto"]
        .dropna()
        .unique()
    )
    current["cliente_producto"] = current["cliente"] + "|" + current["producto"]
    current = current[~current["cliente_producto"].isin(previous_keys)].copy()
    current = current.sort_values("fecha").drop_duplicates(["cliente", "producto"], keep="first")
    return current.drop(columns=["cliente_producto"])


def only_new_client_activations_range(ventas: pd.DataFrame, start_date, end_date, lookback_start=None):
    start_date = pd.Timestamp(start_date)
    end_date = pd.Timestamp(end_date)
    lookback_start = pd.Timestamp(lookback_start) if lookback_start is not None else None
    current = ventas[(ventas["fecha"].ge(start_date)) & (ventas["fecha"].le(end_date))].copy()
    if current.empty:
        return current
    previous = ventas[ventas["fecha"].lt(start_date)].copy()
    if lookback_start is not None:
        previous = previous[previous["fecha"].ge(lookback_start)]
    previous_clients = set(previous["cliente"].dropna().unique())
    current = current[~current["cliente"].isin(previous_clients)].copy()
    current = current.sort_values("fecha").drop_duplicates(["cliente"], keep="first")
    return current


def filter_sales_by_focus(ventas: pd.DataFrame, fecha, focus: str, rutas_base: pd.DataFrame | None = None, route: str = "Todas"):
    focused = focus_sales(ventas, focus)
    filtered = only_new_sku_activations(focused, fecha)
    if rutas_base is not None and rutas_base.empty:
        return filtered.iloc[0:0].copy()
    if rutas_base is not None and not rutas_base.empty:
        route_scope = rutas_base.copy()
        if route != "Todas":
            route_scope = route_scope[route_scope["grupo_ruta"].eq(route)]
        route_keys = route_scope[["vendedor", "cliente"]].drop_duplicates()
        filtered = filtered.merge(route_keys, on=["vendedor", "cliente"], how="inner")
    return filtered


def filter_client_activations_by_focus_range(
    ventas: pd.DataFrame,
    start_date,
    end_date,
    focus: str,
    rutas_base: pd.DataFrame | None = None,
    route: str = "Todas",
    lookback_start=None,
):
    focused = focus_sales(ventas, focus)
    filtered = only_new_client_activations_range(focused, start_date, end_date, lookback_start)
    if rutas_base is not None and rutas_base.empty:
        return filtered.iloc[0:0].copy()
    if rutas_base is not None and not rutas_base.empty:
        route_scope = rutas_base.copy()
        if route != "Todas":
            route_scope = route_scope[route_scope["grupo_ruta"].eq(route)]
        route_keys = route_scope[["vendedor", "cliente"]].drop_duplicates()
        filtered = filtered.merge(route_keys, on=["vendedor", "cliente"], how="inner")
    return filtered


def filter_sales_by_focus_range(
    ventas: pd.DataFrame,
    start_date,
    end_date,
    focus: str,
    rutas_base: pd.DataFrame | None = None,
    route: str = "Todas",
):
    focused = focus_sales(ventas, focus)
    filtered = only_new_sku_activations_range(focused, start_date, end_date)
    if rutas_base is not None and rutas_base.empty:
        return filtered.iloc[0:0].copy()
    if rutas_base is not None and not rutas_base.empty:
        route_scope = rutas_base.copy()
        if route != "Todas":
            route_scope = route_scope[route_scope["grupo_ruta"].eq(route)]
        route_keys = route_scope[["vendedor", "cliente"]].drop_duplicates()
        filtered = filtered.merge(route_keys, on=["vendedor", "cliente"], how="inner")
    return filtered


def available_values(ventas: pd.DataFrame, filter_type: str):
    field = FILTER_FIELDS[filter_type]
    if field is None:
        return ["TOTAL"]
    values = sorted(v for v in ventas[field].fillna("").unique() if v)
    return values or ["Sin valores"]


def summarize(filtered_sales: pd.DataFrame, rutas_base: pd.DataFrame, promotores: pd.DataFrame, fecha, route: str = "Todas"):
    base_routes = rutas_base.copy()
    if route != "Todas":
        base_routes = base_routes[base_routes["grupo_ruta"].eq(route)]
    route_counts = (
        base_routes.drop_duplicates(["vendedor", "cliente"])
        .groupby(["vendedor", "promotor", "supervisor"], as_index=False)
        .agg(clientes_ruta=("cliente", "count"))
    )
    if filtered_sales.empty:
        metrics = pd.DataFrame(columns=["vendedor", "clientes_compra", "brand_distribution", "importe_neto", "cantidad"])
    else:
        tmp = filtered_sales.copy()
        tmp["cliente_sku"] = tmp["cliente"] + "|" + tmp["producto"]
        metrics = (
            tmp.groupby("vendedor", as_index=False)
            .agg(
                clientes_compra=("cliente", "nunique"),
                brand_distribution=("cliente_sku", "nunique"),
                importe_neto=("importe_neto", "sum"),
                cantidad=("cantidad", "sum"),
            )
        )
    summary = promotores.merge(route_counts, on=["vendedor", "promotor", "supervisor"], how="left")
    summary = summary.merge(metrics, on="vendedor", how="left")
    for col in ["clientes_ruta", "clientes_compra", "brand_distribution", "importe_neto", "cantidad"]:
        summary[col] = summary[col].fillna(0)
    summary["% compra"] = summary.apply(
        lambda r: r["clientes_compra"] / r["clientes_ruta"] if r["clientes_ruta"] else 0,
        axis=1,
    )
    summary["BD / cliente ruta"] = summary.apply(
        lambda r: r["brand_distribution"] / r["clientes_ruta"] if r["clientes_ruta"] else 0,
        axis=1,
    )
    summary["clientes_restantes"] = (summary["clientes_ruta"] - summary["clientes_compra"]).clip(lower=0)
    return summary.sort_values(["supervisor", "promotor"])


def trend(ventas: pd.DataFrame, filter_type: str, filter_value: str):
    rows = []
    for fecha in sorted(ventas["fecha"].dropna().unique()):
        filtered = filter_sales(ventas, fecha, filter_type, filter_value)
        tmp = filtered.copy()
        if tmp.empty:
            rows.append({"fecha": fecha, "clientes_compra": 0, "brand_distribution": 0})
            continue
        tmp["cliente_sku"] = tmp["cliente"] + "|" + tmp["producto"]
        rows.append(
            {
                "fecha": fecha,
                "clientes_compra": tmp["cliente"].nunique(),
                "brand_distribution": tmp["cliente_sku"].nunique(),
            }
        )
    return pd.DataFrame(rows)


def trend_by_focus(ventas: pd.DataFrame, focus: str, rutas_dia: pd.DataFrame | None = None, route: str = "Todas"):
    rows = []
    for fecha in sorted(ventas["fecha"].dropna().unique()):
        tmp = filter_sales_by_focus(ventas, fecha, focus, rutas_dia, route)
        if tmp.empty:
            rows.append({"fecha": fecha, "clientes_compra": 0, "brand_distribution": 0})
            continue
        tmp = tmp.copy()
        tmp["cliente_sku"] = tmp["cliente"] + "|" + tmp["producto"]
        rows.append(
            {
                "fecha": fecha,
                "clientes_compra": tmp["cliente"].nunique(),
                "brand_distribution": tmp["cliente_sku"].nunique(),
            }
        )
    return pd.DataFrame(rows)
