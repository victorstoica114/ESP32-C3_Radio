# Cross-module radio energy study

This directory contains a reproducible comparison of the 23 measured radio modules and physical variants in `../comparisons`.

## Outputs

- `radio_module_energy_study.tex`: complete manuscript.
- `radio_module_energy_study.pdf`: compiled manuscript when a LaTeX runtime is available.
- `data/module_summary.csv`: normalized cross-module metrics and row-selection metadata.
- `data/payload_energy_summary.csv`: measured TX/RX energy for every tested logical payload size at the selected per-module mode and power.
- `data/cc1101_controlled_summary.csv`: matched CC1101 V1/V2 payload, rate, and continuous-power points.
- `data/matched_continuous_power_summary.csv`: matched E32-band, nRF24L01 PA/LNA, six-board SX1278, and two-board SX1276 continuous sweeps.
- `data/module_catalog.csv`: module, interface, modulation, rate, and power registry.
- `data/e79_profile_summary.csv`: controlled seven-PHY E79 comparison.
- `figures/`: 16 numbered figures delivered as 19 publication-ready plot sheets in PDF and PNG formats; the TX payload, RX payload, and SX1278 continuous-power figures each span two sheets for legibility.
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
