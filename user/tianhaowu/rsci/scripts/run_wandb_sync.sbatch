#!/bin/bash

#SBATCH --job-name=rsci-wandb-sync
#SBATCH --qos=cpu_lowest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=7-00:00:00
#SBATCH --output=/checkpoint/ram-h100-2/tianhaowu/rsci/wandb-sync/slurm-%j.log
#SBATCH --error=/checkpoint/ram-h100-2/tianhaowu/rsci/wandb-sync/slurm-%j.log

set -e

PROJECT_DIR=/storage/home/tianhaowu/prime-rl
cd "$PROJECT_DIR"
source .venv/bin/activate

export WANDB_IGNORE_GLOBS='*'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

uv run --no-sync user/tianhaowu/rsci/wandb_sync.py \
  --root /checkpoint/ram-h100-2/tianhaowu/rsci \
  --status /checkpoint/ram-h100-2/tianhaowu/rsci/wandb-sync/status.json \
  --entity ram \
  --project rsci \
  --watch-job 9821398 \
  --watch-job 9821400 \
  --run-id-override bupusy2o=bupusy2n
