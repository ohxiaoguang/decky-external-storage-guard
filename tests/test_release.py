import unittest
from scripts.check_release import validate_release


class ReleaseVersionTests(unittest.TestCase):
    def lock(self, version):
        return {"version": version, "packages": {"": {"version": version}}}

    def test_matching_stable_and_prerelease(self):
        for version in ("0.1.0", "0.2.0-beta.1"):
            validate_release(f"v{version}", {"version": version}, self.lock(version))

    def test_wrong_tag_cannot_publish_other_package_version(self):
        for tag in ("v0.2.0", "0.1.0", "vanything"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                validate_release(tag, {"version": "0.1.0"}, self.lock("0.1.0"))

    def test_stale_lockfile_root_or_package_rejected(self):
        for lock in ({}, {"version": "0.0.1"}, {"version": "0.1.0", "packages": {"": {"version": "0.0.1"}}}):
            with self.subTest(lock=lock), self.assertRaises(ValueError):
                validate_release("v0.1.0", {"version": "0.1.0"}, lock)

    def test_install_manifest_declares_privileged_native_udisks_backend(self):
        import json
        from pathlib import Path
        manifest = json.loads((Path(__file__).resolve().parents[1] / "plugin.json").read_text())
        self.assertEqual(manifest["flags"], ["root"])
        self.assertEqual(manifest["api_version"], 1)

    def test_release_asset_filename_stays_compatible_with_update_link(self):
        from pathlib import Path
        from scripts.package import ARCHIVE
        self.assertEqual(ARCHIVE.name, "External-Storage-Guard.zip")
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/release.yml").read_text()
        for command in ("gh release upload", "gh release create"):
            line = next(line for line in workflow.splitlines() if command in line)
            self.assertIn("External-Storage-Guard.zip", line)
