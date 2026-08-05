# lsfg-vk experimental integration log

This file is the hand-off point for future lsfg-vk updates. The canonical machine-readable payload pin is the sole
`remote_binary` record in [`package.json`](package.json); this document records the review context and update procedure.
Update both in the same commit.

## Current baseline

| Item                        | Value                                                                                                                                                 |
|-----------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| Release repository          | [`eugeniosegala/lsfg-vk-experimental`](https://github.com/eugeniosegala/lsfg-vk-experimental)                                                         |
| Tracked branch              | `develop`                                                                                                                                             |
| Last checked                | 2026-08-05                                                                                                                                            |
| Integrated source commit    | `82e0d49976db8bce5e472fa154526e971529e091`                                                                                                            |
| Commit date and subject     | 2026-08-05 — `docs: include v2 limits in release notes`                                                                                               |
| Experimental prerelease tag | `v2.0.0-dev28-experimental.1`                                                                                                                         |
| Upstream lineage            | [`PancakeTAS/lsfg-vk`](https://github.com/PancakeTAS/lsfg-vk) `2.0.0-dev28`                                                                           |
| Release asset               | `lsfg-vk-2.0.0-dev28-experimental.1-linux.tar.xz`                                                                                                     |
| Asset SHA-256               | `d447f6e821d76cffbcb003cfabdd81e1c7ea35c30d9c92c11ec498d4be28e9b2`                                                                                    |
| Asset URL                   | `https://github.com/eugeniosegala/lsfg-vk-experimental/releases/download/v2.0.0-dev28-experimental.1/lsfg-vk-2.0.0-dev28-experimental.1-linux.tar.xz` |
| Decky plugin version        | `0.13.0-experimental.13`                                                                                                                              |
| Decky plugin package ID     | `decky-lsfg-vk-experimental`                                                                                                                          |

The package is pinned to this release asset and SHA-256. The experimental fork's `develop` branch may advance
independently; do not treat newer commits as integrated until an immutable release asset, its checksum, and the
configuration changes have been reviewed.

## Included compatibility patch

The current payload includes the two changes proposed in upstream [PR #544](https://github.com/PancakeTAS/lsfg-vk/pull/544).
They prevent a zero-sized mip level from reaching Vulkan allocation and turn a null allocation handle into a normal
lsfg-vk error. This addresses the startup crash reported with Switch emulators that briefly create a very small Vulkan
swapchain before resizing.

| Upstream PR #544 commit | Included fork commit | Change |
|---|---|---|
| [`545f37a`](https://github.com/PancakeTAS/lsfg-vk/commit/545f37a58ca3ad37213ae84cc0a4fa4078def90a) | [`e250ca5`](https://github.com/eugeniosegala/lsfg-vk-experimental/commit/e250ca577c9a80776ffe0111b6ea54eafc8a67e2) | Clamp mip extents to at least 1. |
| [`f4f7444`](https://github.com/PancakeTAS/lsfg-vk/commit/f4f744429ac6362098e4ebd2d923e87e59d8171e) | [`5a49614`](https://github.com/eugeniosegala/lsfg-vk-experimental/commit/5a49614ef6e49ff4ed987513edc94e9e33689006) | Reject null memory handles returned by `vkAllocateMemory`. |

Verified on 2026-08-05: the changed-file patches for each upstream/fork pair are identical. The fork commit IDs differ
because the changes were carried into the experimental source repository, rather than merged from the upstream branch.
PR #544 was open against upstream `develop` when this review was performed. This is a targeted compatibility fix, not
a guarantee that every emulator or game will run correctly.

## Retained payloads in this repository

[`third_party/lsfg-vk/`](third_party/lsfg-vk/) retains both the unmodified upstream archive for `2.0.0-dev28` and the
patched experimental archive used by the plugin. Their SHA-256 values are recorded there and the patched archive has
been verified against the package pin above. The complete source remains in
[`eugeniosegala/lsfg-vk-experimental`](https://github.com/eugeniosegala/lsfg-vk-experimental); this repository retains
the distributable payloads and integration trail rather than duplicating a second working copy of the engine source.

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
   git -C /path/to/lsfg-vk-experimental log --oneline 82e0d49976db8bce5e472fa154526e971529e091..origin/develop
   ```

3. Review the fork's release notes, `docs/Configuration.md`, `docs/Flatpak-Guide.md`, release asset, and packaging
   script. Confirm the archive has the expected layer, manifest, and CLI filenames. Also check whether PR #544 has
   merged upstream or needs to remain carried explicitly.
4. Update the single `remote_binary` record in `package.json`. It is the canonical runtime pin used by both the local
   packager and the installed plugin. Update this document and `third_party/lsfg-vk/README.md` to match its release
   metadata; copy the reviewed archive into `third_party/lsfg-vk/` when retaining a Git-backed recovery copy.
5. Regenerate the schemas with `python3 scripts/generate_ts_schema.py`, then build the frontend with `pnpm run build`.
6. Build a local Decky ZIP and verify its embedded archive checksum before publishing a new Decky prerelease.

## Scope note

This tracks releases from `eugeniosegala/lsfg-vk-experimental`. PancakeTAS remains the upstream project and should be
credited for lsfg-vk, but a PancakeTAS branch commit is not considered bundled until this fork publishes and Decky pins
a reviewed immutable asset.
