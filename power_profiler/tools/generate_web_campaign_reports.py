from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import shutil
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import generate_continuous_report as continuous_report
from generate_transfer_report import (
    REPORT_FIELDS,
    build_report,
    write_csv as write_transfer_csv,
    write_xlsx as write_transfer_xlsx,
)


COLORS = (
    "blue!75!black",
    "orange!90!black",
    "green!50!black",
    "red!75!black",
    "violet!75!black",
)
LINE_STYLES = ("solid", "dashed", "dashdotted", "densely dotted")
MARKERS = ("*", "square*", "triangle*", "diamond*")
LOSS_FIELDS = (
    "bit_rate_kbps",
    "tx_power_dbm",
    "frames_transmitted",
    "frames_received",
    "frames_lost",
    "frame_loss_percent",
    "delivery_percent",
    "requested_duration_s",
    "frame_bytes",
    "inter_frame_gap_ms",
    "status",
    "source_directory",
)


def _number(value: float | int) -> str:
    return f"{value:.9g}"


def _latex_number(value: float | int) -> str:
    return _number(value).replace(".", "{,}")


def _read_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "campaign" or manifest.get("state") != "completed":
        raise ValueError("The manifest is not a completed campaign")
    if manifest.get("failed_steps") != 0:
        raise ValueError("The campaign contains failed steps")
    if manifest.get("completed_steps") != len(manifest.get("steps", [])):
        raise ValueError("The campaign step count is incomplete")
    return manifest


