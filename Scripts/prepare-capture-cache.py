#!/usr/bin/env python3
"""Fetch reviewed official archives and populate the verified build-only cache."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent

def digest(path):
    with path.open("rb") as stream:
        checksum = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
        return checksum.hexdigest()

def download(record, directory):
    url = urllib.parse.urlparse(record["url"])
    if url.scheme != "https" or url.hostname not in {"downloads.mitmproxy.org", "dl.google.com"}:
        raise ValueError("Dependency download must use a reviewed official HTTPS host")
    filename = record["filename"]
    if Path(filename).name != filename or not filename:
        raise ValueError("Dependency archive must have a plain filename")
    destination = directory / filename
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with urllib.request.urlopen(record["url"], timeout=60) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            if digest(temporary) != record["sha256"]:
                raise ValueError(f"Archive checksum mismatch: {filename}")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    if digest(destination) != record["sha256"]:
        raise ValueError(f"Archive checksum mismatch: {filename}")
    return destination

def prepare(cache_root, archives_directory):
    source_lock = ROOT / "Dependencies/Capture/dependencies-arm64.lock.json"
    download_lock = json.loads((ROOT / "Dependencies/Capture/downloads-arm64.lock.json").read_text())
    if download_lock["schemaVersion"] != 1 or download_lock["dependencyLockSHA256"] != digest(source_lock):
        raise ValueError("Download lock does not match the reviewed dependency lock")
    dependency = json.loads(source_lock.read_text())
    records = {item["name"]: item for item in download_lock["archives"]}
    if set(records) != {"mitmproxy", "platform-tools"}:
        raise ValueError("Download lock must contain the two reviewed archives")
    engine = records["mitmproxy"]
    if engine["url"] != dependency["mitmproxyArchiveURL"] or engine["sha256"] != dependency["mitmproxyArchiveSHA256"]:
        raise ValueError("Network engine archive differs from the reviewed dependency lock")
    cached = cache_root / (digest(source_lock) + "-" + dependency["architecture"])
    command = ["swift", str(ROOT / "Scripts/bundle-capture-dependencies.swift"), "cache", "--cache-root", str(cache_root)]
    if cached.exists():
        # The existing packager rechecks every file hash before accepting a cache hit.
        subprocess.run(command + ["--mitmproxy-app", str(cached / "mitmproxy.app"),
                                  "--platform-tools", str(cached / "platform-tools")], check=True)
        return
    archives_directory.mkdir(parents=True, exist_ok=True)
    engine_archive = download(engine, archives_directory)
    tools_archive = download(records["platform-tools"], archives_directory)
    with tempfile.TemporaryDirectory(prefix="capture-dependencies-") as work:
        extracted = Path(work)
        # Only archives with the exact reviewed SHA256 reach extraction.
        subprocess.run(["/usr/bin/tar", "-xzf", str(engine_archive), "-C", str(extracted)], check=True)
        subprocess.run(["/usr/bin/ditto", "-x", "-k", str(tools_archive), str(extracted)], check=True)
        subprocess.run(command + ["--mitmproxy-app", str(extracted / "mitmproxy.app"),
                                  "--platform-tools", str(extracted / "platform-tools")], check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--archives-directory", type=Path)
    args = parser.parse_args()
    cache = args.cache_root.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    if args.archives_directory:
        prepare(cache, args.archives_directory.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="capture-downloads-") as temporary:
            prepare(cache, Path(temporary))

if __name__ == "__main__":
    main()
