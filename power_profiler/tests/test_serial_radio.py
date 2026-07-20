import unittest
from unittest.mock import Mock, patch

from radio_power_profiler.profiles import load_profile
from radio_power_profiler.serial_radio import (
    CommandResult,
    RadioCommandError,
    SerialRadio,
)


class FakeSerial:
    def __init__(self):
        self.writes = []
        self.flushes = 0

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        self.flushes += 1


class TimedFakeSerial:
    def __init__(self, data):
        self.data = bytearray(data)

    @property
    def in_waiting(self):
        return len(self.data)

    def read(self, length):
        value = bytes(self.data[:length])
        del self.data[:length]
        return value


class SerialRadioTests(unittest.TestCase):
    def test_configure_retries_transient_modem_error(self):
        radio = SerialRadio.__new__(SerialRadio)
        radio.command = Mock(
            side_effect=(
                RadioCommandError("AT+FIXED=OFF: #ERROR"),
                CommandResult("AT+FIXED=OFF", ("OK",)),
            )
        )
        radio.drain = Mock(return_value=())

        with patch("radio_power_profiler.serial_radio.time.sleep") as sleep:
            results = radio.configure(("AT+FIXED=OFF",))

        self.assertEqual(results, [CommandResult("AT+FIXED=OFF", ("OK",))])
        self.assertEqual(radio.command.call_count, 2)
        radio.drain.assert_called_once_with(wait_s=0.05)
        sleep.assert_called_once_with(0.15)

    def test_configure_reraises_persistent_modem_error(self):
        radio = SerialRadio.__new__(SerialRadio)
        radio.command = Mock(side_effect=RadioCommandError("invalid"))
        radio.drain = Mock(return_value=())

        with (
            patch("radio_power_profiler.serial_radio.time.sleep"),
            self.assertRaisesRegex(RadioCommandError, "invalid"),
        ):
            radio.configure(("AT+BAD",), attempts=2)

        self.assertEqual(radio.command.call_count, 2)

    def test_verified_parameters_retry_full_selection_after_readback_mismatch(self):
        radio = SerialRadio.__new__(SerialRadio)
        radio.configure = Mock(
            side_effect=(
                [CommandResult("AT+AIR6", ("OK",))],
                [
                    CommandResult("AT+POWER2", ("OK",)),
                    CommandResult("AT+AIR6", ("OK",)),
                ],
            )
        )
        radio.command = Mock(
            side_effect=(
                CommandResult(
                    "AT+CFG?",
                    (
                        "TX Power: code 1 (30 dBm)",
                        "Air Data Rate: 0.3kbps",
                        "OK",
                    ),
                ),
                CommandResult(
                    "AT+CFG?",
                    (
                        "TX Power: code 1 (30 dBm)",
                        "Air Data Rate: 19.2kbps",
                        "OK",
                    ),
                ),
            )
        )
        radio.drain = Mock(return_value=())
        profile = load_profile("RADIO_EBYTE_E32_433T33D")

        with patch("radio_power_profiler.serial_radio.time.sleep") as sleep:
            results = radio.configure_profile_parameters(
                profile,
                {"tx_power_dbm": 30, "bit_rate_kbps": 19.2},
                previous_parameters={"tx_power_dbm": 30, "bit_rate_kbps": 4.8},
            )

        self.assertEqual(
            radio.configure.call_args_list[0].args[0],
            ["AT+AIR6"],
        )
        self.assertEqual(
            radio.configure.call_args_list[1].args[0],
            ["AT+POWER2", "AT+AIR6"],
        )
        self.assertEqual(results[-1].command, "AT+CFG?")
        radio.drain.assert_called_once_with(wait_s=0.05)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            [1.0, 0.20, 1.0],
        )

    def test_verified_parameters_retry_readback_without_rewriting_modem(self):
        radio = SerialRadio.__new__(SerialRadio)
        radio.configure = Mock(
            return_value=[CommandResult("AT+POWER2", ("OK",))]
        )
        radio.command = Mock(
            side_effect=(
                RadioCommandError("AT+CFG?: no response"),
                CommandResult(
                    "AT+CFG?",
                    (
                        "TX Power: code 1 (30 dBm)",
                        "Air Data Rate: 19.2kbps",
                        "OK",
                    ),
                ),
            )
        )
        radio.drain = Mock(return_value=())
        profile = load_profile("RADIO_EBYTE_E32_433T33D")

        with patch("radio_power_profiler.serial_radio.time.sleep") as sleep:
            radio.configure_profile_parameters(
                profile,
                {"tx_power_dbm": 30, "bit_rate_kbps": 19.2},
            )

        radio.configure.assert_called_once_with(
            ["AT+POWER2", "AT+AIR6"],
            attempts=1,
        )
        self.assertEqual(radio.command.call_count, 2)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            [1.0, 0.75],
        )

    def test_counts_concatenated_transparent_uart_payloads(self):
        payload = SerialRadio.make_payload(12)
        text = payload.decode("ascii")

        self.assertEqual(
            SerialRadio.count_payload_occurrences(text * 7, payload),
            7,
        )

    def test_bounded_drain_does_not_extend_deadline_when_data_arrives(self):
        radio = SerialRadio.__new__(SerialRadio)
        radio.serial = TimedFakeSerial(b"frame-one\r\nframe-two\r\n")

        with patch(
            "radio_power_profiler.serial_radio.time.monotonic",
            side_effect=(10.0, 10.0, 10.021),
        ):
            lines = radio.drain_bounded(duration_s=0.02)

        self.assertEqual(lines, ("frame-one", "frame-two"))

    def test_bounded_drain_preserves_a_line_split_across_time_windows(self):
        radio = SerialRadio.__new__(SerialRadio)
        radio.serial = TimedFakeSerial(b"partial-")

        with patch(
            "radio_power_profiler.serial_radio.time.monotonic",
            side_effect=(20.0, 20.0, 20.021),
        ):
            first = radio.drain_bounded(duration_s=0.02)

        radio.serial = TimedFakeSerial(b"frame\r\n")
        with patch(
            "radio_power_profiler.serial_radio.time.monotonic",
            side_effect=(30.0, 30.0, 30.021),
        ):
            second = radio.drain_bounded(duration_s=0.02)

        self.assertEqual(first, ())
        self.assertEqual(second, ("partial-frame",))

    def test_fragments_large_cc1101_transfer(self):
        radio = SerialRadio.__new__(SerialRadio)
        radio.serial = FakeSerial()
        profile = load_profile("RADIO_CC1101_V2_868")

        result = radio.send_packet(profile, 512)

        self.assertEqual(result.frame_payload_bytes, (32,) * 16)
        self.assertEqual(result.content_bytes, 480)
        self.assertEqual(len(result.expected_payloads), 16)
        self.assertEqual(radio.serial.writes, [b"AT+TXBURST=512,32\r\n"])

    def test_waits_for_rx_stimulus_burst_with_inter_frame_gap(self):
        radio = SerialRadio.__new__(SerialRadio)
        radio.command = Mock(
            return_value=CommandResult(
                "AT+TXBURST=512,32,5",
                ("TXBURST=512,FRAMES=16,FRAME_MAX=32,GAP_MS=5", "OK"),
            )
        )
        profile = load_profile("RADIO_CC1101_V2_868")

        result = radio.send_packet(
            profile,
            512,
            wait_for_completion=True,
            completion_timeout_s=10.0,
            inter_frame_gap_ms=5.0,
        )

        radio.command.assert_called_once_with(
            "AT+TXBURST=512,32,5",
            timeout_s=10.0,
        )
        self.assertEqual(result.response_lines[-1], "OK")

    def test_parses_continuous_transmission_summary(self):
        radio = SerialRadio.__new__(SerialRadio)
        radio.command = Mock(
            return_value=CommandResult(
                "AT+TXCONT=60000,32,15",
                (
                    "TXCONT=60000,ELAPSED_MS=60012,FRAMES=2143,"
                    "BYTES=68576,FRAME=32,GAP_MS=15",
                    "OK",
                ),
            )
        )

        result = radio.send_continuous(
            duration_ms=60000,
            frame_bytes=32,
            inter_frame_gap_ms=15,
            drain_before=False,
        )

        radio.command.assert_called_once_with(
            "AT+TXCONT=60000,32,15",
            timeout_s=75.0,
            drain_before=False,
        )
        self.assertEqual(result.elapsed_ms, 60012)
        self.assertEqual(result.frames, 2143)
        self.assertEqual(result.payload_bytes, 68576)

    def test_e79_fragments_transfer_and_waits_for_each_modem_reply(self):
        radio = SerialRadio.__new__(SerialRadio)
        radio.command = Mock(
            return_value=CommandResult("AT+SEND=payload", ("OK",))
        )
        profile = load_profile("RADIO_EBYTE_E79_CC1352P")

        result = radio.send_packet(profile, 128)

        self.assertEqual(result.frame_payload_bytes, (64, 64))
        self.assertEqual(result.content_bytes, 128)
        self.assertEqual(radio.command.call_count, 2)
        self.assertTrue(
            all(
                call.kwargs == {"timeout_s": None}
                for call in radio.command.call_args_list
            )
        )
        self.assertEqual(result.response_lines, ("OK", "OK"))

    def test_matches_plain_and_hex_receiver_output(self):
        payload = b"E79-TEST"

        self.assertTrue(SerialRadio.line_contains_payload("E79-TEST", payload))
        self.assertTrue(
            SerialRadio.line_contains_payload(
                "+RXHEX:8,-42,4537392D54455354",
                payload,
            )
        )

    def test_host_paces_continuous_e32_text_frames_by_airtime(self):
        radio = SerialRadio.__new__(SerialRadio)
        radio.serial = FakeSerial()
        profile = load_profile("RADIO_EBYTE_E32_868T30D")

        with (
            patch(
                "radio_power_profiler.serial_radio.time.monotonic",
                side_effect=(0.0, 0.0, 0.0, 1.1, 1.1),
            ),
            patch("radio_power_profiler.serial_radio.time.sleep") as sleep,
        ):
            result = radio.send_continuous(
                duration_ms=1000,
                frame_bytes=32,
                inter_frame_gap_ms=15,
                drain_before=False,
                profile=profile,
                frame_airtime_s=0.5,
            )

        self.assertEqual(result.frames, 1)
        self.assertEqual(
            radio.serial.writes,
            [SerialRadio.make_payload(30) + b"\r\n"],
        )
        sleep.assert_called_once_with(0.515)


if __name__ == "__main__":
    unittest.main()
