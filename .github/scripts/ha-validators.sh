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

  # Apt's system docker-clean hook writes under /var/cache/apt, which is not
  # writable by this runner. Load a private configuration before apt reads its
  # host fragments, while retaining the host's signed source and keyring files.
  apt_state="$hassfest_runtime_tmp/apt-state"
  apt_config_parts="$hassfest_runtime_tmp/apt-config-parts"
  apt_config="$hassfest_runtime_tmp/apt.conf"
  apt_lists="$apt_state/lists"
  apt_extended_states="$apt_state/extended_states"
  apt_archives="$hassfest_runtime_tmp/apt-archives"
  apt_pkg_cache="$hassfest_runtime_tmp/apt-pkgcache.bin"
  apt_srcpkg_cache="$hassfest_runtime_tmp/apt-srcpkgcache.bin"
  apt_logs="$hassfest_runtime_tmp/apt-logs"
  mkdir -p "$apt_config_parts" "$apt_lists/partial" "$apt_archives/partial" "$apt_logs"
  python3 - "$apt_config" "$apt_config_parts" "$apt_lists" "$apt_extended_states" \
    "$apt_archives" "$apt_pkg_cache" "$apt_srcpkg_cache" "$apt_logs" <<'PY'
import json
import os
from pathlib import Path
import sys

destination, config_parts, lists, extended_states, archives, pkg_cache, srcpkg_cache, logs = sys.argv[1:]
settings = [
    ("Dir::Etc::Main", "/dev/null"),
    ("Dir::Etc::Parts", config_parts),
    ("Dir::State::status", "/var/lib/dpkg/status"),
    ("Dir::State::lists", lists + os.sep),
    ("Dir::State::extended_states", extended_states),
    ("Dir::Cache::archives", archives + os.sep),
    ("Dir::Cache::pkgcache", pkg_cache),
    ("Dir::Cache::srcpkgcache", srcpkg_cache),
    ("Dir::Log", logs + os.sep),
    ("Debug::NoLocking", "1"),
]
Path(destination).write_text(
    "".join(f"{name} {json.dumps(value)};\n" for name, value in settings),
    encoding="utf-8",
)
PY
  apt_options=(-o "Dir::State::status=/var/lib/dpkg/status" \
    -o "Dir::State::lists=$apt_lists/" \
    -o "Dir::State::extended_states=$apt_extended_states" \
    -o "Dir::Cache::archives=$apt_archives/" \
    -o "Dir::Cache::pkgcache=$apt_pkg_cache" \
    -o "Dir::Cache::srcpkgcache=$apt_srcpkg_cache" \
    -o "Dir::Log=$apt_logs/" \
    -o "Debug::NoLocking=1")
  APT_CONFIG="$apt_config" apt-get "${apt_options[@]}" update -qq

  turbojpeg_package=""
  turbojpeg_version=""
  for candidate_package in libturbojpeg0t64 libturbojpeg0 libturbojpeg; do
    printf 'Signed apt policy for %s:\n' "$candidate_package"
    turbojpeg_policy="$(APT_CONFIG="$apt_config" apt-cache "${apt_options[@]}" policy "$candidate_package")"
    printf '%s\n' "$turbojpeg_policy"
    candidate_version="$(awk '/^[[:space:]]*Candidate:/ { print $2; exit }' <<<"$turbojpeg_policy")"
    if [[ -n "$candidate_version" && "$candidate_version" != "(none)" ]]; then
      turbojpeg_package="$candidate_package"
      turbojpeg_version="$candidate_version"
      break
    fi
  done
  if [[ -z "$turbojpeg_package" ]]; then
    echo "Signed apt indexes have no candidate for libturbojpeg0t64, libturbojpeg0, or libturbojpeg" >&2
    exit 1
  fi
  printf 'Selected libturbojpeg package: %s Candidate: %s\n' "$turbojpeg_package" "$turbojpeg_version"

  (cd "$hassfest_runtime_tmp" && APT_CONFIG="$apt_config" apt-get "${apt_options[@]}" download "$turbojpeg_package")
  turbojpeg_deb="$(find "$hassfest_runtime_tmp" -maxdepth 1 -type f -name "${turbojpeg_package}_*.deb" -print -quit)"
  [[ -n "$turbojpeg_deb" ]] || {
    echo "apt-get download did not produce a $turbojpeg_package package archive" >&2
    exit 1
  }
  downloaded_turbojpeg_version="$(dpkg-deb --field "$turbojpeg_deb" Version)"
  [[ "$downloaded_turbojpeg_version" == "$turbojpeg_version" ]] || {
    echo "Downloaded $turbojpeg_package version $downloaded_turbojpeg_version does not match apt candidate $turbojpeg_version" >&2
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
  python3 - "$turbojpeg_library" <<'PY'
import ctypes
import sys

ctypes.CDLL(sys.argv[1])
PY
fi

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
# Validate the pinned native dependency, including PyTurboJPEG 1.8.3's
# LD_LIBRARY_PATH fallback when the library was extracted into RUNNER_TEMP.
"$venv_python" -c 'from turbojpeg import TurboJPEG; TurboJPEG()'

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
