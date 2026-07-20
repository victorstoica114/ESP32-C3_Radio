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

    def test_counts_concatenated_transparent_uart_payloads(self):
        payload = SerialRadio.make_payload(12)
        text = payload.decode("ascii")

        self.assertEqual(
            SerialRadio.count_payload_occurrences(text * 7, payload),
            7,
        )

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
