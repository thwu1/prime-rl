#!/bin/bash
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=128G
#SBATCH --time=7-00:00:00
#SBATCH --requeue

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl
CONFIG=${1:?usage: sbatch user/tianhaowu/rsci/scripts/run_frontier.sbatch <frontier-config.toml>}
export HF_HUB_OFFLINE=1
export PYTHONDONTWRITEBYTECODE=1
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
exec uv run --no-sync user/tianhaowu/rsci/frontier_loop.py "$CONFIG"
