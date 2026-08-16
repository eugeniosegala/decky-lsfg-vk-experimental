#!/usr/bin/env python3
"""Compare repeatable target-hardware reports without pretending CI is hardware.

The capture harness lives on a dedicated SteamOS/Bazzite runner.  This script is
deliberately capture-tool agnostic: it validates that baseline and candidate
were measured in the same environment, rejects unstable evidence, and applies
the reviewable thresholds stored in a versioned policy file.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any


REPORT_SCHEMA = 1
POLICY_SCHEMA = 1


class QualityGateError(ValueError):
    """Raised when evidence is malformed or cannot support a comparison."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise QualityGateError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise QualityGateError(f"{path} must contain a JSON object")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QualityGateError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise QualityGateError(f"{label} must be a finite number")
    return number


def _validate_report(
    report: dict[str, Any], *, label: str, metrics: set[str], minimum_runs: int
) -> None:
    if set(report) != {"schema", "environment", "subject", "runs"}:
        raise QualityGateError(f"{label} report has unexpected top-level fields")
    if report["schema"] != REPORT_SCHEMA:
        raise QualityGateError(f"{label} report has an unsupported schema")
    if not isinstance(report["environment"], dict) or not report["environment"]:
        raise QualityGateError(f"{label} environment must be a non-empty object")
    if not isinstance(report["subject"], dict) or not report["subject"]:
        raise QualityGateError(f"{label} subject must be a non-empty object")
    runs = report["runs"]
    if not isinstance(runs, list) or len(runs) < minimum_runs:
        raise QualityGateError(
            f"{label} report needs at least {minimum_runs} independent runs"
        )
    for index, run in enumerate(runs):
        if not isinstance(run, dict) or set(run) != metrics:
            raise QualityGateError(
                f"{label} run {index + 1} must contain exactly: {', '.join(sorted(metrics))}"
            )
        for metric, value in run.items():
            _number(value, f"{label} run {index + 1} metric {metric}")


def _validate_policy(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (
        set(policy)
        != {
            "schema",
            "minimum_runs",
            "max_baseline_relative_mad",
            "environment_keys",
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
    if not isinstance(policy["environment_keys"], list) or not all(
        isinstance(key, str) and key for key in policy["environment_keys"]
    ):
        raise QualityGateError("policy environment_keys must be non-empty strings")
    metrics = policy["metrics"]
    if not isinstance(metrics, dict) or not metrics:
        raise QualityGateError("policy metrics must be a non-empty object")
    for name, rule in metrics.items():
        if not isinstance(name, str) or not isinstance(rule, dict):
            raise QualityGateError("policy contains an invalid metric rule")
        if rule.get("direction") not in {"lower", "higher", "hard_max"}:
            raise QualityGateError(f"metric {name} has an invalid direction")
        if not isinstance(rule.get("rationale"), str) or not rule["rationale"].strip():
            raise QualityGateError(f"metric {name} needs a rationale")
        if rule["direction"] == "hard_max":
            if set(rule) != {"direction", "maximum", "rationale"}:
                raise QualityGateError(f"metric {name} has an invalid hard-max rule")
            if _number(rule["maximum"], f"metric {name} maximum") < 0:
                raise QualityGateError(f"metric {name} maximum must be non-negative")
        else:
            if set(rule) != {
                "direction",
                "max_relative_regression",
                "max_absolute_regression",
                "rationale",
            }:
                raise QualityGateError(f"metric {name} has an invalid regression rule")
            if (
                _number(
                    rule["max_relative_regression"], f"metric {name} relative limit"
                )
                < 0
                or _number(
                    rule["max_absolute_regression"], f"metric {name} absolute limit"
                )
                < 0
            ):
                raise QualityGateError(
                    f"metric {name} regression limits must be non-negative"
                )
    return metrics


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def _relative_mad(values: list[float]) -> float:
    center = _median(values)
    deviation = _median([abs(value - center) for value in values])
    scale = max(abs(center), 1e-12)
    return deviation / scale


def evaluate(
    baseline: dict[str, Any], candidate: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    metrics = _validate_policy(policy)
    metric_names = set(metrics)
    minimum_runs = policy["minimum_runs"]
    _validate_report(
        baseline, label="baseline", metrics=metric_names, minimum_runs=minimum_runs
    )
    _validate_report(
        candidate, label="candidate", metrics=metric_names, minimum_runs=minimum_runs
    )

    environment_keys = policy["environment_keys"]
    missing = [
        key
        for key in environment_keys
        if key not in baseline["environment"] or key not in candidate["environment"]
    ]
    if missing:
        raise QualityGateError(
            f"reports are missing environment keys: {', '.join(missing)}"
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

    results: list[dict[str, Any]] = []
    failures: list[str] = []
    max_relative_mad = _number(
        policy["max_baseline_relative_mad"], "max_baseline_relative_mad"
    )
    for name, rule in metrics.items():
        baseline_values = [_number(run[name], name) for run in baseline["runs"]]
        candidate_values = [_number(run[name], name) for run in candidate["runs"]]
        baseline_median = _median(baseline_values)
        candidate_median = _median(candidate_values)
        baseline_relative_mad = _relative_mad(baseline_values)
        passed = True
        detail = ""

        if baseline_relative_mad > max_relative_mad:
            passed = False
            detail = (
                f"baseline relative MAD {baseline_relative_mad:.4f} exceeds "
                f"{max_relative_mad:.4f}"
            )
        elif rule["direction"] == "hard_max":
            limit = _number(rule["maximum"], f"metric {name} maximum")
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
            absolute = _number(
                rule["max_absolute_regression"], f"metric {name} absolute limit"
            )
            tolerance = max(relative, absolute)
            if rule["direction"] == "lower":
                limit = baseline_median + tolerance
                passed = candidate_median <= limit
                detail = f"candidate {candidate_median:.6g}; maximum {limit:.6g}"
            else:
                limit = baseline_median - tolerance
                passed = candidate_median >= limit
                detail = f"candidate {candidate_median:.6g}; minimum {limit:.6g}"

        result = {
            "metric": name,
            "passed": passed,
            "baseline_median": baseline_median,
            "candidate_median": candidate_median,
            "baseline_relative_mad": baseline_relative_mad,
            "detail": detail,
        }
        results.append(result)
        if not passed:
            failures.append(f"{name}: {detail}")

    return {"passed": not failures, "failures": failures, "metrics": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate(
            _load_json(args.baseline),
            _load_json(args.candidate),
            _load_json(args.policy),
        )
    except QualityGateError as error:
        print(f"hardware quality evidence rejected: {error}", file=sys.stderr)
        return 2

    if args.json_output:
        args.json_output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    for metric in result["metrics"]:
        marker = "PASS" if metric["passed"] else "FAIL"
        print(f"[{marker}] {metric['metric']}: {metric['detail']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
