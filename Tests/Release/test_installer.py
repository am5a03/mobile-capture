#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "Scripts/install.sh"
TAG = "v1.2.3-beta.1"
ARCHIVE = "MobileCapture-macOS-arm64-development.zip"
APP = "Mobile Capture.app"


@unittest.skipUnless(sys.platform == "darwin", "Requires stock macOS bsdtar, plutil, and filesystem tools")
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mobile-capture-installer-", dir="/private/tmp")
        self.root = Path(self.temporary.name)
        self.prefix = self.root / "Install Folder"
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.configuration = self.root / "configuration.json"
        self.configuration.write_text(json.dumps({"assessment": 0, "identifier": "local.mobilecapture.development"}))
        self.tool = self.root / "fixture-tool"
        self.tool.write_text(f'''#!{sys.executable}
import json, pathlib, shutil, sys, time
root = pathlib.Path({str(self.root)!r})
config = json.loads((root / "configuration.json").read_text())
command, *args = sys.argv[1:]
if command == "curl":
    url = args[-1]
    with (root / "requests").open("a") as stream: stream.write(url + "\\n")
    if "/releases/tags/" in url:
        if config.get("delay"):
            (root / "downloading").touch()
            time.sleep(config["delay"])
        source = root / "assets/release.json"
    else:
        source = root / "assets" / url.rsplit("/", 1)[-1]
    if not source.exists(): sys.exit(22)
    shutil.copyfile(source, args[args.index("--output") + 1])
elif command == "codesign":
    if config.get("signatureFailure"): sys.exit(1)
    if "-d" in args:
        print("Identifier=" + config["identifier"], file=sys.stderr)
        if config.get("developerID"): print("Authority=Developer ID Application: Fixture (FIXTURE)", file=sys.stderr)
elif command == "file":
    print(config.get("architecture", "Mach-O 64-bit executable arm64"))
elif command == "spctl":
    print("source=" + config.get("assessmentSource", "Notarized Developer ID"), file=sys.stderr)
    sys.exit(config["assessment"])
else:
    raise AssertionError(command)
''')
        self.tool.chmod(0o700)
        production = INSTALLER.read_text()
        for command, path in (("curl", "/usr/bin/curl"), ("codesign", "/usr/bin/codesign"),
                              ("file", "/usr/bin/file"), ("spctl", "/usr/sbin/spctl")):
            self.assertIn(path, production)
            production = production.replace(path, f"'{self.tool}' {command}")
        self.script = self.root / "install-fixture.sh"
        self.script.write_text(production)
        self.entries = self.app_entries()
        self.package()

    def tearDown(self):
        self.temporary.cleanup()

    def configure(self, **changes):
        config = json.loads(self.configuration.read_text())
        config.update(changes)
        self.configuration.write_text(json.dumps(config))

    def app_entries(self, development=True):
        info = {"CFBundleIdentifier": "local.mobilecapture.development" if development else "dev.fixture.capture",
                "CFBundleShortVersionString": "1.2.3", "CFBundleExecutable": "MobileCapture",
                "MobileCaptureCompanion": True, "MobileCaptureDevelopmentIdentity": development,
                "LSMinimumSystemVersion": "26.0"}
        entries = [(f"{APP}/Contents/Info.plist", plistlib.dumps(info), stat.S_IFREG | 0o644),
                   (f"{APP}/Contents/Resources/CaptureDependencies/dependencies.json", b'{"architecture":"arm64"}', stat.S_IFREG | 0o644)]
        entries.extend((f"{APP}/Contents/MacOS/{name}", b"fixture-native-binary", stat.S_IFREG | 0o755)
                       for name in ("MobileCapture", "mobile-capture-host", "mobile-capture-proxy"))
        return entries

    def package(self, entries=None, tag=TAG, archive=ARCHIVE):
        self.tag, self.archive = tag, archive
        path = self.assets / archive
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for name, data, mode in self.entries if entries is None else entries:
                    item = zipfile.ZipInfo(name)
                    item.create_system = 3
                    item.external_attr = mode << 16
                    if stat.S_ISDIR(mode): item.external_attr |= 0x10
                    bundle.writestr(item, data)
        for asset in ("install.sh", "AGENT_SETUP.md"):
            (self.assets / asset).write_text("fixture")
        self.checksums()
        metadata = {"tag_name": tag, "draft": False, "prerelease": "-" in tag,
                    "html_url": f"https://github.com/am5a03/mobile-capture/releases/tag/{tag}",
                    "assets": [{"name": name, "size": (self.assets / name).stat().st_size,
                                "browser_download_url": f"https://github.com/am5a03/mobile-capture/releases/download/{tag}/{name}"}
                               for name in (archive, "SHA256SUMS")]}
        (self.assets / "release.json").write_text(json.dumps(metadata))

    def checksums(self):
        (self.assets / "SHA256SUMS").write_text("".join(
            f"{hashlib.sha256((self.assets / name).read_bytes()).hexdigest()}  {name}\n"
            for name in (self.archive, "install.sh", "AGENT_SETUP.md")))

    def metadata(self, **changes):
        path = self.assets / "release.json"
        value = json.loads(path.read_text())
        value.update(changes)
        path.write_text(json.dumps(value))

    def command(self, *arguments):
        return ["/bin/bash", str(self.script), "--version", self.tag, "--allow-development",
                "--prefix", str(self.prefix), *arguments]

    def run_install(self, expected=0, arguments=None):
        result = subprocess.run(self.command() if arguments is None else ["/bin/bash", str(self.script), *arguments],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, expected, result.stderr)
        if expected in (0, 20):
            self.assertEqual(result.stdout, str(self.prefix / self.tag / APP) + "\n")
            self.assertIn("doctor --json --platform android", result.stderr)
        else:
            self.assertEqual(result.stdout, "")
            self.assertFalse((self.prefix / self.tag).exists())
        self.assertFalse((self.prefix / f".install-{self.tag}.lock").exists())
        self.assertEqual(list(self.prefix.glob(f".install-{self.tag}.????????")), [])
        return result

    def test_install_and_repeat_preserve_bytes_permissions_and_mtime(self):
        self.run_install()
        app = self.prefix / TAG / APP
        before = {str(p.relative_to(app)): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                  for p in app.rglob("*") if p.is_file()}
        self.assertIn("Identical version", self.run_install().stderr)
        after = {str(p.relative_to(app)): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                 for p in app.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_framework_symlinks_are_preserved(self):
        framework = f"{APP}/Contents/Frameworks/Test.framework"
        entries = self.entries + [(framework + "/Versions/A/Test", b"framework", stat.S_IFREG | 0o644),
                                  (framework + "/Versions/Current", b"A", stat.S_IFLNK | 0o777),
                                  (framework + "/Test", b"Versions/Current/Test", stat.S_IFLNK | 0o777)]
        self.package(entries)
        self.run_install()
        installed = self.prefix / TAG / framework
        self.assertTrue((installed / "Versions/Current").is_symlink())
        self.assertEqual((installed / "Test").read_bytes(), b"framework")
        self.run_install()

    def test_human_approval_returns_installed_path_without_execution(self):
        self.configure(assessment=3)
        result = self.run_install(20)
        self.assertIn("Human macOS approval is required", result.stderr)
        self.run_install(20)

    def test_stable_requires_developer_id_and_notarization(self):
        self.entries = self.app_entries(development=False)
        self.package(tag="v1.2.3", archive="MobileCapture-macOS-arm64.zip")
        self.configure(identifier="dev.fixture.capture", developerID=True)
        self.run_install()

    def test_stable_rejects_ad_hoc_signature(self):
        self.entries = self.app_entries(development=False)
        self.package(tag="v1.2.3", archive="MobileCapture-macOS-arm64.zip")
        self.configure(identifier="dev.fixture.capture")
        self.run_install(65)

    def test_stable_assessment_failure_never_publishes(self):
        self.entries = self.app_entries(development=False)
        self.package(tag="v1.2.3", archive="MobileCapture-macOS-arm64.zip")
        self.configure(identifier="dev.fixture.capture", developerID=True, assessment=3)
        self.run_install(65)

    def test_stable_non_notarized_assessment_never_publishes(self):
        self.entries = self.app_entries(development=False)
        self.package(tag="v1.2.3", archive="MobileCapture-macOS-arm64.zip")
        self.configure(identifier="dev.fixture.capture", developerID=True, assessmentSource="Developer ID")
        self.run_install(65)

    def test_unsafe_shared_ancestor_is_refused_before_download(self):
        shared = self.root / "shared"
        shared.mkdir(mode=0o777)
        shared.chmod(0o777)
        self.prefix = shared / "private-prefix"
        self.run_install(73)
        self.assertFalse((self.root / "requests").exists())
        self.assertFalse(self.prefix.exists())

    def test_signature_failure_never_publishes(self):
        self.configure(signatureFailure=True)
        self.run_install(65)

    def test_script_claiming_arm64_is_not_native(self):
        self.configure(architecture="POSIX shell script, ASCII text arm64")
        self.run_install(65)

    def test_invalid_arguments_fail_before_download(self):
        for arguments in ([], ["--version", TAG], ["--version", "latest"],
                          ["--version", TAG, "--allow-development", "--prefix", "relative"],
                          ["--version", TAG, "--allow-development", "--allow-development"],
                          ["--version", "v01.2.3"], ["--unknown"]):
            with self.subTest(arguments=arguments): self.run_install(64, arguments)
        self.assertFalse((self.root / "requests").exists())

    def test_release_metadata_policy_refusal(self):
        for changes in ({"draft": True}, {"prerelease": False}, {"tag_name": "v9.9.9"},
                        {"html_url": "https://github.com/attacker/mobile-capture/releases/tag/" + TAG},
                        {"assets": []}):
            with self.subTest(changes=changes):
                self.package()
                self.metadata(**changes)
                self.run_install(69)

    def test_redirect_asset_url_cannot_change_repository(self):
        metadata = json.loads((self.assets / "release.json").read_text())
        metadata["assets"][0]["browser_download_url"] = "https://example.com/archive.zip"
        self.metadata(**metadata)
        self.run_install(69)

    def test_download_failure(self):
        (self.assets / ARCHIVE).unlink()
        self.run_install(69)

    def test_hash_mismatch(self):
        with (self.assets / ARCHIVE).open("ab") as stream: stream.write(b"corrupt")
        self.run_install(65)

    def test_duplicate_and_missing_checksum_entries(self):
        checksums = (self.assets / "SHA256SUMS").read_text()
        for value in (checksums + checksums.splitlines()[0] + "\n", checksums.splitlines()[0] + "\n",
                      checksums.replace("install.sh", "unexpected.sh")):
            (self.assets / "SHA256SUMS").write_text(value)
            self.run_install(65)

    def test_unsafe_archive_names(self):
        for name in ("../escape", "/private/tmp/mobile-capture-escape", "Unexpected.app/file",
                     APP + "/../escape", APP + "/a/./b", APP + "/a\\b", APP + "/a\nb",
                     APP + "/a//b"):
            with self.subTest(name=name):
                self.package(self.entries + [(name, b"escape", stat.S_IFREG | 0o644)])
                self.run_install(65)

    def test_duplicate_archive_paths(self):
        self.package(self.entries + [self.entries[0]])
        self.run_install(65)

    def test_truncated_zip(self):
        path = self.assets / ARCHIVE
        path.write_bytes(path.read_bytes()[:30])
        self.checksums()
        self.run_install(65)

    def test_escape_symlink_and_symlink_pivots(self):
        outside = self.root / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_bytes(b"preserve")
        pivots = [str(outside).encode(), b"../../outside"]
        for target in pivots:
            for child in (False, True):
                with self.subTest(target=target, child=child):
                    entries = self.entries + [(APP + "/pivot", target, stat.S_IFLNK | 0o777)]
                    if child: entries.append((APP + "/pivot/sentinel", b"overwrite", stat.S_IFREG | 0o644))
                    self.package(entries)
                    self.run_install(65)
                    self.assertEqual(sentinel.read_bytes(), b"preserve")
                    self.assertEqual(list(outside.iterdir()), [sentinel])

    def test_symlink_chain_escape(self):
        self.package(self.entries + [(APP + "/sub/back", b"..", stat.S_IFLNK | 0o777),
                                     (APP + "/sub/escape", b"back/..", stat.S_IFLNK | 0o777)])
        self.run_install(65)

    def test_stock_extractor_refuses_symlink_writes(self):
        outside = self.root / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_bytes(b"preserve")
        cases = [
            [(APP + "/pivot", str(outside).encode(), stat.S_IFLNK | 0o777),
             (APP + "/pivot/sentinel", b"overwrite", stat.S_IFREG | 0o644)],
            [(APP + "/pivot", b"../../outside", stat.S_IFLNK | 0o777),
             (APP + "/pivot/sentinel", b"overwrite", stat.S_IFREG | 0o644)],
            [(APP + "/sub/back", b"..", stat.S_IFLNK | 0o777),
             (APP + "/sub/escape", b"back/../../outside", stat.S_IFLNK | 0o777),
             (APP + "/sub/escape/sentinel", b"overwrite", stat.S_IFREG | 0o644)],
        ]
        for index, entries in enumerate(cases):
            with self.subTest(index=index):
                extraction = self.root / f"extract-{index}"
                extraction.mkdir()
                self.package(entries)
                result = subprocess.run(["/usr/bin/tar", "-xf", str(self.assets / ARCHIVE), "-C", str(extraction),
                                         "--no-same-owner", "--no-acls", "--no-fflags", "--exclude", "__MACOSX"],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn("symlink", result.stderr.lower())
                self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_real_packaged_app(self):
        if not getattr(self, "real_package", None):
            self.skipTest("Pass --real-package and --real-tag to verify a frozen package with real macOS trust tools")
        self.tag = self.real_tag
        self.archive = ARCHIVE
        shutil.copyfile(self.real_package, self.assets / ARCHIVE)
        self.checksums()
        metadata = json.loads((self.assets / "release.json").read_text())
        metadata["tag_name"] = self.tag
        metadata["html_url"] = f"https://github.com/am5a03/mobile-capture/releases/tag/{self.tag}"
        for asset in metadata["assets"]:
            asset["browser_download_url"] = f"https://github.com/am5a03/mobile-capture/releases/download/{self.tag}/" + asset["name"]
            asset["size"] = (self.assets / asset["name"]).stat().st_size
        self.metadata(**metadata)
        self.script.write_text(INSTALLER.read_text().replace("/usr/bin/curl", f"'{self.tool}' curl"))
        first = subprocess.run(self.command(), capture_output=True, text=True, timeout=60)
        self.assertIn(first.returncode, (0, 20), first.stderr)
        self.assertEqual(first.stdout, str(self.prefix / self.tag / APP) + "\n")
        second = subprocess.run(self.command(), capture_output=True, text=True, timeout=60)
        self.assertEqual(second.returncode, first.returncode, second.stderr)
        self.assertEqual(second.stdout, first.stdout)
        self.assertIn("Identical version", second.stderr)
        print(f"Frozen package verified with real codesign, file, tar, plutil, spctl. Installer exit {first.returncode}.", file=sys.stderr)

    def test_conflict_preserves_existing_app(self):
        self.run_install()
        host = self.prefix / TAG / APP / "Contents/MacOS/mobile-capture-host"
        host.write_bytes(b"existing-different")
        result = subprocess.run(self.command(), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(host.read_bytes(), b"existing-different")

    def test_symlink_destination_is_refused(self):
        self.prefix.mkdir()
        other = self.root / "other"
        other.mkdir()
        (self.prefix / TAG).symlink_to(other, target_is_directory=True)
        result = subprocess.run(self.command(), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(list(other.iterdir()), [])

    def test_prefix_symlink_is_refused(self):
        other = self.root / "other"
        other.mkdir()
        self.prefix.symlink_to(other, target_is_directory=True)
        self.run_install(73)
        self.assertFalse((self.root / "requests").exists())

    def test_existing_lock_is_never_stolen(self):
        self.prefix.mkdir()
        lock = self.prefix / f".install-{TAG}.lock"
        lock.mkdir()
        (lock / "owner").write_text("interrupted")
        result = subprocess.run(self.command(), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual((lock / "owner").read_text(), "interrupted")
        self.assertFalse((self.root / "requests").exists())

    def test_concurrent_installer_cannot_publish(self):
        self.configure(delay=2)
        first = subprocess.Popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not (self.root / "downloading").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((self.root / "downloading").exists())
            second = subprocess.run(self.command(), capture_output=True, text=True, timeout=20)
            self.assertEqual(second.returncode, 75, second.stderr)
            self.assertEqual(second.stdout, "")
            stdout, stderr = first.communicate(timeout=20)
            self.assertEqual(first.returncode, 0, stderr)
            self.assertEqual(stdout, str(self.prefix / TAG / APP) + "\n")
            self.assertFalse((self.prefix / f".install-{TAG}.lock").exists())
        finally:
            if first.poll() is None:
                first.terminate()
                first.communicate(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--real-package", type=Path)
    parser.add_argument("--real-tag")
    arguments, remaining = parser.parse_known_args()
    if bool(arguments.real_package) != bool(arguments.real_tag):
        parser.error("--real-package and --real-tag must be specified together")
    InstallerTests.real_package = arguments.real_package
    InstallerTests.real_tag = arguments.real_tag
    unittest.main(argv=[sys.argv[0], *remaining])
