# Configuration guide

The defaults are a good starting point: fixed **2x**, Flow Scale **0.90**, Performance Mode disabled, and FP16 allowed
where supported. Adaptive mode defaults to a **90 FPS** target with **Smooth Cadence** enabled. Adaptive settings can be
changed while a game is running, but the layer briefly resets its timing and stability calculations afterwards. Let it
settle for a few seconds before judging performance. Restart the game after switching between Fixed and Adaptive so
the game-owned swapchain is created with the correct generated-frame capacity.

## Frame-generation mode

- **Frame Generation:** The first control switches frame generation on or off immediately, without changing the selected
  Fixed or Adaptive settings. Turn it back on to resume with those settings.
- **FPS Multiplier:** Fixed 2x, 3x, or 4x generation. lsfg-vk v2 has no fixed 0x multiplier; use the live **Frame
  Generation** switch instead.
- **Adaptive Frame Generation:** Optional mode that estimates the real frame rate and schedules zero to three generated
  frames to approach the selected target. It replaces the fixed multiplier controls for that profile. Target, ceiling,
  and Smooth Cadence changes apply live; expect a short settling period while Adaptive recalculates its timing.

  **Live-change settling period:** Changing an Adaptive setting while a game is running resets its timing and stability
  calculations. Give it a few seconds to settle before judging image quality, smoothness, or input responsiveness;
  normal play can continue once it has settled.
- **Target FPS:** 30–240 FPS. This is a target, not a guarantee: it cannot reduce a game already running above target,
  exceed the selected ceiling, or overcome GPU/model/compositor limits.
- **Maximum Adaptive Multiplier:** Ceiling for generated frames: 2x, 3x, or 4x. 3x is the balanced default; 2x usually
  gives the best image quality, while 4x gives Adaptive more headroom to reach the target. Test per game.
- **Smooth Cadence:** Enabled by default in Adaptive mode. Strict scheduling settles first and constant cadence is
  considered only when the target already needs nearly every matching cadence slot. It can make displayed motion look
  smoother, but does so by holding a continuous generation level; this can lower the real-frame presentation cadence and
  increase input lag. Leave it enabled where its visual smoothness is worthwhile; disable it when strict target
  scheduling or responsiveness matters more for that game. After a severe sustained slowdown, Adaptive briefly
  measures the real-only rate and either resumes fractional
  scheduling or tests one higher level when **Maximum Adaptive Multiplier** permits it. Rescue never exceeds that
  maximum and has a cooldown to avoid repeated switching.

Adaptive also has an automatic Steam-menu discontinuity safeguard, independent of **Smooth Cadence**. After a hard
cadence stall, it temporarily presents real frames, waits for the measured base cadence to remain healthy for one
second, and then restores the last proven generation level. If the old cadence does not recover within five seconds,
Adaptive discards that stale baseline and ramps again from zero. A sustained gameplay cadence drop instead stabilizes
for one second and rebases at the new measured rate, avoiding a five-second wait for an old rate that is no longer
achievable. This can briefly reduce displayed FPS after leaving a menu, but avoids treating its transient frame rate as
normal gameplay. After 2x has already proved stable, an isolated short gameplay hitch instead refreshes three real
history frames and resumes 2x immediately. Fixed mode does not use these Adaptive policies.

## Profiles and per-game selection

The plugin stores multiple lsfg-vk profiles in its private `conf.toml`; it does not create a separate layer install or
config file for every game. In the plugin's **Profile** section, choose **New Profile**, enter a name, and the plugin
copies the selected profile's settings, then switches to the new profile. Configure it normally afterwards.

To select engine settings automatically for a game, enter its executable/process name in **Active In**. lsfg-vk then
matches the appropriate profile at launch. Once at least one profile has an **Active In** value, the wrapper leaves
engine-profile selection to lsfg-vk; you can return the UI selector to **Default** without breaking automatic matching.
The following settings are profile-based and support that automatic match:

- Live Frame Generation, Fixed multiplier or Adaptive mode, Target FPS, Maximum Adaptive Multiplier, and Smooth Cadence
- Flow Scale, Performance Mode, GPU matching, and Active In

The `Lossless.dll` path and FP16 permission are shared globally because they apply to the installed engine, not to an
individual game.

Decky also keeps the launcher compatibility options per profile—Disable LSFG-VK on Next Launch, Hide HDR from Game
(Restart), Base FPS Cap, WoW64, Steam Deck Mode, and Zink. They are saved in this plugin's private profile state and
are restored when you select that profile in Decky. They cannot follow **Active In** automatically: those variables must
be set by the wrapper before lsfg-vk sees the game's process name. Select the profile manually before launching a game
that needs one of those compatibility options, then restart the game after changing profiles.

## Quality and matching

- **Flow Scale:** 0.25–1.0. Lower values generally reduce GPU cost; higher values favour optical-flow quality.
- **Performance Mode:** Uses a lighter model with lower GPU overhead and more artifacts. For the best v2 image quality,
  start with it disabled.
- **Allow FP16:** Allows half-precision processing on supported GPUs. It can improve performance; results vary by game
  and driver.
- **Lossless.dll Path:** Override detection when necessary. Leaving it blank allows lsfg-vk discovery.
- **Active In:** Optional comma-separated executable/process matching. If set, lsfg-vk selects matching profiles
  automatically.
- **GPU:** Optional GPU identifier for multi-GPU systems.

## Compatibility options

- **Base FPS Cap:** Optionally caps the base DirectX framerate before multiplication.
- **WoW64:** Enables `PROTON_USE_WOW64=1` for compatible 32-bit games, primarily as a ProtonGE crash workaround.
- **Steam Deck Mode:** A per-game compatibility path.
- **Zink:** Optional Vulkan-based OpenGL path for OpenGL games.

Gamescope WSI and MangoHud controls are deliberately not shown. The wrapper adds the private experimental manifest
ahead of the normal implicit-layer search path. Vulkan therefore discovers Gamescope WSI when SteamOS enables it, while
the first same-named LSFG-VK manifest remains the private experimental one. Existing caller-supplied layer paths are
preserved.

HDR is automatic rather than a configuration switch. With SteamOS HDR enabled, the engine recognizes the standard
Gamescope HDR10/PQ and linear-scRGB swapchain combinations. HDR10 is converted to linear scRGB around frame generation;
unsupported HDR transfer functions and HDR frame-generation initialization failures remain on real-frame passthrough
instead of producing incorrect colours or failing the game swapchain. A game must still implement HDR and may require
its own in-game HDR setting. For a rare startup problem caused by HDR exposure, use the selected profile's **Hide HDR
from Game (Restart)** workaround to boot in SDR and change the game's HDR setting. It remains active for that profile
until you turn it off. Use **Disable LSFG-VK on Next Launch** when the layer itself is the suspected cause. The plugin
writes `pacing = 'none'` and does not expose a
dual-GPU control. See
[Troubleshooting](TROUBLESHOOTING.md) and the release notes for build-specific compatibility guidance.
