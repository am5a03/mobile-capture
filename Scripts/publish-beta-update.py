#!/usr/bin/env python3
"""Prepare and publish signed public beta metadata with the local Keychain key."""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import stat
import tarfile
import tempfile
from urllib.parse import quote
import xml.etree.ElementTree as ET

from beta_updates import ROOT, POLICY_PATH, archive_info, beta_version, build_number, policy, repository, sha256, verify_signatures

SPARKLE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
CAPTURE = "https://mobilecapture.local/xml-namespaces/updates"
ET.register_namespace("sparkle", SPARKLE)
ET.register_namespace("capture", CAPTURE)
ASSET = "MobileCapture-macOS-arm64-development.zip"
MANIFEST_ASSETS = {ASSET, "install.sh", "AGENT_SETUP.md"}
SHA = re.compile(r"[0-9a-f]{40}")
FEED_SIGNATURE = re.compile(rb"<!-- sparkle-signatures:\nedSignature: ([A-Za-z0-9+/]+={0,2})\nlength: ([1-9][0-9]*)\n-->\n?\Z")


def gh(method, endpoint, payload=None, missing=False):
    command = ["gh", "api", "--method", method, endpoint]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None, capture_output=True, text=True)
    if result.returncode:
        if missing and "HTTP 404" in result.stderr:
            return None
        raise ValueError("GitHub API request failed for " + endpoint + ": " + result.stderr.strip())
    return json.loads(result.stdout)


def download(url, path, maximum=1_073_741_824):
    if not url.startswith("https://"):
        raise ValueError("Public downloads require HTTPS")
    subprocess.run(["/usr/bin/curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https", "--tlsv1.2", "--silent", "--show-error", "--connect-timeout", "15", "--max-time", "600", "--max-filesize", str(maximum), "--output", str(path), url], check=True)


def verify_signature(path, signature, config):
    subprocess.run(["/usr/bin/swift", "-module-cache-path", str(Path(tempfile.gettempdir()) / "mobile-capture-beta-signature-module-cache"), str(ROOT / "Scripts/verify-beta-signature.swift"), str(path), config["publicEDKey"], signature], check=True, capture_output=True)


def unsigned_feed(data):
    matches = list(FEED_SIGNATURE.finditer(data))
    if len(matches) != 1 or data.count(b"<!-- sparkle-signatures:") != 1:
        raise ValueError("Appcast must have one final Sparkle signature")
    match = matches[0]
    content = data[:match.start()]
    if len(content) != int(match[2]) or len(base64.b64decode(match[1], validate=True)) != 64:
        raise ValueError("Invalid signed appcast length or signature")
    return content, match[1].decode("ascii")


def verify_feed(data, config):
    content, signature = unsigned_feed(data)
    with tempfile.TemporaryDirectory(prefix="capture-feed-verify-") as temporary:
        path = Path(temporary) / "feed-content"
        path.write_bytes(content)
        verify_signature(path, signature, config)
    return parse_feed(content, config)


def parse_feed(data, config):
    tree = ET.fromstring(data)
    channel = tree.find("channel")
    if tree.tag != "rss" or channel is None or len(tree.findall("channel")) != 1:
        raise ValueError("Appcast must have one RSS channel")
    items = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        tag = item.findtext(f"{{{CAPTURE}}}releaseTag", "")
        version = item.findtext(f"{{{SPARKLE}}}shortVersionString")
        build = build_number(item.findtext(f"{{{SPARKLE}}}version"))
        digest = item.findtext(f"{{{CAPTURE}}}sha256", "")
        commit = item.findtext(f"{{{CAPTURE}}}releaseCommit", "")
        if version != beta_version(tag) or item.findtext(f"{{{SPARKLE}}}channel") != config["channel"] or not re.fullmatch(r"[0-9a-f]{64}", digest) or not SHA.fullmatch(commit):
            raise ValueError("Invalid beta appcast item")
        url = f"https://github.com/{repository(config)}/releases/download/{tag}/{ASSET}"
        if enclosure is None or enclosure.get("url") != url or not re.fullmatch(r"[1-9][0-9]*", enclosure.get("length", "")) or len(base64.b64decode(enclosure.get(f"{{{SPARKLE}}}edSignature", ""), validate=True)) != 64:
            raise ValueError("Appcast enclosure must name a signed exact-tag public archive")
        items.append({"tag": tag, "build": build, "sha256": digest, "commit": commit, "url": url, "signature": enclosure.get(f"{{{SPARKLE}}}edSignature"), "length": int(enclosure.get("length"))})
    if len({item["tag"] for item in items}) != len(items) or len({item["build"] for item in items}) != len(items) or [item["build"] for item in items] != sorted((item["build"] for item in items), reverse=True):
        raise ValueError("Appcast tags and builds must be unique and decrease in feed order")
    return tree, items


