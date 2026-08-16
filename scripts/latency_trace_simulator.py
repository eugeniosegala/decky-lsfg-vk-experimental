#!/usr/bin/env python3
"""Deterministic fake-clock producer for latency trace v1 conformance tests.

The simulator intentionally does not import the gate or share its state machine.
It is a producer example, not LSFG, Gamescope, or hardware evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


class Trace:
    def __init__(self, scenario: str):
        self.scenario = scenario
        self.sequence = 0
        self.now = 0
        self.records: list[dict[str, Any]] = [
            {
                "record": "header",
                "schema": 1,
                "trace_id": f"simulated-{scenario}",
                "producer": "latency_trace_simulator",
                "measurement_scope": "synthetic_software_proxy",
                "clock": {"domain": "synthetic_monotonic", "unit": "ns"},
                "subject": {
                    "plugin_git_sha": "0000000000000000000000000000000000000000",
                    "engine_source_commit": "unavailable",
                    "engine_sha256": "unavailable",
                    "config_sha256": "sha256:" + "0" * 64,
                },
                "capabilities": {
                    "presentation_feedback": False,
                    "feedback_clock_domain": "unavailable",
                    "gpu_duration": False,
                    "deadline_source": "synthetic_vblank",
                },
                "workload_id": f"{scenario}-v1",
            }
        ]

    def event(
        self,
        name: str,
        data: dict[str, Any],
        *,
        step: int = 100,
        context: str = "ctx",
        epoch: int = 0,
    ) -> None:
        self.now += step
        self.sequence += 1
        self.records.append(
            {
                "record": "event",
                "sequence": self.sequence,
                "timestamp_ns": self.now,
                "context_id": context,
                "epoch": epoch,
                "event": name,
                "data": data,
            }
        )

    def end(self) -> None:
        self.sequence += 1
        self.records.append(
            {
                "record": "end",
                "sequence": self.sequence,
                "timestamp_ns": self.now,
                "status": "complete",
            }
        )

    def real_ready(self, index: int) -> None:
        self.event(
            "real_frame_ready", {"real_frame_id": f"real-{index}", "real_index": index}
        )

    def real_present(self, index: int, result: str = "success") -> None:
        frame_id = f"real-{index}"
        self.event(
            "present_call_started",
            {
                "output_kind": "real",
                "output_frame_id": frame_id,
                "queue_depth": 0,
                "content_order": {
                    "right_real_index": index,
                    "numerator": 1,
                    "denominator": 1,
                },
            },
        )
        self.event(
            "present_call_returned", {"output_frame_id": frame_id, "result": result}
        )

    def plan(
        self, batch: int, planned: int, admitted: int, *, miss: bool = False
    ) -> None:
        batch_id = f"batch-{batch}"
        right = batch
        self.event(
            "frame_plan_created",
            {
                "batch_id": batch_id,
                "left_real_frame_id": f"real-{right - 1}",
                "right_real_frame_id": f"real-{right}",
                "planned_count": planned,
            },
        )
        deadlines: dict[int, int] = {}
        for slot in range(1, planned + 1):
            deadline = self.now + 10_000 + slot * 1_000
            deadlines[slot] = deadline
            self.event(
                "generated_slot_planned",
                {
                    "batch_id": batch_id,
                    "generated_frame_id": f"gen-{batch}-{slot}",
                    "slot_index": slot,
                    "slot_count": planned,
                    "deadline_ns": deadline,
                },
            )
        self.event(
            "generated_batch_admitted",
            {"batch_id": batch_id, "admitted_count": admitted},
        )
        if admitted < planned:
            self.event(
                "generated_batch_skipped",
                {
                    "batch_id": batch_id,
                    "first_skipped_slot": admitted + 1,
                    "reason": "deadline_risk",
                },
            )
        for slot in range(1, admitted + 1):
            frame_id = f"gen-{batch}-{slot}"
            self.event(
                "generation_started",
                {"batch_id": batch_id, "generated_frame_id": frame_id},
            )
            self.event(
                "generation_finished",
                {
                    "batch_id": batch_id,
                    "generated_frame_id": frame_id,
                    "gpu_duration_ns": None,
                },
            )
            self.event("acquire_started", {"output_frame_id": frame_id})
            self.event(
                "acquire_finished", {"output_frame_id": frame_id, "result": "success"}
            )
            if miss and slot == admitted:
                self.now = deadlines[slot]
                self.event(
                    "deadline_missed",
                    {
                        "batch_id": batch_id,
                        "generated_frame_id": frame_id,
                        "deadline_ns": deadlines[slot],
                    },
                    step=1,
                )
            self.event(
                "present_call_started",
                {
                    "output_kind": "generated",
                    "output_frame_id": frame_id,
                    "queue_depth": slot,
                    "content_order": {
                        "right_real_index": right,
                        "numerator": slot,
                        "denominator": planned + 1,
                    },
                },
            )
            self.event(
                "present_call_returned",
                {"output_frame_id": frame_id, "result": "success"},
            )


def build(scenario: str) -> list[dict[str, Any]]:
    trace = Trace(scenario)
    trace.event(
        "context_created", {"present_mode": "fifo", "refresh_interval_ns": 11_111_111}
    )
    trace.real_ready(0)
    trace.real_present(0)

    if scenario in {"normal", "continuous", "prefix-skip", "deadline-miss"}:
        trace.real_ready(1)
        if scenario == "prefix-skip":
            trace.plan(1, 3, 1)
        else:
            trace.plan(1, 1, 1, miss=scenario == "deadline-miss")
        trace.real_present(1)

    if scenario == "continuous":
        trace.real_ready(2)
        trace.plan(2, 1, 1)
        trace.real_present(2)

    if scenario == "recovery":
        # Runtime failure is valid evidence; recovery outcome remains visible.
        # The already-presented real frame is retained, and no lifecycle is open.
        trace.event(
            "recovery_started", {"recovery_id": "recovery-0", "reason": "swapchain"}
        )
        trace.event(
            "recovery_finished", {"recovery_id": "recovery-0", "result": "recovered"}
        )

    trace.event("context_destroyed", {"reason": "normal"})
    trace.end()
    return trace.records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit deterministic latency trace v1 JSONL"
    )
    parser.add_argument(
        "--scenario",
        required=True,
        choices=("normal", "continuous", "prefix-skip", "deadline-miss", "recovery"),
    )
    args = parser.parse_args(argv)
    for record in build(args.scenario):
        sys.stdout.write(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
