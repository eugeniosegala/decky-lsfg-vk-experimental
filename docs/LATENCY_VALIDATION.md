# Latency validation

## What this repository can and cannot validate

The complete player-visible path is longer than this plugin's boundary:

```text
controller
  -> USB/Bluetooth and Linux input
  -> Steam Input
  -> game / Proton / Wine
  -> game simulation
  -> real-frame rendering through Vulkan / DXVK / VKD3D
  -> application vkQueuePresentKHR
  -> LSFG Vulkan layer (history, inference, acquire, generated/real presents)
  -> Gamescope / limiter / compositor
  -> DRM/KMS scanout
  -> OLED/LCD pixel response
```

LSFG runs after the game has sampled input and rendered a real frame. Frame
generation can improve motion cadence, but it cannot turn a 45 Hz simulation
into a 90 Hz simulation. At 30, 45, and 60 FPS, new game state is produced at
approximately 33.33, 22.22, and 16.67 ms intervals respectively.

Generic CI cannot observe the physical input edge, Gamescope/DRM scanout, or
pixel response. Schema v1 exercises synthetic software-proxy calculations; it
does not measure a running plugin. Any future native data would still be a
**software latency proxy**, never input-to-photon evidence. Input-to-photon
claims require target hardware plus an external optical measurement such as a
photodiode, latency analyzer, or suitable high-speed camera.

## Why the trace contract exists

The v1 trace contract is **synthetic conformance only**. It gives CI a strict
event vocabulary with which to test provenance, causality, temporal content
order, lifecycle closure, and summary arithmetic. It does not accept native
runtime traces, apply performance thresholds, or prove that the bundled native
engine has good latency. Native evidence requires a future schema v2 with
runtime semantics that v1 intentionally does not guess.

This PR intentionally does **not**:

- change Smooth Cadence, its default, or any UI option;
- change interpolation timestamps, model quality, Flow Scale, Performance Mode,
  HDR behavior, present mode, or the pinned native artifact;
- reorder submitted frames or implement generated-frame admission;
- run a pretend Vulkan/LSFG benchmark on Lavapipe and call it runtime evidence.

Smooth Cadence is an existing Adaptive option with an intentional trade-off:
steadier generated cadence can reduce real-frame cadence and responsiveness.
Changing the default or adding a profile would choose a preference rather than
fix a proven quality-neutral defect. A future real-frame-priority policy belongs
in the native scheduler and must reject unsafe generated work *before* it is
submitted; FIFO content cannot safely be reordered afterward.

## Tools

Validate a trace and write a canonical result:

```bash
python3 scripts/latency_trace_gate.py trace.jsonl \
  --json-output latency-result.json
```

Exit codes are stable:

| Code | Meaning |
|---:|---|
| `0` | complete conformant synthetic trace; summary arithmetic is valid for that test vector |
| `2` | invalid, truncated, unreadable, or unwritable evidence; no trusted summary |
| `64` | command-line usage error |

Generate deterministic conformance examples:

```bash
python3 scripts/latency_trace_simulator.py --scenario normal > trace.jsonl
python3 scripts/latency_trace_gate.py trace.jsonl
```

Available scenarios are `normal`, `continuous`, `prefix-skip`,
`deadline-miss`, and `recovery`. The simulator has a fake clock and is
independent from the evaluator: it imports neither evaluator transitions nor
expected summaries. Its output is a test vector, not a benchmark.

## Trace v1 envelope

The format is UTF-8 JSON Lines. The first record is a header, middle records are
events, and the final record is a complete end marker. Unknown fields and events
fail closed. Limits are 1 MiB per file, 16 KiB per line, 10,000 events, nesting
depth 6, and printable ASCII IDs of 1-128 characters. NaN/Infinity, duplicate
JSON object keys at any nesting level, and booleans in integer fields are
rejected. JSON integers are limited to 128 decimal digits before conversion, so
pathological numeric input produces a controlled invalid-evidence result rather
than a parser traceback. Nesting checks do not recurse over attacker-controlled
JSON.

The reader opens one descriptor with close-on-exec, no-follow, and nonblocking
flags where the platform provides them. It accepts regular files only, reads at
most 1 MiB plus one detection byte, rejects more than 10,002 physical records
before JSON expansion, and verifies descriptor identity and size before and
after the read. This makes special-file blocking, growth, and record-amplification
attempts invalid evidence. Replacing the pathname cannot
change the already-opened evidence; mutation of that opened inode is rejected.
Producers must finish and close an immutable trace file before invoking the
validator; changes to its identity, size, modification time, or metadata-change
time during validation are rejected.

Header fields bind the trace to:

- schema and producer;
- the literal `synthetic_conformance` scope;
- one nanosecond clock domain;
- plugin commit, engine commit/artifact digest, and configuration digest;
- feedback, GPU-duration, and deadline-source capabilities;
- a named workload.

`native_software_proxy` is reserved and rejected by schema v1. Presentation
feedback is accepted only after producer-side normalization to the header clock
domain and after a successful/suboptimal present. Every such present must have
exactly one terminal feedback event before context destruction. `presented`
feedback has a non-negative integer normalized timestamp no later than the
feedback event; `dropped` and `unknown` feedback have a null timestamp. Missing
required feedback invalidates a complete trace. Missing capabilities produce
`null` metrics with a reason rather than misleading zeros. Canonical valid
results retain producer, subject, clock, capabilities, and workload provenance.

