import csv
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import call, patch

from radio_power_profiler.web_app import (
    AppServer,
    CommandStep,
    JobManager,
    WebConfig,
    build_campaign_steps,
    build_continuous_rx_steps,
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
            manager.vscode_process_id = ""
            manager._session_dir = session
            manager._log_path = session / "session.log"

            with (
                patch("radio_power_profiler.web_app.subprocess.run") as run,
                patch.object(manager, "_open_vscode_uri") as open_uri,
            ):
                run.return_value.returncode = 0
                manager._schedule_codex_callback("campaign")
                manager._callback_thread.join(timeout=3)

            self.assertFalse(manager._callback_thread.is_alive())
            self.assertEqual(run.call_count, 2)
            notification_command = run.call_args_list[0].args[0]
            command = run.call_args_list[1].args[0]
            self.assertEqual(notification_command[:7], command[:7])
            self.assertIn("immediate visible completion notification", notification_command[7])
            self.assertIn("Măsurătorile s-au încheiat", notification_command[7])
            self.assertEqual(
                command[:7],
                [
                    "codex.exe",
                    "exec",
                    "--sandbox",
                    "workspace-write",
                    "resume",
                    "--json",
                    thread_id,
                ],
            )
            self.assertIn(str(session), command[7])
            self.assertIn("/api/ppk-guard/release", command[7])
            self.assertIn("Never stop, kill, or restart", command[7])
            self.assertIn("do not create a temporary repository", command[7])
            self.assertIn("commit/push remains pending", command[7])
            self.assertEqual(
                open_uri.call_args_list,
                [
                    call(f"vscode://openai.chatgpt/local/{thread_id}"),
                    call(f"vscode://openai.chatgpt/local/{thread_id}"),
                ],
            )
            callback_log = (session / "codex_callback.log").read_text(
                encoding="utf-8"
            )
            self.assertIn("visible notification exited with code 0", callback_log)
            self.assertIn("result analysis exited with code 0", callback_log)
            self.assertIn("Displayed immediate completion notification", callback_log)
            self.assertIn("conversation foreground", callback_log)

    def test_codex_callback_test_is_hardware_free_and_uses_a_dedicated_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary), codex_thread_id="thread-id")
            manager.codex_executable = "codex.exe"

            with patch.object(
                manager,
                "_schedule_codex_callback",
                return_value=True,
            ) as schedule:
                status = manager.start_codex_callback_test()

            self.assertEqual(status["state"], "running")
            self.assertEqual(status["kind"], "callback_test")
            self.assertEqual(status["config"], {"hardware_access": False})
            self.assertTrue(status["session_dir"].endswith("_codex_callback_test"))
            _, call_kwargs = schedule.call_args
            self.assertTrue(call_kwargs["update_test_state"])
            self.assertIn("Do not access hardware", call_kwargs["prompt"])

    def test_codex_callback_test_uses_the_immediate_visible_notification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "session"
            session.mkdir()
            manager = JobManager(root, codex_thread_id="thread-id")
            manager.codex_executable = "codex.exe"
            manager.vscode_process_id = ""
            manager._session_dir = session
            manager._log_path = session / "session.log"
            prompt = "Hardware-free callback analysis test."

            with (
                patch("radio_power_profiler.web_app.subprocess.run") as run,
                patch.object(manager, "_open_vscode_uri"),
            ):
                run.return_value.returncode = 0
                manager._schedule_codex_callback(
                    "callback-test",
                    prompt=prompt,
                    update_test_state=True,
                )
                manager._callback_thread.join(timeout=3)

            self.assertFalse(manager._callback_thread.is_alive())
            self.assertEqual(run.call_count, 2)
            self.assertIn(
                "immediate visible completion notification",
                run.call_args_list[0].args[0][7],
            )
            self.assertIn(
                "Testul callback Codex a ajuns în conversație",
                run.call_args_list[0].args[0][7],
            )
            self.assertEqual(run.call_args_list[1].args[0][7], prompt)

    def test_codex_focus_reloads_webviews_before_reopening_the_thread(self):
        thread_id = "12345678-1234-1234-1234-123456789abc"
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary), codex_thread_id=thread_id)
            manager.vscode_process_id = "18572"

            with (
                patch("radio_power_profiler.web_app.subprocess.run") as run,
                patch.object(manager, "_open_vscode_uri") as open_uri,
                patch("radio_power_profiler.web_app.time.sleep"),
            ):
                run.return_value.returncode = 0
                manager._focus_codex_thread()

            uri = f"vscode://openai.chatgpt/local/{thread_id}"
            self.assertEqual(
                open_uri.call_args_list,
                [call(uri), call(uri), call(uri)],
            )
            self.assertEqual(run.call_count, 2)
            reload_command = run.call_args_list[0].args[0]
            self.assertIn("Developer: Reload Webviews", reload_command[-1])
            self.assertIn("Get-Process -Id 18572", reload_command[-1])
            self.assertIn("Get-Process -Name Code", reload_command[-1])
            self.assertIn("MainWindowTitle -like '*ESP32-C3_Radio*'", reload_command[-1])
            self.assertNotIn("Sort-Object StartTime", reload_command[-1])
            activate_command = run.call_args_list[1].args[0]
            self.assertIn("AppActivate($target.Id)", activate_command[-1])

    def test_vscode_uri_uses_internal_cli_with_electron_node_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            install_root = Path(temporary) / "Microsoft VS Code"
            executable = install_root / "Code.exe"
            cli = install_root / "version" / "resources" / "app" / "out" / "cli.js"
            cli.parent.mkdir(parents=True)
            executable.touch()
            cli.touch()
            manager = JobManager(Path(temporary) / "sessions")

            with (
                patch.dict(
                    "radio_power_profiler.web_app.os.environ",
                    {"VSCODE_CWD": str(install_root)},
                    clear=False,
                ),
                patch("radio_power_profiler.web_app.shutil.which", return_value=None),
                patch("radio_power_profiler.web_app.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                manager._open_vscode_uri("vscode://openai.chatgpt/local/thread-id")

            command = run.call_args.args[0]
            self.assertEqual(
                command,
                [
                    str(executable),
                    str(cli),
                    "--open-url",
                    "--",
                    "vscode://openai.chatgpt/local/thread-id",
                ],
            )
            self.assertEqual(
                run.call_args.kwargs["env"]["ELECTRON_RUN_AS_NODE"],
                "1",
            )

    def test_codex_executable_is_rediscovered_after_extension_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            executable = (
                home
                / ".vscode"
                / "extensions"
                / "openai.chatgpt-99.1.2-win32-x64"
                / "bin"
                / "windows-x86_64"
                / "codex.exe"
            )
            executable.parent.mkdir(parents=True)
            executable.touch()
            manager = JobManager(home, codex_thread_id="thread-id")
            manager.codex_executable = str(home / "removed-extension" / "codex.exe")

            with (
                patch("radio_power_profiler.web_app.shutil.which", return_value=None),
                patch("radio_power_profiler.web_app.Path.home", return_value=home),
                patch("radio_power_profiler.web_app.os.name", "nt"),
            ):
                resolved = manager._resolve_codex_executable()

            self.assertEqual(resolved, str(executable))

    def test_quick_and_campaign_plans_cover_expected_work(self):
        config = WebConfig(
            profile_id="RADIO_EBYTE_E32_868T30D",
            measured_port="COM18",
            peer_port="COM17",
            save_raw_campaign=True,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quick = build_quick_steps(config, root / "quick")
            campaign = build_campaign_steps(config, root / "campaign")
            continuous_rx = build_continuous_rx_steps(config, root / "continuous-rx")

        self.assertEqual(len(quick), 4)
        self.assertTrue(all("--save-raw" in step.command for step in quick))
        self.assertTrue(all("--keep-power-on" in step.command for step in quick))
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
        self.assertEqual(len(continuous_rx), 3)
        self.assertTrue(
            all(step.step_id.startswith("continuous_rx_") for step in continuous_rx)
        )
        self.assertTrue(
            all("--keep-power-on" in step.command for step in continuous_rx)
        )
        self.assertTrue(all("--save-raw" in step.command for step in campaign))
        self.assertTrue(all("--keep-power-on" in step.command for step in campaign))

    def test_power_guard_holds_ppk2_open_and_reasserts_on_when_released(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            with patch("radio_power_profiler.ppk.Ppk2Sampler") as sampler_type:
                sampler = sampler_type.return_value

                manager._ensure_current_path_on("COM11", 3300)
                manager._release_current_path_guard()

            sampler_type.assert_called_once_with("COM11", voltage_mv=3300)
            sampler.power_on.assert_called_once_with()
            sampler.close.assert_called_once_with(keep_power_on=True)

    def test_ppk_guard_handoff_api_keeps_the_server_alive(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            server = AppServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            with patch("radio_power_profiler.ppk.Ppk2Sampler") as sampler_type:
                sampler = sampler_type.return_value
                manager._ensure_current_path_on("COM11", 3300)
                thread.start()
                try:
                    host, port = server.server_address
                    release_request = urllib.request.Request(
                        f"http://{host}:{port}/api/ppk-guard/release",
                        data=b"",
                        method="POST",
                    )
                    with urllib.request.urlopen(
                        release_request,
                        timeout=3,
                    ) as response:
                        released = json.loads(response.read().decode("utf-8"))

                    enable_request = urllib.request.Request(
                        f"http://{host}:{port}/api/ppk-guard/enable",
                        data=json.dumps(
                            {"ppk_port": "COM11", "voltage_mv": 3300}
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(
                        enable_request,
                        timeout=3,
                    ) as response:
                        enabled = json.loads(response.read().decode("utf-8"))

                    self.assertFalse(released["guarded"])
                    self.assertTrue(released["was_guarded"])
                    self.assertTrue(enabled["guarded"])
                    self.assertTrue(manager.status()["ppk_guard_active"])
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=3)

            self.assertEqual(sampler_type.call_count, 2)
            self.assertEqual(sampler.power_on.call_count, 2)
            sampler.close.assert_called_once_with(keep_power_on=True)

    def test_lora_profile_uses_sf_and_bandwidth_in_web_campaign(self):
        config = WebConfig(
            profile_id="RADIO_SX1278_SHIELDED",
            measured_port="COM22",
            peer_port="COM21",
            ppk_port="COM11",
            save_raw_campaign=True,
        )
        config.validate()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quick = build_quick_steps(config, root / "quick")
            campaign = build_campaign_steps(config, root / "campaign")

        self.assertEqual(len(quick), 4)
        self.assertIn("spreading_factor=7", quick[0].command)
        self.assertIn("spreading_factor=12", quick[2].command)
        self.assertEqual(
            sum(step.result_kind == "packet" for step in campaign),
            36,
        )
        self.assertEqual(
            sum(step.result_kind == "continuous" for step in campaign),
            4,
        )
        continuous = [step for step in campaign if step.result_kind == "continuous"]
        self.assertTrue(
            all("--powers=-4,10,20" in step.command for step in continuous)
        )
        self.assertTrue(
            all(any(item.startswith("spreading_factor=") for item in step.command) for step in continuous)
        )
        self.assertTrue(
            all("bandwidth_khz=125" in step.command for step in continuous)
        )

    def test_hc12_campaign_uses_datasheet_safe_continuous_gaps(self):
        config = WebConfig(
            profile_id="RADIO_HC12",
            measured_port="COM39",
            peer_port="COM40",
            ppk_port="COM11",
        )
        config.validate()
        with tempfile.TemporaryDirectory() as temporary:
            campaign = build_campaign_steps(config, Path(temporary) / "campaign")

        self.assertEqual(len(campaign), 40)
        continuous_rx = {
            next(item for item in step.command if item.startswith("bit_rate_kbps=")):
            step.command[step.command.index("--gap-ms") + 1]
            for step in campaign
            if step.step_id.startswith("continuous_rx_")
        }
        self.assertEqual(
            continuous_rx,
            {
                "bit_rate_kbps=0.5": "2100",
                "bit_rate_kbps=15": "100",
                "bit_rate_kbps=250": "100",
            },
        )

    def test_nrf24l01_campaign_covers_all_rates_and_controlled_rx(self):
        for profile_id, measured_port, peer_port in (
            ("RADIO_NRF24L01", "COM41", "COM42"),
            ("RADIO_NRF24L01_PA", "COM43", "COM44"),
        ):
            with self.subTest(profile_id=profile_id):
                config = WebConfig(
                    profile_id=profile_id,
                    measured_port=measured_port,
                    peer_port=peer_port,
                    ppk_port="COM11",
                )
                config.validate()
                with tempfile.TemporaryDirectory() as temporary:
                    quick = build_quick_steps(config, Path(temporary) / "quick")
                    campaign = build_campaign_steps(config, Path(temporary) / "campaign")

                self.assertEqual(len(quick), 6)
                high_power_slow = {
                    step.step_id: step
                    for step in quick
                    if step.step_id.endswith("slow_high_power")
                }
                self.assertEqual(
                    set(high_power_slow),
                    {"tx_slow_high_power", "rx_slow_high_power"},
                )
                self.assertTrue(
                    all("tx_power_dbm=0" in step.command for step in high_power_slow.values())
                )
                self.assertTrue(
                    all("data_rate_kbps=250" in step.command for step in high_power_slow.values())
                )
                self.assertTrue(
                    all(
                        "--sizes" in step.command and "32" in step.command
                        for step in high_power_slow.values()
                    )
                )
                self.assertEqual(len(campaign), 40)
                self.assertEqual(
                    sum(step.result_kind == "packet" for step in campaign),
                    36,
                )
                continuous_rx = [
                    step
                    for step in campaign
                    if step.step_id.startswith("continuous_rx_")
                ]
                self.assertEqual(len(continuous_rx), 3)
                self.assertTrue(
                    all(
                        step.command[step.command.index("--gap-ms") + 1] == "15"
                        for step in continuous_rx
                    )
                )

    def test_current_web_defaults_target_e79_pair(self):
        config = WebConfig()
        self.assertEqual(config.profile_id, "RADIO_EBYTE_E79_CC1352P")
        self.assertEqual(config.measured_port, "COM5")
        self.assertEqual(config.peer_port, "COM13")

    def test_e79_quick_check_includes_low_power_metrology_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            quick = build_quick_steps(WebConfig(), Path(temporary) / "quick")

        self.assertEqual(len(quick), 5)
        metrology = next(
            step for step in quick if step.step_id == "tx_low_power_metrology"
        )
        self.assertEqual(metrology.expected_rows, 5)
        self.assertIn("tx_power_dbm=-20", metrology.command)
        self.assertIn("rf_profile=GFSK4K8", metrology.command)
        self.assertEqual(
            metrology.command[metrology.command.index("--repetitions") + 1],
            "5",
        )

    def test_e79_campaign_covers_all_seven_rf_profiles(self):
        config = WebConfig()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = build_campaign_steps(config, root / "campaign")
            continuous_rx = build_continuous_rx_steps(config, root / "continuous-rx")

        self.assertEqual(len(campaign), 176)
        self.assertEqual(
            sum(step.result_kind == "packet" for step in campaign),
            168,
        )
        self.assertEqual(
            sum(step.result_kind == "continuous" for step in campaign),
            8,
        )
        self.assertEqual(len(continuous_rx), 7)
        profile_tokens = {
            item.split("=", 1)[1]
            for step in continuous_rx
            for item in step.command
            if item.startswith("rf_profile=")
        }
        self.assertEqual(
            profile_tokens,
            {
                "GFSK4K8",
                "GFSK50",
                "GFSK200",
                "SLR2K5",
                "SLR5",
                "OOK4K8",
                "IEEE154G50",
            },
        )

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

            continuous_step = CommandStep(
                step_id="continuous",
                label="continuous",
                command=[],
                result_kind="continuous",
                expected_rows=1,
            )
            with (result_dir / "summary.csv").open(
                "w", encoding="utf-8", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {"status": "no_rx_data", "sample_loss_percent": 0}
                )
            continuous_loss = validate_result(continuous_step, result_dir)
            self.assertTrue(continuous_loss["valid"])
            self.assertTrue(continuous_loss["warnings"])

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
                self.assertIn("Test Codex callback", html)
                self.assertIn("currentSession!==s.session_dir", html)
                self.assertIn("/api/status?after=0", html)
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

            def fake_process(command, attempt_log):
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
                    repetitions = int(
                        command[command.index("--repetitions") + 1]
                    )
                    for _ in range(repetitions):
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
            manager._ensure_current_path_on = lambda *_args: None
            manager.start("quick", WebConfig())
            manager._thread.join(timeout=5)
            status = manager.status()

            self.assertEqual(status["state"], "completed")
            self.assertTrue(status["quick_verdict"]["ready_for_campaign"])
            session = Path(status["session_dir"])
            manifest = json.loads(
                (session / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["completed_steps"], 5)
            self.assertTrue(all(step["attempts"] for step in manifest["steps"]))
            self.assertTrue(
                all(
                    Path(step["attempts"][0]["log_file"]).is_file()
                    for step in manifest["steps"]
                )
            )


if __name__ == "__main__":
    unittest.main()
