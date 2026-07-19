from __future__ import annotations

import argparse
import math
from pathlib import Path

from render_lora_campaign_plots import (
    BLUE,
    GREEN,
    ORANGE,
    RED,
    PdfCanvas,
    _axes,
    _f,
    _legend,
    _log_energy_scale,
    _plot_series,
    _rows,
    _three_panel_canvas,
)


COLORS = (BLUE, ORANGE, GREEN)
DASHES = ("[] 0", "[7 3] 0", "[8 3 2 3] 0")


def _rate_label(rate: float) -> str:
    return f"{rate:g} kbps"


def _energy_plot(
    output: Path,
    base: str,
    module: str,
    rows: list[dict[str, str]],
    *,
    title: str,
    suffix: str,
) -> Path:
    canvas, boxes = _three_panel_canvas(f"{module}: {title}")
    powers = tuple(sorted({_f(row["tx_power_dbm"]) for row in rows}))
    rates = tuple(sorted({_f(row["bit_rate_kbps"]) for row in rows}))
    payloads = tuple(sorted({_f(row["payload_bytes"]) for row in rows}))
    y_range, y_ticks = _log_energy_scale(
        [_f(row["energy_total_mJ_mean"]) for row in rows]
    )
    x_range = (min(payloads), max(payloads))
    x_ticks = tuple((payload, f"{payload:g}") for payload in payloads)
    for box, power in zip(boxes, powers):
        _axes(
            canvas,
            box,
            y_ticks=y_ticks,
            y_range=y_range,
            x_ticks=x_ticks,
            x_range=x_range,
            log_x=True,
            log_y=True,
            y_label="Mean energy [mJ]",
        )
        canvas.text(box[0] + 110, 455, f"{power:g} dBm", size=11, bold=True)
        for index, rate in enumerate(rates):
            selected = sorted(
                (
                    row
                    for row in rows
                    if _f(row["tx_power_dbm"]) == power
                    and _f(row["bit_rate_kbps"]) == rate
                ),
                key=lambda row: _f(row["payload_bytes"]),
            )
            _plot_series(
                canvas,
                box,
                [
                    (_f(row["payload_bytes"]), _f(row["energy_total_mJ_mean"]))
                    for row in selected
                ],
                x_range=x_range,
                y_range=y_range,
                color=COLORS[index],
                marker=index,
                log_x=True,
                log_y=True,
                dash=DASHES[index],
            )
    _legend(
        canvas,
        [(_rate_label(rate), COLORS[index], index) for index, rate in enumerate(rates)],
        340,
        55,
    )
    canvas.text(385, 25, "Payload [B]; five repetitions per point", size=9)
    path = output / f"{base}_{suffix}.pdf"
    canvas.save(path)
    return path


def _tx_rx_energy(
    output: Path,
    base: str,
    module: str,
    tx: list[dict[str, str]],
    rx: list[dict[str, str]],
) -> Path:
    power = max(_f(row["tx_power_dbm"]) for row in tx + rx)
    rates = tuple(sorted({_f(row["bit_rate_kbps"]) for row in tx + rx}))
    payloads = tuple(sorted({_f(row["payload_bytes"]) for row in tx + rx}))
    selected_power = [
        row for row in tx + rx if _f(row["tx_power_dbm"]) == power
    ]
    y_range, y_ticks = _log_energy_scale(
        [_f(row["energy_total_mJ_mean"]) for row in selected_power]
    )
    x_range = (min(payloads), max(payloads))
    x_ticks = tuple((payload, f"{payload:g}") for payload in payloads)
    canvas, boxes = _three_panel_canvas(
        f"{module}: TX-RX energy at {power:g} dBm"
    )
    for box, rate in zip(boxes, rates):
        _axes(
            canvas,
            box,
            y_ticks=y_ticks,
            y_range=y_range,
            x_ticks=x_ticks,
            x_range=x_range,
            log_x=True,
            log_y=True,
            y_label="Mean energy [mJ]",
        )
        canvas.text(box[0] + 105, 455, _rate_label(rate), size=11, bold=True)
        for index, (source, color, label) in enumerate(
            ((tx, BLUE, "TX"), (rx, RED, "RX"))
        ):
            selected = sorted(
                (
                    row
                    for row in source
                    if _f(row["bit_rate_kbps"]) == rate
                    and _f(row["tx_power_dbm"]) == power
                ),
                key=lambda row: _f(row["payload_bytes"]),
            )
            _plot_series(
                canvas,
                box,
                [
                    (_f(row["payload_bytes"]), _f(row["energy_total_mJ_mean"]))
                    for row in selected
                ],
                x_range=x_range,
                y_range=y_range,
                color=color,
                marker=index,
                log_x=True,
                log_y=True,
                dash=DASHES[index],
            )
    _legend(canvas, [("TX", BLUE, 0), ("RX", RED, 1)], 455, 55)
    canvas.text(350, 25, "Payload [B]; five repetitions per point", size=9)
    path = output / f"{base}_tx_rx_energy.pdf"
    canvas.save(path)
    return path


