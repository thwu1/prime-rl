#!/bin/bash
#SBATCH --job-name=trace-smoke-audit
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/trace_smoke_audit_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/trace_smoke_audit_%j.log

set -euo pipefail

if (( $# != 0 )); then
    printf 'Configure the smoke audit through environment variables, not positional arguments\n' >&2
    exit 2
fi

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
results_dir=${RESULTS_DIR:?Set RESULTS_DIR to the completed smoke snapshot}
task_file=${SMOKE_TASK_FILE:?Set SMOKE_TASK_FILE to the approved smoke task file}
task_file_sha256=${SMOKE_TASK_FILE_SHA256:?Set SMOKE_TASK_FILE_SHA256 to its approved digest}
expected_traces=${SMOKE_EXPECTED_TRACES:-2}
required_rollout_concurrency=${SMOKE_REQUIRED_ROLLOUT_CONCURRENCY:-}
required_lease_start_concurrency=${SMOKE_REQUIRED_LEASE_START_CONCURRENCY:-}

if [[ ! -x "$x86_uv" ]]; then
    printf 'Missing x86_64 uv binary: %s\n' "$x86_uv" >&2
    exit 2
fi
if [[ "$(uname -m)" != x86_64 || ! -d "$x86_site/pydantic" ]]; then
    printf 'Missing x86_64 Python runtime/dependencies\n' >&2
    exit 2
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site${PYTHONPATH:+:$PYTHONPATH}"

if [[ ( -n "$required_rollout_concurrency" && -z "$required_lease_start_concurrency" ) \
    || ( -z "$required_rollout_concurrency" && -n "$required_lease_start_concurrency" ) ]]; then
    printf 'Both observed-concurrency requirements must be supplied together\n' >&2
    exit 2
fi

args=(
    "$results_dir"
    --expected-task-file "$task_file"
    --expected-task-file-sha256 "$task_file_sha256"
    --expected-traces "$expected_traces"
)
if [[ -n "$required_rollout_concurrency" ]]; then
    args+=(
        --required-rollout-concurrency "$required_rollout_concurrency"
        --required-lease-start-concurrency "$required_lease_start_concurrency"
    )
fi

exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/certify_trace_smoke.py" "${args[@]}"
