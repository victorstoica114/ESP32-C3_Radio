E79 TX recapture session transfer

SESSION_MANIFEST_SHA256.csv covers every file in this session except itself and
the four live PPK2-holder stdout/stderr files listed below. Those files remain
open so both PPK2 devices stay continuously blue and the DUT paths stay ON.
They contain only the READY line (stdout, 55 bytes) or are empty (stderr); their
state is recorded in BENCH_NOTES.md. No capture, RAW trace, analysis, metadata,
summary, aggregate, campaign console log, or inspection artifact is excluded.

Excluded live-holder files:
- com12_hold_after_attempt2.stdout.log
- com12_hold_after_attempt2.stderr.log
- com13_holder_after_final_lot_20260929_200028.stdout.log
- com13_holder_after_final_lot_20260929_200028.stderr.log

Accepted datasets:
- lot45_gfsk200_consensus/20260929_185646_radio_ebyte_e79_cc1352p
- lot270_other_profiles_final_candidate2/20260929_193856_radio_ebyte_e79_cc1352p

The GitHub release archive preserves every other file in the session root,
including every interrupted/rejected attempt and all 315 accepted RAW traces.