def _collect_packet_results(
    manifest: dict[str, Any], direction: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    report: list[dict[str, Any]] = []
    summary: list[dict[str, str]] = []
    metadata: dict[str, Any] | None = None
    prefix = direction + "_"
    for step in manifest["steps"]:
        if step.get("result_kind") != "packet" or not step["step_id"].startswith(prefix):
            continue
        result_dir = Path(step["accepted_result"])
        rows, run_rows, item_metadata = build_report(result_dir)
        if len(rows) != 1:
            raise ValueError(f"Expected one aggregate in {result_dir}, found {len(rows)}")
        if rows[0]["measurement_direction"] != direction:
            raise ValueError(f"Unexpected direction in {result_dir}")
        report.extend(rows)
        summary.extend(run_rows)
        metadata = metadata or item_metadata
    if metadata is None:
        raise ValueError(f"No accepted {direction.upper()} packet results")
    report.sort(
        key=lambda row: (
            row["tx_power_dbm"], row["bit_rate_kbps"], row["payload_bytes"]
        )
    )
    return report, summary, metadata


def _validate_energy_matrix(
    tx_rows: list[dict[str, Any]],
    rx_rows: list[dict[str, Any]],
    repetitions: int,
) -> tuple[list[int], list[float], list[float], float, str, int]:
    module = str(tx_rows[0]["module"])
    if any(row["module"] != module for row in tx_rows + rx_rows):
        raise ValueError("TX and RX data refer to different modules")
    sizes = sorted({int(row["payload_bytes"]) for row in tx_rows})
    powers = sorted({float(row["tx_power_dbm"]) for row in tx_rows})
    rates = sorted({float(row["bit_rate_kbps"]) for row in tx_rows})
    rx_powers = sorted({float(row["tx_power_dbm"]) for row in rx_rows})
    if len(rx_powers) != 1 or rx_powers[0] != max(powers):
        raise ValueError("RX must use the maximum tested transmitter power")
    tx_expected = {
        (size, power, rate) for size in sizes for power in powers for rate in rates
    }
    rx_expected = {(size, rx_powers[0], rate) for size in sizes for rate in rates}
    tx_actual = {
        (row["payload_bytes"], row["tx_power_dbm"], row["bit_rate_kbps"])
        for row in tx_rows
    }
    rx_actual = {
        (row["payload_bytes"], row["tx_power_dbm"], row["bit_rate_kbps"])
        for row in rx_rows
    }
    if tx_actual != tx_expected or len(tx_rows) != len(tx_expected):
        raise ValueError("Incomplete or duplicate TX energy matrix")
    if rx_actual != rx_expected or len(rx_rows) != len(rx_expected):
        raise ValueError("Incomplete or duplicate RX energy matrix")
    if any(
        row["runs"] != repetitions or row["status_ok_runs"] != repetitions
        for row in tx_rows + rx_rows
    ):
        raise ValueError("Every energy point must contain all valid repetitions")
    if any(row["packets_received"] != repetitions for row in rx_rows):
        raise ValueError("Every RX point must contain all received transfers")
    frame_limit = max(int(row["max_frame_payload_bytes"]) for row in tx_rows)
    return sizes, powers, rates, rx_powers[0], module, frame_limit


def _campaign_metadata(
    metadata: dict[str, Any],
    direction: str,
    sizes: list[int],
    powers: list[float],
    rates: list[float],
) -> dict[str, Any]:
    merged = copy.deepcopy(metadata)
    merged["measurement_direction"] = direction
    merged["profile"]["payload_sizes"] = sizes
    for axis in merged["profile"]["axes"]:
        if axis["name"] == "tx_power_dbm":
            axis["values"] = powers
        elif axis["name"] == "bit_rate_kbps":
            axis["values"] = rates
    return merged


def _write_energy_data(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = (
        "module",
        "measurement_direction",
        "payload_bytes",
        "tx_power_dbm",
        "bit_rate_kbps",
        "runs",
        "status_ok_runs",
        "packets_received",
        "energy_total_mJ_mean",
        "energy_total_uJ_stdev",
        "event_mean_uA_mean",
        "event_peak_uA_mean",
        "event_duration_ms_mean",
        "sample_loss_percent_max",
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _y_limits(rows: list[dict[str, Any]]) -> tuple[float, float]:
    values = [float(row["energy_total_mJ_mean"]) for row in rows]
    return (
        10 ** math.floor(math.log10(min(values) * 0.75)),
        10 ** math.ceil(math.log10(max(values) * 1.25)),
    )


def _energy_coordinates(rows: list[dict[str, Any]]) -> list[str]:
    lines = [r"  error bars/.cd, y dir=both, y explicit,", r"] coordinates {"]
    for row in sorted(rows, key=lambda item: item["payload_bytes"]):
        lines.append(
            f"  ({_number(row['payload_bytes'])},{_number(row['energy_total_mJ_mean'])}) "
            f"+- (0,{_number(float(row['energy_total_uJ_stdev']) / 1000.0)})"
        )
    lines.append(r"};")
    return lines


def _energy_document_start(
    rows: list[dict[str, Any]], sizes: list[int], groups: int
) -> list[str]:
    ymin, ymax = _y_limits(rows)
    ticks = ",".join(_number(size) for size in sizes)
    width = 5.7 if groups >= 3 else 7.2
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
        rf"  group style={{group size={groups} by 1, horizontal sep=1.25cm}},",
        rf"  width={width}cm, height=6.2cm,",
        r"  xmode=log, log basis x={2}, ymode=log, log basis y={10},",
        rf"  ymin={_number(ymin)}, ymax={_number(ymax)},",
        rf"  xtick={{{ticks}}}, xticklabels={{{ticks}}},",
        r"  x tick label style={rotate=45, anchor=east, font=\small},",
        r"  y tick label style={font=\small},",
        r"  grid=both, minor grid style={gray!15}, major grid style={gray!35},",
        r"  xlabel={Logical transfer size [B]},",
        r"  every axis plot/.append style={line width=1.05pt},",
        r"  error bars/error bar style={line width=0.35pt},",
        r"  legend style={font=\small, draw=none, fill=none, at={(0.5,-0.29)},",
        r"    anchor=north, legend columns=-1},",
        r"]",
    ]


def _energy_document_end(module: str, title: str, note: str, groups: int) -> list[str]:
    center = (groups + 1) // 2
    return [
        r"\end{groupplot}",
        rf"\node[font=\bfseries\large] at ($(group c{center}r1.north)+(0,0.85cm)$)",
        rf"  {{{module}: {title}}};",
        r"\node[font=\footnotesize, align=center, text width=18.5cm]",
        rf"  at ($(group c{center}r1.south)+(0,-3.15cm)$)",
        rf"  {{{note}}};",
        r"\end{tikzpicture}",
        r"\end{document}",
        "",
    ]


def _write_tx_tex(
    path: Path,
    tx_rows: list[dict[str, Any]],
    sizes: list[int],
    powers: list[float],
    rates: list[float],
    module: str,
    frame_limit: int,
    title: str,
) -> None:
    lines = _energy_document_start(tx_rows, sizes, len(powers))
    legend_power = powers[len(powers) // 2]
    for power in powers:
        ylabel = r", ylabel={Mean total energy [mJ]}" if power == powers[0] else ""
        lines.append(
            rf"\nextgroupplot[title={{\(P_{{\mathrm{{TX}}}}={_latex_number(power)}\,\mathrm{{dBm}}\)}}{ylabel}]"
        )
        for index, rate in enumerate(rates):
            points = [
                row for row in tx_rows
                if row["tx_power_dbm"] == power and row["bit_rate_kbps"] == rate
            ]
            lines.extend(
                [
                    r"\addplot+[",
                    rf"  color={COLORS[index % len(COLORS)]}, {LINE_STYLES[index % len(LINE_STYLES)]}, mark={MARKERS[index % len(MARKERS)]}, mark size=2.2pt,",
                    *_energy_coordinates(points),
                ]
            )
            if power == legend_power:
                lines.append(rf"\addlegendentry{{{_latex_number(rate)} kbps}}")
    note = (
        f"Mean of 5 repetitions; error bars show standard deviation. Logical transfers "
        f"above {frame_limit} B are fragmented into physical frames of at most "
        f"{frame_limit} B; both axes are logarithmic."
    )
    lines.extend(_energy_document_end(module, title, note, len(powers)))
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_tx_rx_tex(
    path: Path,
    tx_rows: list[dict[str, Any]],
    rx_rows: list[dict[str, Any]],
    sizes: list[int],
    rates: list[float],
    power: float,
    module: str,
) -> None:
    plotted = [row for row in tx_rows if row["tx_power_dbm"] == power] + rx_rows
    lines = _energy_document_start(plotted, sizes, len(rates))
    legend_rate = rates[len(rates) // 2]
    for index, rate in enumerate(rates):
        ylabel = r", ylabel={Mean total energy [mJ]}" if index == 0 else ""
        lines.append(rf"\nextgroupplot[title={{{_latex_number(rate)} kbps}}{ylabel}]")
        tx_points = [
            row for row in tx_rows
            if row["tx_power_dbm"] == power and row["bit_rate_kbps"] == rate
        ]
        rx_points = [row for row in rx_rows if row["bit_rate_kbps"] == rate]
        lines.extend(
            [
                r"\addplot+[color=blue!75!black, solid, mark=*, mark size=2.2pt,",
                *_energy_coordinates(tx_points),
            ]
        )
        if rate == legend_rate:
            lines.append(rf"\addlegendentry{{TX at {_latex_number(power)} dBm}}")
        lines.extend(
            [
                r"\addplot+[color=red!75!black, dashed, mark=square*, mark size=2.2pt,",
                *_energy_coordinates(rx_points),
            ]
        )
        if rate == legend_rate:
            lines.append(rf"\addlegendentry{{RX, stimulus at {_latex_number(power)} dBm}}")
    note = (
        "Mean of 5 repetitions; error bars show standard deviation. RX energy includes "
        "receiver activation, reception, and processing of all physical frames."
    )
    lines.extend(_energy_document_end(module, "TX--RX comparison", note, len(rates)))
    path.write_text("\n".join(lines), encoding="utf-8")


def _continuous_steps(manifest: dict[str, Any]) -> tuple[Path, Path, list[Path]]:
    tx: Path | None = None
    rx_by_rate: dict[float, Path] = {}
    for step in manifest["steps"]:
        if step.get("result_kind") != "continuous":
            continue
        result = Path(step["accepted_result"])
        with (result / "summary.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise ValueError(f"Empty continuous result: {result}")
        direction = rows[0]["measurement_direction"]
        rates = {float(row["bit_rate_kbps"]) for row in rows}
        if len(rates) != 1:
            raise ValueError(f"Mixed rates in continuous result: {result}")
        rate = rates.pop()
        if direction == "tx":
            tx = result
        elif direction == "rx":
            rx_by_rate[rate] = result
    if tx is None or not rx_by_rate:
        raise ValueError("Missing accepted continuous TX or RX results")
    with (tx / "summary.csv").open(encoding="utf-8", newline="") as stream:
        tx_rate = float(next(csv.DictReader(stream))["bit_rate_kbps"])
    if tx_rate not in rx_by_rate:
        raise ValueError("No RX sweep matches the continuous TX rate")
    return tx, rx_by_rate[tx_rate], [rx_by_rate[rate] for rate in sorted(rx_by_rate)]


def _read_loss_rows(result_dirs: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result_dir in result_dirs:
        metadata = json.loads((result_dir / "metadata.json").read_text(encoding="utf-8"))
        if metadata.get("measurement_direction") != "rx":
            raise ValueError(f"Not an RX continuous result: {result_dir}")
        with (result_dir / "summary.csv").open(encoding="utf-8", newline="") as stream:
            for raw in csv.DictReader(stream):
                transmitted = int(float(raw["frames_transmitted"]))
                received = int(raw["frames_received"])
                loss = float(raw["frame_loss_percent"])
                row = {
                    "bit_rate_kbps": float(raw["bit_rate_kbps"]),
                    "tx_power_dbm": float(raw["tx_power_dbm"]),
                    "frames_transmitted": transmitted,
                    "frames_received": received,
                    "frames_lost": transmitted - received,
                    "frame_loss_percent": loss,
                    "delivery_percent": 100.0 - loss,
                    "requested_duration_s": float(raw["requested_duration_s"]),
                    "frame_bytes": int(raw["frame_bytes"]),
                    "inter_frame_gap_ms": int(raw["inter_frame_gap_ms"]),
                    "status": raw["status"],
                    "source_directory": result_dir.name,
                }
                if row["status"] != "ok" or not 0 <= loss <= 100:
                    raise ValueError(f"Invalid loss result: {row}")
                rows.append(row)
    rows.sort(key=lambda row: (row["tx_power_dbm"], row["bit_rate_kbps"]))
    powers = {row["tx_power_dbm"] for row in rows}
    rates = {row["bit_rate_kbps"] for row in rows}
    expected = {(power, rate) for power in powers for rate in rates}
    actual = {(row["tx_power_dbm"], row["bit_rate_kbps"]) for row in rows}
    if actual != expected or len(rows) != len(expected):
        raise ValueError("Incomplete or duplicate continuous loss matrix")
    return rows


def _style_sheet(sheet) -> None:
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in sheet[1]:
        cell.fill = fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for index, column in enumerate(sheet.columns, start=1):
        width = min(60, max(len(str(cell.value or "")) for cell in column) + 2)
        sheet.column_dimensions[get_column_letter(index)].width = width


def _write_loss_reports(base: Path, rows: list[dict[str, Any]], module: str) -> None:
    csv_path = base.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=LOSS_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    powers = sorted({row["tx_power_dbm"] for row in rows})
    rates = sorted({row["bit_rate_kbps"] for row in rows})
    workbook = Workbook()
    results = workbook.active
    results.title = "loss_results"
    results.append(LOSS_FIELDS)
    for row in rows:
        results.append([row[field] for field in LOSS_FIELDS])
    _style_sheet(results)
    matrix = workbook.create_sheet("loss_matrix_percent")
    matrix.append(["TX power [dBm]", *rates])
    by_key = {(row["tx_power_dbm"], row["bit_rate_kbps"]): row for row in rows}
    for power in powers:
        matrix.append([power, *(by_key[(power, rate)]["frame_loss_percent"] for rate in rates)])
    _style_sheet(matrix)
    workbook.save(base.with_suffix(".xlsx"))

    ticks = ",".join(_number(rate) for rate in rates)
    labels = ",".join(_latex_number(rate) for rate in rates)
    maximum = max(row["frame_loss_percent"] for row in rows)
    ymax = min(100, max(10, math.ceil(maximum * 1.25 / 5) * 5))
    xmin = min(rates) / 1.5
    xmax = max(rates) * 1.5
    lines = [
        r"\documentclass[tikz,border=6pt]{standalone}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage{pgfplots}",
        r"\pgfplotsset{compat=1.18}",
        r"\begin{document}",
        r"\begin{tikzpicture}",
        r"\begin{axis}[width=12.5cm, height=7.4cm,",
        rf"  title={{{module}: packet loss versus radio rate}},",
        r"  xmode=log, log basis x=10,",
        rf"  xmin={_number(xmin)}, xmax={_number(xmax)}, xtick={{{ticks}}},",
        rf"  xticklabels={{{labels}}}, ymin=0, ymax={_number(ymax)},",
        r"  xlabel={Radio rate [kbps]}, ylabel={Lost frames [\%]},",
        r"  grid=both, minor grid style={gray!15}, major grid style={gray!35},",
        r"  every axis plot/.append style={line width=1.25pt, mark size=2.8pt},",
        r"  legend style={draw=none, fill=white, fill opacity=0.85, text opacity=1,",
        r"    at={(0.03,0.97)}, anchor=north west, legend columns=1},",
        r"]",
    ]
    for index, power in enumerate(reversed(powers)):
        selected = [row for row in rows if row["tx_power_dbm"] == power]
        coordinates = " ".join(
            f"({_number(row['bit_rate_kbps'])},{_number(row['frame_loss_percent'])})"
            for row in selected
        )
        lines.append(
            rf"\addplot+[{COLORS[index % len(COLORS)]}, {LINE_STYLES[index % len(LINE_STYLES)]}, mark={MARKERS[index % len(MARKERS)]}] coordinates {{{coordinates}}};"
        )
        lines.append(rf"\addlegendentry{{{_latex_number(power)} dBm}}")
    lines.extend(
        [
            r"\end{axis}",
            r"\node[font=\footnotesize, align=center, text width=12cm, anchor=north]",
            r"  at ([yshift=-1.45cm]current axis.south)",
            r"  {60 s per point; 32 B frames; 15 ms inter-frame gap.};",
            r"\end{tikzpicture}",
            r"\end{document}",
            "",
        ]
    )
    base.with_suffix(".tex").write_text("\n".join(lines), encoding="utf-8")


def _copy_provenance(manifest_path: Path, output_dir: Path) -> None:
    destination = output_dir / "campaign_logs"
    destination.mkdir(parents=True, exist_ok=True)
    session_dir = manifest_path.parent
    for name in ("manifest.json", "session.log", "codex_callback.log"):
        source = session_dir / name
        if source.exists():
            shutil.copy2(source, destination / name)
    source_logs = session_dir / "logs"
    if source_logs.exists():
        shutil.copytree(source_logs, destination / "attempts", dirs_exist_ok=True)


def generate(manifest_path: Path, output_dir: Path, base_name: str) -> list[Path]:
    manifest = _read_manifest(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    tx_rows, tx_summary, tx_metadata = _collect_packet_results(manifest, "tx")
    rx_rows, rx_summary, rx_metadata = _collect_packet_results(manifest, "rx")
    repetitions = int(manifest["config"]["repetitions"])
    sizes, powers, rates, rx_power, module, frame_limit = _validate_energy_matrix(
        tx_rows, rx_rows, repetitions
    )
    base = output_dir / base_name
    tx_base = base.with_name(base.name + "_tx")
    rx_base = base.with_name(base.name + "_rx")
    large_base = base.with_name(base.name + "_payload_128_512_1024")
    tx_campaign_metadata = _campaign_metadata(
        tx_metadata, "tx", sizes, powers, rates
    )
    rx_campaign_metadata = _campaign_metadata(
        rx_metadata, "rx", sizes, [rx_power], rates
    )
    write_transfer_csv(tx_base.with_suffix(".csv"), tx_rows)
    write_transfer_xlsx(
        tx_base.with_suffix(".xlsx"), tx_rows, tx_summary, tx_campaign_metadata
    )
    write_transfer_csv(rx_base.with_suffix(".csv"), rx_rows)
    write_transfer_xlsx(
        rx_base.with_suffix(".xlsx"), rx_rows, rx_summary, rx_campaign_metadata
    )
    large_rows = [row for row in tx_rows if row["payload_bytes"] >= 128]
    large_summary = [row for row in tx_summary if int(row["payload_bytes"]) >= 128]
    write_transfer_csv(large_base.with_suffix(".csv"), large_rows)
    write_transfer_xlsx(
        large_base.with_suffix(".xlsx"),
        large_rows,
        large_summary,
        tx_campaign_metadata,
    )
    _write_energy_data(
        base.with_name(base.name + "_data").with_suffix(".csv"),
        sorted(
            tx_rows + rx_rows,
            key=lambda row: (
                row["measurement_direction"],
                row["tx_power_dbm"],
                row["bit_rate_kbps"],
                row["payload_bytes"],
            ),
        ),
    )
    _write_energy_data(
        base.with_name(base.name + "_energy_vs_payload_data").with_suffix(".csv"),
        tx_rows,
    )
    _write_tx_tex(
        base.with_name(base.name + "_tx_energy").with_suffix(".tex"),
        tx_rows, sizes, powers, rates, module, frame_limit, "TX energy",
    )
    _write_tx_tex(
        base.with_name(base.name + "_energy_vs_payload").with_suffix(".tex"),
        tx_rows, sizes, powers, rates, module, frame_limit,
        "energy versus logical payload",
    )
    _write_tx_rx_tex(
        base.with_name(base.name + "_tx_rx_energy").with_suffix(".tex"),
        tx_rows, rx_rows, sizes, rates, rx_power, module,
    )

    continuous_tx, continuous_rx, loss_dirs = _continuous_steps(manifest)
    tx_continuous_rows, tx_continuous_metadata = continuous_report.read_session(
        continuous_tx
    )
    rx_continuous_rows, rx_continuous_metadata = continuous_report.read_session(
        continuous_rx
    )
    continuous_report.validate(
        tx_continuous_rows,
        tx_continuous_metadata,
        rx_continuous_rows,
        rx_continuous_metadata,
    )
    continuous_base = base.with_name(base.name + "_continuous")
    continuous_rows = sorted(
        tx_continuous_rows + rx_continuous_rows,
        key=lambda row: (row["measurement_direction"], row["tx_power_dbm"]),
    )
    continuous_report.write_csv(continuous_base.with_suffix(".csv"), continuous_rows)
    continuous_report.write_xlsx(
        continuous_base.with_suffix(".xlsx"),
        tx_continuous_rows,
        rx_continuous_rows,
        tx_continuous_metadata,
        rx_continuous_metadata,
    )
    continuous_report.write_power_tex(
        continuous_base.with_name(continuous_base.name + "_average_power").with_suffix(".tex"),
        tx_continuous_rows,
        rx_continuous_rows,
        module,
    )
    continuous_report.write_delivery_tex(
        continuous_base.with_name(continuous_base.name + "_rx_delivery").with_suffix(".tex"),
        rx_continuous_rows,
        module,
    )
    loss_rows = _read_loss_rows(loss_dirs)
    _write_loss_reports(
        base.with_name(base.name + "_loss_vs_rate"), loss_rows, module
    )
    _copy_provenance(manifest_path, output_dir)
    return sorted(path for path in output_dir.rglob("*") if path.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate compact reports from an unattended web campaign"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--base-name", required=True)
    args = parser.parse_args()
    outputs = generate(args.manifest, args.output_dir, args.base_name)
    for output in outputs:
        print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
