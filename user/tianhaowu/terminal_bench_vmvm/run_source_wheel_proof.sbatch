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

if [[ ${PATH:-} != /usr/bin:/bin || -n ${BASH_ENV+x} || -n ${ENV+x} \
    || -n ${LD_PRELOAD:-} || -n ${LD_LIBRARY_PATH:-} \
    || -n ${VIRTUAL_ENV:-} || -n ${CONDA_PREFIX:-} ]]; then
    printf 'Launcher requires the documented clean submission environment\n' >&2
    exit 2
fi
if declare -F | /usr/bin/grep -q .; then
    printf 'Exported shell functions are forbidden\n' >&2
    exit 2
fi
for variable in ${!LD_@}; do
    printf 'Inherited dynamic-loader environment is forbidden\n' >&2
    exit 2
done
for variable in ${!PYTHON@}; do
    case "$variable" in
        PYTHON_BIN_X86_64 | PYTHON_SITE_X86_64 | PYTHON_STDLIB_X86_64) ;;
        *)
            printf 'Inherited Python environment is forbidden\n' >&2
            exit 2
            ;;
    esac
done
for variable in ${!UV_@}; do
    if [[ "$variable" != UV_BIN_X86_64 ]]; then
        printf 'Inherited uv environment is forbidden\n' >&2
        exit 2
    fi
done

project_dir_input=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
project_dir=$(/usr/bin/readlink -f -- "$project_dir_input")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
inspection_receipt_input=${SOURCE_WHEEL_PROOF_INSPECTION_RECEIPT:-}
inspection_receipt_sha256=${SOURCE_WHEEL_PROOF_INSPECTION_RECEIPT_SHA256:-}
discovery_input=${SOURCE_WHEEL_PROOF_INPUT:-}
discovery_input_sha256=${SOURCE_WHEEL_PROOF_INPUT_SHA256:-}
output_dir=${SOURCE_WHEEL_PROOF_OUTPUT_DIR:-}
expected_source_revision=${SOURCE_WHEEL_PROOF_SOURCE_REVISION:-}
base_runtime_revision=${SOURCE_WHEEL_PROOF_BASE_RUNTIME_REVISION:-}
expected_host=${SOURCE_WHEEL_PROOF_EXPECTED_HOST:-}
resume_state_sha256=${SOURCE_WHEEL_PROOF_STATE_SHA256:-}
slurm_job_id=${SLURM_JOB_ID:-}
expected_entry_count=${SOURCE_WHEEL_PROOF_EXPECTED_ENTRY_COUNT:-}
expected_missing_evidence_sha256=${SOURCE_WHEEL_PROOF_MISSING_EVIDENCE_SHA256:-}
clean_wrapper_sha256=${SOURCE_WHEEL_PROOF_CLEAN_WRAPPER_SHA256:-}
launcher_sha256=${SOURCE_WHEEL_PROOF_LAUNCHER_SHA256:-}
uv_sha256=${SOURCE_WHEEL_PROOF_UV_SHA256:-}
python_sha256=${SOURCE_WHEEL_PROOF_PYTHON_SHA256:-}
python_runtime_manifest_sha256=${SOURCE_WHEEL_PROOF_PYTHON_RUNTIME_MANIFEST_SHA256:-}
site_packages_manifest_sha256=${SOURCE_WHEEL_PROOF_SITE_PACKAGES_MANIFEST_SHA256:-}
vmvm_tb_v2_sha256=${SOURCE_WHEEL_PROOF_VMVM_TB_V2_SHA256:-}
vacli_binary_sha256=${SOURCE_WHEEL_PROOF_VACLI_BINARY_SHA256:-}
max_concurrent_entries=${SOURCE_WHEEL_PROOF_MAX_CONCURRENT_ENTRIES:-2}
python_bin_input=${PYTHON_BIN_X86_64:-/usr/bin/python3}
python_stdlib_input=${PYTHON_STDLIB_X86_64:-}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
vacli_bin_input=${VACLI_BIN:-/public/fbpkgs/x86_64/vacli/stable/vacli}
vacli_lease_retries=${VACLI_LEASE_RETRIES:-1}
vacli_max_concurrent_leases=${VACLI_MAX_CONCURRENT_LEASES:-6}
vacli_max_pull_retries=${VACLI_MAX_PULL_RETRIES:-20}
vacli_image_pull_timeout_seconds=${VACLI_IMAGE_PULL_TIMEOUT_SECONDS:-3600}
vacli_container_privileged=${VACLI_CONTAINER_PRIVILEGED:-1}

for variable in ${!PYTHON@}; do
    unset "$variable"
done
for variable in ${!UV_@}; do
    unset "$variable"
done
unset VIRTUAL_ENV CONDA_PREFIX LD_PRELOAD LD_LIBRARY_PATH CDPATH \
    GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
