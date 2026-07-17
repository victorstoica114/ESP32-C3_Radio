import unittest

from radio_power_profiler.planning import build_cases
from radio_power_profiler.profiles import load_profile, override_profile
from radio_power_profiler.runner import _execute_receive_transfer
from radio_power_profiler.serial_radio import SerialRadio, TransmissionResult


class FakeReceiver:
    def __init__(self, lines):
        self.lines = lines
        self.configure_calls = []
        self.drain_calls = []

    def configure(self, commands):
        self.configure_calls.append(tuple(commands))
        return []

    def drain(self, *, wait_s):
        self.drain_calls.append(wait_s)
        return self.lines


class FakeTransmitter:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def send_packet(self, profile, payload_bytes, **kwargs):
        self.calls.append((profile, payload_bytes, kwargs))
        return self.result


class RunnerTests(unittest.TestCase):
    def test_receive_transfer_bounds_rx_window_and_waits_for_sender(self):
        profile = override_profile(
            load_profile("RADIO_CC1101_V2_868"),
            sizes=(128,),
            repetitions=1,
            axis_overrides={
                "tx_power_dbm": (0,),
                "bit_rate_kbps": (38.4,),
            },
        )
        case = build_cases(profile, "rx")[0]
        payload = SerialRadio.make_payload(30)
        lines = (payload.decode("ascii"),) * 4
        result = TransmissionResult(
            content_bytes=120,
            frame_payload_bytes=(32,) * 4,
            expected_payloads=(payload,) * 4,
            response_lines=("TXBURST=128,FRAMES=4,FRAME_MAX=32,GAP_MS=15", "OK"),
        )
        receiver = FakeReceiver(lines)
        transmitter = FakeTransmitter(result)

        actual_result, actual_lines = _execute_receive_transfer(
            receiver,
            transmitter,
            profile,
            case,
        )

        self.assertIs(actual_result, result)
        self.assertEqual(actual_lines, lines)
        self.assertEqual(
            receiver.configure_calls,
            [profile.receiver_enable_commands, profile.post_config_commands],
        )
        self.assertEqual(receiver.drain_calls, [profile.receive.post_receive_s])
        _, payload_bytes, kwargs = transmitter.calls[0]
        self.assertEqual(payload_bytes, 128)
        self.assertTrue(kwargs["wait_for_completion"])
        self.assertEqual(kwargs["inter_frame_gap_ms"], 15.0)


if __name__ == "__main__":
    unittest.main()
