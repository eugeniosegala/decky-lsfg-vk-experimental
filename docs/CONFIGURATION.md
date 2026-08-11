# Configuration guide

The defaults are a good starting point: fixed **2x**, Flow Scale **0.90**, Performance Mode disabled, and FP16 allowed
where supported. Adaptive settings can be changed while a game is running, but the layer briefly resets its timing and
stability calculations afterwards. Let it settle for a few seconds before judging performance. Restart the game if a
switch between Fixed and Adaptive causes instability or fails to attach.

## Frame-generation mode

- **FPS Multiplier:** Fixed 2x, 3x, or 4x generation. lsfg-vk v2 has no fixed 0x choice. Use the plugin's **Disable
  Frame Generation** setting and restart the game when you need to run without it.
- **Adaptive Frame Generation:** Optional mode that estimates the real frame rate and schedules zero to three generated
  frames to approach the selected target. It replaces the fixed multiplier controls for that profile. Target, ceiling,
  and Smooth Cadence changes apply live; expect a short settling period while Adaptive recalculates its timing.

  **Live-change settling period:** Changing an Adaptive setting while a game is running resets its timing and stability
  calculations. Give it a few seconds to settle before judging image quality, smoothness, or input responsiveness;
  normal play can continue once it has settled.
- **Target FPS:** 30–240 FPS. This is a target, not a guarantee: it cannot reduce a game already running above target,
  exceed the selected ceiling, or overcome GPU/model/compositor limits.
- **Maximum Adaptive Multiplier:** Adaptive ceiling of 2x, 3x, or 4x; 3x is the default. Use 2x to prioritise image
  quality or 4x where the GPU headroom is available.
- **Smooth Cadence:** Disabled by default in Adaptive mode. When enabled, strict scheduling settles first and constant
  cadence is considered only when the target already needs nearly every matching cadence slot. It can make displayed
  motion more consistent, but may lower the real-frame presentation rate and feel less responsive. Leave it disabled
  for lower latency and stricter target scheduling. After a severe sustained slowdown, Adaptive briefly measures the
  real-only rate and either resumes fractional scheduling or tests one higher level when **Maximum Adaptive
  Multiplier** permits it. Rescue never exceeds that maximum and has a cooldown to avoid repeated switching.

Adaptive also has an automatic Steam-menu discontinuity safeguard, independent of **Smooth Cadence**. After a hard
cadence stall, it temporarily presents real frames, waits for the measured base cadence to remain healthy for one
second, and then restores the last proven generation level. If the old cadence does not recover within five seconds,
Adaptive discards that stale baseline and ramps again from zero. A sustained gameplay cadence drop instead stabilizes
for one second and rebases at the new measured rate, avoiding a five-second wait for an old rate that is no longer
achievable. This can briefly reduce displayed FPS after leaving a menu, but avoids treating its transient frame rate as
normal gameplay. Fixed mode does not use this policy.

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
- **Steam Deck Mode** and **MangoHud workaround:** Per-game compatibility paths.
- **Gamescope WSI Layer** and **Zink:** Optional paths for Gamescope and OpenGL games.

The plugin writes `pacing = 'none'` and does not expose general HDR or dual-GPU controls. See
[Troubleshooting](TROUBLESHOOTING.md) and the release notes for build-specific compatibility guidance.
