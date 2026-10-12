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

project_dir_input=${PROJECT_DIR:?}
project_dir=$(/usr/bin/readlink -f -- "$project_dir_input")
canonical_wrapper="$project_dir/user/tianhaowu/terminal_bench_vmvm/run_source_wheel_proof_clean_env.sbatch"
canonical_launcher="$project_dir/user/tianhaowu/terminal_bench_vmvm/run_source_wheel_proof.sbatch"
executed_wrapper_input=${BASH_SOURCE[0]}
wrapper_sha=${SOURCE_WHEEL_PROOF_CLEAN_WRAPPER_SHA256:?}

if [[ "$executed_wrapper_input" != "$canonical_wrapper" \
    || "$(/usr/bin/readlink -f -- "$executed_wrapper_input")" != "$canonical_wrapper" \
    || -L "$canonical_wrapper" || -L "$canonical_launcher" \
    || ! -f "$canonical_wrapper" || ! -f "$canonical_launcher" ]]; then
    printf 'Clean wrapper must run from its canonical tracked path\n' >&2
    exit 2
fi
if [[ ! "$wrapper_sha" =~ ^[0-9a-f]{64}$ \
    || "$(/usr/bin/sha256sum "$canonical_wrapper" | /usr/bin/cut -d' ' -f1)" != "$wrapper_sha" ]]; then
    printf 'Pinned clean-wrapper digest mismatch\n' >&2
    exit 2
fi
if [[ "$(/usr/bin/uname -m)" != x86_64 || ! "${SLURM_JOB_ID:-}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'Clean wrapper requires an x86_64 Slurm allocation\n' >&2
    exit 2
fi
if [[ ! -r "${THRIFT_TLS_CL_CERT_PATH:-}" || ! -r "${THRIFT_TLS_CL_KEY_PATH:-}" ]]; then
    printf 'Clean wrapper requires readable trusted TLS inputs\n' >&2
    exit 2
fi

required=(
    PROJECT_DIR
    SOURCE_WHEEL_PROOF_INSPECTION_RECEIPT
    SOURCE_WHEEL_PROOF_INSPECTION_RECEIPT_SHA256
    SOURCE_WHEEL_PROOF_INPUT
    SOURCE_WHEEL_PROOF_INPUT_SHA256
    SOURCE_WHEEL_PROOF_OUTPUT_DIR
    SOURCE_WHEEL_PROOF_SOURCE_REVISION
    SOURCE_WHEEL_PROOF_BASE_RUNTIME_REVISION
    SOURCE_WHEEL_PROOF_EXPECTED_HOST
    SOURCE_WHEEL_PROOF_EXPECTED_ENTRY_COUNT
    SOURCE_WHEEL_PROOF_MISSING_EVIDENCE_SHA256
    SOURCE_WHEEL_PROOF_CLEAN_WRAPPER_SHA256
    SOURCE_WHEEL_PROOF_LAUNCHER_SHA256
    SOURCE_WHEEL_PROOF_UV_SHA256
    SOURCE_WHEEL_PROOF_PYTHON_SHA256
    SOURCE_WHEEL_PROOF_PYTHON_RUNTIME_MANIFEST_SHA256
    SOURCE_WHEEL_PROOF_SITE_PACKAGES_MANIFEST_SHA256
    SOURCE_WHEEL_PROOF_VMVM_TB_V2_SHA256
    SOURCE_WHEEL_PROOF_VACLI_BINARY_SHA256
    SOURCE_WHEEL_PROOF_MAX_CONCURRENT_ENTRIES
    PYTHON_BIN_X86_64
    PYTHON_STDLIB_X86_64
    PYTHON_SITE_X86_64
    UV_BIN_X86_64
    VACLI_BIN
    VACLI_LEASE_RETRIES
    VACLI_MAX_CONCURRENT_LEASES
    VACLI_MAX_PULL_RETRIES
    VACLI_IMAGE_PULL_TIMEOUT_SECONDS
    VACLI_CONTAINER_PRIVILEGED
    VMVM_TENANT_ID
    VMVM_LEASE_TTL
)
for variable in "${required[@]}"; do
    if [[ -z "${!variable:-}" ]]; then
        printf 'Clean wrapper is missing a required proof input\n' >&2
        exit 2
    fi
done
if [[ ! -r "$SOURCE_WHEEL_PROOF_INSPECTION_RECEIPT" ]]; then
    printf 'Clean wrapper requires the reviewed inspection receipt\n' >&2
    exit 2
fi
if [[ ! "$SOURCE_WHEEL_PROOF_EXPECTED_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$ \
    || "$(/usr/bin/uname -n)" != "$SOURCE_WHEEL_PROOF_EXPECTED_HOST" ]]; then
    printf 'Proof allocation does not match the inspected host\n' >&2
    exit 2
fi

clean_environment=(
    PATH=/usr/bin:/bin
    HOME=/storage/home/tianhaowu
    USER=tianhaowu
    LOGNAME=tianhaowu
    SLURM_JOB_ID="$SLURM_JOB_ID"
    THRIFT_TLS_CL_CERT_PATH="$THRIFT_TLS_CL_CERT_PATH"
    THRIFT_TLS_CL_KEY_PATH="$THRIFT_TLS_CL_KEY_PATH"
)
for variable in "${required[@]}"; do
    clean_environment+=("$variable=${!variable}")
done
for variable in SOURCE_WHEEL_PROOF_STATE_SHA256 SOURCE_WHEEL_PROOF_SESSION_TIMEOUT \
    SOURCE_WHEEL_PROOF_TUNNEL_READY_TIMEOUT SOURCE_WHEEL_PROOF_SSHD_READY_TIMEOUT \
    SOURCE_WHEEL_PROOF_MAX_SESSION_BUFFER_SIZE; do
    if [[ -n "${!variable:-}" ]]; then
        clean_environment+=("$variable=${!variable}")
    fi
done

exec /usr/bin/env -i "${clean_environment[@]}" /bin/bash "$canonical_launcher"
