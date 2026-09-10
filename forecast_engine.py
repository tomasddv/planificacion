from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
import os
import numpy as np
import pandas as pd


SPANISH_MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}

SALES_USECOLS = [2, 4, 17, 18, 39, 40, 42]


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False),
        errors="coerce",
    )


def _sku(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.lstrip("0")
    )


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


def load_customer_location_map(customer_xlsx: str | Path) -> dict[str, str]:
    """
    Mapea cliente -> TRELEW/MADRYN usando 'Descripción Agrupación'
    de la Plantilla Clientes.
    """
    df = pd.read_excel(customer_xlsx, header=1, dtype=str)
    # La primera fila posterior al header contiene tipos de datos.
    df = df.iloc[1:].copy()

    df["Cliente"] = _sku(df["Cliente"])
    agr = df["Descripción Agrupación"].fillna("").str.upper()

    def classify(value: str):
        if "MADRYN" in value:
            return "MADRYN"
        if "TRELEW" in value:
            return "TRELEW"
        return None

    df["loc"] = agr.map(classify)
    return dict(zip(df["Cliente"], df["loc"]))


def load_freshness(path: str | Path, location: str) -> pd.DataFrame:
    df = pd.read_excel(path, header=1)
    df = df.copy()
    df["location"] = location.upper()
    df["sku"] = pd.to_numeric(df["Cód"], errors="coerce")
    df = df[df["sku"].notna()].copy()
    df["sku"] = df["sku"].astype(int).astype(str)
    return df


def freshness_skus(*freshness_frames: pd.DataFrame) -> set[str]:
    result = set()
    for df in freshness_frames:
        result.update(df["sku"].astype(str).tolist())
    return result


