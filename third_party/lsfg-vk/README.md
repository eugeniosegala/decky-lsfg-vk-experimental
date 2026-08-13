# lsfg-vk payload provenance

This directory retains one original PancakeTAS dev28 release asset as a compact baseline and rollback reference.
Experimental fork releases are recorded below as metadata only; their binaries remain on the experimental engine
repository's GitHub releases page instead of being duplicated in this Decky repository.

The Decky packager copies an explicit list of plugin files and does **not**
include this directory in the distributable ZIP. The runtime payload included in a release ZIP remains the single
archive declared and checksum-pinned in
`package.json`.

## Original PancakeTAS dev28 baseline

- Retained file: `v2.0.0-dev28/lsfg-vk-2.0.0-dev28-linux.tar.xz`
- Source repository: `https://github.com/PancakeTAS/lsfg-vk`
- Source: `https://github.com/PancakeTAS/lsfg-vk/releases/download/v2.0.0-dev/lsfg-vk-2.0.0-dev28-linux.tar.xz`
- Source commit: `8b0da2661c6f3473a7fccc8ba643880050e71642`
- SHA-256: `bb2b691939fc6c51888b10349345a3c0ae9ad0b5c3892fd7859d0cdf697b734e`

## Experimental fork release ledger

## v2.0.0-dev28-experimental.1

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.1`
- Source commit: `82e0d49976db8bce5e472fa154526e971529e091`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Source:
  `https://github.com/eugeniosegala/lsfg-vk-experimental/releases/download/v2.0.0-dev28-experimental.1/lsfg-vk-2.0.0-dev28-experimental.1-linux.tar.xz`
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

## v2.0.0-dev28-experimental.4

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.4`
- Source commit: `2b200d53d3d773ac91ab672d8eb76ec641779f5e`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.4-linux.tar.xz`
- Host SHA-256: `25d29b0c18b779ee200779c342b395317e5ad8d57d54dff35d7ad00753aec4ab`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.4-flatpaks.tar.xz`
- Flatpak SHA-256: `06dd1e27103bcf32f6ba521ac32355383c6b56b7442c24ed2a3d79c354e3c7d8`
- Notes: Fixes an empty semaphore-value access and adds disabled-by-default presentation diagnostics.

## v2.0.0-dev28-experimental.5

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.5`
- Source commit: `b5d5ba8f4a0e4407d6c491220a9a7ac367560edd`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.5-linux.tar.xz`
- Host SHA-256: `a1c9d3d68e8a1b9d61dd9e76f40cf06d9c128f7637e24c7242aed9ba45330142`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.5-flatpaks.tar.xz`
- Flatpak SHA-256: `7d5c2081aa7cb63197509d353da1aabe5ba971b755952566c0dda895802a4eff`
- Notes: Adds opt-in recovery from Gamescope generated-image acquisition stalls while retaining `.4` diagnostics.

## v2.0.0-dev28-experimental.6

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.6`
- Source commit: `4f08fcd9a4388ae6250abb0e24a94ecf97ae02f2`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.6-linux.tar.xz`
- Host SHA-256: `ab1541c82a35ac7388462a28aec5a34ff7f33462405bf77bce0189caade5d66b`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.6-flatpaks.tar.xz`
- Flatpak SHA-256: `95fff9536359e631fb5d524f0ac3d6e3c87a271f7547395e6362ce8436631152`
- Notes: Uses non-blocking acquisition probes after the first timeout and reports automatic frame-generation recovery.

## v2.0.0-dev28-experimental.7

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.7`
- Source commit: `5c2807a9b26cbb5e472ca57166a8ac9a7d77ae7c`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.7-linux.tar.xz`
- Host SHA-256: `7e3a8ca2989d5c484ce9e4a3b7f43fa96689ce5c75cb93108be25e2094d5c238`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.7-flatpaks.tar.xz`
- Flatpak SHA-256: `f6f5065ff9471057d4e42a10ec775eaa5f8f67adb5a09b28038c2616dafb61f8`
- Notes: Probes image availability before scheduling inference during Gamescope backoff, preserves the latest real-frame
  history, and resumes generation automatically without dispatching work whose output would be discarded.

