#!/bin/bash
#SBATCH --job-name=gdpval-vmvm
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=128G
#SBATCH --no-requeue
#SBATCH --output=/home/tianhaowu/log/slurm-%j.out
#SBATCH --error=/home/tianhaowu/log/slurm-%j.err

set -euo pipefail

if [[ -n "${GDPVAL_RUNNER_DIR:-}" ]]; then
  runner_dir="$GDPVAL_RUNNER_DIR"
elif [[ -n "${SLURM_JOB_ID:-}" ]]; then
  submitted_script="$({ scontrol show job -o "$SLURM_JOB_ID"; } | sed -n 's/.* Command=\([^ ]*\).*/\1/p')"
  if [[ -z "$submitted_script" ]]; then
    echo "Could not resolve the submitted script path for Slurm job $SLURM_JOB_ID" >&2
    exit 1
  fi
  runner_dir="$(cd "$(dirname "$submitted_script")" && pwd)"
else
  runner_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
project_dir="${GDPVAL_PROJECT_DIR:-$(cd "$runner_dir/../../.." && pwd)}"
config_path="${GDPVAL_CONFIG:-$runner_dir/nemotron_super_kimi.toml}"
output_dir="${GDPVAL_OUTPUT_DIR:-/checkpoint/ram/tianhaowu/gdpval_vmvm/nemotron_super_kimi_final}"

mkdir -p /home/tianhaowu/log
cd "$project_dir"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PYTHONPATH="$runner_dir${PYTHONPATH:+:$PYTHONPATH}"
export VACLI_LEASE_RETRIES=20
export VACLI_MAX_CONCURRENT_LEASES="${GDPVAL_WORKERS:-16}"
export VACLI_MAX_PULL_RETRIES=20
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=3600

args=(
  "$config_path"
  --output-dir "$output_dir"
  --workers "${GDPVAL_WORKERS:-16}"
)
if [[ -n "${GDPVAL_POLICY_JOB_ID:-}" ]]; then
  args+=(--policy-job-id "$GDPVAL_POLICY_JOB_ID")
fi
if [[ -n "${GDPVAL_POLICY_BASE_URL:-}" ]]; then
  args+=(--policy-base-url "$GDPVAL_POLICY_BASE_URL")
fi
if [[ -n "${GDPVAL_JUDGE_BASE_URL:-}" ]]; then
  args+=(--judge-base-url "$GDPVAL_JUDGE_BASE_URL")
fi
if [[ -n "${GDPVAL_LIMIT:-}" ]]; then
  args+=(--limit "$GDPVAL_LIMIT")
fi
if [[ -n "${GDPVAL_TASK_ID:-}" ]]; then
  args+=(--task-id "$GDPVAL_TASK_ID")
fi
args+=("$@")

srun --export=ALL --kill-on-bad-exit=1 uv run --project "$runner_dir" --no-sync python \
  "$runner_dir/run_eval.py" "${args[@]}" --prepare-only

if [[ "${GDPVAL_SKIP_RUNTIME_PROBE:-0}" != "1" ]]; then
  preflight_file="${GDPVAL_PREFLIGHT_FILE:-/tmp/gdpval-preflight-${SLURM_JOB_ID}.json}"
  probe_args=("$config_path")
  if [[ -n "${GDPVAL_POLICY_JOB_ID:-}" ]]; then
    probe_args+=(--policy-job-id "$GDPVAL_POLICY_JOB_ID")
  fi
  if [[ -n "${GDPVAL_POLICY_BASE_URL:-}" ]]; then
    probe_args+=(--policy-base-url "$GDPVAL_POLICY_BASE_URL")
  fi
  if [[ -n "${GDPVAL_JUDGE_BASE_URL:-}" ]]; then
    probe_args+=(--judge-base-url "$GDPVAL_JUDGE_BASE_URL")
  fi
  if [[ -n "${GDPVAL_TASK_ID:-}" ]]; then
    probe_args+=(--asset-task-id "$GDPVAL_TASK_ID")
  fi
  # Preserve inherited proxy variables so the scoped direct-client probe matches the worker environment.
  srun --export=ALL --kill-on-bad-exit=1 uv run --project "$runner_dir" --no-sync python \
    "$runner_dir/probe_runtime.py" "${probe_args[@]}" --output "$preflight_file"
  args+=(--preflight-file "$preflight_file")
else
  judge_probe_args=("$config_path" --judge-only)
  if [[ -n "${GDPVAL_JUDGE_BASE_URL:-}" ]]; then
    judge_probe_args+=(--judge-base-url "$GDPVAL_JUDGE_BASE_URL")
  fi
  srun --export=ALL --kill-on-bad-exit=1 uv run --project "$runner_dir" --no-sync python \
    "$runner_dir/probe_runtime.py" "${judge_probe_args[@]}"
fi

srun --export=ALL --kill-on-bad-exit=1 uv run --project "$runner_dir" --no-sync python \
  "$runner_dir/run_eval.py" "${args[@]}"
