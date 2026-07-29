# Decky LSFG-VK Experimental

> **Experimental fork:** This is a fork of the original [Decky LSFG-VK](https://github.com/xXJSONDeruloXx/decky-lsfg-vk) plugin. It carries experimental features and tracks the latest reviewed `develop` release of [lsfg-vk](https://github.com/PancakeTAS/lsfg-vk). It is independently developed and not officially supported by the creators of Lossless Scaling or lsfg-vk.


<p align="center">
   <img src="assets/decky-lossless-logo.png" alt="decky-lsfg-vk Logo" width="200"/>
</p>
<p align="center">
   <a href="https://ko-fi.com/B0B71HZTAX" target="_blank" rel="noopener noreferrer">
      <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support on Ko-fi"/>
   </a>
</p>


## What is this?

A Decky plugin that installs and configures the **lsfg-vk v2** ([Lossless Scaling Frame Generation Vulkan layer](https://github.com/PancakeTAS/lsfg-vk)) on Steam Deck. It provides a controller-friendly interface for SteamOS, Bazzite, and other Decky Loader-compatible Linux systems.

This preview pins the upstream `v2.0.0-dev28` release. It is a development build of lsfg-vk, so expect to test it per game before relying on it.

## Installation

1. **Download the plugin** from [this fork's releases](https://github.com/eugeniosegala/decky-lsfg-vk/releases)
   - Download the `Decky LSFG-VK Experimental.zip` file to your Steam Deck
2. **Install manually through Decky**:
   - In Game Mode, go to the settings cog in the top right of the Decky Loader tab
   - Enable "Developer Mode"
   - Go to "Developer" tab and select "Install Plugin from Zip"
   - Select the downloaded `Decky LSFG-VK Experimental.zip` file

> **Coexistence:** Decky will show this as a separate plugin from the public release. Both plugins manage the same system-wide lsfg-vk Vulkan layer, however, so use only one lsfg-vk version at a time.

## How to Use

1. **Purchase and install** [Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/) from Steam
2. **Open the plugin** from the Decky menu
3. **Click "Install lsfg-vk"** to automatically set up the lsfg-vk vulkan layer
4. **Configure settings** using the plugin's UI — choose a v2 FPS multiplier, flow scale, performance mode, FP16 behavior, and optional executable/GPU matching rules
5. **Apply launch option** to games you want to use frame generation with:
   - Add `~/lsfg %command%` to your game's launch options in Steam Properties
   - Or use the "Launch Option Clipboard" button in the plugin to copy the command
6. **Launch your game** - frame generation will activate automatically using your plugin configuration

## Configuration Options

The plugin provides several configuration options to optimize frame generation for your games:

### Core Settings
- **FPS Multiplier**: Choose 2x, 3x, or 4x frame generation. v2 requires at least 2x.
- **Flow Scale**: Choose a value from 0.25 to 1.0 (lower generally favors performance; higher favors optical-flow quality).
- **Performance Mode**: Uses a lighter processing model.
- **Lossless.dll Path**: Override the detected DLL path, or leave it blank for upstream automatic discovery.
- **Allow FP16**: Permit v2 to use half-precision processing when supported.
- **Disable Frame Generation**: Temporarily exports upstream's `DISABLE_LSFGVK=1` for Decky-generated launches.
- **Active In**: Optionally limit a profile to one or more executable/process names. When set, the launch script leaves selection to lsfg-vk's native automatic matching; otherwise it uses the profile selected in Decky.
- **GPU**: Optionally select the GPU identifier that lsfg-vk should use.

The current upstream v2 `develop` line supports only `pacing = 'none'`; it forces FIFO presentation. HDR and dual-GPU operation are not currently supported by upstream v2, so this plugin deliberately does not expose the old controls.

## Feedback and Support

For per-game feedback and community support, please join the [decky-lsfg-vk Discord Channel](https://discord.gg/TwvHdVucC3)

## Troubleshooting

**Frame generation not working?**
- Ensure you've added `~/lsfg %command%` to your game's launch options
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
- Automatically downloads and installs the latest lsfg-vk Vulkan layer to `~/.local/lib/`
- Configures the Vulkan layer in `~/.local/share/vulkan/implicit_layer.d/`
- Creates a TOML configuration file in `~/.config/lsfg-vk/conf.toml` with your settings
- Automatically detects your Lossless Scaling DLL installation
- Provides an easy-to-use interface to configure frame generation settings:
  - **FPS Multiplier**: Choose 2x, 3x, or 4x frame generation
  - **Flow Scale**: Adjust motion estimation quality vs performance
  - **Performance Mode**: Use lighter processing for better performance
  - **Allow FP16**, executable matching, and optional GPU selection
- Writes the lsfg-vk **v2** `version = 2` TOML configuration format, including named profiles
- Uses the upstream `LSFGVK_CONFIG` and `LSFGVK_PROFILE` launch environment variables without overriding `active_in` matching
- Configures Flatpak applications with v2's required config and Lossless Scaling filesystem access; extension installation through Flathub is available for Freedesktop runtimes 24.08 and 25.08
- Easy uninstallation that removes all installed files when no longer needed

## Credits

- **[PancakeTAS](https://github.com/PancakeTAS/lsfg-vk)** for creating the lsfg-vk Vulkan compatibility layer
- **[Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/)** developers for the original frame generation technology
- **[Deck Wizard](https://www.youtube.com/@DeckWizard)**  - Extensive community support including comprehensive guides, promotional content, thorough testing and feedback, custom artworks, and tutorial videos. His passionate advocacy and continuous support have been instrumental in this plugin's success.
- The **Decky Loader** team for the plugin framework
- Community contributors and testers for feedback and bug reports
