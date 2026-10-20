# Set up Mobile Capture from a repository URL

Use this guide to install a complete release and report the Mac's prerequisites.
Stop after the report and manual device handoff. Installation and Doctor do not
authorize a capture, software repairs, certificate installation, or routing changes.

The binary route requires Apple Silicon and macOS 26. The installer uses stock
macOS tools. The complete app is intended to run without Xcode, Homebrew, or a
separate Python installation. Validation on a clean Mac without developer tools
remains outstanding. The app includes its network engine, Python, and Android
tools. Physical iPhone USB tools remain external. The Simulator route requires an
existing Xcode installation.

## 1. Select an authorized version

Open [Mobile Capture releases](https://github.com/raymondctc/mobile-capture/releases).
Use the installation and channel permission already given in the task. Select
and record an exact stable tag when stable installation is authorized. If no suitable stable release exists, report
that result. A prerelease requires explicit consent to a development build. Ask only when
that consent is missing; do not ask again when the task already grants it.

The pre-transfer example below uses `v0.1.2-beta.1`. This development build is ad-hoc
signed and unnotarized. Use the example only with authorization for that exact
beta. Its publication and availability must be checked on the release page.

Completion criterion: record the authorized tag and channel. The release must
contain `install.sh`, `AGENT_SETUP.md`, `SHA256SUMS`, and the app ZIP. Stable ZIPs
are named `MobileCapture-macOS-arm64.zip`. Development ZIPs are named
`MobileCapture-macOS-arm64-development.zip`.

## 2. Download and inspect the installer

For `v0.1.1-beta.1`, `v0.1.2-beta.1`, or `v0.1.2-beta.2`, follow
[pre-transfer installation](#install-a-release-published-before-the-transfer)
instead of the release-installer commands below. Those installers reject
GitHub's renamed release metadata after the repository transfer.

For releases published with the transfer fix, replace `AUTHORIZED_POST_TRANSFER_TAG`
with the authorized exact tag. Run these commands in one shell:

```sh
release_version='AUTHORIZED_POST_TRANSFER_TAG'
setup_directory=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/mobile-capture-setup.XXXXXX")
cd "$setup_directory"
release_url="https://github.com/raymondctc/mobile-capture/releases/download/$release_version"
/usr/bin/curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 --output install.sh "$release_url/install.sh"
/usr/bin/curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 --output SHA256SUMS "$release_url/SHA256SUMS"
/usr/bin/awk '$2 == "install.sh" { print }' SHA256SUMS > installer.SHA256SUMS
/bin/test -s installer.SHA256SUMS && /usr/bin/shasum -a 256 -c installer.SHA256SUMS
/bin/cat install.sh
```

Stop if a download or checksum check fails. Read the entire script before
execution. Its repository source is
[`Scripts/install.sh`](https://github.com/raymondctc/mobile-capture/blob/main/Scripts/install.sh).
Compare against the source at the selected tag when you review a release.
The installer must download only from `raymondctc/mobile-capture`, verify the ZIP
before extraction, and preserve existing app copies and capture data.

Hashes from the same release detect inconsistent downloads. They do not provide
independent proof of authenticity if the release account or assets are compromised.
Decide whether you trust the publisher and script before execution.

Completion criterion: the installer checksum passes and you have reviewed the
downloaded script. Keep download and execution as separate steps.

### Install a release published before the transfer

Keep the authorized release tag. Review the current installer in the transferred
repository and record the full source commit containing the transfer fix.
Download that exact source version separately from execution:

```sh
release_version='v0.1.2-beta.1'
installer_source_commit='REVIEWED_FULL_SOURCE_COMMIT'
setup_directory=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/mobile-capture-setup.XXXXXX")
cd "$setup_directory"
/usr/bin/curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 --output install.sh "https://raw.githubusercontent.com/raymondctc/mobile-capture/$installer_source_commit/Scripts/install.sh"
/bin/cat install.sh
```

Stop if the download fails. Review the downloaded script and its source commit
before continuing to step 3. The new script does not match the old release
installer checksum. It still downloads and checks the original app ZIP against
the release's unchanged `SHA256SUMS`. Keep the published assets unchanged.

Completion criterion: record the reviewed installer source commit and authorized
release tag. Use the reviewed script with that exact tag in step 3.

## 3. Install the selected release

For the authorized beta example, run:

```sh
if app_path=$(/bin/bash ./install.sh \
	--version "$release_version" \
	--allow-development \
	--prefix "$HOME/Applications/MobileCapture"); then
	install_status=0
else
	install_status=$?
fi
printf 'Installer exit: %s\nApp path: %s\n' "$install_status" "$app_path"
```

For an authorized stable tag, set `release_version` to that exact tag and omit
`--allow-development`. The installer never selects a version for you. Run
`/bin/bash ./install.sh --help` to inspect its options.

`--prefix` must be an absolute, writable directory. Its default is
`$HOME/Applications/MobileCapture`. The installed path is
`$prefix/$release_version/Mobile Capture.app`. The installer needs neither root
nor `sudo`. It does not launch the app or run Doctor.

On exit `0` or `20`, stdout contains one absolute app path. Guidance goes to
stderr. Preserve the path even when the exit is `20`.

| Installer exit | Result and next action |
| --- | --- |
| `0` | The app is installed, or an identical copy exists. macOS assessment permits execution. Continue to Doctor. |
| `20` | The app is installed, but macOS approval requires the user. Hand off the macOS message and app path. Resume after the user completes the normal macOS approval process. |
| `64` | Arguments, release policy, or Mac platform are invalid. Correct the request. |
| `65` | Artifact, checksum, archive, signature, or app metadata verification failed. Stop and report the failure. |
| `69` | Release lookup or download failed. Check the exact tag and network access. |
| `73` | The destination is unsafe or contains a conflicting copy. Choose a separate writable prefix. |
| `75` | Another installer holds the lock for this tag. Wait for that installation to finish. |

Never remove quarantine, disable Gatekeeper, or re-sign the app to get past a
failure. Development consent does not bypass macOS approval.

An identical repeat installation is safe. A conflicting destination is rejected
rather than overwritten. Keep any copy that owns an active or recoverable
recording. Finish or recover that session in its owning app before starting a
capture in another version. Installation does not interrupt or migrate it.

Beta packages with the updater expose **Check for Updates…** in the app menu and
Settings. Automatic checks start off. Existing `v0.1.1-beta.1` needs a one-time
install to gain the updater. Installing an app does not authorize an update.

Sparkle updates the installed app in place. A version-named parent directory
records the installation origin after an update. Read the app's metadata for its
current version and build. Re-running the original exact-tag installer after an
update safely reports conflict `73`. Install an exact requested tag separately.

Completion criterion: record the installer exit and app path. Exit `20` is an
installed app awaiting human approval, not permission to run a blocked binary.

## 4. Check the Mac with JSON Doctor

After macOS permits execution, choose the requested platform and sources. For
Android network capture prerequisites, run:

```sh
if "$app_path/Contents/MacOS/mobile-capture-host" doctor \
	--json --platform android --sources network; then
	doctor_status=0
else
	doctor_status=$?
fi
printf 'Doctor exit: %s\n' "$doctor_status" >&2
```

Use `--platform iphone` for a physical iPhone or `--platform simulator` for iOS
Simulator. `--sources` accepts `network`, `logs`, or `network,logs` and defaults to
`network`. To check a chosen output location, append
`--output-directory "/absolute/path/to/existing/private/folder"`.
Unknown or duplicate arguments and relative output paths fail before tool checks.

Doctor checks local tool versions, capabilities, architecture, app integrity,
and storage. It does not discover or pair phones, start capture, install tools,
apply repairs, modify trust, or change routing. Report repair suggestions to the
user as proposals. A physical iPhone can report missing external USB tools even
when the complete app is installed. Simulator checks can report missing Xcode.
Some Xcode versions provide a `simctl` shell launcher that can perform first-run
setup. Doctor locates the selected tool but does not execute that launcher; it
can report incompatible even with Xcode installed. Hand this result to an engineer
instead of installing or rewriting tools automatically.

| Doctor exit | Meaning |
| --- | --- |
| `0` | The Mac prerequisites for the requested platform and sources are ready. |
| `10` | One or more Mac prerequisites need action. Read `checks` and `repairs`. |
| `64` | The arguments are invalid. |
| `70` | Doctor cannot resolve its owning app or encountered an internal failure. |

Doctor emits exactly one JSON object with sorted keys and a final newline,
including handled errors. The required envelope is:

| Key | Value |
| --- | --- |
| `schemaVersion` | `1` |
| `command` | `"doctor"` |
| `scope` | `"macPrerequisites"` |
| `platform` | `"android"`, `"iphone"`, `"simulator"`, or `null` |
| `captureNetwork`, `captureLogs` | Booleans for the requested sources |
| `appPath` | The resolved owning app's absolute path, or `null` |
| `checkedAt` | An ISO 8601 timestamp, or `null` |
| `macPrerequisitesReady` | `true`, `false`, or `null` when unavailable |
| `checks` | The service's check rows |
| `repairs` | Sorted repair identifiers suggested by the service |
| `deviceSetup` | `{"status":"notChecked","manualActions":["..."]}` with actual manual action strings |
| `error` | `null` or `{"code":"...","message":"..."}` with the actual error |

Unavailable nullable envelope values remain present as `null`. A check row has `id`,
`title`, `status`, `message`, and `source`, with optional `version`, `path`, and
`repair`. Check status is `ready`, `needsAction`, `missing`, or `incompatible`.
Source is `bundled`, `external`, `system`, or `none`.

Completion criterion: retain the JSON and exit code. Report Mac readiness only
for the platform and sources you checked. A launch blocked by macOS produces no
Doctor result, so report the approval handoff instead of inferring readiness.

## 5. Hand off device setup and report the result

`macPrerequisitesReady: true` does not establish device readiness. Doctor always
reports `deviceSetup.status: "notChecked"`. Give the user its `manualActions` and
the relevant [device setup instructions](https://github.com/raymondctc/mobile-capture/blob/main/docs/CAPTURE.md).
The user must handle USB authorization or pairing, certificate installation and
trust, and any phone VPN or WireGuard settings. These actions require a separate
setup decision. Starting a capture requires a separate request.

Report the exact release tag and channel, installer exit, app path, Doctor exit,
Mac readiness, unmet check messages, and remaining manual device actions. State
whether macOS approval prevented Doctor. A successful installation alone is not
a successful Mac check or a successful phone setup.

## Resolve setup failures

- If a tag or asset is missing, stop at release selection. Do not substitute a
  different version or channel.
- If integrity verification fails, retain the error and download a fresh copy
  from the selected release for investigation. Do not patch the app bundle.
- If the destination conflicts, use a different prefix. The installer does not
  migrate sessions, certificates, profiles, or recovery ownership.
- If a lock remains after an interrupted install, report its location for
  inspection. Do not steal a lock from another installer.
- If Doctor suggests a reinstall, use a complete trusted app release. Installing
  Homebrew or Python does not repair a damaged bundled component.
- If an agent sandbox restricts a launch or storage probe, report that restriction.
  Recheck with permitted read-only host execution before concluding tools or disk
  space are missing. Keep macOS protections enabled.
- If storage needs action, choose an existing private writable local folder with
  at least 512 MB free and rerun Doctor with `--output-directory`.

Fresh-Mac and physical-device acceptance are separate checks. Do not claim either
from an installer exit, a Doctor report, or this guide's examples.
