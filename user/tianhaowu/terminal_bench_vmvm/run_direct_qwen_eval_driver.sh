#!/bin/bash
# shellcheck shell=bash

set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf 'The direct Qwen eval driver accepts no arguments\n' >&2
    exit 2
fi

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
resume_dir=${RESUME_DIR:-}
output_dir=${OUTPUT_DIR:?The direct Qwen wrapper must set OUTPUT_DIR}
inference_base_url=${INFERENCE_BASE_URL:?The direct Qwen wrapper must set INFERENCE_BASE_URL}
approved_task_file=${DIRECT_QWEN_APPROVED_TASK_FILE:?Missing direct Qwen task approval}
approved_task_file_sha256=${DIRECT_QWEN_APPROVED_TASK_FILE_SHA256:?Missing direct Qwen task approval hash}
deployment_root=${DIRECT_QWEN_DEPLOYMENT_ROOT:-/checkpoint/ram/shared/vllm_deployments_v2/shared_qwen38_2p4t}
worker_manifest="$output_dir/direct_workers.json"

if [[ -n ${EVAL_RUN_ROLE:-} || -n ${EVAL_MODEL:-} || -n ${EVAL_APPROVED_TASK_FILE:-} \
    || -n ${INFERENCE_DEPLOYMENT_ID:-} || -n ${INFERENCE_JOB_ID:-} \
    || -n ${INFERENCE_PROXY_INFO:-} || -n ${INFERENCE_PROXY_URL:-} ]]; then
    printf 'Direct Qwen driver received a forbidden generic-eval override\n' >&2
    exit 2
fi
if [[ ${OPENAI_API_KEY:-EMPTY} != EMPTY ]]; then
    printf 'Direct Qwen driver accepts only OPENAI_API_KEY=EMPTY\n' >&2
    exit 2
fi
if [[ "$(uname -m)" != x86_64 || ! -d "$x86_site/pydantic" || ! -x "$x86_uv" ]]; then
    printf 'Missing x86_64 direct Qwen evaluator runtime\n' >&2
    exit 2
fi

if [[ -n "$resume_dir" ]]; then
    if [[ "$output_dir" != "$resume_dir" ]]; then
        printf 'Direct Qwen resume/output directories disagree\n' >&2
        exit 2
    fi
    eval_config="$resume_dir/config.toml"
else
    eval_config=${EVAL_CONFIG:?The direct Qwen wrapper must set EVAL_CONFIG}
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site${PYTHONPATH:+:$PYTHONPATH}"
cd "$project_dir"

if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" \
    || -n "$(git -C deps/verifiers status --porcelain=v1 --untracked-files=all)" \
    || -n "$(git -C deps/renderers status --porcelain=v1 --untracked-files=all)" ]]; then
    printf 'Prime-RL, Verifiers, and Renderers worktrees must all be clean\n' >&2
    exit 2
fi

direct_metadata=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 - "$worker_manifest" "$eval_config" "$approved_task_file" \
        "$approved_task_file_sha256" "$inference_base_url" "$deployment_root" <<'PY'
import hashlib
import sys
from pathlib import Path

from direct_qwen_workers import load_workers, validate_eval_config, validate_saved_manifest

manifest_path = Path(sys.argv[1]).resolve(strict=True)
manifest = validate_saved_manifest(manifest_path)
_, live_spec_sha256, live_bundle_sha256 = load_workers(Path(sys.argv[6]))
task_sha256 = validate_eval_config(
    Path(sys.argv[2]),
    approved_task_file=Path(sys.argv[3]),
    approved_task_file_sha256=sys.argv[4],
)
expected_url = f"http://127.0.0.1:{manifest['router']['port']}/v1"
if (
    sys.argv[5].rstrip("/") != expected_url
    or task_sha256 != manifest["approved_task_allowlist_sha256"]
    or live_spec_sha256 != manifest["spec_sha256"]
    or live_bundle_sha256 != manifest["endpoint_bundle_sha256"]
):
    raise SystemExit(2)
with manifest_path.open("rb") as handle:
    manifest_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
print(
    "\t".join(
        (
            manifest_sha256,
            manifest["spec_sha256"],
            manifest["endpoint_bundle_sha256"],
        )
    )
)
PY
)
IFS=$'\t' read -r worker_manifest_sha256 direct_spec_sha256 direct_bundle_sha256 metadata_extra \
    <<< "$direct_metadata"
if [[ ! "$worker_manifest_sha256" =~ ^[0-9a-f]{64}$ \
    || ! "$direct_spec_sha256" =~ ^[0-9a-f]{64}$ \
    || ! "$direct_bundle_sha256" =~ ^[0-9a-f]{64}$ \
    || -n "$metadata_extra" || "$direct_metadata" == *$'\n'* ]]; then
    printf 'Direct Qwen validator returned invalid metadata\n' >&2
    exit 2
