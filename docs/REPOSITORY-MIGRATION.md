# Standalone repository extraction

Mobile Capture's source now lives in [am5a03/mobile-capture](https://github.com/am5a03/mobile-capture).
The initial snapshot comes from
[Oh My Android commit 2c17961](https://github.com/am5a03/oh-my-android/commit/2c179619f613e5ac0d829d21f0ec176a5760e666)
on `codex/issue-4-unified-capture`, including the latest scrollable Capture Details
layout and native timeline resize fixes. Exact imported-file hashes are recorded
in [SOURCE-ORIGIN.json](SOURCE-ORIGIN.json). This is a source snapshot with provenance;
the original commit history remains available in the source repository.

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

See the repository migration validation checkpoint added after the isolated build,
fixture suites and full development-package checks. No hardware capture is needed
to prove the source/build boundary; existing hardware acceptance gaps remain.
