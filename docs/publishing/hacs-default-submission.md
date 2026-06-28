# HACS Default Repository Submission

This document records attempts to add `javaDevJT/ha-xsense-home` to the upstream `hacs/default` repository list.

## Current Upstream Process

Checked on 2026-06-28:

- HACS default repository submissions are made by adding the repository to the matching file in `hacs/default`.
- Custom integrations are added to the `integration` JSON list on the `master` branch.
- The PR must use the HACS pull request checklist with all required boxes checked.
- The PR must include links to:
  - the current release
  - a successful HACS Action run without `ignore`
  - a successful Hassfest run for integrations
- The `New default repository` label is applied by upstream automation after the checklist is accepted.

Source docs:

- `https://www.hacs.xyz/docs/publish/include/`
- `https://github.com/hacs/default`

## Source Repository Evidence

Repository: `https://github.com/javaDevJT/ha-xsense-home`

- Public: yes
- Issues enabled: yes
- Description present: yes
- Topics present: yes
- Current release: `https://github.com/javaDevJT/ha-xsense-home/releases/tag/v0.1.4`
- HACS Action: `https://github.com/javaDevJT/ha-xsense-home/actions/runs/28338163794`
- Hassfest: `https://github.com/javaDevJT/ha-xsense-home/actions/runs/28338163798`

## Upstream Pull Requests

### PR 8818

URL: `https://github.com/hacs/default/pull/8818`

Status: closed by `hacs-bot`.

Reason: the PR body did not use the required checklist template with checked boxes. The bot comment said to submit a new PR when ready.

### PR 8819

URL: `https://github.com/hacs/default/pull/8819`

Status: open and in the HACS review queue.

Branch: `javaDevJT:codex/add-xsense-home-default`

Commit in fork: `87c7773`

Upstream change:

- Added `javaDevJT/ha-xsense-home` to `integration` immediately after `javaDevJT/DTE-Rates-for-Home-Assistant`.

Local validation before opening:

- `jq --raw-output . appdaemon blacklist critical integration netdaemon plugin python_script removed template theme`
- `python3 scripts/is_sorted.py`
- Python check that `javaDevJT/ha-xsense-home` appears exactly once and remains sorted between neighboring entries.

Upstream validation:

- Lint run: `https://github.com/hacs/default/actions/runs/28338562075`
- Check run: `https://github.com/hacs/default/actions/runs/28338563087`
- Jobs passed: Preflight, Editable PR, Releases, Hassfest, HACS action, Owner, Existing repository, Removed repository, and Action checks completed.

Remaining status:

- Await HACS maintainer review.
- Do not comment, open a duplicate PR, request reviews, or merge upstream `master` into the branch unless maintainers ask.
