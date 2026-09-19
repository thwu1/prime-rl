#!/bin/bash
#SBATCH --job-name=toolathlon-probe
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/toolathlon_vmvm/logs/probe_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/toolathlon_vmvm/logs/probe_%j.log

set -euo pipefail

project_dir=/storage/home/tianhaowu/prime-rl
mkdir -p /checkpoint/ram/tianhaowu/toolathlon_vmvm/logs
cd "$project_dir"

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export VACLI_LEASE_RETRIES=20
export VACLI_MAX_CONCURRENT_LEASES=1
export VACLI_MAX_PULL_RETRIES=20
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=1800
export PYTHONPATH="$project_dir/user/tianhaowu/toolathlon_vmvm:$project_dir/environments/vmvm_tb_v2${PYTHONPATH:+:$PYTHONPATH}"

uv run --no-sync user/tianhaowu/toolathlon_vmvm/probe_vmvm.py "$@"
