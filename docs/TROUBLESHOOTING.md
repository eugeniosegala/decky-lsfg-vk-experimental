# Troubleshooting

## Steam menu / Gamescope recovery

The experimental wrapper enables a 50 ms bound when Gamescope does not release an extra generated-frame image. Rather
than waiting indefinitely, lsfg-vk presents the real game frame, keeps temporal history current, and probes for an
available generated image at a bounded rate.

In Adaptive mode, a successful recovery can request a game-owned Vulkan swapchain rebuild. The replacement context
warms real-frame history, retains the last proven generation level, and delays higher probes. A hard cadence stall
now enters a bounded discontinuity recovery first: Adaptive presents real frames until the healthy base cadence has
returned for one second, then restores the proven level. If that does not happen within five seconds, it starts a clean
ramp from zero. A sustained gameplay cadence drop uses a shorter one-second stabilization and then rebases at the new
rate instead of waiting for the old rate to return. The first image recovery in a hard-discontinuity window refreshes
history without immediately rebuilding the swapchain; a repeated stall can still use the guarded rebuild. This targets
accumulated latency, unstable restarts, and repeated load spikes after Steam-menu transitions. A short drop toward the
base rate, pause, or flicker can still occur during recovery.

If the menu interrupts an Adaptive ramp or bridge test, the engine now treats that probe as incomplete rather than
failed and rearms it after two stable seconds. A probe that genuinely fails its throughput checks retains a 15-second
cooldown, with an earlier retry only after a sustained 15% real-only base-rate improvement.

Adaptive also stops at the lowest proven multiplier that can already supply at least 98% of the requested target. If
a newly accepted higher multiplier later causes a sustained real-frame collapse, the engine briefly measures cadence
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
console log. Starting a game with diagnostics enabled replaces the previous diagnostic file, so it contains one
current test run.

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
grep -aE 'lsfg-vk: present diagnostics: operation=(adaptive-plan|adaptive-discontinuity|adaptive-stabilization|adaptive-ramp|adaptive-ramp-accepted|adaptive-ramp-backoff|adaptive-ramp-early-retry|adaptive-recovery-resume-scheduled|adaptive-load-shed|adaptive-rescue|adaptive-bridge|adaptive-bridge-accepted|adaptive-bridge-rejected|adaptive-probe-aborted|adaptive-rearm-scheduled|adaptive-rearm-ready|skip-generated-frames|generated-image-recovered|request-swapchain-recreation|swapchain-recreation-suppressed|swapchain-context-create|swapchain-context-destroy)' ~/.config/decky-lsfg-vk-experimental/present-diagnostics.log | tail -n 800
```

Remove the temporary Steam launch variables or Heroic environment rows afterwards: diagnostics can generate
substantial log traffic.

## Update and Flatpak checks

After installing a new plugin ZIP, select **Install Experimental LSFG-VK (developer build)**. ZIP installation updates
the plugin files but does not replace the private native engine by itself.

For Heroic, also open **Flatpak Setup** and select **Update** for Heroic's matching runtime extension—usually 25.08.
Do not disable Heroic preparation or remove its per-game Wrapper command merely to update the extension.

If Decky does not show or reload a ZIP update, uninstall this experimental plugin from Decky, install the ZIP again,
restart your Steam Deck or Steam Machine, then install the private engine again.
