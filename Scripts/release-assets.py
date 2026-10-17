#!/usr/bin/env python3
"""Validate release metadata and stage only verified user-download assets."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shutil
import zipfile
from beta_updates import BETA_TAG, archive_info, build_number, policy, validate_info

TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(?:alpha|beta|rc)\.[1-9][0-9]*)?")
ROOT = Path(__file__).resolve().parents[1]
SUPPORT_ASSETS = {"install.sh": "Scripts/install.sh", "AGENT_SETUP.md": "docs/AGENT_SETUP.md"}
SIGNING = ("APPLE_CERTIFICATE_P12_BASE64", "APPLE_CERTIFICATE_PASSWORD", "APPLE_TEAM_ID",
           "CAPTURE_BUNDLE_IDENTIFIER", "APPLE_NOTARY_KEY_P8_BASE64", "APPLE_NOTARY_KEY_ID", "APPLE_NOTARY_ISSUER_ID")

def plan(event):
    ref = event.get("ref", "")
    if not ref.startswith("refs/tags/") or event.get("deleted") is not False:
        raise ValueError("Push a version tag; branch pushes and tag deletions do not publish releases")
    tag = ref[len("refs/tags/"):]
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError("Use vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-beta.1")
    prerelease = "-" in tag
    return {"tag": tag, "version": ".".join(match.groups()[:3]),
            "mode": "development" if prerelease else "release",
            "prerelease": "true" if prerelease else "false"}

def check_signing(environment):
    missing = [key for key in SIGNING if not environment.get(key)]
    if missing:
        raise ValueError("Stable releases require Apple signing/notarization configuration: " + ", ".join(missing))
    identifier = environment["CAPTURE_BUNDLE_IDENTIFIER"]
    if identifier.startswith("local.") or not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", identifier):
        raise ValueError("CAPTURE_BUNDLE_IDENTIFIER must be your owner-controlled release identity")

def ci_build_number(run_number, run_attempt):
    if not 1 <= run_attempt <= 999 or run_number < 1:
        raise ValueError("CI run number must be positive and run attempt must be between 1 and 999")
    return build_number(str(run_number * 1000 + run_attempt))


def stage(package, output, version, mode, tag=None):
    if mode not in {"development", "release"} or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Invalid package version or signing mode")
    source = package / f"MobileCapture-{version}-arm64-{mode}.zip"
    expected = (package / "SHA256SUMS").read_text().strip().split()
    with source.open("rb") as stream:
        checksum = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
        digest = checksum.hexdigest()
    if expected != [digest, source.name]:
        raise ValueError("Package ZIP does not match SHA256SUMS")
    with zipfile.ZipFile(source) as archive:
        if archive.testzip():
            raise ValueError("Package ZIP failed its integrity check")
        if "Mobile Capture.app/Contents/Info.plist" not in archive.namelist():
            raise ValueError("The ZIP must contain Mobile Capture.app, not source code")
        info = plistlib.loads(archive.read("Mobile Capture.app/Contents/Info.plist"))
    if info.get("CFBundleShortVersionString") != version or info.get("MobileCaptureCompanion") is not True:
        raise ValueError("App metadata does not match the requested release")
    if info.get("MobileCaptureDevelopmentIdentity") is not (mode == "development"):
        raise ValueError("App signing mode does not match the requested release")
    if tag and BETA_TAG.fullmatch(tag):
        archive_info(source, policy(), tag)
    else:
        validate_info(info, policy())
        if info.get("CaptureDistributionUpdatesEnabled") is not False:
            raise ValueError("Only beta tags may enable beta updates")
    for relative in SUPPORT_ASSETS.values():
        if not (ROOT / relative).is_file():
            raise ValueError("Release is missing setup asset: " + relative)
    output.mkdir(parents=True, exist_ok=False)
    name = "MobileCapture-macOS-arm64" + ("-development" if mode == "development" else "") + ".zip"
    shutil.copyfile(source, output / name)
    checksums = {name: digest}
    for asset, relative in SUPPORT_ASSETS.items():
        shutil.copyfile(ROOT / relative, output / asset)
        checksums[asset] = hashlib.sha256((output / asset).read_bytes()).hexdigest()
    (output / "install.sh").chmod(0o755)
    (output / "SHA256SUMS").write_text("".join(f"{checksums[asset]}  {asset}\n" for asset in sorted(checksums)))
    return name

def main():
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    metadata = commands.add_parser("plan")
    metadata.add_argument("--event", type=Path, required=True)
    metadata.add_argument("--output", type=Path, required=True)
    metadata.add_argument("--check-signing", action="store_true")
    assets = commands.add_parser("stage")
    assets.add_argument("--package", type=Path, required=True)
    assets.add_argument("--output", type=Path, required=True)
    assets.add_argument("--version", required=True)
    assets.add_argument("--mode", required=True)
    assets.add_argument("--tag")
    build = commands.add_parser("build-number")
    build.add_argument("--run-number", type=int, required=True)
    build.add_argument("--run-attempt", type=int, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        values = plan(json.loads(args.event.read_text()))
        if args.check_signing and values["mode"] == "release":
            check_signing(os.environ)
        with args.output.open("a") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")
    elif args.command == "build-number":
        print(ci_build_number(args.run_number, args.run_attempt))
    else:
        print(stage(args.package, args.output, args.version, args.mode, args.tag))

if __name__ == "__main__":
    main()
