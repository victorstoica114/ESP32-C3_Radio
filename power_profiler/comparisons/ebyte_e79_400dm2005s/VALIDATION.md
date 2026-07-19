# Ebyte E79-400DM2005S campaign validation

## Verdict

The campaign is accepted. All 176 planned steps completed and the measurements
show no systematic RF or metrology anomaly. One packet was not observed by the
peer at the weakest IEEE154G50 setting; a targeted 20-repetition control and a
60-second continuous control both passed without loss, so the event is retained
as an isolated packet loss rather than rewritten or hidden.

## Campaign identity and coverage

- Session: `20260719_003026_campaign_radio_ebyte_e79_cc1352p`
- Interval: 2026-07-18 21:30:26 UTC to 23:47:40 UTC
- Firmware requirement: E79 modem firmware 0.3.0
- Measured device: COM5; peer: COM13; PPK2: COM11
- PPK2 mode: Ampere Meter, with the DUT powered externally
- Completed steps: 176/176; failed steps: 0
- Attempts: 178. Two host-command timeouts recovered automatically on their
  second attempt: TX GFSK4K8, 0 dBm, 128 B and RX GFSK4K8, +13 dBm, 8 B.
- Packet TX: 630 captures across seven RF profiles, three TX powers and six
  logical payload sizes
- Packet RX: 210 captures across seven RF profiles and six logical payload sizes
- Continuous tests: 24 measurements: three TX points and 21 RX points
- Continuous RX profiles: SLR2K5, GFSK4K8, OOK4K8, SLR5, GFSK50,
  IEEE154G50 and GFSK200

## Quality checks

- Current event detected: 840/840 packet captures
- Packet-capture sample loss: at most 0.294737%
- Continuous-capture sample loss: at most 0.002494%
- Highest within-condition energy coefficient of variation: 1.610740%
  (TX IEEE154G50, 0 dBm, 512 B)
- No payload-energy inversion was found.
- No TX-power energy inversion was found.
- Continuous RF frame loss: 0% at every RF profile and TX power.

## Reviewed deviations

### Isolated IEEE154G50 packet loss

The original packet batch at IEEE154G50, -20 dBm and 64 B received 4/5 packets.
The missing repetition had a normal detected current event and energy consistent
with the other repetitions; the batch mean was 293.281 uJ with 1.087% CV.

The targeted control at the exact same setting received 20/20 packets. Its
measured energy ranged from 287.237 to 302.878 uJ, with a 292.395 uJ mean. The
independent 60-second continuous control received 1817/1817 frames. There is no
evidence of a repeatable link, configuration or measurement fault at this
setting.

### Host UART acknowledgements

Two continuous runs reported one lost modem acknowledgement each:

- TX SLR2K5 at 0 dBm: 239 frames attempted, `SERIAL_ERRORS=1`
- RX GFSK50 at +13 dBm: 1853/1853 frames received, `SERIAL_ERRORS=1`

The second run proves that the RF command executed despite the missing UART
reply. These are classified as host-to-modem acknowledgement losses, not RF
frame losses.

## Deliverables

The directory contains CSV and XLSX tables for packet TX, packet RX, large
payloads, continuous power and loss versus rate, plus LaTeX, PDF and PNG versions
of all six comparative graphs. `campaign_logs` preserves the manifest, session
log, callback log and all 178 attempt logs. `diagnostics` preserves the targeted
20-repetition control summary and metadata.

The continuous power graph compares matching SLR2K5 TX and RX measurements. The
continuous CSV/XLSX files retain all 24 continuous measurements, while the
loss-versus-rate graph covers all seven RF profiles at -20, 0 and +13 dBm.
