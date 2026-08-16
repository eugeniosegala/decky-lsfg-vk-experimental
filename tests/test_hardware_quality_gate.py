from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.hardware_quality_gate import (
    MAX_JSON_BYTES,
    QualityGateError,
    evaluate,
    main,
)


ENVIRONMENT = {
    "target_id": "steam-deck-lcd-01",
    "os_build": "steamos-test",
    "kernel": "6.11-test",
    "mesa": "25.1-test",
    "gamescope": "3.16-test",
    "display_mode": "1280x800@60",
    "tdp_watts": 15,
    "gpu_clock_policy": "fixed-1200mhz",
    "workload_id": "lsfg-fixed-motion-v1",
    "workload_build": "sha256:" + "c" * 64,
    "workload_settings_hash": "sha256:" + "d" * 64,
    "capture_harness_sha256": "sha256:" + "b" * 64,
}
BASELINE_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40
ENGINE_SHA256 = "sha256:" + "a" * 64


def _policy():
    return {
        "schema": 1,
        "minimum_runs": 5,
        "max_baseline_relative_mad": 0.03,
        "max_candidate_relative_mad": 0.03,
        "maximum_baseline_outlier_runs": 0,
        "maximum_candidate_outlier_runs": 0,
        "maximum_regressed_runs": 0,
        "environment_keys": list(ENVIRONMENT),
        "run_invariants": [],
        "metrics": {
            "frame_time_p95_ms": {
                "direction": "lower",
                "value_type": "number",
                "minimum": 0,
                "exclusive_minimum": True,
                "maximum": None,
                "max_relative_regression": 0.05,
                "absolute_noise_floor": 0.5,
                "rationale": "frame pacing",
            },
            "generated_frame_ssim": {
                "direction": "higher",
                "value_type": "number",
                "minimum": 0,
                "exclusive_minimum": False,
                "maximum": 1,
                "max_relative_regression": 0.001,
                "absolute_noise_floor": 0.001,
                "rationale": "image similarity",
            },
            "black_frame_count": {
                "direction": "hard_max",
                "value_type": "integer",
                "minimum": 0,
                "exclusive_minimum": False,
                "maximum": 0,
                "rationale": "black frames are forbidden",
            },
        },
    }


def _report(frame_time=10.0, ssim=0.999, black_frames=0, git_sha=BASELINE_SHA):
    return {
        "schema": 1,
        "environment": dict(ENVIRONMENT),
        "subject": {"git_sha": git_sha, "engine_sha256": ENGINE_SHA256},
        "runs": [
            {
                "run_id": f"run-{index + 1}",
                "frame_time_p95_ms": frame_time + offset,
                "generated_frame_ssim": ssim,
                "black_frame_count": black_frames,
            }
            for index, offset in enumerate((-0.1, -0.05, 0, 0.05, 0.1))
        ],
    }


