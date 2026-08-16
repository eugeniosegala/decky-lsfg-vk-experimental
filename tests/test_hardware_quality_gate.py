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
    "workload_build": "sha256:test",
    "workload_settings_hash": "sha256:settings",
}
BASELINE_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40
ENGINE_SHA256 = "sha256:" + "a" * 64


def _policy():
    return {
        "schema": 1,
        "minimum_runs": 5,
        "max_baseline_relative_mad": 0.03,
        "environment_keys": list(ENVIRONMENT),
        "metrics": {
            "frame_time_p95_ms": {
                "direction": "lower",
                "max_relative_regression": 0.05,
                "max_absolute_regression": 0.5,
                "rationale": "frame pacing",
            },
            "generated_frame_ssim": {
                "direction": "higher",
                "max_relative_regression": 0.001,
                "max_absolute_regression": 0.001,
                "rationale": "image similarity",
            },
            "black_frame_count": {
                "direction": "hard_max",
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
                "frame_time_p95_ms": frame_time + offset,
                "generated_frame_ssim": ssim,
                "black_frame_count": black_frames,
            }
            for offset in (-0.1, -0.05, 0, 0.05, 0.1)
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
        self.assertIn("runs-on: [self-hosted, linux, x64, lsfg-hardware]", workflow)
        self.assertIn("/opt/lsfg-hardware/bin/capture-comparison", workflow)
        self.assertIn('--baseline-sha "$BASELINE_SHA"', workflow)
        self.assertIn('--candidate-sha "$CANDIDATE_SHA"', workflow)
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
        run = {name: 0.0 for name in policy["metrics"]}
        run["generated_frame_ssim"] = 1.0
        report = {
            "schema": 1,
            "environment": dict(ENVIRONMENT),
            "subject": {
                "git_sha": BASELINE_SHA,
                "engine_sha256": ENGINE_SHA256,
            },
            "runs": [dict(run) for _ in range(policy["minimum_runs"])],
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

    def test_nonfinite_and_boolean_metrics_are_rejected(self):
        for value in (True, float("nan"), float("inf")):
            with self.subTest(value=value):
                candidate = _report(git_sha=CANDIDATE_SHA)
                candidate["runs"][0]["frame_time_p95_ms"] = value
                with self.assertRaisesRegex(QualityGateError, "finite number"):
                    evaluate(_report(), candidate, _policy())

    def test_cli_writes_machine_readable_result_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "baseline": root / "baseline.json",
                "candidate": root / "candidate.json",
                "policy": root / "policy.json",
                "result": root / "result.json",
            }
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
                        "--json-output",
                        str(paths["result"]),
                    ]
                )

            self.assertEqual(return_code, 1)
            self.assertFalse(json.loads(paths["result"].read_text())["passed"])

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
                    ]
                )

            self.assertEqual(return_code, 2)


if __name__ == "__main__":
    unittest.main()
