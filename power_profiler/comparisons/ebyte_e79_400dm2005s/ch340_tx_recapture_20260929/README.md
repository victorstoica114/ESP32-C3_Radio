# E79 CH340 fragmented-TX RAW recapture (2026-09-29)

Independent follow-up, 30 September: [all 315 RAW traces and archived energies were verified](../../../audits/2026-09-30/README.md). The [separate CH340 supplement](../../ebyte_e79_ch340_20260929/README.md) contains CSV/XLSX exports and matched ESP32 figures. The historical CH9340C series remains a different hardware context.

The complete bench session, including all 315 accepted 100 kS/s PPK2 RAW
captures and every interrupted diagnostic attempt, is published as the GitHub
Release asset
[`e79_ch340_tx_recapture_20260929_full_session.zip`](https://github.com/victorstoica114/ESP32-C3_Radio/releases/download/e79-ch340-tx-recapture-20260929/e79_ch340_tx_recapture_20260929_full_session.zip).

The original recapture plan named the historical CH9340C fixture. Before the
accepted captures, both USB-UART adapters were physically replaced with CH340
adapters because the mixed fixture did not provide a reliable 1 Mbaud link.
This hardware deviation is explicit in the archive's `BENCH_NOTES.md`; the
radio, firmware, PPK2 path, voltage, RF matrix, and integration method remain
the planned E79 campaign.

## Accepted matrix

- Profile: `RADIO_EBYTE_E79_CC1352P`, TX, firmware `E79_AT_MODEM 0.3.0`.
- UART: 1,000,000 baud; PPK2 Ampere mode: 100 kS/s; real supply: 3.3 V.
- PHYs: `GFSK4K8`, `GFSK50`, `GFSK200`, `SLR2K5`, `SLR5`, `OOK4K8`,
  `IEEE154G50`.
- Powers: -20, 0, +13 dBm; payloads: 128, 512, 1024 bytes; five repetitions.
- Exact result: 315/315 captures and RAW files, 245 `ok`, 70 preserved
  `rx_missing`, no accepted analysis/radio/no-event errors.
- Every accepted row uses `per_frame_modeled_airtime_v1` with exact 2/8/16
  disjoint frame windows. The reported energy is the sum of those modeled RF
  windows, not the entire host/UART transaction.
- Maximum reported sample loss: 0.8336842105263158%.

Accepted directories inside the archive:

- `lot45_gfsk200_consensus/20260929_185646_radio_ebyte_e79_cc1352p`
  (45 rows: 37 `ok`, 8 `rx_missing`).
- `lot270_other_profiles_final_candidate2/20260929_193856_radio_ebyte_e79_cc1352p`
  (270 rows: 208 `ok`, 62 `rx_missing`).

Both lots passed the exact matrix/RAW gzip CRC/sample-count/window validator.
Representative slow, low-power, and fast traces were visually inspected; the
HTML and PNG inspection artifacts are included in the archive.

## Integrity

- Release archive size: 766,800,352 bytes.
- Release archive SHA-256:
  `fe09b18b6332ba34362133ab4ca97297633f2f786a21d0af6377544787e6068a`.
- `SESSION_MANIFEST_SHA256.csv` SHA-256:
  `d79432dc03c19153fab5ff6930b721d385b6f51d5eb28db0840ea44d90b8eb54`.
- The versioned copy of the file-level manifest is
  [`SESSION_MANIFEST_SHA256.csv`](SESSION_MANIFEST_SHA256.csv).

The manifest covers 1,109 files and 780,378,622 uncompressed bytes. Four live
PPK2-holder log files (two empty stderr files and two 55-byte `READY` stdout
files) are intentionally excluded so both DUT paths could remain continuously
ON; `SESSION_TRANSFER_README.txt` and `BENCH_NOTES.md` record this explicitly.
No measurement, RAW, analysis, metadata, summary, aggregate, campaign console
log, or inspection artifact is excluded.

The campaign started from repository commit
`26e8aadf9d234556090d67f227b271e70b8d60eb`. The Release tag points to the
commit containing the detector qualification, PPK2 continuous-hold behavior,
terminal-status stop option, warm-up retry bound, tests, and this index.
