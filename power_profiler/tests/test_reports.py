from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import generate_continuous_report as continuous_report  # noqa: E402
import generate_web_campaign_reports as campaign_reports  # noqa: E402


def _continuous_row(profile: str, power: float) -> dict[str, object]:
    return {
        "measurement_direction": "rx",
        "rf_profile": profile,
        "tx_power_dbm": power,
        "mean_current_uA": 7000.0,
        "mean_power_mW": 23.1,
        "mean_excess_power_mW": 0.0,
        "energy_60s_mJ": 1386.0,
        "frames_received": 100,
        "frames_transmitted": 100.0,
        "frame_loss_percent": 0.0,
    }


class ReportTests(unittest.TestCase):
    def test_continuous_workbook_exports_all_rx_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "continuous.xlsx"
            tx = _continuous_row("SLR2K5", -20.0)
            tx["measurement_direction"] = "tx"
            matching_rx = _continuous_row("SLR2K5", -20.0)
            other_rx = _continuous_row("GFSK200", -20.0)

            continuous_report.write_xlsx(
                path,
                [tx],
                [matching_rx],
                {},
                {},
                all_rx_rows=[matching_rx, other_rx],
            )

            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                self.assertEqual(workbook["continuous_results"].max_row - 1, 3)
                self.assertEqual(workbook["comparison"].max_row - 1, 1)
            finally:
                workbook.close()

    def test_loss_graph_staggers_nearly_identical_rate_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "loss_vs_rate"
            rows = []
            for profile, rate in (("GFSK4K8", 4.8), ("SLR5", 5.0)):
                rows.append(
                    {
                        "bit_rate_kbps": rate,
                        "rf_profile": profile,
                        "tx_power_dbm": -20.0,
                        "frames_transmitted": 100,
                        "frames_received": 100,
                        "frames_lost": 0,
                        "frame_loss_percent": 0.0,
                        "delivery_percent": 100.0,
                        "requested_duration_s": 60.0,
                        "frame_bytes": 64,
                        "inter_frame_gap_ms": 15,
                        "status": "ok",
                        "source_directory": profile,
                    }
                )

            campaign_reports._write_loss_reports(base, rows, "Test module")

            latex = base.with_suffix(".tex").read_text(encoding="utf-8")
            self.assertIn("xtick={4.8}", latex)
            self.assertIn("extra x ticks={5}", latex)
            self.assertIn("(4.8,0)", latex)
            self.assertIn("(5,0)", latex)


if __name__ == "__main__":
    unittest.main()
