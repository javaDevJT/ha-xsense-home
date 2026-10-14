#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: bash .github/scripts/ha-validators.sh hassfest [hassfest arguments...]" >&2
  exit 2
}

[[ $# -ge 1 && "$1" == "hassfest" ]] || usage
shift
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE must be set by GitHub Actions}"
: "${RUNNER_TEMP:?RUNNER_TEMP must be set by GitHub Actions}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for required_file in "$script_dir/hassfest-remote-validator.Dockerfile" "$script_dir/prepare_hassfest_context.py"; do
  [[ -f "$required_file" ]] || {
    echo "Missing trusted Hassfest adapter file: $required_file" >&2
    exit 1
  }
done
command -v docker >/dev/null 2>&1 || {
  echo "Hassfest requires the docker CLI with the remote Buildx builder configured" >&2
  exit 1
}

adapter_tmp="$(mktemp -d "$RUNNER_TEMP/hassfest-vendor.XXXXXX")"
cleanup_hassfest_vendor() {
  rm -rf -- "$adapter_tmp"
}
trap cleanup_hassfest_vendor EXIT

mkdir -p "$adapter_tmp/context"
cp "$script_dir/hassfest-remote-validator.Dockerfile" "$adapter_tmp/context/Dockerfile"
cat > "$adapter_tmp/context/.dockerignore" <<'EOF'
*
!Dockerfile
!.dockerignore
EOF

python3 "$script_dir/prepare_hassfest_context.py" \
  "$GITHUB_WORKSPACE" "$adapter_tmp" "$@"

docker buildx build \
  --file "$adapter_tmp/context/Dockerfile" \
  --target result \
  --platform linux/amd64 \
  --no-cache \
  --pull \
  --progress plain \
  --build-context "hassfest-workspace=$adapter_tmp/workspace" \
  --build-context "hassfest-arguments=$adapter_tmp/arguments" \
  --output "type=local,dest=$adapter_tmp/result" \
  "$adapter_tmp/context"

[[ -f "$adapter_tmp/result/validator.log" && -f "$adapter_tmp/result/exit-code" ]] || {
  echo "BuildKit completed without the Hassfest result files" >&2
  exit 1
}
cat "$adapter_tmp/result/validator.log"
status="$(cat "$adapter_tmp/result/exit-code")"
[[ "$status" =~ ^[0-9]{1,3}$ ]] && ((status <= 255)) || {
  echo "BuildKit returned an invalid Hassfest exit code: $status" >&2
  exit 1
}
exit "$status"
