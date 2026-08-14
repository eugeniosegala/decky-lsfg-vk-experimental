# Troubleshooting

## HDR

Experimental HDR frame generation is still developing and disabled by default. Leave **Disable Experimental HDR
(Restart)** enabled for untested games. To test HDR, select the game's Decky profile, turn that option off, enable HDR
in SteamOS and the game, and restart the game. Leave it off only for games where HDR works well.
This is a restart-time exposure boundary rather than a live force-HDR switch: compatible games still select HDR
themselves. The experimental wrapper then preserves Gamescope WSI discovery and authorizes a guarded compatibility
bootstrap for the known Gamescope case where its app-HDR Boolean remains unset. That bootstrap additionally requires an
HDR Gamescope output and a 10-bit or float swapchain; blocked/default SDR profiles cannot enter it. The engine diagnoses
the swapchain format and colour space for the standard SteamOS HDR10/PQ and linear-scRGB paths.

HDR10 frame generation is decoded from BT.2020/PQ into linear scRGB for the model, then encoded back to BT.2020/PQ for
presentation. Unsupported HDR encodings, including HLG and Dolby Vision, use the game's real frames rather than
synthesizing frames with incorrect colours. This does not make HDR available in a game that has no HDR renderer, and a
non-SteamOS compositor or GPU-driver HDR problem remains outside the plugin's colour pipeline.

For HDR10, the experimental engine automatically uses 32-bit packed boundary images when both Vulkan devices validate
the required external-image and storage capabilities. This is not a lossy block-compression mode or a user setting:
HDR10 already has 10-bit PQ precision at the game boundary, while PQ conversion, frame generation, and temporal working
images remain linear 16-bit float. The smaller exchange images target VRAM pressure and boundary bandwidth on Steam
Deck without changing the Adaptive scheduler.

For a quick engine check, start the game from Steam and inspect its log for a line like:

```text
lsfg-vk: experimental layer active; identity=VK_LAYER_LSFGVK_experimental_frame_generation; build=2.0.0-dev28-experimental.25
lsfg-vk: Gamescope application HDR feedback stabilized: active=1; activation_source=gamescope-app-colorspace; contexts_pending_private_transition=1
lsfg-vk: swapchain colour pipeline transitioned in place: mode=hdr10-pq; transport=packed-hdr10-32-bit; application_device_supported=1; backend_device_supported=1
lsfg-vk: HDR10 transport: mode=packed-10-bit; nominal_bytes=16384000; nominal_bytes_saved=16384000; application_device_supported=1; backend_device_supported=1
```

The first line is the authoritative build marker. With `VK_LOADER_DEBUG=layer`, the inserted LSFG layer must be
`VK_LAYER_LSFGVK_experimental_frame_generation` from the plugin-private library. The wrapper sets `DISABLE_LSFGVK=1`
and `DISABLE_LSFG=1`, so `VK_LAYER_LSFGVK_frame_generation` and `VK_LAYER_LS_frame_generation` may be listed as known
manifests but must not be inserted into the game. If the build marker is absent, the HDR result does not test this
experimental engine.

In the loader's `vkCreateInstance layer callstack`, Gamescope WSI should remain above the experimental layer. Wine uses
that position to translate its WSI handles before lower Vulkan layers receive swapchain calls. Gamescope deliberately
changes its driver-facing swapchain copy to the sRGB colour space, so a working HDR trace can report `color-space=0`
while selecting `mode=hdr10-pq; source=gamescope-normalized` (or `mode=scrgb-linear` for float input). If the log instead
starts with `gamescope-hdr-pending`, that is the intentional real-frame safety state while the root-display feedback
settles. It should be followed by `runtime-transition-applied` and the in-place colour-pipeline transition. If it remains
pending, include the HDR preset in the report and confirm that SteamOS HDR is enabled and the game process has
`DXVK_HDR=1`.

For the current x86-64 experimental HDR test, the wrapper enables
`VK_LAYER_DECKY_LSFGVK_experimental_hdr_stack_x86_64`. Its Vulkan meta-layer components must appear as Gamescope WSI
before experimental LSFG in the loader callstack. Seeing both component names is not sufficient: if LSFG appears above
Gamescope, LSFG may initialize yet never receive the game's translated swapchain calls. That failure has a distinctive
trace: the HDR activation line is present and Gamescope creates swapchains, but there is no `swapchain colour pipeline`,
`runtime-state-applied`, or `swapchain-context-create` line. Default SDR does not enable this experimental meta-layer.
If the meta-layer validates but neither component appears in the callstack, confirm the wrapper does not export
`DISABLE_GAMESCOPE_WSI` or `DISABLE_LSFGVK_EXPERIMENTAL`; format 21 used those hard-disable gates and suppressed the
components as well as their unordered standalone instances.

`mode=scrgb-linear` is also supported. `frame-generation=passthrough` includes a reason on the following line and is a
safe compatibility result, not washed-out generated output.

