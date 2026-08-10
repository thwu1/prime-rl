#!/usr/bin/env bash
#SBATCH --job-name=rsci-data-finalize-op10-45-186k
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=/checkpoint/ram-h100-2/tianhaowu/prime-rl-smoke/rsci_data_finalize_op10_45_186k_%j.log

set -euo pipefail

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

REPO_ROOT=/storage/home/tianhaowu/prime-rl
OUTPUT_DIR=${1:-/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-186k}

cd "$REPO_ROOT"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
exec uv run --no-sync python user/tianhaowu/rsci/prepare_rl_op10_40_dataset_186k.py \
  finalize \
  --output-dir "$OUTPUT_DIR"
