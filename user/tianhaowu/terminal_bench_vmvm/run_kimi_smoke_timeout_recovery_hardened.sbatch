#!/usr/bin/bash
#SBATCH --job-name=k3-smoke-recovery-unarmed
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue

set -euo pipefail
umask 077

abort() {
    /usr/bin/printf '%s\n' 'Kimi smoke recovery job failed closed' >&2
    exit 2
}

(( $# == 0 )) || abort
[[ ${SLURM_JOB_ID:-} =~ ^[1-9][0-9]{0,19}$ ]] || abort
[[ ${SLURM_JOB_NAME:-} == "${RECOVERY_EXPECTED_JOB_NAME:-}" ]] || abort
[[ ${KIMI_SMOKE_RECOVERY_MODE:-} == fresh-two ]] || abort
[[ ! ${RESUME_DIR+x} && ! ${KIMI_SMOKE_RECOVERY_SELECTION+x} \
    && ! ${KIMI_SMOKE_COMPOSITE_OUTPUT_DIR+x} ]] || abort

for variable in BASH_ENV ENV GIT_DIR GIT_WORK_TREE LD_PRELOAD LD_LIBRARY_PATH \
    PYTHONHOME PYTHONPATH PYTHONSTARTUP; do
    [[ ! ${!variable+x} ]] || abort
done

required=(
    HOME LANG LC_ALL LOGNAME PATH USER PYTHONDONTWRITEBYTECODE PYTHONNOUSERSITE
    PYTHONSAFEPATH UV_NO_CONFIG PROJECT_DIR EVAL_EXPECTED_PRIME_RL_REVISION
    EVAL_EXPECTED_MODEL EVAL_DEPLOYMENT_ID EVAL_DATASET_ARCHIVE
    EVAL_DATASET_ARCHIVE_SHA256 EVAL_DATASET_CONTENT_SHA256
    INFERENCE_DEPLOYMENT_SPEC INFERENCE_DEPLOYMENT_SPEC_SHA256
    INFERENCE_READINESS_CHECKPOINT INFERENCE_READINESS_CHECKPOINT_SHA256
    INFERENCE_PROXY_INFO INFERENCE_PROXY_INFO_SHA256 OUTPUT_DIR
    KIMI_SMOKE_RECOVERY_MODE VACLI_BIN VACLI_LEASE_RETRIES
    VACLI_MAX_CONCURRENT_LEASES VACLI_MAX_PULL_RETRIES
    VACLI_IMAGE_PULL_TIMEOUT_SECONDS VACLI_CONTAINER_PRIVILEGED
    PYTHON_BIN_X86_64 PYTHON_BIN_X86_64_SHA256 PYTHON_SITE_X86_64
    UV_BIN_X86_64 UV_BIN_X86_64_SHA256 VACLI_BIN_SHA256
    RECOVERY_RUNTIME_MANIFEST_SHA256
    THRIFT_TLS_CL_CERT_PATH THRIFT_TLS_CL_KEY_PATH RECOVERY_PLAN
    RECOVERY_PLAN_SHA256 RECOVERY_REVIEW RECOVERY_REVIEW_SHA256
    RECOVERY_TRIGGER RECOVERY_TRIGGER_SHA256 RECOVERY_AUTHORIZATION
    RECOVERY_ACTIVATION_PERMIT RECOVERY_SUBMISSION_RECEIPT
    RECOVERY_EXPECTED_JOB_NAME RECOVERY_LAUNCH_TOKEN
    RECOVERY_ADMISSION_TIMEOUT_SECONDS RECOVERY_CONTROLLER_SHA256
    RECOVERY_JOB_WRAPPER_SHA256 RECOVERY_WRAPPER_SHA256
)
for variable in "${required[@]}"; do
    [[ -n ${!variable:-} ]] || abort
done

declare -A permitted_environment=()
for variable in "${required[@]}" SLURM_JOB_ID SLURM_JOB_NAME; do
    permitted_environment["$variable"]=1
done
while IFS= read -r variable; do
    case "$variable" in
        BASH_*|ENV|GIT_*|LD_*|SBATCH_*|PYTHON*)
            [[ ${permitted_environment[$variable]+yes} ]] || abort
            ;;
        EVAL_*|INFERENCE_*|KIMI_*|RECOVERY_*|RESUME_DIR|UV_*|VACLI_*)
            [[ ${permitted_environment[$variable]+yes} ]] || abort
            ;;
    esac
