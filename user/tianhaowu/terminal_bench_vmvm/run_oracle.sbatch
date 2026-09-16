#!/bin/bash
#SBATCH --job-name=tb-oracle
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/oracle_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/oracle_%j.log

set -euo pipefail

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
dataset_dir=${DATASET_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9}
dataset_revision=${DATASET_REVISION:-}
dataset_archive=${DATASET_ARCHIVE:-}
dataset_archive_sha256=${DATASET_ARCHIVE_SHA256:-}
image_prefix=${IMAGE_PREFIX:-vmvm-registry.fbinfra.net/terminal_bench}
image_tag=${IMAGE_TAG:-mobius-9b6988a3faf0}
image_manifest=${IMAGE_MANIFEST:-}
image_manifest_sha256=${IMAGE_MANIFEST_SHA256:-}
task_file=${TASK_FILE:-}
task_file_sha256=${TASK_FILE_SHA256:-}
output_dir=${OUTPUT_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/run_${SLURM_JOB_ID}}
max_concurrent=${MAX_CONCURRENT:-64}
oracle_solution_network_mode=${ORACLE_SOLUTION_NETWORK_MODE:-declared}
python_bin=${PYTHON_BIN_X86_64:-python3}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
vacli_lease_retries=${VACLI_LEASE_RETRIES:-20}
vacli_max_concurrent_leases=${VACLI_MAX_CONCURRENT_LEASES:-32}
vacli_max_pull_retries=${VACLI_MAX_PULL_RETRIES:-20}
vacli_image_pull_timeout_seconds=${VACLI_IMAGE_PULL_TIMEOUT_SECONDS:-3600}
vacli_container_privileged=${VACLI_CONTAINER_PRIVILEGED:-1}

cd "$project_dir"

expected_launcher="$workflow_dir/run_oracle.sbatch"
submitted_launcher=${BASH_SOURCE[0]}
if [[ ! -f "$expected_launcher" || ! -f "$submitted_launcher" \
    || "$(sha256sum "$submitted_launcher" | cut -d' ' -f1)" \
       != "$(sha256sum "$expected_launcher" | cut -d' ' -f1)" ]]; then
    printf 'Submitted oracle wrapper does not match the attested Prime RL source\n' >&2
    exit 2
fi

tb4_dataset=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/tb4-prebuilt-v4.0.0/tasks
if [[ "${USE_DECLARED_IMAGES:-0}" == 1 && "$dataset_dir" == "$tb4_dataset" \
    && -z "$dataset_revision" && -z "$dataset_archive" && -z "$dataset_archive_sha256" ]]; then
    dataset_archive=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/downloads/terminal-bench-prebuilt-v4.0.0.tar.gz
    dataset_archive_sha256=6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e
fi
if [[ ( -n "$dataset_archive" && -z "$dataset_archive_sha256" ) \
    || ( -z "$dataset_archive" && -n "$dataset_archive_sha256" ) ]]; then
    printf 'DATASET_ARCHIVE and DATASET_ARCHIVE_SHA256 must be supplied together\n' >&2
    exit 2
fi
if [[ ( -n "$dataset_revision" && -n "$dataset_archive" ) \
    || ( -z "$dataset_revision" && -z "$dataset_archive" ) ]]; then
    printf 'Supply exactly one dataset authority: DATASET_REVISION or DATASET_ARCHIVE pair\n' >&2
    exit 2
fi
if [[ "${USE_DECLARED_IMAGES:-0}" != 1 && -z "$dataset_revision" ]]; then
    printf 'DATASET_REVISION is required for image-manifest oracle promotion\n' >&2
    exit 2
fi
if [[ -z "$image_manifest" && "${USE_DECLARED_IMAGES:-0}" != 1 \
    && -f /checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.json ]]; then
    image_manifest=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.json
fi
if [[ ( -n "$task_file" && -z "$task_file_sha256" ) \
    || ( -z "$task_file" && -n "$task_file_sha256" ) ]]; then
    printf 'TASK_FILE and TASK_FILE_SHA256 must be supplied together\n' >&2
    exit 2
