#!/bin/bash
#SBATCH --job-name=rsci-executable-filter-ablation
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=12:00:00
#SBATCH --output=/home/tianhaowu/log/slurm-%j.out
#SBATCH --error=/home/tianhaowu/log/slurm-%j.out

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

export HF_HUB_OFFLINE=1
export PYTHONDONTWRITEBYTECODE=1
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

exec uv run --no-sync user/tianhaowu/rsci/frontier_executable_filter_ablation.py "$@"
