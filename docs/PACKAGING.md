# Local packaging and publishing

## Build a local installation ZIP

Install pnpm and dependencies once. With Volta, run `volta install pnpm` first.

```bash
pnpm install --frozen-lockfile
pnpm run package:local
```

This creates `out/Decky.LSFG-VK.Experimental.zip`. The packager regenerates configuration bindings, builds the
frontend, downloads the engine pinned in `package.json`, verifies its SHA-256 checksum, and creates a Decky ZIP. It
does not tag, push, or publish anything.

Pass a path to choose the output location:

```bash
pnpm run package:local -- /path/to/Decky.LSFG-VK.Experimental.zip
```

To test an engine candidate before its GitHub release exists, provide locally built native and Flatpak archives. Their
checksums must still match the pin in `package.json`:

```bash
pnpm run package:local -- \
  --engine-archive /path/to/lsfg-vk-<version>-linux.tar.xz \
  --flatpak-archive /path/to/lsfg-vk-<version>-flatpaks.tar.xz \
  /path/to/Decky.LSFG-VK.Experimental-local-test.zip
```

### Build directly from a local engine checkout

For day-to-day development, build both engine payloads and the Decky ZIP in one command:

```bash
pnpm run package:local-engine
```

That command expects the engine checkout at `../lsfg-vk`. For another location, invoke the packager directly:

```bash
scripts/package-local.sh --local-engine-repo /path/to/lsfg-vk
```

The engine's native and Flatpak packaging scripts run first, including their tests and dual-architecture layout
checks. Decky then embeds those artifacts and writes their source commit, dirty-worktree marker, and calculated
checksums into the generated ZIP's copy of `package.json`. The tracked Decky `package.json` remains unchanged, so this
development path cannot alter the release pin. The ZIP is named with the local engine commit and `.dirty` when
applicable. It does not tag, push, or publish either repository.

## Publish a GitHub prerelease

Commit the intended version and release changes on a clean branch, authenticate once with
`gh auth login -h github.com`, then run:

```bash
pnpm run package:publish
```

The script verifies and builds the ZIP, creates or verifies the matching `v<package-version>` tag, pushes the branch
and tag, generates release notes, and creates or updates the GitHub prerelease. It never moves an existing published
tag to newer code.
