# Publish an internal beta update

Use this procedure after the tag workflow publishes the complete beta release.
It requires a Mac with Xcode tools, Python 3, GitHub CLI, repository write access,
and the existing beta signing account in the local login Keychain.
Internal beta updates do not require an Apple Developer ID.

The beta key stays in Keychain. Do not export it, pass it through an environment
variable, or place it in GitHub Actions. Actions publishes the final ad-hoc signed
ZIP. This local procedure signs those exact public bytes and publishes only the
signed public appcast. A successful Actions run alone does not advertise an update.

## Build the beta archive

1. Complete the app and release fixture checks at the reviewed source commit.
2. Create and push an unused exact beta tag, such as `v0.1.2-beta.1`.
3. Wait for **Downloadable release** to publish the ZIP and its setup assets.
4. Record the tag's exact source commit and the current feed branch commit.

The workflow enables beta updates only for `vMAJOR.MINOR.PATCH-beta.N` tags.
The app's `CFBundleShortVersionString` is numeric, such as `0.1.2`.
The appcast's `sparkle:shortVersionString` displays the full beta version without
the leading `v`, such as `0.1.2-beta.1`. Its `sparkle:version` is the app's build number,
`github.run_number * 1000 + github.run_attempt`, with attempts limited to 1 through 999
and the result limited to 2147483647. New feed entries must have a larger build and a later beta tag
than every existing entry. Alpha, release candidate, stable, and ordinary local
packages keep updates disabled.

Read the current feed commit with:

```sh
gh api repos/am5a03/mobile-capture/git/ref/heads/codex/beta-update-feed \
	--jq '.object.sha'
```

Use `absent` only when GitHub reports that this branch does not exist. An
authentication failure or network failure does not establish an absent branch.

## Prepare signed metadata locally

Run from the reviewed repository checkout. Replace the commit values with the
observed full commit hashes. Use a new output directory for each preparation.

```sh
python3 -B Scripts/publish-beta-update.py prepare \
	--tag v0.1.2-beta.1 \
	--expected-release-commit REVIEWED_FULL_SOURCE_COMMIT \
	--expected-feed-sha OBSERVED_FULL_FEED_COMMIT_OR_absent \
	--output /private/tmp/mobile-capture-beta-v0.1.2-beta.1
```

The command reads the public policy from
[`Dependencies/Sparkle/beta-updates.json`](../Dependencies/Sparkle/beta-updates.json).
It checks the tag, public release, three-entry checksum manifest, archive paths,
bundle identity, sealed update metadata, app version, build, architecture, and
strict nested code signatures. It downloads the pinned official Sparkle tools
and verifies their archive hash. To reuse an official cached archive, add
`--tools-archive /absolute/path/Sparkle-2.10.0.tar.xz`.

The command checks that the Keychain account's public key matches the policy.
Sparkle's `sign_update --account` signs the archive and appcast. Public-key
verification checks both signatures. The output contains the downloaded archive,
its unchanged checksum manifest, `appcast.xml`, and `publication.json`. Review the
appcast's tag, source commit, exact-tag URL, build, digest, and release notes.

No app is launched. Preparation does not change GitHub, phone state, certificates,
quarantine, or Gatekeeper.

## Publish the reviewed appcast

```sh
python3 -B Scripts/publish-beta-update.py publish \
	--prepared /private/tmp/mobile-capture-beta-v0.1.2-beta.1
```

Publication rechecks the final public archive and tag. It publishes the signed
appcast to the policy's feed branch using the observed parent commit and a
non-forced reference update. A competing publication fails without replacing it.
The command then reads the exact configured public HTTPS feed URL used by the app
and verifies its signature and bytes. GitHub's public cache may delay that URL
after the branch changes. A fresh response at a URL with a different query string
does not verify the app's feed. If the response has not caught up, publication
verification remains pending and the command fails. Wait for the cache to update,
then retry the same command and prepared directory. An identical signed feed
makes no new commit on retry.

Publication also verifies the current branch's signed feed before any write.
The candidate must advance its highest build and latest beta tag. If the candidate
already exists, only an exact match of the complete signed feed bytes is idempotent.
Changing the local expected commit cannot authorize replay of an older signed feed.
Publish a new beta tag for a changed app. Do not move a published tag or replace its archive.

## Verify the installed update

1. Install an updater-enabled older app and record its source commit, local or
   public origin, sealed beta tag, build, app path, and policy digest.
2. Open **Check for Updates…** while the app is idle.
3. Install the public beta and allow Sparkle to relaunch the app.
4. Read the relaunched app's actual `CFBundleVersion` and short version.
5. Check that preferences and external capture data remain intact.
6. Verify that a modified archive is rejected and busy capture, save, recovery,
   setup, and Doctor operations prevent installation.

A locally packaged older app can prove the public update path without publishing
a dummy release. Its provenance must identify it as local. The existing
`v0.1.1-beta.1` has no updater and needs a one-time install. This procedure does
not establish fresh-Mac Gatekeeper acceptance.

Sparkle replaces the installed app in place. If the exact-tag installer created
`$prefix/v0.1.2-beta.1/Mobile Capture.app`, the parent directory records its
installation origin after an update. Read the app's metadata for its current
version. Re-running that old exact-tag installer reports conflict exit `73`
after an in-place update. Install another exact tag separately when needed.
The installer and its three-entry `SHA256SUMS` contract remain unchanged.
