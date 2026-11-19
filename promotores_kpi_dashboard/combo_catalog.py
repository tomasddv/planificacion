from io import StringIO
from functools import lru_cache
from pathlib import Path
from time import time
from urllib.request import urlopen

import pandas as pd


CATALOG_URL = "https://raw.githubusercontent.com/tomasddv/caffitastream/main/combo_componentes.csv"
LOCAL_CATALOG = Path(__file__).with_name("combo_componentes.csv")
COLUMNS = {"codigo", "articulo_componente", "descripcion", "marca", "calibre", "division", "unidad_negocio"}


@lru_cache(maxsize=2)
def _load_combo_catalog(refresh_bucket: int) -> pd.DataFrame:
    try:
        with urlopen(CATALOG_URL, timeout=5) as response:
            source = StringIO(response.read().decode("utf-8-sig"))
            catalog = pd.read_csv(source, dtype=str).fillna("")
        if not COLUMNS.issubset(catalog.columns):
            raise ValueError("Catalogo remoto incompleto")
    except (OSError, UnicodeError, ValueError):
        catalog = pd.read_csv(LOCAL_CATALOG, dtype=str).fillna("")
    if not COLUMNS.issubset(catalog.columns):
        raise ValueError("El catalogo de combos no tiene las columnas esperadas")
    return catalog.drop_duplicates(["codigo", "articulo_componente"])


def load_combo_catalog() -> pd.DataFrame:
    return _load_combo_catalog(int(time() // 600))


def component_mask(ventas: pd.DataFrame, selected_codes: set[str]) -> pd.Series:
    if not selected_codes:
        return pd.Series(False, index=ventas.index)
    catalog = load_combo_catalog()
    combo_codes = catalog.loc[catalog["articulo_componente"].isin(selected_codes), "codigo"]
    return ventas["articulo_codigo"].astype(str).isin(combo_codes)


def component_sales() -> pd.DataFrame:
    catalog = load_combo_catalog().rename(columns={
        "articulo_componente": "articulo_codigo",
        "descripcion": "articulo_descripcion",
    }).copy()
    catalog["producto"] = catalog["articulo_descripcion"]
    catalog["marca_unificada"] = catalog["marca"]
    catalog["calibre_unificado"] = catalog["calibre"]
    catalog["sku_search_text"] = catalog[["articulo_descripcion", "marca", "calibre"]].agg(" ".join, axis=1).str.upper()
    return catalog
