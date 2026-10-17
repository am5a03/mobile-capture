# Internal beta updates

## Outcome and ownership

Mobile Capture uses Sparkle2.10.0 for download, archive authentication, installation and restart. The app menu and Settings expose Check for Updates. Keep local.mobilecapture.development and external session, certificate and tunnel-profile locations. No Apple Developer ID is required for this internal beta. Browser-download approval remains the normal macOS process.

The falsifiable completion condition is a real packaged older app using the public HTTPS feed to install a newer beta, relaunch with the newer build, preserve external data and preferences, and reject a modified archive. Capturing, save, setup, Doctor and recovery must prevent installation or helper replacement in the running bundle.

## Compared designs

Candidate A uses the standard updater controller and early exclusive admission. Candidate B wraps the standard user driver and migrates every operation to scoped permits. Both identify that shouldPostponeRelaunch alone is incomplete because Sparkle can install on quit. A is the base because it retains Sparkle's standard lifecycle and exposes a smaller app contract. B contributes an explicit check/install state and checks at operation entry points.

The synthesis refines A. A manual check acquires one main-actor admission before calling Sparkle, so existing work wins and new work cannot start during that update attempt. A background check never reserves capture work or offers installation. It records a discovered version and aborts before download. The user can then use Check for Updates while idle. Automatic checking starts off and binds directly to Sparkle's preference when enabled. Automatic download and installation stay disabled. Standard native Sparkle UI owns manual release notes, progress, cancellation and restart. No custom installer or user driver is required.

The update admission owner represents available, checking and installationCommitted. Cancellation or failure before extraction releases checking after the cycle confirms it. Once Sparkle reports didExtractUpdate, installation commitment stays sticky through every later finish or dismissal until app exit. Exact2.10 source shows the ready-to-install reply bypasses userDidMakeChoice, so that delegate cannot prove cancellation. The app tells the user a restart is required once the update is ready. This conservative choice also retains the lock after a ready-stage cancellation rather than guessing that the installer is disarmed. Never use canCheckForUpdates or sessionInProgress as proof that replacement is disarmed. Read exact Sparkle2.10 headers before implementing delegate transitions.

## Safety boundary

CaptureStore and nested setup state remain authoritative. Project their active capture, busy or marker work, Doctor operation, setup preparation, routing recovery and unfinished package retry into an update blocker. Admission runs synchronously without await, acquires and inspects the safe existing per-user ownership inode, and rejects malformed or unproven durable ownership. For a fresh installation, create the private directory and an empty safe owner.lock only as an explicit update lease acquisition, then hold its same-inode nonblocking flock. Validate ownership, modes, regular-file type, link count and no symlink following. Never remove the shared inode. The lease never rewrites an existing owner record or stops a process. Hold it for the manual update attempt. A second running instance of the same resolved bundle path also blocks.

All current-app entry points that launch a helper or mutate evidence consult the shared admission, including direct methods and guided setup. Normal quit must not manufacture update eligibility by stopping a capture. No updater code confirms tunnel-off or changes phone routing.

The guarantee covers live or recoverable work and new work admitted through the running app in the bundle being replaced. Other installed copies have separate helper paths. It does not claim protection from an arbitrary direct CLI launch from the target bundle after the app has exited during Sparkle's replacement interval. Do not add a permanent keeper process for that hypothetical route. Observe the real handoff and add stronger coordination only if a required app-mediated path demonstrates a gap.

## Distribution contract

Dependencies/Sparkle/beta-updates.json is the public configuration authority. It contains the feed, public key, channel, bundle identifier and pinned official tool archive hash. It contains no credential. project.yml pins the framework at2.10.0. Local and normal CI builds remain updater-disabled. Packaging enables and seals the JSON policy into Info.plist before signatures only for an explicit beta release tag. The app reads the sealed metadata. Stable signing remains separate.

