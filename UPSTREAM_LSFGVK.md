# lsfg-vk upstream integration log

This file is the hand-off point for future lsfg-vk updates. Update the **Current baseline** section in the same commit
that updates the bundled upstream payload.

## Current baseline

| Item                       | Value                                                                                                 |
|----------------------------|-------------------------------------------------------------------------------------------------------|
| Upstream repository        | [`PancakeTAS/lsfg-vk`](https://github.com/PancakeTAS/lsfg-vk)                                         |
| Tracked branch             | `develop`                                                                                             |
| Last checked               | 2026-07-29                                                                                            |
| Integrated upstream commit | `8b0da2661c6f3473a7fccc8ba643880050e71642`                                                            |
| Commit date and subject    | 2026-06-28 — `fix: fix: Unset HDR enabled property entirely`                                          |
| Upstream prerelease tag    | `v2.0.0-dev`                                                                                          |
| Release asset              | `lsfg-vk-2.0.0-dev28-linux.tar.xz`                                                                    |
| Asset SHA-256              | `bb2b691939fc6c51888b10349345a3c0ae9ad0b5c3892fd7859d0cdf697b734e`                                    |
| Asset URL                  | `https://github.com/PancakeTAS/lsfg-vk/releases/download/v2.0.0-dev/lsfg-vk-2.0.0-dev28-linux.tar.xz` |
| Decky plugin version       | `0.13.0-experimental.6`                                                                               |
| Decky plugin package ID    | `decky-lsfg-vk-experimental`                                                                          |

The package is pinned to this release asset and SHA-256. The `develop` branch may advance independently; do not treat
newer branch commits as integrated until their release asset and configuration changes have been reviewed.

## Decky integration commits

- `b846c9aa4834213122533bea4134904f9081fc7b` — core installer, configuration, launcher, UI, and documentation update.
- `d52acde3131ea7f4a71764d58254dd46eb35d213` — automatic profile matching, Flatpak overrides, and disable switch.
- `15c21ac748ceb22b615f7fdc10e4ee391bcd3f00` — editable Lossless.dll path in the Decky UI.

## Next update procedure

1. Fetch the upstream branch and tags:

   ```bash
   git -C /path/to/lsfg-vk fetch origin develop --tags
   ```

2. Compare from the baseline commit above:

   ```bash
   git -C /path/to/lsfg-vk log --oneline 8b0da2661c6f3473a7fccc8ba643880050e71642..origin/develop
   ```

3. Review upstream `docs/Configuration.md`, `docs/Flatpak-Guide.md`, the release asset, and the packaging workflow.
   Update `package.json` and `py_modules/lsfg_vk/constants.py` if the asset name, URL, checksum, manifest, or layer
   filename changed.
4. Regenerate the schemas with `python3 scripts/generate_ts_schema.py`, then build the frontend with `pnpm run build`.
5. Update this file's checked date, commit, release, asset checksum, and integration-commit list in the same commit as
   the upgrade.

## Scope note

This tracks only upstream's merged `develop` branch. Do not treat unmerged experimental branches as release-parity
requirements unless they are explicitly brought into `develop`.
