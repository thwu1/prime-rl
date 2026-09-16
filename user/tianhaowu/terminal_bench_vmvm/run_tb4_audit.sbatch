#!/bin/bash
#SBATCH --job-name=tb4-audit
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/tb4_audit_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/tb4_audit_%j.log

set -euo pipefail

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
python_bin=${PYTHON_BIN_X86_64:-python3}
results_dir=${RESULTS_DIR:?Set RESULTS_DIR to the completed TB4 snapshot}
dataset_dir=${TB4_DATASET_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/tb4-prebuilt-v4.0.0/tasks}
task_file=${TB4_TASK_FILE:-}
min_rate=${TB4_MIN_SUPPORTED_PASS_RATE:-0.04}
max_rate=${TB4_MAX_SUPPORTED_PASS_RATE:-0.22}
max_sequence_tokens=${TB4_MAX_SEQUENCE_TOKENS:-262144}
results="$results_dir/results.jsonl"
checkpoint="$results_dir/checkpoint.json"
temporary="$checkpoint.tmp.$SLURM_JOB_ID"

if [[ ! -s "$results" ]]; then
    printf 'Missing or empty TB4 results: %s\n' "$results" >&2
    exit 2
fi
if [[ -e "$results_dir/.writer.lock" ]] && flock -n "$results_dir/.writer.lock" true 2>/dev/null; then
    :
elif [[ -e "$results_dir/.writer.lock" ]]; then
    printf 'TB4 evaluator still owns %s\n' "$results_dir" >&2
    exit 2
fi

cleanup() {
    rm -f -- "$temporary"
}
trap cleanup EXIT

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src${PYTHONPATH:+:$PYTHONPATH}"

args=(
    "$workflow_dir/audit_tb4_results.py"
    "$results"
    --dataset-dir "$dataset_dir"
    --min-supported-pass-rate "$min_rate"
    --max-supported-pass-rate "$max_rate"
    --max-sequence-tokens "$max_sequence_tokens"
)
if [[ -n "$task_file" ]]; then
    args+=(--task-file "$task_file")
fi

"$python_bin" "${args[@]}" > "$temporary"
"$python_bin" -c \
    'import json, sys; assert json.load(open(sys.argv[1], encoding="utf-8"))["ok"] is True' \
    "$temporary"
mv -- "$temporary" "$checkpoint"
trap - EXIT
printf 'Published strict TB4 checkpoint: %s\n' "$checkpoint"
