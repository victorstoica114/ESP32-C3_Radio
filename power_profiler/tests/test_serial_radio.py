import unittest
from unittest.mock import Mock

from radio_power_profiler.profiles import load_profile
from radio_power_profiler.serial_radio import CommandResult, SerialRadio


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


if __name__ == "__main__":
    unittest.main()
