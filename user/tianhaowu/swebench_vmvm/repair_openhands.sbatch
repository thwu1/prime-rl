#!/bin/bash
#SBATCH --job-name=swebench-oh-repair
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=128G
#SBATCH --output=/checkpoint/ram/tianhaowu/swebench_vmvm/logs/openhands_repair_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/swebench_vmvm/logs/openhands_repair_%j.log

set -euo pipefail

: "${BASE_RESULTS_DIR:?Set BASE_RESULTS_DIR to the completed OpenHands run directory}"
: "${INFERENCE_JOB_ID:?Set INFERENCE_JOB_ID to the Nemotron inference job}"

project_dir=/storage/home/tianhaowu/prime-rl
source_config=${SOURCE_CONFIG:-$project_dir/user/tianhaowu/swebench_vmvm/openhands_reasoning.toml}
repair_root=${REPAIR_ROOT:-/checkpoint/ram/tianhaowu/swebench_vmvm/repairs/openhands_${SLURM_JOB_ID}}
repair_config="$repair_root/repair.toml"
repair_results="$repair_root/eval"
base_name=$(basename "$BASE_RESULTS_DIR")
canonical_dir=${CANONICAL_DIR:-/checkpoint/ram/tianhaowu/swebench_vmvm/canonical/${base_name}_openhands}
reasoning_harness=false
if grep -q '^id = "openhands_harness_reasoning"$' "$source_config"; then
    reasoning_harness=true
fi

mkdir -p "$repair_root" "$canonical_dir"
cd "$project_dir"

export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1

repair_count=$(uv run --no-sync user/tianhaowu/swebench_vmvm/make_repair_config.py \
    "$source_config" "$BASE_RESULTS_DIR/results.jsonl" "$repair_config" \
    --include-mode-changes)
echo "OpenHands dirty tasks: $repair_count"

if [ "$repair_count" -eq 0 ]; then
    uv run --no-sync user/tianhaowu/swebench_vmvm/audit_results.py \
        "$BASE_RESULTS_DIR/results.jsonl" \
        --expected-tasks 500 --rollouts-per-task 1 \
        --require-swebench-vmvm-provenance --reject-mode-changes --strict \
        > "$canonical_dir/audit.json"
    if [ "$reasoning_harness" = true ]; then
        uv run --no-sync \
            user/tianhaowu/swebench_vmvm/openhands_harness_reasoning/audit_reasoning.py \
            "$BASE_RESULTS_DIR/results.jsonl" --strict \
            > "$canonical_dir/reasoning_audit.json"
    fi
    exit 0
fi

unset RESUME_DIR
export EVAL_CONFIG="$repair_config"
export OUTPUT_DIR="$repair_results"
export VMVM_LEASE_TTL=${VMVM_LEASE_TTL:-10m}
bash user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch

uv run --no-sync user/tianhaowu/swebench_vmvm/merge_one_rollout_repairs.py \
    "$BASE_RESULTS_DIR/results.jsonl" "$repair_results/results.jsonl" \
    --output "$canonical_dir/results.jsonl" --expected-tasks 500 \
    --reject-mode-changes
uv run --no-sync user/tianhaowu/swebench_vmvm/audit_results.py \
    "$canonical_dir/results.jsonl" \
    --expected-tasks 500 --rollouts-per-task 1 \
    --require-swebench-vmvm-provenance --reject-mode-changes --strict \
    > "$canonical_dir/audit.json"
if [ "$reasoning_harness" = true ]; then
    uv run --no-sync \
        user/tianhaowu/swebench_vmvm/openhands_harness_reasoning/audit_reasoning.py \
        "$canonical_dir/results.jsonl" --strict \
        > "$canonical_dir/reasoning_audit.json"
fi
