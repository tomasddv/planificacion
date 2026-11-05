import ast
import re
import unittest
from pathlib import Path

import pandas as pd


APP_FILE = Path(__file__).resolve().parents[1] / "promotores_kpi_dashboard" / "app.py"
FUNCTIONS = {"sku_269_mask", "sku_selection_mask", "selected_combo_descriptions"}
tree = ast.parse(APP_FILE.read_text(encoding="utf-8"))
module = ast.Module(
    body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS],
    type_ignores=[],
)
namespace = {"pd": pd, "re": re, "COMBO_OPTION_PREFIX": "COMBO/PROMO: "}
exec(compile(module, str(APP_FILE), "exec"), namespace)


class Sku269Tests(unittest.TestCase):
    def test_brahma_quilmes_and_combo_but_not_other_269(self):
        sales = pd.DataFrame([
            ("15624", "BRAHMA CAN 4X6 269", "BRAHMA", "CERVEZAS"),
            ("63068", "QUILMES CLASICA CAN 4X6 269CC", "QUILMES CLASICA", "CERVEZAS"),
            ("900473", "COMBO BRAH&QUIL 269 CC SUR", "", ""),
            ("31073", "PDT TONICA CAN 4X6 269CC", "PASO DE LOS TOROS", "GASEOSAS"),
            ("31434", "BRAHMA CAN 4X4 710CC", "BRAHMA", "CERVEZAS"),
            ("900460", "COMBO LITRO BRAHMA Y QUILMES", "", ""),
        ], columns=["articulo_codigo", "articulo_descripcion", "marca", "division"])
        sales["producto"] = sales["articulo_descripcion"]
        sales["marca_unificada"] = sales["marca"]
        sales["sku_search_text"] = sales["articulo_descripcion"]
        expected = [True, True, True, False, False, False]
        self.assertEqual(namespace["sku_269_mask"](sales).tolist(), expected)
        self.assertEqual(namespace["sku_selection_mask"](sales, ["269 TODOS"]).tolist(), expected)


if __name__ == "__main__":
    unittest.main()
