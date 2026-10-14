#!/usr/bin/env python3
"""Resolve and verify the immutable HACS action image used by this run."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import urllib.parse
import urllib.request

REGISTRY = "https://ghcr.io"
IMAGE = "hacs/action"
TAG = "main"
PLATFORM_OS = "linux"
PLATFORM_ARCH = "amd64"
EXPECTED_ENTRYPOINT = ["python3", "/hacs/action.py"]
EXPECTED_WORKDIR = "/hacs"
ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


def request(url: str, *, token: str | None = None, accept: str | None = None):
    headers = {"User-Agent": "private-runner-hacs-validator/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read(), response.headers


def manifest_digest(raw: bytes, headers) -> str:
    digest = headers.get("Docker-Content-Digest")
    if digest is None:
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise RuntimeError(f"Registry returned an invalid manifest digest: {digest!r}")
    if hashlib.sha256(raw).hexdigest() != digest.removeprefix("sha256:"):
        raise RuntimeError("Registry manifest bytes do not match Docker-Content-Digest")
    return digest


def main() -> None:
    if platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("HACS action runner must be linux/amd64 for this validator")

    scope = urllib.parse.urlencode({"scope": f"repository:{IMAGE}:pull", "service": "ghcr.io"})
    token_body, _ = request(f"{REGISTRY}/token?{scope}")
    token_doc = json.loads(token_body)
    token = token_doc.get("token") or token_doc.get("access_token")
    if not token:
        raise RuntimeError("GHCR did not return an anonymous pull token")

    url = f"{REGISTRY}/v2/{IMAGE}/manifests/{TAG}"
    raw, headers = request(url, token=token, accept=ACCEPT)
    index_digest = manifest_digest(raw, headers)
    manifest = json.loads(raw)
    platform_digest = index_digest

    if "manifests" in manifest:
        matches = [
            item
            for item in manifest["manifests"]
            if item.get("platform", {}).get("os") == PLATFORM_OS
            and item.get("platform", {}).get("architecture") == PLATFORM_ARCH
            and item.get("platform", {}).get("variant") in (None, "")
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one {PLATFORM_OS}/{PLATFORM_ARCH} image manifest, found {len(matches)}"
            )
        platform_digest = matches[0]["digest"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", platform_digest):
            raise RuntimeError(f"Registry returned an invalid platform digest: {platform_digest!r}")
        raw, headers = request(
            f"{REGISTRY}/v2/{IMAGE}/manifests/{platform_digest}",
            token=token,
            accept=ACCEPT,
        )
        if manifest_digest(raw, headers) != platform_digest:
            raise RuntimeError("Platform manifest digest differs from its index descriptor")
        manifest = json.loads(raw)

    config_digest = manifest.get("config", {}).get("digest")
    if not isinstance(config_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", config_digest):
        raise RuntimeError("Image manifest has no valid config digest")
    config_raw, _ = request(f"{REGISTRY}/v2/{IMAGE}/blobs/{config_digest}", token=token)
    if "sha256:" + hashlib.sha256(config_raw).hexdigest() != config_digest:
        raise RuntimeError("Image config bytes do not match the manifest config digest")
    image_config = json.loads(config_raw)
    runtime = image_config.get("config") or {}
    entrypoint = runtime.get("Entrypoint") or []
    command = runtime.get("Cmd") or []
    workdir = runtime.get("WorkingDir") or "/"
    if image_config.get("os") != PLATFORM_OS or image_config.get("architecture") != PLATFORM_ARCH:
        raise RuntimeError("Resolved image config platform is not linux/amd64")
    if entrypoint != EXPECTED_ENTRYPOINT or command:
        raise RuntimeError(
            f"HACS image entrypoint/Cmd changed: entrypoint={entrypoint!r}, Cmd={command!r}"
        )
    if workdir != EXPECTED_WORKDIR:
        raise RuntimeError(f"HACS image working directory changed: {workdir!r}")

    image = f"ghcr.io/{IMAGE}@{index_digest}"
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        raise RuntimeError("GITHUB_OUTPUT is not set")
    with open(github_output, "a", encoding="utf-8") as output:
        output.write(f"image={image}\n")
        output.write(f"index_digest={index_digest}\n")
        output.write(f"platform_digest={platform_digest}\n")

    print(f"Resolved HACS image: {image}")
    print(f"linux/amd64 manifest: {platform_digest}")
    print(f"Verified OCI Entrypoint={entrypoint!r}, Cmd={command!r}, WorkingDir={workdir!r}")


if __name__ == "__main__":
    main()
