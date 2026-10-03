"""Offline validation of saved E79 paired captures; no UI or hardware access."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .marker_analysis import (
    ENERGY_FILTER_RADIO_TOTALS_INTEGRATION_METHOD, ENERGY_FILTER_TOTAL_ONLY_ENERGY_POLICY,
    FILTER_RADIO_TOTALS_INTEGRATION_METHOD, FILTER_TOTAL_ONLY_ENERGY_POLICY,
)

if TYPE_CHECKING:
    from .web_app import CommandStep

DEFAULT_FILTER_HISTORY_POLICY = "current_equivalence_v1"
ENERGY_FILTER_HISTORY_POLICY = "energy_relative_v2"


def _read_rows(result_dir: Path) -> list[dict[str, str]]:
    path = result_dir / "summary.csv"
    if not path.is_file():
        raise ValueError(f"Missing {path}")
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))



def _validate_marker_total_proof(detail: dict, row: dict, start: int, end: int, count: int) -> None:
    proof = detail.get("total_qa")
    if (not isinstance(proof, dict) or proof.get("valid") is not True or proof.get("reasons") != []
            or proof.get("method") != "direct_adc_constant_range_marker_total"):
        raise ValueError("missing or invalid independent direct ADC proof")
    for name in ("constant_range_guard", "wire_logic_match_full_capture", "marker_window_complete",
                 "direct_adc_match", "calibration_valid", "guard_qa_includes_stop"):
        if proof.get(name) is not True:
            raise ValueError(f"direct ADC proof did not establish {name}")
    if (start < 3 or proof.get("window_samples") != [start, end]
            or proof.get("guard_window_samples") != [start - 3, end]
            or any(type(index) is not int for key in ("window_samples", "guard_window_samples") for index in proof[key])):
        raise ValueError("direct ADC proof does not cover the marker and its guard boundaries")
    for name, expected in (("wire_sample_count", count), ("captured_sample_count", count),
                           ("sample_rate_hz", 100_000), ("direct_adc_compared_samples", end - start)):
        if type(proof.get(name)) is not int or proof[name] != expected:
            raise ValueError(f"direct ADC proof has inconsistent {name}")
    if type(proof.get("range_code")) is not int or not 0 <= proof["range_code"] <= 4:
        raise ValueError("direct ADC proof has an invalid range")
    for name in ("counter_anomaly_indices_guard", "invalid_range_indices_guard", "bit17_indices_guard",
                 "nonfinite_current_indices_guard"):
        if proof.get(name) != []:
            raise ValueError(f"direct ADC guard failed: {name}")
    tolerance, difference = proof.get("direct_adc_tolerance_uA"), proof.get("direct_adc_max_difference_uA")
    if (type(tolerance) not in (int, float) or tolerance != 1e-6
            or type(difference) not in (int, float) or not math.isfinite(difference)
            or not 0 <= difference <= tolerance):
        raise ValueError("direct ADC comparison exceeds the fixed 1e-6 uA tolerance")
    for name in ("baseline_median_uA", "threshold_uA", "charge_excess_uC", "energy_excess_uJ"):
        if row[name] != "":
            raise ValueError(f"total-only result must leave {name} unavailable")
    for name in ("charge_total_uC", "energy_total_uJ", "tx_mean_uA", "tx_peak_uA"):
        value = float(row[name])
        if not math.isfinite(value):
            raise ValueError(f"total-only result has nonfinite {name}")
        if name in {"charge_total_uC", "energy_total_uJ"}:
            reference = proof.get(name)
            if (type(reference) not in (int, float) or not math.isfinite(reference)
                    or not math.isclose(value, reference, rel_tol=1e-9, abs_tol=1e-6)):
                raise ValueError(f"summary {name} differs from independent direct ADC proof")
    voltage_mv, proof_voltage_mv = float(row["voltage_mv"]), proof.get("voltage_mv")
    if (not math.isfinite(voltage_mv) or voltage_mv <= 0 or type(proof_voltage_mv) not in (int, float)
            or not math.isfinite(proof_voltage_mv)
            or not math.isclose(voltage_mv, proof_voltage_mv, rel_tol=0, abs_tol=1e-9)):
        raise ValueError("summary voltage differs from the direct ADC proof")
    if not math.isclose(float(row["energy_total_uJ"]), float(row["charge_total_uC"]) * voltage_mv / 1000,
                        rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError("total energy is inconsistent with charge and voltage")



def _validate_filter_marker_total_proof(detail: dict, row: dict, start: int, end: int, count: int,
                                       history_policy: str = DEFAULT_FILTER_HISTORY_POLICY) -> None:
    """Validate the opt-in bounded replay contract without weakening direct ADC QA."""
    proof = detail.get("total_qa")
    energy_history = history_policy == ENERGY_FILTER_HISTORY_POLICY
    if (not isinstance(proof, dict) or proof.get("valid") is not True or proof.get("reasons") != []
            or type(proof.get("schema_version")) is not int or proof["schema_version"] != (2 if energy_history else 1)
            or proof.get("history_policy", DEFAULT_FILTER_HISTORY_POLICY) != history_policy
            or proof.get("method") != "bounded_filter_replay_marker_total"):
        raise ValueError("missing or invalid bounded filter replay proof")

    def finite(name: str) -> float:
        value = proof.get(name)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"filter proof requires finite {name}")
        return value

    def interval(name: str) -> tuple[float, float]:
        values = proof.get(name)
        if (not isinstance(values, list) or len(values) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
                or values[0] > values[1]):
            raise ValueError(f"filter proof has invalid {name}")
        return values[0], values[1]

    for name in ("wire_logic_match_full_capture", "marker_window_complete", "calibration_valid",
                 "guard_qa_includes_stop", "filter_replay_match", "global_state_invariant", "history_bound_valid"):
        if proof.get(name) is not True:
            raise ValueError(f"filter proof did not establish {name}")
    if (start < 3 or proof.get("window_samples") != [start, end]
            or proof.get("guard_window_samples") != [start - 3, end]
            or any(type(i) is not int for key in ("window_samples", "guard_window_samples") for i in proof[key])):
        raise ValueError("filter proof does not cover the marker and guard boundaries")
    for name, expected in (("wire_sample_count", count), ("captured_sample_count", count),
                           ("sample_rate_hz", 100_000), ("filter_replay_compared_samples", count),
                           ("global_adc_domain_values", 81_920), ("wire_logic_mismatch_count", 0)):
        if type(proof.get(name)) is not int or proof[name] != expected:
            raise ValueError(f"filter proof has inconsistent {name}")
    for name in ("wire_sha256", "calibration_sha256"):
        if not isinstance(proof.get(name), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", proof[name]):
            raise ValueError(f"filter proof is missing {name}")
    for name in ("counter_anomaly_indices_guard", "invalid_range_indices_guard", "bit17_indices_guard",
                 "nonfinite_current_indices_guard", "filter_replay_nonfinite_indices"):
        if proof.get(name) != []:
            raise ValueError(f"filter guard or replay failed: {name}")
    ranges = proof.get("range_counts_guard")
    if (not isinstance(ranges, dict) or not ranges or any(k not in {"0", "1", "2", "3", "4"} for k in ranges)
            or any(type(n) is not int or n <= 0 for n in ranges.values())
            or sum(ranges.values()) != end - start + 3):
        raise ValueError("filter guard range counts are incomplete or invalid")
    for name in ("outside_counter_anomaly_count", "outside_invalid_range_count", "outside_bit17_count"):
        if type(proof.get(name)) is not int or proof[name] < 0:
            raise ValueError(f"filter proof is missing anomaly disclosure: {name}")
    parameters = proof.get("filter_parameters")
    if (not isinstance(parameters, dict) or set(parameters) != {"alpha", "alpha5", "samples"}
            or type(parameters["samples"]) is not int or parameters["samples"] != 3
            or any(type(parameters[k]) not in (int, float) or parameters[k] != v
                   for k, v in (("alpha", 0.18), ("alpha5", 0.06)))):
        raise ValueError("filter replay parameters differ from the supported decoder")
    tolerance = finite("filter_tolerance_uA")
    replay = finite("filter_replay_max_difference_uA")
    history = finite("history_interval_max_width_uA")
    combined = finite("combined_error_bound_uA")
    if (tolerance != 1e-6 or min(replay, history, combined) < 0 or replay > tolerance
            or (not energy_history and combined > tolerance)
            or not math.isclose(combined, replay + history, rel_tol=1e-12, abs_tol=1e-18)):
        raise ValueError("combined filter replay/history error exceeds the fixed bound or is inconsistent")
    adc = interval("global_adc_bounds_A")
    states = interval("global_state_bounds_A")
    if states[0] > adc[0] or states[1] < adc[1]:
        raise ValueError("filter state bounds do not contain the ADC domain")
    suffix, suspect = proof.get("history_clean_suffix_start"), proof.get("history_last_suspect_index")
    if (type(suffix) is not int or not 0 <= suffix <= start - 3
            or (suspect is not None and (type(suspect) is not int or not 0 <= suspect < suffix))
            or suffix != (0 if suspect is None else suspect + 1)):
        raise ValueError("filter history is not clean through the guarded marker")
    converged = proof.get("history_state_converged_samples")
    if (not isinstance(converged, dict) or set(converged) != {"fast", "slow"}
            or any(v is not None and (type(v) is not int or not 0 <= v < count) for v in converged.values())):
        raise ValueError("filter history convergence diagnostics are incomplete")
    for name in ("baseline_median_uA", "threshold_uA", "charge_excess_uC", "energy_excess_uJ"):
        if row[name] != "":
            raise ValueError(f"filter total-only result must leave {name} unavailable")
    voltage = finite("voltage_mv")
    if voltage <= 0 or not math.isclose(float(row["voltage_mv"]), voltage, rel_tol=0, abs_tol=1e-9):
        raise ValueError("summary voltage differs from the filter proof")
    for name in ("tx_mean_uA", "tx_peak_uA"):
        if not math.isfinite(float(row[name])):
            raise ValueError(f"filter total-only result has nonfinite {name}")
    bounds = {}
    for quantity, unit in (("charge", "uC"), ("energy", "uJ")):
        name = f"{quantity}_total_{unit}"
        nominal = finite(name)
        low, high = interval(f"{quantity}_interval_{unit}")
        width = finite(f"{quantity}_interval_width_{unit}")
        if (not low <= nominal <= high or width < 0
                or not math.isclose(width, high - low, rel_tol=1e-9, abs_tol=1e-15)
                or not math.isfinite(float(row[name]))
                or not math.isclose(float(row[name]), nominal, rel_tol=1e-9, abs_tol=1e-6)):
            raise ValueError(f"summary {name} or bounded interval is inconsistent")
        bounds[quantity] = (low, high, width)
    # The total interval also includes outward rounding of summation/division,
    # even when sample history width is zero. Its actual enclosure is verified
    # by mandatory saved-file replay, not a history-width * duration shortcut.
    # Energy endpoints are rounded outward independently. Their interval width
    # therefore need not equal charge width * voltage; each width was checked
    # against its own endpoints above, and saved-file replay remains exact.
    if (not math.isclose(proof["energy_total_uJ"], proof["charge_total_uC"] * voltage / 1000,
                         rel_tol=1e-9, abs_tol=1e-6)
            or any(not math.isclose(e, q * voltage / 1000, rel_tol=1e-9, abs_tol=1e-12)
                   for q, e in zip(bounds["charge"][:2], bounds["energy"][:2]))
            or not math.isclose(float(row["tx_mean_uA"]), proof["charge_total_uC"] * 100_000 / (end - start),
                                rel_tol=1e-9, abs_tol=1e-6)):
        raise ValueError("filter totals, mean current, charge or voltage are inconsistent")
    if energy_history:
        low, high, width = bounds["energy"]
        relative = finite("energy_history_relative_bound")
        limit = finite("energy_history_relative_tolerance")
        if low <= 0 or proof["energy_total_uJ"] <= 0:
            raise ValueError("energy history proof requires a strictly positive energy enclosure")
        ratio = width / min(abs(low), abs(high))
        expected_relative = math.nextafter(ratio, math.inf) if ratio > 0 else 0.0
        if (limit != 1e-4 or proof.get("energy_history_budget_valid") is not True
                or relative != expected_relative or not 0 <= relative <= limit):
            raise ValueError("energy history proof exceeds or misstates the 0.01% software uncertainty budget")



def _revalidate_filter_marker_files(result_dir: Path, pairing: dict, transfer: dict,
                                    role: str, detail: dict, count: int) -> None:
    """Bind the new policy to saved bytes, replaying rather than trusting declared bounds."""
    from .filter_marker_totals import prove_filter_marker_total
    from .ppk import Capture

    root = result_dir.resolve()
    run_id = transfer["run_id"]
    raw_path = (root / role / "raw" / f"{run_id}.csv.gz").resolve()
    wire_path = (root / "wire" / run_id / f"{role}.ppk2.bin").resolve()
    recorded_wire = (root / transfer["wire_paths"][role]).resolve()
    if (not raw_path.is_relative_to(root) or not wire_path.is_relative_to(root)
            or recorded_wire != wire_path or not wire_path.is_file()):
        raise ValueError("filter proof RAW/WIRE paths do not identify this role and run")
    samples, logic, triggers = [], [], []
    with gzip.open(raw_path, "rt", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"sample_index", "current_uA", "logic_bits", "trigger"}.issubset(reader.fieldnames or []):
            raise ValueError("filter proof RAW is missing required columns")
        for index, item in enumerate(reader):
            if index >= count or int(item["sample_index"]) != index:
                raise ValueError("filter proof RAW indices/count differ from the summary")
            current, bits, trigger = float(item["current_uA"]), int(item["logic_bits"]), int(item["trigger"])
            if not math.isfinite(current) or not 0 <= bits <= 255 or trigger not in (0, 1):
                raise ValueError("filter proof RAW has invalid current, digital or trigger values")
            samples.append(current)
            logic.append(bits)
            if trigger:
                triggers.append(index)
    expected_trigger = transfer["timing"]["devices"][role]["trigger_index"]
    if len(samples) != count or triggers != [expected_trigger]:
        raise ValueError("filter proof RAW count/trigger differs from the paired capture")
    windows, first = [], None
    for index, bits in enumerate(logic):
        if bits & 1 and first is None:
            first = index
        elif not bits & 1 and first is not None:
            windows.append([first, index])
            first = None
    if not logic or logic[0] & 1 or first is not None or windows != [detail["window_samples"]]:
        raise ValueError("filter proof RAW does not contain exactly the declared complete D0 pulse")
    endpoint = pairing["endpoints"][role]
    recomputed = prove_filter_marker_total(
        Capture(samples, logic, expected_trigger, count / 100_000, count), wire_path,
        tuple(detail["window_samples"]), endpoint["ppk_calibration_metadata"],
        endpoint["voltage_mv"], sample_rate_hz=100_000,
        **({"history_policy": ENERGY_FILTER_HISTORY_POLICY}
           if pairing.get("filter_history_policy", DEFAULT_FILTER_HISTORY_POLICY) == ENERGY_FILTER_HISTORY_POLICY else {}),
    )
    if recomputed.get("valid") is not True or recomputed != detail["total_qa"]:
        raise ValueError("filter proof differs from replay of saved RAW, WIRE and endpoint calibration")



def _validate_fragment_marker_role(detail: dict, row: dict, transfer: dict, role: str,
                                   frame_count: int, rate: int) -> None:
    """Validate every local frame proof before accepting their disjoint sum."""
    count = int(row["captured_samples"])
    trigger = transfer["timing"]["devices"][role]["trigger_index"]
    windows, proofs = detail.get("windows_samples"), detail.get("frame_proofs")
    if (detail.get("valid") is not True or detail.get("reasons") != []
            or type(detail.get("pulse_count")) is not int or detail["pulse_count"] != frame_count
            or type(detail.get("sample_count")) is not int or detail["sample_count"] != count
            or type(trigger) is not int or trigger < 0 or detail.get("software_trigger_index") != trigger
            or not isinstance(windows, list) or len(windows) != frame_count
            or not isinstance(proofs, list) or len(proofs) != frame_count):
        raise ValueError("incomplete fragmented pulse count, capture or trigger evidence")
    duration, previous_end = 0, trigger
    expected_ms, charges, energies = [], [], []
    for window, proof in zip(windows, proofs):
        if (not isinstance(window, list) or len(window) != 2
                or any(type(index) is not int for index in window)):
            raise ValueError("fragment marker windows require integer sample indices")
        start, end = window
        if not previous_end < start < end < count or end - start < 3:
            raise ValueError("fragment marker windows are incomplete, overlapping or unordered")
        # Reuse every single-frame ADC/guard check, with only its own totals.
        if not isinstance(proof, dict):
            raise ValueError("missing fragment direct ADC proof")
        frame_row = {**row, "charge_total_uC": proof.get("charge_total_uC"),
                     "energy_total_uJ": proof.get("energy_total_uJ")}
        _validate_marker_total_proof({"total_qa": proof}, frame_row, start, end, count)
        charges.append(proof["charge_total_uC"])
        energies.append(proof["energy_total_uJ"])
        duration += end - start
        previous_end = end
        expected_ms.append([(start - trigger) * 1000 / rate, (end - trigger) * 1000 / rate])
    if type(detail.get("duration_samples")) is not int or detail["duration_samples"] != duration:
        raise ValueError("fragment duration must be the sum of active intervals only")
    for name, expected in (("charge_total_uC", math.fsum(charges)), ("energy_total_uJ", math.fsum(energies))):
        for actual in (detail.get(name), row.get(name)):
            value = float(actual)
            if not math.isfinite(value) or not math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-6):
                raise ValueError(f"fragment {name} differs from the sum of all frame proofs")
    windows_ms = json.loads(row["integration_windows_ms"])
    if (not isinstance(windows_ms, list) or len(windows_ms) != frame_count
            or any(not isinstance(window, list) or len(window) != 2 for window in windows_ms)):
        raise ValueError("summary must contain every fragment integration interval")
    actual_values = [float(value) for window in windows_ms for value in window]
    expected_values = [value for window in expected_ms for value in window]
    actual_values += [float(row["event_duration_ms"]), float(row["tx_mean_uA"])]
    expected_values += [duration * 1000 / rate, math.fsum(charges) * rate / duration]
    if any(not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-6)
           for actual, expected in zip(actual_values, expected_values)):
        raise ValueError("fragment summary windows, active duration or mean current are inconsistent")



def _validate_paired_marker_evidence(
    pairing: dict[str, Any], transfers: list[dict[str, Any]],
    role_rows: dict[str, list[dict[str, str]]], errors: list[str], warnings: list[str],
    result_dir: Path,
) -> None:
    """Require measured D0 windows; never accept a modeled fallback for this job."""
    local_markers = pairing.get("integration_mode") == "radio_markers"
    totals_only = pairing.get("marker_totals_only") is True
    filter_aware = pairing.get("filter_aware_totals") is True
    history_policy = pairing.get("filter_history_policy", DEFAULT_FILTER_HISTORY_POLICY)
    energy_history = history_policy == ENERGY_FILTER_HISTORY_POLICY
    total_policy = (ENERGY_FILTER_TOTAL_ONLY_ENERGY_POLICY if energy_history else
                    FILTER_TOTAL_ONLY_ENERGY_POLICY if filter_aware else "total_only_with_direct_adc_proof")
    fragmented = pairing.get("fragmented") is True
    frame_count = pairing.get("frame_count")
    description = "local radio" if local_markers else "common TX"
    method = "independent_radio_hardware_markers" if local_markers else "common_tx_hardware_marker"
    if totals_only:
        method = (ENERGY_FILTER_RADIO_TOTALS_INTEGRATION_METHOD if energy_history else
                  FILTER_RADIO_TOTALS_INTEGRATION_METHOD if filter_aware else "independent_radio_hardware_marker_totals")
        warnings.append("Total energy only: baseline, threshold and excess metrics are unavailable")
    if fragmented:
        method = "independent_radio_fragment_marker_totals"
    role_sources = {"tx": "TX DIO17 / RAT_GPO0 / active HIGH", "rx": "RX DIO17 / RAT_GPO1 / active HIGH"}
    source = "Local TX and RX DIO17 / active HIGH" if local_markers else role_sources["tx"]
    rate = pairing.get("sample_rate_hz")
    if type(rate) is not int or rate != 100_000:
        errors.append("Hardware marker evidence requires the recorded 100 kS/s sample rate")
        return
    if local_markers:
        if (pairing.get("rx_arming_policy") != "continuous_across_warmup_and_five_transfers"
                or pairing.get("rx_rearm_between_transfers") is not False):
            errors.append("Local RX marker requires continuous RX arming across warm-up and all transfers")
        for role, signal in (("tx", "RAT_GPO0"), ("rx", "RAT_GPO1")):
            try:
                preflight = pairing["endpoints"][role]["modem_preflight"]
                expected_marker = {"role": role.upper(), "dio": 17, "source": signal,
                                   "active": "HIGH", "ppk_input": "D0"}
                if preflight.get("firmware_version") != "0.3.2" or preflight.get("radio_marker") != expected_marker:
                    raise ValueError("firmware 0.3.2 and the selected local DIO17 marker role are required")
                if preflight.get("marker_set_command") != f"AT+MARKER={role.upper()}":
                    raise ValueError("marker role selection was not recorded")
                replies = [preflight.get("marker_set_reply"), preflight.get("marker_reply")]
                if any(not isinstance(lines, list) or "OK" not in lines
                       or any(not isinstance(line, str) or line.upper().startswith("#ERROR") for line in lines)
                       for lines in replies):
                    raise ValueError("marker role selection/query did not return OK")
                expected_reply = f"+MARKER:ROLE={role.upper()},DIO=17,SOURCE={signal},ACTIVE=HIGH"
                if [line for line in replies[1] if line.startswith("+MARKER:")] != [expected_reply]:
                    raise ValueError("marker query does not confirm the selected local role")
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                errors.append(f"{role.upper()}: invalid local marker preflight: {exc}")
    for transfer in transfers:
        run_id = transfer.get("run_id", "")
        evidence = transfer.get("marker_diagnostics")
        if (not isinstance(evidence, dict) or evidence.get("valid") is not True
                or type(evidence.get("marker_bit")) is not int or evidence["marker_bit"] != 0
                or evidence.get("source") != source
                or evidence.get("width_tolerance_samples") != (None if local_markers else 2)
                or (local_markers and evidence.get("width_comparison") != "not_applicable_independent_radio_intervals")
                or (totals_only and evidence.get("energy_policy") != total_policy)
                or (fragmented and (evidence.get("expected_frame_count") != frame_count
                                    or evidence.get("integration_method") != method
                                    or evidence.get("method") != method))
                or evidence.get("reasons") != []):
            errors.append(f"{run_id}: missing or invalid {description} D0 marker evidence")
            continue
        roles = evidence.get("roles")
        if not isinstance(roles, dict) or set(roles) != {"tx", "rx"}:
            errors.append(f"{run_id}: {description} marker requires evidence from both PPK2 instruments")
            continue
        lengths = []
        for role in ("tx", "rx"):
            row = next((item for item in role_rows[role] if item.get("run_id") == run_id), {})
            try:
                if row.get("integration_method") != method:
                    raise ValueError(f"integration method is not {method}")
                detail = roles[role]
                if not isinstance(detail, dict):
                    raise ValueError("local marker evidence must be an object")
                if local_markers and detail.get("source") != role_sources[role]:
                    raise ValueError("marker source does not match this local radio role")
                if fragmented:
                    _validate_fragment_marker_role(detail, row, transfer, role, frame_count, rate)
                    warnings.extend(f"{run_id}: {warning}" for warning in evidence.get("warnings", []))
                    continue
                window = detail["window_samples"]
                if (not isinstance(window, list) or len(window) != 2
                        or any(type(index) is not int for index in window)):
                    raise ValueError("marker window must contain two integer sample indices")
                start, end = window
                count = int(row["captured_samples"])
                duration = detail["duration_samples"]
                if (detail.get("pulse_count") != 1 or not 0 < start < end < count
                        or type(duration) is not int or duration != end - start or duration < 3):
                    raise ValueError("marker window is incomplete or has inconsistent duration")
                counter_qa = detail.get("counter_qa")
                if totals_only:
                    if filter_aware:
                        _validate_filter_marker_total_proof(detail, row, start, end, count, history_policy)
                        _revalidate_filter_marker_files(result_dir, pairing, transfer, role, detail, count)
                    else:
                        _validate_marker_total_proof(detail, row, start, end, count)
                    if (not isinstance(counter_qa, dict)
                            or type(counter_qa.get("relevant_anomaly_count")) is not int
                            or counter_qa["relevant_anomaly_count"] < 0):
                        raise ValueError("original marker/baseline counter QA must remain available")
                    if counter_qa.get("status") == "review_required" and counter_qa["relevant_anomaly_count"] > 0:
                        disclosed = evidence.get("warnings")
                        if not isinstance(disclosed, list) or not disclosed or any(not isinstance(w, str) for w in disclosed):
                            raise ValueError("baseline counter failure must be disclosed without claiming a pass")
                        warnings.extend(f"{run_id}: {warning}" for warning in disclosed)
                    elif counter_qa.get("status") != "passed_relevant_intervals" or counter_qa["relevant_anomaly_count"] != 0:
                        raise ValueError("original marker/baseline counter QA is inconsistent")
                elif (not isinstance(counter_qa, dict) or counter_qa.get("status") != "passed_relevant_intervals"
                      or counter_qa.get("relevant_anomaly_count") != 0):
                    raise ValueError("wire counter QA did not pass for the marker and baseline intervals")
                trigger_index = transfer["timing"]["devices"][role]["trigger_index"]
                if type(trigger_index) is not int or not 0 <= trigger_index < start:
                    raise ValueError("local trigger sample index is missing or invalid")
                expected_ms = [(start - trigger_index) * 1000 / rate, (end - trigger_index) * 1000 / rate]
                windows_ms = json.loads(row["integration_windows_ms"])
                if not isinstance(windows_ms, list) or len(windows_ms) != 1 or len(windows_ms[0]) != 2:
                    raise ValueError("summary must integrate exactly one marker interval")
                values = [float(value) for value in windows_ms[0]] + [float(row["event_duration_ms"])]
                expected = expected_ms + [duration * 1000 / rate]
                if any(not math.isfinite(value) or not math.isclose(value, reference, rel_tol=1e-9, abs_tol=1e-6)
                       for value, reference in zip(values, expected)):
                    raise ValueError("summary integration window differs from recorded marker edges")
                lengths.append(duration)
            except (KeyError, TypeError, ValueError, OverflowError, OSError, EOFError, csv.Error) as exc:
                errors.append(f"{role.upper()} {run_id}: invalid {description} marker evidence: {exc}")
        if not local_markers and len(lengths) == 2 and abs(lengths[0] - lengths[1]) > 2:
            errors.append(f"{run_id}: common TX marker durations differ by more than two samples")



def _validate_paired_result(step: CommandStep, result_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    pairing = json.loads((result_dir / "pairing.json").read_text(encoding="utf-8"))
    if not isinstance(pairing, dict):
        raise ValueError("pairing.json must contain an object")
    requested_mode = (step.command[step.command.index("--integration-mode") + 1]
                      if "--integration-mode" in step.command else "modeled")
    if pairing.get("integration_mode", "modeled") != requested_mode:
        errors.append(f"Paired result integration mode does not match the requested {requested_mode}")
    requested_totals_only = "--marker-totals-only" in step.command
    requested_filter_aware = "--filter-aware-totals" in step.command
    requested_history_policy = (
        step.command[step.command.index("--filter-history-policy") + 1]
        if "--filter-history-policy" in step.command else DEFAULT_FILTER_HISTORY_POLICY
    )
    if (requested_history_policy not in {DEFAULT_FILTER_HISTORY_POLICY, ENERGY_FILTER_HISTORY_POLICY}
            or pairing.get("filter_history_policy", DEFAULT_FILTER_HISTORY_POLICY) != requested_history_policy
            or (requested_history_policy == ENERGY_FILTER_HISTORY_POLICY and not requested_filter_aware)):
        errors.append("Paired filter history policy does not match the explicit versioned request")
    if pairing.get("filter_aware_totals", False) is not requested_filter_aware:
        errors.append("Paired filter-aware energy policy does not match the explicit request")
    if requested_filter_aware and (not requested_totals_only or requested_mode != "radio_markers"
                                   or "--fragmented" in step.command):
        errors.append("Filter-aware totals require nonfragmented local markers and explicit total-only energy")
    if pairing.get("marker_totals_only", False) is not requested_totals_only:
        errors.append("Paired total-only energy policy does not match the explicit request")
    if requested_totals_only:
        policy = (ENERGY_FILTER_TOTAL_ONLY_ENERGY_POLICY if requested_history_policy == ENERGY_FILTER_HISTORY_POLICY else
                  FILTER_TOTAL_ONLY_ENERGY_POLICY if requested_filter_aware else "total_only_with_direct_adc_proof")
        if requested_mode != "radio_markers" or pairing.get("energy_policy") != policy:
            errors.append("Total-only energy requires local markers and the explicitly selected proof policy")
    elif pairing.get("energy_policy") in {"total_only_with_direct_adc_proof", FILTER_TOTAL_ONLY_ENERGY_POLICY,
                                          ENERGY_FILTER_TOTAL_ONLY_ENERGY_POLICY}:
        errors.append("Total-only energy was not explicitly requested")
    fragmented = "--fragmented" in step.command
    if pairing.get("fragmented", False) is not fragmented:
        errors.append("Paired fragmentation mode does not match the explicit request")
    condition = None
    condition_flags = ("--payload-bytes", "--rf-profile", "--tx-power-dbm")
    if any(flag in step.command for flag in condition_flags):
        try:
            condition = {
                "payload_bytes": int(step.command[step.command.index("--payload-bytes") + 1]),
                "rf_profile": step.command[step.command.index("--rf-profile") + 1],
                "tx_power_dbm": int(step.command[step.command.index("--tx-power-dbm") + 1]),
            }
            if any(pairing.get(key) != value for key, value in condition.items()):
                errors.append("Paired result condition does not match the requested payload/PHY/power")
            for role in ("tx", "rx"):
                actual = pairing["endpoints"][role]["modem_preflight"]["config"]
                if (actual.get("PROFILE") != condition["rf_profile"]
                        or actual.get("PWR") != str(condition["tx_power_dbm"])):
                    errors.append(f"{role.upper()}: modem preflight does not match the requested PHY/power")
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            errors.append("Missing or invalid paired batch condition evidence")
    expected_frames = 0
    if fragmented:
        if (condition is None or condition["payload_bytes"] not in (128, 512, 1024)
                or condition["tx_power_dbm"] != 13 or requested_mode != "radio_markers" or not requested_totals_only):
            errors.append("Fragmented measurements require 128/512/1024 B, +13 dBm and explicit local-marker totals")
        else:
            expected_frames = condition["payload_bytes"] // 64
        contract = pairing.get("marker_contract", {})
        if (type(pairing.get("frame_count")) is not int or pairing["frame_count"] != expected_frames
                or pairing.get("frame_payload_bytes") != [64] * expected_frames
                or pairing.get("integration_method") != "independent_radio_fragment_marker_totals"
                or not isinstance(contract, dict) or contract.get("expected_frame_count") != expected_frames
                or contract.get("inter_frame_energy") != "excluded"):
            errors.append("Missing or inconsistent fragment count and energy interval contract")
    if pairing.get("status") != "valid":
        errors.append(f"Paired capture status is {pairing.get('status')!r}; expected valid")
    if pairing.get("voltage_confirmed") is not True or not pairing.get("voltage_provenance"):
        errors.append("Missing voltage confirmation/provenance in paired result")
    transfers = pairing.get("rows", [])
    if not isinstance(transfers, list) or any(not isinstance(row, dict) for row in transfers):
        raise ValueError("pairing.json rows must be a list of transfers")
    run_ids = [row.get("run_id", "") for row in transfers]
    transfer_ids = [row.get("paired_transfer_id", "") for row in transfers]
    if len(run_ids) != step.expected_rows or len(set(run_ids)) != step.expected_rows or not all(run_ids):
        errors.append(f"Expected {step.expected_rows} unique paired run IDs")
    if len(set(transfer_ids)) != step.expected_rows or not all(transfer_ids):
        errors.append("Missing or duplicate paired transfer identities")
    session_id = pairing.get("session_id")
    if not session_id or any(row.get("paired_transfer_id") != f"{session_id}:{row.get('run_id')}" for row in transfers):
        errors.append("Paired transfer identities do not match this session")
    if any(row.get("status") != "valid" for row in transfers):
        errors.append("One or more paired transfers require review")
    if requested_filter_aware and (
            type(pairing.get("expected_rows")) is not int or pairing["expected_rows"] != 5
            or step.expected_rows != 5
            or any(row.get("packet_received") is not True
                   or row.get("tx_status") != "ok" or row.get("rx_status") != "ok" for row in transfers)):
        errors.append("Filter-aware totals require five complete transfers with confirmed packet delivery")
    if fragmented and any(row.get("packet_received") is not True
                          or row.get("frame_payload_bytes") != [64] * expected_frames for row in transfers):
        errors.append("Every fragmented transfer must receive all expected frames")
    role_results = {}
    role_rows = {}
    for role in ("tx", "rx"):
        rows = _read_rows(result_dir / role)
        role_rows[role] = rows
        ids = [row.get("run_id", "") for row in rows]
        if len(ids) != step.expected_rows or len(set(ids)) != len(ids) or set(ids) != set(run_ids):
            errors.append(f"{role.upper()} summary does not match the paired run IDs")
        for row in rows:
            run_id = row.get("run_id", "")
            if condition is not None:
                try:
                    parameters = json.loads(row["parameters_json"])
                    if (int(row["payload_bytes"]) != condition["payload_bytes"]
                            or parameters != {"rf_profile": condition["rf_profile"],
                                              "tx_power_dbm": condition["tx_power_dbm"]}):
                        raise ValueError("condition mismatch")
                except (KeyError, TypeError, ValueError):
                    errors.append(f"{role.upper()} {run_id}: summary does not match the requested batch condition")
            status = row.get("status", "")
            if status not in {"ok", "rx_missing"} or row.get("analysis_error"):
                errors.append(f"{role.upper()} {run_id}: {status}; {row.get('analysis_error', '')}")
            if requested_filter_aware and (status != "ok" or row.get("packet_received") != "True"):
                errors.append(f"{role.upper()} {run_id}: filter-aware totals require confirmed delivery")
            if fragmented:
                try:
                    payload = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"
                    if (status != "ok" or int(row["frame_count"]) != expected_frames
                            or int(row["serial_content_bytes"]) != condition["payload_bytes"]
                            or row["receiver_response"].split(" | ").count(payload) != expected_frames):
                        raise ValueError("not all expected frame payloads were received")
                except (KeyError, TypeError, ValueError):
                    errors.append(f"{role.upper()} {run_id}: fragmented delivery evidence is incomplete")
            matching = next((item for item in transfers if item.get("run_id") == run_id), None)
            if matching is not None and matching.get(f"{role}_status") != status:
                errors.append(f"{role.upper()} {run_id}: pairing and summary statuses differ")
            expected_raw = result_dir / role / "raw" / f"{run_id}.csv.gz"
            raw_value = matching.get(f"{role}_raw", "") if matching is not None else ""
            raw_path = (result_dir / str(raw_value)).resolve()
            if (not raw_value or not raw_path.is_relative_to(result_dir.resolve())
                    or raw_path != expected_raw.resolve() or not raw_path.is_file()
                    or raw_path.stat().st_size == 0):
                errors.append(f"{role.upper()} {run_id}: missing or mismatched RAW evidence")
            try:
                sample_count = int(row.get("captured_samples", ""))
                sample_loss = float(row.get("sample_loss_percent", ""))
                if sample_count <= 0 or not math.isfinite(sample_loss) or not 0 <= sample_loss <= 1:
                    raise ValueError("invalid sample count/loss")
            except (ValueError, TypeError):
                errors.append(f"{role.upper()} {run_id}: sample count/loss failed quality checks")
            if status == "rx_missing":
                warnings.append(f"{role.upper()} {run_id}: missing packet retained without retry")
        role_results[role] = {"rows": len(rows), "statuses": [row.get("status", "") for row in rows]}
    if requested_mode in {"tx_marker", "radio_markers"}:
        _validate_paired_marker_evidence(pairing, transfers, role_rows, errors, warnings, result_dir)
    return {
        "valid": not errors, "rows": len(transfers), "roles": role_results,
        "errors": errors, "warnings": warnings, "integration_mode": requested_mode,
    }
