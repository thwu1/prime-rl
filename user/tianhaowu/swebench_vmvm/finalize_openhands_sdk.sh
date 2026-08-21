#!/bin/bash

set -euo pipefail

: "${BASE_RESULTS_DIR:?Set BASE_RESULTS_DIR to the completed OpenHands SDK result directory}"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(git -C "$script_dir" rev-parse --show-toplevel)
expected_tasks=${EXPECTED_TASKS:-500}
rollouts_per_task=${ROLLOUTS_PER_TASK:-1}
expected_rows=$((expected_tasks * rollouts_per_task))
results="$BASE_RESULTS_DIR/results.jsonl"

required_artifacts=(
    "$results"
    "$BASE_RESULTS_DIR/config.toml"
    "$BASE_RESULTS_DIR/models.json"
    "$BASE_RESULTS_DIR/implementation.sha256"
    "$BASE_RESULTS_DIR/implementation.tar.gz"
    "$BASE_RESULTS_DIR/implementation_revisions.txt"
    "$BASE_RESULTS_DIR/inference_config.toml"
    "$BASE_RESULTS_DIR/inference_launcher.sbatch"
    "$BASE_RESULTS_DIR/inference_startup.log"
    "$BASE_RESULTS_DIR/inference_slurm_job.txt"
    "$BASE_RESULTS_DIR/inference_snapshot.sha256"
)
for artifact in "${required_artifacts[@]}"; do
    if [ ! -f "$artifact" ]; then
        printf 'Required OpenHands provenance artifact is missing: %s\n' "$artifact" >&2
        exit 1
    fi
done

cd "$project_dir"
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1

finalizer_sources=(
    user/tianhaowu/swebench_vmvm/finalize_openhands_sdk.sh
    user/tianhaowu/swebench_vmvm/watch_finalize_openhands_sdk.sh
    user/tianhaowu/swebench_vmvm/audit_results.py
    user/tianhaowu/swebench_vmvm/openhands_sdk_harness/audit.py
    user/tianhaowu/swebench_vmvm/verify_implementation_snapshot.py
    user/tianhaowu/swebench_vmvm/audit_nemotron_inference.py
)
sha256sum "${finalizer_sources[@]}" > "$BASE_RESULTS_DIR/finalizer_sources.sha256.tmp"
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
    -czf "$BASE_RESULTS_DIR/finalizer_sources.tar.gz.tmp" "${finalizer_sources[@]}"
mv "$BASE_RESULTS_DIR/finalizer_sources.sha256.tmp" "$BASE_RESULTS_DIR/finalizer_sources.sha256"
mv "$BASE_RESULTS_DIR/finalizer_sources.tar.gz.tmp" "$BASE_RESULTS_DIR/finalizer_sources.tar.gz"
uv run --no-sync python user/tianhaowu/swebench_vmvm/verify_implementation_snapshot.py \
    "$BASE_RESULTS_DIR/finalizer_sources.sha256" "$BASE_RESULTS_DIR/finalizer_sources.tar.gz" \
    --require-exact-members --strict \
    > "$BASE_RESULTS_DIR/finalizer_sources_audit.json.tmp"
mv "$BASE_RESULTS_DIR/finalizer_sources_audit.json.tmp" "$BASE_RESULTS_DIR/finalizer_sources_audit.json"

runtime_source_roots=(
    environments/vmvm_tb_v2/vmvm_tb_v2
    deps/verifiers/verifiers/v1
    deps/research-environments/environments/swebench_verified_v1/swebench_verified_v1
)
mapfile -d '' runtime_sources < <(
    find "${runtime_source_roots[@]}" -type f \
        ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 | sort -z
)
if [ "${#runtime_sources[@]}" -eq 0 ]; then
    printf 'No runtime dependency sources found\n' >&2
    exit 1
fi
sha256sum "${runtime_sources[@]}" > "$BASE_RESULTS_DIR/runtime_sources.sha256.tmp"
printf '%s\0' "${runtime_sources[@]}" | \
    tar --null --files-from=- --sort=name --mtime='UTC 1970-01-01' \
        --owner=0 --group=0 --numeric-owner \
        -czf "$BASE_RESULTS_DIR/runtime_sources.tar.gz.tmp"
{
    printf 'prime_rl=%s\n' "$(git rev-parse HEAD)"
    printf 'verifiers=%s\n' "$(git -C deps/verifiers rev-parse HEAD)"
    printf 'research_environments=%s\n' "$(git -C deps/research-environments rev-parse HEAD)"
} > "$BASE_RESULTS_DIR/runtime_revisions.txt.tmp"
mv "$BASE_RESULTS_DIR/runtime_sources.sha256.tmp" "$BASE_RESULTS_DIR/runtime_sources.sha256"
mv "$BASE_RESULTS_DIR/runtime_sources.tar.gz.tmp" "$BASE_RESULTS_DIR/runtime_sources.tar.gz"
mv "$BASE_RESULTS_DIR/runtime_revisions.txt.tmp" "$BASE_RESULTS_DIR/runtime_revisions.txt"
uv run --no-sync python user/tianhaowu/swebench_vmvm/verify_implementation_snapshot.py \
    "$BASE_RESULTS_DIR/runtime_sources.sha256" "$BASE_RESULTS_DIR/runtime_sources.tar.gz" \
    --require-exact-members --strict \
    > "$BASE_RESULTS_DIR/runtime_sources_audit.json.tmp"
