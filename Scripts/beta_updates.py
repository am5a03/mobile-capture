"""Public beta policy and final-bundle validation shared by release commands."""
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import plistlib
import re
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "Dependencies/Sparkle/beta-updates.json"
BETA_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-beta\.[1-9][0-9]*")
SEALED_DEFAULTS = {
    "CaptureDistributionUpdatesEnabled": True,
    "SUEnableAutomaticChecks": False,
    "SUAllowsAutomaticUpdates": False,
    "SUAutomaticallyUpdate": False,
    "SURequireSignedFeed": True,
    "SUVerifyUpdateBeforeExtraction": True,
    "SUSendProfileInfo": False,
}
SEALED_POLICY_KEYS = ("CaptureBetaReleaseTag", "CaptureUpdateChannel", "SUFeedURL", "SUPublicEDKey")
SPARKLE_CODE = (
    "Versions/B/XPCServices/Downloader.xpc",
    "Versions/B/XPCServices/Installer.xpc",
    "Versions/B/Autoupdate",
    "Versions/B/Updater.app",
    ".",
)


def policy(path=POLICY_PATH):
    value = json.loads(Path(path).read_text())
    required = {"schemaVersion", "channel", "bundleIdentifier", "feedURL", "publicEDKey", "keychainAccount", "feedBranch", "feedPath", "sparkleVersion", "sparkleToolsURL", "sparkleToolsSHA256"}
    if set(value) != required or value["schemaVersion"] != 1 or value["channel"] != "beta":
        raise ValueError("Unsupported beta update policy")
    if any(not isinstance(value[key], str) or not value[key] for key in required - {"schemaVersion"}):
        raise ValueError("Beta update policy fields must be nonempty strings")
    if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value["bundleIdentifier"]):
        raise ValueError("Invalid beta bundle identifier")
    if len(base64.b64decode(value["publicEDKey"], validate=True)) != 32:
        raise ValueError("Beta public key must contain 32 bytes")
    branch, feed = value["feedBranch"], value["feedPath"]
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or any(p in {"", ".", ".."} for p in branch.split("/")):
        raise ValueError("Unsafe feed branch")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+\.xml", feed) or any(p in {"", ".", ".."} for p in feed.split("/")):
        raise ValueError("Unsafe feed path")
    feed_match = re.fullmatch(r"https://raw\.githubusercontent\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/" + re.escape(branch + "/" + feed), value["feedURL"])
    if not feed_match:
        raise ValueError("Feed URL must match its GitHub branch and path")
    version = value["sparkleVersion"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or value["sparkleToolsURL"] != f"https://github.com/sparkle-project/Sparkle/releases/download/{version}/Sparkle-{version}.tar.xz":
        raise ValueError("Sparkle tools must use the pinned official release")
    if not re.fullmatch(r"[0-9a-f]{64}", value["sparkleToolsSHA256"]):
        raise ValueError("Invalid Sparkle tools checksum")
    return value


def repository(config):
    return config["feedURL"].split("/")[3] + "/" + config["feedURL"].split("/")[4]


def beta_version(tag):
    match = BETA_TAG.fullmatch(tag)
    if not match:
        raise ValueError("Updater releases require vMAJOR.MINOR.PATCH-beta.N")
    return ".".join(match.groups())


def build_number(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value) or int(value) > 2_147_483_647:
        raise ValueError("App build must be a positive integer no greater than 2147483647")
    return int(value)


def sealed_metadata(config, tag):
    beta_version(tag)
    return dict(SEALED_DEFAULTS, CaptureBetaReleaseTag=tag, CaptureUpdateChannel=config["channel"], SUFeedURL=config["feedURL"], SUPublicEDKey=config["publicEDKey"])


def validate_info(info, config, tag=None):
    enabled = info.get("CaptureDistributionUpdatesEnabled")
    if type(enabled) is not bool:
        raise ValueError("CaptureDistributionUpdatesEnabled must be explicit")
    if tag is not None or enabled:
        tag = tag or info.get("CaptureBetaReleaseTag", "")
        if info.get("CFBundleShortVersionString") != beta_version(tag):
            raise ValueError("Beta tag does not match the numeric app version")
        build_number(info.get("CFBundleVersion"))
        if info.get("CFBundleIdentifier") != config["bundleIdentifier"] or info.get("MobileCaptureDevelopmentIdentity") is not True:
            raise ValueError("Beta updates require the configured development bundle identity")
        for key, expected in sealed_metadata(config, tag).items():
            if type(info.get(key)) is not type(expected) or info[key] != expected:
                raise ValueError("Beta metadata does not match policy: " + key)
    else:
        if any(key in info for key in SEALED_POLICY_KEYS) or any(info.get(key) is True for key in SEALED_DEFAULTS if key != "CaptureDistributionUpdatesEnabled"):
            raise ValueError("Disabled builds must not contain beta feed metadata or update opt-ins")


def seal(app, config, tag=None):
    path = app / "Contents/Info.plist"
    info = plistlib.loads(path.read_bytes())
    for key in (*SEALED_DEFAULTS, *SEALED_POLICY_KEYS):
        info.pop(key, None)
    info["CaptureDistributionUpdatesEnabled"] = False
    if tag:
        info.update(sealed_metadata(config, tag))
    validate_info(info, config, tag)
    path.write_bytes(plistlib.dumps(info))


def validate_framework(app, config):
    framework = app / "Contents/Frameworks/Sparkle.framework"
    path = framework / "Versions/B/Resources/Info.plist"
    if not path.is_file() or plistlib.loads(path.read_bytes()).get("CFBundleShortVersionString") != config["sparkleVersion"]:
        raise ValueError("Packaged Sparkle framework version does not match beta policy")
    for relative in SPARKLE_CODE:
        if not (framework / relative).exists():
            raise ValueError("Missing Sparkle nested code: " + relative)
    return [framework / relative for relative in SPARKLE_CODE]


def verify_signatures(app, config):
    for path in validate_framework(app, config) + [app / "Contents/MacOS/mobile-capture-host", app / "Contents/MacOS/mobile-capture-proxy", app]:
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(path)], check=True, capture_output=True)


