#!/bin/bash
#SBATCH --job-name=tb-wheel-proof
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=12:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=6
#SBATCH --mem=12G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/source_wheel_proof_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/source_wheel_proof_%j.log

set -euo pipefail
umask 077

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
discovery_input=${SOURCE_WHEEL_PROOF_INPUT:-}
discovery_input_sha256=${SOURCE_WHEEL_PROOF_INPUT_SHA256:-}
output_dir=${SOURCE_WHEEL_PROOF_OUTPUT_DIR:-}
expected_source_revision=${SOURCE_WHEEL_PROOF_SOURCE_REVISION:-}
base_runtime_revision=${SOURCE_WHEEL_PROOF_BASE_RUNTIME_REVISION:-}
resume_state_sha256=${SOURCE_WHEEL_PROOF_STATE_SHA256:-}
max_concurrent_entries=${SOURCE_WHEEL_PROOF_MAX_CONCURRENT_ENTRIES:-2}
python_bin=${PYTHON_BIN_X86_64:-python3}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
vacli_bin_input=${VACLI_BIN:-/public/fbpkgs/x86_64/vacli/stable/vacli}
vacli_lease_retries=${VACLI_LEASE_RETRIES:-20}
vacli_max_concurrent_leases=${VACLI_MAX_CONCURRENT_LEASES:-6}
vacli_max_pull_retries=${VACLI_MAX_PULL_RETRIES:-20}
vacli_image_pull_timeout_seconds=${VACLI_IMAGE_PULL_TIMEOUT_SECONDS:-3600}
vacli_container_privileged=${VACLI_CONTAINER_PRIVILEGED:-1}

if [[ -z "$discovery_input" || -z "$discovery_input_sha256" || -z "$output_dir" \
    || -z "$expected_source_revision" ]]; then
    printf 'Proof input, output, and source-revision bindings are required\n' >&2
    exit 2
fi
if [[ -z "$base_runtime_revision" \
    || "$base_runtime_revision" != ceb9356c98c72e51568e7bb4658a540cb1492254 ]]; then
    printf 'SOURCE_WHEEL_PROOF_BASE_RUNTIME_REVISION must select the approved runtime base\n' >&2
    exit 2
