#!/bin/zsh
# Prepare the standalone local product. Nothing is uploaded or published.
set -euo pipefail
cd "$(dirname "$0")/.."
MODE=release
NOTARIZE=1
USB_CANDIDATE=0
for argument in "$@"; do
  case "$argument" in
    --development) MODE=development; NOTARIZE=0 ;;
    --skip-notarize) NOTARIZE=0 ;;
    --mobile-capture) ;; # Retained for the named wrapper and earlier build instructions.
    --experimental-iphone-usb) USB_CANDIDATE=1 ;;
    *) print -u2 "Usage: Scripts/release.sh [--development | --skip-notarize] [--experimental-iphone-usb]"; exit 2 ;;
  esac
done
if (( USB_CANDIDATE )) && [[ "$MODE" != development ]]; then
  print -u2 "The experimental iPhone USB candidate is available only for a development build."
  exit 2
fi
IDENTITY=-
BUILD_OPTIONS=()
if [[ -n "${CAPTURE_RELEASE_VERSION:-}" ]]; then
  [[ "$CAPTURE_RELEASE_VERSION" =~ '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' ]] || { print -u2 "CAPTURE_RELEASE_VERSION must be MAJOR.MINOR.PATCH."; exit 2; }
  BUILD_OPTIONS+=("MARKETING_VERSION=$CAPTURE_RELEASE_VERSION")
fi
if [[ -n "${CAPTURE_BUILD_NUMBER:-}" ]]; then
  [[ "$CAPTURE_BUILD_NUMBER" =~ '^[1-9][0-9]*$' ]] || { print -u2 "CAPTURE_BUILD_NUMBER must be a positive integer."; exit 2; }
  BUILD_OPTIONS+=("CURRENT_PROJECT_VERSION=$CAPTURE_BUILD_NUMBER")
fi
SCHEME=MobileCapture
BUNDLE="Mobile Capture.app"
ARTIFACT=MobileCapture
ENTITLEMENTS=Sources/MobileCaptureApp/MobileCapture.entitlements
CAPTURE_DEPENDENCY_CACHE=${CAPTURE_DEPENDENCY_CACHE:-$HOME/Library/Caches/MobileCapture/Dependencies}
[[ -d "$CAPTURE_DEPENDENCY_CACHE" ]] || { print -u2 "Prepare the pinned dependency cache first. See docs/CAPTURE-DISTRIBUTION.md."; exit 1; }
if [[ "$MODE" == release ]]; then
  CAPTURE_BUNDLE_IDENTIFIER=${CAPTURE_BUNDLE_IDENTIFIER:?Set your owner-controlled capture bundle ID for release; local.mobilecapture.development is for development only}
  [[ "$CAPTURE_BUNDLE_IDENTIFIER" != local.* && "$CAPTURE_BUNDLE_IDENTIFIER" == *.* && "$CAPTURE_BUNDLE_IDENTIFIER" != *[^A-Za-z0-9.-]* ]] || { print -u2 "Choose an owner-controlled reverse-DNS capture bundle identifier, not the provisional local identity."; exit 1; }
  BUILD_OPTIONS+=("MOBILE_CAPTURE_BUNDLE_IDENTIFIER=$CAPTURE_BUNDLE_IDENTIFIER")
  TEAM_ID=${TEAM_ID:?Set TEAM_ID to your own Apple Developer team ID, or use --development}
  IDENTITY=$(/usr/bin/security find-identity -v -p codesigning | /usr/bin/awk -v team="($TEAM_ID)" '/Developer ID Application/ && index($0, team) { print $2; exit }')
  [[ -n "$IDENTITY" ]] || { print -u2 "No Developer ID Application identity for the selected team. iOS certificates cannot sign this Mac release."; exit 1; }
fi
DERIVED="build/${ARTIFACT}Distribution/$MODE"
BUILD="$DERIVED/Build/Products/Release"
mkdir -p "$DERIVED"
xcodegen generate > "$DERIVED/generate.log" 2>&1
if ! xcodebuild -project MobileCapture.xcodeproj -scheme "$SCHEME" -configuration Release \
    -derivedDataPath "$DERIVED" ARCHS=arm64 ONLY_ACTIVE_ARCH=YES CODE_SIGNING_ALLOWED=NO \
    "${BUILD_OPTIONS[@]}" build > "$DERIVED/build.log" 2>&1; then
  /usr/bin/tail -30 "$DERIVED/build.log" >&2
  exit 1