## v2.0.0-dev28-experimental.8

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.8`
- Source commit: `92c23ab7308739dae09c2eb508d3c187c1783e77`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.8-linux.tar.xz`
- Host SHA-256: `8e0b20d29bf9b0419ae665835df21791200ea9d074c545863e2c1dd51dd9a7d5`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.8-flatpaks.tar.xz`
- Flatpak SHA-256: `8a263e743a3bc7f4f92c626a476988443d9d1eaf10c805d2e6ad076f50a79840`
- Notes: Adds one bounded reacquisition attempt per second after the first second of Gamescope backoff, reducing the
  chance that zero-timeout probes repeatedly miss the compositor's image-release window.

## v2.0.0-dev28-experimental.9

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.9`
- Source commit: `18fdb00a0e763218cbcbd40a5cea171ee3fc7d54`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.9-linux.tar.xz`
- Host SHA-256: `9c60ff8893259f1162d218eb8b8a9b51c636102bd5c16b3f3d099d31f585b48f`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.9-flatpaks.tar.xz`
- Flatpak SHA-256: `a9032703eb9db646db0052e3bd95779850ca8531bbbb9f259b8d7cbb926c3586`
- Notes: Adds opt-in Adaptive Frame Generation with target-FPS scheduling while preserving the fixed multiplier path.

## v2.0.0-dev28-experimental.10

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Expected release tag: `v2.0.0-dev28-experimental.10` (local candidate; not yet published)
- Source commit: `57ea3b71427f8582041e0c98b81c8004f6f4b311`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.10-linux.tar.xz`
- Host SHA-256: `3a88778e971a1175910ba95b61821ac097bc7baa99fad930fadfdc94a9cde39e`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.10-flatpaks.tar.xz`
- Flatpak SHA-256: `1221d76dd1007da6ef792e8a3e5aee2bc9ef2f792b1b6fd8880001d8055f8f41`
- Notes: Maintains temporal model history while generated outputs are bypassed during Gamescope presentation stalls and
  resets Adaptive timing state across recovery. Testing showed that a single successful image probe could still restart
  generation too early, which is addressed by the following candidate.

## v2.0.0-dev28-experimental.11

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Expected release tag: `v2.0.0-dev28-experimental.11` (local candidate; not yet published)
- Source commit: `08d6af2a6ea0cccd9fb82b78f38885a9b51dca99`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.11-linux.tar.xz`
- Host SHA-256: `2f011d42755b5b983589b1af09f63cb3bab919f507469c0921832af38acbe683`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.11-flatpaks.tar.xz`
- Flatpak SHA-256: `cbb9907974442a998d4c48004ebd1249457f66eccb11c693eac95278cc8c7c0b`
- Notes: Warms all three shared temporal-history slots with real frames before Adaptive output at startup and after a
  Gamescope recovery. The successful recovery probe is safely presented as a real-frame copy before the warm-up
  continues.

## v2.0.0-dev28-experimental.12

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Expected release tag: `v2.0.0-dev28-experimental.12` (local candidate; not yet published)
- Source commit: `1fedcc5a35ce1411270bef2f98e9725707ad87d4`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.12-linux.tar.xz`
- Host SHA-256: `a4f8f00a6d45753c81ab4e161ebaea7eff41be962bdfad7132dca805d0952f45`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.12-flatpaks.tar.xz`
- Flatpak SHA-256: `38d4cf3b05fe08a30087b95a2e7524b300ee085d7ac9ec969c01ae8a1211027a`
- Notes: Adds a 2x, 3x, or 4x maximum Adaptive multiplier, defaulting to 3x. When the real-frame rate falls, the cap
  allows output to undershoot the target rather than forcing a more artifact-prone interpolation ratio.

## v2.0.0-dev28-experimental.13

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Expected release tag: `v2.0.0-dev28-experimental.13` (local candidate; not yet published)
- Source commit: `1cb0e4b4778813798f1739413e48e524d95abfed`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.13-linux.tar.xz`
- Host SHA-256: `077ecc474acd8a028cdd6f8d9988fb81babfce95d32f1808329ede4121aebc3b`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.13-flatpaks.tar.xz`
- Flatpak SHA-256: `2af906d585ef073eb4cdf32309995c0248de3c7c1ade3f13355171b8f00b89d1`
- Notes: After Adaptive recovers from a genuine Gamescope acquire timeout, an opt-in policy safely presents the
  reacquired and original images before asking the game to recreate its Vulkan swapchain. This creates a fresh LSFG
  context instead of carrying accumulated presentation latency across repeated overlay transitions. Fixed mode is
  unchanged.

## v2.0.0-dev28-experimental.14

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Expected release tag: `v2.0.0-dev28-experimental.14` (local candidate; not yet published)
- Source commit: `ac929d709304b17d11d5c488fb77efd2921beab1`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.14-linux.tar.xz`
- Host SHA-256: `51f67d07ec40c02c60e5de5f1c58651bfcd5b76b5cb99502ab2d54d8313863af`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.14-flatpaks.tar.xz`
- Flatpak SHA-256: `2aea1e6db23593b73cedaa89f1d88eadaffd56f7dfd5af541943fc4b3ca85dbc`
- Notes: Stabilizes Adaptive on real frames after startup or presentation disruption, ramps generated-frame load
  gradually, rolls back counterproductive ramp steps, and shares a five-second swapchain-recreation cooldown across
  replacement contexts. Fixed mode remains unchanged.