class HardwareQualityGateTests(unittest.TestCase):
    def test_hardware_workflow_is_manual_approved_and_read_only(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/hardware-validation.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("environment: steam-deck-hardware", workflow)
        self.assertIn("LSFG_HARDWARE_ENV_READY", workflow)
        self.assertIn("LSFG_HARDWARE_HARNESS_SHA256", workflow)
        self.assertIn("runs-on: [self-hosted, linux, x64, lsfg-hardware]", workflow)
        self.assertIn("/opt/lsfg-hardware/bin/capture-comparison", workflow)
        self.assertIn('--baseline-sha "$BASELINE_SHA"', workflow)
        self.assertIn('--candidate-sha "$CANDIDATE_SHA"', workflow)
        self.assertIn('[[ "$BASELINE_SHA" != "$CANDIDATE_SHA" ]]', workflow)
        self.assertIn(
            'merge-base --is-ancestor "$BASELINE_SHA" "$CANDIDATE_SHA"', workflow
        )
        self.assertIn("github.run_attempt", workflow)
        self.assertIn("sanitized-hardware-evidence", workflow)
        self.assertNotIn("${{ secrets.", workflow)
        self.assertLess(
            workflow.index("Capture repeated target-hardware evidence"),
            workflow.index("Check out trusted gate implementation after capture"),
        )

    def test_repository_policy_accepts_a_stable_complete_report(self):
        root = Path(__file__).resolve().parents[1]
        policy = json.loads(
            (root / ".github/hardware-quality-policy.json").read_text(encoding="utf-8")
        )
        run = {
            name: 1.0 if rule["exclusive_minimum"] else 0.0
            for name, rule in policy["metrics"].items()
        }
        run["generated_frame_ssim"] = 1.0
        report = {
            "schema": 1,
            "environment": dict(ENVIRONMENT),
            "subject": {
                "git_sha": BASELINE_SHA,
                "engine_sha256": ENGINE_SHA256,
            },
            "runs": [
                {"run_id": f"run-{index + 1}", **run}
                for index in range(policy["minimum_runs"])
            ],
        }

        self.assertTrue(evaluate(report, report, policy)["passed"])

    def test_equivalent_stable_reports_pass(self):
        result = evaluate(
            _report(), _report(frame_time=10.2, git_sha=CANDIDATE_SHA), _policy()
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["failures"], [])

    def test_environment_mismatch_rejects_comparison(self):
        candidate = _report(git_sha=CANDIDATE_SHA)
        candidate["environment"]["mesa"] = "different"
        with self.assertRaisesRegex(QualityGateError, "environments differ: mesa"):
            evaluate(_report(), candidate, _policy())

    def test_extra_environment_field_rejects_comparison(self):
        candidate = _report(git_sha=CANDIDATE_SHA)
        candidate["environment"]["cpu_governor"] = "performance"
        with self.assertRaisesRegex(QualityGateError, "environment fields"):
            evaluate(_report(), candidate, _policy())

    def test_environment_hashes_and_tdp_are_strict(self):
        cases = (
            ("workload_build", "sha256:bad", "workload_build"),
            ("workload_settings_hash", "not-a-hash", "workload_settings_hash"),
            ("capture_harness_sha256", "sha256:bad", "capture_harness_sha256"),
            ("target_id", True, "target_id"),
            ("tdp_watts", True, "tdp_watts"),
            ("tdp_watts", 0, "positive"),
        )
        for key, value, message in cases:
            with self.subTest(key=key, value=value):
                candidate = _report(git_sha=CANDIDATE_SHA)
                candidate["environment"][key] = value
                with self.assertRaisesRegex(QualityGateError, message):
                    evaluate(_report(), candidate, _policy())

    def test_report_harness_hash_must_match_attested_executable(self):
        with self.assertRaisesRegex(QualityGateError, "attested capture harness"):
            evaluate(
                _report(),
                _report(git_sha=CANDIDATE_SHA),
                _policy(),
                expected_capture_harness_sha256="sha256:" + "e" * 64,
            )

    def test_insufficient_repetitions_reject_evidence(self):
        candidate = _report(git_sha=CANDIDATE_SHA)
        candidate["runs"] = candidate["runs"][:2]
        with self.assertRaisesRegex(QualityGateError, "at least 5"):
            evaluate(_report(), candidate, _policy())

    def test_frame_time_regression_fails(self):
        result = evaluate(
            _report(), _report(frame_time=11.0, git_sha=CANDIDATE_SHA), _policy()
        )
        self.assertFalse(result["passed"])
        self.assertRegex(result["failures"][0], "frame_time_p95_ms")

    def test_visual_similarity_regression_fails(self):
        result = evaluate(
            _report(), _report(ssim=0.990, git_sha=CANDIDATE_SHA), _policy()
        )
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("generated_frame_ssim" in item for item in result["failures"])
        )

    def test_hard_failure_counter_fails_even_when_baseline_matches(self):
        candidate = _report(git_sha=CANDIDATE_SHA)
        candidate["runs"][0]["black_frame_count"] = 1
        result = evaluate(_report(), candidate, _policy())
        self.assertFalse(result["passed"])
        self.assertTrue(any("black_frame_count" in item for item in result["failures"]))

    def test_noisy_baseline_is_rejected_instead_of_blessing_a_regression(self):
        baseline = _report()
        for run, value in zip(baseline["runs"], (7.0, 8.0, 10.0, 12.0, 13.0)):
            run["frame_time_p95_ms"] = value
        result = evaluate(baseline, _report(git_sha=CANDIDATE_SHA), _policy())
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("baseline relative MAD" in item for item in result["failures"])
        )

    def test_baseline_outliers_fail_even_when_mad_is_zero(self):
        baseline = _report()
        for run, value in zip(baseline["runs"], (10, 10, 10, 1000, 1000)):
            run["frame_time_p95_ms"] = value
        result = evaluate(baseline, _report(git_sha=CANDIDATE_SHA), _policy())
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("baseline outlier runs 2" in item for item in result["failures"])
        )

    def test_noisy_candidate_is_rejected(self):
        policy = _policy()
        policy["maximum_regressed_runs"] = 4
        candidate = _report(git_sha=CANDIDATE_SHA)
        for run, value in zip(candidate["runs"], (7.0, 8.0, 10.0, 12.0, 13.0)):
            run["frame_time_p95_ms"] = value
        result = evaluate(_report(), candidate, policy)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("candidate relative MAD" in item for item in result["failures"])
        )

    def test_two_catastrophic_candidate_runs_fail_even_when_median_passes(self):
        candidate = _report(git_sha=CANDIDATE_SHA)
        for run, value in zip(candidate["runs"], (1000, 1000, 10, 10.05, 10.1)):
            run["frame_time_p95_ms"] = value
        result = evaluate(_report(), candidate, _policy())
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("candidate outlier runs 2" in item for item in result["failures"])
        )

    def test_candidate_regressed_run_allowance_is_enforced(self):
        policy = _policy()
        policy["maximum_regressed_runs"] = 1
        policy["maximum_candidate_outlier_runs"] = 4
        candidate = _report(git_sha=CANDIDATE_SHA)
        candidate["runs"][0]["frame_time_p95_ms"] = 100
        self.assertTrue(evaluate(_report(), candidate, policy)["passed"])
        candidate["runs"][1]["frame_time_p95_ms"] = 100
        self.assertFalse(evaluate(_report(), candidate, policy)["passed"])

    def test_duplicate_run_id_does_not_satisfy_minimum_independent_runs(self):
        candidate = _report(git_sha=CANDIDATE_SHA)
        for run in candidate["runs"]:
            run["run_id"] = "same-run"
        with self.assertRaisesRegex(QualityGateError, "unique run_id"):
            evaluate(_report(), candidate, _policy())

    def test_nonfinite_and_boolean_metrics_are_rejected(self):
        for value in (True, float("nan"), float("inf")):
            with self.subTest(value=value):
                candidate = _report(git_sha=CANDIDATE_SHA)
                candidate["runs"][0]["frame_time_p95_ms"] = value
                with self.assertRaisesRegex(QualityGateError, "finite number"):
                    evaluate(_report(), candidate, _policy())

    def test_metric_domains_reject_impossible_measurements(self):
        cases = (
            ("frame_time_p95_ms", -0.01, "greater than 0"),
            ("generated_frame_ssim", -0.01, "at least 0"),
            ("generated_frame_ssim", 1.01, "at most 1"),
            ("black_frame_count", -1, "at least 0"),
            ("black_frame_count", 0.5, "integer"),
        )
        for metric, value, message in cases:
            with self.subTest(metric=metric, value=value):
                candidate = _report(git_sha=CANDIDATE_SHA)
                candidate["runs"][0][metric] = value
                with self.assertRaisesRegex(QualityGateError, message):
                    evaluate(_report(), candidate, _policy())

    def test_metric_cross_field_invariants_reject_impossible_percentiles(self):
        policy = _policy()
        policy["metrics"]["frame_time_p99_ms"] = {
            **policy["metrics"]["frame_time_p95_ms"],
            "rationale": "tail frame pacing",
        }
        policy["run_invariants"] = [
            {
                "left": "frame_time_p99_ms",
                "operator": "gte",
                "right": "frame_time_p95_ms",
                "rationale": "p99 cannot be lower than p95",
            }
        ]
        baseline = _report()
        candidate = _report(git_sha=CANDIDATE_SHA)
        for report in (baseline, candidate):
            for run in report["runs"]:
                run["frame_time_p95_ms"] = 20
                run["frame_time_p99_ms"] = 10
        with self.assertRaisesRegex(QualityGateError, "frame_time_p99_ms.*gte"):
            evaluate(baseline, candidate, policy)

    def test_cli_writes_machine_readable_result_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "baseline": root / "baseline.json",
                "candidate": root / "candidate.json",
                "policy": root / "policy.json",
                "result": root / "result.json",
                "evidence": root / "evidence",
            }
            paths["evidence"].mkdir()
            documents = {
                "baseline": _report(),
                "candidate": _report(frame_time=11.0, git_sha=CANDIDATE_SHA),
                "policy": _policy(),
            }
            for name, document in documents.items():
                paths[name].write_text(json.dumps(document), encoding="utf-8")

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                return_code = main(
                    [
                        "--baseline",
                        str(paths["baseline"]),
                        "--candidate",
                        str(paths["candidate"]),
                        "--policy",
                        str(paths["policy"]),
                        "--baseline-sha",
                        BASELINE_SHA,
                        "--candidate-sha",
                        CANDIDATE_SHA,
                        "--capture-harness-sha256",
                        ENVIRONMENT["capture_harness_sha256"],
                        "--gate-sha",
                        "f" * 40,
                        "--json-output",
                        str(paths["result"]),
                        "--evidence-output-dir",
                        str(paths["evidence"]),
                    ]
                )

            self.assertEqual(return_code, 1)
            result = json.loads(paths["result"].read_text())
            self.assertFalse(result["passed"])
            self.assertEqual(result["provenance"]["gate_sha"], "f" * 40)
            self.assertEqual(
                result["provenance"]["capture_harness_sha256"],
                ENVIRONMENT["capture_harness_sha256"],
            )
            self.assertEqual(
                json.loads((paths["evidence"] / "baseline.json").read_text()),
                documents["baseline"],
            )
            self.assertEqual(
                json.loads((paths["evidence"] / "candidate.json").read_text()),
                documents["candidate"],
            )

    def test_report_subject_must_match_requested_commit(self):
        with self.assertRaisesRegex(QualityGateError, "requested commit SHA"):
            evaluate(
                _report(),
                _report(git_sha=CANDIDATE_SHA),
                _policy(),
                expected_baseline_sha="3" * 40,
                expected_candidate_sha=CANDIDATE_SHA,
            )

    def test_subject_requires_full_git_and_engine_hashes(self):
        for field, value in (("git_sha", "short"), ("engine_sha256", "sha256:bad")):
            with self.subTest(field=field):
                candidate = _report(git_sha=CANDIDATE_SHA)
                candidate["subject"][field] = value
                with self.assertRaisesRegex(QualityGateError, field):
                    evaluate(_report(), candidate, _policy())

    def test_cli_rejects_oversized_evidence_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            oversized = root / "oversized.json"
            oversized.write_bytes(b"{" + b" " * MAX_JSON_BYTES)

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                return_code = main(
                    [
                        "--baseline",
                        str(oversized),
                        "--candidate",
                        str(oversized),
                        "--policy",
                        str(oversized),
                        "--baseline-sha",
                        BASELINE_SHA,
                        "--candidate-sha",
                        CANDIDATE_SHA,
                        "--json-output",
                        str(root / "result.json"),
                    ]
                )

            self.assertEqual(return_code, 2)
            result = json.loads((root / "result.json").read_text(encoding="utf-8"))
            self.assertFalse(result["passed"])
            self.assertIn("exceeds", result["error"])


if __name__ == "__main__":
    unittest.main()
