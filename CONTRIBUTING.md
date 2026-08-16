# Contributing

## Toolchain

- Node.js 20, 22, or 24
- pnpm 10 (the repository pins pnpm 10.18.0 through Corepack)
- Python 3.12 or newer
- Bash for the packaging and diagnostic scripts

Enable the pinned package manager and install dependencies:

```bash
corepack enable
pnpm install --frozen-lockfile
```

## Fast verification

Run the same non-publishing quality gate used by pull requests. It regenerates
the committed configuration bindings and fails if that produces a diff:

```bash
pnpm check
```

The gate verifies generated configuration bindings, Python byte-compilation,
shell syntax, all Python unit tests, strict TypeScript type checking, i18n
consistency, and the production frontend bundle.

Individual commands are also available:

```bash
pnpm test
pnpm typecheck
pnpm run check:generated
pnpm run check:shell
pnpm run build
```

On Linux with Flatpak installed, the isolated real-CLI suite is available as:

```bash
RUN_FLATPAK_INTEGRATION=1 pnpm run test:flatpak-integration
```

## Generated configuration contract

`shared_config.py` is the configuration source of truth. After changing it,
regenerate and commit the Python and TypeScript bindings:

```bash
python3 scripts/generate_ts_schema.py
```

`pnpm run check:generated` fails when committed bindings are stale.

## Packaging

Use the local packager only after `pnpm check` passes:

```bash
pnpm run package:local
```

The packager downloads checksum-pinned engine assets, validates their expected
architecture paths and experimental identity, builds the frontend, runs tests,
and verifies the resulting ZIP. See [docs/PACKAGING.md](docs/PACKAGING.md) for
local-engine and publishing flows.

Publishing creates tags, pushes Git refs, and updates a GitHub prerelease. Run
`pnpm run package:publish` only with explicit release authority and a clean
worktree. CI intentionally never invokes it.

## CI policy

Pull requests and pushes to `main` run the non-publishing `pnpm check` gate.
The workflow uses a read-only `GITHUB_TOKEN`, does not receive deployment
secrets, pins every reused GitHub action to an immutable full commit SHA, and
cancels superseded runs on the same ref.

Pull requests also run the production Flatpak service against a real Flatpak
CLI in isolated temporary user/XDG directories. This locks the command syntax,
keyfile parser, ownership intent, partial-retry, user-override preservation, and
strict read-back semantics without touching a runner user's normal overrides.

The networked package smoke test is manual so ordinary pull requests do not
repeatedly download engine payloads. By default it verifies the ZIP without
retaining an artifact. A dispatcher can explicitly request an uploaded ZIP for
testing; that artifact is kept for three days. The workflow does not tag, push,
or create a GitHub release.

## Testing boundaries

### Merge evidence matrix

| Change | Required evidence |
| --- | --- |
| Any code or generated file | Green `quality` job |
| Flatpak service, parser, ownership, or UI contract | Green real `Flatpak integration` job |
| Native payload, wrapper runtime environment, presentation/timing, shader, or performance policy | Reviewed target-hardware baseline/candidate report |
| Release metadata or packaged payload | Manual `Package smoke` run before publishing |
| Documentation only | Generated/link-sensitive checks that apply; no fabricated hardware evidence |

Do not turn a noisy benchmark into a required check. Target-hardware evidence
becomes blocking only after repeated unchanged baseline runs demonstrate that
the selected workload and thresholds are stable.

The current suite covers transactional configuration/profile/install/uninstall
state, launch-wrapper behavior, dual-architecture installation, diagnostics,
Flatpak ownership, frontend recovery/mutation contracts, and the hardware-report
gate. Changes to DLL detection or rendered frontend component behavior still
need focused regression coverage where practical.

SteamOS/Decky/Gamescope performance and graphics evidence requires a dedicated
target. See [docs/HARDWARE_VALIDATION.md](docs/HARDWARE_VALIDATION.md) before
changing the native payload, presentation/timing policy, wrapper runtime
environment, or performance-sensitive configuration.
