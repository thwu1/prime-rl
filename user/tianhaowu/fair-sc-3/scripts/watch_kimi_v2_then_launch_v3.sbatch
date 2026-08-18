#!/usr/bin/env bash
#SBATCH --job-name=kimi-v3-gate
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=72:00:00
#SBATCH --requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/eval/kimi-k26-v3-think-r4/gate_%j.log

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl
mkdir -p /checkpoint/ram/tianhaowu/eval/kimi-k26-v3-think-r4

exec uv run --no-sync python -u user/tianhaowu/fair-sc-3/scripts/watch_kimi_v2_then_launch_v3.py \
  --threshold 512 \
  --poll-seconds 120
