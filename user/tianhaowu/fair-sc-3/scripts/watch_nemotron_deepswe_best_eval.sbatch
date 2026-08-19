#!/bin/bash
#SBATCH --job-name=watch-nemotron-best-deepswe
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=48:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/sft_nemotron/best-deepswe-10723476-10723666/watcher_%j.log

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

uv run --no-sync python user/tianhaowu/fair-sc-3/scripts/watch_nemotron_deepswe_best_eval.py \
  --run pass-v38=10723666=/checkpoint/ram/tianhaowu/sft_nemotron/outputs/nemotron-super-120b-base-deepswe-pass-only-v38-192000-cp2-ep8-ulysses-fsdp-offload-expert-loop-fullmem-lr1e5-57steps-5epochs-seed3 \
  --run all-v37=10723476=/checkpoint/ram/tianhaowu/sft_nemotron/outputs/nemotron-super-120b-base-deepswe-all-kimi-v37-192000-cp2-ep8-ulysses-fsdp-offload-expert-loop-fullmem-lr1e5-111steps-5epochs-seed3 \
  --state-dir /checkpoint/ram/tianhaowu/sft_nemotron/best-deepswe-10723476-10723666 \
  --poll-seconds 60 \
  --launch
