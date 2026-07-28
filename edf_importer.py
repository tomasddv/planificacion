import json
import math
import os
import re
import unicodedata
from pathlib import Path

import pandas as pd


DRIVE_URL = "https://drive.google.com/drive/folders/1cukgXLUaPsEDK_yD7tSwgaBFZAbiDUot"
ROOT = Path(__file__).parent
SOURCE_DIR = ROOT / "data" / "drive-source"
DB_PATH = ROOT / "data" / "db.json"

REPAYMENT_TARGETS = {
    "Vertical grande": 2.5,
    "Mostrador": 1.6,
    "Slim": 1.2,
    "Sahara": 1.2,
    "Doble puerta": 3.2,
    "Horizontal": 1.9,
    "3 bandejas": 1.6,
    "Baby visu": 1.6,
    "Vertical mediana": 1.9,
    "Check out": 1.6,
    "Full glass": 2.5,
    "Gondola de calidad": 3.2,
    "Red Bull": 0.001,
}

SUPERVISORS = {
    "BRUNO ISMAEL": [
        "NICASTRO LUCAS", "POCHETINO NICOLAS", "SIRI MARTIN", "GARCIA MATIAS",
        "VILLAGRA ENZO", "FUENTEALBA MAURICIO", "JARAMILLO JORDAN",
        "FABRE GASTON", "GASTON FABRE",
    ],
    "CASCO HERNAN": [
        "MENDEZ CARLOS", "FIELG FERNANDO", "ALVAREZ PABLO", "ROJAS ALEXANDER",
        "GIMENEZ JUAN MANUEL", "MORENI LUCIANO", "HERRERA MARIANO",
        "ALEXANDER ROJAS", "FERNANDO FIELG", "JUAN MANUEL GIMENEZ",
    ],
    "VITI ANIBAL": ["FEDERICO BISS"],
}


def clean(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value)).strip()


def key(value):
    text = unicodedata.normalize("NFD", clean(value))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def name_key(value):
    text = unicodedata.normalize("NFD", clean(value).upper())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", text)).strip()


PROMOTER_SUPERVISOR = {}
for supervisor, promoters in SUPERVISORS.items():
    for promoter in promoters:
        normalized = name_key(promoter)
        parts = normalized.split()
        PROMOTER_SUPERVISOR[normalized] = supervisor
        if len(parts) == 2:
            PROMOTER_SUPERVISOR[f"{parts[1]} {parts[0]}"] = supervisor


def supervisor_for_promoter(promoter):
    return PROMOTER_SUPERVISOR.get(name_key(promoter), "Sin supervisor")


def code(value):
    text = clean(value)
    match = re.match(r"^\((\d+)\)", text)
    if match:
        text = match.group(1)
    if re.match(r"^\d+(\.0)?$", text):
        text = str(int(float(text)))
    return text.lstrip("0") or ("0" if text else "")


def parse_number(value):
    text = clean(value).replace(".", "").replace(",", ".")
    try:
        return round(float(text), 2)
    except ValueError:
        return 0


def first(row, names):
    for name in names:
        if name in row and clean(row[name]):
            return clean(row[name])
    return ""


def normalize_columns(df):
    df = df.copy()
    df.columns = [key(col) or f"col{i}" for i, col in enumerate(df.columns)]
    return df.fillna("")


def read_excel_any(path, sheet=None):
    suffix = path.suffix.lower()
    engine = "pyxlsb" if suffix == ".xlsb" else "openpyxl"
    return normalize_columns(pd.read_excel(path, sheet_name=sheet or 0, engine=engine, dtype=str))


def find_file(patterns):
    files = [p for p in SOURCE_DIR.iterdir() if p.is_file()]
    for pattern in patterns:
        matches = [p for p in files if re.search(pattern, p.name, re.I)]
        if matches:
            return sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    return None


def guess_model(row):
    raw = f"{first(row, ['modelo','codmodelo','descripcionarticulo','descproducto','producto'])} {first(row, ['unidaddenegocio','un'])}".upper()
    if re.search(r"\bBV\b|BABY", raw):
        return "Baby visu"
    if re.search(r"RED BULL|\bRB\b", raw):
        return "Red Bull"
    if re.search(r"VERT.*GRAN|\bVG\b", raw):
        return "Vertical grande"
    if re.search(r"VERT.*MED|\bVM\b", raw):
        return "Vertical mediana"
    if re.search(r"DOBLE|2P|\bDP\b", raw):
        return "Doble puerta"
    if re.search(r"FULL|GLASS", raw):
        return "Full glass"
    if "HORIZ" in raw:
        return "Horizontal"
    if "SAHARA" in raw:
        return "Sahara"
    if "SLIM" in raw:
        return "Slim"
    if "MOST" in raw:
        return "Mostrador"
    if re.search(r"3.*BAN", raw):
        return "3 bandejas"
    return "Mostrador"


