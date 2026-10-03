#!/bin/bash
#SBATCH --job-name=toolathlon-k26-verified
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=48:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/home/tianhaowu/log/slurm-%j.out
#SBATCH --error=/home/tianhaowu/log/slurm-%j.err

set -euo pipefail

project_dir="${TOOLATHLON_PROJECT_DIR:-/storage/home/tianhaowu/prime-rl}"
runner_path="${TOOLATHLON_RUNNER_PATH:-$project_dir/user/tianhaowu/toolathlon_vmvm/legacy_eval.py}"
config_path="${TOOLATHLON_CONFIG:-$project_dir/user/tianhaowu/toolathlon_vmvm/kimi_k26_verified_v2.toml}"
output_dir="${TOOLATHLON_OUTPUT_DIR:-/checkpoint/ram/tianhaowu/toolathlon_vmvm/kimi_k26_verified_v2}"

cd "$project_dir"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PYTHONPATH="$project_dir/environments/vmvm_tb_v2${PYTHONPATH:+:$PYTHONPATH}"
export VACLI_LEASE_RETRIES=20
export VACLI_MAX_CONCURRENT_LEASES=1
export VACLI_MAX_PULL_RETRIES=20
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=3600

srun --kill-on-bad-exit=1 uv run --no-sync python \
  "$runner_path" \
  "$config_path" --output-dir "$output_dir"
