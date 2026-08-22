#!/bin/bash
#SBATCH --job-name=toolathlon-k26-v4
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=06:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --no-requeue
#SBATCH --output=/home/tianhaowu/log/slurm-%j.out
#SBATCH --error=/home/tianhaowu/log/slurm-%j.err

set -euo pipefail

project_dir=/storage/home/tianhaowu/prime-rl
config_path="${TOOLATHLON_CONFIG:-$project_dir/user/tianhaowu/toolathlon_vmvm/kimi_k26_verified_internal_v4.toml}"
output_dir="${TOOLATHLON_OUTPUT_DIR:-/checkpoint/ram/tianhaowu/toolathlon_vmvm/kimi_k26_verified_internal_v4}"
runner_path="${TOOLATHLON_RUNNER_PATH:-$project_dir/user/tianhaowu/toolathlon_vmvm/run_eval.py}"

cd "$project_dir"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PYTHONPATH="$project_dir/user/tianhaowu/toolathlon_vmvm:$project_dir/environments/vmvm_tb_v2${PYTHONPATH:+:$PYTHONPATH}"
export VACLI_LEASE_RETRIES=20
# This limits simultaneous lease bring-up, not the 96 active task workers.
export VACLI_MAX_CONCURRENT_LEASES="${TOOLATHLON_LEASE_START_CONCURRENCY:-48}"
export VACLI_MAX_PULL_RETRIES=20
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=1800

srun --kill-on-bad-exit=1 uv run --no-sync python \
  "$runner_path" \
  "$config_path" --output-dir "$output_dir" "$@"
