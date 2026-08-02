#!/bin/bash

#SBATCH --job-name=rsci-reweight-ablation
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=2-00:00:00
#SBATCH --requeue
#SBATCH --output=/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-reweight-ablation/watcher-%j.log
#SBATCH --error=/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-reweight-ablation/watcher-%j.log

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl
export HF_HUB_OFFLINE=1
export PYTHONDONTWRITEBYTECODE=1
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
exec uv run --no-sync user/tianhaowu/rsci/frontier_reweight_ablation.py "$@"