def _continuous_power(
    output: Path,
    base: str,
    module: str,
    rows: list[dict[str, str]],
) -> Path:
    tx_rates = {_f(row["bit_rate_kbps"]) for row in rows if row["measurement_direction"] == "tx"}
    rate = min(tx_rates)
    selected_rate = [row for row in rows if _f(row["bit_rate_kbps"]) == rate]
    powers = sorted({_f(row["tx_power_dbm"]) for row in selected_rate})
    x_pad = max(1.0, (max(powers) - min(powers)) * 0.06)
    x_range = (min(powers) - x_pad, max(powers) + x_pad)
    x_ticks = tuple((power, f"{power:g}") for power in powers)

    canvas = PdfCanvas()
    title = f"{module}: continuous average power ({_rate_label(rate)})"
    title_size = min(16.0, (canvas.width - 40.0) / (len(title) * 0.6))
    canvas.text(
        max(20.0, (canvas.width - len(title) * title_size * 0.6) / 2.0),
        510,
        title,
        size=title_size,
        bold=True,
    )
    boxes = ((100, 100, 380, 340), (600, 100, 380, 340))
    specs = (
        ("mean_power_mW", "Mean power [mW]", 1.0),
        ("mean_current_uA", "Mean current [mA]", 1000.0),
    )
    for box, (field, label, divisor) in zip(boxes, specs):
        maximum = max(_f(row[field]) / divisor for row in selected_rate)
        tick_step = max(1.0, math.ceil(maximum * 1.15 / 25.0) * 5.0)
        y_max = tick_step * 5.0
        y_range = (0.0, y_max)
        _axes(
            canvas,
            box,
            y_ticks=tuple(tick_step * index for index in range(6)),
            y_range=y_range,
            x_ticks=x_ticks,
            x_range=x_range,
            y_label=label,
        )
        for index, (direction, color) in enumerate((("tx", BLUE), ("rx", RED))):
            selected = sorted(
                (row for row in selected_rate if row["measurement_direction"] == direction),
                key=lambda row: _f(row["tx_power_dbm"]),
            )
            _plot_series(
                canvas,
                box,
                [(_f(row["tx_power_dbm"]), _f(row[field]) / divisor) for row in selected],
                x_range=x_range,
                y_range=y_range,
                color=color,
                marker=index,
                dash=DASHES[index],
            )
    _legend(canvas, [("TX", BLUE, 0), ("RX", RED, 1)], 455, 55)
    canvas.text(450, 25, "Configured TX power [dBm]", size=9)
    path = output / f"{base}_continuous_average_power.pdf"
    canvas.save(path)
    return path