def sha256(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def archive_info(path, config, tag):
    with zipfile.ZipFile(path) as archive:
        names = set()
        entries = archive.infolist()
        if len(entries) > 100000 or sum(entry.file_size for entry in entries) > 4_294_967_296:
            raise ValueError("Update ZIP exceeds expansion limits")
        for entry in entries:
            relative = PurePosixPath(entry.filename)
            name = entry.filename.rstrip("/")
            allowed = name == "Mobile Capture.app" or name.startswith("Mobile Capture.app/") or name in {"__MACOSX", "__MACOSX/Mobile Capture.app"} or name.startswith("__MACOSX/Mobile Capture.app/")
            if name in names or not allowed or relative.is_absolute() or any(part in {".", ".."} for part in entry.filename.split("/")) or "//" in entry.filename or "\\" in entry.filename or any(ord(character) < 32 or ord(character) == 127 for character in entry.filename) or len(entry.filename) > 4096:
                raise ValueError("Unsafe or duplicate update ZIP path")
            names.add(name)
            mode = entry.external_attr >> 16
            if stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK} or mode & 0o6000:
                raise ValueError("Unsupported update ZIP entry")
            if stat.S_ISLNK(entry.external_attr >> 16):
                target = archive.read(entry).decode("utf-8")
                resolved = list(relative.parent.parts)
                if target.startswith("/"):
                    raise ValueError("Absolute update ZIP symlink")
                for part in target.split("/"):
                    if part == "..":
                        if len(resolved) <= 1:
                            raise ValueError("Escaping update ZIP symlink")
                        resolved.pop()
                    elif part not in {"", "."}:
                        resolved.append(part)
        info = plistlib.loads(archive.read("Mobile Capture.app/Contents/Info.plist"))
        validate_info(info, config, tag)
        if archive.testzip():
            raise ValueError("Update ZIP failed integrity check")
    return info
