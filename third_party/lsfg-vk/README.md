# Retained upstream lsfg-vk archives

This directory keeps exact upstream release assets in Git history as a recovery
copy if a historical GitHub release asset is later unavailable.

The Decky packager copies an explicit list of plugin files and does **not**
include this directory in the distributable ZIP. The runtime payload included
in a release ZIP remains the single archive declared and checksum-pinned in
`package.json`.

The current experimental archive carries the two changes documented in
[`UPSTREAM_LSFGVK.md`](../../UPSTREAM_LSFGVK.md): the mip-extent clamp and defensive null-memory handling from
[PancakeTAS/lsfg-vk PR #544](https://github.com/PancakeTAS/lsfg-vk/pull/544). The matching unmodified upstream archive
is retained under `v2.0.0-dev28/` for comparison and recovery.

## v2.0.0-dev28-experimental.1

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.1`
- Source commit: `82e0d49976db8bce5e472fa154526e971529e091`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Source: `https://github.com/eugeniosegala/lsfg-vk-experimental/releases/download/v2.0.0-dev28-experimental.1/lsfg-vk-2.0.0-dev28-experimental.1-linux.tar.xz`
- SHA-256: `d447f6e821d76cffbcb003cfabdd81e1c7ea35c30d9c92c11ec498d4be28e9b2`
