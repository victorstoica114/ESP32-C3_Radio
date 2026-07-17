from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any


POWERS = (-30.0, 0.0, 10.0)
RATES = (1.2, 38.4, 250.0)
SIZES = (8, 32, 64, 128, 512, 1024)
RATE_STYLES = {
    1.2: ("blue!75!black", "solid", "*", "1{,}2 kbps"),
    38.4: ("orange!90!black", "dashed", "square*", "38{,}4 kbps"),
    250.0: ("green!45!black", "dashdotted", "triangle*", "250 kbps"),
}


def read_report(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as stream:
        for raw in csv.DictReader(stream):
            rows.append(
                {
                    "module": raw["module"],
                    "measurement_direction": raw["measurement_direction"],
                    "payload_bytes": int(raw["payload_bytes"]),
                    "tx_power_dbm": float(raw["tx_power_dbm"]),
                    "bit_rate_kbps": float(raw["bit_rate_kbps"]),
                    "runs": int(raw["runs"]),
                    "status_ok_runs": int(raw["status_ok_runs"]),
                    "packets_received": int(raw["packets_received"]),
                    "energy_total_mJ_mean": float(raw["energy_total_mJ_mean"]),
                    "energy_total_mJ_stdev": float(raw["energy_total_uJ_stdev"])
                    / 1000.0,
                    "event_mean_mA_mean": float(raw["event_mean_uA_mean"])
                    / 1000.0,
                    "event_peak_mA_mean": float(raw["event_peak_uA_mean"])
                    / 1000.0,
                    "event_duration_ms_mean": float(raw["event_duration_ms_mean"]),
                    "sample_loss_percent_max": float(raw["sample_loss_percent_max"]),
                }
            )
    return rows


def validate(tx_rows: list[dict[str, Any]], rx_rows: list[dict[str, Any]]) -> None:
    tx_expected = {
        (size, power, rate)
        for size in SIZES
        for power in POWERS
        for rate in RATES
    }
    rx_expected = {(size, 10.0, rate) for size in SIZES for rate in RATES}
    tx_keys = {
        (row["payload_bytes"], row["tx_power_dbm"], row["bit_rate_kbps"])
        for row in tx_rows
    }
    rx_keys = {
        (row["payload_bytes"], row["tx_power_dbm"], row["bit_rate_kbps"])
        for row in rx_rows
    }
    if tx_keys != tx_expected or len(tx_rows) != len(tx_expected):
        raise ValueError("TX report does not contain the complete 6 x 3 x 3 matrix")
    if rx_keys != rx_expected or len(rx_rows) != len(rx_expected):
        raise ValueError("RX report does not contain the complete 6 x 1 x 3 matrix")
    if any(row["measurement_direction"] != "tx" for row in tx_rows):
        raise ValueError("TX report contains non-TX rows")
    if any(row["measurement_direction"] != "rx" for row in rx_rows):
        raise ValueError("RX report contains non-RX rows")
    if any(row["runs"] != 5 or row["status_ok_runs"] != 5 for row in tx_rows + rx_rows):
        raise ValueError("Every plotted point must contain five successful repetitions")
    if any(row["packets_received"] != 5 for row in rx_rows):
        raise ValueError("Every RX aggregate must contain five received transfers")


def _number(value: float | int) -> str:
    return f"{value:.9g}"


def _y_limits(rows: list[dict[str, Any]]) -> tuple[float, float]:
    minimum = min(row["energy_total_mJ_mean"] for row in rows)
    maximum = max(row["energy_total_mJ_mean"] for row in rows)
    return (
        10 ** math.floor(math.log10(minimum * 0.75)),
        10 ** math.ceil(math.log10(maximum * 1.25)),
    )


def _plot_coordinates(rows: list[dict[str, Any]]) -> list[str]:
    lines = [r"  error bars/.cd, y dir=both, y explicit,", r"] coordinates {"]
    for row in sorted(rows, key=lambda item: item["payload_bytes"]):
        lines.append(
            f"  ({_number(row['payload_bytes'])},{_number(row['energy_total_mJ_mean'])}) "
            f"+- (0,{_number(row['energy_total_mJ_stdev'])})"
        )
    lines.append(r"};")
    return lines


def write_data(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "module",
        "measurement_direction",
        "payload_bytes",
        "tx_power_dbm",
        "bit_rate_kbps",
        "runs",
        "status_ok_runs",
        "packets_received",
        "energy_total_mJ_mean",
        "energy_total_mJ_stdev",
        "event_mean_mA_mean",
        "event_peak_mA_mean",
        "event_duration_ms_mean",
        "sample_loss_percent_max",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            sorted(
                rows,
                key=lambda row: (
                    row["measurement_direction"],
                    row["tx_power_dbm"],
                    row["bit_rate_kbps"],
                    row["payload_bytes"],
                ),
            )
        )


def _document_start(ymin: float, ymax: float, horizontal_sep: str) -> list[str]:
    return [
        r"\documentclass[tikz,border=6pt]{standalone}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage{pgfplots}",
        r"\usepgfplotslibrary{groupplots}",
        r"\usetikzlibrary{calc}",
        r"\pgfplotsset{compat=1.18}",
        r"\begin{document}",
        r"\begin{tikzpicture}",
        r"\begin{groupplot}[/pgf/number format/use comma,",
        rf"  group style={{group size=3 by 1, horizontal sep={horizontal_sep}}},",
        r"  width=6.15cm, height=6.2cm,",
        r"  xmode=log, log basis x={2},",
        r"  ymode=log, log basis y={10},",
        rf"  ymin={_number(ymin)}, ymax={_number(ymax)},",
        r"  xmin=6, xmax=1400,",
        r"  xtick={8,32,64,128,512,1024},",
        r"  xticklabels={8,32,64,128,512,1024},",
        r"  x tick label style={rotate=45, anchor=east, font=\small},",
        r"  y tick label style={font=\small},",
        r"  grid=both, minor grid style={gray!15}, major grid style={gray!35},",
        r"  xlabel={Dimensiunea transferului logic [B]},",
        r"  every axis plot/.append style={line width=1.05pt},",
        r"  error bars/error bar style={line width=0.35pt},",
        r"  legend style={font=\small, draw=none, fill=none,",
        r"    at={(0.5,-0.29)}, anchor=north, legend columns=3,",
        r"    /tikz/every even column/.append style={column sep=0.45cm}},",
        r"]",
    ]


def write_tx_tex(
    path: Path, tx_rows: list[dict[str, Any]], module_title: str
) -> None:
    ymin, ymax = _y_limits(tx_rows)
    lines = _document_start(ymin, ymax, "1.25cm")
    for power in POWERS:
        ylabel = r", ylabel={Energia totală medie [mJ]}" if power == POWERS[0] else ""
        lines.append(
            rf"\nextgroupplot[title={{\(P_{{\mathrm{{TX}}}}={_number(power)}\,\mathrm{{dBm}}\)}}{ylabel}]"
        )
        for rate in RATES:
            color, line_style, marker, legend = RATE_STYLES[rate]
            points = [
                row
                for row in tx_rows
                if row["tx_power_dbm"] == power and row["bit_rate_kbps"] == rate
            ]
            lines.extend(
                [
                    r"\addplot+[",
                    rf"  color={color}, {line_style}, mark={marker}, mark size=2.2pt,",
                    *_plot_coordinates(points),
                ]
            )
            if power == 0.0:
                lines.append(rf"\addlegendentry{{{legend}}}")
    lines.extend(
        [
            r"\end{groupplot}",
            r"\node[font=\bfseries\large] at ($(group c2r1.north)+(0,0.85cm)$)",
            rf"  {{{module_title}: consumul în transmisie}};",
            r"\node[font=\footnotesize, align=center, text width=18.5cm]",
            r"  at ($(group c2r1.south)+(0,-3.15cm)$)",
            r"  {Media a 5 repetări; barele indică abaterea standard. Transferurile de 128--1024 B\\",
            r"   sunt fragmentate în cadre fizice de cel mult 32 B, cu pauză de 15 ms. Ambele axe sunt logaritmice.};",
            r"\end{tikzpicture}",
            r"\end{document}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_tx_rx_tex(
    path: Path,
    tx_rows: list[dict[str, Any]],
    rx_rows: list[dict[str, Any]],
    module_title: str,
) -> None:
    tx_10 = [row for row in tx_rows if row["tx_power_dbm"] == 10.0]
    plotted = tx_10 + rx_rows
    ymin, ymax = _y_limits(plotted)
    lines = _document_start(ymin, ymax, "1.25cm")
    for index, rate in enumerate(RATES):
        ylabel = r", ylabel={Energia totală medie [mJ]}" if index == 0 else ""
        rate_label = RATE_STYLES[rate][3]
        lines.append(
            rf"\nextgroupplot[title={{{rate_label}}}{ylabel}]"
        )
        tx_points = [row for row in tx_10 if row["bit_rate_kbps"] == rate]
        rx_points = [row for row in rx_rows if row["bit_rate_kbps"] == rate]
        lines.extend(
            [
                r"\addplot+[",
                r"  color=blue!75!black, solid, mark=*, mark size=2.2pt,",
                *_plot_coordinates(tx_points),
            ]
        )
        if index == 1:
            lines.append(r"\addlegendentry{TX la 10 dBm}")
        lines.extend(
            [
                r"\addplot+[",
                r"  color=red!75!black, dashed, mark=square*, mark size=2.2pt,",
                *_plot_coordinates(rx_points),
            ]
        )
        if index == 1:
            lines.append(r"\addlegendentry{RX, stimul la 10 dBm}")
    lines.extend(
        [
            r"\end{groupplot}",
            r"\node[font=\bfseries\large] at ($(group c2r1.north)+(0,0.85cm)$)",
            rf"  {{{module_title}: comparație TX--RX}};",
            r"\node[font=\footnotesize, align=center, text width=18.5cm]",
            r"  at ($(group c2r1.south)+(0,-3.15cm)$)",
            r"  {Media a 5 repetări; barele indică abaterea standard. Energia RX include activarea receptorului,\\",
            r"   recepția și procesarea tuturor cadrelor; emițătorul de stimul este configurat la 10 dBm.};",
            r"\end{tikzpicture}",
            r"\end{document}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate CC1101 TX and RX PGFPlots figures")
    parser.add_argument("tx_report", type=Path)
    parser.add_argument("rx_report", type=Path)
    parser.add_argument("output_base", type=Path)
    args = parser.parse_args()

    tx_rows = read_report(args.tx_report)
    rx_rows = read_report(args.rx_report)
    validate(tx_rows, rx_rows)
    module_title = tx_rows[0]["module"]
    if any(row["module"] != module_title for row in tx_rows + rx_rows):
        raise ValueError("TX and RX reports refer to different radio modules")
    args.output_base.parent.mkdir(parents=True, exist_ok=True)
    data_path = args.output_base.with_name(args.output_base.name + "_data").with_suffix(".csv")
    tx_tex = args.output_base.with_name(args.output_base.name + "_tx_energy").with_suffix(".tex")
    tx_rx_tex = args.output_base.with_name(args.output_base.name + "_tx_rx_energy").with_suffix(".tex")
    write_data(data_path, tx_rows + rx_rows)
    write_tx_tex(tx_tex, tx_rows, module_title)
    write_tx_rx_tex(tx_rx_tex, tx_rows, rx_rows, module_title)
    print(data_path.resolve())
    print(tx_tex.resolve())
    print(tx_rx_tex.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
