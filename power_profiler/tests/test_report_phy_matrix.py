import csv
import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook
from tools.generate_transfer_report import build_report, write_xlsx


class ReportPhyMatrixTests(unittest.TestCase):
    def test_analysis_failure_cannot_be_published_as_zero_energy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "metadata.json").write_text(json.dumps({}), encoding="utf-8")
            with (path / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["run_id", "status", "analysis_error"])
                writer.writerow(["run_00001", "analysis_review_required", "missing frame"])
            with self.assertRaisesRegex(ValueError, "Analysis review required"):
                build_report(path)

    def test_same_rate_phys_remain_distinct_in_energy_matrix(self):
        metadata = {"profile": {"display_name": "E79", "profile_id": "E79", "transmit": {}}}
        rows = [
            {"tx_power_dbm": 13, "bit_rate_kbps": 50, "rf_profile": phy,
             "payload_bytes": size, "energy_total_mJ_mean": energy}
            for phy, size, energy in (
                ("GFSK50", 32, 1.0), ("IEEE154G50", 32, 2.0),
                ("GFSK50", 64, 3.0), ("IEEE154G50", 64, 4.0),
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xlsx"
            write_xlsx(path, rows, [], metadata)
            workbook = load_workbook(path, read_only=True, data_only=True)
            matrix = list(workbook["energy_matrix_mJ"].values)
            workbook.close()
        self.assertEqual(matrix, [
            ("tx_power_dbm", "bit_rate_kbps", "rf_profile", "32_B", "64_B"),
            (13, 50, "GFSK50", 1, 3), (13, 50, "IEEE154G50", 2, 4),
        ])