fi
VERSION=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$BUILD/$BUNDLE/Contents/Info.plist")
STAMP=$(/bin/date -u +%Y%m%d-%H%M%S)
DESTINATION=${CAPTURE_ARTIFACT_DIRECTORY:-"dist/$ARTIFACT-$VERSION-arm64-$MODE-$STAMP"}
DESTINATION=${DESTINATION:A}
[[ ! -e "$DESTINATION" ]] || { print -u2 "Artifact destination already exists: $DESTINATION"; exit 1; }
mkdir -p "$DESTINATION"
/usr/bin/ditto "$BUILD/$BUNDLE" "$DESTINATION/$BUNDLE"
APP="$DESTINATION/$BUNDLE"
/usr/bin/ditto LICENSE "$APP/Contents/Resources/PROJECT-LICENSE.txt"
if [[ "$MODE" == release ]]; then
  /usr/libexec/PlistBuddy -c 'Set :MobileCaptureDevelopmentIdentity false' "$APP/Contents/Info.plist"
fi
swift Scripts/bundle-capture-dependencies.swift install --app "$APP" \
  --cache-root "$CAPTURE_DEPENDENCY_CACHE" --sign "$IDENTITY"
if (( USB_CANDIDATE )); then
  python3 -B Scripts/bundle-iphone-usb-candidate.py install --app "$APP" \
    --lock Dependencies/Capture/iphone-usb-arm64.candidate.lock.json --sign "$IDENTITY"
fi
SIGN=(/usr/bin/codesign --force --sign "$IDENTITY")
if [[ "$MODE" == release ]]; then SIGN+=(--options runtime --timestamp)
else SIGN+=(--options 0 --timestamp=none)
fi
for helper in mobile-capture-host mobile-capture-proxy; do "${SIGN[@]}" "$APP/Contents/MacOS/$helper"; done
"${SIGN[@]}" --entitlements "$ENTITLEMENTS" "$APP"
/usr/bin/codesign --verify --deep --strict "$APP"
python3 -B Scripts/check-capture-product.py --product capture --app "$APP"
swift Scripts/bundle-capture-dependencies.swift smoke --app "$APP" --cache-root "$CAPTURE_DEPENDENCY_CACHE"
DOCTOR_OPTIONS=()
if (( USB_CANDIDATE )); then
  python3 -B Scripts/bundle-iphone-usb-candidate.py smoke --app "$APP"
  DOCTOR_OPTIONS+=(--iphone-usb)
fi
bash Scripts/test-capture-doctor-bundle.sh "$APP" "${DOCTOR_OPTIONS[@]}"
bash Scripts/test-agent-doctor-bundle.sh "$APP" --simulator
ZIP="$ARTIFACT-$VERSION-arm64-$MODE.zip"
(cd "$DESTINATION" && /usr/bin/ditto -c -k --keepParent "$BUNDLE" "$ZIP")
if (( NOTARIZE )); then
  NOTARY_OPTIONS=(--keychain-profile "${NOTARY_PROFILE:-mobile-capture}")
  if [[ -n "${NOTARY_KEYCHAIN:-}" ]]; then NOTARY_OPTIONS+=(--keychain "$NOTARY_KEYCHAIN"); fi
  xcrun notarytool submit "$DESTINATION/$ZIP" "${NOTARY_OPTIONS[@]}" --wait
  xcrun stapler staple "$APP"
  /bin/rm "$DESTINATION/$ZIP"
  (cd "$DESTINATION" && /usr/bin/ditto -c -k --keepParent "$BUNDLE" "$ZIP")
  /usr/sbin/spctl -a -vv "$APP"
fi
(cd "$DESTINATION" && /usr/bin/shasum -a 256 "$ZIP" > SHA256SUMS)
print "Prepared: $DESTINATION/$ZIP"
if [[ "$MODE" == development ]]; then
  print "Development artifact: ad-hoc signed, Apple Silicon, not notarized. No Gatekeeper settings were changed."
elif (( ! NOTARIZE )); then
  print "Developer ID signed; notarization was explicitly skipped."
fi
print "Updates remain disabled pending independent release configuration. No upload or publication was performed."
