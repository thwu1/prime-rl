#!/usr/bin/env bash
#SBATCH --job-name=rsci-known-cost-kernel-v2
#SBATCH --qos=h100_lowest
#SBATCH --account=ram
#SBATCH --partition=h100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --requeue

set -euo pipefail

PROBE_ROOT=${1:?usage: run_known_cost_tag_kernel.sbatch PROBE_ROOT}
PROBE_ROOT=$(realpath "$PROBE_ROOT")
SOURCE_BOOTSTRAP="$PROBE_ROOT/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh"
if [[ ! -f "$SOURCE_BOOTSTRAP" ]]; then
  echo "pinned source bootstrap does not exist: $SOURCE_BOOTSTRAP" >&2
  exit 1
fi

source "$SOURCE_BOOTSTRAP" "$PROBE_ROOT"
cd "$RSCI_SOURCE_SNAPSHOT"
export HF_HUB_OFFLINE=1
export PYTHONDONTWRITEBYTECODE=1
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

exec uv run --no-sync user/tianhaowu/rsci/probe_known_cost_tag_kernel.py run \
  --probe-dir "$PROBE_ROOT/probe" \
  --output "$PROBE_ROOT/kernel.json" \
  --step-size 0.001 \
  --batch-size 8 \
  --max-self-linearity-relative-error 0.25 \
  --ordering-margin 0.02 \
  --minimum-ordering-pairs-per-source 5 \
  --max-median-off-diagonal 0.5
