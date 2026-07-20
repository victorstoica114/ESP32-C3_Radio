# Rejected HC-12 results

These compact summaries are retained only for diagnosis and provenance. They
are not consumed by the authoritative campaign reports.

- `20260720_001536_radio_hc12_continuous_rx`: auxiliary FU1 run at a 50 ms
  host gap; approximately 99.88% logical-frame loss.
- `20260720_002223_radio_hc12_continuous_rx`: interrupted FU4 recovery with
  only one of three power points captured.
- `20260720_002419_radio_hc12_continuous_rx`: failed recovery with no valid
  result rows.
- `20260720_004158_radio_hc12_continuous_rx`: diagnostic FU1 repeat at a
  50 ms host gap; approximately 99.76--99.88% logical-frame loss.

The accepted FU1 run uses a 100 ms host gap, the accepted FU4 run contains all
three power points, and both are referenced by `recovery_overrides.json`.