## v2.0.0-dev28-experimental.15

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Expected release tag: `v2.0.0-dev28-experimental.15` (local candidate; not yet published)
- Source commit: `918af620df2623a619d013610aa05546939ff926`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.15-linux.tar.xz`
- Host SHA-256: `59c52aa44d9274aed7cd029d7a651d69af4992f4f9a949eb59a054ec708c6615`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.15-flatpaks.tar.xz`
- Flatpak SHA-256: `3efc983008a39b8c928ce6683e9381205de716318610c3095ae6e5bf806d53ef`
- Notes: Adds one bounded bridge test when a Gamescope cadence divisor makes the first Adaptive load step misleading.
  Rejected or interrupted probes wait at least 15 seconds and require two seconds of stable cadence before rearming.
  Fixed mode remains unchanged.

## v2.0.0-dev28-experimental.16

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Expected release tag: `v2.0.0-dev28-experimental.16` (local candidate; not yet published)
- Source commit: `78d2c1b80d3a6de3dbb6b4509818cfa9601d7f84`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.16-linux.tar.xz`
- Host SHA-256: `7d55806186027d6078006d8df6bc455f0ac36f35783cee1645227ed2f24dd5ca`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.16-flatpaks.tar.xz`
- Flatpak SHA-256: `aa72562cba3c164cbb3102323517399e1e19689c0e6b32c6d55d7b01f4a36960`
- Notes: Retains a validated Adaptive generation level through recovery so a recovered context does not always begin
  again from zero. The following `.17` candidate supersedes it for Decky integration.

## v2.0.0-dev28-experimental.17

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Expected release tag: `v2.0.0-dev28-experimental.17` (local candidate; not yet published)
- Source commit: `02a9bfb9cd28df87dd047e7539a24e0a1cd95e65`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.17-linux.tar.xz`
- Host SHA-256: `d752994f6f9f32e0561b81e77f1654adff8ba54d97087eb73a81577b5c7737af`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.17-flatpaks.tar.xz`
- Flatpak SHA-256: `23f38dcf3669389a68f4e93a0641582bd8cc85f0e45843d6afc1e3e2ef4701fb`
- Notes: Adds optional bounded constant-cadence validation, retains the last validated Adaptive generation level through
  a recovered swapchain, progressively backs off rejected higher-level probes, and freezes Adaptive decisions while
  generated output is unavailable. Constant cadence now waits for strict scheduling to settle and is considered only
  near a natural target divisor. A severe sustained collapse performs one bounded real-only measurement before resuming
  fractional scheduling or probing one higher configured level. Abrupt menu-related cadence stalls now enter a separate
  bounded discontinuity recovery: the engine retains the proven generation level, waits for one stable second before
  restoring it, and falls back to a clean ramp after five seconds. Its first generated-image recovery refreshes history
  without immediately rebuilding the swapchain. Smooth Cadence is now opt-in because constant cadence can lower the
  real-frame presentation rate and responsiveness. A sustained gameplay cadence drop rebases after one second instead of
  waiting five seconds for the old rate; only a hard stall retains the previous baseline. The discontinuity safeguard
  remains active in Adaptive mode. An interrupted ramp or bridge probe now rearms after two stable seconds without being
  counted as a failed load test; genuine rejections retain their 15-second cooldown but may retry early after a
  sustained 15% real-only base-rate improvement. Adaptive now stops at the lowest proven level that can supply at least
  98% of its target. It also detects a delayed collapse after accepting a higher strict-scheduling level, measures one
  second without generation load, and restores the lower level only when that measurement recovers the prior cadence.
  Fixed mode remains unchanged.