def _continuous_delivery(
    output: Path,
    base: str,
    module: str,
    rows: list[dict[str, str]],
) -> Path:
    rx = [row for row in rows if row["measurement_direction"] == "rx"]
    rates = sorted({_f(row["bit_rate_kbps"]) for row in rx})
    powers = sorted({_f(row["tx_power_dbm"]) for row in rx})
    x_pad = max(1.0, (max(powers) - min(powers)) * 0.06)
    x_range = (min(powers) - x_pad, max(powers) + x_pad)
    canvas = PdfCanvas()
    canvas.text(210, 510, f"{module}: continuous RX delivery", size=16, bold=True)
    box = (130, 105, 820, 345)
    _axes(
        canvas,
        box,
        y_ticks=(0, 20, 40, 60, 80, 100),
        y_range=(0, 105),
        x_ticks=tuple((power, f"{power:g}") for power in powers),
        x_range=x_range,
        y_label="Received frames [%]",
    )
    entries = []
    for index, rate in enumerate(rates):
        selected = sorted(
            (row for row in rx if _f(row["bit_rate_kbps"]) == rate),
            key=lambda row: _f(row["tx_power_dbm"]),
        )
        values = [
            (_f(row["tx_power_dbm"]), 100.0 - _f(row["frame_loss_percent"]))
            for row in selected
        ]
        _plot_series(
            canvas,
            box,
            values,
            x_range=x_range,
            y_range=(0, 105),
            color=COLORS[index],
            marker=index,
            dash=DASHES[index],
        )
        entries.append((_rate_label(rate), COLORS[index], index))
    _legend(canvas, entries, 350, 475)
    canvas.text(425, 65, "Stimulus TX power [dBm]", size=10, bold=True)
    canvas.text(350, 28, "60 s per point; 60 B logical frames", size=9)
    path = output / f"{base}_continuous_rx_delivery.pdf"
    canvas.save(path)
    return path


def _loss_vs_rate(
    output: Path,
    base: str,
    module: str,
    rows: list[dict[str, str]],
) -> Path:
    rates = sorted({_f(row["bit_rate_kbps"]) for row in rows})
    powers = sorted({_f(row["tx_power_dbm"]) for row in rows}, reverse=True)
    canvas = PdfCanvas()
    canvas.text(250, 510, f"{module}: packet loss versus radio rate", size=14, bold=True)
    box = (130, 105, 820, 345)
    x_range = (min(rates) / 1.5, max(rates) * 1.5)
    max_loss = max(_f(row["frame_loss_percent"]) for row in rows)
    y_max = min(100.0, max(10.0, math.ceil(max_loss * 1.25 / 5.0) * 5.0))
    _axes(
        canvas,
        box,
        y_ticks=tuple(y_max * index / 5.0 for index in range(6)),
        y_range=(0, y_max),
        x_ticks=tuple((rate, f"{rate:g}") for rate in rates),
        x_range=x_range,
        log_x=True,
        y_label="Lost frames [%]",
    )
    entries = []
    for index, power in enumerate(powers):
        selected = sorted(
            (row for row in rows if _f(row["tx_power_dbm"]) == power),
            key=lambda row: _f(row["bit_rate_kbps"]),
        )
        _plot_series(
            canvas,
            box,
            [(_f(row["bit_rate_kbps"]), _f(row["frame_loss_percent"])) for row in selected],
            x_range=x_range,
            y_range=(0, y_max),
            color=COLORS[index],
            marker=index,
            log_x=True,
            dash=DASHES[index],
        )
        entries.append((f"{power:g} dBm", COLORS[index], index))
    _legend(canvas, entries, 160, 475)
    canvas.text(440, 65, "Radio rate [kbps]", size=10, bold=True)
    canvas.text(335, 28, "60 s per point; profile-specific safe pacing", size=9)
    path = output / f"{base}_loss_vs_rate.pdf"
    canvas.save(path)
    return path


def render(output: Path, base: str) -> list[Path]:
    tx = _rows(output / f"{base}_tx.csv")
    rx = _rows(output / f"{base}_rx.csv")
    continuous = _rows(output / f"{base}_continuous.csv")
    loss = _rows(output / f"{base}_loss_vs_rate.csv")
    module = tx[0].get("module", base) if tx else base
    pdfs = [
        _energy_plot(output, base, module, tx, title="TX energy", suffix="tx_energy"),
        _energy_plot(
            output,
            base,
            module,
            tx,
            title="energy versus payload",
            suffix="energy_vs_payload",
        ),
        _tx_rx_energy(output, base, module, tx, rx),
        _continuous_power(output, base, module, continuous),
        _continuous_delivery(output, base, module, continuous),
        _loss_vs_rate(output, base, module, loss),
    ]
    return pdfs + [path.with_suffix(".png") for path in pdfs]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render generic radio campaign PDFs and PNGs without a TeX runtime"
    )
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--base-name", required=True)
    args = parser.parse_args()
    for path in render(args.output_dir.resolve(), args.base_name):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
