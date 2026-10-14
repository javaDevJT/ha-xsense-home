#!/usr/bin/env python3
"""Create curated BuildKit contexts with known credential paths omitted."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sys


CONTAINER_WORKSPACE = Path("/github/workspace")
IGNORED_DIRS = {
    ".ci",
    ".git",
    ".github",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "node_modules",
    "trustedadapter",
    "venv",
}
CREDENTIAL_DIRS = {
    ".aws",
    ".azure",
    ".config",
    ".docker",
    ".gnupg",
    ".kube",
    ".ssh",
    ".storage",
}
SECRET_NAMES = {
    ".netrc",
    "credentials.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
}
PRIVATE_KEY_STEMS = {
    "id_dsa",
    "id_ecdsa",
    "id_ecdsa_sk",
    "id_ed25519",
    "id_ed25519_sk",
    "id_rsa",
    "id_xmss",
}
SECRET_SUFFIXES = {".key", ".p12", ".pem", ".pfx", ".secret", ".token"}
SOURCE_SUFFIXES = {
    ".bash",
    ".c",
    ".cc",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".jinja",
    ".jinja2",
    ".kt",
    ".m",
    ".mm",
    ".php",
    ".py",
    ".pyi",
    ".rs",
    ".sh",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}
SENSITIVE_NAME_COMPONENTS = {
    "api",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "credentials",
    "key",
    "password",
    "passwd",
    "secret",
    "secrets",
    "token",
    "tokens",
}


class ContextError(Exception):
    """Invalid source or unsafe context content."""


def is_secret(path: Path) -> bool:
    name = path.name.casefold()
    stem = path.stem.casefold()
    suffix = path.suffix.casefold()
    # Keep source code even when its filename contains a sensitive term.
    # This is a filename filter for common credential data, not a scanner for
    # arbitrary strings embedded in source or other retained resources.
    if suffix in SOURCE_SUFFIXES:
        return False

    stem_components = set(re.split(r"[^a-z0-9]+", stem))
    return (
        name in SECRET_NAMES
        or name == ".env"
        or name.startswith(".env.")
        or name in {"credential", "credentials", "secret", "secrets", "git-credentials"}
        or name.startswith(
            (
                "credential.",
                "credentials.",
                "secret.",
                "secrets.",
                "secret-",
                "secrets-",
                "secret_",
                "secrets_",
            )
        )
        or bool(stem_components & SENSITIVE_NAME_COMPONENTS)
        or stem in PRIVATE_KEY_STEMS
        or name.startswith(("service-account", "service_account"))
        or suffix in SECRET_SUFFIXES
    )


def _copy_node(source: Path, destination: Path, source_root: Path) -> None:
    # Hassfest reads manifests and integration resources with ordinary names.
    # Dotfiles and dot-directories are repository/host configuration, not
    # validator inputs, and often carry credentials; exclude them by default.
    if (
        source.name.startswith(".")
        or source.name in IGNORED_DIRS
        or source.name in CREDENTIAL_DIRS
        or is_secret(source)
    ):
        return

    if source.is_symlink():
        link_target = os.readlink(source)
        if Path(link_target).is_absolute():
            raise ContextError(f"Refusing absolute symlink in Hassfest context: {source}")
        resolved_target = (source.parent / link_target).resolve(strict=False)
        try:
            resolved_target.relative_to(source_root)
        except ValueError as err:
            raise ContextError(f"Refusing symlink that escapes its source tree: {source}") from err
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(link_target)
        return

    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            _copy_node(child, destination / child.name, source_root)
        return

    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)


def _copy_tree(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ContextError(f"Expected a directory: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    for child in sorted(source.iterdir(), key=lambda item: item.name):
        _copy_node(child, destination / child.name, source)


def _source_path(value: str, workspace: Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    try:
        result = candidate.resolve(strict=True)
    except FileNotFoundError as err:
        raise ContextError(f"Integration path does not exist: {value}") from err
    if not result.is_dir():
        raise ContextError(f"Integration path is not a directory: {value}")
    if not (result / "manifest.json").is_file():
        raise ContextError(f"Integration path has no root manifest.json: {value}")
    return result


def _parse_args(arguments: list[str]) -> tuple[list[str], list[str]]:
    """Validate options and report integration paths for context staging."""
    rewritten: list[str] = []
    integration_paths: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--integration-path":
            index += 1
            if index == len(arguments):
                raise ContextError("--integration-path requires a directory")
            integration_paths.append(arguments[index])
            rewritten.extend(["--integration-path", ""])
        elif argument.startswith("--integration-path="):
            integration_paths.append(argument.partition("=")[2])
            rewritten.append("")
        elif argument == "--core-path":
            index += 1
            if index == len(arguments):
                raise ContextError("--core-path requires a value")
            if arguments[index] != "/usr/src/homeassistant":
                raise ContextError("--core-path must refer to the pinned image at /usr/src/homeassistant")
            # The vendor entrypoint detects this option before its discovery
            # step using only the --core-path=VALUE spelling.
            rewritten.append("--core-path=/usr/src/homeassistant")
        elif argument.startswith("--core-path="):
            value = argument.partition("=")[2]
            if value != "/usr/src/homeassistant":
                raise ContextError("--core-path must refer to the pinned image at /usr/src/homeassistant")
            rewritten.append(argument)
        elif argument == "--action" or argument.startswith("--action="):
            if argument != "--action=validate":
                raise ContextError("The vendor Hassfest action is fixed to validate mode")
            rewritten.append(argument)
        else:
            rewritten.append(argument)
        index += 1

    return rewritten, integration_paths


def prepare_context(workspace_value: str, output_value: str, arguments: list[str]) -> None:
    workspace = Path(workspace_value).resolve(strict=True)
    if not workspace.is_dir():
        raise ContextError(f"GITHUB_WORKSPACE is not a directory: {workspace}")

    output = Path(output_value).resolve(strict=False)
    build_context = output / "context"
    workspace_context = output / "workspace"
    arguments_context = output / "arguments"
    build_context.mkdir(parents=True, exist_ok=True)
    workspace_context.mkdir(parents=True, exist_ok=True)
    arguments_context.mkdir(parents=True, exist_ok=True)

    rewritten, integration_values = _parse_args(arguments)
    if integration_values:
        container_args: list[str] = []
        source_index = 0
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument == "--integration-path":
                source = _source_path(arguments[index + 1], workspace)
                destination = workspace_context / f"integration-{source_index}"
                _copy_tree(source, destination)
                container_args.extend(["--integration-path", str(CONTAINER_WORKSPACE / destination.name)])
                source_index += 1
                index += 2
                continue
            if argument.startswith("--integration-path="):
                source = _source_path(argument.partition("=")[2], workspace)
                destination = workspace_context / f"integration-{source_index}"
                _copy_tree(source, destination)
                container_args.append(f"--integration-path={CONTAINER_WORKSPACE / destination.name}")
                source_index += 1
                index += 1
                continue
            if argument == "--core-path":
                container_args.append(f"--core-path={arguments[index + 1]}")
                index += 2
                continue
            container_args.append(argument)
            index += 1

        if not any(arg == "--core-path" or arg.startswith("--core-path=") for arg in arguments):
            container_args.append("--core-path=/usr/src/homeassistant")
    else:
        # Keep the upstream action's default discovery locations: a root
        # manifest for a standalone integration or custom_components/<domain>.
        if (workspace / "manifest.json").is_file():
            _copy_tree(workspace, workspace_context)
        elif (workspace / "custom_components").is_dir():
            custom_components = (workspace / "custom_components").resolve(strict=True)
            try:
                custom_components.relative_to(workspace)
            except ValueError as err:
                raise ContextError(
                    "Refusing normal-discovery custom_components root outside GITHUB_WORKSPACE"
                ) from err
            _copy_tree(custom_components, workspace_context / "custom_components")
        container_args = rewritten

    (arguments_context / "argv.json").write_text(
        json.dumps(container_args, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: prepare_hassfest_context.py GITHUB_WORKSPACE OUTPUT [HASSFEST_ARGS...]", file=sys.stderr)
        return 2
    try:
        prepare_context(argv[1], argv[2], argv[3:])
    except (ContextError, OSError) as err:
        print(f"Hassfest context preparation failed: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
