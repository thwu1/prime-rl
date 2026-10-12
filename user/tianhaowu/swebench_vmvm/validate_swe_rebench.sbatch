#!/bin/bash
#SBATCH --job-name=swe-rebench-oracle
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --output=/checkpoint/ram/tianhaowu/swebench_vmvm/logs/swe_rebench_oracle_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/swebench_vmvm/logs/swe_rebench_oracle_%j.log

set -euo pipefail

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
dataset_dir=${DATASET_DIR:-/checkpoint/ram/tianhaowu/swebench_vmvm/swe_rebench_07_2026_harbor/swe-rebench-07-2026}
num_tasks=${NUM_TASKS:-1}
taskset_id=${TASKSET_ID:-swe-rebench-harbor}
tasks=${TASKS:-}
vmvm_lease_ttl=${VMVM_LEASE_TTL:-60s}

mkdir -p /checkpoint/ram/tianhaowu/swebench_vmvm/logs
cd "$project_dir"

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export VACLI_LEASE_RETRIES=20
export VACLI_MAX_CONCURRENT_LEASES=${VACLI_MAX_CONCURRENT_LEASES:-4}
export VACLI_MAX_PULL_RETRIES=20
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=3600
export PYTHONPATH="$project_dir/user/tianhaowu/swebench_vmvm:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers${PYTHONPATH:+:$PYTHONPATH}"

args=(
    "$taskset_id"
    --taskset.dataset-dir "$dataset_dir"
    --runtime.type vmvm
    --runtime.session-timeout 7200
    --runtime.tenant-id async_2347641
    --runtime.lease-ttl "$vmvm_lease_ttl"
    --runtime.max-session-buffer-size 67108864
    --num-tasks "$num_tasks"
    --max-concurrent 1
    --validate-timeout 6000
    --rich false
)
if [ -n "$tasks" ]; then
    args+=(--taskset.tasks "$tasks")
fi

uv run --no-sync validate "${args[@]}"
