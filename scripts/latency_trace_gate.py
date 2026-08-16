#!/usr/bin/env python3
"""Strict conformance gate for the latency trace v1 JSONL contract.

This validates causality and produces software-proxy summaries.  It deliberately
does not make performance, visual-quality, or input-to-photon claims.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any


EXIT_OK = 0
EXIT_INVALID_TRACE = 2
EXIT_USAGE = 64
MAX_FILE_BYTES = 1024 * 1024
MAX_LINE_BYTES = 16 * 1024
MAX_EVENT_COUNT = 10_000
MAX_NESTING_DEPTH = 6
MAX_INTEGER_DIGITS = 128

_ID_RE = re.compile(r"^[\x20-\x7e]{1,128}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RESULTS = ("success", "suboptimal", "timeout", "out_of_date", "error")


class LatencyTraceError(ValueError):
    """The supplied trace is not trustworthy evidence."""


def _reject_constant(value: str) -> None:
    raise LatencyTraceError(f"non-finite JSON constant is forbidden: {value}")


def _parse_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > MAX_INTEGER_DIGITS:
        raise LatencyTraceError(
            f"JSON integer exceeds {MAX_INTEGER_DIGITS} decimal digits"
        )
    return int(value)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LatencyTraceError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _exceeds_depth(value: Any, limit: int) -> bool:
    """Bound nesting without recursing on attacker-controlled JSON."""
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > limit:
            return True
        if isinstance(current, dict):
            stack.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)
    return False


def _split_bounded_lines(raw: bytes) -> list[bytes]:
    """Split LF/CRLF JSONL only after proving the physical record bound."""
    record_count = raw.count(b"\n")
    if raw and not raw.endswith(b"\n"):
        record_count += 1
    if record_count > MAX_EVENT_COUNT + 2:
        raise LatencyTraceError("physical record count exceeds limit")

    lines: list[bytes] = []
    start = 0
    number = 1
    while start < len(raw):
        end = raw.find(b"\n", start)
        if end < 0:
            end = len(raw)
        line_end = end - 1 if end > start and raw[end - 1] == 0x0D else end
        if line_end - start > MAX_LINE_BYTES:
            raise LatencyTraceError(
                f"line {number} size exceeds {MAX_LINE_BYTES} bytes"
            )
        lines.append(raw[start:line_end])
        number += 1
        if end == len(raw):
            break
        start = end + 1
    return lines


def load_trace(path: Path) -> list[dict[str, Any]]:
    flags = os.O_RDONLY
    for optional_flag in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= getattr(os, optional_flag, 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise LatencyTraceError(f"cannot read trace: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise LatencyTraceError("trace must be a regular file")
        if before.st_size > MAX_FILE_BYTES:
            raise LatencyTraceError(f"trace size exceeds {MAX_FILE_BYTES} bytes")

        chunks: list[bytes] = []
        remaining = MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_FILE_BYTES:
            raise LatencyTraceError(f"trace size exceeds {MAX_FILE_BYTES} bytes")

        after = os.fstat(fd)
        before_stability = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_stability = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if before_stability != after_stability:
            raise LatencyTraceError("trace metadata changed while reading")
        if len(raw) != after.st_size:
            raise LatencyTraceError(
                "trace size changed or could not be read completely"
            )
    except OSError as exc:
        raise LatencyTraceError(f"cannot read trace: {exc}") from exc
    finally:
        os.close(fd)

    raw_lines = _split_bounded_lines(raw)
    if not raw_lines:
        raise LatencyTraceError("trace is empty")
    records: list[dict[str, Any]] = []
    for number, raw in enumerate(raw_lines, 1):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LatencyTraceError(f"line {number} is not valid UTF-8") from exc
        try:
            value = json.loads(
                text,
                parse_constant=_reject_constant,
                parse_int=_parse_integer,
                object_pairs_hook=_reject_duplicate_pairs,
            )
        except RecursionError as exc:
            raise LatencyTraceError(
                f"line {number} nesting exceeds {MAX_NESTING_DEPTH}"
            ) from exc
        except (json.JSONDecodeError, LatencyTraceError) as exc:
            raise LatencyTraceError(f"line {number} invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise LatencyTraceError(f"line {number} must be a JSON object")
        if _exceeds_depth(value, MAX_NESTING_DEPTH):
            raise LatencyTraceError(
                f"line {number} nesting exceeds {MAX_NESTING_DEPTH}"
            )
        records.append(value)
    return records


def _exact(obj: dict[str, Any], fields: set[str], where: str) -> None:
    if set(obj) != fields:
        raise LatencyTraceError(
            f"{where} fields mismatch: expected {sorted(fields)}, got {sorted(obj)}"
        )


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LatencyTraceError(f"{name} must be an integer, not a boolean")
    if abs(value) > 10**MAX_INTEGER_DIGITS - 1:
        raise LatencyTraceError(
            f"{name} integer exceeds {MAX_INTEGER_DIGITS} decimal digits"
        )
    if value < minimum:
        raise LatencyTraceError(f"{name} must be >= {minimum}")
    return value


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise LatencyTraceError(f"{name} must be 1-128 printable ASCII characters")
    return value


def _one_of(value: Any, allowed: tuple[str, ...] | set[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise LatencyTraceError(f"{name} must be one of {sorted(allowed)}")
    return value


def _nullable_ns(value: Any, name: str) -> int | None:
    return None if value is None else _integer(value, name)


def _distribution(samples: list[int], unavailable_reason: str) -> dict[str, Any]:
    if not samples:
        return {
            "sample_count": 0,
            "p50": None,
            "p95": None,
            "p99": None,
            "unavailable_reason": unavailable_reason,
        }
    ordered = sorted(samples)

    def percentile(p: float) -> int:
        return ordered[math.ceil(p * len(ordered)) - 1]

    return {
        "sample_count": len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "unavailable_reason": None,
    }


def _validate_header(record: dict[str, Any]) -> dict[str, Any]:
    _exact(
        record,
        {
            "record",
            "schema",
            "trace_id",
            "producer",
            "measurement_scope",
            "clock",
            "subject",
            "capabilities",
            "workload_id",
        },
        "header",
    )
    if record["record"] != "header" or _integer(record["schema"], "schema") != 1:
        raise LatencyTraceError("first record must be latency trace header schema 1")
    for field in ("trace_id", "producer", "workload_id"):
        _identifier(record[field], field)
    scope = record["measurement_scope"]
    if scope == "native_software_proxy":
        raise LatencyTraceError(
            "native measurement scope is reserved for a future schema v2"
        )
    _one_of(scope, {"synthetic_conformance"}, "measurement_scope")
    clock = record["clock"]
    if not isinstance(clock, dict):
        raise LatencyTraceError("clock must be an object")
    _exact(clock, {"domain", "unit"}, "clock")
    _identifier(clock["domain"], "clock.domain")
    if clock["unit"] != "ns":
        raise LatencyTraceError("clock.unit must be ns")
    subject = record["subject"]
    if not isinstance(subject, dict):
        raise LatencyTraceError("subject must be an object")
    _exact(
        subject,
        {"plugin_git_sha", "engine_source_commit", "engine_sha256", "config_sha256"},
        "subject",
    )
    if not isinstance(subject["plugin_git_sha"], str) or not _SHA_RE.fullmatch(
        subject["plugin_git_sha"]
    ):
        raise LatencyTraceError("plugin_git_sha must be a lowercase 40-hex SHA")
    engine_commit = subject["engine_source_commit"]
    if engine_commit != "unavailable" and (
        not isinstance(engine_commit, str) or not _SHA_RE.fullmatch(engine_commit)
    ):
        raise LatencyTraceError(
            "engine_source_commit must be unavailable or a lowercase 40-hex SHA"
        )
    engine_hash = subject["engine_sha256"]
    if engine_hash != "unavailable" and (
        not isinstance(engine_hash, str) or not _DIGEST_RE.fullmatch(engine_hash)
    ):
        raise LatencyTraceError(
            "engine_sha256 must be unavailable or sha256:<64 lowercase hex>"
        )
    if not isinstance(subject["config_sha256"], str) or not _DIGEST_RE.fullmatch(
        subject["config_sha256"]
    ):
        raise LatencyTraceError("config_sha256 must be sha256:<64 lowercase hex>")
    caps = record["capabilities"]
    if not isinstance(caps, dict):
        raise LatencyTraceError("capabilities must be an object")
    _exact(
        caps,
        {
            "presentation_feedback",
            "feedback_clock_domain",
            "gpu_duration",
            "deadline_source",
        },
        "capabilities",
    )
    if not isinstance(caps["presentation_feedback"], bool) or not isinstance(
        caps["gpu_duration"], bool
    ):
        raise LatencyTraceError("capability flags must be booleans")
    _one_of(
        caps["deadline_source"],
        {"none", "synthetic_vblank", "display_timing"},
        "deadline_source",
    )
    if caps["presentation_feedback"]:
        if caps["feedback_clock_domain"] != clock["domain"]:
            raise LatencyTraceError(
                "feedback_clock_domain must equal the normalized main clock domain"
            )
    elif caps["feedback_clock_domain"] != "unavailable":
        raise LatencyTraceError(
            "feedback_clock_domain must be unavailable without presentation feedback"
        )
    return record


class _Context:
    def __init__(self, context_id: str, epoch: int):
        self.context_id = context_id
        self.epoch = epoch
        self.created = False
        self.destroyed = False
        self.closure_policy: str | None = None
        self.real: dict[str, dict[str, Any]] = {}
        self.real_indices: dict[int, str] = {}
        self.last_real_index: int | None = None
        self.plans: dict[str, dict[str, Any]] = {}
        self.planned_real_pairs: set[tuple[str, str]] = set()
        self.generated: dict[str, dict[str, Any]] = {}
        self.inputs: dict[str, int] = {}
        self.simulations: dict[str, tuple[str, int]] = {}
        self.operations: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
        self.presented: dict[str, dict[str, Any]] = {}
        self.feedback_ids: set[str] = set()
        self.recovery_ids: set[str] = set()
        self.last_content_order: tuple[int, int, int] | None = None


def _content_order(
    value: Any, output_kind: str, frame: dict[str, Any], name: str
) -> tuple[int, int, int]:
    if not isinstance(value, dict):
        raise LatencyTraceError(f"{name} content_order must be an object")
    _exact(value, {"right_real_index", "numerator", "denominator"}, "content_order")
    right = _integer(value["right_real_index"], "content_order.right_real_index")
    numerator = _integer(value["numerator"], "content_order.numerator", minimum=1)
    denominator = _integer(value["denominator"], "content_order.denominator", minimum=1)
    if output_kind == "real":
        if (right, numerator, denominator) != (frame["real_index"], 1, 1):
            raise LatencyTraceError(
                "real content order must be its real index plus 1/1"
            )
    else:
        slot = frame["slot_index"]
        count = frame["slot_count"]
        if (right, numerator, denominator) != (
            frame["right_real_index"],
            slot,
            count + 1,
        ):
            raise LatencyTraceError(
                "generated content order must match its exact one-based rational slot"
            )
    return right, numerator, denominator


def _order_less(left: tuple[int, int, int], right: tuple[int, int, int]) -> bool:
    if left[0] != right[0]:
        return left[0] < right[0]
    return left[1] * right[2] < right[1] * left[2]


def _validate_strict_closure(ctx: _Context) -> None:
    for plan in ctx.plans.values():
        if plan["planned"] and plan["admitted"] is None:
            raise LatencyTraceError("planned batch lacks admission")
        if plan["admitted"] is None:
            continue
        if plan["admitted"] < plan["planned"] and plan["skip"] is None:
            raise LatencyTraceError("partial admission lacks skipped suffix")
        for slot in range(1, plan["admitted"] + 1):
            frame = ctx.generated[plan["slots"][slot]]
            if not frame["generation_done"]:
                raise LatencyTraceError("admitted slot lacks completed generation")


def _close_completed_batches(ctx: _Context) -> None:
    for plan in ctx.plans.values():
        if plan["planned"] == 0 or plan["admitted"] is None:
            continue
        suffix_complete = (
            plan["admitted"] == plan["planned"] or plan["skip"] is not None
        )
        admitted_frames_closed = all(
            ctx.generated[plan["slots"][slot]]["closed"]
            for slot in range(1, plan["admitted"] + 1)
        )
        if suffix_complete and admitted_frames_closed:
            plan["closed"] = True


class _EventProcessor:
    def __init__(
        self,
        capabilities: dict[str, Any],
        samples: dict[str, list[int]],
        summary: dict[str, Any],
    ):
        self.caps = capabilities
        self.deadline_source = capabilities["deadline_source"]
        self.samples = samples
        self.summary = summary

    def process(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        handlers = {
            "input_observed": self._process_input_observed,
            "simulation_started": self._process_simulation_started,
            "real_frame_ready": self._process_real_frame_ready,
            "frame_plan_created": self._process_frame_plan_created,
            "generated_slot_planned": self._process_generated_slot_planned,
            "generated_batch_admitted": self._process_generated_batch_admitted,
            "generated_batch_skipped": self._process_generated_batch_skipped,
            "generation_started": self._process_generation_started,
            "generation_finished": self._process_generation_finished,
            "acquire_started": self._process_acquire_started,
            "acquire_finished": self._process_acquire_finished,
            "present_call_started": self._process_present_call_started,
            "present_call_returned": self._process_present_call_returned,
            "presentation_feedback": self._process_presentation_feedback,
            "recovery_started": self._process_recovery_started,
            "recovery_finished": self._process_recovery_finished,
        }
        try:
            handler = handlers[event]
        except KeyError as exc:
            raise LatencyTraceError(f"unknown event: {event}") from exc
        handler(ctx, event, data, timestamp)

    def _process_input_observed(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"input_id"}, event)
        input_id = _identifier(data["input_id"], "input_id")
        if input_id in ctx.inputs:
            raise LatencyTraceError("input_id must be unique per epoch")
        ctx.inputs[input_id] = timestamp

    def _process_simulation_started(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"input_id", "real_frame_id"}, event)
        input_id = _identifier(data["input_id"], "input_id")
        frame_id = _identifier(data["real_frame_id"], "real_frame_id")
        if input_id not in ctx.inputs:
            raise LatencyTraceError("simulation_started input_id does not exist")
        if frame_id in ctx.simulations:
            raise LatencyTraceError("real_frame_id has duplicate simulation_started")
        if frame_id in ctx.real or frame_id in ctx.generated:
            raise LatencyTraceError(
                "simulation_started real_frame_id already exists as an output frame"
            )
        if timestamp < ctx.inputs[input_id]:
            raise LatencyTraceError("simulation timestamp precedes input timestamp")
        ctx.simulations[frame_id] = (input_id, timestamp)

    def _process_real_frame_ready(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"real_frame_id", "real_index"}, event)
        frame_id = _identifier(data["real_frame_id"], "real_frame_id")
        index = _integer(data["real_index"], "real_index")
        if (
            frame_id in ctx.real
            or frame_id in ctx.generated
            or index in ctx.real_indices
        ):
            raise LatencyTraceError("real frame id and index must be unique per epoch")
        if ctx.last_real_index is None and index != 0:
            raise LatencyTraceError(
                "first real_index in each context epoch must be zero"
            )
        if ctx.last_real_index is not None and index != ctx.last_real_index + 1:
            raise LatencyTraceError(
                "real_index must be contiguous within each context epoch"
            )
        if frame_id in ctx.simulations and timestamp < ctx.simulations[frame_id][1]:
            raise LatencyTraceError(
                "real frame timestamp precedes simulation timestamp"
            )
        ctx.real[frame_id] = {
            "real_index": index,
            "ready": timestamp,
            "closed": False,
        }
        ctx.real_indices[index] = frame_id
        ctx.last_real_index = index

    def _process_frame_plan_created(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(
            data,
            {
                "batch_id",
                "left_real_frame_id",
                "right_real_frame_id",
                "planned_count",
            },
            event,
        )
        batch_id = _identifier(data["batch_id"], "batch_id")
        left = _identifier(data["left_real_frame_id"], "left_real_frame_id")
        right = _identifier(data["right_real_frame_id"], "right_real_frame_id")
        count = _integer(data["planned_count"], "planned_count")
        if count > 3:
            raise LatencyTraceError("planned_count must be <= 3")
        if batch_id in ctx.plans or left not in ctx.real or right not in ctx.real:
            raise LatencyTraceError(
                "plan batch must be unique and reference existing real frames"
            )
        if right in ctx.presented:
            raise LatencyTraceError(
                "plan cannot be created after the right real frame present started"
            )
        left_index, right_index = (
            ctx.real[left]["real_index"],
            ctx.real[right]["real_index"],
        )
        if right_index != left_index + 1:
            raise LatencyTraceError("plan must reference consecutive real indices")
        pair = (left, right)
        if pair in ctx.planned_real_pairs:
            raise LatencyTraceError(
                "adjacent real-frame pair may have only one generated-frame plan"
            )
        ctx.planned_real_pairs.add(pair)
        ctx.plans[batch_id] = {
            "planned": count,
            "left": left,
            "right": right,
            "right_real_index": right_index,
            "slots": {},
            "admitted": None,
            "skip": None,
            "closed": count == 0,
        }
        self.summary["batch_count"] += 1
        self.summary["planned_generated_frame_count"] += count

    def _process_generated_slot_planned(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(
            data,
            {
                "batch_id",
                "generated_frame_id",
                "slot_index",
                "slot_count",
                "deadline_ns",
            },
            event,
        )
        batch_id = _identifier(data["batch_id"], "batch_id")
        frame_id = _identifier(data["generated_frame_id"], "generated_frame_id")
        slot = _integer(data["slot_index"], "slot_index", minimum=1)
        count = _integer(data["slot_count"], "slot_count", minimum=1)
        deadline = _nullable_ns(data["deadline_ns"], "deadline_ns")
        plan = ctx.plans.get(batch_id)
        if plan is None or plan["admitted"] is not None or plan["planned"] != count:
            raise LatencyTraceError(
                "generated slot must precede admission and match planned_count"
            )
        if slot != len(plan["slots"]) + 1 or slot > count:
            raise LatencyTraceError(
                "generated slots must be contiguous unique one-based slots"
            )
        if (
            frame_id in ctx.generated
            or frame_id in ctx.real
            or frame_id in ctx.simulations
        ):
            raise LatencyTraceError("output frame ids must be unique per epoch")
        if (self.deadline_source == "none") != (deadline is None):
            raise LatencyTraceError("deadline must be null iff deadline_source is none")
        if slot > 1:
            previous_frame_id = plan["slots"][slot - 1]
            previous_deadline = ctx.generated[previous_frame_id]["deadline"]
            if deadline is not None and deadline < previous_deadline:
                raise LatencyTraceError(
                    "generated slot deadlines must be nondecreasing"
                )
        frame = {
            "batch": batch_id,
            "slot_index": slot,
            "slot_count": count,
            "right_real_index": plan["right_real_index"],
            "deadline": deadline,
            "admitted": False,
            "generation_done": False,
            "closed": False,
            "acquire_attempted": False,
        }
        plan["slots"][slot] = frame_id
        ctx.generated[frame_id] = frame

    def _process_generated_batch_admitted(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"batch_id", "admitted_count"}, event)
        batch_id = _identifier(data["batch_id"], "batch_id")
        admitted = _integer(data["admitted_count"], "admitted_count")
        plan = ctx.plans.get(batch_id)
        if (
            plan is None
            or plan["planned"] == 0
            or plan["admitted"] is not None
            or len(plan["slots"]) != plan["planned"]
            or admitted > plan["planned"]
        ):
            raise LatencyTraceError(
                "admission requires all planned slots and a valid admitted prefix"
            )
        for slot in range(1, admitted + 1):
            frame = ctx.generated[plan["slots"][slot]]
            if frame["deadline"] is not None and timestamp > frame["deadline"]:
                raise LatencyTraceError(
                    "generated batch admission occurred after a slot deadline"
                )
            frame["admitted"] = True
        plan["admitted"] = admitted
        self.summary["admitted_generated_frame_count"] += admitted

    def _process_generated_batch_skipped(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"batch_id", "first_skipped_slot"}, event)
        batch_id = _identifier(data["batch_id"], "batch_id")
        first = _integer(data["first_skipped_slot"], "first_skipped_slot", minimum=1)
        plan = ctx.plans.get(batch_id)
        if (
            plan is None
            or plan["admitted"] is None
            or plan["admitted"] >= plan["planned"]
            or plan["skip"] is not None
            or first != plan["admitted"] + 1
        ):
            raise LatencyTraceError(
                "generated_batch_skipped must declare the exact unadmitted skipped suffix"
            )
        plan["skip"] = first
        self.summary["skipped_generated_frame_count"] += (
            plan["planned"] - plan["admitted"]
        )

    def _process_generation_started(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"batch_id", "generated_frame_id"}, event)
        batch_id = _identifier(data["batch_id"], "batch_id")
        frame_id = _identifier(data["generated_frame_id"], "generated_frame_id")
        frame = ctx.generated.get(frame_id)
        if (
            frame is None
            or frame["batch"] != batch_id
            or not frame["admitted"]
            or frame["generation_done"]
        ):
            raise LatencyTraceError(
                "generation_started must reference an admitted unfinished slot"
            )
        op = ("generation", frame_id)
        if op in ctx.operations:
            raise LatencyTraceError("generation already started")
        ctx.operations[op] = (timestamp, data)

    def _process_generation_finished(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"batch_id", "generated_frame_id", "gpu_duration_ns"}, event)
        batch_id = _identifier(data["batch_id"], "batch_id")
        frame_id = _identifier(data["generated_frame_id"], "generated_frame_id")
        gpu = _nullable_ns(data["gpu_duration_ns"], "gpu_duration_ns")
        if self.caps["gpu_duration"] != (gpu is not None):
            raise LatencyTraceError(
                "gpu_duration_ns availability must match capability"
            )
        op = ctx.operations.pop(("generation", frame_id), None)
        frame = ctx.generated.get(frame_id)
        if op is None or frame is None or frame["batch"] != batch_id:
            raise LatencyTraceError(
                "generation_finished lacks matching generation_started"
            )
        if timestamp < op[0]:
            raise LatencyTraceError(
                "generation finish timestamp precedes start timestamp"
            )
        self.samples["generation"].append(timestamp - op[0])
        frame["generation_done"] = True

    def _process_acquire_started(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"output_frame_id"}, event)
        frame_id = _identifier(data["output_frame_id"], "output_frame_id")
        frame = ctx.generated.get(frame_id)
        if frame is None or not frame["generation_done"] or frame["closed"]:
            raise LatencyTraceError(
                "acquire_started requires finished generated output"
            )
        if frame["acquire_attempted"]:
            raise LatencyTraceError(
                "acquire may be attempted exactly once per generated output"
            )
        op = ("acquire", frame_id)
        if op in ctx.operations:
            raise LatencyTraceError("acquire already started")
        frame["acquire_attempted"] = True
        ctx.operations[op] = (timestamp, data)

    def _process_acquire_finished(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"output_frame_id", "result"}, event)
        frame_id = _identifier(data["output_frame_id"], "output_frame_id")
        result = _one_of(data["result"], set(_RESULTS), "acquire result")
        op = ctx.operations.pop(("acquire", frame_id), None)
        frame = ctx.generated.get(frame_id)
        if op is None or frame is None:
            raise LatencyTraceError("acquire_finished lacks matching acquire_started")
        if timestamp < op[0]:
            raise LatencyTraceError("acquire finish timestamp precedes start timestamp")
        self.samples["acquire"].append(timestamp - op[0])
        self.summary["acquire_results"][result] += 1
        if result in {"timeout", "out_of_date", "error"}:
            frame["closed"] = True
        else:
            frame["acquired"] = True

    def _process_present_call_started(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(
            data,
            {"output_kind", "output_frame_id", "queue_depth", "content_order"},
            event,
        )
        output_kind = _one_of(data["output_kind"], {"real", "generated"}, "output_kind")
        frame_id = _identifier(data["output_frame_id"], "output_frame_id")
        queue_depth = _integer(data["queue_depth"], "queue_depth")
        self.summary["maximum_queue_depth"] = max(
            self.summary["maximum_queue_depth"], queue_depth
        )
        if output_kind == "real":
            frame = ctx.real.get(frame_id)
            if frame is None or frame["closed"]:
                raise LatencyTraceError(
                    "real present references unknown or closed frame"
                )
            for plan in ctx.plans.values():
                if plan["right"] != frame_id or plan["planned"] == 0:
                    continue
                metadata_complete = (
                    len(plan["slots"]) == plan["planned"]
                    and plan["admitted"] is not None
                    and (
                        plan["admitted"] == plan["planned"] or plan["skip"] is not None
                    )
                )
                if not metadata_complete:
                    raise LatencyTraceError(
                        "generated plan metadata must be complete before the right "
                        "real frame present starts; a partial admission requires its "
                        "skipped suffix"
                    )
            if timestamp < frame["ready"]:
                raise LatencyTraceError(
                    "real present timestamp precedes ready timestamp"
                )
            simulation = ctx.simulations.get(frame_id)
        else:
            frame = ctx.generated.get(frame_id)
            if frame is None or not frame.get("acquired") or frame["closed"]:
                raise LatencyTraceError("generated present requires successful acquire")
            deadline = frame["deadline"]
            if deadline is not None and timestamp > deadline:
                self.summary["late_generated_present_call_count"] += 1
        order = _content_order(data["content_order"], output_kind, frame, event)
        if ctx.last_content_order is not None and not _order_less(
            ctx.last_content_order, order
        ):
            raise LatencyTraceError("present content order must be strictly increasing")
        ctx.last_content_order = order
        op = ("present", frame_id)
        if op in ctx.operations or frame_id in ctx.presented:
            raise LatencyTraceError("output present may start exactly once")
        ctx.operations[op] = (timestamp, {"kind": output_kind, "frame": frame})
        ctx.presented[frame_id] = {
            "started": timestamp,
            "returned": False,
            "result": None,
            "kind": output_kind,
            "real_ready_candidate": (
                timestamp - frame["ready"] if output_kind == "real" else None
            ),
            "input_candidate": (
                timestamp - ctx.inputs[simulation[0]]
                if output_kind == "real" and simulation
                else None
            ),
        }

    def _process_present_call_returned(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"output_frame_id", "result"}, event)
        frame_id = _identifier(data["output_frame_id"], "output_frame_id")
        result = _one_of(data["result"], set(_RESULTS), "present result")
        op = ctx.operations.pop(("present", frame_id), None)
        if op is None:
            raise LatencyTraceError(
                "present_call_returned lacks matching present start"
            )
        if timestamp < op[0]:
            raise LatencyTraceError("present return timestamp precedes start timestamp")
        op[1]["frame"]["closed"] = True
        ctx.presented[frame_id]["returned"] = True
        ctx.presented[frame_id]["result"] = result
        self.summary["present_results"][result] += 1
        if result in {"success", "suboptimal"}:
            present = ctx.presented[frame_id]
            self.summary["expected_feedback_count"] += int(
                self.caps["presentation_feedback"]
            )
            if present["real_ready_candidate"] is not None:
                self.samples["real"].append(present["real_ready_candidate"])
            if present["input_candidate"] is not None:
                self.samples["input"].append(present["input_candidate"])

    def _process_presentation_feedback(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"output_frame_id", "feedback_timestamp_ns", "status"}, event)
        if not self.caps["presentation_feedback"]:
            raise LatencyTraceError("presentation_feedback event without capability")
        frame_id = _identifier(data["output_frame_id"], "output_frame_id")
        status = _one_of(
            data["status"], {"presented", "dropped", "unknown"}, "feedback status"
        )
        if status == "presented":
            feedback_time = _integer(
                data["feedback_timestamp_ns"], "feedback_timestamp_ns"
            )
        else:
            if data["feedback_timestamp_ns"] is not None:
                raise LatencyTraceError(
                    "dropped or unknown feedback_timestamp_ns must be null"
                )
            feedback_time = None
        presented = ctx.presented.get(frame_id)
        if (
            presented is None
            or not presented["returned"]
            or presented["result"] not in {"success", "suboptimal"}
            or frame_id in ctx.feedback_ids
        ):
            raise LatencyTraceError(
                "feedback requires one successfully returned present"
            )
        if feedback_time is not None and feedback_time < presented["started"]:
            raise LatencyTraceError("feedback timestamp precedes present call")
        if feedback_time is not None and feedback_time > timestamp:
            raise LatencyTraceError(
                "feedback timestamp cannot be in the future relative to its event"
            )
        ctx.feedback_ids.add(frame_id)
        self.summary["received_feedback_count"] += 1
        self.summary[f"{status}_feedback_count"] += 1
        if status == "presented":
            assert feedback_time is not None
            self.samples[f"{presented['kind']}_feedback"].append(
                feedback_time - presented["started"]
            )
            if presented["kind"] == "real":
                frame = ctx.real[frame_id]
                self.samples["real_ready_feedback"].append(
                    feedback_time - frame["ready"]
                )
                simulation = ctx.simulations.get(frame_id)
                if simulation:
                    self.samples["input_feedback"].append(
                        feedback_time - ctx.inputs[simulation[0]]
                    )

    def _process_recovery_started(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"recovery_id"}, event)
        recovery_id = _identifier(data["recovery_id"], "recovery_id")
        if recovery_id in ctx.recovery_ids:
            raise LatencyTraceError("recovery_id must be unique per epoch")
        if any(operation[0] == "recovery" for operation in ctx.operations):
            raise LatencyTraceError(
                "only one active recovery is allowed per context epoch"
            )
        ctx.recovery_ids.add(recovery_id)
        ctx.operations[("recovery", recovery_id)] = (timestamp, data)
        self.summary["recovery_attempt_count"] += 1

    def _process_recovery_finished(
        self,
        ctx: _Context,
        event: str,
        data: dict[str, Any],
        timestamp: int,
    ) -> None:
        _exact(data, {"recovery_id", "result"}, event)
        recovery_id = _identifier(data["recovery_id"], "recovery_id")
        result = _one_of(data["result"], {"recovered", "failed"}, "recovery result")
        recovery = ctx.operations.pop(("recovery", recovery_id), None)
        if recovery is None:
            raise LatencyTraceError("recovery_finished lacks matching recovery_started")
        if timestamp < recovery[0]:
            raise LatencyTraceError(
                "recovery finish timestamp precedes start timestamp"
            )
        if result == "failed":
            self.summary["recovery_failed_count"] += 1


class _TraceRecordProcessor:
    def __init__(
        self,
        capabilities: dict[str, Any],
        samples: dict[str, list[int]],
        summary: dict[str, Any],
        record_count: int,
    ):
        self.capabilities = capabilities
        self.summary = summary
        self.record_count = record_count
        self.contexts: dict[tuple[str, int], _Context] = {}
        self.context_profile: dict[str, Any] | None = None
        self.highest_epoch: dict[str, int] = {}
        self.previous_sequence = 0
        self.previous_timestamp = -1
        self.seen_end = False
        self.events = _EventProcessor(capabilities, samples, summary)

    def process(self, position: int, record: dict[str, Any]) -> None:
        if not isinstance(record, dict):
            raise LatencyTraceError(f"record {position} must be an object")
        if self.seen_end:
            raise LatencyTraceError("records after end are forbidden")
        if record.get("record") == "end":
            self._process_end(position, record)
            return
        self._process_event(record)

    def _process_end(self, position: int, record: dict[str, Any]) -> None:
        _exact(
            record,
            {"record", "sequence", "timestamp_ns", "status", "lost_event_count"},
            "end",
        )
        sequence = _integer(record["sequence"], "end sequence", minimum=1)
        timestamp = _integer(record["timestamp_ns"], "end timestamp_ns")
        if sequence != self.previous_sequence + 1:
            raise LatencyTraceError("end sequence must be globally contiguous")
        if timestamp < self.previous_timestamp:
            raise LatencyTraceError("end timestamp must be nondecreasing")
        if record["status"] != "complete":
            raise LatencyTraceError("end status must be complete")
        if _integer(record["lost_event_count"], "lost_event_count") != 0:
            raise LatencyTraceError("lost_event_count must be zero for complete trace")
        if position != self.record_count - 1:
            raise LatencyTraceError("records after end are forbidden")
        self.seen_end = True
        self.previous_sequence = sequence
        self.previous_timestamp = timestamp

    def _process_event(self, record: dict[str, Any]) -> None:
        _exact(
            record,
            {
                "record",
                "sequence",
                "timestamp_ns",
                "context_id",
                "epoch",
                "event",
                "data",
            },
            "event envelope",
        )
        if record["record"] != "event":
            raise LatencyTraceError("middle records must have record=event")
        sequence = _integer(record["sequence"], "sequence", minimum=1)
        timestamp = _integer(record["timestamp_ns"], "timestamp_ns")
        if sequence != self.previous_sequence + 1:
            raise LatencyTraceError(
                "event sequence must start at one and be globally contiguous"
            )
        if timestamp < self.previous_timestamp:
            raise LatencyTraceError("timestamp_ns must be globally nondecreasing")
        self.previous_sequence = sequence
        self.previous_timestamp = timestamp

        context_id = _identifier(record["context_id"], "context_id")
        epoch = _integer(record["epoch"], "epoch")
        event = record["event"]
        if not isinstance(event, str):
            raise LatencyTraceError("event must be a string")
        data = record["data"]
        if not isinstance(data, dict):
            raise LatencyTraceError("event data must be an object")
        key = (context_id, epoch)

        if event == "context_created":
            self._create_context(key, context_id, epoch, data)
            return
        ctx = self.contexts.get(key)
        if ctx is None or not ctx.created:
            raise LatencyTraceError(
                "event references a context epoch before context_created"
            )
        if ctx.destroyed:
            raise LatencyTraceError("event references a destroyed context epoch")
        if event == "context_destroyed":
            self._destroy_context(ctx, data)
            return
        self.events.process(ctx, event, data, timestamp)
        _close_completed_batches(ctx)

    def _create_context(
        self,
        key: tuple[str, int],
        context_id: str,
        epoch: int,
        data: dict[str, Any],
    ) -> None:
        _exact(data, {"present_mode", "refresh_interval_ns"}, "context_created")
        _one_of(
            data["present_mode"],
            {"fifo", "mailbox", "fifo_latest_ready", "unknown"},
            "present_mode",
        )
        profile = {
            "present_mode": data["present_mode"],
            "refresh_interval_ns": _integer(
                data["refresh_interval_ns"], "refresh_interval_ns", minimum=1
            ),
        }
        if self.context_profile is None:
            self.context_profile = profile
        elif profile != self.context_profile:
            raise LatencyTraceError(
                "context_profile must be homogeneous across all context epochs"
            )
        if key in self.contexts:
            raise LatencyTraceError("context epoch was already created")
        expected = self.highest_epoch.get(context_id, -1) + 1
        if epoch != expected:
            raise LatencyTraceError(
                "context epoch must start at zero and increment by one"
            )
        if epoch > 0 and not self.contexts[(context_id, epoch - 1)].destroyed:
            raise LatencyTraceError(
                "previous epoch must be destroyed before creating the next epoch"
            )
        ctx = self.contexts[key] = _Context(context_id, epoch)
        ctx.created = True
        self.highest_epoch[context_id] = epoch

    def _destroy_context(self, ctx: _Context, data: dict[str, Any]) -> None:
        _exact(data, {"closure_policy"}, "context_destroyed")
        closure_policy = _one_of(
            data["closure_policy"],
            {"strict", "allow_idle_abandonment"},
            "closure_policy",
        )
        if ctx.operations:
            operation = next(iter(ctx.operations))[0]
            raise LatencyTraceError(
                f"context destroyed with a started {operation} operation lacking its end"
            )
        if set(ctx.simulations) - set(ctx.real):
            raise LatencyTraceError(
                "context destroyed with simulation_started lacking real_frame_ready"
            )
        if self.capabilities["presentation_feedback"]:
            expected_feedback = {
                frame_id
                for frame_id, present in ctx.presented.items()
                if present["result"] in {"success", "suboptimal"}
            }
            if expected_feedback - ctx.feedback_ids:
                raise LatencyTraceError(
                    "missing terminal presentation feedback before context destruction"
                )
        open_frames = sum(not frame["closed"] for frame in ctx.real.values())
        open_batches = sum(not plan["closed"] for plan in ctx.plans.values())
        open_generated = sum(
            not frame["closed"] for frame in ctx.generated.values() if frame["admitted"]
        )
        if closure_policy == "strict":
            _validate_strict_closure(ctx)
            if open_frames or open_batches:
                raise LatencyTraceError(
                    "strict context end requires all frame and batch lifecycles closed"
                )
        self.summary["abandoned_frame_count"] += open_frames + open_generated
        self.summary["abandoned_batch_count"] += open_batches
        ctx.destroyed = True
        ctx.closure_policy = closure_policy

    def finish(self) -> None:
        if not self.seen_end:
            raise LatencyTraceError("trace is truncated: missing complete end record")
        for ctx in self.contexts.values():
            if not ctx.destroyed:
                raise LatencyTraceError(
                    "complete end requires every context to be destroyed"
                )
            if ctx.closure_policy == "strict":
                _validate_strict_closure(ctx)


def evaluate_trace(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(records, list) or len(records) < 3:
        raise LatencyTraceError("trace must contain header, events, and end")
    header = _validate_header(records[0])
    if (
        sum(
            1
            for record in records
            if isinstance(record, dict) and record.get("record") == "event"
        )
        > MAX_EVENT_COUNT
    ):
        raise LatencyTraceError("event count exceeds limit")
    caps = header["capabilities"]
    samples: dict[str, list[int]] = {
        name: []
        for name in (
            "real",
            "input",
            "generation",
            "acquire",
            "real_feedback",
            "generated_feedback",
            "real_ready_feedback",
            "input_feedback",
        )
    }
    summary: dict[str, Any] = {
        "batch_count": 0,
        "planned_generated_frame_count": 0,
        "admitted_generated_frame_count": 0,
        "skipped_generated_frame_count": 0,
        "late_generated_present_call_count": 0,
        "maximum_queue_depth": 0,
        "acquire_results": {result: 0 for result in _RESULTS},
        "present_results": {result: 0 for result in _RESULTS},
        "expected_feedback_count": 0,
        "received_feedback_count": 0,
        "presented_feedback_count": 0,
        "dropped_feedback_count": 0,
        "unknown_feedback_count": 0,
        "recovery_attempt_count": 0,
        "recovery_failed_count": 0,
        "abandoned_frame_count": 0,
        "abandoned_batch_count": 0,
    }
    processor = _TraceRecordProcessor(caps, samples, summary, len(records))

    for position, record in enumerate(records[1:], 1):
        processor.process(position, record)
    processor.finish()
    contexts = processor.contexts

    summary["context_epoch_count"] = len(contexts)
    summary["context_id_count"] = len({key[0] for key in contexts})
    summary["real_ready_to_present_call_proxy_ns"] = _distribution(
        samples["real"], "no_successful_real_presents"
    )
    has_input_boundary = any(ctx.simulations for ctx in contexts.values())
    summary["input_observed_to_present_call_entry_proxy_ns"] = _distribution(
        samples["input"],
        "no_successful_real_present_for_input_boundary"
        if has_input_boundary
        else "input_boundary_unavailable",
    )
    summary["host_generation_duration_ns"] = _distribution(
        samples["generation"], "no_generated_frames"
    )
    summary["host_acquire_duration_ns"] = _distribution(
        samples["acquire"], "no_acquire_calls"
    )
    all_feedback = samples["real_feedback"] + samples["generated_feedback"]
    feedback_unavailable = (
        "presentation_feedback_unavailable"
        if not caps["presentation_feedback"]
        else "no_presented_feedback"
    )
    summary["present_call_to_feedback_proxy_ns"] = _distribution(
        all_feedback,
        feedback_unavailable,
    )
    summary["real_present_call_to_feedback_proxy_ns"] = _distribution(
        samples["real_feedback"],
        "presentation_feedback_unavailable"
        if not caps["presentation_feedback"]
        else "no_presented_real_feedback",
    )
    summary["generated_present_call_to_feedback_proxy_ns"] = _distribution(
        samples["generated_feedback"],
        "presentation_feedback_unavailable"
        if not caps["presentation_feedback"]
        else "no_presented_generated_feedback",
    )
    summary["real_ready_to_presentation_feedback_proxy_ns"] = _distribution(
        samples["real_ready_feedback"],
        "presentation_feedback_unavailable"
        if not caps["presentation_feedback"]
        else "no_presented_real_feedback",
    )
    summary["input_observed_to_real_feedback_proxy_ns"] = _distribution(
        samples["input_feedback"],
        (
            "input_boundary_unavailable"
            if not has_input_boundary
            else "presentation_feedback_unavailable"
            if not caps["presentation_feedback"]
            else "no_presented_feedback_for_input_boundary"
        ),
    )
    return {
        "valid": True,
        "schema": 1,
        "trace_id": header["trace_id"],
        "producer": header["producer"],
        "measurement_scope": header["measurement_scope"],
        "clock": header["clock"],
        "subject": header["subject"],
        "capabilities": header["capabilities"],
        "workload_id": header["workload_id"],
        "context_profile": processor.context_profile,
        "summary": summary,
    }


def _write_json(value: dict[str, Any], output: Path | None) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    if output is None:
        sys.stdout.write(payload)
    else:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=output.parent,
                prefix=f".{output.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, output)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate latency trace v1 evidence")
    parser.add_argument("trace", type=Path)
    parser.add_argument("--json-output", type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_USAGE
    try:
        result = evaluate_trace(load_trace(args.trace))
    except (LatencyTraceError, OSError) as exc:
        rejected = {"valid": False, "error": str(exc)}
        try:
            _write_json(rejected, args.json_output)
        except OSError as write_exc:
            print(f"latency trace gate output error: {write_exc}", file=sys.stderr)
        print(f"latency trace rejected: {exc}", file=sys.stderr)
        return EXIT_INVALID_TRACE
    try:
        _write_json(result, args.json_output)
    except OSError as exc:
        print(f"latency trace gate output error: {exc}", file=sys.stderr)
        return EXIT_INVALID_TRACE
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
