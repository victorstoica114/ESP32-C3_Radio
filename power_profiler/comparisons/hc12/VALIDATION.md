# HC-12 campaign validation

Authoritative campaign: `20260719_233346_campaign_radio_hc12`

## Verdict

The HC-12 measurement set is complete and accepted for packet-energy,
continuous average-power, continuous delivery, and loss-versus-rate analysis.
The accepted virtual manifest contains all 40/40 campaign batches with no
failed step. All known invalid or incomplete measurements were diagnosed and
excluded through seven explicit recovery overrides. Their logs and compact
summaries remain available for provenance, while rejected raw captures were
removed during post-validation cleanup.

No additional hardware rerun is required. The authoritative packet set has
zero missing transfers, and the authoritative continuous RX set received all
2,713 of 2,713 logical frames across the three radio rates and three stimulus
powers.

## Configuration and coverage

- Profile: `RADIO_HC12`, channel 10, with HC-12 FU4 at 0.5 kbps, FU3 at
  15 kbps, and FU1 at 250 kbps.
- Configured TX powers: -1, +8, and +20 dBm (HC-12 levels P1, P4, and P8).
- Measured DUT: COM39; peer: COM40; PPK2: COM11 in Ampere Meter mode at
  3300 mV. The DUT remained externally powered while the VIN-to-VOUT current
  path was guarded.
- Packet TX: 27 aggregate points and 135 raw captures across three payloads
  (8, 32, and 60 B), three rates, and three TX powers.
- Packet RX: 9 aggregate points and 45 raw captures at +20 dBm.
- Continuous tests: three TX-power points at 15 kbps and nine RX
  power/rate points, each using a 60 s active window.
- Accepted raw coverage: 192/192 gzip traces, comprising 180 packet and 12
  continuous captures. Every stream was decompressed fully and passed its
  gzip CRC check: 693,751,776 compressed bytes and 4,028,958,667
  uncompressed bytes.

## Integrity checks

- FU3 bidirectional AT/RF channel-isolation diagnostic: 18/18 checks passed.
- FU4 bidirectional AT/RF channel-isolation diagnostic: 18/18 checks passed.
- Corrected FU1 bidirectional AT/RF channel-isolation diagnostic: 18/18
  checks passed.
- Authoritative quick check: 4/4 batches passed; measured peak current was
  63.666 mA.
- Packet current events: 180/180 detected.
- Packet delivery: 180/180 transfers received, with zero packet loss.
- Continuous rows: 12/12 have status `ok`, a 60 s active analysis window,
  and zero transmitter serial errors.
- Maximum packet-energy coefficient of variation: 8.566954%.
- Maximum packet-capture PPK2 sample loss: 0.294737%.
- Maximum continuous-capture PPK2 sample loss: 0.002494%.
- All 40 accepted metadata files identify COM39, COM11, 3300 mV,
  100 ksample/s, raw capture enabled, and the HC-12 profile.

The largest energy variation occurred for 32 B FU4 TX at +8 dBm. All five
packets were received and their current peaks were consistent, while the
detected active durations varied as the HC-12 buffered and emitted slow FU4
bursts. The maximum PPK2 sample loss for that point was only 0.281%, so this
variation is retained as measured rather than treated as a corrupt capture.

## Diagnosed campaign anomalies

The first quick check exposed two profile assumptions that were not valid for
this HC-12 pair. Leaving FU4 must first restore FU3 before changing the UART
to 9600 baud, and re-entering AT mode requires at least the documented 200 ms
transition delay. The firmware now waits 220 ms and the profile applies the
correct transition order.

FU4 also showed a repeatable 1.655--1.661 s end-to-end delay for a 30-byte
line. The former 150 ms peer-confirmation allowance therefore marked three
8-byte TX points as missing even though RF transmission was occurring. Those
three points were rerun with the measured 1.5 s post-airtime allowance and
all 15/15 transfers were confirmed.

The initial FU1 continuous-RX attempt used a 50 ms host gap and received only
about 0.2% of transmitted logical frames. A dedicated pacing sweep established
that 50 ms overdrives the UART/radio buffering path, while 75, 100, 125, 150,
and 200 ms produced zero loss. The authoritative FU1 result uses a 100 ms gap
and received 1,471/1,471 frames. This was a test-pacing artifact, not an RF,
power-level, or PPK2 failure.

## Continuous average power

The TX comparison uses the common 15 kbps FU3 profile.

| Direction / configured TX power | Mean current | Mean electrical power | 60 s energy |
|---|---:|---:|---:|
| TX, -1 dBm | 18.295 mA | 60.374 mW | 3622.452 mJ |
| TX, +8 dBm | 23.424 mA | 77.299 mW | 4637.918 mJ |
| TX, +20 dBm | 31.185 mA | 102.909 mW | 6174.558 mJ |
| RX, -1 dBm stimulus | 17.105 mA | 56.448 mW | 3386.858 mJ |
| RX, +8 dBm stimulus | 17.075 mA | 56.347 mW | 3380.798 mJ |
| RX, +20 dBm stimulus | 17.088 mA | 56.390 mW | 3383.427 mJ |

The RX current is essentially independent of the peer's configured TX power,
while TX current rises monotonically with output power. At 15 kbps, RX is
lower than TX even at the -1 dBm setting for this module pair.

## Continuous RX delivery and mode current

| HC-12 mode / rate | Frames at -1 dBm | Frames at +8 dBm | Frames at +20 dBm | Mean RX-current range |
|---|---:|---:|---:|---:|
| FU4 / 0.5 kbps | 20/20 | 20/20 | 20/20 | 16.424--16.436 mA |
| FU3 / 15 kbps | 394/394 | 394/394 | 394/394 | 17.075--17.105 mA |
| FU1 / 250 kbps | 490/490 | 491/491 | 490/490 | 12.478--12.485 mA |

All authoritative loss values are 0%. These delivery results characterize
the present short-range bench setup and should not be interpreted as a range
or sensitivity limit.

## Post-validation cleanup

The cleanup performed on 2026-07-20 removed 48 superseded, rejected, or
duplicate raw traces and approximately 575.7 MiB of non-authoritative session
data. This comprised 20 traces from the superseded initial quick check, 21
superseded/rejected traces from the main campaign, and seven traces from the
auxiliary callback-recovery session.

The authoritative set remains unchanged at 192/192 gzip traces and
693,751,776 compressed bytes. All campaign, quick-check, callback, attempt,
and diagnostic logs were retained. Compact summaries for rejected continuous
runs are grouped under `campaign_logs/rejected_results`; duplicate copies of
accepted recovery summaries were removed.

## Deliverables

- Consolidated CSV and XLSX files for packet TX, packet RX, continuous power,
  delivery, and loss versus radio rate.
- Six LaTeX sources and matching dependency-free PDF/PNG renderings.
- Campaign manifest, session and callback logs, every campaign attempt log,
  both quick-check histories, authoritative recovery metadata/summaries,
  compact rejected-result summaries, and all five HC-12 diagnostic logs.

The local MiKTeX installation has not completed its first-run setup, so the
LaTeX sources could not be compiled locally. The dependency-free renderer
produced valid PDF and PNG files, and all six PNG plots were inspected
visually.
