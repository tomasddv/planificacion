import unittest
import pandas as pd
from combos_tracking import calculate, prepare_sales


class ComboTrackingTests(unittest.TestCase):
    def setUp(self):
        self.catalog = pd.DataFrame([
            ['445', 'litro', 'Core', 'Litro', 'g'],
            ['460', 'litro', 'Core', 'Litro', 'g'],
            ['299', 'laton', 'Core', 'Lata', 'g'],
        ], columns=['sku','combo','categoria','descripcion','grupo'])
        self.routes = pd.DataFrame([['1','710','A'],['2','710','B'],['3','999','C'],['4','720','D']], columns=['cliente','ruta','nombre'])
        self.members = pd.DataFrame([['g', str(i)] for i in range(1,5)], columns=['grupo','cliente'])

    def sales(self):
        rows = [
            ['2026-10-01','litro','1',2], ['2026-10-02','litro','1',1],
            ['2026-10-03','litro','1',-3], ['2026-10-04','litro','2',1],
            ['2026-10-04','litro','3',1], ['2026-10-04','litro','99',1],
            ['2026-09-30','litro','4',2], ['2026-10-05','laton','4',1],
        ]
        result = pd.DataFrame(rows, columns=['fecha','combo','cliente','unidades'])
        result['fecha'] = pd.to_datetime(result.fecha)
        result['importe'] = result.unidades * 100
        return result

    def test_returns_month_cutoff_union_and_exclusions(self):
        summary, detail, excluded, _ = calculate(self.sales(), self.routes, self.members, self.catalog, '2026-10-04')
        row = summary.set_index('combo').loc['litro']
        self.assertEqual(row.objetivo, 3)
        self.assertEqual(row.ccc, 1)
        self.assertEqual(row.pendientes, 2)
        self.assertEqual(set(excluded.cliente), {'3','99'})
        before, _, _, _ = calculate(self.sales(), self.routes, self.members, self.catalog, '2026-10-02')
        self.assertEqual(before.set_index('combo').loc['litro','ccc'], 1)

    def test_routes_limit_both_denominator_and_numerator(self):
        summary, detail, _, _ = calculate(self.sales(), self.routes, self.members, self.catalog, '2026-10-05', ['720'])
        self.assertEqual(set(detail.cliente), {'4'})
        self.assertEqual(summary.set_index('combo').loc['laton','ccc'], 1)
        self.assertEqual(summary.set_index('combo').loc['litro','ccc'], 0)

    def test_empty_route_population_is_unavailable_rate(self):
        summary, _, _, _ = calculate(self.sales(), self.routes, self.members, self.catalog, '2026-10-05', ['absent'])
        self.assertTrue(summary.cumplimiento.isna().all())

    def test_original_sales_units_and_invalid_price(self):
        raw = pd.DataFrame({'Cod. Cliente':['1','1'], 'Código':['900445','900460'], 'Descripción Período':['2026-10-04']*2, 'Pr Neto':['1.000,00']*2, 'Importes Netos':['2.000,00','-1.000,00']})
        sales = prepare_sales(raw, pd.to_datetime)
        self.assertEqual(sales.combo.nunique(), 1)
        self.assertEqual(sales.unidades.sum(), 1)
        raw.loc[0,'Pr Neto'] = '0'
        with self.assertRaises(ValueError):
            prepare_sales(raw, pd.to_datetime)


if __name__ == '__main__':
    unittest.main()
