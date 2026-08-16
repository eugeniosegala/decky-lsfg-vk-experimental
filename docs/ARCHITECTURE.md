# Architecture

## Purpose and boundaries

Decky LSFG-VK Experimental is a Decky Loader plugin that installs and controls
a private, checksum-pinned experimental lsfg-vk engine. The repository contains
the Decky UI and Python management layer, not the native Vulkan engine source.
Native and Flatpak engine artifacts are produced by the linked experimental
engine repository and embedded during packaging.

The current release keeps experimental HDR exposure disabled. It supports
coexistence with the public Decky LSFG-VK plugin, but each game must use exactly
one launch wrapper.

## Runtime shape

```text
Decky Loader
  -> src/index.tsx
  -> src/components/Content.tsx
  -> hooks and typed callables in src/api/lsfgApi.ts
  -> main.py
  -> py_modules/lsfg_vk/plugin.py
  -> installation / configuration / DLL detection / Flatpak services
  -> private files under the user's ~/.local and ~/.config directories
```

The frontend renders installation status, configuration, profiles, Flatpak
setup, launch-option clipboard helpers, and diagnostics. The Python `Plugin`
class exposes matching callable methods and delegates filesystem/subprocess work
to focused services.

## Configuration contract

`shared_config.py` is the source of truth for fields, types, and defaults.
`scripts/generate_ts_schema.py` generates:

- `src/config/generatedConfigSchema.ts`
- `py_modules/lsfg_vk/config_schema_generated.py`

Configuration is stored as named profiles in TOML. The backend validates field
types, validates new/renamed profile names, and generates a quoted
launch wrapper. The frontend merges generated defaults when reading older
backend data so newly introduced fields have predictable values.

## Installation and isolation

The packaged plugin contains exactly one host engine archive record in
`package.json`. Installation:

1. reads the versioned archive metadata;
2. verifies the archive SHA-256;
3. accepts only expected archive member paths;
4. stages files in a temporary directory;
5. requires the 64-bit layer and optionally installs the 32-bit layer;
6. verifies the experimental build marker in layer binaries;
7. rewrites manifests to the private experimental identity and absolute paths;
8. creates the launcher, diagnostics helper, config, and installed-engine state.

The launcher enables the private experimental layer and disables known public
LSFG identities for that process. Uninstall removes plugin-owned engine files,
manifests, helpers, and state while retaining user profiles and shared Flatpak
runtime extensions.

## Flatpak boundary

Flatpak operations use argv-based subprocess execution rather than shell
interpolation. Runtime extensions are supported for the pinned Freedesktop
branches, and per-app overrides grant access to the wrapper, configuration, and
the configured DLL directory. Real Flatpak and Gamescope behavior requires a
SteamOS/Bazzite integration target; macOS and generic CI can only validate pure
logic and command construction.

## Build and packaging

`scripts/build-frontend.mjs` validates locale key parity, fallbacks,
placeholders, static translation calls, and unused keys before Rollup builds the
frontend.

`scripts/package-local.sh` regenerates bindings, runs backend tests, builds the
frontend, downloads checksum-pinned host/Flatpak payloads, validates architecture
paths and experimental layer identity, assembles the Decky ZIP, and checks
archive integrity.

`scripts/publish-package.sh` additionally requires a clean worktree before and
after packaging, validates release metadata and tag ancestry, creates/pushes a
tag, and publishes a GitHub prerelease. It is intentionally excluded from CI.

## Verification

- `pnpm check` — full non-publishing local/PR gate; regenerates configuration
  bindings, validates the pinned payload manifest, and fails if either the
  bindings or generated translation bundle drift.
- `pnpm test` — current Python unit suite.
- `pnpm typecheck` — strict TypeScript check.
- `pnpm run build` — i18n validation and production frontend bundle.
- `pnpm run package:local` — networked package verification.

The current unit suite focuses on the launch-wrapper environment,
dual-architecture installation, and diagnostics. Flatpak operations, DLL
detection, profile CRUD, RPC behavior, and frontend components remain the main
coverage gaps.
