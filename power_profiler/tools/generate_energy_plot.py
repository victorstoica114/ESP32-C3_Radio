from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


POWERS = (-30, 0, 10)
RATES = (1.2, 38.4, 250.0)
SIZES = (8, 32, 64, 128, 512, 1024)
RATE_STYLES = {
    1.2: ("blue!75!black", "solid", "*", "1{,}2 kbps"),
    38.4: ("orange!90!black", "dashed", "square*", "38{,}4 kbps"),
    250.0: ("green!45!black", "dashdotted", "triangle*", "250 kbps"),
}


def read_aggregates(path: Path, session: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as stream:
        for raw in csv.DictReader(stream):
            params = json.loads(raw["parameters_json"])
            payload_bytes = int(raw["payload_bytes"])
            energy_uJ = float(raw["energy_total_uJ_mean"])
            stdev_uJ = float(raw["energy_total_uJ_stdev"])
            rows.append(
                {
                    "payload_bytes": payload_bytes,
                    "tx_power_dbm": int(params["tx_power_dbm"]),
                    "bit_rate_kbps": float(params["bit_rate_kbps"]),
                    "energy_total_mJ_mean": energy_uJ / 1000.0,
                    "energy_total_mJ_stdev": stdev_uJ / 1000.0,
                    "energy_per_byte_uJ": energy_uJ / payload_bytes,
                    "event_duration_ms_mean": float(raw["event_duration_ms_mean"]),
                    "runs": int(raw["runs"]),
                    "source_session": session,
                }
            )
    return rows


def validate(rows: list[dict[str, Any]]) -> None:
    keys = {
        (row["payload_bytes"], row["tx_power_dbm"], row["bit_rate_kbps"])
        for row in rows
    }
    expected = {(size, power, rate) for size in SIZES for power in POWERS for rate in RATES}
    missing = expected - keys
    extra = keys - expected
    if missing or extra or len(rows) != len(expected):
        raise ValueError(
            f"Incomplete plotting matrix: missing={sorted(missing)}, extra={sorted(extra)}, "
            f"rows={len(rows)}, expected={len(expected)}"
        )
    if any(row["runs"] != 5 for row in rows):
        raise ValueError("Every aggregate must contain exactly five repetitions")


def write_data(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "payload_bytes",
        "tx_power_dbm",
        "bit_rate_kbps",
        "energy_total_mJ_mean",
        "energy_total_mJ_stdev",
        "energy_per_byte_uJ",
        "event_duration_ms_mean",
        "runs",
        "source_session",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            sorted(
                rows,
                key=lambda row: (
                    row["tx_power_dbm"],
                    row["bit_rate_kbps"],
                    row["payload_bytes"],
                ),
            )
        )


def _number(value: float) -> str:
    return f"{value:.9g}"


def write_tex(path: Path, rows: list[dict[str, Any]]) -> None:
    minimum = min(row["energy_total_mJ_mean"] for row in rows)
    maximum = max(row["energy_total_mJ_mean"] for row in rows)
    ymin = 10 ** math.floor(math.log10(minimum * 0.75))
    ymax = 10 ** math.ceil(math.log10(maximum * 1.25))

    lines = [
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
        r"  group style={group size=3 by 1, horizontal sep=1.25cm},",
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

    for power in POWERS:
        ylabel = (
            r", ylabel={Energia totală medie [mJ]}"
            if power == POWERS[0]
            else ""
        )
        lines.append(
            rf"\nextgroupplot[title={{\(P_{{\mathrm{{TX}}}}={power}\,\mathrm{{dBm}}\)}}{ylabel}]"
        )
        for rate in RATES:
            color, line_style, marker, legend = RATE_STYLES[rate]
            points = sorted(
                (
                    row
                    for row in rows
                    if row["tx_power_dbm"] == power
                    and math.isclose(row["bit_rate_kbps"], rate)
                ),
                key=lambda row: row["payload_bytes"],
            )
            lines.extend(
                [
                    r"\addplot+[",
                    rf"  color={color}, {line_style}, mark={marker}, mark size=2.2pt,",
                    r"  error bars/.cd, y dir=both, y explicit,",
                    r"] coordinates {",
                ]
            )
            for row in points:
                lines.append(
                    "  "
                    f"({_number(row['payload_bytes'])},{_number(row['energy_total_mJ_mean'])}) "
                    f"+- (0,{_number(row['energy_total_mJ_stdev'])})"
                )
            lines.append(r"};")
            if power == 0:
                lines.append(rf"\addlegendentry{{{legend}}}")

    lines.extend(
        [
            r"\end{groupplot}",
            r"\node[font=\bfseries\large] at ($(group c2r1.north)+(0,0.85cm)$)",
            r"  {CC1101 V2, 868 MHz: energia în funcție de dimensiune};",
            r"\node[font=\footnotesize, align=center, text width=18.5cm]",
            r"  at ($(group c2r1.south)+(0,-3.15cm)$)",
            r"  {Punctele reprezintă media a 5 repetări; barele indică abaterea standard.\\",
            r"   8--64 B sunt cadre radio individuale; 128--1024 B sunt transferuri logice\\",
            r"   fragmentate în 2/8/16 cadre fizice de 64 B. Ambele axe sunt logaritmice.};",
            r"\end{tikzpicture}",
            r"\end{document}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the CC1101 energy PGFPlots figure")
    parser.add_argument("old_aggregates", type=Path, help="8/32/64-byte aggregate CSV")
    parser.add_argument("new_aggregates", type=Path, help="128/512/1024-byte aggregate CSV")
    parser.add_argument("output_base", type=Path)
    args = parser.parse_args()

    rows = read_aggregates(args.old_aggregates, args.old_aggregates.parent.name)
    rows.extend(read_aggregates(args.new_aggregates, args.new_aggregates.parent.name))
    validate(rows)
    args.output_base.parent.mkdir(parents=True, exist_ok=True)
    data_path = args.output_base.with_name(args.output_base.name + "_data").with_suffix(".csv")
    tex_path = args.output_base.with_suffix(".tex")
    write_data(data_path, rows)
    write_tex(tex_path, rows)
    print(data_path.resolve())
    print(tex_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