def business_from_value(value, category="", brand=""):
    text = f"{clean(value)} {clean(category)} {clean(brand)}".upper()
    if re.search(r"RED BULL|\bRB\b|REDBULL", text):
        return "RB"
    if re.search(r"AGUAS|AGUA|ECO", text):
        return "AGUAS"
    if re.search(r"CERVE|CMQ|CZA", text):
        return "CZA"
    if re.search(r"UNG|GASEOS|ISOTON|ENERG|H2OH|SABORIZ", text):
        return "UNG"
    return "OTROS"


def business_from_edf(row):
    un = first(row, ["un", "unidaddenegocio"])
    logo = first(row, ["logo"])
    product = first(row, ["descproducto", "descripcionarticulo", "producto"])
    text = f"{un} {logo} {product}".upper()
    if re.search(r"CERVE|CMQ|CZA", un.upper()):
        return "CZA"
    if re.search(r"AGUAS|AGUA|ECO", un.upper()):
        return "AGUAS"
    if re.search(r"RED BULL|\bRB\b|REDBULL", text):
        return "RB"
    if re.search(r"UNG|GASEOS|ISOTON|ENERG|H2OH|SABORIZ", text):
        return "UNG"
    return business_from_value(text)


def normalize_status(location, customer_id):
    if customer_id:
        return "PDV"
    text = clean(location).upper()
    if "BAJA" in text:
        return "BAJA DEFINITIVA"
    if "REPAR" in text:
        return "REPARACION"
    if re.search(r"DEPOS|DEP", text):
        return "DEPOSITO"
    return "STOCK"


def deposit_from(row):
    dep_code = code(first(row, ["coddeposito"]))
    text = f"{first(row, ['descdeposito','ubicacion','relaciondeposucursal'])}".upper()
    if dep_code == "8" or "TRELEW" in text:
        return "TRELEW"
    if dep_code == "14" or "MADRYN" in text:
        return "MADRYN"
    return "INTERIOR"


def period_key(cols):
    desc = clean(cols[2]).lower() if len(cols) > 2 else ""
    months = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}
    match = re.search(r"([a-záéíóúñ]{3})-(\d{2})", desc, re.I)
    if match:
        mon = name_key(match.group(1)).lower()[:3]
        return f"{2000 + int(match.group(2))}-{months.get(mon, 1):02d}"
    month = int(float(clean(cols[1]) or 7)) if len(cols) > 1 else 7
    return f"2026-{month:02d}"


def ensure_customer(customers, customer_id, name=""):
    if customer_id not in customers:
        customers[customer_id] = {
            "id": customer_id,
            "name": name,
            "fantasyName": name,
            "legalName": "",
            "address": "",
            "city": "",
            "route": "",
            "seller": "",
            "promoter": "Sin promotor",
            "supervisor": "Sin supervisor",
            "pi": False,
            "piTypes": [],
            "potentialPi": False,
            "annualHl": 0,
            "salesByBusiness": {"CZA": 0, "UNG": 0, "AGUAS": 0, "RB": 0, "OTROS": 0},
            "monthlySalesByBusiness": {"CZA": {}, "UNG": {}, "AGUAS": {}, "RB": {}, "OTROS": {}},
            "categories": [],
            "brands": [],
        }
    return customers[customer_id]


def add_sale(customer, business, period, hl):
    customer["salesByBusiness"][business] = round(customer["salesByBusiness"].get(business, 0) + hl, 2)
    monthly = customer["monthlySalesByBusiness"][business]
    monthly[period] = round(monthly.get(period, 0) + hl, 2)


def sync_drive(folder_url=DRIVE_URL):
    import gdown
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        return gdown.download_folder(url=folder_url, output=str(SOURCE_DIR), quiet=False, use_cookies=False) or []
    except TypeError:
        return gdown.download_folder(url=folder_url, output=str(SOURCE_DIR), quiet=False) or []


