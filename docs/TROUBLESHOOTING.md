# Troubleshooting

## HDR

There is no normal plugin HDR enable/disable switch. Enable HDR in SteamOS, then enable HDR in the game if it offers its
own setting. The experimental wrapper preserves Gamescope WSI discovery so compatible games can expose their HDR modes.
The engine diagnoses the swapchain format and colour space and supports the standard SteamOS HDR10/PQ and linear-scRGB
paths.

HDR10 frame generation is decoded from BT.2020/PQ into linear scRGB for the model, then encoded back to BT.2020/PQ for
presentation. Unsupported HDR encodings, including HLG and Dolby Vision, use the game's real frames rather than
synthesizing frames with incorrect colours. This does not make HDR available in a game that has no HDR renderer, and a
non-SteamOS compositor or GPU-driver HDR problem remains outside the plugin's colour pipeline.

For a quick engine check, start the game from Steam and inspect its log for a line like:

```text
lsfg-vk: swapchain colour pipeline: format=64; color-space=1000104008; mode=hdr10-pq; frame-generation=supported
```

`mode=scrgb-linear` is also supported. `frame-generation=passthrough` includes a reason on the following line and is a
safe compatibility result, not washed-out generated output.

The plugin does not force HDR on. If the game chooses an HDR format that LSFG has not validated, or LSFG cannot create
the HDR frame-generation resources on that GPU, the engine keeps the game's native swapchain and presents real frames.
If a game still fails before reaching its menu, select its Decky profile, enable **Hide HDR from Game (Restart)**,
and restart it. That emergency compatibility path uses the wrapper's previous isolated Vulkan discovery, preventing
Gamescope WSI from advertising HDR so the game can boot in SDR. Disable HDR in the game's settings, clear the Decky
workaround, and test LSFG again. **Disable LSFG-VK on Next Launch** remains available if the LSFG layer itself is the
problem. A separate everyday HDR switch is intentionally avoided.

## Steam menu / Gamescope recovery

The experimental wrapper enables a 50 ms bound when Gamescope does not release an extra generated-frame image. Rather
than waiting indefinitely, lsfg-vk presents the real game frame, keeps temporal history current, and probes for an
available generated image at a bounded rate.

In Adaptive mode, a successful recovery can request a game-owned Vulkan swapchain rebuild. The replacement context warms
real-frame history, retains the last proven generation level, and delays higher probes. A hard cadence stall now enters
a bounded discontinuity recovery first: Adaptive presents real frames until the healthy base cadence has returned for
one second, then restores the proven level. If that does not happen within five seconds, it starts a clean ramp from
zero. A sustained gameplay cadence drop uses a shorter one-second stabilization and then rebases at the new rate instead
of waiting for the old rate to return. The first image recovery in a hard-discontinuity window refreshes history without
immediately rebuilding the swapchain; a repeated stall can still use the guarded rebuild. This targets accumulated
latency, unstable restarts, and repeated load spikes after Steam-menu transitions. A short drop toward the base rate,
pause, or flicker can still occur during recovery.

When Adaptive is capped at 2x and has already validated that level, a short gameplay hitch of up to 250 ms takes a
lighter path: the engine keeps the proven 2x policy, refreshes three real frames of temporal history, and resumes.
Longer interruptions retain the full menu/focus recovery described above.

If the menu interrupts an Adaptive ramp or bridge test, the engine now treats that probe as incomplete rather than
failed and rearms it after two stable seconds. A probe that genuinely fails its throughput checks retains a 15-second
cooldown, with an earlier retry only after a sustained 15% real-only base-rate improvement.

Adaptive also stops at the lowest proven multiplier that can already supply at least 95% of the requested target. If a
newly accepted higher multiplier later causes a sustained real-frame collapse, the engine briefly measures cadence
without generated-frame work. It returns to the lower proven multiplier only when that measurement recovers the prior
rate; otherwise it keeps the higher multiplier because the game scene itself became more demanding. This prevents an
unnecessary 3x load from remaining slower than a capable fixed 2x path while avoiding false backoff in heavy scenes.

### Per-game recovery fallback

If a particular game pauses, flickers, or handles the rebuild poorly after closing the Steam menu, disable only the
swapchain-rebuild stage for that game. The 50 ms bound and history-only real-frame fallback remain enabled:

```text
LSFGVK_PRESENT_RECOVERY_RECREATE=0 ~/.local/bin/lsfg-vk-experimental %command%
```

