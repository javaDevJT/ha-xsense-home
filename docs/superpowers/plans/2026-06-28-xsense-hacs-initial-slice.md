# X-Sense HACS Initial Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first installable HACS custom integration repository for X-Sense Home Security from the newer upstream Home Assistant `xsense` branch.

**Architecture:** Import the upstream Home Assistant component into `custom_components/xsense`, keep it as a cloud hub integration backed by `python-xsense`, and add repository-level HACS metadata, README, tests, and research notes. The first slice focuses on an installable custom repository and local static verification, not live X-Sense account validation.

**Tech Stack:** Home Assistant custom component, HACS metadata, Python standard-library tests, upstream `python-xsense[async]`, `paho-mqtt`.

---

### Task 1: Repository Shape Tests

**Files:**
- Create: `tests/test_repository_layout.py`

- [ ] **Step 1: Write failing tests**

Create tests that assert `custom_components/xsense/manifest.json`, platform files, `hacs.json`, and README setup guidance exist with expected values.

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m unittest discover -s tests -v`

Expected: failure because the component and HACS metadata do not exist yet.

### Task 2: Import Component And HACS Metadata

**Files:**
- Create: `custom_components/xsense/*`
- Create: `hacs.json`
- Create: `README.md`

- [ ] **Step 1: Import upstream component**

Use `theosnel/homeassistant-core` branch `xsense`, path `homeassistant/components/xsense`, as the source baseline.

- [ ] **Step 2: Adapt manifest for HACS**

Add a custom-integration `version`, keep `domain: xsense`, `config_flow: true`, `integration_type: hub`, `iot_class: cloud_polling`, and upstream requirements.

- [ ] **Step 3: Add HACS metadata and README**

Document the second-account sharing model, install path, restart requirement, supported device families, and live-validation status.

- [ ] **Step 4: Run tests to verify pass**

Run: `python3 -m unittest discover -s tests -v`

Expected: all repository-shape tests pass.

### Task 3: Final Verification

**Files:**
- Modify: `docs/research/2026-06-28-x-sense-home-assistant-investigation.md`

- [ ] **Step 1: Update research note with implementation result**

Append what was imported, dependency versions, and what remains unverified.

- [ ] **Step 2: Run static checks**

Run: `python3 -m unittest discover -s tests -v`

Run: `python3 -m compileall custom_components/xsense tests`

Run: `git diff --check`

Expected: all commands exit cleanly.
