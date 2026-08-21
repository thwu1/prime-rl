#!/bin/bash
#SBATCH --job-name=swebench-oh-audit
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --output=/checkpoint/ram/tianhaowu/swebench_vmvm/logs/openhands_canonical_audit_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/swebench_vmvm/logs/openhands_canonical_audit_%j.log

set -euo pipefail

: "${BASE_RESULTS_DIR:?Set BASE_RESULTS_DIR to the completed OpenHands run directory}"

project_dir=/storage/home/tianhaowu/prime-rl
base_name=$(basename "$BASE_RESULTS_DIR")
canonical_dir=${CANONICAL_DIR:-/checkpoint/ram/tianhaowu/swebench_vmvm/canonical/${base_name}_openhands}
target_results="$BASE_RESULTS_DIR/results.jsonl"
if [ -f "$canonical_dir/results.jsonl" ]; then
    target_results="$canonical_dir/results.jsonl"
fi
target_dir=$(dirname "$target_results")

cd "$project_dir"
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1

uv run --no-sync user/tianhaowu/swebench_vmvm/audit_results.py \
    "$target_results" \
    --expected-tasks 500 --rollouts-per-task 1 \
    --require-swebench-vmvm-provenance --reject-mode-changes --strict \
    > "$target_dir/vmvm_provenance_audit.json"
uv run --no-sync \
    user/tianhaowu/swebench_vmvm/openhands_harness_reasoning/audit_reasoning.py \
    "$target_results" --strict \
    > "$target_dir/reasoning_audit.json"

hash_inputs=("$target_results" "$BASE_RESULTS_DIR/config.toml")
if [ -f "${target_results}.provenance.json" ]; then
    hash_inputs+=("${target_results}.provenance.json")
fi
sha256sum "${hash_inputs[@]}" > "$target_dir/provenance.sha256"
