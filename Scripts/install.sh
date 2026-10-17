#!/bin/bash
set -euo pipefail
export LC_ALL=C
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
umask 077

fail() { printf '%s\n' "$2" >&2; exit "$1"; }
usage() {
    cat >&2 <<'HELP'
Usage: /bin/bash install.sh --version vMAJOR.MINOR.PATCH[-alpha.N|-beta.N|-rc.N]
       [--allow-development] [--prefix ABSOLUTE_DIRECTORY]
Installs an exact GitHub release beside other versions. Never launches the app.
Prereleases require --allow-development. Default prefix: $HOME/Applications/MobileCapture
Exit: 0 ready; 20 human macOS approval; 64 arguments/platform; 65 verification;
      69 download/release; 73 destination conflict; 75 install lock.
HELP
}

tag= prefix=${HOME:?HOME must be set}/Applications/MobileCapture development=false
seen_version=false seen_prefix=false seen_development=false
while (( $# )); do
    case "$1" in
        --help) (( $# == 1 )) || fail 64 '--help must be used alone.'; usage; exit 0 ;;
        --version)
            [[ "$seen_version" == false && $# -ge 2 ]] || fail 64 'Specify --version once with a value.'
            tag=$2; seen_version=true; shift 2 ;;
        --prefix)
            [[ "$seen_prefix" == false && $# -ge 2 ]] || fail 64 'Specify --prefix once with a value.'
            prefix=$2; seen_prefix=true; shift 2 ;;
        --allow-development)
            [[ "$seen_development" == false ]] || fail 64 'Specify --allow-development once.'
            development=true; seen_development=true; shift ;;
        *) fail 64 "Unknown argument: $1" ;;
    esac
done
[[ "$tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-(alpha|beta|rc)\.[1-9][0-9]*)?$ ]] || fail 64 'An exact --version vMAJOR.MINOR.PATCH[-beta.N] is required.'
version=${tag#v}; version=${version%%-*}
prerelease=false; [[ "$tag" != *-* ]] || prerelease=true
[[ "$prerelease" == false || "$development" == true ]] || fail 64 'Prereleases require explicit --allow-development consent.'
[[ "$prefix" == /* && "$prefix" != *[$'\001'-$'\037'$'\177']* && "$prefix" != *\\* ]] || fail 64 '--prefix must be an absolute path without control characters or backslashes.'
while [[ "$prefix" == */ && "$prefix" != / ]]; do prefix=${prefix%/}; done
[[ "$prefix" != / && "$prefix/" != *'/../'* && "$prefix/" != *'/./'* && "$prefix" != *//* ]] || fail 64 'Use a normalized absolute installation prefix.'
[[ "$(/usr/bin/uname -s)" == Darwin && "$(/usr/bin/uname -m)" == arm64 ]] || fail 64 'This release requires Apple Silicon macOS.'
os_version=$(/usr/bin/sw_vers -productVersion)
[[ "${os_version%%.*}" =~ ^[0-9]+$ && "${os_version%%.*}" -ge 26 ]] || fail 64 'This release requires macOS 26 or later.'
[[ "$EUID" -ne 0 ]] || fail 64 'Run as your normal user, without sudo.'

part= rest=${prefix#/}
while [[ -n "$rest" ]]; do
    component=${rest%%/*}; part=$part/$component
    [[ "$rest" == */* ]] && rest=${rest#*/} || rest=
    [[ ! -L "$part" ]] || fail 73 "Installation prefix contains a symlink: $part"
    if [[ -e "$part" ]]; then
        [[ -d "$part" ]] || fail 73 "Installation prefix contains a non-directory: $part"
        owner=$(/usr/bin/stat -f %u "$part")
        mode=$(/usr/bin/stat -f %p "$part")
        [[ "$owner" == 0 || "$owner" == "$EUID" ]] || fail 73 "Installation ancestor belongs to another user: $part"
        (( (8#$mode & 0022) == 0 || (owner == 0 && (8#$mode & 01000) != 0) )) || fail 73 "Installation ancestor is writable by other users: $part"
        /bin/ls -lde "$part" | /usr/bin/awk 'NR > 1 && / allow / {exit 1}' || fail 73 "Installation ancestor has an access-granting ACL: $part"
    else
        /bin/mkdir "$part" 2>/dev/null || fail 73 "Cannot create installation directory: $part"
    fi
done
[[ "$(/usr/bin/stat -f %u "$prefix")" == "$EUID" ]] || fail 73 'Installation prefix must belong to your user.'
permissions=$(/usr/bin/stat -f %Lp "$prefix")
(( (8#$permissions & 0022) == 0 )) || fail 73 'Installation prefix must not be writable by other users.'
[[ -w "$prefix" ]] || fail 73 'Installation prefix is not writable.'
lock=$prefix/.install-$tag.lock
/bin/mkdir "$lock" 2>/dev/null || fail 75 "Installation lock exists or cannot be created. Inspect manually: $lock"
stage=
cleanup() {
    [[ -z "$stage" ]] || /bin/rm -rf "$stage"
    /bin/rmdir "$lock" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
stage=$(/usr/bin/mktemp -d "$prefix/.install-$tag.XXXXXXXX") || fail 73 'Cannot create private staging directory.'

fetch() {
    local url=$1 output=$2 maximum=$3
    /usr/bin/curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --tlsv1.2 --connect-timeout 15 --max-time 300 --retry 2 --retry-max-time 60 \
        --max-filesize "$maximum" --output "$output" "$url" >&2 || fail 69 "Download failed: $url"
    [[ -f "$output" && "$(/usr/bin/stat -f %z "$output")" -le "$maximum" ]] || fail 69 'Downloaded asset exceeded its size limit.'
}
json() { /usr/bin/plutil -extract "$2" raw -expect "$3" -o - "$1" 2>/dev/null; }
release=$stage/release.json
fetch "https://api.github.com/repos/am5a03/mobile-capture/releases/tags/$tag" "$release" 2097152
[[ "$(json "$release" tag_name string)" == "$tag" && "$(json "$release" draft bool)" == false && "$(json "$release" prerelease bool)" == "$prerelease" && "$(json "$release" html_url string)" == "https://github.com/am5a03/mobile-capture/releases/tag/$tag" ]] || fail 69 'Release metadata does not match the requested public tag.'
archive=MobileCapture-macOS-arm64.zip
[[ "$prerelease" == false ]] || archive=MobileCapture-macOS-arm64-development.zip
asset_count=$(json "$release" assets array) || fail 69 'Release assets are missing.'
[[ "$asset_count" =~ ^[0-9]+$ && "$asset_count" -le 100 ]] || fail 69 'Invalid release asset count.'
for expected in "$archive" SHA256SUMS; do
    found=0
    for ((i=0; i<asset_count; i++)); do
        name=$(json "$release" "assets.$i.name" string) || fail 69 'Invalid release asset name.'
        [[ "$name" == "$expected" ]] || continue
        found=$((found + 1))
        url=$(json "$release" "assets.$i.browser_download_url" string) || fail 69 'Missing release asset URL.'
        [[ "$url" == "https://github.com/am5a03/mobile-capture/releases/download/$tag/$expected" ]] || fail 69 'Unexpected release asset URL.'
        size=$(json "$release" "assets.$i.size" integer) || fail 69 'Missing release asset size.'
        maximum=1073741824; [[ "$expected" != SHA256SUMS ]] || maximum=65536
        [[ "$size" =~ ^[1-9][0-9]*$ && "$size" -le "$maximum" ]] || fail 69 'Invalid release asset size.'
    done
    [[ "$found" == 1 ]] || fail 69 "Release must contain exactly one $expected asset."
    fetch "https://github.com/am5a03/mobile-capture/releases/download/$tag/$expected" "$stage/$expected" "$maximum"
done
/usr/bin/awk -v archive="$archive" '
    NF != 2 || $1 !~ /^[0-9a-f]+$/ || length($1) != 64 {exit 1}
    $2 != archive && $2 != "install.sh" && $2 != "AGENT_SETUP.md" {exit 1}
    seen[$2]++ {exit 1}
    $2 == archive {digest=$1}
    END {if (NR != 3 || length(seen) != 3 || !digest) exit 1; print digest}
' "$stage/SHA256SUMS" > "$stage/expected-hash" || fail 65 'Malformed or incomplete SHA256SUMS.'
actual=$(/usr/bin/shasum -a 256 "$stage/$archive"); actual=${actual%% *}
[[ "$actual" == "$(/bin/cat "$stage/expected-hash")" ]] || fail 65 'ZIP checksum does not match SHA256SUMS.'
[[ "$(/usr/bin/od -An -tx1 -N4 "$stage/$archive" | /usr/bin/tr -d ' \n')" == 504b0304 ]] || fail 65 'Release archive is not a ZIP.'

(ulimit -f 65536; /usr/bin/tar -tf "$stage/$archive" > "$stage/names") 2> "$stage/archive-errors" || fail 65 'Cannot list the ZIP safely.'
(ulimit -f 65536; /usr/bin/tar -tvf "$stage/$archive" > "$stage/entries") 2>> "$stage/archive-errors" || fail 65 'Cannot inspect the ZIP safely.'
[[ ! -s "$stage/archive-errors" ]] || fail 65 'ZIP inspection reported malformed archive data.'
/usr/bin/awk '
    length($0) > 4096 || /[[:cntrl:]\\]/ || /^\// || /(^|\/)\.\.?($|\/)/ || /\/\// {exit 1}
    {name=$0; sub(/\/$/, "", name)}
    name != "Mobile Capture.app" && index(name,"Mobile Capture.app/") != 1 && name != "__MACOSX" && name != "__MACOSX/Mobile Capture.app" && index(name,"__MACOSX/Mobile Capture.app/") != 1 {exit 1}
    seen[name]++ {exit 1}
    END {if (NR < 1 || NR > 100000) exit 1}
' "$stage/names" || fail 65 'ZIP contains unsafe, duplicate, or unexpected paths.'
/usr/bin/awk '
    substr($1,1,1) !~ /^[-dl]$/ || $5 !~ /^[0-9]+$/ {exit 1}
    substr($1,4,1) ~ /[sS]/ || substr($1,7,1) ~ /[sS]/ {exit 1}
    {total += $5; if (total > 4294967296) exit 1}
    END {if (NR < 1 || NR > 100000) exit 1}
' "$stage/entries" || fail 65 'ZIP has unsupported entries or exceeds expansion limits.'
[[ "$(/usr/bin/wc -l < "$stage/names")" == "$(/usr/bin/wc -l < "$stage/entries")" ]] || fail 65 'ZIP entry listings disagree.'
/bin/mkdir "$stage/payload"
# bsdtar default secure extraction rejects writes through symlinks. Never add -P.
(ulimit -f 2097152; /usr/bin/tar -xf "$stage/$archive" -C "$stage/payload" --no-same-owner --no-acls --no-fflags --exclude __MACOSX) >&2 || fail 65 'ZIP extraction failed its safety checks.'
app=$stage/payload/Mobile\ Capture.app
[[ -d "$app" && ! -L "$app" ]] || fail 65 'ZIP does not contain the expected app directory.'
validate_tree() {
    local root=$1 failure=${2:-65} resolved entry
    /usr/bin/find "$root" -print > "$stage/tree"
    while IFS= read -r entry; do
        [[ "$entry" != *[$'\001'-$'\037'$'\177']* && "$entry" != *\\* ]] || fail "$failure" 'Bundle contains an unsafe file name.'
        [[ -f "$entry" || -d "$entry" || -L "$entry" ]] || fail "$failure" 'Bundle contains a special file.'
        if [[ -L "$entry" ]]; then
            resolved=$(/bin/realpath "$entry" 2>/dev/null) || fail "$failure" 'Bundle contains a broken or cyclic symlink.'
            [[ "$resolved" == "$root/"* ]] || fail "$failure" 'Bundle symlink escapes its app.'
        fi
    done < "$stage/tree"
}
validate_tree "$app"
plist=$app/Contents/Info.plist
[[ -f "$plist" && ! -L "$plist" ]] || fail 65 'Bundle Info.plist is missing or symlinked.'
[[ "$(json "$plist" CFBundleShortVersionString string)" == "$version" && "$(json "$plist" MobileCaptureCompanion bool)" == true && "$(json "$plist" MobileCaptureDevelopmentIdentity bool)" == "$prerelease" ]] || fail 65 'Bundle version or companion signing mode does not match the release.'
identifier=$(json "$plist" CFBundleIdentifier string) || fail 65 'Missing bundle identifier.'
if [[ "$prerelease" == true ]]; then
    [[ "$identifier" == local.mobilecapture.development ]] || fail 65 'Unexpected development bundle identifier.'
else
    [[ "$identifier" =~ ^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$ && "$identifier" != local.* ]] || fail 65 'Stable release requires an owner-controlled bundle identifier.'
fi
minimum=$(json "$plist" LSMinimumSystemVersion string) || fail 65 'Missing minimum macOS version.'
[[ "$minimum" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || fail 65 'Invalid minimum macOS version.'
/usr/bin/awk -v current="$os_version" -v minimum="$minimum" 'BEGIN {split(current,a,"."); split(minimum,b,"."); for(i=1;i<=3;i++) {if(a[i]+0>b[i]+0) exit 0; if(a[i]+0<b[i]+0) exit 1}}' || fail 64 'This app requires a newer macOS version.'
executable=$(json "$plist" CFBundleExecutable string) || fail 65 'Missing app executable metadata.'
[[ -n "$executable" && "$executable" != */* && "$executable" != . && "$executable" != .. && "$executable" != *[$'\001'-$'\037'$'\177']* ]] || fail 65 'Invalid app executable metadata.'
for binary in "$executable" mobile-capture-host mobile-capture-proxy; do
    path=$app/Contents/MacOS/$binary
    [[ -f "$path" && -x "$path" && ! -L "$path" ]] || fail 65 "Missing native executable: $binary"
    description=$(/usr/bin/file -b "$path")
    [[ "$description" == 'Mach-O 64-bit executable arm64' || "$description" == 'Mach-O 64-bit executable arm64e' ]] || fail 65 "Expected a native Apple Silicon executable: $binary"
done
[[ -f "$app/Contents/Resources/CaptureDependencies/dependencies.json" ]] || fail 65 'Sealed dependency manifest is missing.'
[[ "$(json "$app/Contents/Resources/CaptureDependencies/dependencies.json" architecture string)" == arm64 ]] || fail 65 'Invalid sealed dependency manifest architecture.'
/usr/bin/codesign --verify --deep --strict "$app" >&2 || fail 65 'Strict code signature verification failed.'
/usr/bin/codesign -d --verbose=4 "$app" > "$stage/signature" 2>&1 || fail 65 'Cannot inspect app signing identity.'
/usr/bin/grep -Fx "Identifier=$identifier" "$stage/signature" > /dev/null || fail 65 'Signature identifier does not match app metadata.'
if [[ "$prerelease" == false ]]; then
    /usr/bin/grep -E '^Authority=Developer ID Application: .+' "$stage/signature" > /dev/null || fail 65 'Stable app is not signed with Developer ID Application.'
fi
assessment=0
/usr/sbin/spctl --assess --type execute --verbose=4 "$app" > "$stage/assessment" 2>&1 || assessment=$?
if [[ "$prerelease" == false ]]; then
    [[ "$assessment" == 0 ]] || fail 65 'Stable release did not pass macOS execution assessment.'
    /usr/bin/grep -Fx 'source=Notarized Developer ID' "$stage/assessment" > /dev/null || fail 65 'Stable app assessment did not confirm notarization.'
fi
fingerprint() {
    (cd "$1" && /usr/bin/find . -type f -exec /usr/bin/shasum -a 256 {} + && /usr/bin/find . -exec /usr/bin/stat -f '%Sp %N%SY' {} \;) | /usr/bin/sort
}
final=$prefix/$tag
if [[ -e "$final" || -L "$final" ]]; then
    [[ -d "$final" && ! -L "$final" && "$(/usr/bin/stat -f %u "$final")" == "$EUID" ]] || fail 73 'Existing version destination is unsafe.'
    existing=$final/Mobile\ Capture.app
    [[ -d "$existing" && ! -L "$existing" ]] || fail 73 'Existing version is incomplete.'
    validate_tree "$existing" 73
    [[ "$(/usr/bin/find "$final" -mindepth 1 -maxdepth 1 | /usr/bin/wc -l | /usr/bin/tr -d ' ')" == 1 ]] || fail 73 'Existing version contains unexpected content.'
    fingerprint "$app" > "$stage/new-fingerprint"
    fingerprint "$existing" > "$stage/existing-fingerprint"
    /usr/bin/cmp -s "$stage/new-fingerprint" "$stage/existing-fingerprint" || fail 73 'Existing version differs. No installed app was replaced.'
    printf 'Identical version already installed.\n' >&2
else
    /bin/mv -n "$stage/payload" "$final" || fail 73 'Cannot publish completed installation.'
    [[ ! -e "$stage/payload" ]] || fail 73 'Version destination appeared during publication.'
fi
installed=$final/Mobile\ Capture.app
printf '%s\n' "$installed"
printf 'Installed %s. Doctor command after macOS permits execution:\n' "$tag" >&2
printf '  %q doctor --json --platform android\n' "$installed/Contents/MacOS/mobile-capture-host" >&2
if [[ "$assessment" != 0 ]]; then
    printf 'Human macOS approval is required. Review the app in System Settings > Privacy & Security. No app or Doctor command was launched.\n' >&2
    /bin/cat "$stage/assessment" >&2
    exit 20
fi
