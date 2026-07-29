# Decky LSFG-VK Experimental

> **Experimental fork:** This is a fork of the original [Decky LSFG-VK](https://github.com/xXJSONDeruloXx/decky-lsfg-vk) plugin. It carries experimental features and tracks the latest reviewed `develop` release of [lsfg-vk](https://github.com/PancakeTAS/lsfg-vk). It is independently developed and not officially supported by the creators of Lossless Scaling or lsfg-vk.

## What is this?

A Decky plugin that installs and configures the current [lsfg-vk](https://github.com/PancakeTAS/lsfg-vk) frame-generation layer on Steam Deck. It provides a controller-friendly interface for SteamOS, Bazzite, and other Decky Loader-compatible Linux systems.

This experimental build pins upstream release `v2.0.0-dev28`. It installs into a private experimental directory and
activates only games launched through its dedicated wrapper, so it can coexist with the public Decky LSFG-VK plugin.
Test it per game before relying on it.

## Installation

1. **Download the plugin** from [this fork's releases](https://github.com/eugeniosegala/decky-lsfg-vk-experimental/releases)
   - Download the `Decky.LSFG-VK.Experimental.zip` file to your Steam Deck
2. **Install manually through Decky**:
   - In Game Mode, go to the settings cog in the top right of the Decky Loader tab
   - Enable "Developer Mode"
   - Go to "Developer" tab and select "Install Plugin from Zip"
   - Select the downloaded `Decky LSFG-VK Experimental.zip` file

> **Coexistence:** This build does not register its layer in Vulkan's global user directory. Keep both Decky plugins
> installed if you wish, then choose the implementation per game with that plugin's launch wrapper. Do not use both
> wrappers in the same launch option.

> **Isolation tradeoff:** The experimental wrapper intentionally overrides Vulkan's implicit-layer search path so the
> public LSFG-VK layer cannot load alongside it. For that game, other globally installed implicit layers (for example
> vkBasalt) are also not discovered. Use the public plugin's wrapper for games that need those layers.

## Create a local install archive

Install the JavaScript dependencies once, then run the local packager:

```bash
corepack pnpm install --frozen-lockfile
just package-release
```

This creates `out/Decky.LSFG-VK.Experimental.zip`. The script regenerates configuration bindings, builds the frontend, downloads the engine archive declared in `package.json`, verifies its SHA-256 checksum, and packages the files Decky needs. Pass a path directly to use a different output location:

```bash
scripts/package-release.sh /path/to/Decky.LSFG-VK.Experimental.zip
```

## Publish a GitHub pre-release

After committing the version and release changes on a clean checkout, authenticate the GitHub CLI once with
`gh auth login -h github.com`, then run:

```bash
scripts/package-release.sh --publish
```

This verifies and builds the ZIP, creates or verifies the matching `v<package-version>` tag, pushes the current
branch and tag, generates Deck installation notes, and creates or updates the matching GitHub pre-release with the
ZIP attached. Publishing is opt-in; a normal packaging command never pushes or changes GitHub.

## How to Use

1. **Purchase and install** [Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/) from Steam
2. **Open the plugin** from the Decky menu
3. **Click "Install lsfg-vk"** to automatically set up the lsfg-vk vulkan layer
4. **Configure settings** using the plugin's UI — choose an FPS multiplier, flow scale, performance mode, FP16 behavior, and optional executable/GPU matching rules
5. **Apply launch option** to games you want to use frame generation with:
   - Add `~/.local/bin/lsfg-vk-experimental %command%` to your game's launch options in Steam Properties
   - Or use the "Launch Option Clipboard" button in the plugin to copy the command
6. **Launch your game** - frame generation will activate automatically using your plugin configuration

### Coexisting with the public plugin

For native Steam/Proton games, both plugins can stay installed and active. Select exactly one launcher per game:

- Public plugin: its existing `~/lsfg %command%` launch option
- Experimental plugin: `~/.local/bin/lsfg-vk-experimental %command%`

The experimental launcher uses a private manifest and config, so its configuration changes and uninstall operation do
not overwrite the public plugin's layer files. Its isolation mode bypasses the usual implicit-layer directories, so do
not use it for a game that needs vkBasalt or another global implicit layer.

Flatpak runtime extensions are shared by design. The experimental plugin uses its own config for Flatpak overrides,
but configure a particular Flatpak app through only one LSFG-VK plugin at a time.

### Switching a game between plugins

The choice is made entirely in that game's **Steam Properties → Launch Options**. Quit the game, then replace the
LSFG-VK launcher command with the other one; do not combine them.

| To use | Steam launch option |
| --- | --- |
| Public/original Decky LSFG-VK plugin | `~/lsfg %command%` |
| This experimental plugin | `~/.local/bin/lsfg-vk-experimental %command%` |

For example, to move a game from the experimental plugin back to the public plugin, replace
`~/.local/bin/lsfg-vk-experimental %command%` with `~/lsfg %command%`, then launch the game normally. Switch back by
replacing it in the opposite direction. Configure FPS multiplier, flow scale, and other settings in the Decky plugin
you selected; each plugin keeps its own configuration.

### What the isolated per-game launcher does

`~/.local/bin/lsfg-vk-experimental` is a small launcher script installed **once**, not a separate lsfg-vk installation
for every game. When Steam starts a game through it, the script temporarily points that game process at this plugin's
single private lsfg-vk library, Vulkan manifest, and configuration, then starts `%command%` (Steam's placeholder for
the real game command). The same private installation is reused by every game that has the experimental launch option.

This is why it is called *per-game isolation*: the launch option chooses which already-installed plugin a particular
game sees. It does not duplicate the Vulkan layer or Lossless Scaling files per game, and it does not make a persistent
system-wide Vulkan change. Closing the game removes the temporary environment settings automatically.

## Configuration Options

The plugin provides several configuration options to optimize frame generation for your games:

### Core Settings
- **FPS Multiplier**: Choose 2x, 3x, or 4x frame generation. The minimum is 2x.
- **Flow Scale**: Choose a value from 0.25 to 1.0 (lower generally favors performance; higher favors optical-flow quality).
- **Performance Mode**: Uses a lighter processing model.
- **Lossless.dll Path**: Override the detected DLL path, or leave it blank for upstream automatic discovery.
- **Allow FP16**: Permit half-precision processing when supported.
- **Disable Frame Generation**: Temporarily exports upstream's `DISABLE_LSFGVK=1` for Decky-generated launches.
- **Active In**: Optionally limit a profile to one or more executable/process names. When set, the launch script leaves selection to lsfg-vk's native automatic matching; otherwise it uses the profile selected in Decky.
- **GPU**: Optionally select the GPU identifier that lsfg-vk should use.

The current upstream build supports only `pacing = 'none'`; it forces FIFO presentation. HDR and dual-GPU operation are not currently available, so the plugin does not expose controls for them.

## Feedback and Support

For per-game feedback and community support, please join the [decky-lsfg-vk Discord Channel](https://discord.gg/TwvHdVucC3)

## Troubleshooting

**Frame generation not working?**
- Ensure you've added `~/.local/bin/lsfg-vk-experimental %command%` to your game's launch options
- Check that the Lossless Scaling DLL was detected correctly in the plugin
- Try enabling Performance Mode if you're experiencing crashes
- Make sure your game is using a supported Vulkan presentation path
- HDR is currently unsupported upstream; turn HDR off while testing

**Performance issues?**
- Lower the Flow Scale setting for better performance
- Enable Performance Mode (recommended for most games)
- Try reducing the FPS multiplier from 4x to 2x or 3x
- Consider using the experimental FPS limit feature for DirectX games

## What it does

The plugin:
- Automatically downloads and installs its lsfg-vk layer to `~/.local/share/decky-lsfg-vk-experimental/`
- Keeps its manifest out of Vulkan's global implicit-layer directory and exports `VK_IMPLICIT_LAYER_PATH` only from its wrapper
- Creates a TOML configuration file in `~/.config/decky-lsfg-vk-experimental/conf.toml` with your settings
- Automatically detects your Lossless Scaling DLL installation
- Provides an easy-to-use interface to configure frame generation settings:
  - **FPS Multiplier**: Choose 2x, 3x, or 4x frame generation
  - **Flow Scale**: Adjust motion estimation quality vs performance
  - **Performance Mode**: Use lighter processing for better performance
  - **Allow FP16**, executable matching, and optional GPU selection
- Writes the current lsfg-vk TOML configuration format, including named profiles
- Uses the upstream `LSFGVK_CONFIG` and `LSFGVK_PROFILE` launch environment variables without overriding `active_in` matching
- Configures Flatpak applications with this plugin's private config and Lossless Scaling filesystem access; Flatpak runtime extensions remain shared system resources, so configure a given Flatpak app through only one plugin
- Easy uninstallation that removes all installed files when no longer needed

## Credits

- **[PancakeTAS](https://github.com/PancakeTAS/lsfg-vk)** for creating the lsfg-vk Vulkan compatibility layer
- **[Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/)** developers for the original frame generation technology
- **[Deck Wizard](https://www.youtube.com/@DeckWizard)**  - Extensive community support including comprehensive guides, promotional content, thorough testing and feedback, custom artworks, and tutorial videos. His passionate advocacy and continuous support have been instrumental in this plugin's success.
- The **Decky Loader** team for the plugin framework
- Community contributors and testers for feedback and bug reports
