# Decky LSFG-VK Experimental

<p align="center">
  <img src="assets/decky-lossless-logo-experimental.png" width="256" alt="Decky LSFG-VK Experimental logo" />
</p>

> **Experimental fork:** This independently developed fork of the original
> [Decky LSFG-VK](https://github.com/xXJSONDeruloXx/decky-lsfg-vk) plugin packages experimental changes from
> [lsfg-vk Experimental](https://github.com/eugeniosegala/lsfg-vk-experimental), with the explicit goal of pushing
> the library to its limits. It is not officially supported by the creators of Lossless Scaling or lsfg-vk.

> **Optional coexistence:** If you want to keep the original/public Decky LSFG-VK plugin installed, you can. Both
> plugins can remain installed and enabled. For native Steam/Proton games, choose exactly one launch wrapper: public
> `~/lsfg %command%` or experimental `~/.local/bin/lsfg-vk-experimental %command%`; never combine them. Flatpak apps,
> including Heroic, are selected through the plugin's Flatpak setup instead.

## What is this?

A Decky plugin that installs and configures a pinned experimental [lsfg-vk build](https://github.com/eugeniosegala/lsfg-vk-experimental)
frame-generation layer on SteamOS, Bazzite, and other Decky Loader-compatible Linux systems.

This experimental build pins `v2.0.0-dev28-experimental.1`, an immutable release from the experimental lsfg-vk fork.
Its upstream lineage is `v2.0.0-dev28`. It installs into a private experimental directory and activates only games
launched through its dedicated wrapper. Test it per game before relying on it. The exact release asset, checksum, and
integration record are documented in
[UPSTREAM_LSFGVK.md](UPSTREAM_LSFGVK.md).

> **Version-specific notes:** Check the [latest experimental release notes](https://github.com/eugeniosegala/decky-lsfg-vk-experimental/releases)
> for known issues and compatibility guidance for the bundled lsfg-vk build.

## How v2 differs from the older layer

This plugin packages `lsfg-vk 2.0.0-dev28-experimental.1`, a fork release based on upstream's dev28 v2 line. It is a
substantial evolution of the Linux/Vulkan layer, rather than a separate Lossless Scaling algorithm: both old and new
layers use the normal `Lossless.dll` installed by the Lossless Scaling Steam application.

- **Reworked Vulkan backend:** Upstream has reworked synchronization, resource reuse, VRAM handling, pipeline caching,
  and multi-instance/device handling. This is intended to improve robustness and efficiency, but game compatibility is
  still build-specific.
- **Per-game configuration:** Named profiles, automatic executable matching (`active_in`), and optional GPU/device
  selection make it easier to use different settings for different games.
- **Additional tooling:** v2 includes configuration validation and a frame-generation benchmark through `lsfg-vk-cli`,
  alongside an updated configuration UI.
- **Compatibility and runtime work:** The v2 line includes frame-pacing work and broader packaging/runtime support,
  including newer Flatpak runtimes and x86 compatibility fixes.
- **FP16:** v2 supports half-precision processing on compatible hardware, which can improve performance. The public
  Decky plugin's older `fp16-test-2` payload already contains an early FP16 build, so this is not unique to this fork.
- **Armada launch handling:** On Armada hosts, the generated launcher preserves the required game-launch wrapper used
  for FEX, controller, and runtime setup. This does not substitute an older ARM-only LSFG build for this fork's pinned
  v2 developer payload.

**Image-quality note:** In our testing, the v2 full-quality path with **Performance Mode disabled** can show
substantially less ghosting than the older build. Performance Mode remains useful when lower GPU overhead matters more
than image quality. This is an observed result, not a guarantee: test each game and use the public/original plugin if it
works better for that title.

For the upstream change history, see [v1.0.0 compared with the current development line](https://github.com/PancakeTAS/lsfg-vk/compare/v1.0.0...develop).

## Install and use

1. **Install Decky Loader** if it is not already installed. In Game Mode, choose **Steam** > **Power** >
   **Switch to Desktop**, then follow the [official Decky Loader installation guide](https://github.com/SteamDeckHomebrew/decky-loader#-installation).
   Choose **Latest Release** in the installer, then return to Game Mode.
2. **Install [Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/) from Steam.**
3. **Download this plugin** from [the releases page](https://github.com/eugeniosegala/decky-lsfg-vk-experimental/releases).
   Choose the asset ending in `.zip`, for example `Decky.LSFG-VK.Experimental-<version>.zip`.
4. **Install the ZIP through Decky.** In Game Mode, open the settings cog in the Decky Loader tab, enable
   **Developer Mode**, then choose **Developer** > **Install Plugin from Zip** and select the downloaded ZIP.
5. **Open the plugin** and select **Install Experimental LSFG-VK (developer build)** to set up this fork's private
   lsfg-vk Vulkan layer.
6. **Optionally adjust settings.** The defaults suit most setups; change the FPS multiplier, flow scale, performance
   mode, FP16 behaviour, or executable/GPU matching rules only when a game needs it.
7. **For native Steam/Proton games, add the launch option** `~/.local/bin/lsfg-vk-experimental %command%` in the
   game's Steam Properties, or use the plugin's **Launch Option Clipboard** button.
8. **Launch the game.** Frame generation will activate using the plugin configuration.

> **Coexistence:** This build does not register its layer in Vulkan's global user directory. Keep both Decky plugins
> installed if you wish, then choose the implementation per game with that plugin's launch wrapper. Do not use both
> wrappers in the same launch option.

> **Isolation tradeoff:** The experimental wrapper intentionally overrides Vulkan's implicit-layer search path so the
> public LSFG-VK layer cannot load alongside it. For that game, other globally installed implicit layers (for example
> vkBasalt) are also not discovered. Use the public plugin's wrapper for games that need those layers.

### Heroic and other Flatpak applications

The normal Steam launch wrapper cannot enter a Flatpak sandbox, so Heroic needs the **Flatpak Extensions** setup in
this plugin. This uses the same isolated experimental payload and configuration; it does not use the public plugin's
Flathub layer.

1. In the plugin, select **Flatpak Setup** near the bottom. This opens the **Flatpak Extensions** screen.
2. Under **Flatpak Applications**, try to prepare **Heroic**. If its matching runtime extension is not installed,
   the message below Heroic tells you exactly which version to install (for example, `25.08`). Install that version
   from the runtime buttons above, then prepare Heroic again. This grants Heroic access to the existing
   experimental wrapper, this plugin's configuration, and `Lossless.dll`; it does **not** enable frame generation for
   every Heroic game.
3. For each game you want to use LSFG-VK with, open that game's **Settings > Advanced** in Heroic and add a wrapper:

   - In Heroic's first **Wrapper** field, enter the absolute path shown for Heroic under **Flatpak Applications**. On a Steam Deck, use:

     ```text
     /home/deck/.local/bin/lsfg-vk-experimental
     ```

   - Leave **Arguments** empty.

   Do not use `%command%` in Heroic; it is only for Steam launch options. Heroic supplies the real game command
   automatically.
4. Start the game normally from Heroic or from its Steam shortcut. The wrapper is applied only to games configured in
   Heroic, regardless of where you start them.

The extension is installed once for that Flatpak runtime, not once per game. The experimental extension can remain
installed alongside the public one. If you switch Heroic back to the public plugin, remove this Wrapper command from
the affected game and configure that game through the public plugin instead.

The wrapper sets the experimental layer only for the selected game, keeping it isolated from the public layer and
other global implicit Vulkan layers.

If you change the configured `Lossless.dll` location, prepare Heroic again so its Flatpak permission is updated for
the new directory.

> **Flatpak isolation tradeoff:** Like the native experimental wrapper, Heroic launched through this setup does not
> discover vkBasalt or other global implicit Vulkan layers. This affects Heroic games only, not the rest of SteamOS.

### Updating the experimental plugin

Install a newer experimental ZIP **in place**; do not uninstall this plugin first.

1. Quit any game currently using `~/.local/bin/lsfg-vk-experimental`.
2. Download the newer ZIP from [this fork's releases](https://github.com/eugeniosegala/decky-lsfg-vk-experimental/releases).
3. In Game Mode, open Decky Loader's settings, then choose **Developer** > **Install Plugin from Zip** and select it.
4. Reload the plugin from Decky, or restart Game Mode if it does not reload automatically.
5. Open this plugin and select **Install Experimental LSFG-VK (developer build)**. This replaces this plugin's private
   LSFG-VK layer with the version bundled in the new ZIP.
6. If you use Heroic, select **Flatpak Setup**, then install the matching experimental runtime extension again.

Your experimental profiles and existing Steam launch options are retained. The engine files are deliberately replaced,
not stacked. Existing Heroic per-game Wrapper command settings also remain in place; prepare Heroic again only if you
changed the configured `Lossless.dll` location or disabled its Flatpak preparation.

### Use alongside the public plugin

Both plugins can remain installed. For each native Steam/Proton game, use exactly one launch option:

| To use                               | Steam launch option                           |
|--------------------------------------|-----------------------------------------------|
| Public/original Decky LSFG-VK plugin | `~/lsfg %command%`                            |
| This experimental plugin             | `~/.local/bin/lsfg-vk-experimental %command%` |

To switch a game, quit it and replace the command in **Steam Properties > Launch Options**. Do not combine both
wrappers.

The experimental plugin uses its own private manifest and configuration, so it does not overwrite the public plugin's
files. Its isolated launcher cannot discover vkBasalt or other globally installed implicit Vulkan layers, including
some overlay and post-processing layers. This affects only that game; use the public wrapper if it needs those layers.

The public and experimental Flatpak extensions are separate, so either can stay installed. Configure a given Flatpak
application through only one LSFG-VK plugin at a time.

## Configuration Options

The plugin provides several configuration options to optimize frame generation for your games:

### Core Settings

- **FPS Multiplier**: Choose 2x, 3x, or 4x frame generation. The minimum is 2x. The 0x/disabled choice
  available in the older v1 integration is not supported by lsfg-vk v2, so this plugin cannot restore it. Use
  **Disable Frame Generation** instead when you need to launch a game without frame generation.
- **Flow Scale**: Choose a value from 0.25 to 1.0 (lower generally favors performance; higher favors optical-flow
  quality).
- **Performance Mode**: Uses a lighter frame-generation model to reduce GPU overhead, at the cost of more visual artifacts.
- **Lossless.dll Path**: Override the detected DLL path, or leave it blank for upstream automatic discovery.
- **Allow FP16**: Permit half-precision processing when supported.
- **Disable Frame Generation**: Applies `DISABLE_LSFGVK=1` on the next Decky-generated launch. It cannot affect an already-running game; close the game, change the toggle, then launch it again.
- **Active In**: Optionally limit a profile to one or more executable/process names. When set, the launch script leaves
  selection to lsfg-vk's native automatic matching; otherwise it uses the profile selected in Decky.
- **GPU**: Optionally select the GPU identifier that lsfg-vk should use.

### Optional launch settings

- **Base FPS Cap**: Optionally caps the base framerate for DirectX games before the frame multiplier is applied.
- **WoW64**: Enables `PROTON_USE_WOW64=1` for compatible 32-bit games, primarily as a ProtonGE crash workaround.
- **Steam Deck Mode** and **MangoHud workaround**: Per-game compatibility options for cases where the normal launch
  path needs adjustment.
- **Gamescope WSI Layer** and **Zink**: Optional compatibility paths for Gamescope or OpenGL games.

This plugin currently writes only `pacing = 'none'` and does not expose HDR or dual-GPU controls. See the
[latest experimental release notes](https://github.com/eugeniosegala/decky-lsfg-vk-experimental/releases) for
build-specific compatibility notes.

## Create a local installation archive

Install pnpm and the JavaScript dependencies once, then run the local packager. If you use Volta, install pnpm with
`volta install pnpm`; otherwise, enable it with your preferred Node.js package-manager setup.

```bash
pnpm install --frozen-lockfile
pnpm run package:local
```

This creates `out/Decky.LSFG-VK.Experimental.zip`. The script regenerates configuration bindings, builds the frontend,
downloads the engine archive declared in `package.json`, verifies its SHA-256 checksum, and packages the files Decky
needs. Pass a path directly to use a different output location:

```bash
pnpm run package:local -- /path/to/Decky.LSFG-VK.Experimental.zip
```

## Publish a GitHub pre-release

After committing the version and release changes on a clean checkout, authenticate the GitHub CLI once with
`gh auth login -h github.com`, then run:

```bash
pnpm run package:publish
```

This verifies and builds the ZIP, creates or verifies the matching `v<package-version>` tag, pushes the current branch
and tag, generates Deck installation notes, and creates or updates the matching GitHub pre-release with the ZIP
attached. Publishing is opt-in; `pnpm run package:local` never pushes or changes GitHub.

The release version must be committed first. The script creates a new matching tag, or accepts an existing tag only
when it already points to the current commit; it never moves a published tag to newer code.

## Credits

- **[Kurt Himebauch / xXJSONDeruloXx](https://github.com/xXJSONDeruloXx/decky-lsfg-vk)** for creating the original
  Decky LSFG-VK plugin on which this experimental fork is based
- **[PancakeTAS](https://github.com/PancakeTAS/lsfg-vk)** for creating the lsfg-vk Vulkan compatibility layer
- **[Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/)** developers for the original frame
  generation technology
- **[Deck Wizard](https://www.youtube.com/@DeckWizard)**  - Extensive community support including comprehensive guides,
  promotional content, thorough testing and feedback, custom artworks, and tutorial videos. His passionate advocacy and
  continuous support have been instrumental in this plugin's success.
- The **Decky Loader** team for the plugin framework
- Community contributors and testers for feedback and bug reports