def build_daily_sales_bultos(
    sales_paths: list[str | Path],
    customer_xlsx: str | Path,
    wanted_skus: set[str],
    annual_filename: str = "venta anual.txt",
    annual_cutoff: date = date(2026, 5, 31),
    chunksize: int = 120_000,
) -> tuple[pd.DataFrame, dict[str, float], dict]:
    """
    Convierte la venta histórica a bultos y la agrega por:
        fecha + depósito + SKU

    Conversión principal:
        bultos = Importes Netos / Pr Neto

    Si Pr Neto == 0:
        usa HL / factor_HL_por_bulto aprendido de operaciones normales del SKU.
    """
    customer_map = load_customer_location_map(customer_xlsx)

    daily_direct = defaultdict(float)
    daily_zero_hl = defaultdict(float)
    factor_samples = defaultdict(list)
    diagnostics = {}

    for raw_path in sales_paths:
        path = Path(raw_path)
        rows_total = rows_sku = rows_mapped = 0
        min_date = max_date = None

        for chunk in pd.read_csv(
            path,
            sep="\t",
            encoding="latin1",
            usecols=SALES_USECOLS,
            dtype=str,
            chunksize=chunksize,
            low_memory=False,
        ):
            rows_total += len(chunk)
            chunk["sku"] = _sku(chunk["Código"])
            chunk = chunk[chunk["sku"].isin(wanted_skus)].copy()
            rows_sku += len(chunk)
            if chunk.empty:
                continue

            chunk["date"] = parse_spanish_dates(chunk["Descripción Período"])

            if path.name.lower() == annual_filename.lower():
                chunk = chunk[chunk["date"].dt.date <= annual_cutoff].copy()

            if chunk.empty:
                continue

            chunk["client"] = _sku(chunk["Cod. Cliente"])
            chunk["loc"] = chunk["client"].map(customer_map)
            chunk = chunk[
                chunk["loc"].isin(["TRELEW", "MADRYN"]) & chunk["date"].notna()
            ].copy()
            rows_mapped += len(chunk)

            if chunk.empty:
                continue

            cmin = chunk["date"].min()
            cmax = chunk["date"].max()
            min_date = cmin if min_date is None or cmin < min_date else min_date
            max_date = cmax if max_date is None or cmax > max_date else max_date

            chunk["prnet"] = _num(chunk["Pr Neto"])
            chunk["hl"] = _num(chunk["Cantidades Totales"]).fillna(0.0)
            chunk["neto"] = _num(chunk["Importes Netos"]).fillna(0.0)

            normal = chunk[chunk["prnet"].abs() > 1e-12].copy()
            normal["bultos"] = normal["neto"] / normal["prnet"]

            for key, value in normal.groupby(
                ["date", "loc", "sku"], sort=False
            )["bultos"].sum().items():
                daily_direct[key] += float(value)

            # Aprende HL por bulto de las filas donde ambas magnitudes son válidas.
            valid = normal[
                (normal["bultos"].abs() > 1e-9) &
                (normal["hl"].abs() > 1e-9)
            ].copy()
            valid["factor"] = valid["hl"] / valid["bultos"]

            for sku, values in valid.groupby("sku")["factor"]:
                current = factor_samples[sku]
                if len(current) < 1000:
                    vals = (
                        values.replace([np.inf, -np.inf], np.nan)
                        .dropna()
                        .astype(float)
                        .tolist()
                    )
                    current.extend(vals[: 1000 - len(current)])

            zero_price = chunk[chunk["prnet"].abs() <= 1e-12]
            for key, value in zero_price.groupby(
                ["date", "loc", "sku"], sort=False
            )["hl"].sum().items():
                daily_zero_hl[key] += float(value)

        diagnostics[path.name] = {
            "rows_total": rows_total,
            "rows_current_skus": rows_sku,
            "rows_location_mapped": rows_mapped,
            "min_date": str(min_date.date()) if min_date is not None else None,
            "max_date": str(max_date.date()) if max_date is not None else None,
        }

    factors = {}
    for sku, values in factor_samples.items():
        arr = np.asarray(values, dtype=float)
        arr = arr[np.isfinite(arr) & (np.abs(arr) > 1e-12)]
        if len(arr):
            factors[sku] = float(np.median(arr))

    rows = []
    all_keys = set(daily_direct) | set(daily_zero_hl)

    for key in all_keys:
        d, loc, sku = key
        bultos = daily_direct.get(key, 0.0)
        zero_hl = daily_zero_hl.get(key, 0.0)

        if abs(zero_hl) > 1e-12:
            factor = factors.get(sku)
            if factor:
                bultos += zero_hl / factor

        rows.append((d, loc, sku, bultos))

    daily = pd.DataFrame(rows, columns=["date", "loc", "sku", "bultos"])
    if not daily.empty:
        daily = (
            daily.groupby(["date", "loc", "sku"], as_index=False)["bultos"]
            .sum()
            .sort_values(["loc", "sku", "date"])
        )

    diagnostics["conversion"] = {
        "sku_with_factor": len(factors),
        "sku_requested": len(wanted_skus),
        "daily_rows": len(daily),
    }
    return daily, factors, diagnostics


def _freshness_lookup(freshness_frames: list[pd.DataFrame]) -> dict:
    result = {}
    for df in freshness_frames:
        for _, row in df.iterrows():
            key = (row["location"], row["sku"])
            result[key] = {
                "description": str(row["Descripción"]),
                "vta_prom": float(row["Vta. prom."]) if pd.notna(row["Vta. prom."]) else 0.0,
                "policy": int(row["Política de Stock (Días)"])
                if pd.notna(row["Política de Stock (Días)"]) else 0,
                "stock_total": float(row["Stock total"])
                if pd.notna(row["Stock total"]) else 0.0,
            }
    return result


