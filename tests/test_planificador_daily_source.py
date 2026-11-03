import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import planificador_promotores as planner
import gdown


class DailyDriveSourceTests(unittest.TestCase):
    def test_current_daily_file_is_selected_by_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            downloads = []

            def download(*, id, output, **kwargs):
                downloads.append(id)
                Path(output).write_text("venta", encoding="utf-8")

            files = [
                SimpleNamespace(path="ventadiaria octubre.txt", id="old-month"),
                SimpleNamespace(path="ventadiaria.txt", id="new-current"),
            ]
            with (
                patch.object(planner, "PROJECT_ROOT", Path(temp_dir)),
                patch.object(gdown, "download", side_effect=download),
                patch.object(gdown, "download_folder", return_value=files),
            ):
                folder = planner.resolve_google_drive_folder(
                    planner.DEFAULT_DRIVE_URL, force_refresh=True
                )

            self.assertIsNotNone(folder)
            self.assertIn("new-current", downloads)
            self.assertNotIn(planner.PLANIFICADOR_DRIVE_FILE_IDS["ventadiaria.txt"], downloads)
            self.assertEqual((folder / "ventadiaria.txt").read_text(encoding="utf-8"), "venta")


if __name__ == "__main__":
    unittest.main()
