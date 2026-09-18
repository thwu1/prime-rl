#!/bin/bash
#SBATCH --job-name=qwen-repair-chain
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=3-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_repair_chain_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_repair_chain_%j.log

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
    QWEN_CHAIN_PROJECT_DIR
    QWEN_CHAIN_EXPECTED_REVISION
    QWEN_CHAIN_SOURCE_ROOT
    QWEN_CHAIN_SOURCE_DIR
    QWEN_CHAIN_APPROVED_TASK_FILE_SHA256
    QWEN_CHAIN_EXPECTED_PROVENANCE_SHA256
    QWEN_CHAIN_RUNTIME_ROOT
    QWEN_CHAIN_RUNTIME_DIR
    QWEN_CHAIN_OUTPUT_ROOT
    QWEN_CHAIN_ORIGINAL_EXPORT_DIR
    QWEN_CHAIN_REPAIR_EXPORT_DIR
    QWEN_CHAIN_MERGED_OUTPUT_DIR
    QWEN_CHAIN_VALIDATION_PERMYRIAD
    QWEN_CHAIN_SPLIT_SALT
)
for variable in "${required[@]}"; do
    if [[ -z ${!variable:-} ]]; then
        fail required_environment_missing
    fi
done

if [[ $(uname -m) != x86_64 ]]; then
    fail x86_64_required
fi
if [[ ! ${SLURM_JOB_ID:-} =~ ^[1-9][0-9]*$ ]]; then
    fail slurm_allocation_required
fi
if [[ ! $QWEN_CHAIN_EXPECTED_REVISION =~ ^[0-9a-f]{40}$ ]]; then
    fail project_revision_invalid
fi
if [[ ! $QWEN_CHAIN_APPROVED_TASK_FILE_SHA256 =~ ^[0-9a-f]{64}$ ]] \
    || [[ ! $QWEN_CHAIN_EXPECTED_PROVENANCE_SHA256 =~ ^[0-9a-f]{64}$ ]]; then
    fail expected_digest_invalid
fi
if [[ ! $QWEN_CHAIN_VALIDATION_PERMYRIAD =~ ^[0-9]+$ ]] \
    || (( QWEN_CHAIN_VALIDATION_PERMYRIAD >= 10000 )); then
    fail validation_permyriad_invalid
fi

project_dir=$QWEN_CHAIN_PROJECT_DIR
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
python_bin=${PYTHON_BIN_X86_64:-python3}
if [[ ! -x $x86_uv || ! -d $x86_site/pydantic || ! -f $workflow_dir/qwen_repair_chain.py ]]; then
    fail x86_runtime_unavailable
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site"
cd "$project_dir"
exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/qwen_repair_chain.py" \
    --project-dir "$project_dir" \
    --expected-project-revision "$QWEN_CHAIN_EXPECTED_REVISION" \
    --source-root "$QWEN_CHAIN_SOURCE_ROOT" \
    --source-dir "$QWEN_CHAIN_SOURCE_DIR" \
    --approved-task-file-sha256 "$QWEN_CHAIN_APPROVED_TASK_FILE_SHA256" \
    --expected-provenance-sha256 "$QWEN_CHAIN_EXPECTED_PROVENANCE_SHA256" \
    --runtime-root "$QWEN_CHAIN_RUNTIME_ROOT" \
    --runtime-dir "$QWEN_CHAIN_RUNTIME_DIR" \
    --output-root "$QWEN_CHAIN_OUTPUT_ROOT" \
    --original-export-dir "$QWEN_CHAIN_ORIGINAL_EXPORT_DIR" \
    --repair-export-dir "$QWEN_CHAIN_REPAIR_EXPORT_DIR" \
    --merged-output-dir "$QWEN_CHAIN_MERGED_OUTPUT_DIR" \
    --validation-permyriad "$QWEN_CHAIN_VALIDATION_PERMYRIAD" \
    --split-salt "$QWEN_CHAIN_SPLIT_SALT"
