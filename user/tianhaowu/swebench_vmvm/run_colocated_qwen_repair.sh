#!/bin/bash

set -euo pipefail

: "${INFERENCE_JOB_ID:?Set INFERENCE_JOB_ID to the active Qwen inference allocation}"
: "${SOURCE_EVAL_JOB_ID:?Set SOURCE_EVAL_JOB_ID to the original evaluator allocation}"
: "${BASE_RESULTS_DIR:?Set BASE_RESULTS_DIR to the Qwen MiniSWE result directory}"

project_dir=/storage/home/tianhaowu/prime-rl
status_dir=${STATUS_DIR:-/checkpoint/ram/tianhaowu/swebench_vmvm/colocated_qwen}
run_id=${COLOCATED_RUN_ID:-${SLURM_JOB_ID}-${SLURM_STEP_ID:-step}}
status_file="$status_dir/${run_id}.json"
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
initial_rows=$(wc -l < "$BASE_RESULTS_DIR/results.jsonl")

write_status() {
    rc=$?
    trap - EXIT
    completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    final_rows=$(wc -l < "$BASE_RESULTS_DIR/results.jsonl")
    tmp="$status_file.tmp.$$"
    printf '{"run_id":"%s","host":"%s","started_at":"%s","completed_at":"%s","initial_rows":%s,"final_rows":%s,"exit_code":%s}\n' \
        "$run_id" "$(hostname)" "$started_at" "$completed_at" "$initial_rows" "$final_rows" "$rc" > "$tmp"
    mv "$tmp" "$status_file"
    exit "$rc"
}
trap write_status EXIT

mkdir -p "$status_dir"
cd "$project_dir"

source_state=$(squeue -h -j "$SOURCE_EVAL_JOB_ID" -o '%T' 2>/dev/null || true)
if [ -n "$source_state" ]; then
    echo "source evaluator $SOURCE_EVAL_JOB_ID is still active: $source_state" >&2
    exit 1
fi

export CUDA_VISIBLE_DEVICES=
export VMVM_LEASE_TTL=${VMVM_LEASE_TTL:-10m}
for task in gotd__td-1759 openrewrite__rewrite-7784; do
    TASKS="$task" bash user/tianhaowu/swebench_vmvm/validate_swe_rebench.sbatch
done

export INFERENCE_JOB_ID
export PROJECT_DIR="$project_dir"
export RESUME_DIR="$BASE_RESULTS_DIR"
export RESUME_RUN_ID="$run_id"
bash user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch
unset RESUME_DIR RESUME_RUN_ID

export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
uv run --no-sync python user/tianhaowu/swebench_vmvm/audit_results.py \
    "$BASE_RESULTS_DIR/results.jsonl" --expected-tasks 111 --rollouts-per-task 5 \
    --reject-mode-changes --strict \
    > "$BASE_RESULTS_DIR/strict_audit.json.tmp"
mv "$BASE_RESULTS_DIR/strict_audit.json.tmp" "$BASE_RESULTS_DIR/strict_audit.json"
uv run --no-sync python user/tianhaowu/swebench_vmvm/swe_rebench_miniswe/audit_native_tools.py \
    "$BASE_RESULTS_DIR/results.jsonl" --strict \
    > "$BASE_RESULTS_DIR/native_tools_audit.json.tmp"
mv "$BASE_RESULTS_DIR/native_tools_audit.json.tmp" "$BASE_RESULTS_DIR/native_tools_audit.json"
uv run --no-sync python user/tianhaowu/swebench_vmvm/swe_rebench_harbor/audit.py \
    "$BASE_RESULTS_DIR/results.jsonl" --expected-rollouts 5 \
    --require-verifier-metadata --strict \
    > "$BASE_RESULTS_DIR/swe_rebench_audit.json.tmp"
mv "$BASE_RESULTS_DIR/swe_rebench_audit.json.tmp" "$BASE_RESULTS_DIR/swe_rebench_audit.json"
hash_inputs=(
    "$BASE_RESULTS_DIR/results.jsonl" \
    "$BASE_RESULTS_DIR/config.toml" \
    "$BASE_RESULTS_DIR/strict_audit.json" \
    "$BASE_RESULTS_DIR/native_tools_audit.json" \
    "$BASE_RESULTS_DIR/swe_rebench_audit.json"
)
for artifact in "$BASE_RESULTS_DIR"/models*.json "$BASE_RESULTS_DIR"/config.before-resume-*.toml; do
    if [ -f "$artifact" ]; then
        hash_inputs+=("$artifact")
    fi
done
sha256sum "${hash_inputs[@]}" > "$BASE_RESULTS_DIR/final.sha256.tmp"
mv "$BASE_RESULTS_DIR/final.sha256.tmp" "$BASE_RESULTS_DIR/final.sha256"
