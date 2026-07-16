import unittest

from radio_power_profiler.profiles import load_profile
from radio_power_profiler.serial_radio import SerialRadio


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

        self.assertEqual(result.frame_payload_bytes, (64,) * 8)
        self.assertEqual(result.content_bytes, 496)
        self.assertEqual(len(result.expected_payloads), 8)
        self.assertEqual(radio.serial.writes, [b"AT+TXBURST=512,64\r\n"])


if __name__ == "__main__":
    unittest.main()
