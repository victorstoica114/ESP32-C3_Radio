# RA-01 SX1278-Shielded campaign validation

## Verdict

The campaign is accepted after targeted recovery of the two failed continuous
SF9 batches. Packet energy, continuous power and PPK2 capture quality are
consistent. The measured continuous-frame loss is real and repeatable, but its
near-independence from TX power indicates a receiver throughput/rearm limitation
under the 15 ms continuous-test gap rather than an RF link-budget or shielding
failure.

## Campaign identity and coverage

- Session: `20260719_070906_campaign_radio_sx1278_shielded`
- Measured device: COM22; peer: COM21; PPK2: COM11
- PPK2 mode: Ampere Meter, with the DUT powered externally
- Profile: `RADIO_SX1278_SHIELDED` (`RADIO_RA01_SX1278 + AT_COMMANDS`)
- Axes: -4, +10 and +20 dBm; SF7, SF9 and SF12; 125 kHz bandwidth
- Payloads: 8, 32 and 128 B; five packet repetitions per point
- Packet coverage: 36 points and 180 captures
- Continuous coverage: 12 points of 60 s each

## Targeted recovery

The original unattended run accepted 38/40 batches. Both failed batches were
the multi-power SF9 continuous sweeps. After a valid first power point, the
SX1278 AT session stopped acknowledging the next `AT+PWR` command. Repeating the
same sweep without changing the session lifecycle reproduced the timeout.

The profiler now closes, reopens and fully restores both LoRa AT sessions
between continuous power levels for all three SX1278 physical variants. The
recovered TX and RX sweeps completed all six SF9 points with zero UART errors.
`recovery_overrides.json` records exactly which result directories replace the
two failed batches; the original manifest and every failed attempt log remain
unchanged in the provenance directory.

## Packet quality checks

- Current event detected: 180/180 captures
- Highest within-condition energy coefficient of variation: 0.398957%
- Maximum packet-capture sample loss: 0.525714%
- No payload-energy or TX-power energy inversion was found.
- Two isolated packet losses occurred in the original 180 captures:
  - TX, SF12, +20 dBm, 32 B: 4/5 observed by the peer
  - RX, SF9, +20 dBm, 128 B: 4/5 observed by the measured receiver
- Exact-setting controls received 20/20 packets for each case. The TX control
  averaged 558873.948 uJ and the RX control averaged 28105.817 uJ. The original
  losses are preserved in the campaign tables and classified as isolated.

## Continuous-test finding

- Maximum continuous-capture sample loss: 0.002494%
- Measured frame loss range: 21.7778% to 27.2727%
- SF7: 21.78% to 22.00% loss across all three powers
- SF9: 26.35% to 27.03% loss across all three powers
- SF12: 22.73% to 27.27%; with only 22 frames per point, one frame changes the
  percentage by 4.55 points

The absence of an improving trend from -4 to +20 dBm, together with the same
delivery band at every SF, is evidence against weak RF power or the shield as
the cause. The result is consistent with the controlled receiver not being
ready for every frame at the 15 ms host gap. This is an inference from the
measured pattern; the loss values remain reported without correction.

## Deliverables

The directory contains CSV and XLSX tables for TX, RX, continuous power and
loss versus effective payload speed, plus LaTeX, PDF and PNG versions of four
graphs. `campaign_logs` contains the original manifest, all 44 unattended
attempt logs, the callback log, the recovery override and summary/metadata for
all targeted recovery and diagnostic runs. Raw PPK2 traces remain in the source
web session.
