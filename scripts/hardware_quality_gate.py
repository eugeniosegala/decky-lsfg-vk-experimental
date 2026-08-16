#!/usr/bin/env python3
"""Compare repeatable target-hardware reports without pretending CI is hardware.

The capture harness lives on a dedicated SteamOS/Bazzite runner.  This script is
deliberately capture-tool agnostic: it validates that baseline and candidate
were measured in the same environment, rejects unstable evidence, and applies
the reviewable thresholds stored in a versioned policy file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
from typing import Any


REPORT_SCHEMA = 1
POLICY_SCHEMA = 1
GIT_SHA_LENGTH = 40
SHA256_HEX_LENGTH = 64
MAX_JSON_BYTES = 1_048_576
HASHED_ENVIRONMENT_FIELDS = {
    "workload_build",
    "workload_settings_hash",
    "capture_harness_sha256",
}


class QualityGateError(ValueError):
    """Raised when evidence is malformed or cannot support a comparison."""


def _read_bounded(path: Path) -> bytes:
    try:
        with path.open("rb") as source:
            payload = source.read(MAX_JSON_BYTES + 1)
        if len(payload) > MAX_JSON_BYTES:
            raise QualityGateError(f"{path} exceeds the {MAX_JSON_BYTES}-byte limit")
        return payload
    except OSError as error:
        raise QualityGateError(f"cannot read {path}: {error}") from error


def _decode_json(payload: bytes, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise QualityGateError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise QualityGateError(f"{path} must contain a JSON object")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    return _decode_json(_read_bounded(path), path)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QualityGateError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise QualityGateError(f"{label} must be a finite number")
    return number


def _bounded_metric(value: object, label: str, rule: dict[str, Any]) -> float:
    number = _number(value, label)
    if rule["value_type"] == "integer" and not number.is_integer():
        raise QualityGateError(f"{label} must be an integer")
    minimum = rule["minimum"]
    maximum = rule["maximum"]
    if minimum is not None:
        if rule["exclusive_minimum"] and number <= minimum:
            raise QualityGateError(f"{label} must be greater than {minimum:g}")
        if not rule["exclusive_minimum"] and number < minimum:
            raise QualityGateError(f"{label} must be at least {minimum:g}")
    if rule["direction"] != "hard_max" and maximum is not None and number > maximum:
        raise QualityGateError(f"{label} must be at most {maximum:g}")
    return number


def _lower_hex(value: object, *, length: int, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise QualityGateError(
            f"{label} must be {length} lowercase hexadecimal characters"
        )
    return value


def _validate_report(
    report: dict[str, Any],
    *,
    label: str,
    metrics: dict[str, dict[str, Any]],
    minimum_runs: int,
) -> None:
    if set(report) != {"schema", "environment", "subject", "runs"}:
        raise QualityGateError(f"{label} report has unexpected top-level fields")
    if report["schema"] != REPORT_SCHEMA:
        raise QualityGateError(f"{label} report has an unsupported schema")
    if not isinstance(report["environment"], dict) or not report["environment"]:
        raise QualityGateError(f"{label} environment must be a non-empty object")
    if not isinstance(report["subject"], dict) or not report["subject"]:
        raise QualityGateError(f"{label} subject must be a non-empty object")
    if set(report["subject"]) != {"git_sha", "engine_sha256"}:
        raise QualityGateError(
            f"{label} subject must contain exactly git_sha and engine_sha256"
        )
    _lower_hex(
        report["subject"]["git_sha"],
        length=GIT_SHA_LENGTH,
        label=f"{label} subject git_sha",
    )
    engine_sha256 = report["subject"]["engine_sha256"]
    if not isinstance(engine_sha256, str) or not engine_sha256.startswith("sha256:"):
        raise QualityGateError(
            f"{label} subject engine_sha256 must use the sha256:<hex> form"
        )
    _lower_hex(
        engine_sha256.removeprefix("sha256:"),
        length=SHA256_HEX_LENGTH,
        label=f"{label} subject engine_sha256",
    )
    runs = report["runs"]
    if not isinstance(runs, list) or len(runs) < minimum_runs:
        raise QualityGateError(
            f"{label} report needs at least {minimum_runs} independent runs"
        )
    run_fields = set(metrics) | {"run_id"}
    run_ids: set[str] = set()
    for index, run in enumerate(runs):
        if not isinstance(run, dict) or set(run) != run_fields:
            raise QualityGateError(
                f"{label} run {index + 1} must contain exactly: "
                f"{', '.join(sorted(run_fields))}"
            )
        run_id = run["run_id"]
        if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 128:
            raise QualityGateError(
                f"{label} run {index + 1} run_id must be 1-128 characters"
            )
        if run_id in run_ids:
            raise QualityGateError(f"{label} report requires a unique run_id per run")
        run_ids.add(run_id)
        for metric, rule in metrics.items():
            _bounded_metric(
                run[metric], f"{label} run {index + 1} metric {metric}", rule
            )


def _validate_policy(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (
        set(policy)
        != {
            "schema",
            "minimum_runs",
            "max_baseline_relative_mad",
            "max_candidate_relative_mad",
            "maximum_baseline_outlier_runs",
            "maximum_candidate_outlier_runs",
            "maximum_regressed_runs",
            "environment_keys",
            "run_invariants",
            "metrics",
        }
        or policy["schema"] != POLICY_SCHEMA
    ):
        raise QualityGateError("policy has an unsupported shape or schema")
    minimum_runs = policy["minimum_runs"]
    if (
        isinstance(minimum_runs, bool)
        or not isinstance(minimum_runs, int)
        or minimum_runs < 3
    ):
        raise QualityGateError("policy minimum_runs must be an integer of at least 3")
    if _number(policy["max_baseline_relative_mad"], "max_baseline_relative_mad") < 0:
        raise QualityGateError("max_baseline_relative_mad must be non-negative")
    if _number(policy["max_candidate_relative_mad"], "max_candidate_relative_mad") < 0:
        raise QualityGateError("max_candidate_relative_mad must be non-negative")
    for field in (
        "maximum_baseline_outlier_runs",
        "maximum_candidate_outlier_runs",
        "maximum_regressed_runs",
    ):
        maximum = policy[field]
        if (
            isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or maximum < 0
            or maximum >= minimum_runs
        ):
            raise QualityGateError(
                f"policy {field} must be an integer from 0 to minimum_runs - 1"
            )
    if not isinstance(policy["environment_keys"], list) or not all(
        isinstance(key, str) and key for key in policy["environment_keys"]
    ):
        raise QualityGateError("policy environment_keys must be non-empty strings")
    if len(set(policy["environment_keys"])) != len(policy["environment_keys"]):
        raise QualityGateError("policy environment_keys must be unique")
    metrics = policy["metrics"]
    if not isinstance(metrics, dict) or not metrics:
        raise QualityGateError("policy metrics must be a non-empty object")
    for name, rule in metrics.items():
        if not isinstance(name, str) or not isinstance(rule, dict):
            raise QualityGateError("policy contains an invalid metric rule")
        if rule.get("direction") not in {"lower", "higher", "hard_max"}:
            raise QualityGateError(f"metric {name} has an invalid direction")
        if rule.get("value_type") not in {"number", "integer"}:
            raise QualityGateError(f"metric {name} has an invalid value_type")
        if not isinstance(rule.get("rationale"), str) or not rule["rationale"].strip():
            raise QualityGateError(f"metric {name} needs a rationale")
        minimum = rule.get("minimum")
        maximum = rule.get("maximum")
        if minimum is not None:
            minimum = _number(minimum, f"metric {name} minimum")
        if maximum is not None:
            maximum = _number(maximum, f"metric {name} maximum")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise QualityGateError(f"metric {name} minimum exceeds maximum")
        rule["minimum"] = minimum
        rule["maximum"] = maximum
        if rule["direction"] == "hard_max":
            if set(rule) != {
                "direction",
                "value_type",
                "minimum",
                "exclusive_minimum",
                "maximum",
                "rationale",
            }:
                raise QualityGateError(f"metric {name} has an invalid hard-max rule")
            if maximum is None:
                raise QualityGateError(f"metric {name} hard maximum is required")
        else:
            if set(rule) != {
                "direction",
                "value_type",
                "minimum",
                "exclusive_minimum",
                "maximum",
                "max_relative_regression",
                "absolute_noise_floor",
                "rationale",
            }:
                raise QualityGateError(f"metric {name} has an invalid regression rule")
            if (
                _number(
                    rule["max_relative_regression"], f"metric {name} relative limit"
                )
                < 0
                or _number(
                    rule["absolute_noise_floor"], f"metric {name} absolute noise floor"
                )
                < 0
            ):
                raise QualityGateError(
                    f"metric {name} regression limits must be non-negative"
                )
        if not isinstance(rule["exclusive_minimum"], bool):
            raise QualityGateError(f"metric {name} exclusive_minimum must be a boolean")
        if rule["exclusive_minimum"] and minimum is None:
            raise QualityGateError(
                f"metric {name} cannot use exclusive_minimum without minimum"
            )
    invariants = policy["run_invariants"]
    if not isinstance(invariants, list):
        raise QualityGateError("policy run_invariants must be a list")
    for index, invariant in enumerate(invariants):
        if not isinstance(invariant, dict) or set(invariant) != {
            "left",
            "operator",
            "right",
            "rationale",
        }:
            raise QualityGateError(f"run invariant {index + 1} has an invalid shape")
        if invariant["operator"] != "gte":
            raise QualityGateError(
                f"run invariant {index + 1} has an unsupported operator"
            )
        if (
            invariant["left"] not in metrics
            or invariant["right"] not in metrics
            or invariant["left"] == invariant["right"]
        ):
            raise QualityGateError(
                f"run invariant {index + 1} must reference two known metrics"
            )
        if (
            not isinstance(invariant["rationale"], str)
            or not invariant["rationale"].strip()
        ):
            raise QualityGateError(f"run invariant {index + 1} needs a rationale")
    return metrics


def _validate_run_invariants(
    report: dict[str, Any], *, label: str, invariants: list[dict[str, Any]]
) -> None:
    for run_index, run in enumerate(report["runs"]):
        for invariant in invariants:
            left = _number(run[invariant["left"]], invariant["left"])
            right = _number(run[invariant["right"]], invariant["right"])
            if invariant["operator"] == "gte" and left < right:
                raise QualityGateError(
                    f"{label} run {run_index + 1} violates "
                    f"{invariant['left']} gte {invariant['right']}"
                )


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def _relative_mad(values: list[float]) -> float:
    center = _median(values)
    deviation = _median([abs(value - center) for value in values])
    scale = max(abs(center), 1e-12)
    return deviation / scale


def evaluate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    policy: dict[str, Any],
    *,
    expected_baseline_sha: str | None = None,
    expected_candidate_sha: str | None = None,
    expected_capture_harness_sha256: str | None = None,
) -> dict[str, Any]:
    metrics = _validate_policy(policy)
    minimum_runs = policy["minimum_runs"]
    _validate_report(
        baseline, label="baseline", metrics=metrics, minimum_runs=minimum_runs
    )
    _validate_report(
        candidate, label="candidate", metrics=metrics, minimum_runs=minimum_runs
    )
    _validate_run_invariants(
        baseline, label="baseline", invariants=policy["run_invariants"]
    )
    _validate_run_invariants(
        candidate, label="candidate", invariants=policy["run_invariants"]
    )

    expected_subjects = (
        ("baseline", baseline, expected_baseline_sha),
        ("candidate", candidate, expected_candidate_sha),
    )
    for label, report, expected_sha in expected_subjects:
        if expected_sha is None:
            continue
        _lower_hex(expected_sha, length=GIT_SHA_LENGTH, label=f"expected {label} SHA")
        if report["subject"]["git_sha"] != expected_sha:
            raise QualityGateError(
                f"{label} report subject does not match the requested commit SHA"
            )

    environment_keys = set(policy["environment_keys"])
    for label, report in (("baseline", baseline), ("candidate", candidate)):
        actual_keys = set(report["environment"])
        if actual_keys != environment_keys:
            missing = sorted(environment_keys - actual_keys)
            extra = sorted(actual_keys - environment_keys)
            detail = []
            if missing:
                detail.append(f"missing {', '.join(missing)}")
            if extra:
                detail.append(f"unexpected {', '.join(extra)}")
            raise QualityGateError(
                f"{label} environment fields do not match policy: {'; '.join(detail)}"
            )
        tdp_watts = report["environment"].get("tdp_watts")
        if (
            isinstance(tdp_watts, bool)
            or not isinstance(tdp_watts, (int, float))
            or _number(tdp_watts, f"{label} environment tdp_watts") <= 0
        ):
            raise QualityGateError(
                f"{label} environment tdp_watts must be a positive number"
            )
        for key, value in report["environment"].items():
            if key == "tdp_watts":
                continue
            if not isinstance(value, str) or not value.strip():
                raise QualityGateError(
                    f"{label} environment {key} must be a non-empty string"
                )
        for field in HASHED_ENVIRONMENT_FIELDS:
            digest = report["environment"].get(field)
            if not isinstance(digest, str) or not digest.startswith("sha256:"):
                raise QualityGateError(
                    f"{label} environment {field} must use sha256:<hex>"
                )
            _lower_hex(
                digest.removeprefix("sha256:"),
                length=SHA256_HEX_LENGTH,
                label=f"{label} environment {field}",
            )
    mismatched = [
        key
        for key in environment_keys
        if baseline["environment"][key] != candidate["environment"][key]
    ]
    if mismatched:
        raise QualityGateError(
            f"baseline and candidate environments differ: {', '.join(mismatched)}"
        )
    if expected_capture_harness_sha256 is not None:
        if not expected_capture_harness_sha256.startswith("sha256:"):
            raise QualityGateError(
                "expected capture harness SHA-256 must use sha256:<hex>"
            )
        _lower_hex(
            expected_capture_harness_sha256.removeprefix("sha256:"),
            length=SHA256_HEX_LENGTH,
            label="expected capture harness SHA-256",
        )
        if (
            baseline["environment"]["capture_harness_sha256"]
            != expected_capture_harness_sha256
        ):
            raise QualityGateError(
                "reports do not match the attested capture harness SHA-256"
            )

    results: list[dict[str, Any]] = []
    failures: list[str] = []
    max_relative_mad = _number(
        policy["max_baseline_relative_mad"], "max_baseline_relative_mad"
    )
    max_candidate_relative_mad = _number(
        policy["max_candidate_relative_mad"], "max_candidate_relative_mad"
    )
    maximum_regressed_runs = policy["maximum_regressed_runs"]
    maximum_baseline_outliers = policy["maximum_baseline_outlier_runs"]
    maximum_candidate_outliers = policy["maximum_candidate_outlier_runs"]
    for name, rule in metrics.items():
        baseline_values = [
            _bounded_metric(run[name], name, rule) for run in baseline["runs"]
        ]
        candidate_values = [
            _bounded_metric(run[name], name, rule) for run in candidate["runs"]
        ]
        baseline_median = _median(baseline_values)
        candidate_median = _median(candidate_values)
        baseline_relative_mad = _relative_mad(baseline_values)
        candidate_relative_mad = _relative_mad(candidate_values)
        passed = True
        detail = ""

        if baseline_relative_mad > max_relative_mad:
            passed = False
            detail = (
                f"baseline relative MAD {baseline_relative_mad:.4f} exceeds "
                f"{max_relative_mad:.4f}"
            )
        elif (
            rule["direction"] != "hard_max"
            and candidate_relative_mad > max_candidate_relative_mad
        ):
            passed = False
            detail = (
                f"candidate relative MAD {candidate_relative_mad:.4f} exceeds "
                f"{max_candidate_relative_mad:.4f}"
            )
        elif rule["direction"] == "hard_max":
            limit = rule["maximum"]
            baseline_maximum = max(baseline_values)
            candidate_maximum = max(candidate_values)
            passed = baseline_maximum <= limit and candidate_maximum <= limit
            detail = (
                f"baseline maximum {baseline_maximum:.6g}; candidate maximum "
                f"{candidate_maximum:.6g}; limit {limit:.6g}"
            )
        else:
            relative = abs(baseline_median) * _number(
                rule["max_relative_regression"], f"metric {name} relative limit"
            )
            noise_floor = _number(
                rule["absolute_noise_floor"], f"metric {name} absolute noise floor"
            )
            tolerance = max(relative, noise_floor)
            baseline_stability_tolerance = max(
                abs(baseline_median) * max_relative_mad, noise_floor
            )
            candidate_stability_tolerance = max(
                abs(candidate_median) * max_candidate_relative_mad, noise_floor
            )
            baseline_outliers = sum(
                abs(value - baseline_median) > baseline_stability_tolerance
                for value in baseline_values
            )
            candidate_outliers = sum(
                abs(value - candidate_median) > candidate_stability_tolerance
                for value in candidate_values
            )
            if baseline_outliers > maximum_baseline_outliers:
                passed = False
                detail = (
                    f"baseline outlier runs {baseline_outliers}/{len(baseline_values)} "
                    f"exceed allowed {maximum_baseline_outliers}"
                )
            elif candidate_outliers > maximum_candidate_outliers:
                passed = False
                detail = (
                    f"candidate outlier runs {candidate_outliers}/{len(candidate_values)} "
                    f"exceed allowed {maximum_candidate_outliers}"
                )
            elif rule["direction"] == "lower":
                limit = baseline_median + tolerance
                regressed_runs = sum(value > limit for value in candidate_values)
                passed = (
                    candidate_median <= limit
                    and regressed_runs <= maximum_regressed_runs
                )
                detail = (
                    f"candidate median {candidate_median:.6g}; maximum {limit:.6g}; "
                    f"regressed runs {regressed_runs}/{len(candidate_values)} "
                    f"(allowed {maximum_regressed_runs})"
                )
            else:
                limit = baseline_median - tolerance
                regressed_runs = sum(value < limit for value in candidate_values)
                passed = (
                    candidate_median >= limit
                    and regressed_runs <= maximum_regressed_runs
                )
                detail = (
                    f"candidate median {candidate_median:.6g}; minimum {limit:.6g}; "
                    f"regressed runs {regressed_runs}/{len(candidate_values)} "
                    f"(allowed {maximum_regressed_runs})"
                )

        result = {
            "metric": name,
            "passed": passed,
            "baseline_median": baseline_median,
            "candidate_median": candidate_median,
            "baseline_relative_mad": baseline_relative_mad,
            "candidate_relative_mad": candidate_relative_mad,
            "detail": detail,
        }
        results.append(result)
        if not passed:
            failures.append(f"{name}: {detail}")

    return {"passed": not failures, "failures": failures, "metrics": results}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    """Create one bounded result file without following or replacing a symlink."""
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(payload) > MAX_JSON_BYTES:
        raise QualityGateError(f"refusing to write oversized JSON output to {path}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
    except OSError as error:
        raise QualityGateError(f"cannot write {path}: {error}") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--capture-harness-sha256")
    parser.add_argument("--gate-sha")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--evidence-output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        baseline = _load_json(args.baseline)
        candidate = _load_json(args.candidate)
        policy_payload = _read_bounded(args.policy)
        policy = _decode_json(policy_payload, args.policy)
        result = evaluate(
            baseline,
            candidate,
            policy,
            expected_baseline_sha=args.baseline_sha,
            expected_candidate_sha=args.candidate_sha,
            expected_capture_harness_sha256=args.capture_harness_sha256,
        )
        provenance: dict[str, str] = {
            "policy_sha256": "sha256:" + hashlib.sha256(policy_payload).hexdigest(),
        }
        if args.capture_harness_sha256:
            provenance["capture_harness_sha256"] = args.capture_harness_sha256
        if args.gate_sha:
            provenance["gate_sha"] = _lower_hex(
                args.gate_sha, length=GIT_SHA_LENGTH, label="gate SHA"
            )
        result["provenance"] = provenance
    except QualityGateError as error:
        rejection = {"passed": False, "error": str(error)}
        if args.json_output:
            try:
                _write_json(args.json_output, rejection)
            except QualityGateError as output_error:
                print(
                    f"hardware quality result could not be written: {output_error}",
                    file=sys.stderr,
                )
        print(f"hardware quality evidence rejected: {error}", file=sys.stderr)
        return 2

    try:
        if args.json_output:
            _write_json(args.json_output, result)
        if args.evidence_output_dir:
            if (
                not args.evidence_output_dir.is_dir()
                or args.evidence_output_dir.is_symlink()
            ):
                raise QualityGateError(
                    "evidence output directory must be a real directory"
                )
            _write_json(args.evidence_output_dir / "baseline.json", baseline)
            _write_json(args.evidence_output_dir / "candidate.json", candidate)
    except QualityGateError as error:
        print(
            f"hardware quality evidence could not be sanitized: {error}",
            file=sys.stderr,
        )
        return 2
    for metric in result["metrics"]:
        marker = "PASS" if metric["passed"] else "FAIL"
        print(f"[{marker}] {metric['metric']}: {metric['detail']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
