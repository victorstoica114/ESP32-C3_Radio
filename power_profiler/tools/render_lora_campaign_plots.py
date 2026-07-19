from __future__ import annotations

import argparse
import binascii
import csv
import math
import struct
import zlib
from pathlib import Path
from typing import Sequence


BLUE = (0.08, 0.32, 0.68)
RED = (0.72, 0.12, 0.12)
ORANGE = (0.92, 0.48, 0.04)
GREEN = (0.08, 0.52, 0.20)
GRID = (0.82, 0.84, 0.88)
BLACK = (0.08, 0.09, 0.12)


FONT_5X7 = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    "%": ("11001", "11010", "00100", "01000", "10110", "00110", "00000"),
    "/": ("00001", "00010", "00100", "01000", "10000", "00000", "00000"),
    "[": ("01110", "01000", "01000", "01000", "01000", "01000", "01110"),
    "]": ("01110", "00010", "00010", "00010", "00010", "00010", "01110"),
    "(": ("00110", "01000", "10000", "10000", "10000", "01000", "00110"),
    ")": ("01100", "00010", "00001", "00001", "00001", "00010", "01100"),
    ",": ("00000", "00000", "00000", "00000", "00110", "00100", "01000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "=": ("00000", "11111", "00000", "11111", "00000", "00000", "00000"),
    " ": ("00000",) * 7,
}