def import_data(sync=False, folder_url=DRIVE_URL):
    if sync:
        sync_drive(folder_url)

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    semaforo_file = find_file([r"sem.*activos.*\.xlsx$"])
    clientes_file = find_file([r"plantilla.*clientes.*\.xlsx$"])
    pi_file = find_file([r"pi 2026.*\.xlsb$"])
    edf1_file = find_file([r"edf 1.*\.xlsx$"])
    edf2_file = find_file([r"edf 2.*\.xlsx$"])
    sales_files = sorted([p for p in SOURCE_DIR.iterdir() if p.is_file() and re.match(r"venta.*\.txt$", p.name, re.I)], key=lambda p: p.stat().st_mtime)

    missing = [name for name, file in {
        "semaforo": semaforo_file,
        "clientes": clientes_file,
    }.items() if file is None]
    if missing:
        raise FileNotFoundError(f"Faltan archivos en Drive: {', '.join(missing)}")

    semaforo = read_excel_any(semaforo_file, "Page1")
    clientes = read_excel_any(clientes_file, "Clientes")
    pi_sheets = []
    if pi_file:
        for sheet, pi_type in [("CZA", "CZA"), ("UNG", "UNG"), ("RB", "RB")]:
            try:
                df = read_excel_any(pi_file, sheet)
                df["__pitype"] = pi_type
                pi_sheets.append(df)
            except Exception:
                pass
    pi_rows = pd.concat(pi_sheets, ignore_index=True) if pi_sheets else pd.DataFrame()

    edf_frames = []
    for file in [edf1_file, edf2_file]:
        if file:
            edf_frames.append(read_excel_any(file, "Browser"))
    edf_rows = pd.concat(edf_frames, ignore_index=True) if edf_frames else pd.DataFrame()
    asset_by_serial = {}
    if not edf_rows.empty:
        for row in edf_rows.to_dict("records"):
            serial = first(row, ["numerodeserie", "nroserie", "serie", "serial"])
            asset = first(row, ["numerodeactivo", "nrodeactivo", "activo", "nroactivo"])
            if serial and asset and serial not in asset_by_serial:
                asset_by_serial[serial] = asset

    customers = {}
    for row in clientes.to_dict("records"):
        customer_id = code(first(row, ["cliente", "codcliente", "codigocliente", "nrocliente"]))
        if not customer_id or customer_id == "0":
            continue
        fantasy_name = first(row, ["nombredefantasia", "nombrefantasia", "fantasia"])
        legal_name = first(row, ["razonsocial", "nombre", "cliente"])
        display_name = fantasy_name or legal_name
        customer = ensure_customer(customers, customer_id, display_name)
        customer["name"] = display_name or customer.get("name", "")
        customer["fantasyName"] = fantasy_name or customer.get("fantasyName", "") or display_name
        customer["legalName"] = legal_name or customer.get("legalName", "")
        customer["address"] = " ".join(x for x in [first(row, ["calle", "direccion", "domicilio"]), first(row, ["altura"])] if x)
        customer["city"] = first(row, ["localidad", "codigolocalidad", "ciudad"])
        customer["route"] = first(row, ["ruta", "recorrido"])
        customer["seller"] = first(row, ["vendedor", "preventista"])
        customer["promoter"] = customer["seller"] or "Sin promotor"
        customer["supervisor"] = supervisor_for_promoter(customer["promoter"])

    pi_types = {}
    if not pi_rows.empty:
        for row in pi_rows.to_dict("records"):
            dist_code = code(first(row, ["codigodistribuidor", "coddistribuidor", "codigodirectadistri", "codigodistri"]))
            dist_name = key(first(row, ["distribuidor", "directadistri", "distridirecta"]))
            if dist_code != "70549" and "distribuidoradelvalle" not in dist_name:
                continue
            customer_id = code(first(row, ["codigocliente", "codcliente", "beescodcliente", "cliente"]))
            if customer_id.startswith("70549") and len(customer_id) > 5:
                customer_id = code(customer_id[5:])
            if customer_id and customer_id != "0":
                pi_types.setdefault(customer_id, set()).add(row.get("__pitype", "PI"))
    for customer_id, types in pi_types.items():
        customer = ensure_customer(customers, customer_id)
        customer["pi"] = True
        customer["piTypes"] = sorted(types)

    for sales_file in sales_files:
        with sales_file.open("r", encoding="utf-8", errors="ignore") as fh:
            next(fh, None)
            for line in fh:
                cols = line.rstrip("\n").split("\t")
                if len(cols) <= 40:
                    continue
                customer_id = code(cols[4])
                if not customer_id or customer_id == "0":
                    continue
                customer = ensure_customer(customers, customer_id, clean(cols[5]))
                hl = parse_number(cols[40])
                business = business_from_value(cols[35] if len(cols) > 35 else "", cols[26] if len(cols) > 26 else "", cols[20] if len(cols) > 20 else "")
                period = period_key(cols)
                customer["annualHl"] = round(customer["annualHl"] + hl, 2)
                add_sale(customer, business, period, hl)
                if business == "RB":
                    add_sale(customer, "UNG", period, hl)
                if not customer.get("route") and len(cols) > 8:
                    customer["route"] = clean(cols[8])
                if not customer.get("seller") and len(cols) > 15:
                    customer["seller"] = clean(cols[15])
                    customer["promoter"] = customer["seller"] or "Sin promotor"
                    customer["supervisor"] = supervisor_for_promoter(customer["promoter"])
                category = clean(cols[26]).lower() if len(cols) > 26 else ""
                brand = clean(cols[20]) if len(cols) > 20 else ""
                if category and category not in customer["categories"]:
                    customer["categories"].append(category)
                if brand and brand not in customer["brands"]:
                    customer["brands"].append(brand)

    edfs = []
    seen = {}
    for row in semaforo.to_dict("records"):
        serial = first(row, ["nroserie", "numerodeserie", "serie", "serial"])
        asset = first(row, ["nrodeactivo", "numerodeactivo", "activo", "nroactivo"]) or asset_by_serial.get(serial, "")
        if not serial and not asset:
            continue
        customer_id = code(first(row, ["codcliente", "cliente", "codigocliente", "nrocliente"]))
        if customer_id == "0":
            customer_id = ""
        if customer_id:
            ensure_customer(customers, customer_id, first(row, ["cliente"]))
        unique = serial or asset
        candidate = {
            "id": "",
            "asset": asset,
            "serial": serial,
            "model": guess_model(row),
            "business": business_from_edf(row),
            "status": normalize_status(first(row, ["ubicacion", "origen", "descdeposito", "relaciondeposucursal"]), customer_id),
            "deposit": deposit_from(row),
            "customerId": customer_id or None,
            "source": "Google Drive",
        }
        old = seen.get(unique)
        if not old or (candidate["status"] == "PDV" and old["status"] != "PDV"):
            seen[unique] = candidate
    edfs = [{**edf, "id": f"edf_{i+1}"} for i, edf in enumerate(seen.values())]

    for customer in customers.values():
        customer["promoter"] = customer.get("promoter") or customer.get("seller") or "Sin promotor"
        customer["supervisor"] = supervisor_for_promoter(customer["promoter"])
        if not customer.get("pi") and customer.get("annualHl", 0) >= 1.2:
            customer["potentialPi"] = True

    allocate_repayment(edfs, customers)
    for edf in edfs:
        customer = customers.get(edf.get("customerId") or "")
        edf["customer"] = customer if customer else None

    db = {
        "customers": sorted(customers.values(), key=lambda c: int(c["id"]) if str(c["id"]).isdigit() else 999999999),
        "edfs": edfs,
        "audit": [{
            "action": "IMPORTAR_STREAMLIT_DRIVE",
            "changes": {
                "sourceDir": str(SOURCE_DIR),
                "files": [p.name for p in SOURCE_DIR.iterdir() if p.is_file()],
                "salesFiles": [p.name for p in sales_files],
                "customers": len(customers),
                "edfs": len(edfs),
            },
        }],
    }
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
    return db


