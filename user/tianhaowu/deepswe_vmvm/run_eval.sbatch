#!/bin/bash
#SBATCH --job-name=deepswe-vmvm-eval
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=1-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=128G
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_vmvm/logs/eval_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/deepswe_vmvm/logs/eval_%j.log

set -euo pipefail

: "${INFERENCE_BASE_URL:?Set INFERENCE_BASE_URL to the prime-rl inference /v1 endpoint}"

project_dir=/storage/home/tianhaowu/prime-rl
eval_config=${EVAL_CONFIG:-user/tianhaowu/deepswe_vmvm/eval.toml}
eval_overlay=${EVAL_OVERLAY:-}
num_tasks=${NUM_TASKS:-}
max_concurrent=${MAX_CONCURRENT:-}
output_dir=${OUTPUT_DIR:-/checkpoint/ram/tianhaowu/deepswe_vmvm/evals/run_${SLURM_JOB_ID}}

mkdir -p "$output_dir"
cd "$project_dir"

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export OPENAI_API_KEY=EMPTY
export VACLI_LEASE_RETRIES=20
export VACLI_MAX_CONCURRENT_LEASES=16
export VACLI_MAX_PULL_RETRIES=20
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=3600
export PYTHONPATH="$project_dir/environments/vmvm_tb_v2${PYTHONPATH:+:$PYTHONPATH}"

eval_args=(@ "$eval_config")
[ -n "$eval_overlay" ] && eval_args+=(@ "$eval_overlay")
[ -n "$num_tasks" ] && eval_args+=(--num-tasks "$num_tasks")
[ -n "$max_concurrent" ] && eval_args+=(--max-concurrent "$max_concurrent")

uv run --no-sync eval "${eval_args[@]}" \
    --client.base-url "$INFERENCE_BASE_URL" \
    --output-dir "$output_dir"
