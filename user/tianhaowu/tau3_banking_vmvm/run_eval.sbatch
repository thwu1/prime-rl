#!/bin/bash
#SBATCH --job-name=tau3-banking-vmvm
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --no-requeue
#SBATCH --output=/home/tianhaowu/log/slurm-%j.out
#SBATCH --error=/home/tianhaowu/log/slurm-%j.err

set -euo pipefail

project_dir=/storage/home/tianhaowu/prime-rl
config_path="${TAU3_CONFIG:-$project_dir/user/tianhaowu/tau3_banking_vmvm/nemotron_super_kimi.toml}"
output_dir="${TAU3_OUTPUT_DIR:-/checkpoint/ram/tianhaowu/tau3_banking_vmvm/nemotron_super_kimi_k26}"

cd "$project_dir"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$project_dir/environments/vmvm_tb_v2${PYTHONPATH:+:$PYTHONPATH}"
export VACLI_LEASE_RETRIES=20
export VACLI_MAX_CONCURRENT_LEASES="${TAU3_WORKERS:-16}"
export VACLI_MAX_PULL_RETRIES=20
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=3600

args=("$config_path" --output-dir "$output_dir" --workers "${TAU3_WORKERS:-16}")
if [[ -n "${TAU3_POLICY_JOB_ID:-}" ]]; then
  args+=(--policy-job-id "$TAU3_POLICY_JOB_ID")
fi
if [[ -n "${TAU3_LIMIT:-}" ]]; then
  args+=(--limit "$TAU3_LIMIT")
fi
if [[ -n "${TAU3_TASK_ID:-}" ]]; then
  args+=(--task-id "$TAU3_TASK_ID")
fi
if [[ -n "${TAU3_TRIAL:-}" ]]; then
  args+=(--trial "$TAU3_TRIAL")
fi

srun --kill-on-bad-exit=1 uv run --no-sync python \
  user/tianhaowu/tau3_banking_vmvm/run_eval.py "${args[@]}"