The production signing key stays in login Keychain account am5a03.mobile-capture.beta. Automatic approval review rejected exporting it to GitHub Actions. No export or alternate transfer is permitted. GitHub Actions builds and publishes the complete beta ZIP. A reviewed local command downloads those final bytes, validates release/checksum/bundle/version/config/nested signatures, signs with the Keychain account using official Sparkle tools, verifies the signatures, and publishes only signed public appcast metadata. The appcast is also signed and verified before extraction. Keep the existing three-entry installer checksum manifest unchanged.

Publish the feed over HTTPS from the independent codex/beta-update-feed branch. It does not trigger the tag-only release workflow. Use exact-tag enclosure URLs. Verify archives are reachable before feed publication. Re-read and use an expected feed commit for atomic publication, reject non-increasing build numbers or same-tag changed archives, and verify the actual public response. Do not move or replace existing release tags/assets.

The installer retains exact-tag safety. Sparkle updates the installed app in place. A version-named parent directory records installation origin after an update. The running app's metadata supplies its actual version. Re-running an old exact-tag installer after an in-place update safely reports conflicting content; install an exact requested tag separately. Do not introduce receipts, mutable-slot migration or relaxed signature/conflict checks.

## Work units and checks

1. Verify ad-hoc compatibility before production changes. The disposable actual Sparkle proof installed build2 over build1, verified final nested signatures, and rejected an altered ZIP with EdDSA mismatch. Browser-download Gatekeeper was not tested.
2. App owner implements typed admission, actual operation guards, standard updater, app menu and native Settings. Use apple-design references and write-swift. Add meaningful safety and state tests. Verify imported callbacks and real build.
3. Release owner implements policy sealing, explicit nested signing, signed local feed publication, release notes/guide and archive/feed fixture tests. The root retains all private-key and GitHub publication operations.
4. Integrate in ordered checkpoint commits. Run relevant tests then a complete package. Drive native UI, cancellation, busy refusal and real old-to-new installation. Inspect actual version, processes and preserved data.
5. Run a separate comment review and independent shipping verdict against exact base/head/patch. Land only the reviewed revision with a service head guard. Publish the beta, sign and verify the public feed, then finish the public download/update proof and audit.

Two isolated implementation worktrees eliminate shared file writes. The app owner owns project.yml, app and state files plus its new update tests. The release owner owns release/feed scripts, product checks, workflows, release tests and setup documentation. The root owns integration, audit, Keychain and public publication.

## Verification limits

A local updater-enabled older build can prove installation from a public beta without a dummy public release. Its provenance must be recorded. Existing beta0.1.1-beta.1 cannot update itself because it has no updater. A one-time install is required. Fresh-Mac Gatekeeper acceptance is distinct from Sparkle archive authentication and must not be claimed from a local build.

## Independent design judgment

GPT6 Luna recommended the refined A design. Its candidate scores for safety, maintainability, beta UX, publication, installer compatibility and proof were A3/4/2/4/2/4 and B3/2/4/1/4/4. The synthesis fixes A background-check blocking and avoids both candidates installer expansion. The judge required explicit fresh-install ownership acquisition and stage-specific sticky cancellation, incorporated above. It found no need for a custom user driver, mutable beta slot or keeper. The source-only judgment does not replace native app proof.

## Accepted implementation reconciliation

The app owner read SPUUIBasedUpdateDriver.m417-425 and SPUCoreBasedUpdateDriver.m235-250 in the resolved2.10 source. The ready-stage reply goes straight to the core driver without userDidMakeChoice, and installer cancellation has no disarmed acknowledgement suitable for releasing admission. The root accepted didExtractUpdate as the sticky commitment signal. Pre-extraction cancellation releases after cycle completion. All later outcomes require app exit before capture work resumes. This updates the contract before the next unit.

The implementation names the nonclaiming primitive CaptureReadOnlyRoutingLock(validatingIdleOwnerIn:). Its descriptor opens O_RDONLY and holds an exclusive flock. Tests check that existing owner bytes and inode survive the admitted check and release for saved, partial and failed terminal sessions. The host routing lease remains the only record writer.
