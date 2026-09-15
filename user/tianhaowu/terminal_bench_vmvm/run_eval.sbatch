#!/bin/bash
#SBATCH --job-name=tb-eval
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=96G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/eval_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/eval_%j.log

set -euo pipefail

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
eval_config=${EVAL_CONFIG:-$workflow_dir/configs/eval/tb4_kimi_k3_max_miniswe.toml}
output_dir=${OUTPUT_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/run_${SLURM_JOB_ID}}
resume_dir=${RESUME_DIR:-}
inference_base_url=${INFERENCE_BASE_URL:-}
inference_deployment_id=${INFERENCE_DEPLOYMENT_ID:-}
eval_model=${EVAL_MODEL:-}
inference_proxy_url=${INFERENCE_PROXY_URL:-}

if [[ "$(uname -m)" != x86_64 || ! -d "$x86_site/pydantic" ]]; then
    printf 'Missing x86_64 Python runtime/dependencies\n' >&2
    exit 2
fi
if [[ ! -x "$x86_uv" ]]; then
    printf 'Missing x86_64 uv binary: %s\n' "$x86_uv" >&2
    exit 2
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
    printf 'resume_slurm_job_id=%s\n' "$SLURM_JOB_ID" >> "$output_dir/provenance.txt"
else
    "$python_bin" "$workflow_dir/snapshot_eval_inputs.py" \
        "$eval_config" "$output_dir/inputs"
    {
        printf 'prime_rl=%s\n' "$(git rev-parse HEAD)"
        printf 'verifiers=%s\n' "$(git -C deps/verifiers rev-parse HEAD)"
        printf 'renderers=%s\n' "$(git -C deps/renderers rev-parse HEAD)"
        printf 'inference_base_url=%s\n' "$inference_base_url"
        printf 'inference_deployment_id=%s\n' "$inference_deployment_id"
        printf 'slurm_job_id=%s\n' "$SLURM_JOB_ID"
    } > "$output_dir/provenance.txt"
fi

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
if [[ -n "$inference_proxy_url" ]]; then
    export HTTP_PROXY="$inference_proxy_url"
    export HTTPS_PROXY="$inference_proxy_url"
fi
export OPENAI_API_KEY=${OPENAI_API_KEY:-EMPTY}
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site${PYTHONPATH:+:$PYTHONPATH}"
export VACLI_LEASE_RETRIES=${VACLI_LEASE_RETRIES:-20}
export VACLI_MAX_CONCURRENT_LEASES=${VACLI_MAX_CONCURRENT_LEASES:-32}
export VACLI_MAX_PULL_RETRIES=${VACLI_MAX_PULL_RETRIES:-20}
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=${VACLI_IMAGE_PULL_TIMEOUT_SECONDS:-3600}
export VACLI_CONTAINER_PRIVILEGED=${VACLI_CONTAINER_PRIVILEGED:-1}

if [[ -n "$resume_dir" ]]; then
    if (( $# != 0 )); then
        printf 'RESUME_DIR cannot be combined with eval overrides\n' >&2
        exit 2
    fi
    args=(--resume "$resume_dir")
else
    args=(
        @ "$output_dir/inputs/source_config.toml"
        --client.base-url "$inference_base_url"
        --output-dir "$output_dir"
    )
    if [[ -f "$output_dir/inputs/task_file.txt" ]]; then
        args+=(--taskset.task-file "$output_dir/inputs/task_file.txt")
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
    args+=("$@")
fi
exec "$x86_uv" run --no-project --offline --python python3 \
    python3 -c 'from verifiers.v1.cli.eval.main import main; main()' "${args[@]}"
