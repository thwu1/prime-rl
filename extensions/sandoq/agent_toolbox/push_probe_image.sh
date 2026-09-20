#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <oci-archive.zst> <run-dir> <destination-image>" >&2
  exit 2
fi

archive=$1
run_dir=$2
destination=$3
registry=${destination%%/*}
expected_registry=588845226011.dkr.ecr.us-east-2.amazonaws.com
if [ "$registry" != "$expected_registry" ]; then
  echo "destination must use the development ECR registry: $expected_registry" >&2
  exit 2
fi
storage_dir=$(mktemp -d /var/slurm-tmp/agent-toolbox.XXXXXX)

mkdir -p "$run_dir" "$storage_dir"/{storage,run,run-xdg,docker-config}
chmod 700 "$storage_dir" "$storage_dir/run-xdg"
export XDG_RUNTIME_DIR="$storage_dir/run-xdg"
export CONTAINERS_CONF="$storage_dir/containers.conf"
export DOCKER_CONFIG="$storage_dir/docker-config"
printf '[containers]\npidns = "host"\ndefault_sysctls = []\nkeyring = false\n' >"$CONTAINERS_CONF"
printf '{}\n' >"$DOCKER_CONFIG/config.json"

podman_storage=(
  /usr/bin/podman
  --storage-driver vfs
  --root "$storage_dir/storage"
  --runroot "$storage_dir/run"
)

cleanup() {
  "${podman_storage[@]}" system reset --force >/dev/null 2>&1 || true
  chmod -R u+rwX "$storage_dir" >/dev/null 2>&1 || true
  rm -rf -- "$storage_dir"
}
trap cleanup EXIT

{
  echo "job_id=${SLURM_JOB_ID:-none}"
  echo "host=$(hostname)"
  echo "architecture=$(uname -m)"
  echo "archive=$archive"
  echo "archive_sha256=$(sha256sum "$archive" | awk '{print $1}')"
  echo "destination=$destination"
} | tee "$run_dir/build-metadata.txt"

zstd -dc -- "$archive" | "${podman_storage[@]}" load
"${podman_storage[@]}" image inspect localhost/prime-agent-toolbox:probe \
  --format 'local_image={{.Id}} architecture={{.Architecture}} size={{.Size}}' \
  | tee -a "$run_dir/build-metadata.txt"

credential="/var/facebook/credentials/$USER/x509/$USER.pem"
if [ -f "$credential" ]; then
  export THRIFT_TLS_CL_CERT_PATH="$credential"
  export THRIFT_TLS_CL_KEY_PATH="$credential"
fi
eval "$(ucloud aws get-credentials --role SSOContainerRegistryReadWrite 588845226011)"
umask 077
aws ecr get-login-password --region us-east-2 >"$storage_dir/ecr-token"
"${podman_storage[@]}" login --username AWS --password-stdin "$registry" <"$storage_dir/ecr-token"

"${podman_storage[@]}" tag localhost/prime-agent-toolbox:probe "$destination"
"${podman_storage[@]}" push --digestfile "$run_dir/manifest.digest" "$destination"
echo "manifest_digest=$(cat "$run_dir/manifest.digest")" | tee -a "$run_dir/build-metadata.txt"
