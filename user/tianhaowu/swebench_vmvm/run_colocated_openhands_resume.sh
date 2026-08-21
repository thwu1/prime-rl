#!/bin/bash

set -euo pipefail

: "${INFERENCE_JOB_ID:?Set INFERENCE_JOB_ID to the active Nemotron inference allocation}"
: "${BASE_RESULTS_DIR:?Set BASE_RESULTS_DIR to the interrupted OpenHands result directory}"

project_dir=/storage/home/tianhaowu/prime-rl
canonical_dir=${CANONICAL_DIR:-/checkpoint/ram/tianhaowu/swebench_vmvm/canonical/$(basename "$BASE_RESULTS_DIR")_openhands}
status_dir=${STATUS_DIR:-/checkpoint/ram/tianhaowu/swebench_vmvm/colocated_openhands}
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

mkdir -p "$status_dir" "$canonical_dir"
cd "$project_dir"

export CUDA_VISIBLE_DEVICES=
export INFERENCE_JOB_ID
export PROJECT_DIR="$project_dir"
export VMVM_LEASE_TTL=${VMVM_LEASE_TTL:-10m}
export RESUME_DIR="$BASE_RESULTS_DIR"
export RESUME_RUN_ID="$run_id"
bash user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch

unset RESUME_DIR RESUME_RUN_ID
export SOURCE_CONFIG=${SOURCE_CONFIG:-$project_dir/user/tianhaowu/swebench_vmvm/openhands_reasoning.toml}
export CANONICAL_DIR="$canonical_dir"
bash user/tianhaowu/swebench_vmvm/repair_openhands.sbatch
bash user/tianhaowu/swebench_vmvm/audit_openhands_canonical.sbatch