mv "$BASE_RESULTS_DIR/runtime_sources_audit.json.tmp" "$BASE_RESULTS_DIR/runtime_sources_audit.json"

uv run --no-sync python user/tianhaowu/swebench_vmvm/audit_results.py \
    "$results" --expected-tasks "$expected_tasks" \
    --rollouts-per-task "$rollouts_per_task" \
    --require-swebench-vmvm-provenance --reject-mode-changes --strict \
    > "$BASE_RESULTS_DIR/strict_audit.json.tmp"
mv "$BASE_RESULTS_DIR/strict_audit.json.tmp" "$BASE_RESULTS_DIR/strict_audit.json"

uv run --no-sync python user/tianhaowu/swebench_vmvm/openhands_sdk_harness/audit.py \
    "$results" --expected-rows "$expected_rows" --strict \
    > "$BASE_RESULTS_DIR/sdk_harness_audit.json.tmp"
mv "$BASE_RESULTS_DIR/sdk_harness_audit.json.tmp" "$BASE_RESULTS_DIR/sdk_harness_audit.json"

uv run --no-sync python user/tianhaowu/swebench_vmvm/verify_implementation_snapshot.py \
    "$BASE_RESULTS_DIR/implementation.sha256" "$BASE_RESULTS_DIR/implementation.tar.gz" \
    --require-exact-members --strict \
    > "$BASE_RESULTS_DIR/implementation_audit.json.tmp"
mv "$BASE_RESULTS_DIR/implementation_audit.json.tmp" "$BASE_RESULTS_DIR/implementation_audit.json"

sha256sum -c "$BASE_RESULTS_DIR/inference_snapshot.sha256"
uv run --no-sync python user/tianhaowu/swebench_vmvm/audit_nemotron_inference.py \
    "$BASE_RESULTS_DIR/inference_config.toml" "$BASE_RESULTS_DIR/models.json" \
    "$BASE_RESULTS_DIR/inference_startup.log" --strict \
    > "$BASE_RESULTS_DIR/inference_audit.json.tmp"
mv "$BASE_RESULTS_DIR/inference_audit.json.tmp" "$BASE_RESULTS_DIR/inference_audit.json"

# Prove that the sources executed above did not change after being archived.
sha256sum -c "$BASE_RESULTS_DIR/finalizer_sources.sha256"
sha256sum -c "$BASE_RESULTS_DIR/runtime_sources.sha256"

hash_inputs=(
    "$results"
    "$BASE_RESULTS_DIR/config.toml"
    "$BASE_RESULTS_DIR/strict_audit.json"
    "$BASE_RESULTS_DIR/sdk_harness_audit.json"
)
for artifact in \
    "$BASE_RESULTS_DIR"/models*.json \
    "$BASE_RESULTS_DIR"/config.before-resume-*.toml \
    "$BASE_RESULTS_DIR"/inference_* \
    "$BASE_RESULTS_DIR"/implementation.sha256 \
    "$BASE_RESULTS_DIR"/implementation.tar.gz \
    "$BASE_RESULTS_DIR"/implementation_revisions.txt \
    "$BASE_RESULTS_DIR"/implementation_audit.json \
    "$BASE_RESULTS_DIR"/finalizer_sources.sha256 \
    "$BASE_RESULTS_DIR"/finalizer_sources.tar.gz \
    "$BASE_RESULTS_DIR"/finalizer_sources_audit.json \
    "$BASE_RESULTS_DIR"/runtime_sources.sha256 \
    "$BASE_RESULTS_DIR"/runtime_sources.tar.gz \
    "$BASE_RESULTS_DIR"/runtime_sources_audit.json \
    "$BASE_RESULTS_DIR"/runtime_revisions.txt; do
    if [ -f "$artifact" ]; then
        hash_inputs+=("$artifact")
    fi
done
sha256sum "${hash_inputs[@]}" > "$BASE_RESULTS_DIR/final.sha256.tmp"
mv "$BASE_RESULTS_DIR/final.sha256.tmp" "$BASE_RESULTS_DIR/final.sha256"
sha256sum -c "$BASE_RESULTS_DIR/final.sha256"
