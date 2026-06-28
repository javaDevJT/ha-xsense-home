"""Repository-level checks for the X-Sense HACS custom integration."""

from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = PROJECT_ROOT / "custom_components" / "xsense"


class RepositoryLayoutTest(unittest.TestCase):
    """Verify the repository is shaped like an installable HACS integration."""

    def _description_names(self, file_name: str, call_name: str) -> dict[str, str | None]:
        tree = ast.parse((COMPONENT_DIR / file_name).read_text(encoding="utf-8"))
        descriptions: dict[str, str | None] = {}

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != call_name:
                continue

            kwargs = {
                keyword.arg: keyword.value
                for keyword in node.keywords
                if keyword.arg is not None
            }
            key_node = kwargs.get("key")
            if not isinstance(key_node, ast.Constant) or not isinstance(
                key_node.value, str
            ):
                continue

            name_node = kwargs.get("name")
            descriptions[key_node.value] = (
                name_node.value
                if isinstance(name_node, ast.Constant)
                and isinstance(name_node.value, str)
                else None
            )

        return descriptions

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
        self.assertEqual(manifest["issue_tracker"], "https://github.com/javaDevJT/ha-xsense-home/issues")
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
        self.assertEqual(hacs.get("homeassistant"), "2025.12.0")
        self.assertNotIn("domains", hacs)
        self.assertNotIn("render_readme", hacs)

    def test_readme_documents_install_and_account_model(self) -> None:
        readme_path = PROJECT_ROOT / "README.md"
        self.assertTrue(readme_path.exists(), "README.md is missing")
        readme = readme_path.read_text(encoding="utf-8")

        self.assertIn("custom_components/xsense", readme)
        self.assertIn("second X-Sense account", readme)
        self.assertIn("share", readme.lower())
        self.assertIn("restart Home Assistant", readme)
        self.assertTrue(re.search(r"SBS50|XS0B-MR|XP0A-MR", readme), "README should name supported device families")

    def test_mqtt_subscriptions_include_subscription_id(self) -> None:
        mqtt_path = COMPONENT_DIR / "mqtt.py"
        tree = ast.parse(mqtt_path.read_text(encoding="utf-8"))

        bad_calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "Subscription":
                continue
            keyword_names = {keyword.arg for keyword in node.keywords}
            if len(node.args) < 7 and "subscription_id" not in keyword_names:
                bad_calls.append(node.lineno)

        self.assertEqual(
            bad_calls,
            [],
            "Subscription construction must include subscription_id for current Home Assistant",
        )

    def test_entity_descriptions_have_readable_names(self) -> None:
        expected_sensor_names = {
            "wifi_rssi": "Wi-Fi signal strength",
            "wifi_ssid": "Wi-Fi SSID",
            "sw_version": "Software version",
            "wifi_sw": "Wi-Fi module firmware",
            "ip": "IP address",
            "alarm_vol": "Alarm volume",
            "voice_vol": "Voice volume",
            "co": "Carbon monoxide",
            "temperature": "Temperature",
            "humidity": "Humidity",
            "battery": "Battery",
            "rf_level": "RF signal strength",
        }
        expected_binary_sensor_names = {
            "is_life_end": "End of life",
            "alarm_status": "Alarm detected",
            "mute_status": "Muted",
            "activate": "Alarm active",
            "door": "Door",
            "connected": "Connected",
        }
        expected_button_names = {
            "test": "Test alarm",
        }

        self.assertEqual(
            self._description_names("sensor.py", "XSenseSensorEntityDescription"),
            expected_sensor_names,
        )
        self.assertEqual(
            self._description_names(
                "binary_sensor.py", "XSenseBinarySensorEntityDescription"
            ),
            expected_binary_sensor_names,
        )
        self.assertEqual(
            self._description_names("button.py", "XSenseButtonEntityDescription"),
            expected_button_names,
        )


if __name__ == "__main__":
    unittest.main()
