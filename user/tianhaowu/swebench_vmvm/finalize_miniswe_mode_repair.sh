#!/bin/bash

set -euo pipefail

: "${BASE_RESULTS_DIR:?Set BASE_RESULTS_DIR to the original 500-task MiniSWE result directory}"
: "${REPAIR_RESULTS_DIR:?Set REPAIR_RESULTS_DIR to the completed mode-clean repair result directory}"

project_dir=/storage/home/tianhaowu/prime-rl
expected_repairs=${EXPECTED_REPAIRS:-93}
canonical_dir=${CANONICAL_DIR:-/checkpoint/ram/tianhaowu/swebench_vmvm/canonical/$(basename "$BASE_RESULTS_DIR")_miniswe_filemode_clean}

cd "$project_dir"
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1

uv run --no-sync python user/tianhaowu/swebench_vmvm/audit_results.py \
    "$REPAIR_RESULTS_DIR/results.jsonl" --expected-tasks "$expected_repairs" \
    --rollouts-per-task 1 --require-swebench-vmvm-provenance \
    --reject-mode-changes --strict > "$REPAIR_RESULTS_DIR/strict_audit.json.tmp"
mv "$REPAIR_RESULTS_DIR/strict_audit.json.tmp" "$REPAIR_RESULTS_DIR/strict_audit.json"
uv run --no-sync python user/tianhaowu/swebench_vmvm/swe_rebench_miniswe/audit_native_tools.py \
    "$REPAIR_RESULTS_DIR/results.jsonl" --strict \
    > "$REPAIR_RESULTS_DIR/native_tools_audit.json.tmp"
mv "$REPAIR_RESULTS_DIR/native_tools_audit.json.tmp" "$REPAIR_RESULTS_DIR/native_tools_audit.json"
if [ -f "$REPAIR_RESULTS_DIR/implementation.sha256" ] && [ -f "$REPAIR_RESULTS_DIR/implementation.tar.gz" ]; then
    uv run --no-sync python user/tianhaowu/swebench_vmvm/verify_implementation_snapshot.py \
        "$REPAIR_RESULTS_DIR/implementation.sha256" "$REPAIR_RESULTS_DIR/implementation.tar.gz" --strict \
        > "$REPAIR_RESULTS_DIR/implementation_audit.json.tmp"
    mv "$REPAIR_RESULTS_DIR/implementation_audit.json.tmp" "$REPAIR_RESULTS_DIR/implementation_audit.json"
fi

mkdir -p "$canonical_dir"
uv run --no-sync python user/tianhaowu/swebench_vmvm/merge_one_rollout_repairs.py \
    "$BASE_RESULTS_DIR/results.jsonl" "$REPAIR_RESULTS_DIR/results.jsonl" \
    --output "$canonical_dir/results.jsonl" --expected-tasks 500 \
    --reject-mode-changes > "$canonical_dir/merge.json"
uv run --no-sync python user/tianhaowu/swebench_vmvm/audit_results.py \
    "$canonical_dir/results.jsonl" --expected-tasks 500 --rollouts-per-task 1 \
    --require-swebench-vmvm-provenance --reject-mode-changes --strict \
    > "$canonical_dir/strict_audit.json"
uv run --no-sync python user/tianhaowu/swebench_vmvm/swe_rebench_miniswe/audit_native_tools.py \
    "$canonical_dir/results.jsonl" --strict > "$canonical_dir/native_tools_audit.json"

hash_inputs=(
    "$canonical_dir/results.jsonl"
    "$canonical_dir/results.jsonl.provenance.json"
    "$canonical_dir/merge.json"
    "$canonical_dir/strict_audit.json"
    "$canonical_dir/native_tools_audit.json"
    "$BASE_RESULTS_DIR/results.jsonl"
    "$BASE_RESULTS_DIR/config.toml"
    "$REPAIR_RESULTS_DIR/results.jsonl"
    "$REPAIR_RESULTS_DIR/config.toml"
    "$REPAIR_RESULTS_DIR/strict_audit.json"
    "$REPAIR_RESULTS_DIR/native_tools_audit.json"
)
for artifact in \
    "$BASE_RESULTS_DIR"/models*.json \
    "$REPAIR_RESULTS_DIR"/models*.json \
    "$REPAIR_RESULTS_DIR"/implementation.sha256 \
    "$REPAIR_RESULTS_DIR"/implementation.tar.gz \
    "$REPAIR_RESULTS_DIR"/implementation_audit.json; do
    if [ -f "$artifact" ]; then
        hash_inputs+=("$artifact")
    fi
done
sha256sum "${hash_inputs[@]}" > "$canonical_dir/final.sha256.tmp"
mv "$canonical_dir/final.sha256.tmp" "$canonical_dir/final.sha256"
sha256sum -c "$canonical_dir/final.sha256"
