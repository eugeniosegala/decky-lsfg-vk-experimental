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
the configured DLL directory. A per-app change is issued as one multi-option
Flatpak command, but is not treated as atomic: the backend always performs a
strict read-back and reports `complete`, `partial`, `failed`, `rejected`, or
`unverified`. The UI never turns an unavailable read into a false/off state,
refreshes after every mutation attempt, and offers explicit repair/removal
actions for partial state. The observed contract distinguishes exact-path
presence from access-mode readiness: preparing requires config `rw` and
payload/wrapper `ro`.

Flatpak does not provide a stable per-key reset API. The plugin therefore keeps
a mode-`0600` ownership ledger in its configuration directory and writes a
durable pending intent before invoking an external override mutation. Only
paths proven absent at the app override layer are recorded as plugin-owned.
Correct pre-existing grants are retained but never claimed; wrong modes,
explicit denials, legacy environment values/unsets, corrupt ownership state,
or external drift fail closed without an automatic cleanup command. Removal
targets only exact grants recorded as plugin-owned and succeeds only after
read-back proves those app-layer entries absent. A denial or mixed state leaves
the durable intent pending/blocked for repair rather than reporting success.

The UI distinguishes prepared, partial, retained pre-existing, unknown,
pending, and blocked state. It never offers ordinary removal for unowned or
unknown access. Neither `--unset-env` nor Flatpak's broad `--reset` is used for
automatic cleanup because either could alter unrelated user or lower-layer
configuration.

The PR workflow also runs an isolated real Flatpak CLI integration suite on a
Linux VM. It uses temporary `HOME` and XDG roots to verify production
add/read-back/remove behavior, pre-existing grant preservation, access modes,
partial-command reconciliation, and DLL path changes against Flatpak's actual
user override keyfiles. It does not install or launch a game and never touches
the runner's normal user overrides.

Real Decky, Gamescope, presentation timing, visual quality, and frame pacing
still require a SteamOS/Bazzite target. Generic CI must not be used as evidence
that FPS, latency, power use, or generated-frame quality remained unchanged.

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
  bindings and fails if either they or the generated translation bundle drift.
- `pnpm test` — Python unit tests plus dependency-free frontend contract tests.
- `pnpm run test:flatpak-integration` — opt-in Linux test against the real
  Flatpak CLI; CI enables it with `RUN_FLATPAK_INTEGRATION=1` in isolated XDG
  directories.
- `pnpm typecheck` — strict TypeScript check.
- `pnpm run build` — i18n validation and production frontend bundle.
- `pnpm run package:local` — networked package verification.

The current unit suite covers transactional configuration/installation,
launch-wrapper behavior, diagnostics, and Flatpak command/result contracts.
DLL detection and rendered frontend component behavior remain important
coverage gaps.