Use that command in the game's **Steam Properties > Launch Options**. Remove it to return to the default guarded
recovery path.

## Collecting diagnostics

Diagnostics are off by default. They are written to the plugin-private file below, rather than Steam's cumulative
console log. Starting a game with diagnostics enabled replaces the previous diagnostic file, so it contains one current
test run.

For a Steam game, temporarily replace the normal launch option with:

```text
LSFGVK_PRESENT_DIAGNOSTICS=1 LSFGVK_PRESENT_DIAGNOSTICS_THRESHOLD_MS=25 ~/.local/bin/lsfg-vk-experimental %command%
```

For a Heroic game, leave its **Wrapper** as `/home/deck/.local/bin/lsfg-vk-experimental` and leave **Arguments**
empty. Under the game's **Environment Variables**, add these two name/value rows:

```text
LSFGVK_PRESENT_DIAGNOSTICS=1
LSFGVK_PRESENT_DIAGNOSTICS_THRESHOLD_MS=25
```

Do not put `%command%` or either variable in Heroic's Wrapper or Arguments fields.

Reproduce the issue, quit the game, then run this in Desktop Mode:

```bash
~/.local/bin/lsfg-vk-experimental-diagnostics all
```

The plugin installs that read-only helper beside its launch wrapper and refreshes it automatically when the plugin is
loaded. It selects the plugin-private log first and falls back to Steam's console log if necessary. Choose one or more
presets to produce a smaller report:

```bash
# Was HDR10/PQ or linear scRGB selected? Did HDR initialize or use passthrough?
~/.local/bin/lsfg-vk-experimental-diagnostics hdr

# Target selection, stabilization, cadence, ramp, load shedding, bridge and rescue.
~/.local/bin/lsfg-vk-experimental-diagnostics adaptive

# Generated-image timeout, real-frame fallback, history warm-up and recreation.
~/.local/bin/lsfg-vk-experimental-diagnostics recovery

# Slow acquire, fence, scheduling, copy, submission and presentation operations.
~/.local/bin/lsfg-vk-experimental-diagnostics performance

# Vulkan layer discovery, Gamescope WSI, swapchain context and colour selection.
~/.local/bin/lsfg-vk-experimental-diagnostics startup

# Failures, timeouts, fallbacks, passthrough and Vulkan errors.
~/.local/bin/lsfg-vk-experimental-diagnostics errors

# Combine related views without collecting unrelated Adaptive policy traffic.
~/.local/bin/lsfg-vk-experimental-diagnostics hdr recovery errors

# Every relevant LSFG, Vulkan-loader, and Gamescope WSI line from the run.
~/.local/bin/lsfg-vk-experimental-diagnostics --lines 2000 all > ~/lsfg-report.txt
```

Run `~/.local/bin/lsfg-vk-experimental-diagnostics --help` for the complete preset list. Use `--log PATH` to inspect a
specific saved log and `--lines N` to change the output limit. Presets only filter an existing log; they do not enable
diagnostics or change the game configuration.

If the helper is unavailable, these raw commands provide the two most common reports:

```bash
# HDR selection and safe fallback.
grep -aE 'lsfg-vk: (swapchain colour pipeline|frame generation disabled|LSFG frame-generation initialization failed)' ~/.config/decky-lsfg-vk-experimental/present-diagnostics.log | tail -n 100

# Adaptive policy and Gamescope recovery.
grep -aE 'lsfg-vk: present diagnostics: operation=(adaptive-|skip-generated-frames|resume-generated-frames|generated-image-recovered|history-warmup|request-swapchain-recreation|swapchain-recreation-suppressed|swapchain-context-create|swapchain-context-destroy)' ~/.config/decky-lsfg-vk-experimental/present-diagnostics.log | tail -n 800
```

Remove the temporary Steam launch variables or Heroic environment rows afterwards: diagnostics can generate substantial
log traffic.

## Update and Flatpak checks

After installing a new plugin ZIP, select **Install Experimental LSFG-VK (developer build)**. ZIP installation updates
the plugin files but does not replace the private native engine by itself.

For Heroic, also open **Flatpak Setup** and select **Update** for Heroic's matching runtime extension—usually 25.08. Do
not disable Heroic preparation or remove its per-game Wrapper command merely to update the extension.

If Decky does not show or reload a ZIP update, uninstall this experimental plugin from Decky, install the ZIP again,
restart your Steam Deck or Steam Machine, then install the private engine again.
