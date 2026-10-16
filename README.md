# Mobile Capture

A standalone macOS companion for collecting Android and iOS device logs and full
HTTP(S) requests/responses in one shared timeline, then exporting one evidence ZIP.
It is generic and does not require Oh My Android or a company-specific app.

Connect a device, choose device logs and/or network capture, start recording,
reproduce the behavior, then choose **Stop & Save**. Add time markers, filter and
inspect the timeline, and share the exported package with an engineer. First-run
**Device Setup** guides certificate/profile installation; **Doctor** checks the
Mac's capture components. Certificate trust and phone VPN toggles remain explicit
phone-side steps.

Supported development routes: Android devices/emulators, iOS Simulator, and
physical iPhones using USB log tools plus WireGuard for network capture. Logs are
app-scoped and bounded by default; network capture retains full admitted bodies.
The upper **Capture Details** panel scrolls and collapses while preserving the
timeline's reading position and selected event.

## Build

The current development target is **macOS 26 / Apple Silicon**, with **Xcode
with Swift 6.3 (validated with Xcode 26.6)** and XcodeGen. This repository has no Swift package dependencies
and contains only the capture app and its two native helpers.

```sh
git clone https://github.com/am5a03/mobile-capture.git
cd mobile-capture
brew install xcodegen
xcodegen generate
xcodebuild -project MobileCapture.xcodeproj -scheme MobileCapture \
  -configuration Debug -derivedDataPath build/DerivedData CODE_SIGN_IDENTITY=- build
```

The generated `MobileCapture.xcodeproj` can also be opened in Xcode. This quick
build does **not** populate the signed bundled-tool payload. In an unpackaged
build, source-development paths can use installed tools, but Doctor's bundled
component checks can report missing components even when this Mac has ADB/Python.
Use a complete development package to test first-run setup and Doctor.

### Complete development package

Prepare the reviewed external dependency cache as described in
[distribution](docs/CAPTURE-DISTRIBUTION.md#prepare-the-external-cache), then run:

```sh
CAPTURE_DEPENDENCY_CACHE="$HOME/Library/Caches/MobileCapture/Dependencies" \
  Scripts/release-mobile-capture.sh --development
```

The timestamped `dist/` folder contains the signed app, ZIP and SHA256SUMS. It
bundles the pinned network engine with its own Python and Android tools, runs
signature/tool/Doctor checks, and never publishes a release. Development packages
are ad-hoc signed and not notarized. Dependency binaries are not stored in Git.
Physical iPhone USB utilities are external by default; an explicit experimental
local-bundle option is documented in the distribution guide.

## Tests

```sh
bash Scripts/test-all.sh
# Or one group:
bash Scripts/test-all.sh timeline
```

Groups are `core`, `services`, `timeline` and `python`. These use fake tools,
isolated fixtures and loopback checks; they do not capture from connected phones
or install certificates. Optional real-engine tests require
`CAPTURE_TEST_MITMDUMP`. CI builds the app/helpers and runs all four groups.
Hardware and fresh-Mac acceptance remain separate.

## Documentation

- [Capture usage and platform limitations](docs/CAPTURE.md)
- [Build, dependency packaging and distribution](docs/CAPTURE-DISTRIBUTION.md)
- [Evidence package format](docs/CAPTURE-PACKAGE.md)
- [Native runtime architecture](docs/CAPTURE-NATIVE-RUNTIME.md)
- [First-run setup and Doctor](docs/CAPTURE-SETUP-IMPLEMENTATION.md)
- [Logging policy and validation](docs/CAPTURE-LOGGING-VALIDATION.md)
- [Planned MCP interface](docs/CAPTURE-MCP-PLAN.md)
- [Repository migration and source provenance](docs/REPOSITORY-MIGRATION.md)

Implementation/proof reports describe their recorded checkpoint; they are not
claims that every later change or every device has passed hardware acceptance.
Public distribution still needs a permanent release identity/icon, Developer ID
signing/notarization, fresh-Mac setup validation and resolution of the recorded
WireGuard engine shutdown issue. HTTPS capture also depends on app proxy behavior
and CA trust; pinning, QUIC and IPv6 can leave gaps. Captures can contain private
data. Evidence stays local unless you explicitly share it.

## Oh My Android integration

[Oh My Android](https://github.com/am5a03/oh-my-android) is optional and can launch
an installed compatible Mobile Capture app with a device/app preselection. This
repository preserves its versioned `mobilecapture://` launch contract and existing
local-development identity. It does not change session locations, certificate
stores or private WireGuard profiles. Finish/recover an active recording in its
owning app before replacing that copy.

## License and origin

MIT. Extracted from the Mobile Capture work in
[am5a03/oh-my-android](https://github.com/am5a03/oh-my-android), originally forked
from Royan AB's Oh My Android. The original copyright and license are retained in
[LICENSE](LICENSE). Imported-file provenance is recorded in
[docs/SOURCE-ORIGIN.json](docs/SOURCE-ORIGIN.json). Dependency licenses and pinned
packaging metadata live under `Dependencies/Capture/`.
