import base64
import hashlib
import importlib.util
import json
import os
import plistlib
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Scripts"))
import beta_updates as beta

spec = importlib.util.spec_from_file_location("beta_publication", ROOT / "Scripts/publish-beta-update.py")
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


class BetaPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.crypto_temporary = tempfile.TemporaryDirectory(prefix="capture-fixture-keys-")
        cls.crypto_root = Path(cls.crypto_temporary.name)
        source = cls.crypto_root / "fixture.swift"
        source.write_text('''import CryptoKit
import Foundation
let args = CommandLine.arguments
if args[1] == "generate" {
    let key = Curve25519.Signing.PrivateKey()
    try key.rawRepresentation.write(to: URL(fileURLWithPath: args[2]))
    print(key.publicKey.rawRepresentation.base64EncodedString())
} else {
    let key = try Curve25519.Signing.PrivateKey(rawRepresentation: Data(contentsOf: URL(fileURLWithPath: args[2])))
    let data = try Data(contentsOf: URL(fileURLWithPath: args[3]))
    print(try key.signature(for: data).base64EncodedString())
}
''')
        cls.crypto = cls.crypto_root / "fixture-crypto"
        subprocess.run(["/usr/bin/swiftc", "-module-cache-path", str(cls.crypto_root / "module-cache"), str(source), "-o", str(cls.crypto)], check=True, capture_output=True)
        cls.seed = cls.crypto_root / "disposable-seed"
        cls.public_key = subprocess.run([str(cls.crypto), "generate", str(cls.seed)], check=True, capture_output=True, text=True).stdout.strip()
        cls.seed.chmod(0o600)

    @classmethod
    def tearDownClass(cls):
        cls.crypto_temporary.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="capture-publication-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = dict(beta.policy(), publicEDKey=self.public_key, keychainAccount="disposable-fixture-account")
        self.archive = self.root / publication.ASSET
        self.archive.write_bytes(b"disposable synthetic public archive")
        self.candidate = {"tag": "v0.1.2-beta.1", "build": 2001, "sha256": beta.sha256(self.archive), "commit": "a" * 40, "length": self.archive.stat().st_size, "url": "https://github.com/" + beta.repository(self.config) + "/releases/download/v0.1.2-beta.1/" + publication.ASSET}
        self.info = {"LSMinimumSystemVersion": "26.0"}

    def sign(self, path):
        return subprocess.run([str(self.crypto), "sign", str(self.seed), str(path)], check=True, capture_output=True, text=True).stdout.strip()

    def signed_feed(self, candidate=None, previous=None):
        path = self.root / "unsigned.xml"
        path.write_bytes(publication.make_feed(previous, candidate or self.candidate, self.info, self.sign(self.archive), "Fixture update notes", self.config))
        signature = self.sign(path)
        content = path.read_bytes()
        return content + f"<!-- sparkle-signatures:\nedSignature: {signature}\nlength: {len(content)}\n-->\n".encode()

    def prepared(self, expected="b" * 40):
        feed = self.signed_feed()
        (self.root / "appcast.xml").write_bytes(feed)
        record = {"schemaVersion": 1, "candidate": self.candidate, "expectedFeedSHA": expected, "policySHA256": beta.sha256(beta.POLICY_PATH), "feedSHA256": hashlib.sha256(feed).hexdigest()}
        (self.root / "publication.json").write_text(json.dumps(record))
        return feed

    def fake_release(self, config, tag, commit, destination):
        (destination / publication.ASSET).write_bytes(self.archive.read_bytes())

    def test_signed_feed_and_archive_are_verified_with_public_key_only(self):
        data = self.signed_feed()
        tree, items = publication.verify_feed(data, self.config)
        self.assertEqual(items[0]["build"], 2001)
        self.assertEqual(tree.findtext(f"channel/item/{{{publication.SPARKLE}}}shortVersionString"), "0.1.2-beta.1")
        publication.verify_signature(self.archive, items[0]["signature"], self.config)
        self.archive.write_bytes(b"modified archive")
        with self.assertRaises(subprocess.CalledProcessError):
            publication.verify_signature(self.archive, items[0]["signature"], self.config)
        with self.assertRaises(subprocess.CalledProcessError):
            publication.verify_feed(data.replace(b"Fixture update notes", b"Changed update notes"), self.config)

    def test_transfer_retains_only_explicit_signed_legacy_links(self):
        canonical = beta.repository(self.config)
        legacy = "am5a03/mobile-capture"
        historical = dict(self.candidate, url=self.candidate["url"].replace(canonical, legacy))
        data = self.signed_feed(historical)
        items = publication.verify_feed(data, self.config)[1]
        self.assertEqual(items[0]["url"], historical["url"])
        with self.assertRaisesRegex(ValueError, "enclosure"):
            publication.verify_feed(data, dict(self.config, legacyRepositories=[]))
        foreign = dict(historical, url=historical["url"].replace(legacy, "other-owner/mobile-capture"))
        with self.assertRaisesRegex(ValueError, "enclosure"):
            publication.verify_feed(self.signed_feed(foreign), self.config)
        with self.assertRaises(subprocess.CalledProcessError):
            publication.verify_feed(data.replace(b"am5a03", b"am5a04"), self.config)
        newer = dict(self.candidate, tag="v0.1.2-beta.2", build=3001,
                     url=self.candidate["url"].replace("beta.1", "beta.2"))
        items = publication.verify_feed(self.signed_feed(newer, data), self.config)[1]
        self.assertEqual([item["url"] for item in items], [newer["url"], historical["url"]])
        self.assertFalse(publication.reconcile(items[1:], newer))

    def test_unsigned_wrong_key_trailing_data_and_length_are_rejected(self):
        data = self.signed_feed()
        for changed in (data.split(b"<!-- sparkle-signatures:")[0], data + b"<item/>", data.replace(b"length: ", b"length: 0")):
            with self.subTest(changed=changed[-80:]), self.assertRaises(ValueError):
                publication.verify_feed(changed, self.config)
        wrong_key = dict(self.config, publicEDKey=base64.b64encode(b"x" * 32).decode())
        with self.assertRaises(subprocess.CalledProcessError):
            publication.verify_feed(data, wrong_key)

    def test_same_tag_is_idempotent_only_for_the_same_archive_build_and_commit(self):
        self.assertTrue(publication.reconcile([self.candidate], self.candidate))
        for changed in ({"sha256": "0" * 64}, {"build": 2002}, {"commit": "0" * 40}, {"length": 10}):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "cannot change"):
                publication.reconcile([self.candidate], dict(self.candidate, **changed))
        for build in (1, 2001):
            with self.subTest(build=build), self.assertRaisesRegex(ValueError, "strictly increase"):
                publication.reconcile([self.candidate], dict(self.candidate, tag="v0.1.3-beta.1", build=build))
        self.assertFalse(publication.reconcile([self.candidate], dict(self.candidate, tag="v0.1.3-beta.1", build=2002)))
        with self.assertRaisesRegex(ValueError, "tag must advance"):
            publication.reconcile([self.candidate], dict(self.candidate, tag="v0.1.1-beta.99", build=2002))

    def test_feed_url_version_order_and_channel_are_validated(self):
        content = publication.unsigned_feed(self.signed_feed())[0]
        for changed in (content.replace(b"/v0.1.2-beta.1/", b"/latest/"), content.replace(b">2001<", b">0<"), content.replace(b">beta<", b">stable<"), content.replace(b">0.1.2-beta.1<", b">0.1.2<"), content.replace(b">0.1.2-beta.1<", b">0.1.2-beta.2<")):
            with self.subTest(changed=changed[:20]), self.assertRaises(ValueError):
                publication.parse_feed(changed, self.config)
        tree, _ = publication.parse_feed(content, self.config)
        channel = tree.find("channel")
        channel.append(ET.fromstring(ET.tostring(channel.find("item"))))
        with self.assertRaisesRegex(ValueError, "unique"):
            publication.parse_feed(ET.tostring(tree), self.config)

    def test_missing_asset_checksum_tag_and_public_download_fail_before_signing(self):
        checksums = f"{beta.sha256(self.archive)}  {publication.ASSET}\n{'1' * 64}  install.sh\n{'2' * 64}  AGENT_SETUP.md\n".encode()
        body = {"tag_name": self.candidate["tag"], "draft": False, "prerelease": True, "assets": [{"name": name, "state": "uploaded", "size": len(checksums) if name == "SHA256SUMS" else self.archive.stat().st_size, "browser_download_url": f"https://github.com/{beta.repository(self.config)}/releases/download/{self.candidate['tag']}/{name}"} for name in (*publication.MANIFEST_ASSETS, "SHA256SUMS")]}
        destination = self.root / "downloads"
        destination.mkdir()
        def downloaded(url, path, maximum=None):
            path.write_bytes(checksums if path.name == "SHA256SUMS" else self.archive.read_bytes())
        with patch.object(publication, "release_commit", return_value=self.candidate["commit"]), patch.object(publication, "gh", return_value=body), patch.object(publication, "download", side_effect=downloaded):
            publication.fetch_release(self.config, self.candidate["tag"], self.candidate["commit"], destination)
            body["assets"] = [asset for asset in body["assets"] if asset["name"] != publication.ASSET]
            with self.assertRaisesRegex(ValueError, "missing"):
                publication.fetch_release(self.config, self.candidate["tag"], self.candidate["commit"], destination)
        with patch.object(publication, "release_commit", return_value="0" * 40), self.assertRaisesRegex(ValueError, "reviewed source"):
            publication.fetch_release(self.config, self.candidate["tag"], self.candidate["commit"], destination)
        body["assets"].append({"name": publication.ASSET, "state": "uploaded", "size": self.archive.stat().st_size, "browser_download_url": self.candidate["url"]})
        with patch.object(publication, "release_commit", return_value=self.candidate["commit"]), patch.object(publication, "gh", return_value=body), patch.object(publication, "download", side_effect=OSError("public download unavailable")), self.assertRaisesRegex(OSError, "unavailable"):
            publication.fetch_release(self.config, self.candidate["tag"], self.candidate["commit"], destination)
        checksums = checksums.replace(beta.sha256(self.archive).encode(), b"0" * 64)
        with patch.object(publication, "release_commit", return_value=self.candidate["commit"]), patch.object(publication, "gh", return_value=body), patch.object(publication, "download", side_effect=downloaded), self.assertRaisesRegex(ValueError, "three-entry"):
            publication.fetch_release(self.config, self.candidate["tag"], self.candidate["commit"], destination)

    def test_tools_are_extracted_only_after_the_pinned_archive_matches(self):
        archive = self.root / "tools.tar.xz"
        for name in ("sign_update", "generate_keys"):
            (self.root / name).write_text("synthetic tool fixture")
        with tarfile.open(archive, "w:xz") as output:
            for name in ("sign_update", "generate_keys"):
                output.add(self.root / name, arcname="./bin/" + name)
        destination = self.root / "tools"
        destination.mkdir()
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            publication.tools(self.config, archive, destination)
        self.assertEqual(list(destination.iterdir()), [])
        publication.tools(dict(self.config, sparkleToolsSHA256=beta.sha256(archive)), archive, destination)
        self.assertEqual({path.name for path in destination.iterdir()}, {"sign_update", "generate_keys"})

    def test_failed_compare_and_set_does_not_force_a_branch_update(self):
        self.prepared()
        with patch.object(publication, "fetch_release", side_effect=self.fake_release), patch.object(publication, "feed_head", return_value="c" * 40), patch.object(publication, "existing_feed", return_value=b"another signed feed"), patch.object(publication, "gh") as api:
            with self.assertRaisesRegex(ValueError, "Feed changed before"):
                publication.publish(SimpleNamespace(prepared=self.root), self.config)
            api.assert_not_called()

    def test_publication_rechecks_archive_and_does_not_publish_changed_bytes(self):
        self.prepared()
        def changed(config, tag, commit, destination):
            (destination / publication.ASSET).write_bytes(b"changed after preparation")
        with patch.object(publication, "fetch_release", side_effect=changed), patch.object(publication, "gh") as api:
            with self.assertRaisesRegex(ValueError, "archive changed"):
                publication.publish(SimpleNamespace(prepared=self.root), self.config)
            api.assert_not_called()

    def test_publish_uses_expected_parent_nonforce_and_verifies_public_bytes(self):
        feed = self.prepared()
        older = dict(self.candidate, tag="v0.1.1-beta.1", build=1001, url=self.candidate["url"].replace("v0.1.2-beta.1", "v0.1.1-beta.1"))
        previous = self.signed_feed(older)
        calls = []
        def api(method, endpoint, payload=None, **kwargs):
            calls.append((method, endpoint, payload))
            if endpoint.endswith("/blobs"):
                return {"sha": "d" * 40}
            if method == "GET" and "/commits/" in endpoint:
                return {"tree": {"sha": "e" * 40}}
            if endpoint.endswith("/trees"):
                return {"sha": "f" * 40}
            if endpoint.endswith("/commits"):
                self.assertEqual(payload["parents"], ["b" * 40])
                return {"sha": "c" * 40}
            self.assertEqual(method, "PATCH")
            self.assertEqual(payload, {"sha": "c" * 40, "force": False})
            return {}
        with patch.object(publication, "fetch_release", side_effect=self.fake_release), patch.object(publication, "feed_head", side_effect=["b" * 40, "b" * 40, "c" * 40]), patch.object(publication, "existing_feed", return_value=previous), patch.object(publication, "gh", side_effect=api), patch.object(publication, "verify_public", return_value=feed) as public:
            publication.publish(SimpleNamespace(prepared=self.root), self.config)
            public.assert_called_once()
        self.assertEqual([call[0] for call in calls], ["POST", "GET", "POST", "POST", "PATCH"])

    def test_retry_after_success_checks_public_response_without_any_mutation(self):
        feed = self.prepared()
        with patch.object(publication, "fetch_release", side_effect=self.fake_release), patch.object(publication, "feed_head", return_value="c" * 40), patch.object(publication, "existing_feed", return_value=feed), patch.object(publication, "gh") as api, patch.object(publication, "verify_public", return_value=feed):
            publication.publish(SimpleNamespace(prepared=self.root), self.config)
            api.assert_not_called()
        with patch.object(publication, "fetch_release", side_effect=self.fake_release), patch.object(publication, "feed_head", return_value="c" * 40), patch.object(publication, "existing_feed", return_value=feed), patch.object(publication, "gh") as api, patch.object(publication, "verify_public", return_value=b"stale public feed"):
            with self.assertRaisesRegex(ValueError, "Public feed response"):
                publication.publish(SimpleNamespace(prepared=self.root), self.config)
            api.assert_not_called()

    def test_stale_configured_feed_stays_pending_and_retry_never_rewrites(self):
        feed = self.prepared()
        older = dict(self.candidate, tag="v0.1.1-beta.1", build=1001, url=self.candidate["url"].replace("v0.1.2-beta.1", "v0.1.1-beta.1"))
        public_feed = self.signed_feed(older)
        urls = []
        def downloaded(url, path, maximum):
            urls.append(url)
            path.write_bytes(public_feed if url == self.config["feedURL"] else feed)
        with patch.object(publication, "fetch_release", side_effect=self.fake_release), patch.object(publication, "feed_head", return_value="c" * 40), patch.object(publication, "existing_feed", return_value=feed), patch.object(publication, "gh") as api, patch.object(publication, "download", side_effect=downloaded):
            with self.assertRaisesRegex(ValueError, "verification is pending"):
                publication.publish(SimpleNamespace(prepared=self.root), self.config)
            self.assertEqual(urls, [self.config["feedURL"]])
            api.assert_not_called()
            public_feed = feed
            publication.publish(SimpleNamespace(prepared=self.root), self.config)
            self.assertEqual(urls, [self.config["feedURL"], self.config["feedURL"]])
            api.assert_not_called()

    def test_old_signed_feed_cannot_replay_with_an_edited_expected_head(self):
        old_feed = self.prepared()
        newer = dict(self.candidate, tag="v0.1.3-beta.1", build=2002, url=self.candidate["url"].replace("v0.1.2-beta.1", "v0.1.3-beta.1"))
        current_feed = self.signed_feed(newer, old_feed)
        record_path = self.root / "publication.json"
        record = json.loads(record_path.read_text())
        record["expectedFeedSHA"] = "c" * 40
        record_path.write_text(json.dumps(record))
        def api(method, endpoint, payload=None, **kwargs):
            self.assertEqual(method, "GET", "A signed feed replay must fail before any GitHub mutation")
            self.assertTrue(endpoint.endswith("?ref=" + "c" * 40))
            return {"content": base64.b64encode(current_feed).decode("ascii")}
        with patch.object(publication, "fetch_release", side_effect=self.fake_release), patch.object(publication, "feed_head", return_value="c" * 40), patch.object(publication, "gh", side_effect=api) as requests:
            with self.assertRaisesRegex(ValueError, "already published.*different feed"):
                publication.publish(SimpleNamespace(prepared=self.root), self.config)
            self.assertEqual([call.args[0] for call in requests.call_args_list], ["GET"])

    def test_new_candidate_must_advance_the_current_published_build_and_tag(self):
        self.prepared(expected="c" * 40)
        for build, error in ((2002, "strictly increase"), (2000, "tag must advance")):
            with self.subTest(current_build=build):
                newer = dict(self.candidate, tag="v0.1.3-beta.1", build=build, url=self.candidate["url"].replace("v0.1.2-beta.1", "v0.1.3-beta.1"))
                current_feed = self.signed_feed(newer)
                def api(method, endpoint, payload=None, **kwargs):
                    self.assertEqual(method, "GET", "A non-increasing candidate must fail before any GitHub mutation")
                    return {"content": base64.b64encode(current_feed).decode("ascii")}
                with patch.object(publication, "fetch_release", side_effect=self.fake_release), patch.object(publication, "feed_head", return_value="c" * 40), patch.object(publication, "gh", side_effect=api) as requests:
                    with self.assertRaisesRegex(ValueError, error):
                        publication.publish(SimpleNamespace(prepared=self.root), self.config)
                    self.assertEqual([call.args[0] for call in requests.call_args_list], ["GET"])

    def test_prepare_signs_final_archive_with_framework_links_under_symlinked_temporary_root(self):
        info = {"CFBundleShortVersionString": "0.1.2", "CFBundleVersion": "2001", "CFBundleIdentifier": self.config["bundleIdentifier"], "CFBundleExecutable": "Mobile Capture", "MobileCaptureDevelopmentIdentity": True, "LSMinimumSystemVersion": "26.0"}
        info.update(beta.sealed_metadata(self.config, self.candidate["tag"]))
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("Mobile Capture.app/Contents/Info.plist", plistlib.dumps(info))
            for name in ("Mobile Capture", "mobile-capture-host", "mobile-capture-proxy"):
                archive.writestr("Mobile Capture.app/Contents/MacOS/" + name, b"synthetic executable")
            framework = "Mobile Capture.app/Contents/Frameworks/Sparkle.framework/"
            archive.writestr(framework + "Versions/B/Sparkle", b"synthetic framework")
            archive.writestr(framework + "Versions/B/Resources/Info.plist", plistlib.dumps({"CFBundleShortVersionString": self.config["sparkleVersion"]}))
            for name, target in (("Versions/Current", "B"), ("Sparkle", "Versions/Current/Sparkle"), ("Resources", "Versions/Current/Resources")):
                link = zipfile.ZipInfo(framework + name)
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(link, target)
        output = self.root / "prepared"
        tool_directory = self.root / "fake-tools"
        tool_directory.mkdir()
        temporary_root = self.root / "ordinary-temporary-root"
        temporary_root.mkdir()
        temporary_alias = self.root / "temporary-alias"
        temporary_alias.symlink_to(temporary_root, target_is_directory=True)
        temporary_directory = tempfile.TemporaryDirectory
        args = SimpleNamespace(tag=self.candidate["tag"], expected_release_commit=self.candidate["commit"], expected_feed_sha="absent", output=output, tools_archive=None)
        real_run = subprocess.run
        signing_calls = []
        def run(command, **kwargs):
            if str(command[0]).endswith("generate_keys"):
                self.assertEqual(command[1:], ["--account", self.config["keychainAccount"], "-p"])
                return subprocess.CompletedProcess(command, 0, self.public_key + "\n")
            if str(command[0]).endswith("sign_update"):
                signing_calls.append(command)
                self.assertEqual(command[1:3], ["--account", self.config["keychainAccount"]])
                self.assertNotIn("--ed-key-file", command)
                if "--verify" in command:
                    publication.verify_feed(Path(command[-1]).read_bytes(), self.config)
                    return subprocess.CompletedProcess(command, 0, b"")
                if "-p" in command:
                    return subprocess.CompletedProcess(command, 0, self.sign(Path(command[-1])) + "\n")
                path = Path(command[-1])
                content = path.read_bytes()
                signature = self.sign(path)
                path.write_bytes(content + f"<!-- sparkle-signatures:\nedSignature: {signature}\nlength: {len(content)}\n-->\n".encode())
                return subprocess.CompletedProcess(command, 0, b"")
            if command[0] == "/usr/bin/lipo":
                return subprocess.CompletedProcess(command, 0, "arm64\n")
            if command[0] == "python3":
                return subprocess.CompletedProcess(command, 0, b"")
            return real_run(command, **kwargs)
        def fetched(config, tag, commit, destination):
            (destination / publication.ASSET).write_bytes(self.archive.read_bytes())
            return {"body": "Synthetic beta release notes"}
        def verified(app, config):
            self.assertTrue(app.is_relative_to(temporary_alias))
            self.assertNotEqual(app, app.resolve(strict=True))
            self.assertEqual(len([entry for entry in app.rglob("*") if entry.is_symlink()]), 3)
        with patch.object(publication, "existing_feed", return_value=None), patch.object(publication, "fetch_release", side_effect=fetched), patch.object(publication, "verify_signatures", side_effect=verified), patch.object(publication, "tools", return_value=tool_directory), patch.object(publication.tempfile, "TemporaryDirectory", side_effect=lambda **kwargs: temporary_directory(dir=temporary_alias, **kwargs)), patch.object(publication.subprocess, "run", side_effect=run):
            publication.prepare(args, self.config)
        record = json.loads((output / "publication.json").read_text())
        self.assertEqual(record["candidate"]["sha256"], beta.sha256(self.archive))
        self.assertEqual(record["candidate"]["build"], 2001)
        self.assertEqual(record["expectedFeedSHA"], "absent")
        self.assertEqual(len(signing_calls), 3)
        tree, items = publication.verify_feed((output / "appcast.xml").read_bytes(), self.config)
        self.assertEqual(items[0]["sha256"], beta.sha256(self.archive))
        self.assertEqual(tree.findtext(f"channel/item/{{{publication.SPARKLE}}}shortVersionString"), "0.1.2-beta.1")
        self.assertEqual(beta.archive_info(output / publication.ASSET, self.config, self.candidate["tag"])["CFBundleShortVersionString"], "0.1.2")

    def test_unsafe_extracted_bundle_stops_before_verification_or_signing(self):
        info = {"CFBundleShortVersionString": "0.1.2", "CFBundleVersion": "2001", "CFBundleIdentifier": self.config["bundleIdentifier"], "MobileCaptureDevelopmentIdentity": True}
        info.update(beta.sealed_metadata(self.config, self.candidate["tag"]))
        real_run = subprocess.run
        for unsafe in ("escaping-link", "root-link", "root-file", "special-file"):
            with self.subTest(unsafe=unsafe):
                with zipfile.ZipFile(self.archive, "w") as archive:
                    archive.writestr("Mobile Capture.app/Contents/Info.plist", plistlib.dumps(info))
                    if unsafe == "escaping-link":
                        for name, target in (("Alias", "."), ("Contents/escape", "../Alias/..")):
                            link = zipfile.ZipInfo("Mobile Capture.app/" + name)
                            link.create_system = 3
                            link.external_attr = (stat.S_IFLNK | 0o777) << 16
                            archive.writestr(link, target)
                output = self.root / unsafe
                args = SimpleNamespace(tag=self.candidate["tag"], expected_release_commit=self.candidate["commit"], expected_feed_sha="absent", output=output, tools_archive=None)
                def run(command, **kwargs):
                    result = real_run(command, **kwargs)
                    if command[0] == "/usr/bin/tar":
                        app = Path(command[command.index("-C") + 1]) / "Mobile Capture.app"
                        if unsafe in {"root-link", "root-file"}:
                            app.rename(app.with_name("ordinary-app"))
                            if unsafe == "root-link":
                                app.symlink_to("ordinary-app", target_is_directory=True)
                            else:
                                app.write_text("not an app directory")
                        elif unsafe == "special-file":
                            os.mkfifo(app / "Contents/special")
                    return result
                with patch.object(publication, "existing_feed", return_value=None), patch.object(publication, "fetch_release", side_effect=self.fake_release), patch.object(publication, "verify_signatures") as signatures, patch.object(publication, "tools") as signing_tools, patch.object(publication.subprocess, "run", side_effect=run):
                    with self.assertRaises(ValueError):
                        publication.prepare(args, self.config)
                    signatures.assert_not_called()
                    signing_tools.assert_not_called()
                self.assertFalse((output / "publication.json").exists())
                self.assertFalse((output / "appcast.xml").exists())

    def test_race_during_commit_creation_fails_without_updating_ref(self):
        self.prepared()
        calls = []
        def api(method, endpoint, payload=None):
            calls.append((method, endpoint))
            if "/commits/" in endpoint:
                return {"tree": {"sha": "d" * 40}}
            return {"sha": "c" * 40}
        with patch.object(publication, "fetch_release", side_effect=self.fake_release), patch.object(publication, "feed_head", side_effect=["b" * 40, "f" * 40]), patch.object(publication, "existing_feed", return_value=None), patch.object(publication, "gh", side_effect=api):
            with self.assertRaisesRegex(ValueError, "Feed changed while"):
                publication.publish(SimpleNamespace(prepared=self.root), self.config)
        self.assertFalse(any(method == "PATCH" or endpoint.endswith("/refs") for method, endpoint in calls))

    @unittest.skipUnless(os.environ.get("CAPTURE_TEST_SPARKLE_TOOLS_ARCHIVE"), "Optional pinned official-tool check uses a disposable fixture seed")
    def test_pinned_official_signer_and_public_verifier_agree(self):
        directory = self.root / "official-tools"
        directory.mkdir()
        publication.tools(self.config, Path(os.environ["CAPTURE_TEST_SPARKLE_TOOLS_ARCHIVE"]), directory)
        fixture_key = self.root / "disposable-key.base64"
        fixture_key.write_bytes(base64.b64encode(self.seed.read_bytes()))
        fixture_key.chmod(0o600)
        signer = [str(directory / "sign_update"), "--ed-key-file", str(fixture_key)]
        signature = subprocess.run(signer + ["-p", str(self.archive)], check=True, capture_output=True, text=True).stdout.strip()
        publication.verify_signature(self.archive, signature, self.config)
        feed_path = self.root / "official-appcast.xml"
        feed_path.write_bytes(publication.make_feed(None, self.candidate, self.info, signature, "Disposable official-tool fixture", self.config))
        subprocess.run(signer + [str(feed_path)], check=True, capture_output=True)
        subprocess.run(signer + ["--verify", str(feed_path)], check=True, capture_output=True)
        publication.verify_feed(feed_path.read_bytes(), self.config)
        feed_path.write_bytes(feed_path.read_bytes().replace(b"Disposable official-tool fixture", b"Xisposable official-tool fixture"))
        with self.assertRaises(subprocess.CalledProcessError):
            publication.verify_feed(feed_path.read_bytes(), self.config)

    def test_prepared_policy_drift_is_rejected_before_any_publication_request(self):
        self.prepared()
        path = self.root / "publication.json"
        record = json.loads(path.read_text())
        record["policySHA256"] = "0" * 64
        path.write_text(json.dumps(record))
        with patch.object(publication, "gh") as api, self.assertRaisesRegex(ValueError, "policy changed"):
            publication.publish(SimpleNamespace(prepared=self.root), self.config)
        api.assert_not_called()

    def test_failed_final_nested_signature_stops_before_keychain_signing(self):
        info = {"CFBundleShortVersionString": "0.1.2", "CFBundleVersion": "2001", "CFBundleIdentifier": self.config["bundleIdentifier"], "MobileCaptureDevelopmentIdentity": True}
        info.update(beta.sealed_metadata(self.config, self.candidate["tag"]))
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("Mobile Capture.app/Contents/Info.plist", plistlib.dumps(info))
        output = self.root / "refused"
        args = SimpleNamespace(tag=self.candidate["tag"], expected_release_commit=self.candidate["commit"], expected_feed_sha="absent", output=output, tools_archive=None)
        with patch.object(publication, "existing_feed", return_value=None), patch.object(publication, "fetch_release", side_effect=self.fake_release), patch.object(publication, "verify_signatures", side_effect=subprocess.CalledProcessError(1, "fixture codesign verify")), patch.object(publication, "tools") as signing_tools:
            with self.assertRaises(subprocess.CalledProcessError):
                publication.prepare(args, self.config)
            signing_tools.assert_not_called()
        self.assertFalse((output / "publication.json").exists())
        self.assertFalse((output / "appcast.xml").exists())
