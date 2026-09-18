#!/bin/bash
#SBATCH --job-name=tb-eval
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/eval_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/eval_%j.log

set -euo pipefail

dry_run=0
if (( $# == 1 )) && [[ $1 == --dry-run ]]; then
    dry_run=1
elif (( $# != 0 )); then
    printf 'The eval launcher accepts no overrides except a single --dry-run\n' >&2
    exit 2
fi

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
eval_config=${EVAL_CONFIG:-$workflow_dir/configs/eval/tb4_kimi_k3_max_miniswe.toml}
output_dir=${OUTPUT_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/run_${SLURM_JOB_ID}}
resume_dir=${RESUME_DIR:-}
inference_base_url=${INFERENCE_BASE_URL:-}
inference_deployment_id=${INFERENCE_DEPLOYMENT_ID:-}
inference_proxy_info=${INFERENCE_PROXY_INFO:-}
eval_model=${EVAL_MODEL:-}
inference_proxy_url=${INFERENCE_PROXY_URL:-}
direct_qwen_manifest_sha256=${DIRECT_QWEN_MANIFEST_SHA256:-}
direct_qwen_router_policy=${DIRECT_QWEN_ROUTER_POLICY:-}
direct_qwen_request_id_headers=${DIRECT_QWEN_REQUEST_ID_HEADERS:-}
direct_qwen_provider_concurrency=${DIRECT_QWEN_PROVIDER_CONCURRENCY:-}
direct_qwen_generation_transition_sha256=${DIRECT_QWEN_GENERATION_TRANSITION_SHA256:-}
direct_qwen_capacity_smoke_sha256=${DIRECT_QWEN_CAPACITY_SMOKE_SHA256:-}

if [[ "$(uname -m)" != x86_64 || ! -d "$x86_site/pydantic" ]]; then
    printf 'Missing x86_64 Python runtime/dependencies\n' >&2
    exit 2
fi
if [[ ! -x "$x86_uv" ]]; then
    printf 'Missing x86_64 uv binary: %s\n' "$x86_uv" >&2
    exit 2
fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site${PYTHONPATH:+:$PYTHONPATH}"

if [[ "$dry_run" -eq 1 ]]; then
    if [[ -n "$resume_dir" ]]; then
        printf 'RESUME_DIR cannot be combined with --dry-run\n' >&2
        exit 2
    fi
    cd "$project_dir"
    args=(
        @ "$eval_config"
        --output-dir "$output_dir"
        --dry-run
    )
    if [[ -n "$inference_base_url" ]]; then
        args+=(--client.base-url "$inference_base_url")
    fi
    if [[ -n "$eval_model" ]]; then
        args+=(--model "$eval_model")
    fi
    exec "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 -c 'from verifiers.v1.cli.eval.main import main; main()' "${args[@]}"
fi

eval_approved_task_file=${EVAL_APPROVED_TASK_FILE:-}
eval_approved_task_file_sha256=${EVAL_APPROVED_TASK_FILE_SHA256:-}
direct_approved_task_file=${DIRECT_QWEN_APPROVED_TASK_FILE:-}
direct_approved_task_file_sha256=${DIRECT_QWEN_APPROVED_TASK_FILE_SHA256:-}
if [[ ( -n "$eval_approved_task_file" && -z "$eval_approved_task_file_sha256" ) \
    || ( -z "$eval_approved_task_file" && -n "$eval_approved_task_file_sha256" ) ]]; then
    printf 'The EVAL task approval pair is incomplete\n' >&2
    exit 2
fi
if [[ ( -n "$direct_approved_task_file" && -z "$direct_approved_task_file_sha256" ) \
    || ( -z "$direct_approved_task_file" && -n "$direct_approved_task_file_sha256" ) ]]; then
    printf 'The DIRECT_QWEN task approval pair is incomplete\n' >&2
    exit 2
fi
if [[ -n "$eval_approved_task_file" && -n "$direct_approved_task_file" ]]; then
    if [[ "$eval_approved_task_file" != "$direct_approved_task_file" \
        || "$eval_approved_task_file_sha256" != "$direct_approved_task_file_sha256" ]]; then
        printf 'The task approval environment pairs conflict\n' >&2
        exit 2
    fi
    approved_task_file=$eval_approved_task_file
    approved_task_file_sha256=$eval_approved_task_file_sha256
elif [[ -n "$eval_approved_task_file" ]]; then
    approved_task_file=$eval_approved_task_file
    approved_task_file_sha256=$eval_approved_task_file_sha256
elif [[ -n "$direct_approved_task_file" ]]; then
    approved_task_file=$direct_approved_task_file
    approved_task_file_sha256=$direct_approved_task_file_sha256
else
    printf 'An external approved task file and lowercase SHA-256 are required\n' >&2
    exit 2
fi

direct_qwen_router_metadata=0
if [[ -n "$direct_qwen_manifest_sha256" \
    || -n "$direct_qwen_router_policy" \
    || -n "$direct_qwen_request_id_headers" \
    || -n "$direct_qwen_provider_concurrency" ]]; then
    if [[ ! "$direct_qwen_manifest_sha256" =~ ^[0-9a-f]{64}$ \
        || "$direct_qwen_router_policy" != consistent_hash \
        || "$direct_qwen_request_id_headers" != x-session-id \
        || ! "$direct_qwen_provider_concurrency" =~ ^[1-9][0-9]*$ ]] \
        || (( direct_qwen_provider_concurrency > 64 )); then
        printf 'Direct Qwen router provenance is incomplete or invalid\n' >&2
        exit 2
    fi
    direct_qwen_router_metadata=1
fi
if [[ -n "$direct_qwen_generation_transition_sha256" ]]; then
    if [[ "$direct_qwen_router_metadata" -ne 1 \
        || ! "$direct_qwen_generation_transition_sha256" =~ ^[0-9a-f]{64}$ \
        || ! "$direct_qwen_capacity_smoke_sha256" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'Direct Qwen serving-generation provenance is invalid\n' >&2
        exit 2
    fi
elif [[ -n "$direct_qwen_capacity_smoke_sha256" ]]; then
    printf 'Direct Qwen capacity-smoke provenance has no serving generation\n' >&2
    exit 2
fi

if [[ -n "$inference_proxy_info" ]]; then
    if [[ ! -r "$inference_proxy_info" ]]; then
        printf 'Cannot read INFERENCE_PROXY_INFO: %s\n' "$inference_proxy_info" >&2
        exit 2
    fi
    proxy_url=$(
        "$python_bin" -c \
            'import json, sys; print(json.load(open(sys.argv[1]))["url"])' \
            "$inference_proxy_info"
    )
    proxy_api_key=$(
        "$python_bin" -c \
            'import json, sys; print(json.load(open(sys.argv[1]))["api_key"])' \
            "$inference_proxy_info"
    )
    if [[ -z "$proxy_url" || -z "$proxy_api_key" ]]; then
        printf 'INFERENCE_PROXY_INFO must contain nonempty url and api_key fields\n' >&2
        exit 2
    fi
    proxy_url=${proxy_url%/}
    if [[ "$proxy_url" == */v1 ]]; then
        inference_base_url=${inference_base_url:-$proxy_url}
    else
        inference_base_url=${inference_base_url:-$proxy_url/v1}
    fi
    export OPENAI_API_KEY=$proxy_api_key
fi

if [[ -n "$resume_dir" ]]; then
    output_dir=$resume_dir
elif [[ -z "$inference_base_url" ]]; then
    : "${INFERENCE_JOB_ID:?Set INFERENCE_BASE_URL or INFERENCE_JOB_ID}"
    inference_nodes=$(squeue -h -j "$INFERENCE_JOB_ID" -t RUNNING -o '%N')
    if [[ -z "$inference_nodes" ]]; then
        printf 'Inference job %s is not running\n' "$INFERENCE_JOB_ID" >&2
        exit 2
    fi
    inference_host=$(scontrol show hostnames "$inference_nodes" | head -n 1)
    inference_base_url="http://${inference_host}:8000/v1"
fi

mkdir -p "$output_dir" /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs
exec 9>"$output_dir/.writer.lock"
if ! flock -n 9; then
    printf 'Another evaluator owns %s\n' "$output_dir" >&2
    exit 2
fi
if [[ -z "$resume_dir" && -e "$output_dir/results.jsonl" ]]; then
    printf 'Refusing to overwrite %s/results.jsonl; use the eval resume command\n' "$output_dir" >&2
    exit 2
fi
cd "$project_dir"

if [[ -n "$resume_dir" ]]; then
    approval_args=(
        --inputs-dir "$output_dir/inputs"
        --approved-task-file "$approved_task_file"
        --approved-task-file-sha256 "$approved_task_file_sha256"
        --resume-config "$output_dir/config.toml"
    )
else
    "$python_bin" "$workflow_dir/snapshot_eval_inputs.py" \
        "$eval_config" "$output_dir/inputs"
    approval_args=(
        --inputs-dir "$output_dir/inputs"
        --approved-task-file "$approved_task_file"
        --approved-task-file-sha256 "$approved_task_file_sha256"
    )
fi
approval_metadata=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/validate_task_approval.py" "${approval_args[@]}"
)
IFS=$'\t' read -r validated_approval_sha256 validated_approval_count metadata_extra \
    <<< "$approval_metadata"
if [[ "$validated_approval_sha256" != "$approved_task_file_sha256" \
    || ! "$validated_approval_count" =~ ^[1-9][0-9]*$ \
    || -n "$metadata_extra" \
    || "$approval_metadata" == *$'\n'* ]]; then
    printf 'Task approval validator returned invalid metadata\n' >&2
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
        if [[ "$direct_qwen_router_metadata" -eq 1 ]]; then
            printf 'resume_direct_qwen_manifest_sha256=%s\n' "$direct_qwen_manifest_sha256"
            printf 'resume_direct_qwen_router_policy=%s\n' "$direct_qwen_router_policy"
            printf 'resume_direct_qwen_request_id_headers=%s\n' "$direct_qwen_request_id_headers"
            printf 'resume_direct_qwen_provider_concurrency=%s\n' "$direct_qwen_provider_concurrency"
            if [[ -n "$direct_qwen_generation_transition_sha256" ]]; then
                printf 'resume_qwen_serving_generation_transition_sha256=%s\n' \
                    "$direct_qwen_generation_transition_sha256"
                printf 'resume_qwen_serving_generation_capacity_smoke_sha256=%s\n' \
                    "$direct_qwen_capacity_smoke_sha256"
            fi
        fi
    } >> "$output_dir/provenance.txt"
else
    {
        printf 'prime_rl=%s\n' "$(git rev-parse HEAD)"
        printf 'verifiers=%s\n' "$(git -C deps/verifiers rev-parse HEAD)"
        printf 'renderers=%s\n' "$(git -C deps/renderers rev-parse HEAD)"
        printf 'inference_base_url=%s\n' "$inference_base_url"
        printf 'inference_deployment_id=%s\n' "$inference_deployment_id"
        printf 'slurm_job_id=%s\n' "$SLURM_JOB_ID"
        printf 'approval_task_file_sha256=%s\n' "$validated_approval_sha256"
        printf 'approval_task_count=%s\n' "$validated_approval_count"
        if [[ "$direct_qwen_router_metadata" -eq 1 ]]; then
            printf 'direct_qwen_manifest_sha256=%s\n' "$direct_qwen_manifest_sha256"
            printf 'direct_qwen_router_policy=%s\n' "$direct_qwen_router_policy"
            printf 'direct_qwen_request_id_headers=%s\n' "$direct_qwen_request_id_headers"
            printf 'direct_qwen_provider_concurrency=%s\n' "$direct_qwen_provider_concurrency"
            if [[ -n "$direct_qwen_generation_transition_sha256" ]]; then
                printf 'qwen_serving_generation_transition_sha256=%s\n' \
                    "$direct_qwen_generation_transition_sha256"
                printf 'qwen_serving_generation_capacity_smoke_sha256=%s\n' \
                    "$direct_qwen_capacity_smoke_sha256"
            fi
        fi
    } > "$output_dir/provenance.txt"
fi

if [[ -z "$resume_dir" && -n "$direct_qwen_generation_transition_sha256" ]]; then
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/migrate_qwen_serving_generation.py" commit-launch \
        --run-dir "$output_dir" \
        --expected-transition-sha256 "$direct_qwen_generation_transition_sha256" \
        --router-lock-fd 8 \
        --writer-lock-fd 9
fi

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
if [[ -n "$inference_proxy_url" ]]; then
    export HTTP_PROXY="$inference_proxy_url"
    export HTTPS_PROXY="$inference_proxy_url"
fi
export OPENAI_API_KEY=${OPENAI_API_KEY:-EMPTY}
export VACLI_LEASE_RETRIES=${VACLI_LEASE_RETRIES:-20}
export VACLI_MAX_CONCURRENT_LEASES=${VACLI_MAX_CONCURRENT_LEASES:-32}
export VACLI_MAX_PULL_RETRIES=${VACLI_MAX_PULL_RETRIES:-20}
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=${VACLI_IMAGE_PULL_TIMEOUT_SECONDS:-3600}
export VACLI_CONTAINER_PRIVILEGED=${VACLI_CONTAINER_PRIVILEGED:-1}

if [[ -n "$resume_dir" ]]; then
    args=(--resume "$resume_dir")
else
    args=(
        @ "$output_dir/inputs/source_config.toml"
        --client.base-url "$inference_base_url"
        --output-dir "$output_dir"
    )
    if [[ -f "$output_dir/inputs/task_file.txt" ]]; then
        args+=(--taskset.task-file "$output_dir/inputs/task_file.txt")
        args+=(--taskset.task-file-sha256 "$approved_task_file_sha256")
    fi
    if [[ -f "$output_dir/inputs/image_manifest.json" ]]; then
        args+=(--taskset.image-manifest "$output_dir/inputs/image_manifest.json")
    fi
    if [[ -n "$inference_deployment_id" ]]; then
        if [[ ! "$inference_deployment_id" =~ ^[A-Za-z0-9._:-]+$ ]]; then
            printf 'Invalid INFERENCE_DEPLOYMENT_ID: %s\n' "$inference_deployment_id" >&2
            exit 2
        fi
        args+=(--client.headers "{\"X-Deployment-Id\":\"$inference_deployment_id\"}")
    fi
    if [[ -n "$eval_model" ]]; then
        args+=(--model "$eval_model")
    fi
fi
exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 -c 'from verifiers.v1.cli.eval.main import main; main()' "${args[@]}"
