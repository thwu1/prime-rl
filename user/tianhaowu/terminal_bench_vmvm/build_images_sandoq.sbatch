#!/bin/bash
#SBATCH --job-name=tb-sandoq-build
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=12:00:00
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/sandoq_build_%A_%a.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/sandoq_build_%A_%a.log

set -euo pipefail
umask 077
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
plan=${1:?usage: sbatch build_images_sandoq.sbatch BUILD_PLAN.tsv}
dataset_dir=${DATASET_DIR:?Set DATASET_DIR}
status_root=${BUILD_STATUS_ROOT:?Set BUILD_STATUS_ROOT}
token_file=${SANDOQ_BUILD_TOKEN_FILE:-/storage/home/tianhaowu/.config/oci-runner/firecracker-token}
ecr_push_token_file=${ECR_PUSH_TOKEN_FILE:-/storage/home/tianhaowu/.config/oci-runner/ecr-dev-token}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_ram_prime_f7313db4}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}

[[ "$(uname -m)" == x86_64 && -d "$sandoq_site/sandoq_client" && -x "$x86_uv" ]] \
    || { printf 'Pinned x86 Sandoq runtime is unavailable\n' >&2; exit 2; }
for secret in "$token_file" "$ecr_push_token_file"; do
    [[ -f "$secret" && ! -L "$secret" && "$(stat -c '%a:%u:%h' -- "$secret")" == "600:$(id -u):1" ]] \
        || { printf 'A required private token file is unavailable or unsafe\n' >&2; exit 2; }
done

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$project_dir/extensions/sandoq:$sandoq_site:$x86_site"
exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/build_images_sandoq.py" \
    --plan "$plan" --dataset-dir "$dataset_dir" --status-root "$status_root" \
    --token-file "$token_file" --ecr-push-token-file "$ecr_push_token_file" \
    --array-index "${SLURM_ARRAY_TASK_ID:-0}" --array-count "${SLURM_ARRAY_TASK_COUNT:-1}" \
    --build-timeout "${BUILD_TIMEOUT_SECONDS:-7200}"
