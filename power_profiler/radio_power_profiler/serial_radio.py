from __future__ import annotations

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

    def command(self, text: str, *, timeout_s: float | None = None) -> CommandResult:
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
                    line = raw.decode("utf-8", errors="replace").strip("\r ")
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
            lines.append(partial.decode("utf-8", errors="replace").strip())
        rendered = " | ".join(lines) if lines else "no response"
        raise RadioCommandError(f"Timeout waiting for OK after {text!r}: {rendered}")

    def configure(self, commands: Iterable[str]) -> list[CommandResult]:
        return [self.command(command) for command in commands]

    @staticmethod
    def make_payload(length: int) -> bytes:
        alphabet = b"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"
        return bytes(alphabet[index % len(alphabet)] for index in range(length))

    def send_packet(self, profile: Profile, over_air_bytes: int) -> int:
        content_length = over_air_bytes - profile.transmit.line_overhead_bytes
        if content_length < 1:
            raise ValueError("Packet has no payload after accounting for line overhead")
        payload = self.make_payload(content_length)

        if profile.transmit.mode == "text_line":
            self.serial.write(payload + b"\r\n")
            self.serial.flush()
            return content_length

        if profile.transmit.mode == "hex_command":
            if not profile.transmit.command:
                raise ValueError("hex_command transmit mode requires a command template")
            command = profile.transmit.command.format(payload_hex=payload.hex().upper())
            self._write_line(command)
            return content_length

        raise ValueError(f"Unsupported transmit mode: {profile.transmit.mode!r}")