`HDR10 transport: mode=packed-10-bit` confirms that the compact path was selected. `nominal_bytes_saved` covers only
the private source/output transport images for that context, not all LSFG allocations. `mode=rgba16f` with either
support field at `0` means the device capability check kept the established float transport; it is useful evidence to
include in an HDR performance report.

The plugin does not force HDR on. If the game chooses an HDR format that LSFG has not validated, or LSFG cannot create
the HDR frame-generation resources on that GPU, the engine keeps the game's native swapchain and presents real frames.
If a game fails before reaching its menu, select its Decky profile, re-enable **Disable Experimental HDR (Restart)**,
and restart it. That compatibility path uses the wrapper's previous isolated Vulkan discovery, preventing
Gamescope WSI from advertising HDR so the game can boot in SDR. It also bypasses other global Vulkan layers for that
game. Disable HDR in the game's settings, clear the Decky
workaround, and test LSFG again. **Disable Experimental LSFG-VK on Next Launch** remains available if the LSFG layer itself is the
problem.

## Steam menu / Gamescope recovery

The developing Gamescope HDR transport reserves generated destinations with timeout zero before scheduling model work.
If no image is immediately available, the real game frame wins: LSFG schedules no synthetic work, presents natively,
and retries on the next frame. It also polls private GPU work without blocking the game's present thread. The wrapper's
50 ms acquisition ceiling remains only for the legacy non-Gamescope path. The proven SDR transport intentionally keeps
its ordered FIFO and synchronous fence behaviour; applying the opportunistic HDR bypass to SDR caused generated frames
to be skipped on ordinary one-frame overlap on Deck-class hardware.

Recovery never returns a fabricated out-of-date result merely to make the game rebuild its swapchain. Ordered SDR and
Gamescope HDR deliberately use different policies. SDR refreshes two real history frames after a cadence discontinuity
and retains the last proven multiplier; sustained model-load collapse falls directly to the cheaper proven generated
level, while validated 2x is retained rather than inserting a visible real-only second. HDR uses the more conservative
bounded discontinuity recovery because a stall can also mean colour-transition or compositor-admission pressure. It
presents real frames until healthy base cadence has returned for one second, restores the proven level, or starts a
clean ramp after the bounded timeout. This separation prevents HDR safety guards from degrading the established SDR
path.

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
# Was HDR10/PQ or linear scRGB selected, and was packed HDR10 transport enabled?
~/.local/bin/lsfg-vk-experimental-diagnostics hdr

# Did a Decky change apply live or wait safely for natural recreation?
~/.local/bin/lsfg-vk-experimental-diagnostics config

# Target selection, stabilization, cadence, ramp, load shedding, bridge and rescue.
~/.local/bin/lsfg-vk-experimental-diagnostics adaptive

# Generated-image timeout, real-frame fallback, history warm-up and in-place recovery.
~/.local/bin/lsfg-vk-experimental-diagnostics recovery

# Fixed multiplier/input-output telemetry plus slow GPU/presentation operations.
~/.local/bin/lsfg-vk-experimental-diagnostics performance

# Vulkan layer discovery, Gamescope WSI, swapchain context and colour selection.
~/.local/bin/lsfg-vk-experimental-diagnostics startup

# Failures, timeouts, fallbacks, passthrough and Vulkan errors.
~/.local/bin/lsfg-vk-experimental-diagnostics errors

# Combine related views without collecting unrelated Adaptive policy traffic.
~/.local/bin/lsfg-vk-experimental-diagnostics hdr config adaptive recovery performance errors

# Every relevant LSFG, Vulkan-loader, and Gamescope WSI line from the run.
~/.local/bin/lsfg-vk-experimental-diagnostics --lines 2000 all > ~/lsfg-report.txt
```

Run `~/.local/bin/lsfg-vk-experimental-diagnostics --help` for the complete preset list. Use `--log PATH` to inspect a
specific saved log and `--lines N` to change the output limit. Presets only filter an existing log; they do not enable
diagnostics or change the game configuration.

If the helper is unavailable, these raw commands provide the two most common reports:

```bash
# HDR selection, private transition, and safe fallback.
grep -aE 'lsfg-vk: (Gamescope application HDR feedback|swapchain colour pipeline|HDR10 transport|frame generation disabled|LSFG frame-generation initialization failed)|lsfg-vk: present diagnostics: operation=(runtime-transition-pending|runtime-transition-applied|runtime-state-applied|gamescope-refresh-rate-applied)' ~/.config/decky-lsfg-vk-experimental/present-diagnostics.log | tail -n 200

# Adaptive policy and Gamescope recovery.
grep -aE 'lsfg-vk: present diagnostics: operation=(runtime-transition-pending|runtime-transition-applied|runtime-state-applied|gamescope-refresh-rate-applied|generated-delivery-miss|fixed-plan|adaptive-|skip-generated-frames|resume-generated-frames|generated-image-recovered|history-warmup|swapchain-recreation-suppressed|swapchain-context-create|swapchain-context-destroy)' ~/.config/decky-lsfg-vk-experimental/present-diagnostics.log | tail -n 800
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
