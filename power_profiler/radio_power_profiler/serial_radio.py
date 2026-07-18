from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Iterable

from .models import Profile


class RadioCommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class TransmissionResult:
    content_bytes: int
    frame_payload_bytes: tuple[int, ...]
    expected_payloads: tuple[bytes, ...]
    response_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContinuousTransmissionResult:
    requested_duration_ms: int
    elapsed_ms: int
    frames: int
    payload_bytes: int
    frame_bytes: int
    inter_frame_gap_ms: int
    response_lines: tuple[str, ...]


class SerialRadio:
    def __init__(
        self,
        port: str,
        baudrate: int,
        *,
        command_timeout_s: float = 8.0,
        open_wait_s: float = 1.5,
    ):
        import serial

        self.port = port
        self.baudrate = baudrate
        self.command_timeout_s = command_timeout_s
        self.serial = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=0.03,
            write_timeout=5.0,
        )
        # Opening an ESP32-C3 USB CDC port can reset the controller.  Wait for
        # its AT firmware to finish setup before discarding the boot banner;
        # otherwise the first command can be interleaved with that banner and
        # its standalone "OK" becomes impossible to recognize.
        time.sleep(open_wait_s)
        self.drain(wait_s=0.25)
        self._synchronize_after_open()

    def _synchronize_after_open(self) -> None:
        last_error: RadioCommandError | None = None
        for _ in range(3):
            try:
                self.command("AT", timeout_s=3.0)
                return
            except RadioCommandError as exc:
                # A command written during ESP32 boot can be answered while
                # the boot banner is still being printed.  Let setup finish,
                # discard that mixed output, and retry the harmless probe.
                last_error = exc
                time.sleep(0.50)
                self.drain(wait_s=0.25)
        self.close()
        raise RadioCommandError(
            f"Unable to synchronize AT firmware on {self.port}: {last_error}"
        )

    def close(self) -> None:
        if self.serial.is_open:
            self.serial.close()

    def __enter__(self) -> "SerialRadio":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _write_line(self, text: str) -> None:
        self.serial.write(text.encode("ascii") + b"\r\n")
        self.serial.flush()

    def drain(self, *, wait_s: float = 0.05) -> tuple[str, ...]:
        deadline = time.monotonic() + wait_s
        data = bytearray()
        while time.monotonic() < deadline:
            waiting = self.serial.in_waiting
            if waiting:
                data.extend(self.serial.read(waiting))
                deadline = time.monotonic() + wait_s
            else:
                time.sleep(0.005)
        text = data.decode("utf-8", errors="replace")
        return tuple(line.strip() for line in text.splitlines() if line.strip())

    def command(
        self,
        text: str,
        *,
        timeout_s: float | None = None,
        drain_before: bool = True,
    ) -> CommandResult:
        if drain_before:
            self.drain(wait_s=0.02)
        self._write_line(text)
        deadline = time.monotonic() + (timeout_s or self.command_timeout_s)
        lines: list[str] = []
        partial = bytearray()

        while time.monotonic() < deadline:
            waiting = self.serial.in_waiting
            if waiting:
                partial.extend(self.serial.read(waiting))
                while b"\n" in partial:
                    raw, _, remainder = partial.partition(b"\n")
                    partial = bytearray(remainder)
                    line = raw.decode("utf-8", errors="replace").strip("\x00\r ")
                    if not line:
                        continue
                    lines.append(line)
                    upper = line.upper()
                    if upper == "OK":
                        return CommandResult(text, tuple(lines))
                    if upper == "#ERROR" or upper.startswith("#ERROR:"):
                        raise RadioCommandError(f"{text}: {line}")
            else:
                time.sleep(0.005)

        if partial:
            lines.append(
                partial.decode("utf-8", errors="replace").strip("\x00\r ")
            )
        rendered = " | ".join(lines) if lines else "no response"
        raise RadioCommandError(f"Timeout waiting for OK after {text!r}: {rendered}")

    def send_continuous(
        self,
        *,
        duration_ms: int,
        frame_bytes: int,
        inter_frame_gap_ms: int,
        drain_before: bool = True,
        profile: Profile | None = None,
        frame_airtime_s: float = 0.0,
    ) -> ContinuousTransmissionResult:
        if not 1000 <= duration_ms <= 600000:
            raise ValueError("Continuous duration must be between 1000 and 600000 ms")
        if not 3 <= frame_bytes <= 64:
            raise ValueError("Continuous frame size must be between 3 and 64 bytes")
        if not 0 <= inter_frame_gap_ms <= 1000:
            raise ValueError("Continuous inter-frame gap must be between 0 and 1000 ms")
        if frame_airtime_s < 0:
            raise ValueError("Continuous frame airtime cannot be negative")

        if profile is not None and profile.transmit.mode != "burst_command":
            if frame_bytes > (
                profile.transmit.frame_payload_bytes
                or profile.transmit.max_payload_bytes
            ):
                raise ValueError(
                    f"Continuous frame size exceeds the physical limit for "
                    f"{profile.profile_id}"
                )
            if profile.transmit.mode not in {
                "hex_command",
                "text_command",
                "text_line",
            }:
                raise ValueError(
                    f"Profile {profile.profile_id} does not support host-driven "
                    "continuous transmission"
                )
            content_bytes = frame_bytes - profile.transmit.line_overhead_bytes
            if content_bytes < 1:
                raise ValueError("Continuous frame contains no payload bytes")
            payload = self.make_payload(content_bytes)
            tx_command = None
            if profile.transmit.mode != "text_line":
                if not profile.transmit.command:
                    raise ValueError(
                        f"{profile.transmit.mode} requires a command template"
                    )
                tx_command = profile.transmit.command.format(
                    payload_hex=payload.hex().upper(),
                    payload_text=payload.decode("ascii"),
                )
            if drain_before:
                self.drain(wait_s=0.02)
            start = time.monotonic()
            deadline = start + duration_ms / 1000.0
            frames = 0
            serial_errors = 0
            while time.monotonic() < deadline:
                frames += 1
                if profile.transmit.mode == "text_line":
                    self.serial.write(payload + b"\r\n")
                    self.serial.flush()
                else:
                    try:
                        self.command(
                            str(tx_command),
                            timeout_s=0.75,
                            drain_before=False,
                        )
                    except RadioCommandError:
                        # The validated E79 bridge runs its internal UART at
                        # 1 Mbaud and can occasionally lose the modem's short
                        # OK reply during long stress runs. The RF command may
                        # still have been executed, so keep the attempted frame
                        # in the offered-traffic count, clear the line, and
                        # continue.
                        serial_errors += 1
                        self.drain(wait_s=0.05)
                pacing_s = inter_frame_gap_ms / 1000.0
                if profile.transmit.mode == "text_line":
                    pacing_s += frame_airtime_s
                if pacing_s:
                    remaining_s = deadline - time.monotonic()
                    if remaining_s > 0:
                        time.sleep(min(pacing_s, remaining_s))
            elapsed_ms = int(round((time.monotonic() - start) * 1000.0))
            summary = (
                f"TXCONT={duration_ms},ELAPSED_MS={elapsed_ms},FRAMES={frames},"
                f"BYTES={frames * frame_bytes},FRAME={frame_bytes},"
                f"GAP_MS={inter_frame_gap_ms}"
            )
            return ContinuousTransmissionResult(
                requested_duration_ms=duration_ms,
                elapsed_ms=elapsed_ms,
                frames=frames,
                payload_bytes=frames * frame_bytes,
                frame_bytes=frame_bytes,
                inter_frame_gap_ms=inter_frame_gap_ms,
                response_lines=(summary, f"SERIAL_ERRORS={serial_errors}"),
            )

        command = f"AT+TXCONT={duration_ms},{frame_bytes},{inter_frame_gap_ms}"
        result = self.command(
            command,
            timeout_s=duration_ms / 1000.0 + 15.0,
            drain_before=drain_before,
        )
        summary = next(
            (line for line in result.lines if line.startswith("TXCONT=")),
            None,
        )
        if summary is None:
            raise RadioCommandError(f"{command}: missing TXCONT summary")
        match = re.fullmatch(
            r"TXCONT=(\d+),ELAPSED_MS=(\d+),FRAMES=(\d+),BYTES=(\d+),"
            r"FRAME=(\d+),GAP_MS=(\d+)",
            summary,
        )
        if match is None:
            raise RadioCommandError(f"{command}: malformed summary {summary!r}")
        requested, elapsed, frames, payload_bytes, parsed_frame, gap = (
            int(value) for value in match.groups()
        )
        return ContinuousTransmissionResult(
            requested_duration_ms=requested,
            elapsed_ms=elapsed,
            frames=frames,
            payload_bytes=payload_bytes,
            frame_bytes=parsed_frame,
            inter_frame_gap_ms=gap,
            response_lines=result.lines,
        )

    def configure(self, commands: Iterable[str]) -> list[CommandResult]:
        return [self.command(command) for command in commands]

    @staticmethod
    def make_payload(length: int) -> bytes:
        alphabet = b"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"
        return bytes(alphabet[index % len(alphabet)] for index in range(length))

    @staticmethod
    def line_contains_payload(line: str, payload: bytes) -> bool:
        text = payload.decode("ascii", errors="ignore")
        upper = line.upper()
        return (bool(text) and text in line) or payload.hex().upper() in upper

    def send_packet(
        self,
        profile: Profile,
        over_air_bytes: int,
        *,
        wait_for_completion: bool = False,
        completion_timeout_s: float | None = None,
        inter_frame_gap_ms: float = 0.0,
    ) -> TransmissionResult:
        frame_sizes = profile.transmit.frame_sizes(over_air_bytes)
        expected_payloads = tuple(
            self.make_payload(frame_bytes - profile.transmit.line_overhead_bytes)
            for frame_bytes in frame_sizes
        )
        content_bytes = sum(len(payload) for payload in expected_payloads)

        if profile.transmit.mode == "burst_command":
            if not profile.transmit.command or not profile.transmit.frame_payload_bytes:
                raise ValueError(
                    "burst_command mode requires a command and frame_payload_bytes"
                )
            command = profile.transmit.command.format(
                payload_bytes=over_air_bytes,
                frame_payload_bytes=profile.transmit.frame_payload_bytes,
            )
            if inter_frame_gap_ms > 0:
                command += f",{int(round(inter_frame_gap_ms))}"
            response_lines: tuple[str, ...] = ()
            if wait_for_completion:
                response_lines = self.command(
                    command,
                    timeout_s=completion_timeout_s,
                ).lines
            else:
                self._write_line(command)
            return TransmissionResult(
                content_bytes=content_bytes,
                frame_payload_bytes=frame_sizes,
                expected_payloads=expected_payloads,
                response_lines=response_lines,
            )

        response_lines: list[str] = []
        for index, payload in enumerate(expected_payloads):
            if profile.transmit.mode == "text_line":
                self.serial.write(payload + b"\r\n")
                self.serial.flush()
            elif profile.transmit.mode in {"hex_command", "text_command"}:
                if not profile.transmit.command:
                    raise ValueError(
                        f"{profile.transmit.mode} transmit mode requires a command template"
                    )
                command = profile.transmit.command.format(
                    payload_hex=payload.hex().upper(),
                    payload_text=payload.decode("ascii"),
                )
                if wait_for_completion or profile.transmit.wait_for_ok:
                    response_lines.extend(
                        self.command(
                            command,
                            timeout_s=completion_timeout_s,
                        ).lines
                    )
                else:
                    self._write_line(command)
            else:
                raise ValueError(f"Unsupported transmit mode: {profile.transmit.mode!r}")

            if index + 1 < len(expected_payloads) and inter_frame_gap_ms > 0:
                time.sleep(inter_frame_gap_ms / 1000.0)

        return TransmissionResult(
            content_bytes=content_bytes,
            frame_payload_bytes=frame_sizes,
            expected_payloads=expected_payloads,
            response_lines=tuple(response_lines),
        )
