# syntax=docker/dockerfile:1.7

ARG HASSFEST_IMAGE=ghcr.io/home-assistant/hassfest@sha256:4b1adfb1e0a37710af0390708eb8000230b80b2193ccffbeed0a901fa9765181
FROM --platform=linux/amd64 ${HASSFEST_IMAGE} AS validator

WORKDIR /github/workspace

# Both inputs are small, curated, local BuildKit contexts. The upstream
# entrypoint and its Core checkout remain inside the pinned vendor image.
RUN --mount=type=bind,from=hassfest-workspace,target=/github/workspace,ro \
    --mount=type=bind,from=hassfest-arguments,target=/run/hassfest,ro \
    set -eu; \
    mkdir -p /out; \
    status=0; \
    python3 -c 'import json, os; args=json.load(open("/run/hassfest/argv.json", encoding="utf-8")); assert isinstance(args, list) and all(isinstance(arg, str) for arg in args); os.execv("/bin/sh", ["/bin/sh", "/usr/src/homeassistant/script/hassfest/docker/entrypoint.sh", *args])' \
      > /out/validator.log 2>&1 || status=$?; \
    printf '%s\n' "$status" > /out/exit-code; \
    exit 0

# Return only the short validator receipt to the runner.
FROM scratch AS result
COPY --from=validator /out/validator.log /validator.log
COPY --from=validator /out/exit-code /exit-code
