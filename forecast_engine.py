from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import math
import re
import unicodedata

import numpy as np
import pandas as pd


DAY_NAMES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"]
DAY_COLS = ["lun", "mar", "mie", "jue", "vie", "sab"]
SPANISH_MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _clean_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _code(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
        .str.lstrip("0")
    )


def _num(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip()

    # Los TXT comerciales usan coma decimal. Los enteros funcionan igual.
    comma_mask = text.str.contains(",", regex=False)
    out = pd.Series(np.nan, index=text.index, dtype=float)

    if comma_mask.any():
        out.loc[comma_mask] = pd.to_numeric(
            text.loc[comma_mask]
            .str.replace(".", "", regex=False)
            .str.replace(",", ".", regex=False),
            errors="coerce",
        )

    if (~comma_mask).any():
        out.loc[~comma_mask] = pd.to_numeric(
            text.loc[~comma_mask].str.replace(" ", "", regex=False),
            errors="coerce",
        )
    return out


def parse_spanish_dates(series: pd.Series) -> pd.Series:
    x = series.fillna("").astype(str).str.lower().str.strip()
    parts = x.str.extract(r"^\s*(\d{1,2})-([a-záéíóúñ]{3})-(\d{2,4})\s*$")
    day = pd.to_numeric(parts[0], errors="coerce")
    month = parts[1].map(SPANISH_MONTHS)
    year = pd.to_numeric(parts[2], errors="coerce")
    year = np.where(year < 100, 2000 + year, year)
    return pd.to_datetime(
        pd.DataFrame({"year": year, "month": month, "day": day}),
        errors="coerce",
    )


def load_history_base(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    frame = pd.read_csv(path, compression="infer", dtype={"loc": str, "sku": str})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["sku"] = _code(frame["sku"])
    frame["loc"] = frame["loc"].fillna("").astype(str).str.upper().str.strip()
    frame["bultos"] = pd.to_numeric(frame["bultos"], errors="coerce").fillna(0.0)
    return (
        frame[frame["date"].notna() & frame["loc"].isin(["TRELEW", "MADRYN"])]
        .groupby(["date", "loc", "sku"], as_index=False)["bultos"]
        .sum()
    )


def load_customer_location_map(customer_xlsx: str | Path) -> dict[str, str]:
    df = pd.read_excel(customer_xlsx, header=1, dtype=str)
    # La fila inmediatamente posterior al encabezado contiene los tipos.
    if not df.empty:
        df = df.iloc[1:].copy()

    if "Cliente" not in df.columns or "Descripción Agrupación" not in df.columns:
        raise ValueError("Plantilla clientes sin columnas Cliente / Descripción Agrupación.")

    df["cliente_norm"] = _code(df["Cliente"])
    agr = df["Descripción Agrupación"].fillna("").astype(str).str.upper()

    df["loc"] = np.where(
        agr.str.contains("MADRYN", na=False),
        "MADRYN",
        np.where(agr.str.contains("TRELEW", na=False), "TRELEW", None),
    )
    return dict(zip(df["cliente_norm"], df["loc"]))


def load_current_bultos(
    sales_txt: str | Path,
    customer_xlsx: str | Path,
    wanted_skus: set[str] | None = None,
) -> pd.DataFrame:
    """
    Lee ventadiaria bultos.txt. En ese archivo Cantidades Totales ya está en bultos.
    """
    customer_map = load_customer_location_map(customer_xlsx)
    pieces = []

    wanted = {str(x).lstrip("0") for x in wanted_skus} if wanted_skus else None
    cols = ["Descripción Período", "Cod. Cliente", "Código", "Cantidades Totales"]

    for chunk in pd.read_csv(
        sales_txt,
        sep="\t",
        encoding="latin1",
        usecols=cols,
        dtype=str,
        chunksize=120_000,
        low_memory=False,
    ):
        chunk["sku"] = _code(chunk["Código"])
        if wanted is not None:
            chunk = chunk[chunk["sku"].isin(wanted)].copy()
        if chunk.empty:
            continue

        chunk["date"] = parse_spanish_dates(chunk["Descripción Período"])
        chunk["client"] = _code(chunk["Cod. Cliente"])
        chunk["loc"] = chunk["client"].map(customer_map)
        chunk["bultos"] = _num(chunk["Cantidades Totales"]).fillna(0.0)

        chunk = chunk[
            chunk["date"].notna()
            & chunk["loc"].isin(["TRELEW", "MADRYN"])
        ].copy()
        if not chunk.empty:
            pieces.append(
                chunk.groupby(["date", "loc", "sku"], as_index=False)["bultos"].sum()
            )

    if not pieces:
        return pd.DataFrame(columns=["date", "loc", "sku", "bultos"])

    return (
        pd.concat(pieces, ignore_index=True)
        .groupby(["date", "loc", "sku"], as_index=False)["bultos"]
        .sum()
        .sort_values(["date", "loc", "sku"])
    )


def combine_history(history: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """
    El archivo de venta diaria manda sobre cualquier fecha solapada con la base histórica.
    """
    if history.empty:
        return current.copy()
    if current.empty:
        return history.copy()

    current_keys = current[["date", "loc", "sku"]].drop_duplicates()
    hist = history.merge(
        current_keys.assign(_current=1),
        on=["date", "loc", "sku"],
        how="left",
    )
    hist = hist[hist["_current"].isna()].drop(columns="_current")

    return (
        pd.concat([hist, current], ignore_index=True)
        .groupby(["date", "loc", "sku"], as_index=False)["bultos"]
        .sum()
        .sort_values(["date", "loc", "sku"])
    )


def _normalise_products(products: pd.DataFrame) -> pd.DataFrame:
    frame = products.copy()
    frame["loc"] = frame["ciudad"].fillna("").astype(str).str.upper().str.strip()
    frame["sku"] = _code(frame["codigo"])
    frame["venta_promedio"] = pd.to_numeric(
        frame.get("venta_promedio", 0), errors="coerce"
    ).fillna(0.0)
    frame["stock_total"] = pd.to_numeric(
        frame.get("stock_total", 0), errors="coerce"
    ).fillna(0.0)
    frame["politica_stock_dias"] = pd.to_numeric(
        frame.get("politica_stock_dias", 0), errors="coerce"
    ).fillna(0.0)
    return frame


def _weekday_previous_dates(as_of: date, weekday: int, count: int, floor: date):
    d = as_of - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)

    found = 0
    while d >= floor and found < count:
        yield d
        found += 1
        d -= timedelta(days=7)


def estimate_depletion_date(
    stock: float,
    profile: dict,
    as_of: date,
    max_days: int = 730,
) -> date | None:
    remaining = max(float(stock), 0.0)
    if remaining <= 1e-9:
        return as_of

    d = as_of + timedelta(days=1)
    for _ in range(max_days):
        if d.weekday() < 6:
            remaining -= max(float(profile.get(DAY_COLS[d.weekday()], 0.0)), 0.0)
            if remaining <= 1e-9:
                return d
        d += timedelta(days=1)
    return None


def build_weekday_profiles(
    daily: pd.DataFrame,
    products: pd.DataFrame,
    as_of: date,
    recent_occurrences: int = 2,
) -> pd.DataFrame:
    """
    Perfil de venta distinto para cada día de la semana.

    - Producto maduro: últimas 2 apariciones del mismo día de semana.
    - Producto nuevo: mezcla progresiva con Vta. prom. del archivo de Frescura.
    - El día `as_of` no entra al promedio porque puede estar incompleto.
    """
    products_n = _normalise_products(products)

    history = daily[daily["date"].dt.date <= as_of].copy()
    lookup = {
        (row.loc, row.sku, row.date.date()): float(row.bultos)
        for row in history.itertuples(index=False)
    }

    first_sale = {}
    positive = history[history["bultos"] > 0]
    for (loc, sku), grp in positive.groupby(["loc", "sku"]):
        first_sale[(loc, sku)] = grp["date"].min().date()

    rows = []
    for row in products_n.itertuples(index=False):
        loc = row.loc
        sku = row.sku
        first = first_sale.get((loc, sku))
        age_weeks = ((as_of - first).days / 7.0) if first else 0.0

        if age_weeks >= 8:
            own_weight, confidence = 1.00, "ALTA"
        elif age_weeks >= 4:
            own_weight, confidence = 0.75, "MEDIA"
        elif age_weeks >= 2:
            own_weight, confidence = 0.50, "BAJA"
        else:
            own_weight, confidence = 0.00, "BAJA"

        profile = {}
        for weekday in range(6):
            values = []
            if first:
                for d in _weekday_previous_dates(
                    as_of, weekday, recent_occurrences, first
                ):
                    # Si ese día no hubo venta queda 0: forma parte del patrón real.
                    values.append(max(0.0, lookup.get((loc, sku, d), 0.0)))

            own = float(np.mean(values)) if values else np.nan
            fallback = max(float(row.venta_promedio), 0.0)

            if np.isnan(own):
                estimate = fallback
            else:
                estimate = own_weight * own + (1.0 - own_weight) * fallback

            profile[DAY_COLS[weekday]] = max(estimate, 0.0)

        weekly = sum(profile.values())
        depletion = estimate_depletion_date(
            stock=float(row.stock_total),
            profile=profile,
            as_of=as_of,
        )

        rows.append({
            "loc": loc,
            "sku": sku,
            "description": str(row.descripcion),
            "history_start": first,
            "age_weeks": age_weeks,
            "confidence": confidence,
            "weekly_bultos": weekly,
            "avg_sale_day": weekly / 6.0,
            "stock_total": float(row.stock_total),
            "current_policy_days": float(row.politica_stock_dias),
            "sku_depletion_date": depletion,
            "dynamic_coverage_days": (
                (depletion - as_of).days if depletion is not None else np.nan
            ),
            **profile,
        })

    return pd.DataFrame(rows)


def simulate_fefo(
    lots: pd.DataFrame,
    profiles: pd.DataFrame,
    as_of: date,
    max_extra_days: int = 730,
) -> pd.DataFrame:
    """
    Proyecta venta natural día por día usando FEFO.

    La Política de Stock actual NO gobierna el semáforo.
    El riesgo se calcula contra la fecha real de vencimiento.

    Para cada lote se obtienen:
    - bultos que se venderían naturalmente antes de vencer,
    - bultos que quedarían al vencimiento,
    - fecha hipotética de agotamiento,
    - margen contra vencimiento,
    - incremento de venta necesario.
    """
    if lots.empty or profiles.empty:
        return pd.DataFrame()

    lot_frame = lots.copy()
    lot_frame["loc"] = lot_frame["ciudad"].fillna("").astype(str).str.upper().str.strip()
    lot_frame["sku"] = _code(lot_frame["codigo"])
    lot_frame["stock_lote"] = pd.to_numeric(
        lot_frame["stock_lote"], errors="coerce"
    ).fillna(0.0)
    lot_frame["fecha_vencimiento"] = pd.to_datetime(
        lot_frame["fecha_vencimiento"], errors="coerce"
    )
    lot_frame = lot_frame[
        (lot_frame["stock_lote"] > 0)
        & lot_frame["fecha_vencimiento"].notna()
    ].copy()

    pmap = {
        (r["loc"], r["sku"]): r
        for r in profiles.to_dict("records")
    }

    result = []

    for (loc, sku), group in lot_frame.groupby(["loc", "sku"], sort=False):
        profile = pmap.get((loc, sku))
        if not profile:
            continue

        items = []
        for r in group.sort_values(
            ["fecha_vencimiento", "lote_nro"]
        ).to_dict("records"):
            expiry = pd.Timestamp(r["fecha_vencimiento"]).date()
            stock = float(r["stock_lote"])
            items.append({
                **r,
                "expiry": expiry,
                "remaining": stock,
                "sold_until_expiry": 0.0,
                "risk_at_expiry": None,
                "depletion_date": None,
            })

        # Lotes ya vencidos: todo el stock remanente se considera riesgo.
        for item in items:
            if item["expiry"] < as_of:
                item["risk_at_expiry"] = item["remaining"]

        max_expiry = max(item["expiry"] for item in items)
        simulation_end = max_expiry + timedelta(days=max_extra_days)

        d = as_of + timedelta(days=1)
        while d <= simulation_end:
            demand = (
                max(float(profile.get(DAY_COLS[d.weekday()], 0.0)), 0.0)
                if d.weekday() < 6
                else 0.0
            )

            if demand > 0:
                for item in items:
                    if item["remaining"] <= 1e-9:
                        continue

                    taken = min(item["remaining"], demand)
                    item["remaining"] -= taken
                    demand -= taken

                    if d <= item["expiry"]:
                        item["sold_until_expiry"] += taken

                    if item["remaining"] <= 1e-9 and item["depletion_date"] is None:
                        item["depletion_date"] = d

                    if demand <= 1e-9:
                        break

            # Snapshot al cierre del día de vencimiento.
            for item in items:
                if item["risk_at_expiry"] is None and d == item["expiry"]:
                    item["risk_at_expiry"] = max(item["remaining"], 0.0)

            if all(item["remaining"] <= 1e-9 for item in items) and d >= max_expiry:
                break
            d += timedelta(days=1)

        for item in items:
            if item["risk_at_expiry"] is None:
                item["risk_at_expiry"] = (
                    item["stock_lote"] if item["expiry"] <= as_of else 0.0
                )

            risk = max(float(item["risk_at_expiry"]), 0.0)
            stock = float(item["stock_lote"])
            risk_pct = risk / stock if stock > 0 else 0.0
            sold = max(float(item["sold_until_expiry"]), 0.0)
            depletion = item["depletion_date"]
            days_to_expiry = (item["expiry"] - as_of).days
            margin = (
                (item["expiry"] - depletion).days
                if depletion is not None
                else np.nan
            )

            if risk <= 0.05:
                status = "OK"
            elif days_to_expiry <= 0:
                status = "CRITICO"
            elif risk_pct >= 0.50 or (days_to_expiry <= 30 and risk_pct >= 0.10):
                status = "CRITICO"
            else:
                status = "ACCIONAR"

            if risk <= 0.05:
                lift = 0.0
            elif sold > 1e-9:
                lift = (risk / sold) * 100.0
            else:
                lift = np.inf

            avg_day = max(float(profile.get("avg_sale_day", 0.0)), 0.0)
            extra_days = risk / avg_day if avg_day > 1e-9 else np.inf

            result.append({
                "ciudad": str(item["ciudad"]),
                "codigo": str(item["codigo"]),
                "descripcion": str(item["descripcion"]),
                "lote_nro": int(item["lote_nro"]),
                "stock_lote": stock,
                "fecha_vencimiento": pd.Timestamp(item["fecha_vencimiento"]),
                "dias_para_vencer": days_to_expiry,
                "venta_estimada_hasta_vto": sold,
                "bultos_riesgo": risk,
                "riesgo_pct": risk_pct * 100.0,
                "agotamiento_estimado": (
                    pd.Timestamp(depletion) if depletion is not None else pd.NaT
                ),
                "margen_frescura_dias": margin,
                "incremento_necesario_pct": lift,
                "dias_venta_extra_equiv": extra_days,
                "confianza": profile.get("confidence", "BAJA"),
                "venta_semanal_estimada": float(profile.get("weekly_bultos", 0.0)),
                "dias_stock_dinamicos": profile.get("dynamic_coverage_days", np.nan),
                "politica_actual_dias": profile.get("current_policy_days", np.nan),
                "estado_predictivo": status,
                **{col: float(profile.get(col, 0.0)) for col in DAY_COLS},
            })

    return pd.DataFrame(result)



def load_supermarket_dispatches(
    report_xlsx: str | Path,
    wanted_skus: set[str] | None = None,
) -> pd.DataFrame:
    """
    Lee el ReporteComprobantesDetallado de Cuenta y Orden.

    Regla:
    - Bultos Total positivos = salida a supermercados.
    - Devoluciones negativas reducen la salida neta.
    - Comprobantes anulados se excluyen.
    - Se excluye únicamente el CD de La Anónima:
      cliente 999 / RUTA 25 PQUE.INDUSTRIAL.
    """
    usecols = [
        "Fecha Comprobante",
        "Cliente",
        "Razon Social",
        "Domicilio",
        "Descripcion Agrupacion",
        "Codigo de Articulo",
        "Bultos Total",
        "Anulado",
    ]

    df = pd.read_excel(report_xlsx, sheet_name="Datos", usecols=usecols)

    def norm_code(value):
        if pd.isna(value):
            return ""
        text = str(value).strip()
        if text.endswith(".0"):
            text = text[:-2]
        return text.lstrip("0") or ("0" if text else "")

    df["sku"] = df["Codigo de Articulo"].map(norm_code)
    df["client"] = df["Cliente"].map(norm_code)
    df["date"] = pd.to_datetime(df["Fecha Comprobante"], errors="coerce")
    df["bultos"] = pd.to_numeric(df["Bultos Total"], errors="coerce").fillna(0.0)

    agr = df["Descripcion Agrupacion"].fillna("").astype(str).str.upper()
    df["loc"] = np.where(
        agr.str.contains("MADRYN", na=False),
        "MADRYN",
        np.where(agr.str.contains("TRELEW", na=False), "TRELEW", None),
    )

    reason = df["Razon Social"].fillna("").astype(str).str.upper().str.strip()
    address = df["Domicilio"].fillna("").astype(str).str.upper()

    excluded_cd = (
        reason.eq("S.A. IMPORTADORA Y EXPORTADORA DE LA PATAGONIA")
        & (
            df["client"].eq("999")
            | (
                address.str.contains("RUTA 25", na=False)
                & address.str.contains("PQUE", na=False)
                & address.str.contains("INDUSTRIAL", na=False)
            )
        )
    )

    valid = (
        df["Anulado"].fillna("").astype(str).str.upper().ne("SI")
        & ~excluded_cd
        & df["loc"].isin(["TRELEW", "MADRYN"])
        & df["date"].notna()
    )

    if wanted_skus:
        wanted = {str(x).lstrip("0") for x in wanted_skus}
        valid &= df["sku"].isin(wanted)

    out = df.loc[valid, ["date", "loc", "sku", "bultos"]].copy()

    if out.empty:
        return pd.DataFrame(columns=["date", "loc", "sku", "bultos"])

    return (
        out.groupby(["date", "loc", "sku"], as_index=False)["bultos"]
        .sum()
        .sort_values(["date", "loc", "sku"])
    )


def build_supermarket_weekday_profiles(
    daily_super: pd.DataFrame,
    products: pd.DataFrame,
    as_of: date,
    recent_occurrences: int = 8,
) -> pd.DataFrame:
    """
    Promedio esperado de salida a supermercados por día de semana.
    Usa una ventana más estable que venta normal porque estos despachos
    son más grandes e irregulares.
    """
    products_n = _normalise_products(products)

    hist = daily_super[daily_super["date"].dt.date <= as_of].copy()
    lookup = {
        (r.loc, r.sku, r.date.date()): float(r.bultos)
        for r in hist.itertuples(index=False)
    }

    first = {}
    positive = hist[hist["bultos"] != 0]
    for (loc, sku), grp in positive.groupby(["loc", "sku"]):
        first[(loc, sku)] = grp["date"].min().date()

    rows = []
    for row in products_n.itertuples(index=False):
        loc = row.loc
        sku = row.sku
        floor = first.get((loc, sku))

        profile = {}
        for weekday in range(6):
            values = []
            if floor:
                for d in _weekday_previous_dates(
                    as_of, weekday, recent_occurrences, floor
                ):
                    values.append(lookup.get((loc, sku, d), 0.0))

            # Las devoluciones pueden reducir el despacho neto del día,
            # pero nunca proyectamos una "salida negativa" futura.
            estimate = float(np.mean(values)) if values else 0.0
            profile[DAY_COLS[weekday]] = max(estimate, 0.0)

        rows.append({
            "loc": loc,
            "sku": sku,
            "super_weekly_bultos": sum(profile.values()),
            **{f"super_{k}": v for k, v in profile.items()},
        })

    return pd.DataFrame(rows)


def combine_normal_and_supermarket_profiles(
    normal_profiles: pd.DataFrame,
    supermarket_profiles: pd.DataFrame,
    as_of: date,
) -> pd.DataFrame:
    """
    Mantiene conceptualmente separadas:
    - venta normal del distribuidor
    - salida a supermercados

    pero suma ambas para calcular consumo de stock y riesgo de frescura.
    """
    merged = normal_profiles.merge(
        supermarket_profiles,
        on=["loc", "sku"],
        how="left",
    )

    for col in DAY_COLS:
        merged[f"normal_{col}"] = pd.to_numeric(
            merged[col], errors="coerce"
        ).fillna(0.0)

        merged[f"super_{col}"] = pd.to_numeric(
            merged.get(f"super_{col}", 0.0), errors="coerce"
        ).fillna(0.0)

        merged[col] = merged[f"normal_{col}"] + merged[f"super_{col}"]

    merged["normal_weekly_bultos"] = merged[
        [f"normal_{c}" for c in DAY_COLS]
    ].sum(axis=1)
    merged["super_weekly_bultos"] = merged[
        [f"super_{c}" for c in DAY_COLS]
    ].sum(axis=1)
    merged["weekly_bultos"] = merged[DAY_COLS].sum(axis=1)
    merged["avg_sale_day"] = merged["weekly_bultos"] / 6.0

    depletion_dates = []
    coverage_days = []

    for rec in merged.to_dict("records"):
        depletion = estimate_depletion_date(
            stock=float(rec.get("stock_total", 0.0)),
            profile=rec,
            as_of=as_of,
        )
        depletion_dates.append(depletion)
        coverage_days.append(
            (depletion - as_of).days if depletion is not None else np.nan
        )

    merged["sku_depletion_date"] = depletion_dates
    merged["dynamic_coverage_days"] = coverage_days

    return merged


def forecast_summary(forecast: pd.DataFrame) -> dict:
    if forecast.empty:
        return {
            "risk_bultos": 0.0,
            "risk_lots": 0,
            "critical_lots": 0,
            "action_lots": 0,
        }

    risk = pd.to_numeric(forecast["bultos_riesgo"], errors="coerce").fillna(0.0)
    states = forecast["estado_predictivo"].fillna("").astype(str)
    return {
        "risk_bultos": float(risk.sum()),
        "risk_lots": int((risk > 0.05).sum()),
        "critical_lots": int(states.eq("CRITICO").sum()),
        "action_lots": int(states.eq("ACCIONAR").sum()),
    }
