#!/bin/bash
#SBATCH --job-name=tb-oracle
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=64G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/oracle_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/oracle_%j.log

set -euo pipefail

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
dataset_dir=${DATASET_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9}
image_prefix=${IMAGE_PREFIX:-vmvm-registry.fbinfra.net/terminal_bench}
image_tag=${IMAGE_TAG:-mobius-9b6988a3faf0}
image_manifest=${IMAGE_MANIFEST:-}
output_dir=${OUTPUT_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/run_${SLURM_JOB_ID}}
max_concurrent=${MAX_CONCURRENT:-64}
python_bin=${PYTHON_BIN_X86_64:-python3}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}

mkdir -p "$output_dir" /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs
cd "$project_dir"

if [[ "$(uname -m)" != x86_64 ]]; then
    printf 'Oracle runner requires an x86_64 CPU node\n' >&2
    exit 2
fi
if [[ ! -d "$x86_site/pydantic" ]]; then
    printf 'Missing staged x86_64 dependencies: %s\n' "$x86_site" >&2
    exit 2
fi
if [[ ! -x "$x86_uv" ]]; then
    printf 'Missing x86_64 uv binary: %s\n' "$x86_uv" >&2
    exit 2
fi

{
    printf 'prime_rl=%s\n' "$(git rev-parse HEAD)"
    printf 'prime_rl_tree=%s\n' "$(git status --porcelain=v1 | sha256sum | cut -d' ' -f1)"
    printf 'verifiers=%s\n' "$(git -C deps/verifiers rev-parse HEAD)"
    printf 'vmvm_tb_v2=%s\n' "$(sha256sum environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/*.py | sha256sum | cut -d' ' -f1)"
    printf 'host=%s\n' "$(hostname)"
    printf 'slurm_job_id=%s\n' "$SLURM_JOB_ID"
} > "$output_dir/provenance.txt"

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site${PYTHONPATH:+:$PYTHONPATH}"
export VACLI_LEASE_RETRIES=${VACLI_LEASE_RETRIES:-20}
export VACLI_MAX_CONCURRENT_LEASES=${VACLI_MAX_CONCURRENT_LEASES:-32}
export VACLI_MAX_PULL_RETRIES=${VACLI_MAX_PULL_RETRIES:-20}
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=${VACLI_IMAGE_PULL_TIMEOUT_SECONDS:-3600}
export VACLI_CONTAINER_PRIVILEGED=${VACLI_CONTAINER_PRIVILEGED:-1}

args=(
    --dataset-dir "$dataset_dir"
    --output-dir "$output_dir"
    --image-prefix "$image_prefix"
    --image-tag "$image_tag"
    --max-concurrent "$max_concurrent"
    --infra-retries "${INFRA_RETRIES:-2}"
    --setup-timeout "${SETUP_TIMEOUT:-3600}"
    --validate-timeout "${VALIDATE_TIMEOUT:-10800}"
    --session-timeout "${SESSION_TIMEOUT:-10800}"
    --timeout-multiplier "${TIMEOUT_MULTIPLIER:-1}"
    --resource-multiplier "${RESOURCE_MULTIPLIER:-1}"
    --minimum-pass-rate "${MINIMUM_PASS_RATE:-0.9}"
)
if [[ -z "$image_manifest" && "${USE_DECLARED_IMAGES:-0}" != 1 \
    && -f /checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.json ]]; then
    image_manifest=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.json
fi
if [[ -n "${TASK_FILE:-}" ]]; then
    args+=(--task-file "$TASK_FILE")
fi
if [[ -n "$image_manifest" ]]; then
    args+=(--image-manifest "$image_manifest")
fi
if [[ -n "${TASKS:-}" ]]; then
    read -r -a selected_tasks <<< "$TASKS"
    args+=(--tasks "${selected_tasks[@]}")
fi
if [[ -n "${LIMIT:-}" ]]; then
    args+=(--limit "$LIMIT")
fi
if [[ "${RERUN_INVALID:-0}" == 1 ]]; then
    args+=(--rerun-invalid)
fi
if [[ "${USE_DECLARED_IMAGES:-0}" == 1 ]]; then
    args+=(--use-declared-images)
fi
if [[ "${ENABLE_COMPOSE:-0}" == 1 ]]; then
    args+=(--enable-compose)
fi

exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/run_oracle.py" "${args[@]}"
