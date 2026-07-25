# Cross-module radio energy study

This directory contains a reproducible comparison of the 28 measured radio modules, host-interface contexts, and physical variants in `../comparisons`. Twenty-three entries include packet and 60-second continuous campaigns; the five latest entries currently contain packet campaigns only.

## Outputs

- `radio_module_energy_study.tex`: complete manuscript.
- `radio_module_energy_study.pdf`: compiled manuscript when a LaTeX runtime is available.
- `data/module_summary.csv`: normalized cross-module metrics and row-selection metadata.
- `data/payload_energy_summary.csv`: measured TX/RX energy for every tested logical payload size at the selected per-module mode and power.
- `data/cc1101_controlled_summary.csv`: matched CC1101 V1/V2 payload, rate, and continuous-power points.
- `data/e07_controlled_summary.csv`: matched E07 payload- and rate-sweep points.
- `data/cc1101_family_summary.csv`: common 32-byte, 38.4-kbps power sweep for the two earlier CC1101 boards and three E07 modules.
- `data/e79_interface_summary.csv`: E79 observations for the ESP32 and CH9340C host-interface contexts, including the matched TX matrix, matched +13-dBm RX points, and the newer additional RX power sweeps.
- `data/ra08_ra09_summary.csv`: matched Ai-Thinker RA-08 (ASR6601) and Ai-Thinker RA-09 (STM32WLE5) payload and spreading-factor points.
- `data/matched_continuous_power_summary.csv`: matched E32-band, NRF24L01 (nRF24L01+) PA/LNA, six-board SX1278, and two-board SX1276 continuous sweeps.
- `data/module_catalog.csv`: module, interface, modulation, rate, and power registry.
- `data/e79_profile_summary.csv`: controlled seven-PHY E79 comparison.
- `figures/`: 22 numbered figures delivered as 27 publication-ready plot sheets in PDF and PNG formats. The expanded TX and RX payload figures each span three sheets, and the SX1278 continuous-power figure spans two sheets for legibility.
- `tables/`: generated LaTeX tables.

## Regenerate

From the repository root:

```powershell
python power_profiler\study\generate_study.py
Set-Location power_profiler\study
pdflatex -interaction=nonstopmode radio_module_energy_study.tex
pdflatex -interaction=nonstopmode radio_module_energy_study.tex
```

The generator uses only the Python standard library and the existing dependency-free plot renderer in `../tools`.

## Interpretation boundary

The study compares measured module energy and end-to-end delivery under the recorded workloads. Configured TX power is not a conducted RF-power or EIRP measurement, and continuous delivery is not a calibrated sensitivity/PER test. See the manuscript's limitations section before using the results for module selection.
