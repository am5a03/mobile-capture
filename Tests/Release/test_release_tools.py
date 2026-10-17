import hashlib
import importlib.util
import io
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "Scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

release = module("release_assets", "release-assets.py")
cache = module("capture_cache", "prepare-capture-cache.py")

def event(tag="v1.2.3"):
    return {"ref": "refs/tags/" + tag, "deleted": False}

class ReleaseMetadataTests(unittest.TestCase):
    def test_stable_release_sets_app_version_and_signing_mode(self):
        self.assertEqual(release.plan(event()), {"tag": "v1.2.3", "version": "1.2.3", "mode": "release", "prerelease": "false"})

    def test_prerelease_uses_development_package_with_numeric_app_version(self):
        for suffix in ("alpha.1", "beta.2", "rc.3"):
            with self.subTest(suffix=suffix):
                self.assertEqual(release.plan(event("v0.2.0-"+suffix))["version"], "0.2.0")
                self.assertEqual(release.plan(event("v0.2.0-"+suffix))["mode"], "development")

    def test_rejects_shell_fragments_paths_and_invalid_versions(self):
        for tag in ("v1.2.3;echo unsafe", "$(whoami)", "../v1.2.3", "v01.2.3", "v1.2", "v1.2.3\nmode=development", "v1.2.3-beta.0"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release.plan(event(tag))

    def test_prerelease_flag_is_derived_from_the_version_tag(self):
        self.assertEqual(release.plan(event("v1.2.3-beta.1"))["prerelease"], "true")
        self.assertEqual(release.plan(event())["prerelease"], "false")

    def test_branch_pushes_deletions_and_unrelated_events_are_rejected(self):
        for payload in ({"ref":"refs/heads/v1.2.3", "deleted":False}, {"ref":"refs/tags/v1.2.3", "deleted":True}, {"release":{"tag_name":"v1.2.3"}}):
            with self.assertRaises(ValueError): release.plan(payload)

    def test_stable_release_reports_missing_signing_without_secret_values(self):
        with self.assertRaisesRegex(ValueError, "APPLE_CERTIFICATE_P12_BASE64"):
            release.check_signing({})
        configured={key: "test-secret-do-not-print" for key in release.SIGNING}
        configured["CAPTURE_BUNDLE_IDENTIFIER"]="local.mobilecapture.development"
        with self.assertRaises(ValueError) as error:
            release.check_signing(configured)
        self.assertNotIn("test-secret-do-not-print", str(error.exception))

    def test_owner_controlled_identity_passes_configuration_check(self):
        configured={key: "fixture" for key in release.SIGNING}
        configured["CAPTURE_BUNDLE_IDENTIFIER"]="com.example.mobilecapture"
        release.check_signing(configured)

    def test_signing_setup_cannot_modify_a_developer_keychain(self):
        environment=dict(os.environ, GITHUB_ACTIONS="false")
        result=subprocess.run(["bash", str(ROOT/"Scripts/configure-release-signing.sh"), "prepare"], env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires a GitHub-hosted runner", result.stderr)

class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.record={"url":"https://dl.google.com/reviewed-fixture.zip", "filename":"fixture.zip", "sha256":hashlib.sha256(b"reviewed").hexdigest()}

    def test_cached_archive_is_hash_checked_without_network(self):
        (self.root/"fixture.zip").write_bytes(b"reviewed")
        with patch.object(cache.urllib.request, "urlopen", side_effect=AssertionError("No network expected")):
            self.assertEqual(cache.download(self.record,self.root).read_bytes(), b"reviewed")

    def test_tampered_existing_archive_is_rejected(self):
        (self.root/"fixture.zip").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError,"checksum mismatch"):
            cache.download(self.record,self.root)

    def test_bad_download_never_becomes_an_accepted_archive(self):
        with patch.object(cache.urllib.request,"urlopen", return_value=io.BytesIO(b"changed")):
            with self.assertRaisesRegex(ValueError,"checksum mismatch"):
                cache.download(self.record,self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_good_download_is_verified_before_reuse(self):
        with patch.object(cache.urllib.request,"urlopen", return_value=io.BytesIO(b"reviewed")):
            self.assertEqual(cache.download(self.record,self.root).read_bytes(), b"reviewed")

    def test_rejects_unreviewed_hosts_and_escaping_filenames(self):
        for changed in ({"url":"http://dl.google.com/fixture.zip"}, {"url":"https://untrusted.example/fixture.zip"}, {"filename":"../fixture.zip"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                cache.download(dict(self.record,**changed),self.root)

class ReleaseAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.package=self.root/"package"
        self.package.mkdir()
        self.output=self.root/"downloads"

    def fixture(self, mode="development", version="1.2.3", app=True):
        path=self.package/f"MobileCapture-1.2.3-arm64-{mode}.zip"
        with zipfile.ZipFile(path,"w") as archive:
            if app:
                archive.writestr("Mobile Capture.app/Contents/Info.plist", plistlib.dumps({"CFBundleShortVersionString":version, "MobileCaptureCompanion":True, "MobileCaptureDevelopmentIdentity":mode=="development"}))
            else: archive.writestr("README.md", "source checkout")
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        (self.package/"SHA256SUMS").write_text(f"{digest}  {path.name}\n")
        return path

    def test_development_asset_has_explicit_name_and_matching_checksum(self):
        self.fixture()
        name=release.stage(self.package,self.output,"1.2.3","development")
        self.assertEqual(name,"MobileCapture-macOS-arm64-development.zip")
        self.assertEqual(sorted(p.name for p in self.output.iterdir()),[name,"SHA256SUMS"])
        checksum=hashlib.sha256((self.output/name).read_bytes()).hexdigest()
        self.assertEqual((self.output/"SHA256SUMS").read_text(),f"{checksum}  {name}\n")

    def test_release_asset_has_stable_download_name(self):
        self.fixture("release")
        self.assertEqual(release.stage(self.package,self.output,"1.2.3","release"),"MobileCapture-macOS-arm64.zip")

    def test_bad_checksum_and_wrong_version_publish_nothing(self):
        self.fixture(version="1.2.2")
        with self.assertRaisesRegex(ValueError,"metadata"):
            release.stage(self.package,self.output,"1.2.3","development")
        self.assertFalse(self.output.exists())
        (self.package/"SHA256SUMS").write_text("wrong checksum")
        with self.assertRaisesRegex(ValueError,"SHA256SUMS"):
            release.stage(self.package,self.output,"1.2.3","development")
        self.assertFalse(self.output.exists())

    def test_source_code_zip_is_never_a_user_app_download(self):
        self.fixture(app=False)
        with self.assertRaisesRegex(ValueError,"not source code"):
            release.stage(self.package,self.output,"1.2.3","development")
        self.assertFalse(self.output.exists())

    def test_existing_staged_assets_are_not_overwritten(self):
        self.fixture()
        self.output.mkdir()
        marker=self.output/"preserved"
        marker.write_text("existing assets")
        with self.assertRaises(FileExistsError):
            release.stage(self.package,self.output,"1.2.3","development")
        self.assertEqual(marker.read_text(),"existing assets")
