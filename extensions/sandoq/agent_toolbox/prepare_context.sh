#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <new-build-context>" >&2
  exit 2
fi

output=$(realpath -m "$1")
if [ "$output" = / ] || [ -e "$output" ]; then
  echo "output must be a new, non-root path: $output" >&2
  exit 2
fi

fbsource=${FBSOURCE_ROOT:-$HOME/fbsource}
case "$fbsource" in
  /*) ;;
  *) echo "FBSOURCE_ROOT must be absolute" >&2; exit 2 ;;
esac

scratch=$(mktemp -d "${TMPDIR:-/tmp}/agent-toolbox-build.XXXXXX")
cleanup() {
  rm -rf -- "$scratch"
}
trap cleanup EXIT

mkdir -p "$output/rootfs/opt/prime-agents" "$scratch/rpm" "$scratch/muse"
cp "$(dirname "$0")/Containerfile" "$output/Containerfile"

targets=(
  fbcode//3pai_tooling/opencode:opencode-binary
  fbcode//3pai_tooling/pi:pi-binary
  fbsource//third-party/pi-mono:pi-assets
)
build_output=$(cd "$fbsource" && buck2 build "${targets[@]}" --show-full-output)

target_path() {
  local target=$1
  local path
  path=$(awk -v target="$target" '$1 == target { print $2 }' <<<"$build_output")
  if [ -z "$path" ] || [ ! -e "$path" ]; then
    echo "Buck did not materialize $target" >&2
    exit 1
  fi
  printf '%s\n' "$path"
}

opencode=$(target_path "${targets[0]}")
pi=$(target_path "${targets[1]}")
pi_assets=$(target_path "${targets[2]}")

install -D -m 0755 "$opencode" "$output/rootfs/opt/prime-agents/opencode/opencode"
install -D -m 0755 "$pi" "$output/rootfs/opt/prime-agents/pi/pi"
cp -R "$pi_assets"/. "$output/rootfs/opt/prime-agents/pi/"

# Muse's source cell is not present in every fbsource sparse profile. Obtain
# the canonical signed build artifact instead of copying an installed binary.
yumdownloader --destdir="$scratch/rpm" fb-muse-code
muse_rpm=$(find "$scratch/rpm" -maxdepth 1 -type f -name 'fb-muse-code*.x86_64.rpm' -print -quit)
if [ -z "$muse_rpm" ]; then
  echo "yumdownloader did not produce an x86-64 fb-muse-code RPM" >&2
  exit 1
fi
rpm -K "$muse_rpm"
(cd "$scratch/muse" && rpm2cpio "$muse_rpm" | cpio -idm --quiet ./usr/local/bin/muse_code/muse.real)
install -D -m 0755 "$scratch/muse/usr/local/bin/muse_code/muse.real" \
  "$output/rootfs/opt/prime-agents/muse/muse"

(
  cd "$output/rootfs"
  sha256sum \
    opt/prime-agents/opencode/opencode \
    opt/prime-agents/pi/pi \
    opt/prime-agents/muse/muse
) >"$output/agent-binaries.sha256"

printf 'Prepared clean build context: %s\n' "$output"
cat "$output/agent-binaries.sha256"
