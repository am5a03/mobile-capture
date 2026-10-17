#!/bin/bash
# Credentials exist only on a fresh GitHub-hosted runner, never on a developer Mac.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_ENVIRONMENT:-}" == github-hosted && "${RUNNER_TEMP:-}" == /* ]] || { echo "Signing setup requires a GitHub-hosted runner." >&2; exit 2; }
keychain="$RUNNER_TEMP/mobile-capture-signing.keychain-db"
certificate="$RUNNER_TEMP/mobile-capture-signing.p12"
notary_key="$RUNNER_TEMP/mobile-capture-notary.p8"
if [[ "${1:-}" == cleanup ]]; then
  if [[ -f "$keychain" ]]; then /usr/bin/security delete-keychain "$keychain"; fi
  rm -f "$certificate" "$notary_key"
  exit 0
fi
[[ "${1:-}" == prepare ]] || { echo "Usage: configure-release-signing.sh prepare|cleanup" >&2; exit 2; }
umask 077
python3 - <<'DECODE'
import base64, importlib.util, os
from pathlib import Path
spec=importlib.util.spec_from_file_location("release_assets", "Scripts/release-assets.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.check_signing(os.environ)
for key, name in [("APPLE_CERTIFICATE_P12_BASE64", "mobile-capture-signing.p12"), ("APPLE_NOTARY_KEY_P8_BASE64", "mobile-capture-notary.p8")]:
    value="".join(os.environ[key].split())
    (Path(os.environ["RUNNER_TEMP"])/name).write_bytes(base64.b64decode(value, validate=True))
DECODE
password=$(/usr/bin/openssl rand -hex 32)
/usr/bin/security create-keychain -p "$password" "$keychain"
/usr/bin/security set-keychain-settings -lut 21600 "$keychain"
/usr/bin/security unlock-keychain -p "$password" "$keychain"
/usr/bin/security import "$certificate" -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign -t cert -f pkcs12 -k "$keychain"
/usr/bin/security set-key-partition-list -S apple-tool:,apple:,codesign: -k "$password" "$keychain" > /dev/null
/usr/bin/security list-keychains -d user -s "$keychain"
xcrun notarytool store-credentials mobile-capture-ci --key "$notary_key" \
  --key-id "$APPLE_NOTARY_KEY_ID" --issuer "$APPLE_NOTARY_ISSUER_ID" --keychain "$keychain"
rm -f "$certificate" "$notary_key"