done < <(compgen -e)

controller="$PROJECT_DIR/user/tianhaowu/terminal_bench_vmvm/kimi_smoke_timeout_recovery_control.py"
job_wrapper="$PROJECT_DIR/user/tianhaowu/terminal_bench_vmvm/run_kimi_smoke_timeout_recovery_hardened.sbatch"
recovery_wrapper="$PROJECT_DIR/user/tianhaowu/terminal_bench_vmvm/run_kimi_smoke_recovery.sbatch"

stable_hash() {
    local path=$1
    local expected=$2
    local expected_mode=$3
    local metadata
    local digest
    [[ ! -L "$path" && "$(/usr/bin/readlink -e -- "$path" 2>/dev/null)" == "$path" ]] || return 1
    metadata=$(/usr/bin/stat -c '%F|%a|%h|%u' -- "$path" 2>/dev/null) || return 1
    [[ "$metadata" == "regular file|$expected_mode|1|656177" ]] || return 1
    digest=$(/usr/bin/sha256sum -- "$path" 2>/dev/null) || return 1
    [[ "$digest" == "$expected  $path" ]]
}

stable_hash "$controller" "$RECOVERY_CONTROLLER_SHA256" 500 || abort
stable_hash "$job_wrapper" "$RECOVERY_JOB_WRAPPER_SHA256" 500 || abort
stable_hash "$recovery_wrapper" "$RECOVERY_WRAPPER_SHA256" 755 || abort
stable_hash_root() {
    local path=$1
    local expected=$2
    local metadata
    local digest
    [[ ! -L "$path" && "$(/usr/bin/readlink -e -- "$path" 2>/dev/null)" == "$path" ]] || return 1
    metadata=$(/usr/bin/stat -c '%F|%a|%h|%u' -- "$path" 2>/dev/null) || return 1
    [[ "$metadata" == "regular file|755|1|0" ]] || return 1
    digest=$(/usr/bin/sha256sum -- "$path" 2>/dev/null) || return 1
    [[ "$digest" == "$expected  $path" ]]
}
stable_hash_root "$PYTHON_BIN_X86_64" "$PYTHON_BIN_X86_64_SHA256" || abort
stable_hash_root "$VACLI_BIN" "$VACLI_BIN_SHA256" || abort
stable_hash "$UV_BIN_X86_64" "$UV_BIN_X86_64_SHA256" 755 || abort
spooled_sha=$(/usr/bin/sha256sum -- "${BASH_SOURCE[0]}" 2>/dev/null) || abort
[[ "${spooled_sha%%  *}" == "$RECOVERY_JOB_WRAPPER_SHA256" ]] || abort
exec {controller_fd}<"$controller" || abort
controller_fd_path="/proc/self/fd/$controller_fd"
controller_fd_metadata=$(/usr/bin/stat -Lc '%F|%a|%h|%u' -- "$controller_fd_path" 2>/dev/null) || abort
[[ "$controller_fd_metadata" == 'regular file|500|1|656177' ]] || abort
controller_fd_digest=$(/usr/bin/sha256sum -- "$controller_fd_path" 2>/dev/null) || abort
[[ "${controller_fd_digest%%  *}" == "$RECOVERY_CONTROLLER_SHA256" ]] || abort

