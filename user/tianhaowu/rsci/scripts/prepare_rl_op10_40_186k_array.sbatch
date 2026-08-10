#!/usr/bin/env bash
#SBATCH --job-name=rsci-data-op10-45-186k
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --partition=cpu
#SBATCH --array=10-45
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=7-00:00:00
#SBATCH --output=/checkpoint/ram-h100-2/tianhaowu/prime-rl-smoke/rsci_data_op10_45_186k_%A_%a.log

set -euo pipefail

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

REPO_ROOT=/storage/home/tianhaowu/prime-rl
OUTPUT_DIR=${1:-/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-186k}
OPERATION=${SLURM_ARRAY_TASK_ID:?SLURM_ARRAY_TASK_ID must select an operation from 10 through 45}

if (( OPERATION < 10 || OPERATION > 45 )); then
  echo "SLURM_ARRAY_TASK_ID must be between 10 and 45, found $OPERATION" >&2
  exit 2
fi

cd "$REPO_ROOT"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
exec uv run --no-sync python user/tianhaowu/rsci/prepare_rl_op10_40_dataset_186k.py \
  generate-shard \
  --output-dir "$OUTPUT_DIR" \
  --operation "$OPERATION"
