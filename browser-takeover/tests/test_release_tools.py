import importlib.util
import unittest
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "release_tools.py"
SPEC = importlib.util.spec_from_file_location("release_tools", MODULE_PATH)
release_tools = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_tools)


class ReleaseToolsTests(unittest.TestCase):
    def test_versions_are_consistent(self):
        self.assertEqual(release_tools.release_version(), "0.6.0")

    def test_release_validation_passes(self):
        checks = release_tools.validate_release()
        self.assertIn("version consistency", checks)

    def test_packages_have_expected_layout_and_checksums(self):
        artifacts = release_tools.package_release()
        extension_zip, plugin_zip, checksum_path = artifacts
        with zipfile.ZipFile(extension_zip) as archive:
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("background.js", archive.namelist())
        with zipfile.ZipFile(plugin_zip) as archive:
            self.assertIn("browser-takeover/.codex-plugin/plugin.json", archive.namelist())
            self.assertIn("browser-takeover/scripts/browser_takeover_mcp.py", archive.namelist())
        checksums = checksum_path.read_text(encoding="utf-8")
        self.assertIn(extension_zip.name, checksums)
        self.assertIn(plugin_zip.name, checksums)