exec /usr/bin/env -i \
    HOME="$HOME" LANG=C LC_ALL=C LOGNAME=tianhaowu PATH=/usr/bin:/bin USER=tianhaowu \
    PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONSAFEPATH=1 UV_NO_CONFIG=1 \
    PROJECT_DIR="$PROJECT_DIR" EVAL_EXPECTED_PRIME_RL_REVISION="$EVAL_EXPECTED_PRIME_RL_REVISION" \
    EVAL_EXPECTED_MODEL=Kimi-K3 EVAL_DEPLOYMENT_ID="$EVAL_DEPLOYMENT_ID" \
    EVAL_DATASET_ARCHIVE="$EVAL_DATASET_ARCHIVE" \
    EVAL_DATASET_ARCHIVE_SHA256="$EVAL_DATASET_ARCHIVE_SHA256" \
    EVAL_DATASET_CONTENT_SHA256="$EVAL_DATASET_CONTENT_SHA256" \
    INFERENCE_DEPLOYMENT_SPEC="$INFERENCE_DEPLOYMENT_SPEC" \
    INFERENCE_DEPLOYMENT_SPEC_SHA256="$INFERENCE_DEPLOYMENT_SPEC_SHA256" \
    INFERENCE_READINESS_CHECKPOINT="$INFERENCE_READINESS_CHECKPOINT" \
    INFERENCE_READINESS_CHECKPOINT_SHA256="$INFERENCE_READINESS_CHECKPOINT_SHA256" \
    INFERENCE_PROXY_INFO="$INFERENCE_PROXY_INFO" \
    INFERENCE_PROXY_INFO_SHA256="$INFERENCE_PROXY_INFO_SHA256" \
    OUTPUT_DIR="$OUTPUT_DIR" KIMI_SMOKE_RECOVERY_MODE=fresh-two \
    VACLI_BIN="$VACLI_BIN" VACLI_LEASE_RETRIES=20 VACLI_MAX_CONCURRENT_LEASES=2 \
    VACLI_MAX_PULL_RETRIES=20 VACLI_IMAGE_PULL_TIMEOUT_SECONDS=3600 \
    VACLI_CONTAINER_PRIVILEGED=1 PYTHON_BIN_X86_64="$PYTHON_BIN_X86_64" \
    PYTHON_BIN_X86_64_SHA256="$PYTHON_BIN_X86_64_SHA256" \
    PYTHON_SITE_X86_64="$PYTHON_SITE_X86_64" UV_BIN_X86_64="$UV_BIN_X86_64" \
    UV_BIN_X86_64_SHA256="$UV_BIN_X86_64_SHA256" VACLI_BIN_SHA256="$VACLI_BIN_SHA256" \
    RECOVERY_RUNTIME_MANIFEST_SHA256="$RECOVERY_RUNTIME_MANIFEST_SHA256" \
    THRIFT_TLS_CL_CERT_PATH="$THRIFT_TLS_CL_CERT_PATH" \
    THRIFT_TLS_CL_KEY_PATH="$THRIFT_TLS_CL_KEY_PATH" \
    RECOVERY_PLAN="$RECOVERY_PLAN" RECOVERY_PLAN_SHA256="$RECOVERY_PLAN_SHA256" \
    RECOVERY_REVIEW="$RECOVERY_REVIEW" RECOVERY_REVIEW_SHA256="$RECOVERY_REVIEW_SHA256" \
    RECOVERY_TRIGGER="$RECOVERY_TRIGGER" RECOVERY_TRIGGER_SHA256="$RECOVERY_TRIGGER_SHA256" \
    RECOVERY_AUTHORIZATION="$RECOVERY_AUTHORIZATION" \
    RECOVERY_ACTIVATION_PERMIT="$RECOVERY_ACTIVATION_PERMIT" \
    RECOVERY_SUBMISSION_RECEIPT="$RECOVERY_SUBMISSION_RECEIPT" \
    RECOVERY_EXPECTED_JOB_NAME="$RECOVERY_EXPECTED_JOB_NAME" \
    RECOVERY_LAUNCH_TOKEN="$RECOVERY_LAUNCH_TOKEN" \
    RECOVERY_ADMISSION_TIMEOUT_SECONDS=1500 RECOVERY_CONTROLLER_SHA256="$RECOVERY_CONTROLLER_SHA256" \
    RECOVERY_JOB_WRAPPER_SHA256="$RECOVERY_JOB_WRAPPER_SHA256" \
    RECOVERY_WRAPPER_SHA256="$RECOVERY_WRAPPER_SHA256" \
    SLURM_JOB_ID="$SLURM_JOB_ID" SLURM_JOB_NAME="$SLURM_JOB_NAME" \
    "$PYTHON_BIN_X86_64" -I -S -B "$controller_fd_path" run-job \
    --plan "$RECOVERY_PLAN" --review "$RECOVERY_REVIEW" --trigger "$RECOVERY_TRIGGER"
