import tempfile
import unittest
from pathlib import Path

from promotores_kpi_dashboard.dashboard_data import find_current_daily_sales_file


class DailySalesSourceTest(unittest.TestCase):
    def test_exact_daily_file_wins_over_older_month_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            current = base / "ventadiaria.txt"
            closed = base / "ventadiaria octubre.txt"
            current.write_text("new", encoding="utf-8")
            closed.write_text("old", encoding="utf-8")
            self.assertEqual(find_current_daily_sales_file(base), current)

    def test_falls_back_when_only_dated_daily_file_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            dated = base / "ventadiaria octubre.txt"
            dated.write_text("old", encoding="utf-8")
            self.assertEqual(find_current_daily_sales_file(base), dated)


if __name__ == "__main__":
    unittest.main()
