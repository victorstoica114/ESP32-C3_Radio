import csv
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from radio_power_profiler.web_app import (
    AppServer,
    CommandStep,
    JobManager,
    WebConfig,
    build_campaign_steps,
    build_quick_steps,
    validate_result,
)


class WebAppTests(unittest.TestCase):
    def test_codex_callback_resumes_the_captured_thread(self):
        thread_id = "12345678-1234-1234-1234-123456789abc"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "session"
            session.mkdir()
            manager = JobManager(root, codex_thread_id=thread_id)
            manager.codex_executable = "codex.exe"
            manager._session_dir = session
            manager._log_path = session / "session.log"

            with (
                patch("radio_power_profiler.web_app.subprocess.run") as run,
                patch("radio_power_profiler.web_app.os.startfile") as startfile,
            ):
                run.return_value.returncode = 0
                manager._schedule_codex_callback("campaign")
                manager._callback_thread.join(timeout=3)

            self.assertFalse(manager._callback_thread.is_alive())
            command = run.call_args.args[0]
            self.assertEqual(
                command[:5],
                ["codex.exe", "exec", "resume", "--json", thread_id],
            )
            self.assertIn(str(session), command[5])
            startfile.assert_called_once_with(
                f"vscode://openai.chatgpt/local/{thread_id}"
            )
            callback_log = (session / "codex_callback.log").read_text(
                encoding="utf-8"
            )
            self.assertIn("exited with code 0", callback_log)
            self.assertIn("conversation foreground", callback_log)

    def test_quick_and_campaign_plans_cover_expected_work(self):
        config = WebConfig(save_raw_campaign=True)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quick = build_quick_steps(config, root / "quick")
            campaign = build_campaign_steps(config, root / "campaign")

        self.assertEqual(len(quick), 4)
        self.assertTrue(all("--save-raw" in step.command for step in quick))
        self.assertTrue(all(step.expected_rows == 2 for step in quick))
        self.assertTrue(
            all(
                step.command[step.command.index("--repetitions") + 1] == "2"
                for step in quick
            )
        )
        self.assertEqual(len(campaign), 76)
        self.assertEqual(
            sum(step.result_kind == "packet" for step in campaign),
            72,
        )
        self.assertEqual(
            sum(step.result_kind == "continuous" for step in campaign),
            4,
        )
        self.assertTrue(all("--save-raw" in step.command for step in campaign))

    def test_config_rejects_duplicate_ports(self):
        with self.assertRaisesRegex(ValueError, "must be different"):
            WebConfig.from_mapping(
                {
                    "measured_port": "COM18",
                    "peer_port": "COM18",
                    "ppk_port": "COM11",
                }
            )

    def test_result_validation_retries_hardware_failures_but_keeps_loss(self):
        step = CommandStep(
            step_id="packet",
            label="packet",
            command=[],
            result_kind="packet",
            expected_rows=1,
        )
        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary)
            fields = ["status", "sample_loss_percent"]
            with (result_dir / "summary.csv").open(
                "w", encoding="utf-8", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"status": "rx_missing", "sample_loss_percent": 0})
            loss = validate_result(step, result_dir)
            self.assertTrue(loss["valid"])
            self.assertTrue(loss["warnings"])

            with (result_dir / "summary.csv").open(
                "w", encoding="utf-8", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {"status": "no_event_detected", "sample_loss_percent": 0}
                )
            invalid = validate_result(step, result_dir)
            self.assertFalse(invalid["valid"])

    def test_http_ui_and_status_are_available_without_hardware(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            server = AppServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with urllib.request.urlopen(
                    f"http://{host}:{port}/", timeout=3
                ) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("Run quick check", html)
                with urllib.request.urlopen(
                    f"http://{host}:{port}/api/status", timeout=3
                ) as response:
                    status = json.loads(response.read().decode("utf-8"))
                self.assertEqual(status["state"], "idle")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_quick_job_persists_manifest_logs_and_verdict(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = JobManager(root)
            counter = 0

            def fake_process(_command, attempt_log):
                nonlocal counter
                counter += 1
                attempt_log.parent.mkdir(parents=True, exist_ok=True)
                attempt_log.write_text("synthetic hardware log\n", encoding="utf-8")
                result_dir = root / f"synthetic_{counter}"
                result_dir.mkdir()
                fields = [
                    "status",
                    "sample_loss_percent",
                    "event_peak_uA",
                    "tx_peak_uA",
                ]
                with (result_dir / "summary.csv").open(
                    "w", encoding="utf-8", newline=""
                ) as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    for _ in range(2):
                        writer.writerow(
                            {
                                "status": "ok",
                                "sample_loss_percent": 0,
                                "event_peak_uA": 500_000,
                                "tx_peak_uA": 500_000,
                            }
                        )
                return 0, str(result_dir)

            manager._run_process = fake_process
            manager._force_power_off = lambda *_args: None
            manager.start("quick", WebConfig())
            manager._thread.join(timeout=5)
            status = manager.status()

            self.assertEqual(status["state"], "completed")
            self.assertTrue(status["quick_verdict"]["ready_for_campaign"])
            session = Path(status["session_dir"])
            manifest = json.loads(
                (session / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["completed_steps"], 4)
            self.assertTrue(all(step["attempts"] for step in manifest["steps"]))
            self.assertTrue(
                all(
                    Path(step["attempts"][0]["log_file"]).is_file()
                    for step in manifest["steps"]
                )
            )


if __name__ == "__main__":
    unittest.main()