fi
if [[ ( -n "$image_manifest" && -z "$image_manifest_sha256" ) \
    || ( -z "$image_manifest" && -n "$image_manifest_sha256" ) ]]; then
    printf 'IMAGE_MANIFEST and IMAGE_MANIFEST_SHA256 must be supplied together\n' >&2
    exit 2
fi
if [[ ! "$vacli_lease_retries" =~ ^(0|[1-9][0-9]*)$ \
    || ! "$vacli_max_pull_retries" =~ ^(0|[1-9][0-9]*)$ \
    || ! "$vacli_max_concurrent_leases" =~ ^[1-9][0-9]*$ \
    || ! "$vacli_image_pull_timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
    printf 'VACLI retry, concurrency, and pull-timeout controls must be canonical integers\n' >&2
    exit 2
fi
if [[ "$vacli_container_privileged" != 0 && "$vacli_container_privileged" != 1 ]]; then
    printf 'VACLI_CONTAINER_PRIVILEGED must be 0 or 1\n' >&2
    exit 2
fi

case "$oracle_solution_network_mode" in
    declared|public) ;;
    *)
        printf 'Invalid ORACLE_SOLUTION_NETWORK_MODE: %s\n' "$oracle_solution_network_mode" >&2
        exit 2
        ;;
esac

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

prime_rl_status=$(git status --porcelain=v1 --untracked-files=all)
if [[ -n "$prime_rl_status" ]]; then
    printf 'Prime RL source worktree is not clean; refusing an unpinned oracle launch\n' >&2
    exit 2
fi
verifiers_status=$(git -C deps/verifiers status --porcelain=v1 --untracked-files=all)
if [[ -n "$verifiers_status" ]]; then
    printf 'Verifiers source worktree is not clean; refusing an unpinned oracle launch\n' >&2
    exit 2
fi
prime_rl_commit=$(git rev-parse --verify HEAD)
prime_rl_tree_sha256=$(printf '%s' "$prime_rl_status" | sha256sum | cut -d' ' -f1)
verifiers_commit=$(git -C deps/verifiers rev-parse --verify HEAD)
vmvm_tb_v2_sha256=$(sha256sum environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/*.py \
    | sha256sum | cut -d' ' -f1)
invocation_host=$(hostname)

mkdir -p "$output_dir" /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site${PYTHONPATH:+:$PYTHONPATH}"
export VACLI_LEASE_RETRIES="$vacli_lease_retries"
export VACLI_MAX_CONCURRENT_LEASES="$vacli_max_concurrent_leases"
export VACLI_MAX_PULL_RETRIES="$vacli_max_pull_retries"
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS="$vacli_image_pull_timeout_seconds"
export VACLI_CONTAINER_PRIVILEGED="$vacli_container_privileged"

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
    --oracle-solution-network-mode "$oracle_solution_network_mode"
    --minimum-pass-rate "${MINIMUM_PASS_RATE:-0.9}"
    --minimum-valid "${MINIMUM_VALID:-0}"
    --vacli-lease-retries "$vacli_lease_retries"
    --vacli-max-concurrent-leases "$vacli_max_concurrent_leases"
    --vacli-max-pull-retries "$vacli_max_pull_retries"
    --vacli-image-pull-timeout-seconds "$vacli_image_pull_timeout_seconds"
    --vacli-container-privileged "$vacli_container_privileged"
    --prime-rl-commit "$prime_rl_commit"
    --prime-rl-tree-sha256 "$prime_rl_tree_sha256"
    --verifiers-commit "$verifiers_commit"
    --vmvm-tb-v2-sha256 "$vmvm_tb_v2_sha256"
    --invocation-host "$invocation_host"
    --slurm-job-id "$SLURM_JOB_ID"
)
if [[ -n "$dataset_revision" ]]; then
    args+=(--dataset-revision "$dataset_revision")
else
    args+=(--dataset-archive "$dataset_archive" --dataset-archive-sha256 "$dataset_archive_sha256")
fi
if [[ -n "$task_file" ]]; then
    args+=(--task-file "$task_file" --task-file-sha256 "$task_file_sha256")
fi
if [[ -n "$image_manifest" ]]; then
    args+=(--image-manifest "$image_manifest" --image-manifest-sha256 "$image_manifest_sha256")
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
