#!/bin/bash
#SBATCH --job-name=sandoq-client-setup
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_eval/sandoq_client_setup_%j.log

set -euo pipefail

project_dir=/storage/home/tianhaowu/prime-rl
target=/checkpoint/ram/tianhaowu/deepswe_eval/sandoq-client-site
mkdir -p "$target"
cd "$project_dir"

source deps/sandoq-provider/extensions/sandoq/vault_env.sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

uv pip install \
    --target "$target" \
    --exclude-newer-package sandoq-client=2026-08-14T00:00:00Z \
    -r deps/sandoq-provider/extensions/sandoq/requirements.txt

PYTHONPATH="$target" uv run --no-sync python - <<'PY'
import importlib.metadata
import sandoq_client

print("sandoq_client", sandoq_client.__file__)
print("version", importlib.metadata.version("sandoq-client"))
PY
