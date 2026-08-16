from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.latency_trace_gate import (
    EXIT_INVALID_TRACE,
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
            first["summary"]["input_observed_to_present_call_proxy_ns"]["p95"],
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

    def test_hashes_and_native_deadline_source_are_strict(self):
        bad_hash = _records()
        bad_hash[0]["subject"]["config_sha256"] = "sha256:nope"
        with self.assertRaisesRegex(LatencyTraceError, "config_sha256"):
            evaluate_trace(bad_hash)

        native = _records()
        native[0]["measurement_scope"] = "native_software_proxy"
        native[0]["capabilities"]["deadline_source"] = "synthetic_vblank"
        with self.assertRaisesRegex(LatencyTraceError, "synthetic_vblank"):
            evaluate_trace(native)

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
        (
            records[generated_present]["data"]["content_order"],
            records[real_present]["data"]["content_order"],
        ) = (
            records[real_present]["data"]["content_order"],
            records[generated_present]["data"]["content_order"],
        )
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

    def test_late_present_requires_exact_deadline_miss_event(self):
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
        with self.assertRaisesRegex(LatencyTraceError, "deadline_missed"):
            evaluate_trace(records)

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
        result = evaluate_trace(records)
        self.assertEqual(result["summary"]["missed_generated_frame_count"], 1)

    def test_deadline_miss_requires_admission_and_subsequent_late_present(self):
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
        with self.assertRaisesRegex(LatencyTraceError, "admitted"):
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
        _event(records, "context_destroyed")["data"]["reason"] = "shutdown"
        for record_index, record in enumerate(records[1:], start=1):
            sequence = record_index
            record["sequence"] = sequence
            if record_index >= present_start:
                record["timestamp_ns"] = max(record["timestamp_ns"], 2001)
        with self.assertRaisesRegex(LatencyTraceError, "subsequent late"):
            evaluate_trace(records)

    def test_full_admission_needs_no_skip_but_partial_requires_one(self):
        records = _records("valid-partial-prefix.jsonl")
        records.remove(_event(records, "generated_batch_skipped"))
        with self.assertRaisesRegex(LatencyTraceError, "skipped suffix"):
            evaluate_trace(records)

        records = _records("valid-partial-prefix.jsonl")
        admission = _event(records, "generated_batch_admitted")
        admission["data"]["admitted_count"] = 3
        records.remove(_event(records, "generated_batch_skipped"))
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
        records[5]["data"]["reason"] = "shutdown"
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
                    "data": {"reason": "shutdown"},
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
                "data": {"reason": "shutdown"},
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
                    {"present_mode": "fifo", "refresh_interval_ns": 1},
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
                ("context_destroyed", {"reason": "normal"}, latency + 3),
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

    def test_native_trace_requires_artifact_identity_and_result_retains_provenance(
        self,
    ):
        records = _records("valid-runtime-failure.jsonl")
        records[0]["subject"]["engine_source_commit"] = "unavailable"
        records[0]["subject"]["engine_sha256"] = "unavailable"
        with self.assertRaisesRegex(LatencyTraceError, "engine_sha256"):
            evaluate_trace(records)

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
                self.assertEqual(
                    result["measurement_scope"], "synthetic_software_proxy"
                )


if __name__ == "__main__":
    unittest.main()