def build_weekday_profiles(
    daily: pd.DataFrame,
    freshness_frames: list[pd.DataFrame],
    as_of: date,
    recent_occurrences: int = 2,
) -> pd.DataFrame:
    """
    Estima bultos para lunes..sábado.

    Regla base validada por backtesting:
      promedio de las últimas 2 apariciones del mismo día de semana.

    SKU recientes:
      8+ semanas: 100% historial propio
      4-8 semanas: 75% historial + 25% Vta. prom.
      2-4 semanas: 50% historial + 50% Vta. prom.
      <2 semanas: Vta. prom. como fallback inicial.
    """
    lookup = {
        (r.loc, r.sku, r.date.date()): float(r.bultos)
        for r in daily.itertuples(index=False)
        if r.date.date() <= as_of
    }

    first_sale = {}
    positive = daily[(daily["bultos"] > 0) & (daily["date"].dt.date <= as_of)]
    for (loc, sku), group in positive.groupby(["loc", "sku"]):
        first_sale[(loc, sku)] = group["date"].min().date()

    fresh_lookup = _freshness_lookup(freshness_frames)
    labels = ["lun", "mar", "mie", "jue", "vie", "sab"]
    output = []

    for (loc, sku), meta in fresh_lookup.items():
        first = first_sale.get((loc, sku))
        age_weeks = ((as_of - first).days / 7) if first else 0.0

        if age_weeks >= 8:
            blend = 1.0
            confidence = "ALTA"
        elif age_weeks >= 4:
            blend = 0.75
            confidence = "MEDIA"
        elif age_weeks >= 2:
            blend = 0.50
            confidence = "BAJA"
        else:
            blend = 0.0
            confidence = "BAJA"

        profile = {}
        for weekday in range(6):
            values = []
            d = as_of
            while d.weekday() != weekday:
                d -= timedelta(days=1)

            # No usamos el día actual: puede estar incompleto.
            if d >= as_of:
                d -= timedelta(days=7)

            while (
                len(values) < recent_occurrences
                and first is not None
                and d >= first
            ):
                values.append(max(0.0, lookup.get((loc, sku, d), 0.0)))
                d -= timedelta(days=7)

            own = float(np.mean(values)) if values else np.nan
            fallback = meta["vta_prom"]

            if np.isnan(own):
                estimate = fallback
            else:
                estimate = blend * own + (1.0 - blend) * fallback

            profile[labels[weekday]] = max(0.0, estimate)

        output.append({
            "loc": loc,
            "sku": sku,
            "description": meta["description"],
            "history_start": first,
            "age_weeks": age_weeks,
            "confidence": confidence,
            **profile,
        })

    return pd.DataFrame(output)


def extract_lots(freshness_frames: list[pd.DataFrame]) -> pd.DataFrame:
    blocks = [
        ("Stock lote", "Fecha venc."),
        ("Stock lote.1", "Fecha venc..1"),
        ("Stock lote.2", "Fecha venc..2"),
    ]
    rows = []

    for df in freshness_frames:
        for _, row in df.iterrows():
            policy = int(row["Política de Stock (Días)"]) if pd.notna(
                row["Política de Stock (Días)"]
            ) else 0

            for lot_number, (stock_col, date_col) in enumerate(blocks, 1):
                if stock_col not in df.columns or date_col not in df.columns:
                    continue

                stock = row.get(stock_col)
                expiry = row.get(date_col)

                if pd.isna(stock) or pd.isna(expiry):
                    continue

                stock = float(stock)
                if stock <= 0:
                    continue

                expiry_date = pd.to_datetime(expiry).date()
                block_date = expiry_date - timedelta(days=policy)

                rows.append({
                    "loc": row["location"],
                    "sku": row["sku"],
                    "description": str(row["Descripción"]),
                    "lot_number": lot_number,
                    "stock_lot": stock,
                    "stock_total": float(row["Stock total"])
                    if pd.notna(row["Stock total"]) else 0.0,
                    "expiry": expiry_date,
                    "policy_days": policy,
                    "block_date": block_date,
                })

    return pd.DataFrame(rows)