def feed_head(config):
    result = gh("GET", f"repos/{repository(config)}/git/ref/heads/{quote(config['feedBranch'], safe='/')}", missing=True)
    return result["object"]["sha"] if result else "absent"


def existing_feed(config, expected):
    current = feed_head(config)
    if current != expected:
        raise ValueError("Feed changed. Re-read its commit and prepare again")
    if current == "absent":
        return None
    result = gh("GET", f"repos/{repository(config)}/contents/{config['feedPath']}?ref={current}")
    data = base64.b64decode(result["content"], validate=False)
    verify_feed(data, config)
    return data


def release_commit(config, tag):
    obj = gh("GET", f"repos/{repository(config)}/git/ref/tags/{tag}")["object"]
    for _ in range(5):
        if obj["type"] == "commit":
            return obj["sha"]
        if obj["type"] != "tag":
            break
        obj = gh("GET", f"repos/{repository(config)}/git/tags/{obj['sha']}")["object"]
    raise ValueError("Release tag does not resolve to a commit")


def fetch_release(config, tag, commit, destination):
    beta_version(tag)
    if not SHA.fullmatch(commit) or release_commit(config, tag) != commit:
        raise ValueError("Release tag does not match the reviewed source commit")
    release = gh("GET", f"repos/{repository(config)}/releases/tags/{tag}")
    if release.get("tag_name") != tag or release.get("draft") is not False or release.get("prerelease") is not True:
        raise ValueError("Beta archive must belong to a published prerelease")
    names = [asset["name"] for asset in release["assets"]]
    required = MANIFEST_ASSETS | {"SHA256SUMS"}
    if any(names.count(name) != 1 for name in required):
        raise ValueError("Published beta is missing a unique installer asset")
    for name in ("SHA256SUMS", ASSET):
        asset = next(asset for asset in release["assets"] if asset["name"] == name)
        url = f"https://github.com/{repository(config)}/releases/download/{tag}/{name}"
        if asset.get("browser_download_url") != url or asset.get("state") != "uploaded":
            raise ValueError("Release asset is not the final public exact-tag download")
        maximum = 65536 if name == "SHA256SUMS" else 1_073_741_824
        if not isinstance(asset.get("size"), int) or not 0 < asset["size"] <= maximum:
            raise ValueError("Release asset size exceeds publication limits")
        download(url, destination / name, maximum)
        if (destination / name).stat().st_size != asset["size"]:
            raise ValueError("Public asset length differs from release metadata")
        if asset.get("digest") and asset["digest"] != "sha256:" + sha256(destination / name):
            raise ValueError("Public asset differs from its GitHub digest")
    checksums = {}
    for line in (destination / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if not match or match[2] in checksums:
            raise ValueError("Malformed or duplicate release checksum entry")
        checksums[match[2]] = match[1]
    if set(checksums) != MANIFEST_ASSETS or checksums[ASSET] != sha256(destination / ASSET):
        raise ValueError("Release ZIP does not match the existing three-entry installer manifest")
    if release_commit(config, tag) != commit:
        raise ValueError("Release tag changed during public archive verification")
    return release


def tools(config, archive, destination):
    if archive is None:
        archive = destination / "Sparkle.tar.xz"
        download(config["sparkleToolsURL"], archive)
    if sha256(archive) != config["sparkleToolsSHA256"]:
        raise ValueError("Sparkle tools archive checksum mismatch")
    with tarfile.open(archive) as source:
        for name in ("sign_update", "generate_keys"):
            member = source.getmember("./bin/" + name)
            if not member.isfile():
                raise ValueError("Sparkle signing tool is not an ordinary file")
            path = destination / name
            path.write_bytes(source.extractfile(member).read())
            path.chmod(0o755)
    return destination


def reconcile(items, candidate):
    for item in items:
        if item["tag"] == candidate["tag"]:
            if any(item[key] != candidate[key] for key in ("build", "sha256", "commit", "length")):
                raise ValueError("A published beta tag cannot change build, archive, or source commit")
            return True
    if any(item["build"] >= candidate["build"] for item in items):
        raise ValueError("Beta appcast build must strictly increase")
    def order(tag):
        return tuple(map(int, beta_version(tag).split("."))) + (int(tag.rsplit(".", 1)[1]),)
    if any(order(item["tag"]) >= order(candidate["tag"]) for item in items):
        raise ValueError("Beta appcast release tag must advance")
    return False


def make_feed(previous, candidate, info, signature, notes, config):
    if previous:
        tree, _ = parse_feed(unsigned_feed(previous)[0], config)
    else:
        tree = ET.Element("rss", {"version": "2.0"})
        channel = ET.SubElement(tree, "channel")
        ET.SubElement(channel, "title").text = "Mobile Capture beta updates"
        ET.SubElement(channel, "link").text = f"https://github.com/{repository(config)}"
        ET.SubElement(channel, "description").text = "Internal development betas. Ad-hoc signed and not notarized."
    channel = tree.find("channel")
    item = ET.Element("item")
    values = {"title": candidate["tag"], f"{{{SPARKLE}}}version": str(candidate["build"]), f"{{{SPARKLE}}}shortVersionString": beta_version(candidate["tag"]), f"{{{SPARKLE}}}channel": config["channel"], f"{{{SPARKLE}}}minimumSystemVersion": info["LSMinimumSystemVersion"], f"{{{CAPTURE}}}releaseTag": candidate["tag"], f"{{{CAPTURE}}}releaseCommit": candidate["commit"], f"{{{CAPTURE}}}sha256": candidate["sha256"], "description": notes, "pubDate": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")}
    for key, value in values.items():
        ET.SubElement(item, key).text = value
    ET.SubElement(item, "enclosure", {"url": candidate["url"], "length": str(candidate["length"]), "type": "application/octet-stream", f"{{{SPARKLE}}}edSignature": signature})
    channel.insert(3, item)
    ET.indent(tree, space="  ")
    return ET.tostring(tree, encoding="utf-8", xml_declaration=True) + b"\n"


def prepare(args, config):
    beta_version(args.tag)
    if args.expected_feed_sha != "absent" and not SHA.fullmatch(args.expected_feed_sha):
        raise ValueError("Expected feed SHA must be a commit SHA or absent")
    previous = existing_feed(config, args.expected_feed_sha)
    args.output.mkdir(parents=True, exist_ok=False)
    release = fetch_release(config, args.tag, args.expected_release_commit, args.output)
    archive = args.output / ASSET
    info = archive_info(archive, config, args.tag)
    with tempfile.TemporaryDirectory(prefix="capture-beta-tools-") as temporary:
        temporary = Path(temporary)
        extracted = temporary / "extracted"
        extracted.mkdir()
        subprocess.run(["/usr/bin/tar", "-xf", str(archive), "-C", str(extracted), "--no-same-owner", "--no-acls", "--no-fflags", "--exclude", "__MACOSX"], check=True)
        app = extracted / "Mobile Capture.app"
        for entry in [app, *app.rglob("*")]:
            mode = entry.lstat().st_mode
            if stat.S_ISLNK(mode):
                if not entry.resolve(strict=True).is_relative_to(app):
                    raise ValueError("Extracted bundle symlink escapes its app")
            elif not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError("Extracted bundle contains a special file")
        verify_signatures(app, config)
        subprocess.run(["python3", "-B", str(ROOT / "Scripts/check-capture-product.py"), "--product", "capture", "--app", str(app)], check=True)
        for name in (info["CFBundleExecutable"], "mobile-capture-host", "mobile-capture-proxy"):
            architectures = subprocess.run(["/usr/bin/lipo", "-archs", str(app / "Contents/MacOS" / name)], check=True, capture_output=True, text=True).stdout.split()
            if architectures != ["arm64"]:
                raise ValueError("Beta app and native helpers must be arm64")
        candidate = {"tag": args.tag, "build": build_number(info["CFBundleVersion"]), "sha256": sha256(archive), "commit": args.expected_release_commit, "length": archive.stat().st_size, "url": f"https://github.com/{repository(config)}/releases/download/{args.tag}/{ASSET}"}
        items = verify_feed(previous, config)[1] if previous else []
        unchanged = reconcile(items, candidate)
        feed_path = args.output / "appcast.xml"
        if unchanged:
            published = next(item for item in items if item["tag"] == candidate["tag"])
            verify_signature(archive, published["signature"], config)
            feed_path.write_bytes(previous)
        else:
            tool_directory = tools(config, args.tools_archive, temporary)
            public = subprocess.run([str(tool_directory / "generate_keys"), "--account", config["keychainAccount"], "-p"], check=True, capture_output=True, text=True).stdout.strip()
            if public != config["publicEDKey"]:
                raise ValueError("Keychain account public key differs from beta policy")
            signer = [str(tool_directory / "sign_update"), "--account", config["keychainAccount"]]
            signature = subprocess.run(signer + ["-p", str(archive)], check=True, capture_output=True, text=True).stdout.strip()
            verify_signature(archive, signature, config)
            feed_path.write_bytes(make_feed(previous, candidate, info, signature, release.get("body") or args.tag, config))
            subprocess.run(signer + [str(feed_path)], check=True, capture_output=True)
            subprocess.run(signer + ["--verify", str(feed_path)], check=True, capture_output=True)
        verify_feed(feed_path.read_bytes(), config)
    record = {"schemaVersion": 1, "candidate": candidate, "expectedFeedSHA": args.expected_feed_sha, "policySHA256": sha256(POLICY_PATH), "feedSHA256": sha256(feed_path)}
    (args.output / "publication.json").write_text(json.dumps(record, indent=2) + "\n")
    print("Prepared verified public metadata in " + str(args.output))


def verify_public(config, expected, destination):
    download(config["feedURL"] + "?capture_commit=" + expected, destination, 2_097_152)
    data = destination.read_bytes()
    verify_feed(data, config)
    return data


def publish(args, config):
    record = json.loads((args.prepared / "publication.json").read_text())
    feed = (args.prepared / "appcast.xml").read_bytes()
    if record.get("schemaVersion") != 1 or record["policySHA256"] != sha256(POLICY_PATH) or record["feedSHA256"] != sha256(args.prepared / "appcast.xml"):
        raise ValueError("Prepared publication or beta policy changed")
    _, items = verify_feed(feed, config)
    candidate = record["candidate"]
    if not reconcile(items, candidate):
        raise ValueError("Prepared feed does not contain its candidate")
    with tempfile.TemporaryDirectory(prefix="capture-publication-") as temporary:
        temporary = Path(temporary)
        fetch_release(config, candidate["tag"], candidate["commit"], temporary)
        if sha256(temporary / ASSET) != candidate["sha256"]:
            raise ValueError("Public beta archive changed after preparation")
        item = next(item for item in items if item["tag"] == candidate["tag"])
        verify_signature(temporary / ASSET, item["signature"], config)
        current = feed_head(config)
        if current != record["expectedFeedSHA"]:
            existing = existing_feed(config, current)
            if existing != feed:
                raise ValueError("Feed changed before publication. Prepare again")
            head = current
        else:
            existing = existing_feed(config, current)
            if existing == feed:
                head = current
            else:
                prefix = f"repos/{repository(config)}/git"
                blob = gh("POST", prefix + "/blobs", {"content": base64.b64encode(feed).decode("ascii"), "encoding": "base64"})
                tree = {"tree": [{"path": config["feedPath"], "mode": "100644", "type": "blob", "sha": blob["sha"]}]}
                if current != "absent":
                    tree["base_tree"] = gh("GET", prefix + "/commits/" + current)["tree"]["sha"]
                tree_sha = gh("POST", prefix + "/trees", tree)["sha"]
                head = gh("POST", prefix + "/commits", {"message": "Publish beta update " + candidate["tag"], "tree": tree_sha, "parents": [] if current == "absent" else [current]})["sha"]
                if feed_head(config) != current:
                    raise ValueError("Feed changed while creating metadata. Nothing was published")
                if current == "absent":
                    gh("POST", prefix + "/refs", {"ref": "refs/heads/" + config["feedBranch"], "sha": head})
                else:
                    gh("PATCH", prefix + "/refs/heads/" + config["feedBranch"], {"sha": head, "force": False})
        if feed_head(config) != head or verify_public(config, head, temporary / "public-appcast.xml") != feed:
            raise ValueError("Public feed response differs from the verified publication. Retry verification")
    print("Published and verified signed beta feed at " + head)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare", help="Fetch final public bytes and sign metadata locally")
    preparation.add_argument("--tag", required=True)
    preparation.add_argument("--expected-release-commit", required=True)
    preparation.add_argument("--expected-feed-sha", required=True)
    preparation.add_argument("--output", type=Path, required=True)
    preparation.add_argument("--tools-archive", type=Path, help="Optional cached official archive, always hash checked")
    publication = commands.add_parser("publish", help="Publish only the reviewed signed metadata with compare-and-set")
    publication.add_argument("--prepared", type=Path, required=True)
    args = parser.parse_args()
    try:
        (prepare if args.command == "prepare" else publish)(args, policy())
    except (ValueError, KeyError, TypeError, subprocess.CalledProcessError, OSError, ET.ParseError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
