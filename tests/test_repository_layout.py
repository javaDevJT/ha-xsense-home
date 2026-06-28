"""Repository-level checks for the X-Sense HACS custom integration."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = PROJECT_ROOT / "custom_components" / "xsense"


class RepositoryLayoutTest(unittest.TestCase):
    """Verify the repository is shaped like an installable HACS integration."""

    def test_custom_component_manifest_is_hacs_ready(self) -> None:
        manifest_path = COMPONENT_DIR / "manifest.json"
        self.assertTrue(manifest_path.exists(), "custom component manifest is missing")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["domain"], "xsense")
        self.assertEqual(manifest["name"], "X-Sense Home Security")
        self.assertIs(manifest["config_flow"], True)
        self.assertEqual(manifest["integration_type"], "hub")
        self.assertEqual(manifest["iot_class"], "cloud_polling")
        self.assertEqual(manifest["requirements"], ["python-xsense[async]==0.0.16", "paho-mqtt==2.1.0"])
        self.assertRegex(manifest.get("version", ""), r"^\d+\.\d+\.\d+$")

    def test_expected_component_files_are_present(self) -> None:
        expected_files = {
            "__init__.py",
            "binary_sensor.py",
            "button.py",
            "config_flow.py",
            "const.py",
            "coordinator.py",
            "diagnostics.py",
            "entity.py",
            "manifest.json",
            "mqtt.py",
            "sensor.py",
            "strings.json",
        }

        missing = sorted(path for path in expected_files if not (COMPONENT_DIR / path).exists())
        self.assertEqual(missing, [])

    def test_hacs_metadata_identifies_xsense_domain(self) -> None:
        hacs_path = PROJECT_ROOT / "hacs.json"
        self.assertTrue(hacs_path.exists(), "hacs.json is missing")

        hacs = json.loads(hacs_path.read_text(encoding="utf-8"))
        self.assertEqual(hacs["name"], "X-Sense Home Security")
        self.assertEqual(hacs["domains"], ["xsense"])
        self.assertIs(hacs["render_readme"], True)

    def test_readme_documents_install_and_account_model(self) -> None:
        readme_path = PROJECT_ROOT / "README.md"
        self.assertTrue(readme_path.exists(), "README.md is missing")
        readme = readme_path.read_text(encoding="utf-8")

        self.assertIn("custom_components/xsense", readme)
        self.assertIn("second X-Sense account", readme)
        self.assertIn("share", readme.lower())
        self.assertIn("restart Home Assistant", readme)
        self.assertTrue(re.search(r"SBS50|XS0B-MR|XP0A-MR", readme), "README should name supported device families")


if __name__ == "__main__":
    unittest.main()
