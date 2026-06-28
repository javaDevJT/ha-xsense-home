# X-Sense Home Security for Home Assistant

Custom Home Assistant integration for X-Sense Home Security devices. This repository packages the newer upstream `xsense` Home Assistant work as a HACS-installable custom integration.

## Current Status

This is an initial HACS-ready slice. The component code is imported from Theo Snel's `homeassistant-core` `xsense` branch and uses `python-xsense[async]==0.0.16` plus `paho-mqtt==2.1.0`.

Live validation with an X-Sense account and real devices is still required before treating this as production-ready.

## Supported Device Families

The upstream library includes mappings for base station and sensor families such as:

- `SBS50` base station
- `XS0B-MR`, `XS01-M`, `XS01-WX`, `XS03-WX`, `XS03-iWX` smoke alarms
- `XP0A-MR`, `XP02S-MR`, `SC07-WX`, `SC07-MR` smoke/CO alarms
- `XC01-M`, `XC04-WX` CO alarms
- `XH02-M` heat alarm
- `SWS51` water leak sensor
- `STH0A`, `STH0B`, `STH51` thermometer/hygrometer devices

Device support depends on what the X-Sense cloud API returns for your account.

## Recommended Account Model

Create a second X-Sense account for Home Assistant in the X-Sense Home Security app. From your primary account, share only supported devices to the second X-Sense account. Use that second account's email and password in Home Assistant.

This keeps Home Assistant automation access separate from your owner account and matches the setup model used by the prior community integration.

## HACS Installation

1. In Home Assistant, open HACS.
2. Add this repository as a custom repository with category `Integration`.
3. Install `X-Sense Home Security`.
4. Restart Home Assistant.
5. Go to **Settings > Devices & services > Add integration**.
6. Search for `X-Sense Home Security`.
7. Enter the second X-Sense account credentials.

HACS updates also require a restart Home Assistant cycle before updated integration code is loaded.

## Local Manual Installation

Copy `custom_components/xsense` into your Home Assistant config directory:

```text
/config/custom_components/xsense
```

Restart Home Assistant, then add the integration from **Settings > Devices & services**.

## What It Exposes

The imported integration includes `binary_sensor`, `sensor`, and `button` platforms. Expected entities include alarm state, connectivity, life-end status, mute/activation state, Wi-Fi diagnostics, CO, temperature, humidity, battery, RF level, and test button support where the device exposes those capabilities.

## Validation Still Needed

- Confirm login with current X-Sense credentials.
- Confirm device discovery for the user's actual devices.
- Confirm polling and MQTT update behavior in Home Assistant logs.
- Confirm entity availability after Home Assistant restart.
- Decide whether to publish as a public HACS repository after live testing.

## Provenance

Integration code baseline:

- `theosnel/homeassistant-core`, branch `xsense`, path `homeassistant/components/xsense`
- `theosnel/python-xsense`

This repo keeps the Apache-2.0 license inherited from Home Assistant Core.
