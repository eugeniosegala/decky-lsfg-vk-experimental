# Decky LSFG-VK Experimental

<p align="center">
  <img src="assets/decky-lossless-logo-experimental.png" width="256" alt="Decky LSFG-VK Experimental logo" />
</p>

> **Experimental fork:** This independently developed fork of the original
> [Decky LSFG-VK](https://github.com/xXJSONDeruloXx/decky-lsfg-vk) plugin packages the fast-moving
> [lsfg-vk Experimental](https://github.com/eugeniosegala/lsfg-vk-experimental) engine for SteamOS, Bazzite, and
> other Decky Loader-compatible Linux systems. Test it per game; it is not an official release from Lossless Scaling
> or lsfg-vk.

> **Optional coexistence:** You can keep the public/original Decky LSFG-VK plugin installed. Choose exactly one
> launcher for each native Steam/Proton game: public `~/lsfg %command%` or experimental
> `~/.local/bin/lsfg-vk-experimental %command%`. Never combine them. Heroic and other Flatpak games are selected
> through this plugin's Flatpak setup.

## ✨ Experimental highlights

|    | Highlight                       | What it brings                                                                                                                                                                                                                                                                                        |
|:--:|---------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 🖼️ | **Improved full-quality image** | In testing, v2 with **Performance Mode disabled** can show noticeably less ghosting than the older layer. Results remain game-dependent; Performance Mode is still useful when lower GPU overhead matters more than image quality.                                                                    |
| ⏯️ | **Live frame-generation switch** | Turn frame generation on or off immediately without changing the selected Fixed or Adaptive settings. Turn it back on to resume with the same profile.                                                                                                                                                |
| 🎯 | **Adaptive Frame Generation**   | Optionally target 30–240 FPS while the layer varies generated frames up to a selected 2x–4x ceiling. It is disabled by default while it continues to be refined.                                                                                                                                      |
| 🛡️ | **Gamescope recovery**          | Bounded presentation recovery preserves proven Adaptive state, ignores transient Steam-menu cadence, refreshes history, and resumes only after the game cadence is stable again. A validated 2x Adaptive setup also recovers from short gameplay hitches without entering the longer menu/focus path. |
| 🎮 | **Per-game Heroic support**     | Use the experimental layer only for the Heroic games you choose, with the same private configuration and engine as native Steam games.                                                                                                                                                                |

## What it is

This plugin installs a private, checksum-verified lsfg-vk v2 engine and activates it only through its experimental
launcher. It uses the normal `Lossless.dll` from the Lossless Scaling Steam application; it does not install, copy, or
modify that DLL.

The currently pinned engine, source commit, checksum, and upstream change record are in
[UPSTREAM_LSFGVK.md](UPSTREAM_LSFGVK.md). Check the
[latest experimental release notes](https://github.com/eugeniosegala/decky-lsfg-vk-experimental/releases) for
build-specific known issues.

## Install and use

1. **Install Decky Loader** if needed: switch to Desktop Mode and follow the
   [official Decky Loader installation guide](https://github.com/SteamDeckHomebrew/decky-loader#-installation), then
   return to Game Mode.
2. **Install [Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/) from Steam.**
3. **Download this plugin ZIP** from [Releases](https://github.com/eugeniosegala/decky-lsfg-vk-experimental/releases).
4. In Decky's settings cog, enable **Developer Mode**, then select **Developer > Install Plugin from Zip**.
5. Open this plugin and select **Install Experimental LSFG-VK (developer build)**. This required step installs the
   engine bundled in the ZIP into the plugin's private location.
6. Leave the defaults in place unless a game needs adjustment. Fixed 2x remains the default; Adaptive Frame Generation
   is optional.
7. For a native Steam/Proton game, add this to **Steam Properties > Launch Options**:

   ```text
   ~/.local/bin/lsfg-vk-experimental %command%
   ```

8. Start the game normally.

> [!IMPORTANT]
> If Decky does not show or reload the plugin after installing a ZIP, uninstall **this experimental plugin** from
> Decky, install the ZIP again, then restart your Steam Deck or Steam Machine. Afterwards, repeat step 5.

### Heroic and other Flatpak applications

The Steam launch wrapper cannot enter a Flatpak sandbox, so configure Heroic through **Flatpak Setup**:

1. Select **Flatpak Setup** in the plugin.
2. Under **Flatpak Applications**, prepare **Heroic**. If the matching runtime extension is missing, the message tells
   you which runtime to install, commonly **25.08**. Preparing Heroic grants access to the wrapper, configuration, and
   `Lossless.dll`; it does not enable frame generation for every Heroic game.
3. In every Heroic game you want to enable, open **Settings > Advanced** and set the first **Wrapper** field to:

   ```text
   /home/deck/.local/bin/lsfg-vk-experimental
   ```

   Leave **Arguments** empty. Do not use `%command%` in Heroic.
4. Start that game normally from Heroic or its Steam shortcut.

The wrapper applies only to the selected Heroic games. It uses the isolated experimental Flatpak layer, so those games
cannot discover vkBasalt or other globally installed implicit Vulkan layers.

> [!IMPORTANT]
> After installing a newer experimental plugin ZIP, return to **Flatpak Setup** and select **Update** for Heroic's
> matching runtime extension, commonly **25.08**. This replaces Heroic's Flatpak engine with the version bundled in
> the ZIP. Your Heroic preparation and per-game Wrapper commands remain in place.

### Updating

Install a newer ZIP **in place**; do not normally uninstall the plugin first.

1. Quit games using the experimental wrapper, then install the newer ZIP through **Developer > Install Plugin from
   Zip**.
2. Reload the plugin. If it does not reload, restart your Steam Deck or Steam Machine.
3. **Required:** select **Install Experimental LSFG-VK (developer build)** to replace the private native engine with the
   version bundled in the ZIP.
4. If you use Heroic, open **Flatpak Setup** and select **Update** for Heroic's matching runtime extension, usually
   **25.08**. This updates its Flatpak engine without changing Heroic preparation or per-game Wrapper commands.

Profiles, Steam launch options, and Heroic Wrapper commands are retained. If Decky fails to load the update, use the
reinstall-and-restart fallback above, then repeat the required engine-install step.

## Documentation

- [Configuration guide](docs/CONFIGURATION.md): fixed and Adaptive modes, quality/performance settings, profiles, and
  compatibility options.
- [Troubleshooting](docs/TROUBLESHOOTING.md): Gamescope recovery behaviour, the per-game recovery fallback, and
  diagnostic logs.
- [Local packaging and publishing](docs/PACKAGING.md): build a ZIP for a Steam machine or publish a prerelease.
- [Upstream engine record](UPSTREAM_LSFGVK.md): pinned source, checksums, and carried changes.

## Featured In

Community creators have covered and tested this experimental plugin on Steam Deck hardware. See
[Featured In](docs/FEATURED_IN.md) for video links, channels, and coverage details.

## Credits

- **[Kurt Himebauch / xXJSONDeruloXx](https://github.com/xXJSONDeruloXx/decky-lsfg-vk)** for the original Decky LSFG-VK
  plugin on which this experimental fork is based
- **[PancakeTAS](https://github.com/PancakeTAS/lsfg-vk)** for creating the lsfg-vk Vulkan compatibility layer
- **[Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/)** developers for the original
  frame-generation technology
- **[Deck Wizard](https://www.youtube.com/@DeckWizard)** for community support, guides, testing, feedback, artwork, and
  tutorials
- The **Decky Loader** team and community contributors and testers
