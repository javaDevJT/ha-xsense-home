# X-Sense Home Assistant Integration Investigation

Date: 2026-06-28

## Summary

An X-Sense Home integration is feasible. The best baseline is not the older HACS fork alone; it is Theo Snel's newer `homeassistant-core` branch `xsense`, backed by the `python-xsense` library.

The integration is cloud-based. The X-Sense Home Security app API uses AWS Cognito SRP authentication, HTTPS API calls to `https://api.x-sense-iot.com/app`, and AWS-signed MQTT/WebSocket behavior for push-style updates. Home Assistant should model this as a hub/cloud integration, with careful credential handling and a dedicated X-Sense account shared from the user's primary account.

## Key Findings

- Official X-Sense pages now advertise Home Assistant compatibility for smoke, CO, combination, and heat alarms connected to a base station.
- Official product pages identify relevant device families:
  - `XP0A-MR31`: smoke/CO alarm bundle with SBS50 base station, 915.275 MHz interconnect, app/base-station mode.
  - `XS0B-iR` and `XP0A-iR`: direct 2.4 GHz Wi-Fi app devices.
  - The homepage lists `XS0B-MR` bundle variants including `XS0B-MR31`, `XS0B-MR61`, and `XS0B-MR121`.
- There is prior Home Assistant work:
  - `M4D1NG3R/ha-xsense-component`: public HACS custom component, not archived, but pinned to `python-xsense==0.0.7`.
  - `Elwinmage/ha-xsense-component`: archived origin/older repository.
  - `theosnel/homeassistant-core` branch `xsense`: newer Home Assistant integration code, modified in 2025, using `python-xsense[async]==0.0.16` and `paho-mqtt==2.1.0`.
  - `theosnel/python-xsense`: active Python client. PyPI latest observed version was `0.0.17`.
- The newer HA branch exposes platforms:
  - `binary_sensor`
  - `button`
  - `sensor`
- The newer HA branch manifest describes:
  - domain: `xsense`
  - name: `X-Sense Home Security`
  - integration type: `hub`
  - IoT class: `cloud_polling`
  - quality scale: `legacy`
- Entity/action surface observed in the HA branch:
  - binary sensors: `is_life_end`, `alarm_status`, `mute_status`, `activate`, `door`, `connected`
  - sensors: `wifi_rssi`, `wifi_ssid`, `sw_version`, `wifi_sw`, `serial_number`, `ip`, `ip_address`, `alarm_vol`, `voice_vol`, `co`, `temperature`, `humidity`, `battery`, `rf_level`
  - button actions: `test`; `mute` appears present in code but commented out in the description tuple
- `python-xsense` known model mappings include `SBS50`, `SC07-WX`, `SC07-MR`, `SWS51`, `STH0A`, `STH0B`, `STH51`, `XC01-M`, `XC04-WX`, `XH02-M`, `XP0A-MR`, `XP02S-MR`, `XS01-M`, `XS01-WX`, `XS0B-MR`, `XS03-iWX`, and `XS03-WX`.
- The HACS fork README confirms tested devices including SBS50, XH02-M, XC01-M, XC04-WX, XS01-M/WX, XS03-WX, SC07-WX, SWS51, and STH51.

## Recommended Direction

1. Create a clean HACS custom integration repository in this worktree using `theosnel/homeassistant-core` branch `xsense` as the starting implementation.
2. Update the dependency target after checking `python-xsense` `0.0.17` compatibility; do not blindly keep the HACS fork's `0.0.7` pin.
3. Keep setup instructions aligned with the prior component guidance:
   - create a second X-Sense account for Home Assistant
   - share only supported devices from the primary X-Sense account to the Home Assistant account
4. Add focused tests around config flow, coordinator startup, entity descriptions, unique IDs, and unavailable/auth failure handling before release.
5. Verify in real Home Assistant/HACS after install, including the visible integration page, entities, logs, and restart behavior.

## 2026-06-28 Implementation Pass

