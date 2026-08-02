#!/bin/bash
#SBATCH --job-name=rsci-infer-concurrency
#SBATCH --qos=h100_ram_high
#SBATCH --account=ram
#SBATCH --partition=h100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=64
#SBATCH --mem=256G
#SBATCH --time=02:00:00

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl
exec bash user/tianhaowu/rsci/scripts/run_inference_concurrency_benchmark.sh "$@"