export PATH=/usr/bin:/bin
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONSAFEPATH=1

if [[ -z "$inspection_receipt_input" || -z "$inspection_receipt_sha256" \
    || -z "$discovery_input" || -z "$discovery_input_sha256" || -z "$output_dir" \
    || -z "$expected_source_revision" || -z "$expected_host" \
    || -z "$expected_missing_evidence_sha256" \
    || -z "$clean_wrapper_sha256" || -z "$launcher_sha256" \
    || -z "$uv_sha256" || -z "$python_sha256" \
    || -z "$python_runtime_manifest_sha256" || -z "$site_packages_manifest_sha256" \
    || -z "$vmvm_tb_v2_sha256" || -z "$vacli_binary_sha256" \
    || -z "$python_stdlib_input" ]]; then
    printf 'Proof input, output, and source-revision bindings are required\n' >&2
    exit 2
fi
if [[ "$expected_entry_count" != 8 ]]; then
    printf 'SOURCE_WHEEL_PROOF_EXPECTED_ENTRY_COUNT must be exactly 8\n' >&2
    exit 2
fi
if [[ ! "$slurm_job_id" =~ ^[1-9][0-9]*$ ]]; then
    printf 'A canonical Slurm job ID is required\n' >&2
    exit 2
fi
if [[ -z "$base_runtime_revision" \
    || "$base_runtime_revision" != ceb9356c98c72e51568e7bb4658a540cb1492254 ]]; then
    printf 'SOURCE_WHEEL_PROOF_BASE_RUNTIME_REVISION must select the approved runtime base\n' >&2
    exit 2