def repayment_band(pct, hl):
    if hl <= 0:
        return {"key": "venta0", "label": "Venta 0", "color": "gray"}
    if pct < 25:
        return {"key": "0-25", "label": "0%-25%", "color": "red"}
    if pct < 50:
        return {"key": "25-50", "label": "25%-50%", "color": "orange"}
    if pct < 75:
        return {"key": "50-75", "label": "50%-75%", "color": "yellow"}
    if pct < 100:
        return {"key": "75-99", "label": "75%-99%", "color": "lightgreen"}
    return {"key": "100", "label": "100%+", "color": "green"}


def allocate_repayment(edfs, customers):
    placed = [e for e in edfs if e.get("status") == "PDV" and e.get("customerId")]
    grouped = {}
    for edf in placed:
        grouped.setdefault((edf["customerId"], edf.get("business") or "OTROS"), []).append(edf)
    for group in grouped.values():
        group.sort(key=lambda e: (e.get("asset") or "", e.get("serial") or ""))
    for edf in edfs:
        target = REPAYMENT_TARGETS.get(edf.get("model"), 1.6)
        edf["repayment"] = {"hl": 0, "target": target, "minimum": round(target * 0.75, 3), "pct": 0, "band": repayment_band(0, 0)}
    for (customer_id, business), group in grouped.items():
        customer = customers.get(customer_id)
        if not customer:
            continue
        available = customer["salesByBusiness"].get(business, 0)
        for edf in group:
            target = edf["repayment"]["target"]
            assigned = min(available, target)
            available = max(0, round(available - assigned, 3))
            pct = round((assigned / target) * 100) if target else 0
            edf["repayment"]["hl"] = round(assigned, 3)
            edf["repayment"]["pct"] = pct
            edf["repayment"]["band"] = repayment_band(pct, assigned)