Every event has a contiguous global integer sequence starting at one, a non-negative timestamp,
`context_id`, `epoch`, event name, and exact data object. Equal timestamps are
valid, but timestamps must never decrease in record order. Producers that learn
an asynchronous result later must normalize its observation timestamp into the
main clock without inserting an older timestamp after newer records. Lifecycle
boundaries add stricter causal checks for simulation-to-ready, start-to-finish,
present-to-feedback, and deadline comparisons.

Within each `(context_id, epoch)`, `real_index` is trace-relative: the first real
frame is index zero and each subsequent real frame increments it by exactly one.

The end marker immediately follows the final event in the same sequence and has
an exact `lost_event_count` field. A complete trace is valid only when that value
is the integer zero (not a boolean). A producer must assign the sequence number
before an event enters any buffer, and increment its loss counter for every
event that cannot be retained or written. It must not emit a `complete` end
marker with a nonzero loss count.

## Temporal order and admission

Generated content uses exact rational order rather than floating point:

```text
slot i of N before right real frame k: (right_real_index=k, i/(N+1))
right real frame k:                    (right_real_index=k, 1/1)
```

Slots are one-based and contiguous. The gate compares rationals by cross
multiplication and rejects temporal inversion. Slot deadlines must be
nondecreasing in the same temporal order. Planning must occur before the right
real frame begins its lower present. Before that present starts, a positive batch
must declare every slot, admit exactly one contiguous prefix, and declare any
skipped suffix. This forward-causal boundary prevents later metadata from
rewriting a real-present decision that already happened. Admission at a deadline
is valid; admission after it is invalid. A `deadline_missed` event may reference
only an admitted slot, never a skipped suffix, and must be followed by the exact
generated present after its declared deadline.

Each adjacent real-frame pair may have only one plan in schema v1. Replanning
would require explicit cancellation or supersession semantics in a later schema.

These rules describe evidence for a possible future policy. They do not assert
that the currently pinned engine implements prefix admission.

In v1, a deadline applies only to host entry into `present_call_started`. It does
not prove queue admission, submission serialization, compositor acceptance,
display timing, scanout, or that a real frame received priority over generated
work. A return or presentation-feedback timestamp after the deadline does not by
itself constitute a deadline miss when present-call entry was on time.

## Lifecycle and failure semantics

Contexts are keyed by `(context_id, epoch)`; an ID may be reused only with the
next epoch and after its preceding epoch was destroyed. Real frames, generated
batches, generation, acquire, present, and recovery calls must close exactly
once. A generated output receives exactly one acquire attempt, including when
that attempt returns success or suboptimal. Normal destruction requires complete
lifecycle closure. Out-of-date, recovery-failed, or shutdown destruction may
abandon idle frames/batches, but never repairs a started call with no matching
return. Likewise, `simulation_started` is forward causal: its output ID must not
already exist as a real or generated frame.

Synthetic runtime-failure scenarios are valid *bad* conformance evidence.
Acquire/present timeout,
out-of-date/error, dropped feedback, and failed recovery remain visible as
counters instead of making the trace structurally invalid. This distinction
prevents a gate from discarding the failures it was designed to detect.

Every `simulation_started` mapping must reach its matching `real_frame_ready`
before context destruction, including non-normal destruction. Its output ID is
reserved for that real frame and cannot be reused as a generated frame ID.

## Summary definitions

Only a complete valid trace receives a summary. Distributions use deterministic
nearest-rank p50/p95/p99. The summary includes:

- successful/suboptimal real-ready to host present-call-entry proxy;
- optional `input_observed_to_present_call_entry_proxy_ns` from producer-observed
  input to the matching successful/suboptimal real host present-call entry;
- host generation and acquire durations;
- separate real and generated host present-call-entry to normalized presented
  feedback proxies, plus their aggregate;
- direct real-ready to presented-feedback and optional
  `input_observed_to_real_feedback_proxy_ns` from observed input to matching real
  presented feedback;
- maximum declared queue depth;
- planned, admitted, skipped, and deadline-missed generated **frame** counts;
- separate batch and context/epoch counts;
- acquire/present outcomes; expected, received, presented, dropped, unknown, and
  missing feedback counts; recovery attempts/failures; and explicitly abandoned
  frames/batches.

Failed present attempts contribute only to outcome counters; they do not create
latency samples. Dropped and unknown terminal feedback contribute to feedback
counters but not timestamp distributions.

The existing hardware quality gate remains responsible for baseline/candidate
comparison, robust evidence aggregation, visual metrics, power, thermals,
crashes, black frames, and generation failures.

## Required progression before runtime changes

1. Land this contract and its independently hand-authored fixtures.
2. In a separate PR, optionally add a synthetic Vulkan producer only to validate
   loader/event plumbing; do not attach numeric latency claims to it.
3. Define schema v2 native semantics, including queue identity, the exact
   instrumentation boundary, binding between feedback and output provenance,
   and an immutable effective-configuration hash.
4. Instrument the exact native source with bounded diagnostics-off overhead and
   immutable source/artifact/config provenance.
5. Prove whether the scheduler already prioritizes fresh real frames and where
   deadline risk enters before changing admission.
6. Test injected-clock scheduling across 40/60/90/120 Hz and 2x/3x/4x, including
   overload, recovery, warm-up, oscillation, and unsupported timing.
7. Publish a new checksummed native artifact, update the plugin pin, and require
   repeated target-hardware A/B evidence with existing visual, stability, power,
   and thermal gates.

Stop if exact native source is unavailable, clock domains cannot be normalized,
instrumentation changes diagnostics-off behavior, a design requires FIFO
reordering, or stable target evidence regresses.
