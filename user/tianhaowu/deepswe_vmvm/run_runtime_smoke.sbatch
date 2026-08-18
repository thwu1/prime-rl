#!/bin/bash
#SBATCH --job-name=deepswe-vmvm-smoke
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_vmvm/logs/runtime_smoke_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/deepswe_vmvm/logs/runtime_smoke_%j.log

set -euo pipefail

project_dir=/storage/home/tianhaowu/prime-rl
mkdir -p /checkpoint/ram/tianhaowu/deepswe_vmvm/logs
cd "$project_dir"

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$project_dir/environments/vmvm_tb_v2${PYTHONPATH:+:$PYTHONPATH}"

uv run --no-sync user/tianhaowu/deepswe_vmvm/smoke_runtime.py
