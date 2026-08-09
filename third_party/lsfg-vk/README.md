# Retained upstream lsfg-vk archives

This directory keeps exact upstream release assets in Git history as a recovery
copy if a historical GitHub release asset is later unavailable.

The Decky packager copies an explicit list of plugin files and does **not**
include this directory in the distributable ZIP. The runtime payload included
in a release ZIP remains the single archive declared and checksum-pinned in
`package.json`.

## v2.0.0-dev28-experimental.1

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.1`
- Source commit: `82e0d49976db8bce5e472fa154526e971529e091`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Source: `https://github.com/eugeniosegala/lsfg-vk-experimental/releases/download/v2.0.0-dev28-experimental.1/lsfg-vk-2.0.0-dev28-experimental.1-linux.tar.xz`
- SHA-256: `d447f6e821d76cffbcb003cfabdd81e1c7ea35c30d9c92c11ec498d4be28e9b2`

## v2.0.0-dev28-experimental.2

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.2`
- Source commit: `a05160d8ae97430ab5f77a2cfa7d3ea8aa4df854`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.2-linux.tar.xz`
- Host SHA-256: `a7f0056c873bc325f55c58acb7ca4e632957472b39575c6553482420cfa1ed48`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.2-flatpaks.tar.xz`
- Flatpak SHA-256: `15d3286c880afb14fe683e7b76baf40805028380a86fc56b43ea708296fc7fd4`

## v2.0.0-dev28-experimental.3

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.3`
- Source commit: `431c2f9395885ed9891443d7b1fc5dc4f4e15b14`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.3-linux.tar.xz`
- Host SHA-256: `6b0667b6118c935d0642b312e80d7573b43084e44dbf195f765bd7ecf6471bb8`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.3-flatpaks.tar.xz`
- Flatpak SHA-256: `cf8cfb1a43fecf789a0d3c08529a97524d63545a7e8ba1210b3d289297195748`
- Notes: Flatpak extension packaging hotfix. The manifest now points to the installed `lib64` layer path.
