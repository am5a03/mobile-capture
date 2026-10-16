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

TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(?:alpha|beta|rc)\.[1-9][0-9]*)?")
SIGNING = ("APPLE_CERTIFICATE_P12_BASE64", "APPLE_CERTIFICATE_PASSWORD", "APPLE_TEAM_ID",
           "CAPTURE_BUNDLE_IDENTIFIER", "APPLE_NOTARY_KEY_P8_BASE64", "APPLE_NOTARY_KEY_ID", "APPLE_NOTARY_ISSUER_ID")

def plan(event):
    release = event.get("release", {})
    tag = release.get("tag_name", "")
    match = TAG.fullmatch(tag)
    if event.get("action") != "published" or release.get("draft") is not False or not match:
        raise ValueError("Publish a release tagged vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-beta.1")
    prerelease = release.get("prerelease")
    if not isinstance(prerelease, bool) or prerelease != ("-" in tag):
        raise ValueError("Prerelease tags and the GitHub prerelease checkbox must agree")
    return {"tag": tag, "version": ".".join(match.groups()[:3]),
            "mode": "development" if prerelease else "release"}

def check_signing(environment):
    missing = [key for key in SIGNING if not environment.get(key)]
    if missing:
        raise ValueError("Stable releases require Apple signing/notarization configuration: " + ", ".join(missing))
    identifier = environment["CAPTURE_BUNDLE_IDENTIFIER"]
    if identifier.startswith("local.") or not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", identifier):
        raise ValueError("CAPTURE_BUNDLE_IDENTIFIER must be your owner-controlled release identity")

def stage(package, output, version, mode):
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
    output.mkdir(parents=True, exist_ok=False)
    name = "MobileCapture-macOS-arm64" + ("-development" if mode == "development" else "") + ".zip"
    shutil.copyfile(source, output / name)
    (output / "SHA256SUMS").write_text(f"{digest}  {name}\n")
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
    args = parser.parse_args()
    if args.command == "plan":
        values = plan(json.loads(args.event.read_text()))
        if args.check_signing and values["mode"] == "release":
            check_signing(os.environ)
        with args.output.open("a") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")
    else:
        print(stage(args.package, args.output, args.version, args.mode))

if __name__ == "__main__":
    main()
