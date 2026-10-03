# E79 CH340 fragmented-TX supplement, 29 September 2026

This separate dataset contains **315 measured attempts, 63 configurations and seven PHYs**, with five attempts at each combination of -20/0/+13 dBm and 128/512/1024 bytes. Both adapters were physically replaced by CH340 units. These observations do not replace historical CH9340C data or supply its missing all-frame measurements. No 8/32/64-byte CH340, RX or continuous values are synthesized.

The accepted measured E79 DUT is **COM16 through PPK2 COM13**, with COM4 as peer, following the documented switch from the initial COM4/PPK2 COM12 path. The adapter and measured-unit/session changes prevent an isolated USB-bridge causal comparison. Converter supply power is outside the measured radio-module boundary. Firmware was E79 AT modem 0.3.0, UART 1 Mbaud, declared/measured supply 3.3 V and PPK2 Ampere mode at 100 kS/s; see [the original bench notes](source_lots/BENCH_NOTES.md).

## Results and interpretation

- **245 `ok` and 70 `rx_missing`** are retained. No measured RF-loss attempt was removed or retried selectively in the accepted lots. Entire earlier diagnostic/aborted attempts remain in the release archive and are not pooled into these results.
- The metric sums 2/8/16 disjoint modeled-airtime windows around detected current bursts. It excludes inter-frame host/UART/ACK gaps and is not full-transaction energy. `event_duration_ms` is summed window length, not wall-clock transfer span. Excess energy subtracts the pre-trigger baseline within these windows; it is not independently measured standby energy.
- Independent full-RAW verification reproduced all 315 archived energies and all 315 windows; current analyzer results are valid for all 315. Maximum reported sample loss is 0.833684%; unavailable samples are not reconstructed.
- Primary 4-MAD consensus selected 312 traces. Runs 00009 and 00012 in the 270-run lot use the qualified long-frame low-signal bracket; run 00264 uses the high-signal bracket. Their original diagnostics and inspection PNGs are retained under `evidence/`. The three traces were visually reviewed against their saved windows. Arithmetic agreement and charge-based segmentation do not establish synchronized RF boundaries.
- The ESP32 comparator retains its published values. Re-running its 315 fragmented RAW traces with the new detector accepts all 315, keeps 294 windows identical and changes 21 SLR2K5 windows; the maximum total-energy difference is 0.001543018%. This method sensitivity remains a comparison limit, not a PPK uncertainty estimate. No ESP32 exports were replaced.

GFSK200 at +13 dBm (means of all five attempts):

| Payload [B] | CH340 window energy [mJ] | Published ESP32 [mJ] | CH340/ESP32 | CH340 received |
| --- | --- | --- | --- | --- |
| 128 | 0.326386 | 0.304150 | 1.0731 | 4/5 |
| 512 | 1.322129 | 1.204723 | 1.0975 | 5/5 |
| 1024 | 2.629776 | 2.410810 | 1.0908 | 3/5 |

## Artifacts

- [`e79_ch340_tx.csv`](e79_ch340_tx.csv), [`e79_ch340_tx.xlsx`](e79_ch340_tx.xlsx): 63 condition aggregates; the workbook contains all 315 summary rows with `source_lot` and globally unique `source_run_key` because run IDs repeat between lots. The PHY-aware matrix has 21 power/PHY rows.
- [`e79_ch340_summary_runs.csv`](e79_ch340_summary_runs.csv): all 315 attempts and recorded delivery telemetry.
- [`e79_ch340_vs_esp32.csv`](e79_ch340_vs_esp32.csv): 63 matched configurations with total/excess energy, standard deviation, loss, compatible modeled duration and voltage, and ratios.
- [`e79_ch340_tx_energy.pdf`](e79_ch340_tx_energy.pdf), [`e79_ch340_vs_esp32.pdf`](e79_ch340_vs_esp32.pdf): TX curves and all 63 matched energy ratios; matching PNG and editable LaTeX files accompany them.
- `source_lots/`: byte-identical original metadata, summary and aggregate files for both accepted lots; bench notes and session file manifest.
- `provenance/`: independent CH340 verification and ESP32 detector-regression summaries/results. The [canonical 30 September audit](../../audits/2026-09-30/) also preserves the release integrity checks and independent proofs. [`publication_manifest.json`](publication_manifest.json) records input, code and output SHA-256 values.

## Source and reproduction

The [complete release archive](https://github.com/victorstoica114/ESP32-C3_Radio/releases/download/e79-ch340-tx-recapture-20260929/e79_ch340_tx_recapture_20260929_full_session.zip) includes all accepted RAW and all diagnostic/aborted attempts. Archive SHA-256: `fe09b18b6332ba34362133ab4ca97297633f2f786a21d0af6377544787e6068a`. Release code commit: `37599a2a5394de9aa3a84432e578dbcaadfd6da2`. This repository supplement does not duplicate the large RAW archive.

After extracting that release and running `tools/verify_e79_ch340_release.py` and the ESP32 regression verification, invoke from the repository root:

```powershell
python -B power_profiler/tools/publish_e79_ch340.py --session <extracted-session> --verification <verification-dir> --archive <release.zip> --esp32-regression <regression-dir>
```

`--validate-only` checks publication gates without writing outputs. Rendering requires `pdflatex` and `mgs`; CSV/XLSX creation requires `openpyxl`. Historical CH9340C/ESP32 comparisons and the main 28-entry study are not modified by this command.