## v2.0.0-dev28-experimental.18

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.18`
- Source commit: `2eb2facedeebf7ee3345ea271345de98a1767674`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.18-linux.tar.xz`
- Host SHA-256: `055a455c58bf8029e738290711f8035e59c4e4c31f3b5c56b2e194c6b4e04235`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.18-flatpaks.tar.xz`
- Flatpak SHA-256: `c7b8cd70e62ededfce10665ff1cad41fc6268d12d9995fdae5edd6e1748c4603`
- Notes: First published engine prerelease since `.9`, consolidating the tested `.10` through `.18` revisions. It adds
  temporal-history maintenance and warm-up, a configurable Adaptive ceiling and optional Smooth Cadence, load-aware ramp
  and rescue policies, Gamescope recovery safeguards, less sensitive target satisfaction, and DX12/VKD3D fast-present
  burst filtering. Fixed multiplier mode remains unchanged.

## v2.0.0-dev28-experimental.19

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.19`
- Source commit: `40f56701df1e43c4893d6110cb47362fb9565859`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.19-linux.tar.xz`
- Host SHA-256: `2b26c0e532eb407eb8e1ac6252ba8dc0f6478b424065bbcfca8222e0898b6489`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.19-flatpaks.tar.xz`
- Flatpak SHA-256: `35ad14a6fa0162e07c3c2d637cdde07d22dfd2a408d409f4877d4036eb3cdf7c`
- Notes: Keeps a validated 2x Adaptive level through an isolated 100–250 ms gameplay hitch, refreshes three real
  temporal-history frames, and resumes without entering the longer menu/focus recovery. Fixed mode, Adaptive 3x/4x,
  generated-image acquisition fallback, and swapchain recreation are unchanged.

## v2.0.0-dev28-experimental.20

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.20`
- Source commit: `70da2eedab0422e0a3ef5bb4d67da446d0d3d9f3`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.20-linux.tar.xz`
- Host SHA-256: `5c9f9d75c9cadae56546ff9e3448b14c82bafaf0a931f3a48babb9c41e842b49`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.20-flatpaks.tar.xz`
- Flatpak SHA-256: `78d5d8099b439e297ff5e1e08f3aeb04c54fa1a15efd4ac512bf2e3a5928f9db`
- Notes: Adds the independent `frame_generation_enabled` runtime switch used by the Decky **Frame Generation** toggle.
  When disabled, LSFG-VK forwards original frames and skips generated-frame work. Re-enabling it resets and warms
  temporal history before synthesis resumes; Fixed/Adaptive mode selection and existing recovery safeguards remain
  intact.

## v2.0.0-dev28-experimental.21

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.21`
- Source commit: `eb5c453fa04010d6c9a0f4decb4d2bb71d2ae38b`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.21-linux.tar.xz`
- Host SHA-256: `29972ff0a9bf66189b97882c72d522ff81cb4c41a12040050ada6163bc2d3fc6`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.21-flatpaks.tar.xz`
- Flatpak SHA-256: `503db55c420345215dc83261be3748d3d38e7385ff785143d1996d3b35ca33ca`
- Notes: Extracts Adaptive policy into a clock-driven state machine with deterministic regression coverage and prevents
  Smooth Cadence from retaining a generated-frame level above the configured maximum. The unstable local-only
  `ab4f790` hot-path experiment is excluded, preserving the known-good rendering and submission path.

## v2.0.0-dev28-experimental.24

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Release tag: `v2.0.0-dev28-experimental.24`
- Source commit: `865b34b2f596c545cabfd0810f905c18194bf6b4`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.24-linux.tar.xz`
- Host SHA-256: `09add7d1a14f7a6928cec65fc2aa711bf83c101639825409b9e80d7120d05ee4`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.24-flatpaks.tar.xz`
- Flatpak SHA-256: `726325151f0645c687b78d013165785bcb3a9c2587a58aa4accdbf1857753727`
- Notes: Strengthens Adaptive recovery after Steam-menu or focus interruptions, adds safer bounded generated-image
  recovery, and ensures restoration, rescue, and recovery respect the configured Maximum Adaptive Multiplier. The
  deterministic scheduler baseline, rendering path, shaders, interpolation timing, and Fixed scheduling remain unchanged.

## v2.0.0-dev28-experimental.25 (local candidate)

- Source repository: `https://github.com/eugeniosegala/lsfg-vk-experimental`
- Reserved release tag: `v2.0.0-dev28-experimental.25` (not published)
- Source commit: `4777cb2115760fd0936f91f535becb6d17d0c329`
- Upstream lineage: `lsfg-vk 2.0.0-dev28`
- Host archive: `lsfg-vk-2.0.0-dev28-experimental.25-linux.tar.xz`
- Host SHA-256: `859aa47000bc4e6c5aef4cb2fa35950d288d466488dc13b82473215976f43c14`
- Flatpak archive: `lsfg-vk-2.0.0-dev28-experimental.25-flatpaks.tar.xz`
- Flatpak SHA-256: `e2d7b432a8f29a4c241543fe9e8d0c14f7ad333396197a46e5cc55fc850a135b`
- Notes: Adds explicit swapchain colour classification, HDR10/PQ conversion through linear scRGB, direct linear-scRGB
  frame generation, and real-frame passthrough for unsupported HDR modes or frame-generation initialization failures.
  The local Decky candidate preserves Gamescope WSI discovery by default and adds a per-profile SDR startup recovery.