def _f(value: object) -> float:
    return float(value or 0)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class PdfCanvas:
    def __init__(self, width: float = 1080, height: float = 540) -> None:
        self.width = width
        self.height = height
        self.commands: list[str] = []
        self.raster_ops: list[tuple[object, ...]] = []

    @staticmethod
    def _rgb(color: tuple[float, float, float]) -> str:
        return " ".join(f"{part:.3f}" for part in color)

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        color: tuple[float, float, float] = BLACK,
        width: float = 1,
        dash: str = "[] 0",
    ) -> None:
        self.raster_ops.append(("line", x1, y1, x2, y2, color, width))
        self.commands.append(
            f"q {self._rgb(color)} RG {width:.2f} w {dash} d "
            f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S Q"
        )

    def polyline(
        self,
        points: Sequence[tuple[float, float]],
        *,
        color: tuple[float, float, float],
        width: float = 2,
        dash: str = "[] 0",
    ) -> None:
        if not points:
            return
        self.raster_ops.append(("polyline", tuple(points), color, width))
        path = [f"{points[0][0]:.2f} {points[0][1]:.2f} m"]
        path.extend(f"{x:.2f} {y:.2f} l" for x, y in points[1:])
        self.commands.append(
            f"q {self._rgb(color)} RG {width:.2f} w {dash} d "
            + " ".join(path)
            + " S Q"
        )

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        size: float = 10,
        bold: bool = False,
        color: tuple[float, float, float] = BLACK,
    ) -> None:
        self.raster_ops.append(("text", x, y, value, size, bold, color))
        font = "F2" if bold else "F1"
        self.commands.append(
            f"q {self._rgb(color)} rg BT /{font} {size:.2f} Tf "
            f"{x:.2f} {y:.2f} Td ({_escape(value)}) Tj ET Q"
        )

    def marker(
        self,
        x: float,
        y: float,
        *,
        color: tuple[float, float, float],
        kind: int,
        radius: float = 4,
    ) -> None:
        self.raster_ops.append(("marker", x, y, color, kind, radius))
        if kind % 3 == 0:
            self.commands.append(
                f"q {self._rgb(color)} rg {x-radius:.2f} {y-radius:.2f} "
                f"{2*radius:.2f} {2*radius:.2f} re f Q"
            )
        elif kind % 3 == 1:
            self.commands.append(
                f"q {self._rgb(color)} rg {x:.2f} {y+radius:.2f} m "
                f"{x-radius:.2f} {y-radius:.2f} l {x+radius:.2f} "
                f"{y-radius:.2f} l h f Q"
            )
        else:
            k = 0.55228475 * radius
            self.commands.append(
                f"q {self._rgb(color)} rg {x+radius:.2f} {y:.2f} m "
                f"{x+radius:.2f} {y+k:.2f} {x+k:.2f} {y+radius:.2f} "
                f"{x:.2f} {y+radius:.2f} c {x-k:.2f} {y+radius:.2f} "
                f"{x-radius:.2f} {y+k:.2f} {x-radius:.2f} {y:.2f} c "
                f"{x-radius:.2f} {y-k:.2f} {x-k:.2f} {y-radius:.2f} "
                f"{x:.2f} {y-radius:.2f} c {x+k:.2f} {y-radius:.2f} "
                f"{x+radius:.2f} {y-k:.2f} {x+radius:.2f} {y:.2f} c f Q"
            )

    def save(self, path: Path) -> None:
        content = ("\n".join(self.commands) + "\n").encode("latin-1", "replace")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.width:g} {self.height:g}] "
                "/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>"
            ).encode("ascii"),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"endstream",
        ]
        data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, obj in enumerate(objects, 1):
            offsets.append(len(data))
            data.extend(f"{number} 0 obj\n".encode("ascii"))
            data.extend(obj)
            data.extend(b"\nendobj\n")
        xref = len(data)
        data.extend(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
        data.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        data.extend(
            f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n".encode("ascii")
        )
        path.write_bytes(data)
        self.save_png(path.with_suffix(".png"))

    @staticmethod
    def _png_chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        )

    def save_png(self, path: Path, scale: float = 1.5) -> None:
        width = int(round(self.width * scale))
        height = int(round(self.height * scale))
        pixels = bytearray(b"\xff" * (width * height * 3))

        def rgb(color: tuple[float, float, float]) -> tuple[int, int, int]:
            return tuple(max(0, min(255, round(value * 255))) for value in color)  # type: ignore[return-value]

        def put(x: int, y: int, color: tuple[int, int, int]) -> None:
            if 0 <= x < width and 0 <= y < height:
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes(color)

        def draw_line(
            x1: float,
            y1: float,
            x2: float,
            y2: float,
            color: tuple[float, float, float],
            stroke: float,
        ) -> None:
            x0 = int(round(x1 * scale))
            y0 = int(round((self.height - y1) * scale))
            x_end = int(round(x2 * scale))
            y_end = int(round((self.height - y2) * scale))
            dx = abs(x_end - x0)
            sx = 1 if x0 < x_end else -1
            dy = -abs(y_end - y0)
            sy = 1 if y0 < y_end else -1
            error = dx + dy
            radius = max(0, int(round(stroke * scale / 2)) - 1)
            ink = rgb(color)
            while True:
                for oy in range(-radius, radius + 1):
                    for ox in range(-radius, radius + 1):
                        put(x0 + ox, y0 + oy, ink)
                if x0 == x_end and y0 == y_end:
                    break
                twice = 2 * error
                if twice >= dy:
                    error += dy
                    x0 += sx
                if twice <= dx:
                    error += dx
                    y0 += sy

        def draw_marker(
            x: float,
            y: float,
            color: tuple[float, float, float],
            kind: int,
            radius: float,
        ) -> None:
            cx = int(round(x * scale))
            cy = int(round((self.height - y) * scale))
            r = max(2, int(round(radius * scale)))
            ink = rgb(color)
            for oy in range(-r, r + 1):
                for ox in range(-r, r + 1):
                    if kind % 3 == 0:
                        inside = True
                    elif kind % 3 == 1:
                        inside = oy >= -r and abs(ox) <= (oy + r) / 2
                    else:
                        inside = ox * ox + oy * oy <= r * r
                    if inside:
                        put(cx + ox, cy + oy, ink)

        def draw_text(
            x: float,
            y: float,
            value: str,
            size: float,
            bold: bool,
            color: tuple[float, float, float],
        ) -> None:
            cell = max(1, int(round(size * scale / 8)))
            start_x = int(round(x * scale))
            start_y = int(round((self.height - y - size) * scale))
            ink = rgb(color)
            if bold:
                ink_offsets = (0, 1)
            else:
                ink_offsets = (0,)
            cursor = start_x
            for char in value.upper():
                glyph = FONT_5X7.get(char, FONT_5X7[" "])
                for row_index, row in enumerate(glyph):
                    for column, active in enumerate(row):
                        if active == "1":
                            for oy in range(cell):
                                for ox in range(cell):
                                    for extra in ink_offsets:
                                        put(
                                            cursor + column * cell + ox + extra,
                                            start_y + row_index * cell + oy,
                                            ink,
                                        )
                cursor += 6 * cell

        for operation in self.raster_ops:
            kind = operation[0]
            if kind == "line":
                _, x1, y1, x2, y2, color, stroke = operation
                draw_line(x1, y1, x2, y2, color, stroke)  # type: ignore[arg-type]
            elif kind == "polyline":
                _, points, color, stroke = operation
                for first, second in zip(points, points[1:]):  # type: ignore[arg-type]
                    draw_line(*first, *second, color, stroke)  # type: ignore[arg-type]
            elif kind == "marker":
                _, x, y, color, marker_kind, radius = operation
                draw_marker(x, y, color, marker_kind, radius)  # type: ignore[arg-type]
            elif kind == "text":
                _, x, y, value, size, bold, color = operation
                draw_text(x, y, value, size, bold, color)  # type: ignore[arg-type]

        scanlines = bytearray()
        row_bytes = width * 3
        for row in range(height):
            scanlines.append(0)
            start = row * row_bytes
            scanlines.extend(pixels[start : start + row_bytes])
        png = bytearray(b"\x89PNG\r\n\x1a\n")
        png.extend(self._png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        png.extend(self._png_chunk(b"IDAT", zlib.compress(bytes(scanlines), 9)))
        png.extend(self._png_chunk(b"IEND", b""))
        path.write_bytes(png)


def _map(value: float, low: float, high: float, start: float, length: float, log: bool = False) -> float:
    if log:
        value, low, high = math.log10(value), math.log10(low), math.log10(high)
    return start + (value - low) / (high - low) * length


def _axes(
    canvas: PdfCanvas,
    box: tuple[float, float, float, float],
    *,
    y_ticks: Sequence[float],
    y_range: tuple[float, float],
    x_ticks: Sequence[tuple[float, str]],
    x_range: tuple[float, float],
    log_x: bool = False,
    log_y: bool = False,
    y_label: str = "",
) -> None:
    x, y, width, height = box
    for tick in y_ticks:
        py = _map(tick, *y_range, y, height, log_y)
        canvas.line(x, py, x + width, py, color=GRID, width=0.6)
        canvas.text(x - 34, py - 3, f"{tick:g}", size=8)
    for tick, label in x_ticks:
        px = _map(tick, *x_range, x, width, log_x)
        canvas.line(px, y, px, y + height, color=GRID, width=0.6)
        canvas.text(px - 12, y - 18, label, size=8)
    canvas.line(x, y, x + width, y, width=1.2)
    canvas.line(x, y, x, y + height, width=1.2)
    canvas.line(x + width, y, x + width, y + height, width=0.6)
    canvas.line(x, y + height, x + width, y + height, width=0.6)
    if y_label:
        canvas.text(x - 42, y + height + 12, y_label, size=8, bold=True)


def _legend(canvas: PdfCanvas, entries: Sequence[tuple[str, tuple[float, float, float], int]], x: float, y: float) -> None:
    for index, (label, color, marker) in enumerate(entries):
        px = x + index * 82
        canvas.line(px, y, px + 22, y, color=color, width=2)
        canvas.marker(px + 11, y, color=color, kind=marker, radius=3)
        canvas.text(px + 27, y - 3, label, size=9)


def _plot_series(
    canvas: PdfCanvas,
    box: tuple[float, float, float, float],
    values: Sequence[tuple[float, float]],
    *,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    color: tuple[float, float, float],
    marker: int,
    log_x: bool = False,
    log_y: bool = False,
    dash: str = "[] 0",
) -> None:
    x, y, width, height = box
    points = [
        (_map(px, *x_range, x, width, log_x), _map(py, *y_range, y, height, log_y))
        for px, py in values
    ]
    canvas.polyline(points, color=color, width=2, dash=dash)
    for px, py in points:
        canvas.marker(px, py, color=color, kind=marker)


def _three_panel_canvas(title: str) -> tuple[PdfCanvas, list[tuple[float, float, float, float]]]:
    canvas = PdfCanvas()
    canvas.text(390, 510, title, size=16, bold=True)
    boxes = [(75 + index * 345, 95, 285, 340) for index in range(3)]
    return canvas, boxes


def _tx_energy(
    output: Path,
    base: str,
    module: str,
    rows: list[dict[str, str]],
) -> Path:
    canvas, boxes = _three_panel_canvas(f"{module}: TX energy")
    powers = (-4.0, 10.0, 20.0)
    sfs = (7, 9, 12)
    colors = (BLUE, ORANGE, GREEN)
    for box, power in zip(boxes, powers):
        _axes(canvas, box, y_ticks=(1, 10, 100, 1000, 10000), y_range=(1, 10000), x_ticks=((8, "8"), (32, "32"), (128, "128")), x_range=(8, 128), log_x=True, log_y=True, y_label="Energy [mJ]")
        canvas.text(box[0] + 110, 455, f"{power:g} dBm", size=11, bold=True)
        for index, sf in enumerate(sfs):
            selected = sorted((row for row in rows if _f(row["tx_power_dbm"]) == power and int(float(row["spreading_factor"])) == sf), key=lambda row: _f(row["payload_bytes"]))
            _plot_series(canvas, box, [(_f(row["payload_bytes"]), _f(row["energy_total_mJ_mean"])) for row in selected], x_range=(8, 128), y_range=(1, 10000), color=colors[index], marker=index, log_x=True, log_y=True, dash=("[] 0", "[7 3] 0", "[8 3 2 3] 0")[index])
    _legend(canvas, [(f"SF{sf}", colors[i], i) for i, sf in enumerate(sfs)], 420, 55)
    canvas.text(385, 25, "Payload [B]; five repetitions per point", size=9)
    path = output / f"{base}_tx_energy.pdf"
    canvas.save(path)
    return path


def _tx_rx_energy(
    output: Path,
    base: str,
    module: str,
    tx: list[dict[str, str]],
    rx: list[dict[str, str]],
) -> Path:
    canvas, boxes = _three_panel_canvas(f"{module}: TX--RX energy at 20 dBm")
    for box, sf in zip(boxes, (7, 9, 12)):
        _axes(canvas, box, y_ticks=(1, 10, 100, 1000, 10000), y_range=(1, 10000), x_ticks=((8, "8"), (32, "32"), (128, "128")), x_range=(8, 128), log_x=True, log_y=True, y_label="Energy [mJ]")
        canvas.text(box[0] + 125, 455, f"SF{sf}", size=11, bold=True)
        for index, (source, color, label) in enumerate(((tx, BLUE, "TX"), (rx, RED, "RX"))):
            selected = sorted((row for row in source if int(float(row["spreading_factor"])) == sf and _f(row["tx_power_dbm"]) == 20), key=lambda row: _f(row["payload_bytes"]))
            _plot_series(canvas, box, [(_f(row["payload_bytes"]), _f(row["energy_total_mJ_mean"])) for row in selected], x_range=(8, 128), y_range=(1, 10000), color=color, marker=index, log_x=True, log_y=True, dash=("[] 0", "[7 3] 0")[index])
    _legend(canvas, [("TX", BLUE, 0), ("RX", RED, 1)], 455, 55)
    canvas.text(350, 25, "Payload [B]; RX uses one deterministic LoRa airtime window", size=9)
    path = output / f"{base}_tx_rx_energy.pdf"
    canvas.save(path)
    return path


def _continuous(
    output: Path,
    base: str,
    module: str,
    rows: list[dict[str, str]],
) -> Path:
    canvas = PdfCanvas()
    canvas.text(350, 510, f"{module}: continuous average power (SF9)", size=16, bold=True)
    boxes = [(100, 100, 380, 340), (600, 100, 380, 340)]
    sf9 = [row for row in rows if int(float(row["spreading_factor"])) == 9]
    specs = (("mean_power_mW", "Mean power [mW]", (0, 270), (0, 50, 100, 150, 200, 250)), ("mean_current_uA", "Mean current [mA]", (0, 85), (0, 20, 40, 60, 80)))
    for box, (field, label, yrange, ticks) in zip(boxes, specs):
        _axes(canvas, box, y_ticks=ticks, y_range=yrange, x_ticks=((-4, "-4"), (10, "10"), (20, "20")), x_range=(-4, 20), y_label=label)
        for index, (direction, color) in enumerate((("tx", BLUE), ("rx", RED))):
            selected = sorted((row for row in sf9 if row["measurement_direction"] == direction), key=lambda row: _f(row["tx_power_dbm"]))
            values = []
            for row in selected:
                value = _f(row[field]) / (1000 if field == "mean_current_uA" else 1)
                values.append((_f(row["tx_power_dbm"]), value))
            _plot_series(canvas, box, values, x_range=(-4, 20), y_range=yrange, color=color, marker=index, dash=("[] 0", "[7 3] 0")[index])
    _legend(canvas, [("TX", BLUE, 0), ("RX", RED, 1)], 455, 55)
    canvas.text(450, 25, "Configured TX power [dBm]", size=9)
    path = output / f"{base}_continuous_average_power.pdf"
    canvas.save(path)
    return path


def _loss(
    output: Path,
    base: str,
    module: str,
    rows: list[dict[str, str]],
) -> Path:
    canvas = PdfCanvas()
    canvas.text(330, 510, f"{module}: loss versus effective payload speed", size=16, bold=True)
    box = (130, 105, 820, 345)
    rates = sorted({_f(row["effective_payload_rate_kbps"]) for row in rows})
    clustered: list[float] = []
    for rate in rates:
        if not clustered or rate / clustered[-1] > 1.02:
            clustered.append(rate)
    ticks = tuple((rate, f"{rate:.3g}") for rate in clustered)
    x_range = (min(rates) * 0.75, max(rates) * 1.25)
    _axes(canvas, box, y_ticks=(0, 20, 40, 60, 80, 100), y_range=(0, 100), x_ticks=ticks, x_range=x_range, log_x=True, y_label="Lost frames [%]")
    entries = []
    for index, (power, color) in enumerate(((20.0, BLUE), (10.0, ORANGE), (-4.0, GREEN))):
        selected = sorted((row for row in rows if _f(row["tx_power_dbm"]) == power), key=lambda row: _f(row["effective_payload_rate_kbps"]))
        _plot_series(canvas, box, [(_f(row["effective_payload_rate_kbps"]), _f(row["frame_loss_percent"])) for row in selected], x_range=x_range, y_range=(0, 100), color=color, marker=index, log_x=True, dash=("[] 0", "[7 3] 0", "[8 3 2 3] 0")[index])
        entries.append((f"{power:g} dBm", color, index))
    _legend(canvas, entries, 160, 475)
    canvas.text(420, 65, "Effective payload speed [kbps]", size=10, bold=True)
    canvas.text(320, 28, "60 s per point; 64 B frames; 15 ms host gap", size=9)
    path = output / f"{base}_loss_vs_speed.pdf"
    canvas.save(path)
    return path


def render(output: Path, base: str) -> list[Path]:
    tx = _rows(output / f"{base}_tx.csv")
    rx = _rows(output / f"{base}_rx.csv")
    continuous = _rows(output / f"{base}_continuous.csv")
    loss = _rows(output / f"{base}_loss_vs_speed.csv")
    module = tx[0].get("module", base) if tx else base
    pdfs = [
        _tx_energy(output, base, module, tx),
        _tx_rx_energy(output, base, module, tx, rx),
        _continuous(output, base, module, continuous),
        _loss(output, base, module, loss),
    ]
    pngs = [pdf.with_suffix(".png") for pdf in pdfs]
    return pdfs + pngs


def main() -> int:
    parser = argparse.ArgumentParser(description="Render LoRa report PDFs and PNGs without a TeX runtime")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--base-name", required=True)
    args = parser.parse_args()
    for path in render(args.output_dir.resolve(), args.base_name):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
