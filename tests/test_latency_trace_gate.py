from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import scripts.latency_trace_gate as latency_trace_gate
from scripts.latency_trace_gate import (
    EXIT_INVALID_TRACE,
    EXIT_USAGE,
    MAX_EVENT_COUNT,
    MAX_FILE_BYTES,
    LatencyTraceError,
    evaluate_trace,
    load_trace,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "latency-traces"


def _records(name: str = "valid-real-only.jsonl") -> list[dict]:
    return load_trace(FIXTURES / name)


def _event(records: list[dict], event: str) -> dict:
    return next(record for record in records if record.get("event") == event)


def _renumber(records: list[dict]) -> None:
    for sequence, record in enumerate(records[1:], start=1):
        record["sequence"] = sequence


def _enable_feedback(records: list[dict]) -> None:
    records[0]["capabilities"].update(
        {
            "presentation_feedback": True,
            "feedback_clock_domain": records[0]["clock"]["domain"],
        }
    )


def _feedback(
    output_frame_id: str,
    *,
    feedback_timestamp_ns: int | None,
    event_timestamp_ns: int,
    status: str = "presented",
) -> dict:
    return {
        "record": "event",
        "sequence": 0,
        "timestamp_ns": event_timestamp_ns,
        "context_id": "ctx",
        "epoch": 0,
        "event": "presentation_feedback",
        "data": {
            "output_frame_id": output_frame_id,
            "feedback_timestamp_ns": feedback_timestamp_ns,
            "status": status,
        },
    }


class LatencyTraceContractTests(unittest.TestCase):
    def test_hand_authored_real_only_trace_has_deterministic_proxy(self):
        first = evaluate_trace(_records())
        second = evaluate_trace(_records())

        self.assertEqual(first, second)
        self.assertTrue(first["valid"])
        self.assertEqual(
            first["summary"]["real_ready_to_present_call_proxy_ns"],
            {
                "sample_count": 1,
                "p50": 200,
                "p95": 200,
                "p99": 200,
                "unavailable_reason": None,
            },
        )
        self.assertEqual(
            first["summary"]["input_observed_to_present_call_entry_proxy_ns"]["p95"],
            600,
        )

    def test_partial_prefix_counts_frames_not_batches(self):
        result = evaluate_trace(_records("valid-partial-prefix.jsonl"))

        self.assertEqual(result["summary"]["batch_count"], 1)
        self.assertEqual(result["summary"]["planned_generated_frame_count"], 3)
        self.assertEqual(result["summary"]["admitted_generated_frame_count"], 1)
        self.assertEqual(result["summary"]["skipped_generated_frame_count"], 2)
        self.assertEqual(result["summary"]["maximum_queue_depth"], 1)

    def test_generated_slot_deadlines_follow_temporal_order(self):
        records = _records("valid-partial-prefix.jsonl")
        slots = [
            record
            for record in records
            if record.get("event") == "generated_slot_planned"
        ]
        slots[1]["data"]["deadline_ns"] = slots[0]["data"]["deadline_ns"] - 1

        with self.assertRaisesRegex(LatencyTraceError, "nondecreasing"):
            evaluate_trace(records)

    def test_runtime_failures_are_valid_bad_evidence(self):
        result = evaluate_trace(_records("valid-runtime-failure.jsonl"))

        self.assertTrue(result["valid"])
        self.assertEqual(result["summary"]["present_results"]["out_of_date"], 1)
        self.assertEqual(result["summary"]["recovery_failed_count"], 1)

    def test_failed_real_present_attempts_do_not_create_latency_samples(self):
        for result in ("timeout", "out_of_date", "error"):
            with self.subTest(result=result):
                records = _records()
                _event(records, "present_call_returned")["data"]["result"] = result

                summary = evaluate_trace(records)["summary"]

                self.assertEqual(
                    summary["real_ready_to_present_call_proxy_ns"]["sample_count"],
                    0,
                )
                self.assertEqual(
                    summary["input_observed_to_present_call_entry_proxy_ns"][
                        "sample_count"
                    ],
                    0,
                )

    def test_failed_only_real_attempts_have_an_exact_unavailable_reason(self):
        records = _records()
        _event(records, "present_call_returned")["data"]["result"] = "error"

        metric = evaluate_trace(records)["summary"][
            "real_ready_to_present_call_proxy_ns"
        ]

        self.assertEqual(metric["unavailable_reason"], "no_successful_real_presents")

    def test_failed_real_present_with_input_mapping_has_precise_reasons(self):
        records = _records()
        _event(records, "present_call_returned")["data"]["result"] = "error"

        summary = evaluate_trace(records)["summary"]

        self.assertIn("input_observed_to_present_call_entry_proxy_ns", summary)
        self.assertIn("input_observed_to_real_feedback_proxy_ns", summary)
        self.assertEqual(
            summary["input_observed_to_present_call_entry_proxy_ns"][
                "unavailable_reason"
            ],
            "no_successful_real_present_for_input_boundary",
        )
        self.assertEqual(
            summary["input_observed_to_real_feedback_proxy_ns"]["unavailable_reason"],
            "presentation_feedback_unavailable",
        )

    def test_dangling_simulation_is_invalid_for_every_closure_policy(self):
        for closure_policy in ("strict", "allow_idle_abandonment"):
            with self.subTest(closure_policy=closure_policy):
                records = _records()
                records = [
                    record
                    for record in records
                    if record.get("event")
                    not in {
                        "real_frame_ready",
                        "present_call_started",
                        "present_call_returned",
                    }
                ]
                for record in records:
                    if record.get("event") == "context_destroyed":
                        record["data"]["closure_policy"] = closure_policy
                _renumber(records)

                with self.assertRaisesRegex(
                    LatencyTraceError,
                    "simulation_started lacking real_frame_ready",
                ):
                    evaluate_trace(records)

    def test_generated_frame_cannot_reuse_a_simulation_output_id(self):
        records = _records("valid-partial-prefix.jsonl")
        context_index = next(
            index
            for index, record in enumerate(records)
            if record.get("event") == "context_created"
        )
        records[context_index + 1 : context_index + 1] = [
            {
                "record": "event",
                "sequence": 0,
                "timestamp_ns": 50,
                "context_id": "ctx",
                "epoch": 0,
                "event": "input_observed",
                "data": {"input_id": "input-future"},
            },
            {
                "record": "event",
                "sequence": 0,
                "timestamp_ns": 50,
                "context_id": "ctx",
                "epoch": 0,
                "event": "simulation_started",
                "data": {
                    "input_id": "input-future",
                    "real_frame_id": "future-real",
                },
            },
        ]
        _renumber(records)
        generated = _event(records, "generated_slot_planned")
        generated["data"]["generated_frame_id"] = "future-real"

        with self.assertRaisesRegex(
            LatencyTraceError,
            "output frame ids must be unique per epoch",
        ):
            evaluate_trace(records)

    def test_feedback_reason_distinguishes_capability_from_missing_feedback(self):
        without_feedback = _records()
        summary = evaluate_trace(without_feedback)["summary"]
        self.assertEqual(
            summary["input_observed_to_real_feedback_proxy_ns"]["unavailable_reason"],
            "presentation_feedback_unavailable",
        )

        with_feedback = _records()
        _enable_feedback(with_feedback)
        present_return_index = next(
            index
            for index, record in enumerate(with_feedback)
            if record.get("event") == "present_call_returned"
        )
        present = with_feedback[present_return_index]
        with_feedback.insert(
            present_return_index + 1,
            _feedback(
                present["data"]["output_frame_id"],
                feedback_timestamp_ns=None,
                event_timestamp_ns=present["timestamp_ns"],
                status="dropped",
            ),
        )
        _renumber(with_feedback)

        summary = evaluate_trace(with_feedback)["summary"]
        self.assertEqual(
            summary["input_observed_to_real_feedback_proxy_ns"]["unavailable_reason"],
            "no_presented_feedback_for_input_boundary",
        )

    def test_absent_input_mapping_reserves_input_boundary_unavailable_reason(self):
        summary = evaluate_trace(_records("valid-runtime-failure.jsonl"))["summary"]

        self.assertIn("input_observed_to_present_call_entry_proxy_ns", summary)
        self.assertIn("input_observed_to_real_feedback_proxy_ns", summary)
        self.assertEqual(
            summary["input_observed_to_present_call_entry_proxy_ns"][
                "unavailable_reason"
            ],
            "input_boundary_unavailable",
        )
        self.assertEqual(
            summary["input_observed_to_real_feedback_proxy_ns"]["unavailable_reason"],
            "input_boundary_unavailable",
        )

    def test_equal_timestamps_are_valid_but_decreasing_timestamps_are_not(self):
        records = _records()
        records[4]["timestamp_ns"] = records[3]["timestamp_ns"]
        self.assertTrue(evaluate_trace(records)["valid"])

        records[4]["timestamp_ns"] = records[3]["timestamp_ns"] - 1
        with self.assertRaisesRegex(LatencyTraceError, "timestamp"):
            evaluate_trace(records)

    def test_sequence_must_be_strict_and_integer_not_boolean(self):
        for value, message in ((1, "sequence"), (True, "integer")):
            with self.subTest(value=value):
                records = _records()
                records[2]["sequence"] = value
                with self.assertRaisesRegex(LatencyTraceError, message):
                    evaluate_trace(records)

    def test_event_sequence_must_not_skip_a_value(self):
        records = _records()
        for record in records[2:]:
            record["sequence"] += 1

        with self.assertRaisesRegex(LatencyTraceError, "contiguous"):
            evaluate_trace(records)

    def test_end_sequence_must_immediately_follow_the_last_event(self):
        records = _records()
        records[-1]["sequence"] += 1

        with self.assertRaisesRegex(LatencyTraceError, "contiguous"):
            evaluate_trace(records)

    def test_first_real_index_in_each_context_epoch_must_be_zero(self):
        records = _records()
        _event(records, "real_frame_ready")["data"]["real_index"] = 1
        _event(records, "present_call_started")["data"]["content_order"][
            "right_real_index"
        ] = 1

        with self.assertRaisesRegex(LatencyTraceError, "real_index.*zero"):
            evaluate_trace(records)

    def test_real_indices_must_be_contiguous_within_a_context_epoch(self):
        records = _records()
        second_frame = [
            {
                "record": "event",
                "sequence": 0,
                "timestamp_ns": 760,
                "context_id": "ctx",
                "epoch": 0,
                "event": "real_frame_ready",
                "data": {"real_frame_id": "real-2", "real_index": 2},
            },
            {
                "record": "event",
                "sequence": 0,
                "timestamp_ns": 770,
                "context_id": "ctx",
                "epoch": 0,
                "event": "present_call_started",
                "data": {
                    "output_kind": "real",
                    "output_frame_id": "real-2",
                    "queue_depth": 0,
                    "content_order": {
                        "right_real_index": 2,
                        "numerator": 1,
                        "denominator": 1,
                    },
                },
            },
            {
                "record": "event",
                "sequence": 0,
                "timestamp_ns": 780,
                "context_id": "ctx",
                "epoch": 0,
                "event": "present_call_returned",
                "data": {"output_frame_id": "real-2", "result": "success"},
            },
        ]
        records[-2:-2] = second_frame
        _renumber(records)

        with self.assertRaisesRegex(LatencyTraceError, "real_index.*contiguous"):
            evaluate_trace(records)

    def test_unknown_fields_events_and_scope_fail_closed(self):
        cases = []
        extra = _records()
        extra[0]["surprise"] = True
        cases.append((extra, "fields"))
        event = _records()
        event[1]["event"] = "magic_latency"
        cases.append((event, "event"))
        scope = _records()
        scope[0]["measurement_scope"] = "input_to_photon"
        cases.append((scope, "measurement_scope"))
        for records, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(LatencyTraceError, message):
                    evaluate_trace(records)

    def test_hashes_are_strict(self):
        bad_hash = _records()
        bad_hash[0]["subject"]["config_sha256"] = "sha256:nope"
        with self.assertRaisesRegex(LatencyTraceError, "config_sha256"):
            evaluate_trace(bad_hash)

    def test_v1_rejects_native_scope_until_native_semantics_are_defined(self):
        records = _records()
        records[0]["measurement_scope"] = "native_software_proxy"

        with self.assertRaisesRegex(LatencyTraceError, "native.*reserved"):
            evaluate_trace(records)

    def test_feedback_requires_same_normalized_clock_and_valid_present(self):
        records = _records()
        records[0]["capabilities"].update(
            {"presentation_feedback": True, "feedback_clock_domain": "other"}
        )
        with self.assertRaisesRegex(LatencyTraceError, "feedback_clock_domain"):
            evaluate_trace(records)

        records = _records()
        records[0]["capabilities"].update(
            {
                "presentation_feedback": True,
                "feedback_clock_domain": "synthetic_monotonic",
            }
        )
        feedback = {
            "record": "event",
            "sequence": 7,
            "timestamp_ns": 900,
            "context_id": "ctx",
            "epoch": 0,
            "event": "presentation_feedback",
            "data": {
                "output_frame_id": "real-0",
                "feedback_timestamp_ns": 900,
                "status": "presented",
            },
        }
        records.insert(-2, feedback)
        records[-2]["sequence"] = 8
        records[-2]["timestamp_ns"] = 900
        records[-1]["sequence"] = 9
        records[-1]["timestamp_ns"] = 900
        result = evaluate_trace(records)
        self.assertEqual(
            result["summary"]["present_call_to_feedback_proxy_ns"]["p50"], 200
        )

        records = _records()
        records[0]["capabilities"].update(
            {
                "presentation_feedback": True,
                "feedback_clock_domain": "synthetic_monotonic",
            }
        )
        feedback["timestamp_ns"] = 760
        records.insert(-2, deepcopy(feedback))
        records[-2]["sequence"] = 8
        records[-1]["sequence"] = 9
        with self.assertRaisesRegex(LatencyTraceError, "future"):
            evaluate_trace(records)

    def test_no_feedback_is_unavailable_not_zero(self):
        metric = evaluate_trace(_records())["summary"][
            "present_call_to_feedback_proxy_ns"
        ]
        self.assertIsNone(metric["p50"])
        self.assertEqual(metric["sample_count"], 0)
        self.assertEqual(
            metric["unavailable_reason"], "presentation_feedback_unavailable"
        )

    def test_feedback_capability_requires_feedback_for_every_successful_present(self):
        for result in ("success", "suboptimal"):
            with self.subTest(result=result):
                records = _records()
                _enable_feedback(records)
                _event(records, "present_call_returned")["data"]["result"] = result

                with self.assertRaisesRegex(LatencyTraceError, "missing.*feedback"):
                    evaluate_trace(records)

    def test_feedback_capability_rejects_selectively_missing_feedback(self):
        records = _records("valid-partial-prefix.jsonl")
        _enable_feedback(records)
        records.insert(
            -2,
            _feedback(
                "gen-1",
                feedback_timestamp_ns=1660,
                event_timestamp_ns=1760,
            ),
        )
        _renumber(records)

        with self.assertRaisesRegex(LatencyTraceError, "missing.*feedback"):
            evaluate_trace(records)

    def test_feedback_summary_separates_real_and_generated_present_samples(self):
        records = _records("valid-partial-prefix.jsonl")
        _enable_feedback(records)
        records[-2:-2] = [
            _feedback(
                "real-0",
                feedback_timestamp_ns=300,
                event_timestamp_ns=1760,
            ),
            _feedback(
                "gen-1",
                feedback_timestamp_ns=1660,
                event_timestamp_ns=1770,
            ),
            _feedback(
                "real-1",
                feedback_timestamp_ns=1760,
                event_timestamp_ns=1780,
            ),
        ]
        _event(records, "context_destroyed")["timestamp_ns"] = 1780
        records[-1]["timestamp_ns"] = 1780
        _renumber(records)

        summary = evaluate_trace(records)["summary"]
        self.assertIn("real_present_call_to_feedback_proxy_ns", summary)
        self.assertIn("generated_present_call_to_feedback_proxy_ns", summary)
        self.assertEqual(
            summary["real_present_call_to_feedback_proxy_ns"]["sample_count"], 2
        )
        self.assertEqual(
            summary["generated_present_call_to_feedback_proxy_ns"]["sample_count"],
            1,
        )

    def test_feedback_summary_reports_direct_real_and_input_boundaries(self):
        records = _records()
        _enable_feedback(records)
        records.insert(
            -2,
            _feedback(
                "real-0",
                feedback_timestamp_ns=770,
                event_timestamp_ns=780,
            ),
        )
        _renumber(records)

        summary = evaluate_trace(records)["summary"]
        self.assertIn("real_ready_to_presentation_feedback_proxy_ns", summary)
        self.assertIn("input_observed_to_real_feedback_proxy_ns", summary)
        self.assertEqual(
            summary["real_ready_to_presentation_feedback_proxy_ns"]["p50"], 270
        )
        self.assertEqual(
            summary["input_observed_to_real_feedback_proxy_ns"]["p50"],
            670,
        )

    def test_dropped_feedback_is_valid_and_fully_accounted(self):
        records = _records()
        _enable_feedback(records)
        records.insert(
            -2,
            _feedback(
                "real-0",
                feedback_timestamp_ns=None,
                event_timestamp_ns=780,
                status="dropped",
            ),
        )
        _renumber(records)

        result = evaluate_trace(records)
        summary = result["summary"]

        self.assertTrue(result["valid"])
        self.assertEqual(summary["expected_feedback_count"], 1)
        self.assertEqual(summary["received_feedback_count"], 1)
        self.assertEqual(summary["presented_feedback_count"], 0)
        self.assertEqual(summary["dropped_feedback_count"], 1)
        self.assertEqual(summary["unknown_feedback_count"], 0)
        self.assertNotIn("missing_feedback_count", summary)
        self.assertEqual(
            summary["received_feedback_count"],
            summary["presented_feedback_count"]
            + summary["dropped_feedback_count"]
            + summary["unknown_feedback_count"],
        )

    def test_unknown_feedback_is_valid_and_fully_accounted(self):
        records = _records()
        _enable_feedback(records)
        records.insert(
            -2,
            _feedback(
                "real-0",
                feedback_timestamp_ns=None,
                event_timestamp_ns=780,
                status="unknown",
            ),
        )
        _renumber(records)

        result = evaluate_trace(records)
        summary = result["summary"]

        self.assertTrue(result["valid"])
        self.assertEqual(summary["expected_feedback_count"], 1)
        self.assertEqual(summary["received_feedback_count"], 1)
        self.assertEqual(summary["presented_feedback_count"], 0)
        self.assertEqual(summary["dropped_feedback_count"], 0)
        self.assertEqual(summary["unknown_feedback_count"], 1)
        self.assertNotIn("missing_feedback_count", summary)
        self.assertEqual(
            summary["received_feedback_count"],
            summary["presented_feedback_count"]
            + summary["dropped_feedback_count"]
            + summary["unknown_feedback_count"],
        )

    def test_nonpresented_feedback_has_exact_boundary_unavailable_reasons(self):
        for status in ("dropped", "unknown"):
            with self.subTest(status=status):
                records = _records()
                _enable_feedback(records)
                records.insert(
                    -2,
                    _feedback(
                        "real-0",
                        feedback_timestamp_ns=None,
                        event_timestamp_ns=780,
                        status=status,
                    ),
                )
                _renumber(records)

                summary = evaluate_trace(records)["summary"]

                self.assertEqual(
                    summary["real_present_call_to_feedback_proxy_ns"][
                        "unavailable_reason"
                    ],
                    "no_presented_real_feedback",
                )
                self.assertEqual(
                    summary["generated_present_call_to_feedback_proxy_ns"][
                        "unavailable_reason"
                    ],
                    "no_presented_generated_feedback",
                )
                self.assertEqual(
                    summary["input_observed_to_real_feedback_proxy_ns"][
                        "unavailable_reason"
                    ],
                    "no_presented_feedback_for_input_boundary",
                )

    def test_simulation_cannot_start_after_its_output_frame_exists(self):
        records = _records()
        simulation = _event(records, "simulation_started")
        records.remove(simulation)
        real_ready_index = records.index(_event(records, "real_frame_ready"))
        simulation["timestamp_ns"] = 600
        records.insert(real_ready_index + 1, simulation)
        for sequence, record in enumerate(records[1:], start=1):
            record["sequence"] = sequence
            record["timestamp_ns"] = max(record["timestamp_ns"], 600)
        with self.assertRaisesRegex(LatencyTraceError, "already exists"):
            evaluate_trace(records)

    def test_content_order_uses_one_based_exact_rational_slots(self):
        records = _records("valid-partial-prefix.jsonl")
        present = next(
            record
            for record in records
            if record.get("event") == "present_call_started"
            and record["data"]["output_kind"] == "generated"
        )
        present["data"]["content_order"]["numerator"] = 0
        with self.assertRaisesRegex(LatencyTraceError, "content_order"):
            evaluate_trace(records)

    def test_temporal_inversion_is_invalid(self):
        records = _records("valid-partial-prefix.jsonl")
        generated_present = next(
            index
            for index, record in enumerate(records)
            if record.get("event") == "present_call_started"
            and record["data"]["output_kind"] == "generated"
        )
        real_present = next(
            index
            for index, record in enumerate(records)
            if record.get("event") == "present_call_started"
            and record["data"]["output_frame_id"] == "real-1"
        )
        generated_pair = records[generated_present : generated_present + 2]
        real_pair = records[real_present : real_present + 2]
        records[generated_present : real_present + 2] = real_pair + generated_pair
        for record in records[generated_present:]:
            record["timestamp_ns"] = 1800
        _renumber(records)

        with self.assertRaisesRegex(LatencyTraceError, "content order"):
            evaluate_trace(records)

    def test_admission_at_deadline_is_valid_and_after_deadline_is_invalid(self):
        records = _records("valid-partial-prefix.jsonl")
        admission = _event(records, "generated_batch_admitted")
        admission["timestamp_ns"] = 2000
        admission_index = records.index(admission)
        for record in records[admission_index + 1 :]:
            record["timestamp_ns"] = max(record["timestamp_ns"], 2000)
        self.assertTrue(evaluate_trace(records)["valid"])

        admission["timestamp_ns"] = 2001
        for record in records[admission_index + 1 :]:
            record["timestamp_ns"] = max(record["timestamp_ns"], 2001)
        with self.assertRaisesRegex(LatencyTraceError, "deadline"):
            evaluate_trace(records)

    def test_deadline_applies_to_present_call_entry_not_return_or_display(self):
        records = _records("valid-partial-prefix.jsonl")
        _enable_feedback(records)
        generated_start = next(
            record
            for record in records
            if record.get("event") == "present_call_started"
            and record["data"]["output_kind"] == "generated"
        )
        generated_return = next(
            record
            for record in records
            if record.get("event") == "present_call_returned"
            and record["data"]["output_frame_id"] == "gen-1"
        )
        generated_start["timestamp_ns"] = 2000
        generated_return["timestamp_ns"] = 2500
        start_index = records.index(generated_start)
        for record in records[start_index + 2 :]:
            record["timestamp_ns"] = max(record["timestamp_ns"], 2500)
        records[-2:-2] = [
            _feedback(
                "real-0",
                feedback_timestamp_ns=2400,
                event_timestamp_ns=2600,
            ),
            _feedback(
                "gen-1",
                feedback_timestamp_ns=2600,
                event_timestamp_ns=2700,
            ),
            _feedback(
                "real-1",
                feedback_timestamp_ns=2750,
                event_timestamp_ns=2750,
            ),
        ]
        _event(records, "context_destroyed")["timestamp_ns"] = 2800
        records[-1]["timestamp_ns"] = 2800
        _renumber(records)

        self.assertTrue(evaluate_trace(records)["valid"])

    def test_late_present_is_derived_from_present_call_timestamp(self):
        records = _records("valid-partial-prefix.jsonl")
        present_index = next(
            index
            for index, record in enumerate(records)
            if record.get("event") == "present_call_started"
            and record["data"]["output_kind"] == "generated"
        )
        records[present_index]["timestamp_ns"] = 2001
        records[present_index + 1]["timestamp_ns"] = 2050
        for record in records[present_index + 2 :]:
            record["timestamp_ns"] = max(record["timestamp_ns"], 2050)
        result = evaluate_trace(records)
        self.assertEqual(result["summary"]["late_generated_present_call_count"], 1)

        miss = {
            "record": "event",
            "sequence": records[present_index]["sequence"],
            "timestamp_ns": 2001,
            "context_id": "ctx",
            "epoch": 0,
            "event": "deadline_missed",
            "data": {
                "batch_id": "batch-1",
                "generated_frame_id": "gen-1",
                "deadline_ns": 2000,
            },
        }
        records.insert(present_index, miss)
        for sequence, record in enumerate(records[1:], start=1):
            record["sequence"] = sequence
        with self.assertRaisesRegex(
            LatencyTraceError, "unknown event.*deadline_missed"
        ):
            evaluate_trace(records)

    def test_legacy_deadline_miss_is_rejected_for_skipped_or_admitted_slots(self):
        records = _records("valid-partial-prefix.jsonl")
        generation_start = records.index(_event(records, "generation_started"))
        next(
            record
            for record in records
            if record.get("event") == "generated_slot_planned"
            and record["data"]["generated_frame_id"] == "gen-2"
        )["data"]["deadline_ns"] = 3000
        skipped_miss = {
            "record": "event",
            "sequence": 0,
            "timestamp_ns": 3100,
            "context_id": "ctx",
            "epoch": 0,
            "event": "deadline_missed",
            "data": {
                "batch_id": "batch-1",
                "generated_frame_id": "gen-2",
                "deadline_ns": 3000,
            },
        }
        records.insert(generation_start, skipped_miss)
        for sequence, record in enumerate(records[1:], start=1):
            record["sequence"] = sequence
            if sequence > generation_start:
                record["timestamp_ns"] = max(record["timestamp_ns"], 3100)
        with self.assertRaisesRegex(
            LatencyTraceError, "unknown event.*deadline_missed"
        ):
            evaluate_trace(records)

        records = _records("valid-partial-prefix.jsonl")
        present_start = next(
            index
            for index, record in enumerate(records)
            if record.get("event") == "present_call_started"
            and record["data"]["output_kind"] == "generated"
        )
        del records[present_start : present_start + 2]
        miss = {
            "record": "event",
            "sequence": 0,
            "timestamp_ns": 2001,
            "context_id": "ctx",
            "epoch": 0,
            "event": "deadline_missed",
            "data": {
                "batch_id": "batch-1",
                "generated_frame_id": "gen-1",
                "deadline_ns": 2000,
            },
        }
        records.insert(present_start, miss)
        _event(records, "context_destroyed")["data"]["closure_policy"] = (
            "allow_idle_abandonment"
        )
        for record_index, record in enumerate(records[1:], start=1):
            sequence = record_index
            record["sequence"] = sequence
            if record_index >= present_start:
                record["timestamp_ns"] = max(record["timestamp_ns"], 2001)
        with self.assertRaisesRegex(
            LatencyTraceError, "unknown event.*deadline_missed"
        ):
            evaluate_trace(records)

    def test_full_admission_needs_no_skip_but_partial_requires_one(self):
        records = _records("valid-partial-prefix.jsonl")
        records.remove(_event(records, "generated_batch_skipped"))
        _renumber(records)
        with self.assertRaisesRegex(LatencyTraceError, "skipped suffix"):
            evaluate_trace(records)

        records = _records("valid-partial-prefix.jsonl")
        admission = _event(records, "generated_batch_admitted")
        admission["data"]["admitted_count"] = 3
        records.remove(_event(records, "generated_batch_skipped"))
        _renumber(records)
        with self.assertRaisesRegex(LatencyTraceError, "admitted slot"):
            evaluate_trace(records)

    def test_acquire_is_exactly_once_even_after_success_or_suboptimal(self):
        for first_result in ("success", "suboptimal"):
            with self.subTest(first_result=first_result):
                records = _records("valid-partial-prefix.jsonl")
                first_finish = _event(records, "acquire_finished")
                first_finish["data"]["result"] = first_result
                present_index = next(
                    index
                    for index, record in enumerate(records)
                    if record.get("event") == "present_call_started"
                    and record["data"]["output_kind"] == "generated"
                )
                duplicate = [
                    {
                        "record": "event",
                        "sequence": 0,
                        "timestamp_ns": 1550,
                        "context_id": "ctx",
                        "epoch": 0,
                        "event": "acquire_started",
                        "data": {"output_frame_id": "gen-1"},
                    },
                    {
                        "record": "event",
                        "sequence": 0,
                        "timestamp_ns": 1560,
                        "context_id": "ctx",
                        "epoch": 0,
                        "event": "acquire_finished",
                        "data": {"output_frame_id": "gen-1", "result": "success"},
                    },
                ]
                records[present_index:present_index] = duplicate
                for sequence, record in enumerate(records[1:], start=1):
                    record["sequence"] = sequence
                with self.assertRaisesRegex(LatencyTraceError, "acquire.*once"):
                    evaluate_trace(records)

    def test_unmatched_lifecycle_and_truncation_fail_closed(self):
        records = _records()
        records.pop()
        with self.assertRaisesRegex(LatencyTraceError, "end"):
            evaluate_trace(records)

        records = _records()
        records.pop(-3)
        _renumber(records)
        with self.assertRaisesRegex(LatencyTraceError, "present"):
            evaluate_trace(records)

    def test_non_normal_destroy_counts_idle_abandonment(self):
        records = _records()
        records[5]["data"]["output_frame_id"] = "unknown"
        with self.assertRaises(LatencyTraceError):
            evaluate_trace(records)

        records = _records()
        del records[5:7]
        records[5]["sequence"] = 5
        records[5]["timestamp_ns"] = 700
        records[5]["data"]["closure_policy"] = "allow_idle_abandonment"
        records[6]["sequence"] = 6
        records[6]["timestamp_ns"] = 700
        result = evaluate_trace(records)
        self.assertEqual(result["summary"]["abandoned_frame_count"], 1)

    def test_context_epochs_allow_id_reuse_after_destruction(self):
        records = _records()
        end = records.pop()
        records.extend(
            [
                {
                    "record": "event",
                    "sequence": 8,
                    "timestamp_ns": 800,
                    "context_id": "ctx",
                    "epoch": 1,
                    "event": "context_created",
                    "data": {"present_mode": "fifo", "refresh_interval_ns": 16666667},
                },
                {
                    "record": "event",
                    "sequence": 9,
                    "timestamp_ns": 800,
                    "context_id": "ctx",
                    "epoch": 1,
                    "event": "real_frame_ready",
                    "data": {"real_frame_id": "real-0", "real_index": 0},
                },
                {
                    "record": "event",
                    "sequence": 10,
                    "timestamp_ns": 800,
                    "context_id": "ctx",
                    "epoch": 1,
                    "event": "context_destroyed",
                    "data": {"closure_policy": "allow_idle_abandonment"},
                },
            ]
        )
        end.update(sequence=11, timestamp_ns=800)
        records.append(end)
        result = evaluate_trace(records)
        self.assertEqual(result["summary"]["context_epoch_count"], 2)
        self.assertEqual(result["summary"]["abandoned_frame_count"], 1)

    def test_distinct_contexts_can_interleave(self):
        records = _records()
        end = records.pop()
        second_context_events = [
            {
                "record": "event",
                "sequence": 0,
                "timestamp_ns": 50,
                "context_id": "ctx-b",
                "epoch": 0,
                "event": "context_created",
                "data": {"present_mode": "fifo", "refresh_interval_ns": 16666667},
            },
            {
                "record": "event",
                "sequence": 0,
                "timestamp_ns": 600,
                "context_id": "ctx-b",
                "epoch": 0,
                "event": "real_frame_ready",
                "data": {"real_frame_id": "real-b", "real_index": 0},
            },
            {
                "record": "event",
                "sequence": 0,
                "timestamp_ns": 775,
                "context_id": "ctx-b",
                "epoch": 0,
                "event": "context_destroyed",
                "data": {"closure_policy": "allow_idle_abandonment"},
            },
        ]
        records.extend(second_context_events)
        records[1:] = sorted(records[1:], key=lambda record: record["timestamp_ns"])
        records.append(end)
        for sequence, record in enumerate(records[1:], start=1):
            record["sequence"] = sequence

        result = evaluate_trace(records)
        self.assertEqual(result["summary"]["context_epoch_count"], 2)
        self.assertEqual(result["summary"]["abandoned_frame_count"], 1)

    def test_same_context_next_epoch_requires_previous_epoch_destroyed(self):
        records = _records()
        create = {
            "record": "event",
            "sequence": 7,
            "timestamp_ns": 760,
            "context_id": "ctx",
            "epoch": 1,
            "event": "context_created",
            "data": {"present_mode": "fifo", "refresh_interval_ns": 16666667},
        }
        records.insert(-2, create)
        records[-2]["sequence"] = 8
        records[-1]["sequence"] = 9
        with self.assertRaisesRegex(LatencyTraceError, "previous epoch"):
            evaluate_trace(records)

    def test_plan_cannot_be_created_after_right_real_present_started(self):
        source = _records("valid-partial-prefix.jsonl")
        selected = [
            source[0],
            *source[1:6],
            source[18],
            source[19],
            source[6],
            source[7],
            source[10],
            source[11],
            source[20],
            source[21],
        ]
        selected[8]["data"]["planned_count"] = 1
        selected[9]["data"]["slot_count"] = 1
        selected[10]["data"]["admitted_count"] = 0
        selected[11]["data"]["first_skipped_slot"] = 1
        for sequence, record in enumerate(selected[1:], start=1):
            record["sequence"] = sequence
            record["timestamp_ns"] = sequence * 100
        with self.assertRaisesRegex(LatencyTraceError, "right real frame"):
            evaluate_trace(selected)

    def test_adjacent_real_pair_accepts_only_one_generated_frame_plan(self):
        records = _records("valid-partial-prefix.jsonl")
        original = _event(records, "frame_plan_created")
        duplicate = deepcopy(original)
        duplicate["sequence"] = 0
        duplicate["data"]["batch_id"] = "batch-duplicate"
        records.insert(records.index(original) + 1, duplicate)
        _renumber(records)

        with self.assertRaisesRegex(
            LatencyTraceError,
            "real-frame pair may have only one",
        ):
            evaluate_trace(records)

    def test_plan_metadata_must_finish_before_right_real_present_starts(self):
        for stop_event in ("frame_plan_created", "generated_batch_admitted"):
            with self.subTest(stop_event=stop_event):
                records = _records("valid-partial-prefix.jsonl")
                real_start = next(
                    record
                    for record in records
                    if record.get("event") == "present_call_started"
                    and record["data"]["output_frame_id"] == "real-1"
                )
                real_return = next(
                    record
                    for record in records
                    if record.get("event") == "present_call_returned"
                    and record["data"]["output_frame_id"] == "real-1"
                )
                records.remove(real_start)
                records.remove(real_return)
                insertion = records.index(_event(records, stop_event)) + 1
                records[insertion:insertion] = [real_start, real_return]
                for sequence, record in enumerate(records[1:], start=1):
                    record["sequence"] = sequence
                    record["timestamp_ns"] = sequence * 100
                with self.assertRaisesRegex(LatencyTraceError, "metadata.*complete"):
                    evaluate_trace(records)

    def test_nearest_rank_percentiles_are_stable(self):
        records = _records()
        # Create four more independent contexts with ready->present samples 1..4 ns.
        end = records.pop()
        sequence = records[-1]["sequence"]
        timestamp = records[-1]["timestamp_ns"]
        for index, latency in enumerate((1, 2, 3, 4), start=1):
            context_id = f"extra-{index}"
            for event, data, increment in (
                (
                    "context_created",
                    {"present_mode": "fifo", "refresh_interval_ns": 16666667},
                    0,
                ),
                ("real_frame_ready", {"real_frame_id": "real", "real_index": 0}, 1),
                (
                    "present_call_started",
                    {
                        "output_kind": "real",
                        "output_frame_id": "real",
                        "queue_depth": 0,
                        "content_order": {
                            "right_real_index": 0,
                            "numerator": 1,
                            "denominator": 1,
                        },
                    },
                    latency + 1,
                ),
                (
                    "present_call_returned",
                    {"output_frame_id": "real", "result": "success"},
                    latency + 2,
                ),
                ("context_destroyed", {"closure_policy": "strict"}, latency + 3),
            ):
                sequence += 1
                records.append(
                    {
                        "record": "event",
                        "sequence": sequence,
                        "timestamp_ns": timestamp + increment,
                        "context_id": context_id,
                        "epoch": 0,
                        "event": event,
                        "data": data,
                    }
                )
            timestamp += latency + 3
        end.update(sequence=sequence + 1, timestamp_ns=timestamp)
        records.append(end)
        distribution = evaluate_trace(records)["summary"][
            "real_ready_to_present_call_proxy_ns"
        ]
        self.assertEqual(distribution["sample_count"], 5)
        self.assertEqual(distribution["p50"], 3)
        self.assertEqual(distribution["p95"], 200)
        self.assertEqual(distribution["p99"], 200)

    def test_bounded_loader_rejects_large_lines_files_and_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nonfinite = root / "nonfinite.jsonl"
            nonfinite.write_text('{"record":"header","schema":NaN}\n', encoding="utf-8")
            with self.assertRaisesRegex(LatencyTraceError, "constant"):
                load_trace(nonfinite)

            oversized = root / "oversized.jsonl"
            oversized.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
            with self.assertRaisesRegex(LatencyTraceError, "size"):
                load_trace(oversized)

            deeply_nested = root / "deep.jsonl"
            deeply_nested.write_text(
                '{"record":"header","nested":' + "[" * 1100 + "0" + "]" * 1100 + "}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(LatencyTraceError, "nesting"):
                load_trace(deeply_nested)

            huge_integer = root / "huge-integer.jsonl"
            huge_integer.write_text(
                '{"record":"header","schema":' + "9" * 5000 + "}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(LatencyTraceError, "integer"):
                load_trace(huge_integer)
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                code = main([str(huge_integer)])
            self.assertEqual(code, EXIT_INVALID_TRACE)
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_loader_rejects_fifo_without_waiting_for_a_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / "trace.fifo"
            os.mkfifo(fifo)
            command = [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    "from scripts.latency_trace_gate import "
                    "LatencyTraceError, load_trace; "
                    f"path = Path({str(fifo)!r}); "
                    "\ntry: load_trace(path)\n"
                    "except LatencyTraceError as exc: "
                    "print(exc); raise SystemExit(0)\n"
                    "raise SystemExit(1)"
                ),
            ]

            try:
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=4,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                self.fail("load_trace blocked while opening a FIFO")

        self.assertEqual(completed.returncode, 0)
        self.assertRegex(completed.stdout, "regular file")

    def test_loader_rejects_special_files_as_non_regular(self):
        with self.assertRaisesRegex(LatencyTraceError, "regular file"):
            load_trace(Path(os.devnull))

    def test_loader_rejects_record_amplification_before_json_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "amplified.jsonl"
            path.write_text("{}\n" * (MAX_EVENT_COUNT + 3), encoding="utf-8")

            with mock.patch(
                "scripts.latency_trace_gate.json.loads",
                side_effect=AssertionError("JSON objects must not be expanded"),
            ):
                with self.assertRaisesRegex(LatencyTraceError, "record count"):
                    load_trace(path)

    def test_loader_rejects_same_size_rewrite_detected_by_file_times(self):
        source = FIXTURES / "valid-real-only.jsonl"
        old = source.read_bytes()
        new = old.replace(
            b'"trace_id":"real-only"',
            b'"trace_id":"new-trace"',
            1,
        ).replace(
            b'"timestamp_ns":800,"status":"complete"',
            b'"timestamp_ns":801,"status":"complete"',
            1,
        )
        self.assertEqual(len(old), len(new))
        first_change = old.index(b'"trace_id":"real-only"')
        second_change = old.index(b'"timestamp_ns":800,"status":"complete"')
        split = (first_change + second_change) // 2
        hybrid = old[:split] + new[split:]
        self.assertNotEqual(hybrid, old)
        self.assertNotEqual(hybrid, new)
        self.assertTrue(
            evaluate_trace([json.loads(line) for line in hybrid.splitlines()])["valid"]
        )

        source_stat = source.stat()
        before = mock.Mock(
            st_mode=source_stat.st_mode,
            st_size=len(old),
            st_dev=source_stat.st_dev,
            st_ino=source_stat.st_ino,
            st_mtime_ns=100,
            st_ctime_ns=200,
        )
        after = mock.Mock(
            st_mode=source_stat.st_mode,
            st_size=len(old),
            st_dev=source_stat.st_dev,
            st_ino=source_stat.st_ino,
            st_mtime_ns=101,
            st_ctime_ns=201,
        )
        with (
            mock.patch("scripts.latency_trace_gate.os.open", return_value=17),
            mock.patch(
                "scripts.latency_trace_gate.os.fstat", side_effect=[before, after]
            ),
            mock.patch(
                "scripts.latency_trace_gate.os.read",
                side_effect=[old[:split], new[split:], b""],
            ),
            mock.patch("scripts.latency_trace_gate.os.close"),
        ):
            with self.assertRaisesRegex(LatencyTraceError, "changed while reading"):
                load_trace(source)

    def test_record_bound_is_checked_without_materializing_all_split_lines(self):
        class SplitlinesBomb(bytes):
            def splitlines(self, *args, **kwargs):
                raise AssertionError("unbounded bytes.splitlines was called")

        splitter = getattr(latency_trace_gate, "_split_bounded_lines", None)
        self.assertIsNotNone(
            splitter,
            "load_trace needs a bounded line scanner before JSON expansion",
        )
        payload = SplitlinesBomb(b"{}\n" * (MAX_EVENT_COUNT + 3))

        with self.assertRaisesRegex(LatencyTraceError, "record count"):
            splitter(payload)

    def test_duplicate_json_keys_are_rejected_before_exact_field_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = (FIXTURES / "valid-real-only.jsonl").read_text(encoding="utf-8")
            cases = {
                "header": original.replace('"schema":1', '"schema":999,"schema":1', 1),
                "event-data": original.replace(
                    '"present_mode":"fifo"',
                    '"present_mode":"mailbox","present_mode":"fifo"',
                    1,
                ),
            }
            for name, payload in cases.items():
                with self.subTest(name=name):
                    path = root / f"{name}.jsonl"
                    path.write_text(payload, encoding="utf-8")
                    with self.assertRaisesRegex(LatencyTraceError, "duplicate"):
                        load_trace(path)

    def test_result_retains_canonical_producer(self):
        records = _records("valid-runtime-failure.jsonl")
        result = evaluate_trace(records)
        self.assertIn("producer", result)
        self.assertEqual(result["producer"], records[0]["producer"])

    def test_result_retains_header_provenance(self):
        records = _records("valid-runtime-failure.jsonl")
        result = evaluate_trace(records)
        self.assertEqual(result["subject"], records[0]["subject"])
        self.assertEqual(result["clock"], records[0]["clock"])
        self.assertEqual(result["capabilities"], records[0]["capabilities"])
        self.assertEqual(result["workload_id"], records[0]["workload_id"])

    def test_event_limit_is_enforced(self):
        records = _records()
        records[1:-1] = [deepcopy(records[1]) for _ in range(MAX_EVENT_COUNT + 1)]
        for sequence, record in enumerate(records[1:], start=1):
            record["sequence"] = sequence
        with self.assertRaisesRegex(LatencyTraceError, "event count"):
            evaluate_trace(records)

    def test_complete_end_requires_explicit_zero_lost_event_count(self):
        records = _records()
        records[-1].pop("lost_event_count")

        with self.assertRaisesRegex(LatencyTraceError, "lost_event_count"):
            evaluate_trace(records)

    def test_zero_lost_event_count_is_valid(self):
        records = _records()
        records[-1]["lost_event_count"] = 0

        try:
            result = evaluate_trace(records)
        except LatencyTraceError as exc:
            self.fail(f"zero lost_event_count was rejected: {exc}")
        self.assertTrue(result["valid"])

    def test_nonzero_lost_event_count_is_rejected(self):
        records = _records()
        records[-1]["lost_event_count"] = 1

        with self.assertRaisesRegex(LatencyTraceError, "lost_event_count must be zero"):
            evaluate_trace(records)

    def test_cli_has_stable_invalid_exit_and_no_trusted_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                code = main(
                    [
                        str(FIXTURES / "valid-real-only.jsonl"),
                        "--json-output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(output.read_text())["valid"])

            malformed = Path(directory) / "bad.jsonl"
            malformed.write_text("{}\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main([str(malformed), "--json-output", str(output)])
            self.assertEqual(code, EXIT_INVALID_TRACE)
            rejected = json.loads(output.read_text())
            self.assertFalse(rejected["valid"])
            self.assertNotIn("summary", rejected)

    def test_all_simulator_scenarios_are_deterministic_and_conformant(self):
        simulator = ROOT / "scripts" / "latency_trace_simulator.py"
        for scenario in (
            "normal",
            "continuous",
            "prefix-skip",
            "deadline-miss",
            "recovery",
        ):
            with self.subTest(scenario=scenario):
                command = [sys.executable, str(simulator), "--scenario", scenario]
                first = subprocess.run(command, check=True, capture_output=True).stdout
                second = subprocess.run(command, check=True, capture_output=True).stdout
                self.assertEqual(first, second)
                with tempfile.NamedTemporaryFile() as trace:
                    trace.write(first)
                    trace.flush()
                    result = evaluate_trace(load_trace(Path(trace.name)))
                self.assertEqual(result["measurement_scope"], "synthetic_conformance")


class LatencyTraceV1CorrectionContractTests(unittest.TestCase):
    """Regression contract for the minimal, claim-safe v1 correction."""

    @staticmethod
    def _insert_before_destroy(records: list[dict], events: list[dict]) -> None:
        destroy_index = next(
            index
            for index, record in enumerate(records)
            if record.get("event") == "context_destroyed"
        )
        records[destroy_index:destroy_index] = events
        _renumber(records)

    def test_context_destroyed_accepts_only_explicit_closure_policy(self):
        records = _records()
        self.assertTrue(evaluate_trace(records)["valid"])

        legacy = deepcopy(records)
        destroy = _event(legacy, "context_destroyed")
        destroy["data"] = {"reason": "normal"}
        with self.assertRaisesRegex(LatencyTraceError, "closure_policy|fields"):
            evaluate_trace(legacy)

    def test_allow_idle_abandonment_counts_only_idle_lifecycles(self):
        records = _records()
        del records[5:7]
        destroy = _event(records, "context_destroyed")
        destroy["data"]["closure_policy"] = "allow_idle_abandonment"
        destroy["timestamp_ns"] = 700
        records[-1]["timestamp_ns"] = 700
        _renumber(records)

        summary = evaluate_trace(records)["summary"]
        self.assertEqual(summary["abandoned_frame_count"], 1)
        self.assertEqual(summary["abandoned_batch_count"], 0)

    def test_strict_closure_rejects_an_idle_open_frame(self):
        records = _records()
        del records[5:7]
        _event(records, "context_destroyed")["timestamp_ns"] = 700
        records[-1]["timestamp_ns"] = 700
        _renumber(records)

        with self.assertRaisesRegex(LatencyTraceError, "strict|lifecycles closed"):
            evaluate_trace(records)

    def test_generated_batch_skipped_has_no_producer_asserted_reason(self):
        records = _records("valid-partial-prefix.jsonl")
        self.assertTrue(evaluate_trace(records)["valid"])

        legacy = deepcopy(records)
        _event(legacy, "generated_batch_skipped")["data"]["reason"] = "deadline_risk"
        with self.assertRaisesRegex(LatencyTraceError, "fields"):
            evaluate_trace(legacy)

    def test_recovery_started_has_no_producer_asserted_reason(self):
        records = _records("valid-runtime-failure.jsonl")
        self.assertTrue(evaluate_trace(records)["valid"])

        legacy = deepcopy(records)
        _event(legacy, "recovery_started")["data"]["reason"] = "swapchain"
        with self.assertRaisesRegex(LatencyTraceError, "fields"):
            evaluate_trace(legacy)

    def test_only_one_recovery_may_be_active_per_context_epoch(self):
        records = _records()
        self._insert_before_destroy(
            records,
            [
                {
                    "record": "event",
                    "sequence": 0,
                    "timestamp_ns": 760,
                    "context_id": "ctx",
                    "epoch": 0,
                    "event": "recovery_started",
                    "data": {"recovery_id": "recovery-a"},
                },
                {
                    "record": "event",
                    "sequence": 0,
                    "timestamp_ns": 770,
                    "context_id": "ctx",
                    "epoch": 0,
                    "event": "recovery_started",
                    "data": {"recovery_id": "recovery-b"},
                },
            ],
        )
        _event(records, "context_destroyed")["timestamp_ns"] = 780
        records[-1]["timestamp_ns"] = 780

        with self.assertRaisesRegex(LatencyTraceError, "active recovery"):
            evaluate_trace(records)

    def test_failed_recovery_is_nonterminal_and_fresh_id_retry_is_valid(self):
        records = _records()
        self._insert_before_destroy(
            records,
            [
                {
                    "record": "event",
                    "sequence": 0,
                    "timestamp_ns": 760,
                    "context_id": "ctx",
                    "epoch": 0,
                    "event": "recovery_started",
                    "data": {"recovery_id": "recovery-a"},
                },
                {
                    "record": "event",
                    "sequence": 0,
                    "timestamp_ns": 770,
                    "context_id": "ctx",
                    "epoch": 0,
                    "event": "recovery_finished",
                    "data": {"recovery_id": "recovery-a", "result": "failed"},
                },
                {
                    "record": "event",
                    "sequence": 0,
                    "timestamp_ns": 780,
                    "context_id": "ctx",
                    "epoch": 0,
                    "event": "recovery_started",
                    "data": {"recovery_id": "recovery-b"},
                },
                {
                    "record": "event",
                    "sequence": 0,
                    "timestamp_ns": 790,
                    "context_id": "ctx",
                    "epoch": 0,
                    "event": "recovery_finished",
                    "data": {"recovery_id": "recovery-b", "result": "recovered"},
                },
            ],
        )
        _event(records, "context_destroyed")["timestamp_ns"] = 800
        records[-1]["timestamp_ns"] = 800

        summary = evaluate_trace(records)["summary"]
        self.assertEqual(summary["recovery_attempt_count"], 2)
        self.assertEqual(summary["recovery_failed_count"], 1)

    def test_recovery_id_cannot_be_reused_after_finish(self):
        records = _records()
        events = []
        for timestamp, event in (
            (760, "recovery_started"),
            (770, "recovery_finished"),
            (780, "recovery_started"),
        ):
            data = {"recovery_id": "same-id"}
            if event == "recovery_finished":
                data["result"] = "failed"
            events.append(
                {
                    "record": "event",
                    "sequence": 0,
                    "timestamp_ns": timestamp,
                    "context_id": "ctx",
                    "epoch": 0,
                    "event": event,
                    "data": data,
                }
            )
        self._insert_before_destroy(records, events)
        _event(records, "context_destroyed")["timestamp_ns"] = 790
        records[-1]["timestamp_ns"] = 790

        with self.assertRaisesRegex(LatencyTraceError, "recovery_id.*unique"):
            evaluate_trace(records)

    def test_destroy_while_recovery_is_active_is_invalid(self):
        records = _records()
        self._insert_before_destroy(
            records,
            [
                {
                    "record": "event",
                    "sequence": 0,
                    "timestamp_ns": 760,
                    "context_id": "ctx",
                    "epoch": 0,
                    "event": "recovery_started",
                    "data": {"recovery_id": "active"},
                }
            ],
        )
        _event(records, "context_destroyed")["timestamp_ns"] = 770
        records[-1]["timestamp_ns"] = 770
        with self.assertRaisesRegex(
            LatencyTraceError, "active recovery|recovery.*lacking"
        ):
            evaluate_trace(records)

    def test_recovery_finish_requires_the_matching_active_id(self):
        records = _records()
        self._insert_before_destroy(
            records,
            [
                {
                    "record": "event",
                    "sequence": 0,
                    "timestamp_ns": 760,
                    "context_id": "ctx",
                    "epoch": 0,
                    "event": "recovery_finished",
                    "data": {"recovery_id": "never-started", "result": "failed"},
                }
            ],
        )
        _event(records, "context_destroyed")["timestamp_ns"] = 770
        records[-1]["timestamp_ns"] = 770
        with self.assertRaisesRegex(LatencyTraceError, "matching.*recovery_started"):
            evaluate_trace(records)

    def test_late_generated_present_is_derived_without_deadline_event(self):
        records = _records("valid-partial-prefix.jsonl")
        start = next(
            record
            for record in records
            if record.get("event") == "present_call_started"
            and record["data"]["output_kind"] == "generated"
        )
        start["timestamp_ns"] = 2001
        start_index = records.index(start)
        for record in records[start_index + 1 :]:
            record["timestamp_ns"] = max(record["timestamp_ns"], 2001)

        summary = evaluate_trace(records)["summary"]
        self.assertEqual(summary["late_generated_present_call_count"], 1)
        self.assertNotIn("missed_generated_frame_count", summary)

    def test_legacy_deadline_missed_event_is_rejected(self):
        records = _records("valid-partial-prefix.jsonl")
        present_index = next(
            i
            for i, record in enumerate(records)
            if record.get("event") == "present_call_started"
            and record["data"]["output_kind"] == "generated"
        )
        records[present_index]["timestamp_ns"] = 2001
        records.insert(
            present_index,
            {
                "record": "event",
                "sequence": 0,
                "timestamp_ns": 2001,
                "context_id": "ctx",
                "epoch": 0,
                "event": "deadline_missed",
                "data": {
                    "batch_id": "batch-1",
                    "generated_frame_id": "gen-1",
                    "deadline_ns": 2000,
                },
            },
        )
        for record in records[present_index + 2 :]:
            record["timestamp_ns"] = max(record["timestamp_ns"], 2001)
        _renumber(records)
        with self.assertRaisesRegex(
            LatencyTraceError, "unknown event.*deadline_missed"
        ):
            evaluate_trace(records)

    def test_failed_acquire_is_valid_without_present_or_abandonment(self):
        for result in ("timeout", "out_of_date", "error"):
            with self.subTest(result=result):
                records = _records("valid-partial-prefix.jsonl")
                finish = _event(records, "acquire_finished")
                finish["data"]["result"] = result
                start_index = next(
                    i
                    for i, record in enumerate(records)
                    if record.get("event") == "present_call_started"
                    and record["data"]["output_kind"] == "generated"
                )
                del records[start_index : start_index + 2]
                _renumber(records)

                summary = evaluate_trace(records)["summary"]
                self.assertEqual(summary["acquire_results"][result], 1)
                self.assertEqual(summary["abandoned_frame_count"], 0)
                self.assertEqual(summary["late_generated_present_call_count"], 0)

    def test_idle_acquired_frame_abandonment_is_not_a_late_present(self):
        records = _records("valid-partial-prefix.jsonl")
        start_index = next(
            i
            for i, record in enumerate(records)
            if record.get("event") == "present_call_started"
            and record["data"]["output_kind"] == "generated"
        )
        del records[start_index : start_index + 2]
        destroy = _event(records, "context_destroyed")
        destroy["data"]["closure_policy"] = "allow_idle_abandonment"
        _renumber(records)

        summary = evaluate_trace(records)["summary"]
        self.assertEqual(summary["late_generated_present_call_count"], 0)
        self.assertEqual(summary["abandoned_frame_count"], 1)

    def test_context_profile_is_homogeneous_and_retained(self):
        records = _records()
        end = records.pop()
        records.extend(
            [
                {
                    "record": "event",
                    "sequence": 0,
                    "timestamp_ns": 800,
                    "context_id": "ctx-b",
                    "epoch": 0,
                    "event": "context_created",
                    "data": {"present_mode": "fifo", "refresh_interval_ns": 16666667},
                },
                {
                    "record": "event",
                    "sequence": 0,
                    "timestamp_ns": 800,
                    "context_id": "ctx-b",
                    "epoch": 0,
                    "event": "context_destroyed",
                    "data": {"closure_policy": "strict"},
                },
            ]
        )
        records.append(end)
        _renumber(records)
        result = evaluate_trace(records)
        self.assertEqual(
            result["context_profile"],
            {
                "present_mode": "fifo",
                "refresh_interval_ns": 16666667,
            },
        )

        different = deepcopy(records)
        different[-3]["data"]["present_mode"] = "mailbox"
        with self.assertRaisesRegex(LatencyTraceError, "context_profile|homogeneous"):
            evaluate_trace(different)

    def test_subject_hashes_are_self_declared_and_retained_not_verified(self):
        records = _records()
        records[0]["subject"] = {
            "plugin_git_sha": "1" * 40,
            "engine_source_commit": "2" * 40,
            "engine_sha256": "sha256:" + "3" * 64,
            "config_sha256": "sha256:" + "4" * 64,
        }
        self.assertEqual(evaluate_trace(records)["subject"], records[0]["subject"])

    def test_valid_summary_omits_impossible_missing_feedback_counter(self):
        summary = evaluate_trace(_records())["summary"]
        self.assertNotIn("missing_feedback_count", summary)

    def test_canonical_result_has_exact_top_level_keys(self):
        result = evaluate_trace(_records())

        self.assertEqual(
            set(result),
            {
                "valid",
                "schema",
                "trace_id",
                "producer",
                "measurement_scope",
                "clock",
                "subject",
                "capabilities",
                "workload_id",
                "context_profile",
                "summary",
            },
        )

    def test_canonical_summary_has_exact_keys(self):
        summary = evaluate_trace(_records())["summary"]

        self.assertEqual(
            set(summary),
            {
                "batch_count",
                "planned_generated_frame_count",
                "admitted_generated_frame_count",
                "skipped_generated_frame_count",
                "late_generated_present_call_count",
                "maximum_queue_depth",
                "acquire_results",
                "present_results",
                "expected_feedback_count",
                "received_feedback_count",
                "presented_feedback_count",
                "dropped_feedback_count",
                "unknown_feedback_count",
                "recovery_attempt_count",
                "recovery_failed_count",
                "abandoned_frame_count",
                "abandoned_batch_count",
                "context_epoch_count",
                "context_id_count",
                "real_ready_to_present_call_proxy_ns",
                "input_observed_to_present_call_entry_proxy_ns",
                "host_generation_duration_ns",
                "host_acquire_duration_ns",
                "present_call_to_feedback_proxy_ns",
                "real_present_call_to_feedback_proxy_ns",
                "generated_present_call_to_feedback_proxy_ns",
                "real_ready_to_presentation_feedback_proxy_ns",
                "input_observed_to_real_feedback_proxy_ns",
            },
        )

    def test_canonical_summary_distributions_have_exact_keys(self):
        summary = evaluate_trace(_records())["summary"]
        distribution_names = (
            "real_ready_to_present_call_proxy_ns",
            "input_observed_to_present_call_entry_proxy_ns",
            "host_generation_duration_ns",
            "host_acquire_duration_ns",
            "present_call_to_feedback_proxy_ns",
            "real_present_call_to_feedback_proxy_ns",
            "generated_present_call_to_feedback_proxy_ns",
            "real_ready_to_presentation_feedback_proxy_ns",
            "input_observed_to_real_feedback_proxy_ns",
        )

        for name in distribution_names:
            with self.subTest(distribution=name):
                self.assertEqual(
                    set(summary[name]),
                    {"sample_count", "p50", "p95", "p99", "unavailable_reason"},
                )

    def test_canonical_summary_result_buckets_have_exact_keys(self):
        summary = evaluate_trace(_records())["summary"]
        expected = {"success", "suboptimal", "timeout", "out_of_date", "error"}

        self.assertEqual(set(summary["acquire_results"]), expected)
        self.assertEqual(set(summary["present_results"]), expected)

    def test_line_limit_counts_json_bytes_not_lf_or_crlf_terminator(self):
        splitter = latency_trace_gate._split_bounded_lines
        for terminator in (b"\n", b"\r\n"):
            with self.subTest(terminator=terminator):
                self.assertEqual(
                    splitter(b"x" * latency_trace_gate.MAX_LINE_BYTES + terminator),
                    [b"x" * latency_trace_gate.MAX_LINE_BYTES],
                )
                with self.assertRaisesRegex(LatencyTraceError, "line 1 size"):
                    splitter(
                        b"x" * (latency_trace_gate.MAX_LINE_BYTES + 1) + terminator
                    )

    def test_cli_rejects_invalid_utf8_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "invalid-utf8.jsonl"
            trace.write_bytes(b'{"record":"header"}\xff\n')
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                code = main([str(trace)])
        self.assertEqual(code, EXIT_INVALID_TRACE)
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_json_output_replace_failure_keeps_stale_file_untrusted_and_cleans_temp(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "result.json"
            stale = b'{"valid":true,"stale":true}\n'
            output.write_bytes(stale)
            with mock.patch(
                "scripts.latency_trace_gate.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = main(
                        [
                            str(FIXTURES / "valid-real-only.jsonl"),
                            "--json-output",
                            str(output),
                        ]
                    )
            self.assertEqual(code, EXIT_INVALID_TRACE)
            self.assertEqual(output.read_bytes(), stale)
            self.assertEqual([path.name for path in root.iterdir()], ["result.json"])

    def test_json_output_is_fsynced_then_atomically_replaced_from_same_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "result.json"
            real_replace = os.replace
            real_fsync = os.fsync
            operations = []

            def observed_fsync(fd):
                operations.append("fsync")
                return real_fsync(fd)

            def observed_replace(source, destination):
                operations.append("replace")
                return real_replace(source, destination)

            with (
                mock.patch(
                    "scripts.latency_trace_gate.os.replace",
                    side_effect=observed_replace,
                ) as replace,
                mock.patch(
                    "scripts.latency_trace_gate.os.fsync",
                    side_effect=observed_fsync,
                ),
            ):
                latency_trace_gate._write_json({"valid": True}, output)

            self.assertEqual(operations, ["fsync", "replace"])
            replace.assert_called_once()
            temporary, destination = map(Path, replace.call_args.args)
            self.assertEqual(temporary.parent, output.parent)
            self.assertEqual(destination, output)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")), {"valid": True}
            )
            self.assertEqual([path.name for path in root.iterdir()], ["result.json"])

    def test_json_output_fsync_failure_keeps_stale_file_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "result.json"
            stale = b'{"valid":true,"stale":true}\n'
            output.write_bytes(stale)

            with mock.patch(
                "scripts.latency_trace_gate.os.fsync",
                side_effect=OSError("fsync failed"),
            ):
                with self.assertRaisesRegex(OSError, "fsync failed"):
                    latency_trace_gate._write_json({"valid": True}, output)

            self.assertEqual(output.read_bytes(), stale)
            self.assertEqual([path.name for path in root.iterdir()], ["result.json"])

    def test_cli_rejects_input_output_alias_without_modifying_trace(self):
        for payload in (
            (FIXTURES / "valid-real-only.jsonl").read_bytes(),
            b"{}\n",
        ):
            with self.subTest(valid_input=payload != b"{}\n"):
                with tempfile.TemporaryDirectory() as directory:
                    trace = Path(directory) / "trace.jsonl"
                    trace.write_bytes(payload)
                    before = trace.read_bytes()
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        code = main(
                            [str(trace), "--json-output", str(trace.absolute())]
                        )
                    self.assertEqual(code, EXIT_USAGE)
                    self.assertEqual(trace.read_bytes(), before)

    def test_cli_rejects_hardlinked_input_output_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.jsonl"
            output = root / "result.json"
            trace.write_bytes((FIXTURES / "valid-real-only.jsonl").read_bytes())
            os.link(trace, output)
            before = trace.read_bytes()
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main([str(trace), "--json-output", str(output)])
            self.assertEqual(code, EXIT_USAGE)
            self.assertEqual(trace.read_bytes(), before)
            self.assertEqual(output.read_bytes(), before)

    def test_alias_inspection_error_does_not_mask_unreadable_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.jsonl"
            output = root / "result.json"
            trace.write_bytes((FIXTURES / "valid-real-only.jsonl").read_bytes())
            with (
                mock.patch(
                    "scripts.latency_trace_gate.os.path.samefile",
                    side_effect=PermissionError("alias inspection denied"),
                ),
                mock.patch(
                    "scripts.latency_trace_gate.load_trace",
                    side_effect=LatencyTraceError(
                        "cannot read trace: permission denied"
                    ),
                ),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                code = main([str(trace), "--json-output", str(output)])

            self.assertEqual(code, EXIT_INVALID_TRACE)
            rejected = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(rejected["error"], "cannot read trace: permission denied")

    def test_cli_sanitizes_untrusted_terminal_control_characters(self):
        records = _records()
        _event(records, "real_frame_ready")["event"] = "\x1b]0;owned\x07"
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            output = Path(directory) / "result.json"
            trace.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                code = main([str(trace), "--json-output", str(output)])
            rejected = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(code, EXIT_INVALID_TRACE)
        self.assertNotIn("\x1b", stderr.getvalue())
        self.assertNotIn("\x07", stderr.getvalue())
        self.assertNotIn("\x1b", rejected["error"])
        self.assertNotIn("\x07", rejected["error"])
        self.assertLessEqual(
            len(rejected["error"]), latency_trace_gate.MAX_DIAGNOSTIC_CHARS
        )
        self.assertIn("latency trace rejected", stderr.getvalue())

    def test_empty_context_reports_queue_depth_as_unavailable(self):
        records = _records()
        records = [records[0], records[1], records[-2], records[-1]]
        _renumber(records)
        summary = evaluate_trace(records)["summary"]
        self.assertIsNone(summary["maximum_queue_depth"])

    def test_simulator_scenarios_have_exact_semantic_summaries(self):
        expected = {
            "normal": (1, 1, 1, 0, 0, 0, 0, 3, 1),
            "continuous": (2, 2, 2, 0, 0, 0, 0, 5, 2),
            "prefix-skip": (1, 3, 1, 2, 0, 0, 0, 3, 1),
            "deadline-miss": (1, 1, 1, 0, 1, 0, 0, 3, 1),
            "recovery": (0, 0, 0, 0, 0, 1, 0, 1, 0),
        }
        simulator = ROOT / "scripts" / "latency_trace_simulator.py"
        keys = (
            "batch_count",
            "planned_generated_frame_count",
            "admitted_generated_frame_count",
            "skipped_generated_frame_count",
            "late_generated_present_call_count",
            "recovery_attempt_count",
            "recovery_failed_count",
        )
        for scenario, counts in expected.items():
            with self.subTest(scenario=scenario):
                payload = subprocess.run(
                    [sys.executable, str(simulator), "--scenario", scenario],
                    check=True,
                    capture_output=True,
                ).stdout
                with tempfile.NamedTemporaryFile() as trace:
                    trace.write(payload)
                    trace.flush()
                    summary = evaluate_trace(load_trace(Path(trace.name)))["summary"]
                self.assertEqual(tuple(summary[key] for key in keys), counts[:7])
                self.assertEqual(summary["present_results"]["success"], counts[7])
                self.assertEqual(summary["acquire_results"]["success"], counts[8])


if __name__ == "__main__":
    unittest.main()
