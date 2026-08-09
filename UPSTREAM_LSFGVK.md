# lsfg-vk experimental integration log

This file is the hand-off point for future lsfg-vk updates. The canonical machine-readable payload pin is the sole
`remote_binary` record in [`package.json`](package.json); this document records the review context and update procedure.
Update both in the same commit.

## Current baseline

| Item                        | Value                                                                                                                                                 |
|-----------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| Release repository          | [`eugeniosegala/lsfg-vk-experimental`](https://github.com/eugeniosegala/lsfg-vk-experimental)                                                         |
| Tracked branch              | `develop`                                                                                                                                             |
| Last checked                | 2026-08-08                                                                                                                                            |
| Integrated source commit    | `a05160d8ae97430ab5f77a2cfa7d3ea8aa4df854`                                                                                                            |
| Commit date and subject     | 2026-08-08 — `release: package experimental Flatpak extensions`                                                                                       |
| Experimental prerelease tag | `v2.0.0-dev28-experimental.2`                                                                                                                         |
| Upstream lineage            | [`PancakeTAS/lsfg-vk`](https://github.com/PancakeTAS/lsfg-vk) `2.0.0-dev28`                                                                           |
| Release asset               | `lsfg-vk-2.0.0-dev28-experimental.2-linux.tar.xz`                                                                                                     |
| Asset SHA-256               | `a7f0056c873bc325f55c58acb7ca4e632957472b39575c6553482420cfa1ed48`                                                                                    |
| Asset URL                   | `https://github.com/eugeniosegala/lsfg-vk-experimental/releases/download/v2.0.0-dev28-experimental.2/lsfg-vk-2.0.0-dev28-experimental.2-linux.tar.xz` |
| Flatpak archive             | `lsfg-vk-2.0.0-dev28-experimental.2-flatpaks.tar.xz`                                                                                                  |
| Flatpak SHA-256             | `15d3286c880afb14fe683e7b76baf40805028380a86fc56b43ea708296fc7fd4`                                                                                    |
| Decky plugin version        | `0.13.0-experimental.14` (prepared locally; not yet released)                                                                                         |
| Decky plugin package ID     | `decky-lsfg-vk-experimental`                                                                                                                          |

The package is pinned to this release asset and SHA-256. The experimental fork's `develop` branch may advance
independently; do not treat newer commits as integrated until an immutable release asset, its checksum, and the
configuration changes have been reviewed.

## Integrated Flatpak support

Engine prerelease `v2.0.0-dev28-experimental.2` adds separate experimental Flatpak runtime extensions for 23.08, 24.08,
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

The Decky release remains pending. Do not change the engine URL or checksums without publishing a new immutable engine
release and repeating package verification.

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
   git -C /path/to/lsfg-vk-experimental log --oneline a05160d8ae97430ab5f77a2cfa7d3ea8aa4df854..origin/develop
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
