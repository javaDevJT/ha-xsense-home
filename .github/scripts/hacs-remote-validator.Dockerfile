# syntax=docker/dockerfile:1.7
ARG HACS_ACTION_IMAGE
FROM ${HACS_ACTION_IMAGE} AS validator

ARG GITHUB_ACTOR
ARG GITHUB_REPOSITORY
ARG GITHUB_REF
ARG GITHUB_SHA
ARG GITHUB_EVENT_NAME
ARG INPUT_CATEGORY=integration
ARG INPUT_IGNORE=
ARG INPUT_REPOSITORY=
ARG INPUT_COMMENT=true

ENV GITHUB_ACTOR=${GITHUB_ACTOR} \
    GITHUB_REPOSITORY=${GITHUB_REPOSITORY} \
    GITHUB_REF=${GITHUB_REF} \
    GITHUB_SHA=${GITHUB_SHA} \
    GITHUB_EVENT_NAME=${GITHUB_EVENT_NAME} \
    GITHUB_EVENT_PATH=/run/secrets/github-event.json \
    GITHUB_WORKSPACE=/github/workspace \
    INPUT_CATEGORY=${INPUT_CATEGORY} \
    INPUT_IGNORE=${INPUT_IGNORE} \
    INPUT_REPOSITORY=${INPUT_REPOSITORY} \
    INPUT_COMMENT=${INPUT_COMMENT}

WORKDIR /hacs

# The pinned HACS action source only reads files from GITHUB_WORKSPACE when it
# validates HACS's own default repository. These snapshots validate external
# javaDevJT repositories through the GitHub API, so keep this context empty and
# avoid sending checkout data or .git credentials to the remote builder.
RUN mkdir -p /github/workspace

RUN --mount=type=secret,id=hacs-token,target=/run/secrets/hacs-token,required=true \
    --mount=type=secret,id=github-event,target=/run/secrets/github-event.json,required=true \
    mkdir -p /out; \
    status=0; \
    INPUT_GITHUB_TOKEN="$(cat /run/secrets/hacs-token)" python3 /hacs/action.py > /out/validator.log 2>&1 || status=$?; \
    printf '%s\n' "$status" > /out/exit-code; \
    exit 0

FROM scratch AS result
COPY --from=validator /out/validator.log /validator.log
COPY --from=validator /out/exit-code /exit-code
