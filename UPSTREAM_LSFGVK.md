# lsfg-vk experimental integration log

This file is the hand-off point for future lsfg-vk updates. The canonical machine-readable payload pin is the sole
`remote_binary` record in [`package.json`](package.json); this document records the review context and update procedure.
Update both in the same commit.

## Current baseline

| Item                        | Value                                                                                                                                                 |
|-----------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| Release repository          | [`eugeniosegala/lsfg-vk-experimental`](https://github.com/eugeniosegala/lsfg-vk-experimental)                                                         |
| Tracked branch              | `develop`                                                                                                                                             |
| Last checked                | 2026-08-11                                                                                                                                            |
| Integrated source commit    | `40f56701df1e43c4893d6110cb47362fb9565859`                                                                                                            |
| Commit date and subject     | 2026-08-11 — `release: prepare 2.0.0-dev28-experimental.19`                                                                                           |
| Experimental prerelease tag | `v2.0.0-dev28-experimental.19`                                                                                                                        |
| Release state               | Engine prerelease published and verified on 2026-08-11; Decky prerelease is prepared locally                                                          |
| Upstream lineage            | [`PancakeTAS/lsfg-vk`](https://github.com/PancakeTAS/lsfg-vk) `2.0.0-dev28`                                                                           |
| Release asset               | `lsfg-vk-2.0.0-dev28-experimental.19-linux.tar.xz`                                                                                                    |
| Asset SHA-256               | `2b26c0e532eb407eb8e1ac6252ba8dc0f6478b424065bbcfca8222e0898b6489`                                                                                    |
| Asset URL                   | `https://github.com/eugeniosegala/lsfg-vk-experimental/releases/download/v2.0.0-dev28-experimental.19/lsfg-vk-2.0.0-dev28-experimental.19-linux.tar.xz` |
| Flatpak archive             | `lsfg-vk-2.0.0-dev28-experimental.19-flatpaks.tar.xz`                                                                                                 |
| Flatpak SHA-256             | `35ad14a6fa0162e07c3c2d637cdde07d22dfd2a408d409f4877d4036eb3cdf7c`                                                                                    |
| Decky plugin version        | `0.13.0-experimental.19` (prepared locally; not yet released)                                                                                         |
| Decky plugin package ID     | `decky-lsfg-vk-experimental`                                                                                                                          |

This integration is pinned to the published tag and checksum-verified release assets above. The experimental fork's
`develop` branch may advance independently; do not treat newer commits as integrated until their source and immutable
artifacts have been reviewed and this record has been updated.

## Integrated Flatpak support

Engine release `v2.0.0-dev28-experimental.19` includes separate experimental Flatpak runtime extensions for 23.08, 24.08,
and 25.08. The Decky pin includes the checksum-verified host and Flatpak release assets. The local package script
downloads, verifies, and embeds those three extensions. The plugin prepares a Flatpak app to access its private
configuration, `Lossless.dll`, and wrapper; the wrapper then enables the experimental layer only for Heroic games
that explicitly select it.

| Item                 | Value                                                                                                             |
|----------------------|-------------------------------------------------------------------------------------------------------------------|
| Flatpak extension ID | `org.freedesktop.Platform.VulkanLayer.lsfgvkexperimental`                                                         |
| Extension prefix     | `/usr/lib/extensions/vulkan/lsfgvkexperimental`                                                                   |
| Supported runtimes   | Freedesktop `23.08`, `24.08`, and `25.08`                                                                         |
| Coexistence design   | Dedicated ID and prefix; the experimental plugin selects it only for Flatpak apps explicitly enabled by the user. |

The engine prerelease and both archive checksums have been verified. The Decky prerelease remains local until its
complete integration is reviewed and packaged.

### Adaptive Frame Generation

The published `v2.0.0-dev28-experimental.19` release retains the opt-in target-FPS scheduler introduced in `.9`. It
smooths the measured real-frame interval and dynamically schedules zero to three generated frames between real frames,
with evenly spaced interpolation timestamps. It adds a configurable 2x, 3x, or 4x Adaptive ceiling, defaulting to 3x.
If reaching the target would require a higher ratio, the scheduler deliberately undershoots the target instead of
adding more artifact-prone generated frames. Fixed 2x, 3x, and 4x operation continues through the previous code path
and remains the Decky default.

This is an independent implementation of the target-FPS concept, not a port of Lossless Scaling's closed Windows
capture engine. It cannot lower a real-frame rate that already exceeds the target, guarantee a target that exceeds
the selected multiplier/GPU/compositor limit, or expose the Windows application's Queue Target modes. Decky stores
`adaptive`, `target_fps`, and `adaptive_max_multiplier` per profile and disables the fixed multiplier controls while
Adaptive Frame Generation is selected.

### Gamescope presentation recovery

The published `v2.0.0-dev28-experimental.19` release retains the `.4` synchronization fix and diagnostics. SteamOS
traces showed the Steam-menu slowdown was dominated by generated-image acquisition, with waits reaching approximately
74 ms. Testing `.5` then showed the fallback working safely but repeating the full 25 ms timeout on every unavailable
frame. The `.6` engine uses non-blocking probes after the first timeout, continues showing real game frames while
Gamescope is unavailable, and resumes generated frames automatically. The `.7` engine performs those probes before
scheduling more inference: while no image is available, it keeps the two real-frame source images and synchronization
sequence aligned without dispatching model work whose output would be discarded. Generation resumes from the latest
two real frames. Testing `.7` also captured recoveries lasting 225 and 529 real frames because zero-timeout probes
could repeatedly miss the compositor's image-release window. The `.8` engine makes one bounded reacquisition attempt
per second after the first second of fallback, without forcing a game-owned swapchain recreation.

Prepared plugin version `0.13.0-experimental.19` enables a validated 50 ms timeout in its isolated wrapper. SteamOS
testing showed successful acquisitions between 25 and 48 ms, while genuine stalls reached the 50 ms bound; this avoids
the false fallbacks seen with the earlier 25 ms wrapper setting. Explicit caller overrides are preserved. The engine
itself remains opt-in when used outside this Decky plugin.

SteamOS Adaptive testing then confirmed a second issue: after a generated-image timeout, the `.7` counter-only bypass
kept synchronization aligned but did not refresh the model's shared temporal feature maps. Repeated Steam-menu
transitions could therefore resume generation from stale history and make ghosting accumulate. The `.10` engine runs
the shared mipmap and alpha/beta history pre-pass for every real frame during fallback while still skipping the more
expensive per-output generation passes. It also clears Adaptive smoothing and output credit when entering and leaving
backoff. Later `.10` traces showed that a single successful image probe could still restart Adaptive generation while
Gamescope availability was unstable. Testers also reported occasional elevated ghosting at game startup that cleared
after toggling Adaptive mode. The `.11` engine therefore presents three real frames to populate the deepest temporal
history ring before Adaptive first generates output, and repeats that warm-up after each successful Gamescope recovery.
The image acquired by the recovery probe is filled with the real frame and presented safely rather than being leaked
or used as immediate generated output. Testing then showed that repeated recoveries could still accumulate input
latency even with Adaptive capped at 2x, and toggling Adaptive could not always clear it. The `.13` engine therefore
adds a guarded `LSFGVK_PRESENT_RECOVERY_RECREATE=1` path: after an acquire timeout has recovered, it safely presents the
reacquired image and original game image before returning `VK_ERROR_OUT_OF_DATE_KHR`. The game then recreates its
swapchain, which creates a fresh LSFG context and runs the normal startup history warm-up. The experimental Decky
wrapper opts into this path while preserving an explicit caller override. Fixed multiplier behavior is unchanged.
The `.14` engine additionally stabilizes on real frames for one second after startup, recovery, or a sustained cadence
drop, then ramps generated-frame load one step at a time. It rolls back a step when base throughput collapses without
a useful output gain and shares a five-second recreation cooldown across replacement swapchains. This prevents the
recreate-and-immediately-overload loop observed in `.13` testing.
The `.15` engine addresses a remaining 0-to-1 probe loop seen in `.14`. When the first generated-frame step preserves
most estimated output but a Gamescope cadence divisor still makes it appear counterproductive, Adaptive can make one
bounded test at two generated frames. The bridge must demonstrate at least a 15% estimated-output improvement while
remaining inside base-FPS safety limits. A failed or cadence-interrupted probe waits at least 15 seconds and requires
two stable seconds before rearming, instead of repeatedly oscillating between zero and one generated frame.
The `.17` engine adds optional, bounded constant-cadence validation for safe fractional targets. For example, with a
90 FPS target, a stable 60 FPS game can validate a continuous 2x cadence (120 internal FPS) rather than alternate
real-only and generated frames to average 90. It keeps that cadence only if it sustains at least 98% of the target
while retaining at least 74% of the probe's base rate; otherwise it returns to strict target scheduling. Bounded
activation and retention limits, plus a short exit grace, tolerate normal frame-time variation without allowing costly
cases such as 100 -> 120 to run at 2x. Decky exposes `adaptive_stable_cadence` as the Adaptive-only **Smooth Cadence**
toggle. It now defaults to enabled: it can make motion smoother and feel more responsive in some games, while others
work better with it off. Enabling or disabling it does not change the other Adaptive protections.

The `.17` candidate now lets strict Adaptive settle before considering Smooth Cadence and requires the strict schedule
to demand at least 95% of the corresponding integer cadence. A severe sustained cadence collapse starts one bounded
real-only measurement. Adaptive then resumes fractional scheduling or probes one higher generated-frame level only when
the configured maximum permits it. The rescue path never exceeds **Maximum Adaptive Multiplier** and uses a 15-second
cooldown to prevent oscillation. Fixed mode remains unchanged.

Recovery now carries the last validated generation level into the replacement swapchain context. The existing
three-second real-frame stabilization and temporal-history warm-up still run first; generation then resumes at the
validated level instead of restarting from zero, while higher probes remain paused for five seconds. Repeated rejected
higher-level probes use progressive 5, 15, 30, and 60 second retry delays, with an early retry only if the measured base
rate improves by at least 15%. Adaptive policy decisions are frozen while generated output is bypassed during a
Gamescope acquisition stall so a cheaper real-frame-only path cannot falsely validate a multiplier. These changes are
Adaptive-mode logic only; fixed multiplier behavior is unchanged.

The final `.17` candidate adds a bounded discontinuity recovery for abrupt Gamescope cadence stalls such as a Steam-menu
transition. Adaptive remembers the last proven generation level and healthy base cadence, presents real frames while
the base cadence recovers, then restores that level only after one stable second. If stability does not return within
five seconds, it discards the stale baseline and ramps again from zero. The first generated-image recovery inside this
window refreshes history without immediately forcing another swapchain rebuild; a repeated stall can still use the
existing guarded rebuild. This prevents transient menu-rate samples from driving a fresh context into repeated probes,
load shedding, and recreation. Later Steam Deck testing showed that applying the same five-second policy to a sustained
gameplay cadence drop could wait for an old rate that was no longer achievable. A cadence drop now uses the ordinary
one-second stabilization and rebases at the new measured rate; only a hard stall retains the old baseline. Fixed mode
remains unchanged.

The latest `.17` source candidate also separates interrupted probes from genuine throughput failures. A ramp or bridge
probe interrupted by the Steam menu now rearms after two stable seconds without incrementing the failed-probe count.
A rejected first-step or bridge probe retains its 15-second cooldown, but may retry early when the real-only base rate
improves by at least 15% over the pre-probe baseline and remains there for two seconds. Diagnostics now identify the
rearm reason, remaining cooldown, baseline rate, and whether rearming followed interruption settling, performance
recovery, or normal cooldown expiry.

The final `.17` policy also avoids escalating generated-frame load once the lowest proven multiplier can already
supply at least 98% of the requested target. If measured capacity later falls below that threshold, the next level
becomes eligible automatically. This specifically avoids cases where an unnecessary 3x load reduces enough real-frame
throughput to perform worse than fixed 2x. A higher level that passes its initial probe is also monitored for a delayed
collapse. After one sustained second, Adaptive measures one second without generated-frame load: it restores the lower
proven level only if real cadence recovers, otherwise it keeps the higher level because the scene itself became more
demanding. A confirmed load-induced collapse is held for 15 seconds before another probe. Fixed mode remains unchanged.

The published `.18` release makes target satisfaction less sensitive to small display-rate variations, requires a
sustained deficit before increasing generated-frame load, and starts delayed-load rescue earlier when base throughput
collapses. It also rejects impossible DX12/VKD3D fast-present bursts before they can contaminate Adaptive's cadence
estimate. While such a burst is active, target-deficit, ramp, Smooth Cadence, rescue, and stabilization timers are
paused and reset; normal scheduling resumes from real-frame cadence after the burst. Diagnostics aggregate burst
frames at most once per second, report burst completion, and include a per-swapchain context identifier. Fixed
multiplier mode is unchanged.

The published `.19` release adds one narrow refinement for a validated 2x Adaptive ceiling. A hard gameplay hitch
between 100 and 250 ms now keeps the proven 2x policy, refreshes three real temporal-history frames, and resumes
without entering the one-to-five-second menu/focus recovery. Longer interruptions still use the guarded recovery
path. Fixed mode, Adaptive 3x/4x, generated-image acquisition fallback, and swapchain recreation are unchanged.

### Flatpak payload hotfix

`v2.0.0-dev28-experimental.3` corrects the Flatpak layer manifest's library path from `lib/` to the actual `lib64/`
location. It is a packaging correction only: it enables Heroic and other Flatpak applications to load the experimental
layer; it does not change lsfg-vk's rendering implementation. The engine release process now verifies the installed
Flatpak extension layout and manifest path for all three supported runtimes before publishing.

## Decky integration commits

- `b846c9aa4834213122533bea4134904f9081fc7b` — core installer, configuration, launcher, UI, and documentation update.
- `d52acde3131ea7f4a71764d58254dd46eb35d213` — automatic profile matching, Flatpak overrides, and disable switch.
- `15c21ac748ceb22b615f7fdc10e4ee391bcd3f00` — editable Lossless.dll path in the Decky UI.

## Next update procedure

1. Fetch the experimental branch and tags:

   ```bash
   git -C /path/to/lsfg-vk-experimental fetch origin develop --tags
   ```

2. Compare from the baseline commit above:

   ```bash
   git -C /path/to/lsfg-vk-experimental log --oneline 40f56701df1e43c4893d6110cb47362fb9565859..origin/develop
   ```

3. Review the fork's release notes, `docs/Configuration.md`, `docs/Flatpak-Guide.md`, host release asset, Flatpak
   archive, and packaging scripts. Confirm the host archive has the expected layer, manifest, and CLI filenames; for
   Flatpak support, confirm the archive contains the 23.08, 24.08, and 25.08 experimental extension bundles.
4. Update the single `remote_binary` record in `package.json`. It is the canonical runtime pin used by both the local
   packager and the installed plugin. When the release provides Flatpak support, add its checksum-verified
   `flatpak_bundle` record at the same time. Update this document and `third_party/lsfg-vk/README.md` to match the
   release metadata; copy reviewed archives into `third_party/lsfg-vk/` when retaining Git-backed recovery copies.
5. Regenerate the schemas with `python3 scripts/generate_ts_schema.py`, then build the frontend with `pnpm run build`.
6. Build a local Decky ZIP and verify its embedded archive checksum before publishing a new Decky prerelease.

## Scope note

This tracks releases from `eugeniosegala/lsfg-vk-experimental`. PancakeTAS remains the upstream project and should be
credited for lsfg-vk, but a PancakeTAS branch commit is not considered bundled until this fork publishes and Decky pins
a reviewed immutable asset.
