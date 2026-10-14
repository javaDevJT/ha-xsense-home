#!/usr/bin/env bash
set -Eeuo pipefail

CORE_REPOSITORY="https://github.com/home-assistant/core.git"
CORE_COMMIT="abe1fdd7cd6b4de1715c87b6fd87d92699514ef9"
HA_WHEEL_INDEX="https://wheels.home-assistant.io/musllinux-index/"

usage() {
  echo "Usage: bash .github/scripts/ha-validators.sh hassfest [hassfest arguments...]" >&2
  exit 2
}

[[ $# -ge 1 ]] || usage
[[ "$1" == "hassfest" ]] || usage
shift
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE must be set by GitHub Actions}"
: "${RUNNER_TEMP:?RUNNER_TEMP must be set by GitHub Actions}"

hassfest_runtime_tmp=""
core_source=""
entrypoint=""
hassfest_venv=""
cleanup_hassfest_temp() {
  local paths=()
  local path
  for path in "$hassfest_runtime_tmp" "$core_source" "$entrypoint" "$hassfest_venv"; do
    [[ -n "$path" ]] && paths+=("$path")
  done
  if ((${#paths[@]})); then
    rm -rf -- "${paths[@]}"
  fi
}
trap cleanup_hassfest_temp EXIT

hassfest_runtime_tmp="$(mktemp -d "$RUNNER_TEMP/hassfest-runtime.XXXXXX")"

if ! python3 -c 'import ctypes.util, sys; sys.exit(0 if ctypes.util.find_library("turbojpeg") else 1)'; then
  if ! command -v apt-get >/dev/null 2>&1 || ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "Hassfest requires libturbojpeg; apt-get and dpkg-deb are required to download and extract it" >&2
    exit 1
  fi

  # Keep apt's package lists and download cache under RUNNER_TEMP so refreshing
  # signed package metadata and extracting the runtime library never needs sudo
  # or writes into the runner image's package database.
  apt_lists="$hassfest_runtime_tmp/apt-lists"
  apt_cache="$hassfest_runtime_tmp/apt-cache"
  mkdir -p "$apt_lists/partial" "$apt_cache/archives/partial"
  apt_options=(-o "Dir::State::lists=$apt_lists" -o "Dir::Cache=$apt_cache")
  apt-get "${apt_options[@]}" update -qq

  if apt-cache "${apt_options[@]}" show libturbojpeg0t64 >/dev/null 2>&1; then
    turbojpeg_package=libturbojpeg0t64
  elif apt-cache "${apt_options[@]}" show libturbojpeg0 >/dev/null 2>&1; then
    turbojpeg_package=libturbojpeg0
  else
    echo "No supported apt package provides libturbojpeg" >&2
    exit 1
  fi

  (cd "$hassfest_runtime_tmp" && apt-get "${apt_options[@]}" download "$turbojpeg_package")
  turbojpeg_deb="$(find "$hassfest_runtime_tmp" -maxdepth 1 -type f -name "${turbojpeg_package}_*.deb" -print -quit)"
  [[ -n "$turbojpeg_deb" ]] || {
    echo "apt-get download did not produce a $turbojpeg_package package archive" >&2
    exit 1
  }
  turbojpeg_root="$hassfest_runtime_tmp/turbojpeg-root"
  mkdir -p "$turbojpeg_root"
  dpkg-deb --extract "$turbojpeg_deb" "$turbojpeg_root"
  turbojpeg_library="$(find "$turbojpeg_root" -name 'libturbojpeg.so.0' -print -quit)"
  [[ -f "$turbojpeg_library" ]] || {
    echo "Extracted $turbojpeg_package package does not contain libturbojpeg.so.0" >&2
    exit 1
  }
  turbojpeg_library_dir="$(dirname "$turbojpeg_library")"
  ln -sf "$turbojpeg_library" "$turbojpeg_library_dir/libturbojpeg.so"
  export LD_LIBRARY_PATH="$turbojpeg_library_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export LIBRARY_PATH="$turbojpeg_library_dir${LIBRARY_PATH:+:$LIBRARY_PATH}"
fi
python3 -c 'import ctypes.util, sys; sys.exit(0 if ctypes.util.find_library("turbojpeg") else 1)' || {
  echo "Unable to discover libturbojpeg after preparing the Hassfest OS dependency" >&2
  exit 1
}

core_source="$(mktemp -d "$RUNNER_TEMP/home-assistant-core.XXXXXX")"
entrypoint="$(mktemp "$RUNNER_TEMP/hassfest-entrypoint.XXXXXX")"
hassfest_venv="$(mktemp -d "$RUNNER_TEMP/hassfest-venv.XXXXXX")"

git init -q "$core_source"
git -C "$core_source" remote add origin "$CORE_REPOSITORY"
git -C "$core_source" sparse-checkout init --cone
git -C "$core_source" sparse-checkout set homeassistant script
git -C "$core_source" fetch --quiet --filter=blob:none --depth=1 origin "$CORE_COMMIT"
git -C "$core_source" checkout --quiet --detach FETCH_HEAD
actual_commit="$(git -C "$core_source" rev-parse HEAD)"
[[ "$actual_commit" == "$CORE_COMMIT" ]] || {
  echo "Home Assistant Core source mismatch: expected $CORE_COMMIT, got $actual_commit" >&2
  exit 1
}

pinned_version() {
  local package="$1"
  local file="$2"
  awk -F '==' -v package="$package" '$1 == package { print $2; exit }' "$file"
}

uv_version="$(pinned_version uv "$core_source/requirements.txt")"
pipdeptree_version="$(pinned_version pipdeptree "$core_source/requirements_test.txt")"
tqdm_version="$(pinned_version tqdm "$core_source/requirements_test.txt")"
ruff_version="$(pinned_version ruff "$core_source/requirements_test_pre_commit.txt")"
for version in "$uv_version" "$pipdeptree_version" "$tqdm_version" "$ruff_version"; do
  [[ -n "$version" ]] || {
    echo "Could not resolve a pinned Hassfest dependency from Core commit $CORE_COMMIT" >&2
    exit 1
  }
done

python3 -m venv "$hassfest_venv"
venv_python="$hassfest_venv/bin/python"
venv_uv="$hassfest_venv/bin/uv"
"$venv_python" -m pip install --disable-pip-version-check "uv==$uv_version"
unset UV_SYSTEM_PYTHON
export VIRTUAL_ENV="$hassfest_venv"
export PATH="$hassfest_venv/bin:$PATH"
UV_EXTRA_INDEX_URL="" "$venv_uv" pip install --python "$venv_python" --no-build \
  "pipdeptree==$pipdeptree_version" \
  "tqdm==$tqdm_version" \
  "ruff==$ruff_version"
UV_EXTRA_INDEX_URL="$HA_WHEEL_INDEX" "$venv_uv" pip install --python "$venv_python" --no-build \
  -c "$core_source/homeassistant/package_constraints.txt" \
  -r "$core_source/requirements.txt"

# Keep the Core Docker entrypoint's manifest discovery and invocation byte-for-byte;
# only point its hard-coded image path at this pinned source checkout.
python3 - "$core_source/script/hassfest/docker/entrypoint.sh" "$entrypoint" "$core_source" <<'PY'
from pathlib import Path
import sys

source_path, destination_path, core_path = map(Path, sys.argv[1:])
source = source_path.read_text(encoding="utf-8")
old = "cd /usr/src/homeassistant || exit 1"
if source.count(old) != 1:
    raise SystemExit("Pinned Core Hassfest entrypoint no longer has the expected Core path")
new = f'cd "{core_path}" || exit 1'
Path(destination_path).write_text(source.replace(old, new, 1), encoding="utf-8")
PY

cd "$GITHUB_WORKSPACE"
has_explicit_core_path=false
has_explicit_integration_path=false
for arg in "$@"; do
  case "$arg" in
    --core-path=*) has_explicit_core_path=true ;;
    --integration-path|--integration-path=*) has_explicit_integration_path=true ;;
  esac
done
if [[ "$has_explicit_integration_path" == true && "$has_explicit_core_path" == false ]]; then
  set -- "--core-path=$core_source" "$@"
fi
/bin/sh "$entrypoint" "$@"
