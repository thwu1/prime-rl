#!/bin/bash
#SBATCH --job-name=rsci-harmonic-sft-driver
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --output=/home/tianhaowu/log/slurm-%j.out
#SBATCH --error=/home/tianhaowu/log/slurm-%j.out

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

export HF_HUB_OFFLINE=1
export PYTHONDONTWRITEBYTECODE=1
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

exec uv run --no-sync user/tianhaowu/rsci/harmonic_sft_ablation.py "$@"