fi
if [[ ! "$discovery_input_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'SOURCE_WHEEL_PROOF_INPUT_SHA256 must be a lowercase SHA-256\n' >&2
    exit 2
fi
if [[ ! "$expected_source_revision" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'SOURCE_WHEEL_PROOF_SOURCE_REVISION must be a full lowercase Git revision\n' >&2
    exit 2
fi
if [[ -n "$resume_state_sha256" && ! "$resume_state_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'SOURCE_WHEEL_PROOF_STATE_SHA256 must be a lowercase SHA-256\n' >&2
    exit 2
fi
if [[ ! "$max_concurrent_entries" =~ ^[1-3]$ ]]; then
    printf 'SOURCE_WHEEL_PROOF_MAX_CONCURRENT_ENTRIES must be between 1 and 3\n' >&2
    exit 2
fi
if [[ ! "$vacli_lease_retries" =~ ^(0|[1-9][0-9]*)$ \
    || ! "$vacli_max_pull_retries" =~ ^(0|[1-9][0-9]*)$ \
    || ! "$vacli_max_concurrent_leases" =~ ^[1-9][0-9]*$ \
    || ! "$vacli_image_pull_timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
    printf 'VACLI retry, concurrency, and pull-timeout controls must be canonical integers\n' >&2
    exit 2
fi
if (( vacli_max_concurrent_leases > max_concurrent_entries * 3 )); then
    printf 'VACLI_MAX_CONCURRENT_LEASES exceeds the proof live-runtime cap\n' >&2
    exit 2
fi
if [[ "$vacli_container_privileged" != 0 && "$vacli_container_privileged" != 1 ]]; then
    printf 'VACLI_CONTAINER_PRIVILEGED must be 0 or 1\n' >&2
    exit 2
fi
if [[ "$(uname -m)" != x86_64 ]]; then
    printf 'Source-wheel proof requires an x86_64 CPU node\n' >&2
    exit 2
fi
vacli_bin=$(readlink -f -- "$vacli_bin_input")
if [[ ! -x "$x86_uv" || ! -d "$x86_site/pydantic" || ! -x "$vacli_bin" ]]; then
    printf 'Missing staged x86_64 Python runtime\n' >&2
    exit 2
fi

cd "$project_dir"
source_status=$(git status --porcelain=v1 --untracked-files=all)
if [[ -n "$source_status" ]]; then
    printf 'Source worktree must be clean before proof\n' >&2
    exit 2
fi
for dependency in deps/verifiers deps/renderers deps/pydantic-config; do
    if [[ ! -f "$dependency/.git" ]]; then
        printf 'Required source dependency is not initialized\n' >&2
        exit 2
    fi
    expected_dependency_commit=$(git ls-tree HEAD "$dependency" | awk '{print $3}')
    observed_dependency_commit=$(git -C "$dependency" rev-parse --verify HEAD)
    dependency_status=$(git -C "$dependency" status --porcelain=v1 --untracked-files=all)
    if [[ -z "$expected_dependency_commit" \
        || "$observed_dependency_commit" != "$expected_dependency_commit" \
        || -n "$dependency_status" ]]; then
        printf 'Required source dependency is not at its clean gitlink\n' >&2
        exit 2
    fi
done
source_commit=$(git rev-parse --verify HEAD)
if [[ "$source_commit" != "$expected_source_revision" ]]; then
    printf 'Proof source revision does not match the approved revision\n' >&2
    exit 2
fi
if ! git merge-base --is-ancestor "$base_runtime_revision" "$source_commit"; then
    printf 'Approved runtime base is not an ancestor of the proof utility revision\n' >&2
    exit 2
fi
source_git_tree=$(git rev-parse --verify 'HEAD^{tree}')
source_tree_sha256=$(printf '%s' "$source_status" | sha256sum | cut -d' ' -f1)
verifiers_commit=$(git -C deps/verifiers rev-parse --verify HEAD)
renderers_commit=$(git -C deps/renderers rev-parse --verify HEAD)
pydantic_config_commit=$(git -C deps/pydantic-config rev-parse --verify HEAD)
vmvm_tb_v2_sha256=$(sha256sum environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/*.py \
    | sha256sum | cut -d' ' -f1)
vacli_binary_sha256=$(sha256sum "$vacli_bin" | cut -d' ' -f1)
invocation_host=$(hostname)

mkdir -p /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs

export PYTHONDONTWRITEBYTECODE=1
export VACLI_BIN="$vacli_bin"
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site${PYTHONPATH:+:$PYTHONPATH}"
export VACLI_LEASE_RETRIES="$vacli_lease_retries"
export VACLI_MAX_CONCURRENT_LEASES="$vacli_max_concurrent_leases"
export VACLI_MAX_PULL_RETRIES="$vacli_max_pull_retries"
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS="$vacli_image_pull_timeout_seconds"
export VACLI_CONTAINER_PRIVILEGED="$vacli_container_privileged"

args=(
    --discovery-input "$discovery_input"
    --discovery-input-sha256 "$discovery_input_sha256"
    --output-dir "$output_dir"
    --max-concurrent-entries "$max_concurrent_entries"
    --session-timeout "${SOURCE_WHEEL_PROOF_SESSION_TIMEOUT:-10800}"
    --tunnel-ready-timeout "${SOURCE_WHEEL_PROOF_TUNNEL_READY_TIMEOUT:-120}"
    --sshd-ready-timeout "${SOURCE_WHEEL_PROOF_SSHD_READY_TIMEOUT:-180}"
    --max-session-buffer-size "${SOURCE_WHEEL_PROOF_MAX_SESSION_BUFFER_SIZE:-67108864}"
    --tenant-id "${VMVM_TENANT_ID:-async_2347641}"
    --lease-ttl "${VMVM_LEASE_TTL:-60s}"
    --vacli-lease-retries "$vacli_lease_retries"
    --vacli-max-concurrent-leases "$vacli_max_concurrent_leases"
    --vacli-max-pull-retries "$vacli_max_pull_retries"
    --vacli-image-pull-timeout-seconds "$vacli_image_pull_timeout_seconds"
    --vacli-container-privileged "$vacli_container_privileged"
    --source-commit "$source_commit"
    --base-runtime-commit "$base_runtime_revision"
    --source-git-tree "$source_git_tree"
    --source-tree-sha256 "$source_tree_sha256"
    --verifiers-commit "$verifiers_commit"
    --renderers-commit "$renderers_commit"
    --pydantic-config-commit "$pydantic_config_commit"
    --vmvm-tb-v2-sha256 "$vmvm_tb_v2_sha256"
    --vacli-binary-sha256 "$vacli_binary_sha256"
    --invocation-host "$invocation_host"
    --slurm-job-id "$SLURM_JOB_ID"
)
if [[ -n "$resume_state_sha256" ]]; then
    args+=(--resume-state-sha256 "$resume_state_sha256")
fi

exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/prove_source_wheel_policy.py" "${args[@]}"
