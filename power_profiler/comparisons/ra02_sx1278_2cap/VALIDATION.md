# RA-02 (SX1278) + 2Cap validation

Authoritative campaign: `20260719_200959_campaign_radio_ra02_sx1278_2cap`

## Test identity

- Profile: `RADIO_RA02_SX1278_2CAP`
- Measured device: COM35
- Peer: COM36
- PPK2: COM11, ampere mode, 3300 mV
- RF configuration: 433 MHz, CR 4/5, 15-symbol preamble, CRC enabled, explicit header
- TX powers: -4, 10 and 20 dBm
- LoRa settings: SF7, SF9 and SF12 at 125 kHz

## Integrity and completeness

- Full AT pair diagnostic: 82/82 checks passed.
- Quick check: 4/4 steps passed on the first attempt.
- Campaign: 40/40 steps passed on the first attempt; no retries or recovery overrides.
- Packet measurements: 180/180 current events detected; 179/180 packets received.
- Continuous measurements: 12/12 points have status `ok`, with a 60 s active window for every point.
- Raw traces: 192/192 gzip files decompressed fully and passed their gzip CRC checks. They contain 4,375,271,124 uncompressed bytes.
- Maximum PPK2 sample loss: 0.525714%; maximum packet-energy CV across the five repetitions: 0.710177%.
- No serial errors were reported by any continuous transmitter run.

## Observed radio losses

One packet was not received in the packet campaign: TX, 8 B, 10 dBm, SF9, BW 125 kHz. The classic RA-02 campaign also lost exactly one of five packets at this same test point, although in a different repetition. The current event was detected and measured correctly, so the energy result remains valid.

The continuous RX campaign received 1,747 of 1,758 frames (99.3743%):

| SF | Effective payload rate | TX power | Received | Lost | Loss |
|---:|---:|---:|---:|---:|---:|
| 7 | 3.644 kbps | -4 dBm | 427/427 | 0 | 0.000% |
| 7 | 3.644 kbps | 10 dBm | 427/427 | 0 | 0.000% |
| 7 | 3.644 kbps | 20 dBm | 420/427 | 7 | 1.639% |
| 9 | 1.186 kbps | -4 dBm | 136/139 | 3 | 2.158% |
| 9 | 1.186 kbps | 10 dBm | 139/139 | 0 | 0.000% |
| 9 | 1.186 kbps | 20 dBm | 138/139 | 1 | 0.719% |
| 12 | 0.171 kbps | all powers | 60/60 | 0 | 0.000% |

Loss is sparse and non-monotonic with TX power. Together with the clean serial and PPK2 data, this does not indicate a measurement-path or firmware defect. The measured losses are retained rather than replaced by cherry-picked retries.

## Comparison with classic RA-02

The 2Cap pair has lower TX packet energy at all 27 matching TX points. The average difference is -2.3745%, spanning -3.8630% to -0.2719%. Its continuous TX current is also lower:

| TX power | Classic RA-02 | RA-02 + 2Cap | Difference |
|---:|---:|---:|---:|
| -4 dBm | 11.1065 mA | 11.0661 mA | -0.3635% |
| 10 dBm | 26.6657 mA | 25.6753 mA | -3.7141% |
| 20 dBm | 61.7242 mA | 59.6795 mA | -3.3127% |

RX is effectively unchanged: the mean continuous current is 11.9475 mA for the classic pair and 11.9604 mA for the 2Cap pair (+0.1024% averaged across matched points). Packet RX energy differs by +0.2291% on average.

Continuous delivery was 99.6018% for the classic pair and 99.3743% for the 2Cap pair. This small difference is based on only one pair of each hardware variant and sparse losses; it is not sufficient evidence that the two capacitors reduce RF performance. Likewise, the TX-current difference is consistent and measurable for these pairs, but unit-to-unit variation prevents attributing it exclusively to the added capacitors without testing more samples.

## Verdict

The RA-02 + 2Cap campaign is complete and valid. No additional hardware diagnostic or campaign rerun is required.
