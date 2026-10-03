#!/bin/bash
#SBATCH --job-name=qwen-epoch3-sft-finalize
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=12:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_epoch3_sft_finalize_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_epoch3_sft_finalize_%j.log

set -euo pipefail
umask 077

fail() {
    printf '{"code":"%s","status":"error"}\n' "$1" >&2
    exit 2
}

if (( $# != 0 )); then
    fail arguments_forbidden
fi

required=(
    FINALIZER_PROJECT_DIR
    FINALIZER_EXPECTED_REVISION
    FINALIZER_SOURCE_ROOT
    FINALIZER_SOURCE_DIR
    FINALIZER_EXPECTED_PROVENANCE_SHA256
    FINALIZER_OUTPUT_ROOT
    FINALIZER_OUTPUT_DIR
    FINALIZER_EXPECTED_COUNT
    FINALIZER_SELECTION
    FINALIZER_VALIDATION_PERMYRIAD
    FINALIZER_SPLIT_SALT
)
for variable in "${required[@]}"; do
    if [[ -z ${!variable:-} ]]; then
        fail required_environment_missing
    fi
done

if [[ $(uname -m) != x86_64 ]]; then
    fail x86_64_required
fi
if [[ ! $FINALIZER_EXPECTED_REVISION =~ ^[0-9a-f]{40}$ ]]; then
    fail project_revision_invalid
fi
if [[ ! $FINALIZER_EXPECTED_PROVENANCE_SHA256 =~ ^[0-9a-f]{64}$ ]]; then
    fail expected_provenance_digest_invalid
fi
if [[ ! $FINALIZER_EXPECTED_COUNT =~ ^[1-9][0-9]*$ ]]; then
    fail expected_count_invalid
fi
if [[ $FINALIZER_SELECTION != pass-only && $FINALIZER_SELECTION != all-outcomes ]]; then
    fail selection_invalid
fi
if [[ ! $FINALIZER_VALIDATION_PERMYRIAD =~ ^[0-9]+$ ]] \
    || (( FINALIZER_VALIDATION_PERMYRIAD >= 10000 )); then
    fail validation_permyriad_invalid
fi

project_dir=$FINALIZER_PROJECT_DIR
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
python_bin=${PYTHON_BIN_X86_64:-python3}

if [[ ! -x $x86_uv || ! -d $x86_site/pydantic || ! -f $workflow_dir/finalize_qwen_sft.py ]]; then
    fail x86_runtime_unavailable
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

cd "$project_dir"
exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/finalize_qwen_sft.py" \
    --project-dir "$project_dir" \
    --expected-project-revision "$FINALIZER_EXPECTED_REVISION" \
    --source-root "$FINALIZER_SOURCE_ROOT" \
    --source-dir "$FINALIZER_SOURCE_DIR" \
    --expected-provenance-sha256 "$FINALIZER_EXPECTED_PROVENANCE_SHA256" \
    --output-root "$FINALIZER_OUTPUT_ROOT" \
    --output-dir "$FINALIZER_OUTPUT_DIR" \
    --expected-count "$FINALIZER_EXPECTED_COUNT" \
    --selection "$FINALIZER_SELECTION" \
    --validation-permyriad "$FINALIZER_VALIDATION_PERMYRIAD" \
    --split-salt "$FINALIZER_SPLIT_SALT"