fi
for digest in "$inspection_receipt_sha256" "$discovery_input_sha256" "$expected_missing_evidence_sha256" \
    "$clean_wrapper_sha256" "$launcher_sha256" "$uv_sha256" "$python_sha256" \
    "$python_runtime_manifest_sha256" "$site_packages_manifest_sha256" \
    "$vmvm_tb_v2_sha256" "$vacli_binary_sha256"; do
    if [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'Every proof digest binding must be a lowercase SHA-256\n' >&2
        exit 2
    fi
done
if [[ ! "$expected_source_revision" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'SOURCE_WHEEL_PROOF_SOURCE_REVISION must be a full lowercase Git revision\n' >&2
    exit 2
fi
if [[ ! "$expected_host" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$ ]]; then
    printf 'SOURCE_WHEEL_PROOF_EXPECTED_HOST must be the exact inspected host\n' >&2
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
if [[ "$vacli_lease_retries" != 1 \
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
canonical_launcher="$workflow_dir/run_source_wheel_proof.sbatch"
clean_wrapper="$workflow_dir/run_source_wheel_proof_clean_env.sbatch"
inspection_receipt=$(/usr/bin/readlink -f -- "$inspection_receipt_input")
executed_launcher_input=${BASH_SOURCE[0]}
if [[ "$executed_launcher_input" != "$canonical_launcher" ]]; then
    printf 'Launcher must be executed from the canonical tracked path\n' >&2
    exit 2
fi
executed_launcher=$(readlink -f -- "$executed_launcher_input")
if [[ "$executed_launcher" != "$canonical_launcher" || -L "$canonical_launcher" ]]; then
    printf 'Launcher must be a non-symlinked canonical tracked file\n' >&2
    exit 2
fi
x86_uv=$(readlink -f -- "$x86_uv")
python_bin=$(readlink -f -- "$python_bin_input")
python_stdlib=$(readlink -f -- "$python_stdlib_input")
x86_site=$(readlink -f -- "$x86_site")
vacli_bin=$(readlink -f -- "$vacli_bin_input")
if [[ "$inspection_receipt" != "$inspection_receipt_input" \
    || ! -f "$inspection_receipt" || -L "$inspection_receipt" \
    || ! -f "$clean_wrapper" || -L "$clean_wrapper" \
    || ! -f "$canonical_launcher" || ! -f "$executed_launcher" || ! -x "$x86_uv" \
    || ! -x "$python_bin" || ! -d "$python_stdlib" \
    || ! -d "$x86_site/pydantic" || ! -x "$vacli_bin" ]]; then
    printf 'Missing staged x86_64 Python runtime\n' >&2
    exit 2
fi
if [[ "$(sha256sum "$inspection_receipt" | cut -d' ' -f1)" != "$inspection_receipt_sha256" \
    || "$(sha256sum "$clean_wrapper" | cut -d' ' -f1)" != "$clean_wrapper_sha256" \
    || "$(sha256sum "$canonical_launcher" | cut -d' ' -f1)" != "$launcher_sha256" \
    || "$(sha256sum "$executed_launcher" | cut -d' ' -f1)" != "$launcher_sha256" \
    || "$(sha256sum "$x86_uv" | cut -d' ' -f1)" != "$uv_sha256" \
    || "$(sha256sum "$python_bin" | cut -d' ' -f1)" != "$python_sha256" \
    || "$(sha256sum "$vacli_bin" | cut -d' ' -f1)" != "$vacli_binary_sha256" ]]; then
    printf 'Pinned execution tool digest mismatch\n' >&2
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
invocation_host=$(/usr/bin/uname -n)
if [[ "$invocation_host" != "$expected_host" ]]; then
    printf 'Proof allocation does not match the inspected host\n' >&2
    exit 2
fi

mkdir -p /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs

export VACLI_BIN="$vacli_bin"
export VACLI_LEASE_RETRIES="$vacli_lease_retries"
export VACLI_MAX_CONCURRENT_LEASES="$vacli_max_concurrent_leases"
export VACLI_MAX_PULL_RETRIES="$vacli_max_pull_retries"
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS="$vacli_image_pull_timeout_seconds"
export VACLI_CONTAINER_PRIVILEGED="$vacli_container_privileged"

args=(
    --discovery-input "$discovery_input"
    --discovery-input-sha256 "$discovery_input_sha256"
    --expected-entry-count "$expected_entry_count"
    --expected-missing-evidence-sha256 "$expected_missing_evidence_sha256"
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
    --project-dir "$project_dir"
    --inspection-receipt-path "$inspection_receipt"
    --clean-wrapper-path "$clean_wrapper"
    --canonical-launcher-path "$canonical_launcher"
    --executed-launcher-path "$executed_launcher"
    --uv-path "$x86_uv"
    --python-path "$python_bin"
    --python-stdlib-path "$python_stdlib"
    --site-packages-path "$x86_site"
    --vacli-path "$vacli_bin"
    --inspection-receipt-sha256 "$inspection_receipt_sha256"
    --clean-wrapper-sha256 "$clean_wrapper_sha256"
    --launcher-sha256 "$launcher_sha256"
    --uv-sha256 "$uv_sha256"
    --python-sha256 "$python_sha256"
    --python-runtime-manifest-sha256 "$python_runtime_manifest_sha256"
    --site-packages-manifest-sha256 "$site_packages_manifest_sha256"
    --source-commit "$source_commit"
    --base-runtime-commit "$base_runtime_revision"
    --source-git-tree "$source_git_tree"
    --source-tree-sha256 "$source_tree_sha256"
    --verifiers-commit "$verifiers_commit"
    --renderers-commit "$renderers_commit"
    --pydantic-config-commit "$pydantic_config_commit"
    --vmvm-tb-v2-sha256 "$vmvm_tb_v2_sha256"
    --vacli-binary-sha256 "$vacli_binary_sha256"
    --expected-host "$expected_host"
    --invocation-host "$invocation_host"
    --slurm-job-id "$slurm_job_id"
)
if [[ -n "$resume_state_sha256" ]]; then
    args+=(--resume-state-sha256 "$resume_state_sha256")
fi

bootstrap_args=(
    --project-dir "$project_dir"
    --inspection-receipt-path "$inspection_receipt"
    --clean-wrapper-path "$clean_wrapper"
    --canonical-launcher-path "$canonical_launcher"
    --executed-launcher-path "$executed_launcher"
    --uv-path "$x86_uv"
    --python-path "$python_bin"
    --python-stdlib-path "$python_stdlib"
    --site-packages-path "$x86_site"
    --vacli-path "$vacli_bin"
    --inspection-receipt-sha256 "$inspection_receipt_sha256"
    --clean-wrapper-sha256 "$clean_wrapper_sha256"
    --launcher-sha256 "$launcher_sha256"
    --uv-sha256 "$uv_sha256"
    --python-sha256 "$python_sha256"
    --python-runtime-manifest-sha256 "$python_runtime_manifest_sha256"
    --site-packages-manifest-sha256 "$site_packages_manifest_sha256"
    --base-runtime-commit "$base_runtime_revision"
    --source-commit "$source_commit"
    --source-git-tree "$source_git_tree"
    --source-tree-sha256 "$source_tree_sha256"
    --verifiers-commit "$verifiers_commit"
    --renderers-commit "$renderers_commit"
    --pydantic-config-commit "$pydantic_config_commit"
    --vmvm-tb-v2-sha256 "$vmvm_tb_v2_sha256"
    --vacli-binary-sha256 "$vacli_binary_sha256"
    --expected-host "$expected_host"
    --main-script "$workflow_dir/prove_source_wheel_policy.py"
)

exec "$python_bin" -I -S -B "$workflow_dir/source_wheel_proof_bootstrap.py" run \
    "${bootstrap_args[@]}" -- "${args[@]}"
