#!/bin/bash
#SBATCH --job-name=toolathlon-nemo-v3
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=12:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --no-requeue
#SBATCH --output=/home/tianhaowu/log/slurm-%j.out
#SBATCH --error=/home/tianhaowu/log/slurm-%j.err

set -euo pipefail

project_dir=/storage/home/tianhaowu/prime-rl
config_path="${TOOLATHLON_CONFIG:-$project_dir/user/tianhaowu/toolathlon_vmvm/nemotron_super_verified_internal_v3.toml}"
output_dir="${TOOLATHLON_OUTPUT_DIR:-/checkpoint/ram/tianhaowu/toolathlon_vmvm/nemotron_super_verified_internal_v3}"
inference_job_id="${NEMOTRON_INFERENCE_JOB_ID:?Set NEMOTRON_INFERENCE_JOB_ID}"
evaluation_succeeded=0

cleanup() {
  local status=$?
  if (( evaluation_succeeded == 1 )) || [[ "${TOOLATHLON_KEEP_INFERENCE_ON_FAILURE:-1}" != "1" ]]; then
    scancel "$inference_job_id" 2>/dev/null || true
  else
    echo "Preserving inference job $inference_job_id after evaluator failure" >&2
  fi
  return "$status"
}
trap cleanup EXIT

cd "$project_dir"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PYTHONPATH="$project_dir/user/tianhaowu/toolathlon_vmvm:$project_dir/environments/vmvm_tb_v2${PYTHONPATH:+:$PYTHONPATH}"
export VACLI_LEASE_RETRIES=20
export VACLI_MAX_CONCURRENT_LEASES="${TOOLATHLON_LEASE_START_CONCURRENCY:-48}"
export VACLI_MAX_PULL_RETRIES=20
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=1800

node_list="$(squeue -h -j "$inference_job_id" -o %N)"
if [[ -z "$node_list" || "$node_list" == "(null)" ]]; then
  echo "Inference job $inference_job_id is not running" >&2
  exit 1
fi
router_node="$(scontrol show hostnames "$node_list" | head -n 1)"
export NEMOTRON_TOOLATHLON_BASE_URL="http://$router_node:8000"

deadline=$((SECONDS + 7200))
mapfile -t inference_nodes < <(scontrol show hostnames "$node_list")
while true; do
  all_workers_ready=1
  for inference_node in "${inference_nodes[@]}"; do
    if ! curl --noproxy '*' --fail --silent --max-time 10 \
      "http://$inference_node:8100/v1/models" >/dev/null; then
      all_workers_ready=0
      break
    fi
  done
  if (( all_workers_ready == 1 )) && curl --noproxy '*' --fail --silent --max-time 10 \
    "$NEMOTRON_TOOLATHLON_BASE_URL/v1/models" >/dev/null; then
    break
  fi
  if ! squeue -h -j "$inference_job_id" | rg -q .; then
    echo "Inference job $inference_job_id stopped before becoming ready" >&2
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "Inference endpoint did not become ready within 7200 seconds" >&2
    exit 1
  fi
  sleep 15
done

srun --kill-on-bad-exit=1 uv run --no-sync python \
  user/tianhaowu/toolathlon_vmvm/run_eval.py \
  "$config_path" --output-dir "$output_dir"
evaluation_succeeded=1
