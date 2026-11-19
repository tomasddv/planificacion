import unittest

import pandas as pd

from promotores_kpi_dashboard.combo_catalog import component_sales, load_combo_catalog
from promotores_kpi_dashboard.dashboard_data import focus_sales


class ComboCatalogTests(unittest.TestCase):
    def test_catalog_has_latest_pure_gold_and_red_bull_combos(self):
        catalog = load_combo_catalog()
        self.assertIn("900503", set(catalog["codigo"]))
        self.assertIn("900505", set(catalog["codigo"]))

    def test_component_focus_matches_combo_without_name_hint(self):
        sales = pd.DataFrame({
            "articulo_codigo": ["900503", "900505", "900999"],
            "marca": ["", "", ""],
            "division": ["", "", ""],
            "calibre_unificado": ["", "", ""],
            "sku_search_text": ["PROMO DESCONOCIDA"] * 3,
        })
        self.assertEqual(focus_sales(sales, "Total CZA")["articulo_codigo"].tolist(), ["900503"])
        self.assertEqual(focus_sales(sales, "Nabs")["articulo_codigo"].tolist(), ["900505"])

    def test_components_have_searchable_descriptions(self):
        components = component_sales()
        self.assertTrue(components.loc[components["codigo"].eq("900503"), "sku_search_text"].str.contains("PURE GOLD").any())


if __name__ == "__main__":
    unittest.main()
