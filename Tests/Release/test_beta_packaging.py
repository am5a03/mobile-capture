import importlib.util
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Scripts"))
import beta_updates as beta

spec = importlib.util.spec_from_file_location("release_assets_beta", ROOT / "Scripts/release-assets.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class BetaPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / "Mobile Capture.app"
        (self.app / "Contents").mkdir(parents=True)
        self.config = beta.policy()
        self.tag = "v0.1.2-beta.1"
        self.info = {"CFBundleShortVersionString": "0.1.2", "CFBundleVersion": "2001", "CFBundleIdentifier": self.config["bundleIdentifier"], "MobileCaptureDevelopmentIdentity": True}
        self.write_info()

    def write_info(self):
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps(self.info))

    def test_explicit_beta_seals_exact_policy_and_false_update_defaults(self):
        beta.seal(self.app, self.config, self.tag)
        info = plistlib.loads((self.app / "Contents/Info.plist").read_bytes())
        beta.validate_info(info, self.config, self.tag)
        self.assertEqual(info["SUFeedURL"], self.config["feedURL"])
        self.assertFalse(info["SUAllowsAutomaticUpdates"])
        self.assertTrue(info["SURequireSignedFeed"])
        self.assertTrue(info["SUVerifyUpdateBeforeExtraction"])

    def test_ordinary_build_removes_beta_metadata(self):
        beta.seal(self.app, self.config, self.tag)
        beta.seal(self.app, self.config)
        info = plistlib.loads((self.app / "Contents/Info.plist").read_bytes())
        self.assertFalse(info["CaptureDistributionUpdatesEnabled"])
        self.assertFalse(any(key in info for key in beta.SEALED_POLICY_KEYS))

    def test_tag_version_build_identity_and_policy_drift_fail_before_write(self):
        original = dict(self.info)
        for changed in ({"CFBundleShortVersionString": "0.1.1"}, {"CFBundleVersion": "0"}, {"CFBundleVersion": "2147483648"}, {"CFBundleIdentifier": "com.example.stable"}, {"MobileCaptureDevelopmentIdentity": False}):
            with self.subTest(changed=changed):
                self.info = dict(original, **changed)
                self.write_info()
                before = (self.app / "Contents/Info.plist").read_bytes()
                with self.assertRaises(ValueError):
                    beta.seal(self.app, self.config, self.tag)
                self.assertEqual((self.app / "Contents/Info.plist").read_bytes(), before)
        self.info = original
        self.write_info()
        for tag in ("v0.1.2", "v0.1.2-rc.1", "v0.1.2-beta.0", "v0.1.2-beta.1\n"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                beta.seal(self.app, self.config, tag)
        beta.seal(self.app, self.config, self.tag)
        info = plistlib.loads((self.app / "Contents/Info.plist").read_bytes())
        for key, value in (("SUPublicEDKey", "changed"), ("SURequireSignedFeed", False), ("SUEnableAutomaticChecks", 0)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                beta.validate_info(dict(info, **{key: value}), self.config, self.tag)

    def test_ci_attempts_are_monotonic_and_bounded(self):
        self.assertLess(release.ci_build_number(12, 1), release.ci_build_number(12, 2))
        self.assertLess(release.ci_build_number(12, 999), release.ci_build_number(13, 1))
        for run, attempt in ((0, 1), (1, 0), (1, 1000), (2147484, 1)):
            with self.subTest(run=run, attempt=attempt), self.assertRaises(ValueError):
                release.ci_build_number(run, attempt)

    def test_beta_archive_rejects_unsafe_paths_and_validates_actual_plist(self):
        beta.seal(self.app, self.config, self.tag)
        archive = self.root / "beta.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.write(self.app / "Contents/Info.plist", "Mobile Capture.app/Contents/Info.plist")
        self.assertEqual(beta.archive_info(archive, self.config, self.tag)["CFBundleVersion"], "2001")
        with zipfile.ZipFile(archive, "a") as output:
            output.writestr("Mobile Capture.app/../../escape", "bad")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            beta.archive_info(archive, self.config, self.tag)

    def test_source_defaults_cannot_enable_feed(self):
        self.info.update(CaptureDistributionUpdatesEnabled=False, SUFeedURL=self.config["feedURL"])
        with self.assertRaisesRegex(ValueError, "Disabled"):
            beta.validate_info(self.info, self.config)
