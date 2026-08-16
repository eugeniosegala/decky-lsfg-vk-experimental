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

That command expects the engine checkout at `../lsfg-vk-experimental`. For another location, invoke the packager directly:

```bash
scripts/package-local.sh --local-engine-repo /path/to/lsfg-vk-experimental
```

For quick native Steam-game iteration, omit the expensive Flatpak runtime
matrix and the 32-bit host layer while retaining a verified 64-bit build:

```bash
pnpm run package:local-engine-fast
```

Native-only, 64-bit-only archives are labelled accordingly and must not be published. Run
the complete local-engine packaging command before any release candidate or
when testing Flatpak games and launchers. Local artifacts are keyed by the
engine commit and dirty-worktree fingerprint, so UI-only repackaging reuses an
already verified matching engine build; changing engine source produces a new
fingerprint and rebuilds it.

The engine's native and Flatpak packaging scripts run first, including their tests and dual-architecture layout
checks. Decky then embeds those artifacts and writes their source commit, dirty-worktree marker, and calculated
checksums into the generated ZIP's copy of `package.json`. The tracked Decky `package.json` remains unchanged, so this
development path cannot alter the release pin. The ZIP is named with the local engine commit and `.dirty` when
applicable. It does not tag, push, or publish either repository.

## Fast direct SteamOS iteration

When both checkouts are on the SteamOS machine, do not create a ZIP for every
edit. Install the experimental plugin and use its **Install Experimental
LSFG-VK** action once first, then run these commands from this repository:

```bash
pnpm run dev:frontend  # TypeScript/React change
pnpm run dev:backend   # Python/backend change
pnpm run dev:engine    # Native 64-bit layer change
pnpm run dev:all       # All three
pnpm run dev:host      # Decky plus 64-bit and genuine 32-bit host layers
pnpm run dev:flatpaks  # Decky plus Flatpak bundles for 23.08, 24.08, and 25.08
pnpm run dev:e2e       # Decky, both host layers, and all Flatpak bundles
```

Each command deploys directly to Decky's installed experimental plugin at
`~/homebrew/plugins/Decky LSFG-VK Experimental` and tells you to reload it from
Decky's Developer menu. `dev:engine` calls the engine's persistent incremental
build, then atomically replaces only the private 64-bit host layer. It skips
the archive, ZIP, Flatpak runtime matrix, 32-bit layer, CLI/UI, and full test
suite, so it is for native 64-bit Steam-game testing only. Quit the game before
deploying the engine. Use the regular package commands before publishing or
testing release packaging.

`dev:all` remains the fast native 64-bit loop. Use `dev:host` when you also
need a genuine 32-bit Steam/Proton process, `dev:flatpaks` when testing the
Flatpak Setup flow, and `dev:e2e` before a full local regression pass. The
Flatpak commands build and place the three verified bundles in the installed
plugin; open **Flatpak Setup** and choose **Update** for the target runtime to
install a bundle into the application sandbox.

On SteamOS, the host commands require `lib32-glibc`; if
`/usr/include/gnu/stubs-32.h` is missing despite the package appearing
installed, reinstall it without `--needed`. The Flatpak commands additionally
need `flatpak-builder`. The source-build guide gives the exact SteamOS commands
for the former; for the latter use `sudo pacman -S flatpak-builder` while the
SteamOS filesystem is temporarily writable.

The Flatpak command retains its downloaded dependency cache in
`build/steamos-flatpak-cache` and stages builds under
`build/steamos-flatpak-tmp`, both inside the engine checkout. This avoids
SteamOS's comparatively small `/tmp` filesystem and makes later bundle builds
reuse the downloaded runtimes. Set `LSFGVK_FLATPAK_CACHE_ROOT` or
`LSFGVK_FLATPAK_TMP_ROOT` to move either location.

The cache has no automatic expiry and survives reboots. Inspect its current
size with the safe, dry-run command:

```bash
pnpm run dev:prune-flatpak-cache
```

Only when you explicitly want to reclaim that space, remove this checkout's
Flatpak cache and any interrupted staging directory with:

```bash
pnpm run dev:prune-flatpak-cache -- --confirm
```

It never removes the native incremental builds, the installed Decky plugin,
the plugin's three already-deployed Flatpak bundles, or your normal user
Flatpak installation. The next `dev:flatpaks` or `dev:e2e` run will need to
download the SDK/runtime dependencies again. For safety, the prune command
targets only the default repo-local locations; if you set either cache-location
environment variable, manage that custom directory yourself.

Every direct development deployment refreshes a blue status box at the top of
the plugin. It records the local deployment timestamp, the Decky and LSFG Git
commits (and whether either checkout had local edits), the deployed frontend
and backend scope, and the first 12 characters of the 64-bit layer, 32-bit
layer, and Flatpak-bundle SHA-256 values when those artifacts were part of the
run. `dev:all`, `dev:host`, and `dev:e2e` are the confirmation that Decky and
the applicable LSFG artifacts were deployed together in the displayed run;
narrower commands explicitly identify the part left unchanged.

Set `DECKY_PLUGIN_DIR` if the local plugin was installed elsewhere, or invoke
`scripts/deploy-dev.sh --engine-repo /path/to/lsfg-vk-experimental --engine`
when the engine checkout is not a sibling. The engine build requires the
SteamOS CMake/Ninja/compiler prerequisites in its
[source-build guide](https://github.com/eugeniosegala/lsfg-vk-experimental/blob/develop/docs/Building-From-Source.md).

## Publish a GitHub prerelease

Commit the intended version and release changes on a clean branch, authenticate once with
`gh auth login -h github.com`, then run:

```bash
pnpm run package:publish
```

The script verifies and builds the ZIP, creates or verifies the matching `v<package-version>` tag, pushes the branch
and tag, generates release notes, and creates or updates the GitHub prerelease. It never moves an existing published
tag to newer code.