def simulate_fefo(
    lots: pd.DataFrame,
    profiles: pd.DataFrame,
    as_of: date,
    action_horizon_days: int = 60,
) -> pd.DataFrame:
    """
    Simula salida FEFO día por día.
    La fecha límite operativa es:
        vencimiento - Política de Stock (Días)

    El lote puede vender hasta el propio día de bloqueo inclusive.
    """
    profile_lookup = {}
    for row in profiles.to_dict("records"):
        profile_lookup[(row["loc"], row["sku"])] = row

    results = []
    day_labels = ["lun", "mar", "mie", "jue", "vie", "sab"]

    for (loc, sku), group in lots.groupby(["loc", "sku"]):
        profile = profile_lookup.get((loc, sku))
        if profile is None:
            continue

        items = group.sort_values(
            ["block_date", "expiry", "lot_number"]
        ).to_dict("records")

        for item in items:
            item["remaining"] = item["stock_lot"]
            item["forecast_sold"] = 0.0
            item["risk_bultos"] = 0.0
            item["closed"] = False

        max_block = max(item["block_date"] for item in items)
        current = as_of + timedelta(days=1)

        while current <= max_block:
            if current.weekday() < 6:
                demand = float(profile[day_labels[current.weekday()]])
            else:
                demand = 0.0

            if demand > 0:
                for item in items:
                    if item["closed"] or item["remaining"] <= 1e-12:
                        continue
                    if current > item["block_date"]:
                        continue

                    taken = min(item["remaining"], demand)
                    item["remaining"] -= taken
                    item["forecast_sold"] += taken
                    demand -= taken

                    if demand <= 1e-12:
                        break

            # Al terminar el día de bloqueo, el remanente queda en riesgo.
            for item in items:
                if not item["closed"] and current == item["block_date"]:
                    item["risk_bultos"] = max(0.0, item["remaining"])
                    item["closed"] = True

            current += timedelta(days=1)

        for item in items:
            risk_pct = (
                item["risk_bultos"] / item["stock_lot"]
                if item["stock_lot"] else 0.0
            )
            days_to_block = (item["block_date"] - as_of).days

            if item["risk_bultos"] <= 0.01:
                action = "OK"
            elif days_to_block <= 0:
                action = "CRITICO"
            elif days_to_block <= action_horizon_days:
                action = "CRITICO" if risk_pct >= 0.25 else "ACCIONAR"
            else:
                # Evita disparar una acción prematura con un horizonte largo.
                action = "MONITOREAR"

            results.append({
                "loc": loc,
                "sku": sku,
                "description": item["description"],
                "lot_number": item["lot_number"],
                "stock_lot": item["stock_lot"],
                "expiry": item["expiry"],
                "block_date": item["block_date"],
                "days_to_block": days_to_block,
                "forecast_sold_before_block": item["forecast_sold"],
                "risk_bultos": item["risk_bultos"],
                "risk_pct": risk_pct,
                "extra_bultos_needed": item["risk_bultos"],
                "confidence": profile["confidence"],
                "action": action,
                **{label: profile[label] for label in day_labels},
            })

    return pd.DataFrame(results)


def run_forecast(
    sales_paths: list[str | Path],
    customer_xlsx: str | Path,
    freshness_trelew: str | Path,
    freshness_madryn: str | Path,
    as_of: date,
    recent_occurrences: int = 2,
):
    trelew = load_freshness(freshness_trelew, "TRELEW")
    madryn = load_freshness(freshness_madryn, "MADRYN")
    skus = freshness_skus(trelew, madryn)

    daily, factors, diagnostics = build_daily_sales_bultos(
        sales_paths=sales_paths,
        customer_xlsx=customer_xlsx,
        wanted_skus=skus,
    )

    profiles = build_weekday_profiles(
        daily=daily,
        freshness_frames=[trelew, madryn],
        as_of=as_of,
        recent_occurrences=recent_occurrences,
    )

    lots = extract_lots([trelew, madryn])
    forecast = simulate_fefo(lots, profiles, as_of=as_of)

    return {
        "daily": daily,
        "factors": factors,
        "profiles": profiles,
        "lots": lots,
        "forecast": forecast,
        "diagnostics": diagnostics,
    }
