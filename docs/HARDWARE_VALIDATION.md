# Target-hardware validation

## Why this is separate from normal CI

GitHub-hosted Ubuntu runners can validate source, packaging, subprocess
contracts, and real Flatpak override behaviour. They cannot prove Steam Deck
frame pacing, generated-image quality, input responsiveness, power use, or
Gamescope presentation behaviour because they do not provide the target APU,
display stack, game workload, or physical display path.

The `Target hardware validation` workflow is therefore manual and runs only on
a dedicated SteamOS/Bazzite machine after approval through the
`steam-deck-hardware` environment. It accepts full baseline and candidate commit
SHAs, captures at least five independent runs, and compares the resulting JSON
reports with `.github/hardware-quality-policy.json`.

## Security boundary

Never attach a personal Steam Deck or a persistent machine containing accounts,
SSH keys, browser data, gamesaves, or repository credentials to a public pull
request workflow. A pull request can modify executable repository content.

The hardware runner must be disposable or reimaged after every job, have no
repository secrets, use a read-only GitHub token, and expose only the
`lsfg-hardware` label. The capture program at
`/opt/lsfg-hardware/bin/capture-comparison` must be root-owned and not writable
by the runner account. Create the `steam-deck-hardware` environment with required
reviewers and the environment variable `LSFG_HARDWARE_ENV_READY=true`;
otherwise the job fails before checkout. Maintainers review the candidate SHA
before approving the protected environment. Do not add an automatic
`pull_request` trigger to this workflow.

This follows GitHub's warning that self-hosted runners should almost never run
untrusted public pull-request code because they are not guaranteed to be clean,
ephemeral virtual machines: [GitHub secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use#hardening-for-self-hosted-runners).

## Required capture contract

The runner-local harness receives baseline/candidate source directories and
writes `baseline.json` and `candidate.json`. Each report contains:

```json
{
  "schema": 1,
  "environment": {
    "target_id": "steam-deck-lcd-01",
    "os_build": "...",
    "kernel": "...",
    "mesa": "...",
    "gamescope": "...",
    "display_mode": "1280x800@60",
    "tdp_watts": 15,
    "gpu_clock_policy": "fixed-1200mhz",
    "workload_id": "lsfg-fixed-motion-v1",
    "workload_build": "sha256:...",
    "workload_settings_hash": "sha256:..."
  },
  "subject": { "git_sha": "...", "engine_sha256": "..." },
  "runs": [
    {
      "frame_time_p95_ms": 0,
      "frame_time_p99_ms": 0,
      "missed_present_ratio": 0,
      "input_to_present_proxy_p95_ms": 0,
      "generated_frame_ssim": 1,
      "average_power_watts": 0,
      "process_crash_count": 0,
      "black_frame_count": 0,
      "generated_frame_failure_count": 0,
      "thermal_throttle_event_count": 0
    }
  ]
}
```

Baseline and candidate environment fields must match exactly. The gate rejects
missing/non-finite metrics, fewer than five runs, and a baseline whose median
absolute deviation is too high. This prevents a noisy or thermally throttled
capture from blessing a regression.

## What to measure

- **Frame pacing:** collect per-present timestamps and derive p95/p99 frame time,
  missed-present ratio, and generated-frame failures. MangoHud can log FPS,
  frametime, power, and percentile summaries; the harness must preserve raw logs
  locally for diagnosis. See the [MangoHud project documentation](https://github.com/flightlessmango/MangoHud#fps-logging).
- **Graphics:** capture the same deterministic scene and compare generated frames
  against the baseline sequence. The report currently accepts SSIM plus explicit
  black-frame/failure counters. Any future perceptual metric must be versioned in
  the policy and workload identity.
- **Latency:** `input_to_present_proxy_p95_ms` is only a software timestamp proxy.
  It must never be described as input-to-photon latency. True end-to-end latency
  requires an LED/photodiode, high-speed camera, or equivalent external rig.
- **Power and thermals:** keep TDP and GPU clock policy fixed, record average
  package power, and reject every thermally throttled run.

Use a fixed game/replay, camera path, save state, resolution, refresh rate,
graphics preset, LSFG profile, warm-up duration, and capture duration. Hash the
workload and settings so an accidental scene change cannot be compared to an
older baseline.

## Rollout

1. Keep the workflow manual while the capture harness and thresholds are being
   calibrated.
2. Collect several unchanged baseline-vs-baseline comparisons on each target.
3. Adjust the versioned policy only in a dedicated reviewed change with the raw
   variance evidence attached.
4. Once the runner is ephemeral and the false-positive rate is known, require
   this check only for native engine, wrapper, presentation, timing, shader,
   payload, or performance-policy changes. UI/docs-only pull requests do not need
   target-hardware evidence.

The checked-in thresholds are initial reviewable guardrails, not universal
performance truths. They must be recalibrated from unchanged A/A captures before
the workflow becomes a branch-protection requirement; threshold changes need the
same evidence as code changes and must not be loosened inside a performance PR.

The repository contains the Decky management plugin, not the native Vulkan
engine source. A plugin-only change cannot directly validate shader mathematics;
the hardware report records the exact pinned engine artifact so the evidence is
still attributable.
