#!/bin/bash
#SBATCH --job-name=swe-rebench-harbor
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=/checkpoint/ram/tianhaowu/swebench_vmvm/logs/swe_rebench_harbor_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/swebench_vmvm/logs/swe_rebench_harbor_%j.log

set -euo pipefail

dataset=${DATASET:-ibragim-badertdinov/swe-rebench-07-2026@2026-07}
output_dir=${OUTPUT_DIR:-/checkpoint/ram/tianhaowu/swebench_vmvm/swe_rebench_07_2026_harbor}

mkdir -p /checkpoint/ram/tianhaowu/swebench_vmvm/logs "$output_dir"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1

uv tool run --offline --from harbor==0.14.0 harbor download \
    "$dataset" --export -o "$output_dir"
