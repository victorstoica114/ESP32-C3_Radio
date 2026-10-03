import json
import struct
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from radio_power_profiler.ppk import Capture
from radio_power_profiler.reference_runner import REFERENCE_POINTS, configure_reference_roles, infer_power_mapping, readback_fields, validate_reference_result, verify_physical_readbacks, wire_qa
from radio_power_profiler.web_app import E280ReferenceConfig, E32ReferenceConfig, E32T33ReferenceConfig, E32868T20ReferenceConfig, E32868T30ReferenceConfig, HC12ReferenceConfig, SX1278ReferenceConfig, ReferenceConfig, build_reference_steps


class ReferenceRunnerTests(unittest.TestCase):
    def test_spi_references_disable_tx_listening_and_enable_packet_ack_debug(self):
        for profile_id in ('RADIO_SX1278_ADAFRUIT_LEVEL_SHIFTER', 'RADIO_EBYTE_E22_SX1268'):
            calls = {'tx': [], 'rx': []}
            radios = {role: SimpleNamespace(command=commands.append) for role, commands in calls.items()}
            configure_reference_roles(radios, REFERENCE_POINTS[profile_id])
            self.assertEqual(calls['tx'], ['AT+DEBUG=ON', 'AT+RX=OFF'])
            self.assertEqual(calls['rx'], ['AT+RX=ON'])
        config = SX1278ReferenceConfig.from_mapping({
            'tx_radio_port': 'COM48', 'rx_radio_port': 'COM49', 'tx_ppk_port': 'COM10',
            'rx_ppk_port': 'COM11', 'tx_voltage_mv': 5000, 'rx_voltage_mv': 5000,
            'tx_identity': 'SX1278 TX', 'rx_identity': 'SX1278 RX', 'interface_label': 'ESP32',
            'voltage_confirmed': True, 'voltage_provenance': 'operator setup'})
        step = build_reference_steps(config, Path('session'))[0]
        self.assertEqual(step.command[step.command.index('--profile-id') + 1], 'RADIO_SX1278_ADAFRUIT_LEVEL_SHIFTER')
        self.assertEqual(step.expected_rows, 5)

    def test_hc12_requires_actual_module_reply_even_when_bridge_says_ok(self):
        point = REFERENCE_POINTS['RADIO_HC12']
        replies = {command: [expected, 'OK'] for command, expected in point['physical_queries'].items()}
        radio = SimpleNamespace(command=lambda command: SimpleNamespace(lines=replies[command]))
        self.assertEqual(verify_physical_readbacks(radio, point), replies)
        for bad_reply in (['OK'], ['OK+RP:-1dBm', 'OK'], ['OK+RP:+20dBm', 'OK+RP:+20dBm', 'OK']):
            replies['AT+RAW=AT+RP'] = bad_reply
            with self.assertRaisesRegex(ValueError, 'Physical module readback mismatch'):
                verify_physical_readbacks(radio, point)
        config = HC12ReferenceConfig.from_mapping({
            'tx_radio_port': 'COM46', 'rx_radio_port': 'COM47', 'tx_ppk_port': 'COM10',
            'rx_ppk_port': 'COM11', 'tx_voltage_mv': 5000, 'rx_voltage_mv': 5000,
            'tx_identity': 'HC-12 TX', 'rx_identity': 'HC-12 RX', 'interface_label': 'ESP32',
            'voltage_confirmed': True, 'voltage_provenance': 'operator setup'})
        step = build_reference_steps(config, Path('session'))[0]
        self.assertEqual(step.command[step.command.index('--profile-id') + 1], 'RADIO_HC12')
        self.assertEqual(step.expected_rows, 5)

    def test_mapping_can_reverse_ports_and_rejects_ambiguous_or_shared_supply(self):
        self.assertEqual(infer_power_mapping({"tx": {"tx": 0, "rx": 7000}, "rx": {"tx": 6500, "rx": 50}}),
                         {"tx": "rx", "rx": "tx"})
        for controls in ({"tx": {"tx": 7000, "rx": 2000}, "rx": {"tx": 0, "rx": 8000}},
                         {"tx": {"tx": 7000, "rx": 0}, "rx": {"tx": 6500, "rx": 0}},
                         {"tx": {"tx": 0, "rx": 0}, "rx": {"tx": 0, "rx": 8000}}):
            with self.assertRaises(ValueError):
                infer_power_mapping(controls)

    def test_wire_integrity_rejects_missing_samples_and_invalid_words_before_analysis(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wire.ppk2.bin"
            cap = Capture([1., 1., 1.], [0, 0, 0], 1, .1, 3)
            for words in ((0, 1 << 18, 3 << 18), (0, 1 << 18, (2 << 18) | (7 << 14)),
                          (0, (1 << 18) | (1 << 17), 2 << 18)):
                path.write_bytes(struct.pack("<III", *words))
                with self.assertRaisesRegex(ValueError, "WIRE integrity"):
                    wire_qa(cap, path, {})

    def test_reference_config_uses_only_agreed_point_and_requires_5v(self):
        payload = {"tx_radio_port": "COM34", "rx_radio_port": "COM35", "tx_ppk_port": "COM10",
                   "rx_ppk_port": "COM11", "tx_voltage_mv": 5000, "rx_voltage_mv": 5000,
                   "tx_identity": "E22 TX", "rx_identity": "E22 RX", "interface_label": "ESP32",
                   "voltage_confirmed": True, "voltage_provenance": "operator setup"}
        config = ReferenceConfig.from_mapping(payload)
        self.assertEqual(config.profile_id, "RADIO_EBYTE_E22_SX1268")
        steps = build_reference_steps(config, Path("session"))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].expected_rows, 5)
        self.assertIn("radio_power_profiler.reference_runner", steps[0].command)
        with self.assertRaises(ValueError):
            ReferenceConfig.from_mapping({**payload, "tx_voltage_mv": 3300})

    def test_incomplete_batches_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "reference.json").write_text(json.dumps({"status": "running", "accepted_batch": None}))
            self.assertFalse(validate_reference_result(root)["valid"])

    def test_e280_uses_transparent_32_bytes_and_sleep_wake_mapping(self):
        profile_id = "RADIO_EBYTE_E280_SX1280"
        point = REFERENCE_POINTS[profile_id]
        self.assertEqual(point["content_bytes"], 30)
        self.assertEqual(point["parameters"], {"tx_power_dbm": 12, "air_rate": "2M"})
        self.assertEqual((point["control_low"], point["control_high"]), ("AT+SLEEP", "AT+WAKE"))
        self.assertFalse(any(command.startswith("AT+RX=") for command in point["setup"]))
        self.assertIsNone(point["tx_success_line"])
        config = E280ReferenceConfig.from_mapping({
            "tx_radio_port": "COM36", "rx_radio_port": "COM37", "tx_ppk_port": "COM10",
            "rx_ppk_port": "COM11", "tx_voltage_mv": 5000, "rx_voltage_mv": 5000,
            "tx_identity": "E280 TX", "rx_identity": "E280 RX", "interface_label": "ESP32",
            "voltage_confirmed": True, "voltage_provenance": "operator setup"})
        self.assertEqual(config.profile_id, profile_id)
        step = build_reference_steps(config, Path("session"))[0]
        self.assertEqual(step.command[step.command.index("--profile-id") + 1], profile_id)
        self.assertEqual(step.step_id, "e280_reference_32b")
        self.assertEqual(step.expected_rows, 5)

    def test_e32_readback_parses_physical_configuration_and_rejects_duplicates(self):
        lines = ["====== E32 CONFIGURATION ======", "Air Data Rate: 19.2kbps",
                 "TX Power: code 0 (20 dBm)", "Runtime mode: NORMAL", "Feat: 14"]
        fields = readback_fields(lines)
        self.assertEqual(fields['Air Data Rate'], '19.2kbps')
        self.assertEqual(fields['TX Power'], 'code 0 (20 dBm)')
        self.assertEqual(fields['Feat'], '14')
        self.assertEqual(readback_fields(['CURR=0.0 mA (0=skip)', 'BW=125.0 kHz'])['BW'], '125.0 kHz')
        with self.assertRaises(ValueError):
            readback_fields(lines + ['Air Data Rate: 4.8kbps'])

    def test_e32_reference_requires_the_t20_condition_and_32_uart_bytes(self):
        profile_id = 'RADIO_EBYTE_E32_433T20D'
        point = REFERENCE_POINTS[profile_id]
        self.assertEqual(point['content_bytes'], 30)
        self.assertEqual(point['parameters'], {'tx_power_dbm': 20, 'bit_rate_kbps': 19.2})
        self.assertEqual(point['expected']['TX Power'], 'code 0 (20 dBm)')
        config = E32ReferenceConfig.from_mapping({
            'tx_radio_port': 'COM38', 'rx_radio_port': 'COM39', 'tx_ppk_port': 'COM10',
            'rx_ppk_port': 'COM11', 'tx_voltage_mv': 5000, 'rx_voltage_mv': 5000,
            'tx_identity': 'E32 TX', 'rx_identity': 'E32 RX', 'interface_label': 'ESP32',
            'voltage_confirmed': True, 'voltage_provenance': 'operator setup'})
        step = build_reference_steps(config, Path('session'))[0]
        self.assertEqual(step.command[step.command.index('--profile-id') + 1], profile_id)
        self.assertEqual(step.expected_rows, 5)

    def test_t33_reference_selects_30_dbm_using_power_index_two(self):
        profile_id = 'RADIO_EBYTE_E32_433T33D'
        point = REFERENCE_POINTS[profile_id]
        self.assertEqual(point['parameters'], {'tx_power_dbm': 30, 'bit_rate_kbps': 19.2})
        self.assertIn('AT+SETRADIO=0,0,23,8,1,6,2,1,1,0,PP', point['setup'])
        self.assertEqual(point['expected']['TX Power'], 'code 1 (30 dBm)')
        self.assertEqual(point['expected']['Feat'], '21')
        config = E32T33ReferenceConfig.from_mapping({
            'tx_radio_port': 'COM40', 'rx_radio_port': 'COM41', 'tx_ppk_port': 'COM10',
            'rx_ppk_port': 'COM11', 'tx_voltage_mv': 5000, 'rx_voltage_mv': 5000,
            'tx_identity': 'E32 T33 TX', 'rx_identity': 'E32 T33 RX', 'interface_label': 'ESP32',
            'voltage_confirmed': True, 'voltage_provenance': 'operator setup'})
        step = build_reference_steps(config, Path('session'))[0]
        self.assertEqual(step.command[step.command.index('--profile-id') + 1], profile_id)
        self.assertEqual(step.expected_rows, 5)

    def test_868_t20_reference_checks_the_band_and_channel_six(self):
        profile_id = 'RADIO_EBYTE_E32_868T20D'
        point = REFERENCE_POINTS[profile_id]
        self.assertEqual(point['frequency_mhz'], 868)
        self.assertEqual(point['expected']['Freq'], '45')
        self.assertEqual(point['expected']['CHAN'], '6')
        self.assertEqual(point['parameters'], {'tx_power_dbm': 20, 'bit_rate_kbps': 19.2})
        self.assertIn('AT+SETRADIO=0,0,6,8,1,6,1,1,1,0,PP', point['setup'])
        config = E32868T20ReferenceConfig.from_mapping({
            'tx_radio_port': 'COM42', 'rx_radio_port': 'COM43', 'tx_ppk_port': 'COM10',
            'rx_ppk_port': 'COM11', 'tx_voltage_mv': 5000, 'rx_voltage_mv': 5000,
            'tx_identity': 'E32 868 T20 TX', 'rx_identity': 'E32 868 T20 RX', 'interface_label': 'ESP32',
            'voltage_confirmed': True, 'voltage_provenance': 'operator setup'})
        step = build_reference_steps(config, Path('session'))[0]
        self.assertEqual(step.command[step.command.index('--profile-id') + 1], profile_id)
        self.assertEqual(step.expected_rows, 5)

    def test_868_t30_uses_power_index_one_with_the_t30_readback(self):
        profile_id = 'RADIO_EBYTE_E32_868T30D'
        point = REFERENCE_POINTS[profile_id]
        self.assertEqual(point['parameters'], {'tx_power_dbm': 30, 'bit_rate_kbps': 19.2})
        self.assertEqual(point['expected']['Freq'], '45')
        self.assertEqual(point['expected']['Feat'], '1E')
        self.assertEqual(point['expected']['TX Power'], 'code 0 (30 dBm)')
        self.assertIn('AT+SETRADIO=0,0,6,8,1,6,1,1,1,0,PP', point['setup'])
        config = E32868T30ReferenceConfig.from_mapping({
            'tx_radio_port': 'COM44', 'rx_radio_port': 'COM45', 'tx_ppk_port': 'COM10',
            'rx_ppk_port': 'COM11', 'tx_voltage_mv': 5000, 'rx_voltage_mv': 5000,
            'tx_identity': 'E32 868 T30 TX', 'rx_identity': 'E32 868 T30 RX', 'interface_label': 'ESP32',
            'voltage_confirmed': True, 'voltage_provenance': 'operator setup'})
        step = build_reference_steps(config, Path('session'))[0]
        self.assertEqual(step.command[step.command.index('--profile-id') + 1], profile_id)
        self.assertEqual(step.expected_rows, 5)
