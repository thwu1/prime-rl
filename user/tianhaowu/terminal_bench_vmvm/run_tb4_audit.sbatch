#!/bin/bash
#SBATCH --job-name=tb4-audit
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/tb4_audit_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/tb4_audit_%j.log

set -euo pipefail

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
results_dir=${RESULTS_DIR:?Set RESULTS_DIR to the completed TB4 snapshot}
min_rate=0.04
max_rate=0.22
max_sequence_tokens=262144
expected_rollout_concurrency=${TB4_EXPECTED_ROLLOUT_CONCURRENCY:-4}
expected_lease_start_concurrency=${TB4_EXPECTED_LEASE_START_CONCURRENCY:-2}
results="$results_dir/results.jsonl"
checkpoint="$results_dir/checkpoint.json"

if [[ ! -s "$results" ]]; then
    printf 'Missing or empty TB4 results: %s\n' "$results" >&2
    exit 2
fi
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

args=(
    "$workflow_dir/audit_tb4_results.py"
    "$results"
    --certificate "$checkpoint"
    --min-supported-pass-rate "$min_rate"
    --max-supported-pass-rate "$max_rate"
    --max-sequence-tokens "$max_sequence_tokens"
    --expected-rollout-concurrency "$expected_rollout_concurrency"
    --expected-lease-start-concurrency "$expected_lease_start_concurrency"
)

"$x86_uv" run --no-project --offline --python "$python_bin" python3 "${args[@]}"
printf 'Published strict TB4 checkpoint: %s\n' "$checkpoint"
printf 'Use checkpoint_file_sha256 above for EVAL_TB4_CERTIFICATE_SHA256; tb4_certificate_sha256 is the internal body digest.\n'