- Imported `theosnel/homeassistant-core` branch `xsense`, path `homeassistant/components/xsense`, into `custom_components/xsense`.
- Added HACS-facing repository metadata in `hacs.json`.
- Added a top-level README with HACS installation, local installation, second-account setup guidance, supported device families, and explicit live-validation gaps.
- Added `version: 0.1.0` to `custom_components/xsense/manifest.json` for custom integration packaging.
- Preserved the upstream dependency pin from the newer HA branch: `python-xsense[async]==0.0.16` and `paho-mqtt==2.1.0`.
- Copied the upstream Home Assistant Apache-2.0 license as `LICENSE.md`.
- Added repository-shape tests in `tests/test_repository_layout.py`.
- Local verification completed during this pass:
  - `python3 -m unittest discover -s tests -v`
  - `python3 -m compileall -q custom_components/xsense tests`

This pass does not prove live X-Sense authentication, cloud API access, MQTT updates, or Home Assistant runtime behavior.

## 2026-06-28 HACS Validation Fix

The initial `v0.1.0` HACS Action failed three validation checks:

- Repository topics were missing in GitHub.
- `custom_components/xsense/manifest.json` did not include `issue_tracker`.
- `hacs.json` included unsupported keys: `domains` and `render_readme`.

Fix applied:

- Added GitHub topics: `home-assistant`, `hacs`, `hacs-integration`, `x-sense`, `xsense`, `smoke-detector`, and `carbon-monoxide`.
- Added `issue_tracker: https://github.com/javaDevJT/ha-xsense-home/issues` to the integration manifest.
- Removed unsupported keys from `hacs.json`.
- Bumped manifest version to `0.1.1` for a corrected HACS test release.
- Verified the corrected commit `c82ae50` passed HACS Action run `28336801298` and Hassfest run `28336801289`.
- Published `v0.1.1` at `https://github.com/javaDevJT/ha-xsense-home/releases/tag/v0.1.1`.

## 2026-06-28 Runtime MQTT Subscription Fix

Home Assistant runtime error from the custom integration:

```text
TypeError: Subscription.__init__() missing 1 required positional argument: 'subscription_id'
```

Root cause: the imported X-Sense MQTT bridge constructed `homeassistant.components.mqtt.client.Subscription` using the older six-argument shape. Current Home Assistant requires a seventh `subscription_id` field. Current Home Assistant core generates that ID per topic using its MQTT subscription ID generator before constructing `Subscription`.

Fix applied:

- Added local topic-to-subscription-id tracking in `custom_components/xsense/mqtt.py`.
- Passed `subscription_id` into the `Subscription` constructor.
- Added regression coverage in `tests/test_repository_layout.py` to catch old six-argument `Subscription(...)` calls.
- Bumped manifest version to `0.1.2`.

## Risks And Open Questions

- Official Home Assistant compatibility may refer to selected base-station devices only; direct Wi-Fi devices may behave differently.
- The HA branch quality metadata still marks many quality-scale rules as `todo`, so it likely needs modernization before a confident HACS release.
- `boto3`, `botocore`, `pycognito`, and `paho-mqtt` dependency behavior should be reviewed against current Home Assistant packaging constraints.
- Need live credentials/device access to prove current X-Sense auth, polling, and MQTT still work.
- Need to decide whether to preserve cloud polling only or enable MQTT updates in the first HACS release.

## Sources Checked

- X-Sense official homepage: `https://www.x-sense.com/`
- X-Sense EU homepage: `https://eu.x-sense.com/`
- X-Sense `XP0A-MR31` product page: `https://www.x-sense.com/products/interlinked-smart-wi-fi-smoke-and-carbon-monoxide-detector-with-voice-alerts-x-sense-xp0a-mr31`
- X-Sense `XS0B-iR` product page: `https://www.x-sense.com/products/xs0b-ir-smart-smoke-alarm`
- X-Sense `XP0A-iR` product page: `https://www.x-sense.com/products/x-sense-wifi-smoke-and-co-detector-xp0a-ir`
- Home Assistant integrations index: `https://www.home-assistant.io/integrations/`
- HACS include docs: `https://www.hacs.xyz/docs/publish/include/`
- `M4D1NG3R/ha-xsense-component`: `https://github.com/M4D1NG3R/ha-xsense-component`
- `Elwinmage/ha-xsense-component`: `https://github.com/Elwinmage/ha-xsense-component`
- `theosnel/homeassistant-core` branch `xsense`: `https://github.com/theosnel/homeassistant-core/tree/xsense/homeassistant/components/xsense`
- `theosnel/python-xsense`: `https://github.com/theosnel/python-xsense`
- PyPI `python-xsense`: `https://pypi.org/project/python-xsense/`
