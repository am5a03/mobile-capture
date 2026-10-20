# Standalone repository extraction

Mobile Capture's source now lives in [raymondctc/mobile-capture](https://github.com/raymondctc/mobile-capture).
The initial snapshot comes from
[Oh My Android commit 2c17961](https://github.com/am5a03/oh-my-android/commit/2c179619f613e5ac0d829d21f0ec176a5760e666)
on `codex/issue-4-unified-capture`, including the latest scrollable Capture Details
layout and native timeline resize fixes. Exact imported-file hashes are recorded
in [SOURCE-ORIGIN.json](SOURCE-ORIGIN.json). This is a source snapshot with provenance;
the original commit history remains available in the source repository.

## GitHub ownership transfer

The standalone repository moved from `am5a03/mobile-capture` to
[raymondctc/mobile-capture](https://github.com/raymondctc/mobile-capture).
For an existing clone, update the remote and fetch:

```sh
git remote set-url origin git@github.com:raymondctc/mobile-capture.git
git fetch origin
```

New installers, release links, and beta feed configuration use the new owner.
Published archives, checksums, tags, and signed feed bytes remain unchanged.
The beta signing key and its Keychain account also stay unchanged.
See [pre-transfer installation](AGENT_SETUP.md#install-a-release-published-before-the-transfer)
for existing release installers and [beta feed compatibility](BETA-UPDATES.md#repository-transfer)
for signed update history. Original Oh My Android links and historical audit
records retain their original owner.

## Repository boundary

- `MobileCapture.xcodeproj` is generated from this repository's `project.yml`.
  The only targets are MobileCapture, mobile-capture-host and mobile-capture-proxy.
- Capture app/core/UI, runtime resources, pinned dependency metadata, fixture tests
  and capture documentation are included. The helpers and bundled engine can be
  built and packaged without another checkout.
- Original Android app features, its launcher implementation, MCP, Sparkle updater,
  branding, project and release jobs remain in Oh My Android. This extraction does
  not delete or modify that checkout.
- This repository has its own build/test CI and capture-only release entry point.
  Imported historical reports may describe earlier multi-product checkpoints;
  use this README and distribution guide for current build commands.
- No saved sessions, live traffic, device profiles, CA/private keys, dependency
  binaries or personal agent configuration are imported. Their existing on-disk
  locations and the app's launch/handoff contract remain unchanged.

## Validation

Validated on Apple Silicon with macOS 26, Xcode 26.6 and Swift 6.3.3:

| Check | Result |
| --- | --- |
| Generated standalone project | Exactly three capture targets; no original-checkout paths or Swift package dependencies |
| Optimized app and both helpers | Passed with Swift 6 warnings as errors |
| Core fixture group | Handoff/catalog, plans, readiness, USB discovery and private profile fixtures passed |
| Services fixture group | Doctor/setup state, discovery/export, lifecycle/recovery and bounded logs passed |
| Timeline fixture group | Native index/store, table resize/selection/follow and command-target fixtures passed |
| Swift Testing total | 194 tests passed, in addition to the standalone fixture checks |
| Python runtime/proof/setup fixtures | 68 tests, passed with one optional real-engine test skipped |
| Complete development packaging | Passed using the pre-existing external pinned cache; experimental iPhone USB candidate included |
| Product boundary and sealed dependency hashes | Passed; no original Android app/MCP or Sparkle payload |
| Deep/strict signatures, clean-PATH tool probes and actual packaged Doctor | Passed; no phone connection probes |
| ZIP integrity and SHA256SUMS | Passed |
| Shell/Python syntax and local documentation links | Passed |

The source/runtime/tests/lock files were imported unchanged; an inherited extra
blank line at the end of one Swift file was removed afterward. Build/CI/release
configuration and current repository guidance were adapted for this checkout.
The packaged artifact is a local ad-hoc signed arm64 development build, not a
notarized release. No capture evidence or dependency binaries are committed.
No device capture, certificate/profile installation or routing change was made
for this migration. Existing hardware/fresh-Mac/release acceptance gaps remain.