fi

exec 9>"$output_dir/.writer.lock"
if ! flock -n 9; then
    printf 'Another evaluator owns %s\n' "$output_dir" >&2
    exit 2
fi
if [[ -z "$resume_dir" ]]; then
    for existing in inputs config.toml results.jsonl provenance.txt; do
        if [[ -e "$output_dir/$existing" ]]; then
            printf 'Refusing to overwrite existing direct Qwen artifact: %s/%s\n' "$output_dir" "$existing" >&2
            exit 2
        fi
    done
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/snapshot_eval_inputs.py" "$eval_config" "$output_dir/inputs"
    approval_args=(
        --inputs-dir "$output_dir/inputs"
        --approved-task-file "$approved_task_file"
        --approved-task-file-sha256 "$approved_task_file_sha256"
    )
else
    approval_args=(
        --inputs-dir "$output_dir/inputs"
        --approved-task-file "$approved_task_file"
        --approved-task-file-sha256 "$approved_task_file_sha256"
        --resume-config "$output_dir/config.toml"
    )
fi

approval_metadata=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/validate_task_approval.py" "${approval_args[@]}"
)
IFS=$'\t' read -r validated_approval_sha256 validated_approval_count approval_extra \
    <<< "$approval_metadata"
if [[ "$validated_approval_sha256" != "$approved_task_file_sha256" \
    || ! "$validated_approval_count" =~ ^[1-9][0-9]*$ \
    || -n "$approval_extra" || "$approval_metadata" == *$'\n'* ]]; then
    printf 'Direct Qwen task approval validator returned invalid metadata\n' >&2
    exit 2
fi

if [[ -n "$resume_dir" ]]; then
    {
        printf 'resume_slurm_job_id=%s\n' "$SLURM_JOB_ID"
        printf 'resume_prime_rl=%s\n' "$(git rev-parse HEAD)"
        printf 'resume_verifiers=%s\n' "$(git -C deps/verifiers rev-parse HEAD)"
        printf 'resume_renderers=%s\n' "$(git -C deps/renderers rev-parse HEAD)"
        printf 'resume_approval_task_file_sha256=%s\n' "$validated_approval_sha256"
        printf 'resume_approval_task_count=%s\n' "$validated_approval_count"
        printf 'resume_direct_worker_manifest_sha256=%s\n' "$worker_manifest_sha256"
    } >> "$output_dir/provenance.txt"
    args=(--resume "$resume_dir")
else
    {
        printf 'prime_rl=%s\n' "$(git rev-parse HEAD)"
        printf 'verifiers=%s\n' "$(git -C deps/verifiers rev-parse HEAD)"
        printf 'renderers=%s\n' "$(git -C deps/renderers rev-parse HEAD)"
        printf 'inference_base_url=%s\n' "$inference_base_url"
        printf 'inference_deployment_id=\n'
        printf 'slurm_job_id=%s\n' "$SLURM_JOB_ID"
        printf 'approval_task_file_sha256=%s\n' "$validated_approval_sha256"
        printf 'approval_task_count=%s\n' "$validated_approval_count"
        printf 'direct_worker_manifest_sha256=%s\n' "$worker_manifest_sha256"
        printf 'direct_spec_sha256=%s\n' "$direct_spec_sha256"
        printf 'direct_endpoint_bundle_sha256=%s\n' "$direct_bundle_sha256"
    } > "$output_dir/provenance.txt"
    args=(
        @ "$output_dir/inputs/source_config.toml"
        --client.base-url "$inference_base_url"
        --output-dir "$output_dir"
        --taskset.task-file "$output_dir/inputs/task_file.txt"
        --taskset.task-file-sha256 "$approved_task_file_sha256"
    )
    if [[ -f "$output_dir/inputs/image_manifest.json" ]]; then
        args+=(--taskset.image-manifest "$output_dir/inputs/image_manifest.json")
    fi
fi

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export OPENAI_API_KEY=EMPTY
export VACLI_LEASE_RETRIES=${VACLI_LEASE_RETRIES:-20}
export VACLI_MAX_CONCURRENT_LEASES=${VACLI_MAX_CONCURRENT_LEASES:-8}
export VACLI_MAX_PULL_RETRIES=${VACLI_MAX_PULL_RETRIES:-20}
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=${VACLI_IMAGE_PULL_TIMEOUT_SECONDS:-3600}
export VACLI_CONTAINER_PRIVILEGED=${VACLI_CONTAINER_PRIVILEGED:-1}
export VACLI_BIN=${VACLI_BIN:-/public/fbpkgs/x86_64/vacli/stable/vacli}

exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 -c 'from verifiers.v1.cli.eval.main import main; main()' "${args[@]}"
