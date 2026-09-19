#!/usr/bin/bash
# Task-free, aggregate-only VMVM transport diagnostic.

set -euo pipefail
umask 077

fail() {
    printf '{"code":"diagnostic_job_failed","state":"failed"}\n' >&2
    exit 2
}

[[ $# == 0 ]] || fail
[[ ${SLURM_JOB_ID:-} =~ ^[1-9][0-9]*$ ]] || fail

readonly SOURCE_REVISION=a09a9a189697034e23b776fdbfccb369522c469d
readonly SOURCE_TREE=58bec828df10962ec5411762837aa6e3f71461da
readonly VERIFIERS_REVISION=ef35ac787de13c95953ce0ac0225202e544711ce
readonly RENDERERS_REVISION=044d9e2541f6a911cacae9da353fc063911ef1f8
readonly PYDANTIC_CONFIG_REVISION=896ade4e69d8d8dff2d4b0a431b7e1c7c12d638f
readonly VMVM_SHA256=1e7c8ac2906a45d8212d609b5900fdc3d30f91ba73d4bcdb1c36dfc8bfdd09e2
readonly X86_UV_SHA256=ec831939765474162efb6c8c813e2b10908b26b04eaf98ac3e2972fa12d189b9
readonly VACLI_SHA256=8be49a764bd0fac1a3ef2bef053ced556d18397d44642660eb8a2d22a7c235b3

required_environment=(
    DIAG_ACTIVATION_PERMIT DIAG_AUTHORIZATION DIAG_AUTHORIZATION_FILE_SHA256
    DIAG_AUTHORIZATION_SHA256
    DIAG_BUNDLE_IDENTITY DIAG_BUNDLE_ROOT DIAG_COMPLETION_RECEIPT
    DIAG_FINALIZER_PATH DIAG_FINALIZER_SHA256 DIAG_JOB_AUTHORIZATION
    DIAG_JOB_NAME DIAG_LAUNCHER_PATH DIAG_LAUNCHER_SHA256 DIAG_OUTPUT_ROOT
    DIAG_OUTPUT_PARENT_IDENTITY DIAG_PROBE_PATH DIAG_PROBE_SHA256
    DIAG_RESERVATION DIAG_RESERVATION_IDENTITY DIAG_SCRATCH_ROOT
    DIAG_SOURCE_IDENTITY DIAG_SOURCE_REVISION DIAG_SOURCE_ROOT
    DIAG_SOURCE_TREE DIAG_SUBMISSION_RECEIPT DIAG_VMVM_SHA256
    DIAG_WRAPPER_GATE_TIMEOUT_SECONDS DIAG_WRAPPER_PATH DIAG_WRAPPER_SHA256
    HOME LANG LC_ALL LOGNAME PATH PYTHONDONTWRITEBYTECODE PYTHON_BIN_X86_64
    PYTHON_SITE_X86_64 PYTHON_SITE_X86_64_ENTRY_COUNT
    PYTHON_SITE_X86_64_IDENTITY PYTHON_SITE_X86_64_MANIFEST_SHA256
    PYTHON_SITE_X86_64_TOTAL_BYTES SLURM_EXPORT_ENV TZ USER UV_BIN_X86_64 VACLI_BIN
    VACLI_CONTAINER_PRIVILEGED VACLI_IMAGE_PULL_TIMEOUT_SECONDS
    VACLI_LEASE_RETRIES VACLI_MAX_CONCURRENT_LEASES VACLI_MAX_PULL_RETRIES
    THRIFT_TLS_CL_CERT_PATH THRIFT_TLS_CL_KEY_PATH X2P_ENV X2P_CFG_ENV
    X2P_PROXY_URL
)
for variable in "${required_environment[@]}"; do
    [[ -n ${!variable:-} ]] || fail
done
for variable in "${!BASH_FUNC_@}" "${!LD_@}" "${!GIT_@}"; do
    [[ -z $variable ]] || fail
done
for variable in "${!UV_@}"; do
    [[ $variable == UV_BIN_X86_64 ]] || fail
done
for variable in "${!PYTHON_@}"; do
    [[ $variable == PYTHONDONTWRITEBYTECODE \
        || $variable == PYTHON_BIN_X86_64 \
        || $variable == PYTHON_SITE_X86_64 \
        || $variable == PYTHON_SITE_X86_64_ENTRY_COUNT \
        || $variable == PYTHON_SITE_X86_64_IDENTITY \
        || $variable == PYTHON_SITE_X86_64_MANIFEST_SHA256 \
        || $variable == PYTHON_SITE_X86_64_TOTAL_BYTES ]] || fail
done
if [[ -n ${BASH_ENV+x} || -n ${ENV+x} || -n ${CDPATH+x} \
    || -n ${PYTHONHOME+x} || -n ${PYTHONPATH+x} || -n ${PYTHONSTARTUP+x} \
    || -n ${PYTHONINSPECT+x} || -n ${PYTHONPYCACHEPREFIX+x} \
    || -n ${PYTHONNOUSERSITE+x} || -n ${PYTHONSAFEPATH+x} \
    || -n ${VIRTUAL_ENV+x} || -n ${CONDA_PREFIX+x} ]]; then
    fail
fi

if [[ $DIAG_SOURCE_REVISION != "$SOURCE_REVISION" \
    || $DIAG_SOURCE_TREE != "$SOURCE_TREE" \
    || $DIAG_VMVM_SHA256 != "$VMVM_SHA256" \
    || $DIAG_WRAPPER_GATE_TIMEOUT_SECONDS != 900 \
    || $HOME != /storage/home/tianhaowu \
    || $LANG != C || $LC_ALL != C || $LOGNAME != tianhaowu \
    || $PATH != /usr/bin:/bin || $PYTHONDONTWRITEBYTECODE != 1 \
    || $PYTHON_BIN_X86_64 != python3 \
    || $PYTHON_SITE_X86_64 != /checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64 \
    || $SLURM_EXPORT_ENV != NONE || $TZ != UTC || $USER != tianhaowu \
    || $UV_BIN_X86_64 != /storage/home/tianhaowu/.local/x86_64/bin/uv \
    || $VACLI_BIN != /public/fbpkgs/x86_64/vacli/stable/vacli \
    || $VACLI_CONTAINER_PRIVILEGED != 1 \
    || $VACLI_IMAGE_PULL_TIMEOUT_SECONDS != 300 \
    || $VACLI_LEASE_RETRIES != 2 \
    || $VACLI_MAX_CONCURRENT_LEASES != 1 \
    || $VACLI_MAX_PULL_RETRIES != 1 ]]; then
    fail
fi
for value in "$DIAG_BUNDLE_ROOT" "$DIAG_LAUNCHER_PATH" "$DIAG_WRAPPER_PATH" \
    "$DIAG_PROBE_PATH" "$DIAG_FINALIZER_PATH" "$DIAG_SOURCE_ROOT" \
    "$DIAG_OUTPUT_ROOT" "$DIAG_COMPLETION_RECEIPT" \
    "$DIAG_RESERVATION" "$DIAG_SCRATCH_ROOT" "$DIAG_AUTHORIZATION" \
    "$DIAG_JOB_AUTHORIZATION" "$DIAG_ACTIVATION_PERMIT" \
    "$DIAG_SUBMISSION_RECEIPT" "$PYTHON_SITE_X86_64" "$UV_BIN_X86_64" \
    "$VACLI_BIN" "$THRIFT_TLS_CL_CERT_PATH" "$THRIFT_TLS_CL_KEY_PATH"; do
    [[ $value == /* && $value != *$'\n'* && $value != *$'\r'* ]] || fail
done
for value in "$DIAG_AUTHORIZATION_FILE_SHA256" "$DIAG_AUTHORIZATION_SHA256" \
    "$DIAG_LAUNCHER_SHA256" \
    "$DIAG_WRAPPER_SHA256" "$DIAG_PROBE_SHA256" "$DIAG_FINALIZER_SHA256" \
    "$PYTHON_SITE_X86_64_MANIFEST_SHA256"; do
    [[ $value =~ ^[0-9a-f]{64}$ ]] || fail
done
for value in "$DIAG_BUNDLE_IDENTITY" "$DIAG_OUTPUT_PARENT_IDENTITY" \
    "$DIAG_RESERVATION_IDENTITY" "$DIAG_SOURCE_IDENTITY" \
    "$PYTHON_SITE_X86_64_IDENTITY"; do
    [[ $value =~ ^[0-9]+:[0-9]+:[0-9]+:[0-9]+$ ]] || fail
done
[[ $PYTHON_SITE_X86_64_ENTRY_COUNT =~ ^[1-9][0-9]*$ \
    && $PYTHON_SITE_X86_64_TOTAL_BYTES =~ ^[1-9][0-9]*$ ]] || fail

exec {bundle_fd}<"$DIAG_BUNDLE_ROOT" || fail
exec {source_fd}<"$DIAG_SOURCE_ROOT" || fail
exec {site_fd}<"$PYTHON_SITE_X86_64" || fail
exec {reservation_fd}<"$DIAG_RESERVATION" || fail
exec {output_parent_fd}<"${DIAG_OUTPUT_ROOT%/*}" || fail
[[ $(/usr/bin/stat -Lc '%d:%i:%a:%u' "/proc/self/fd/$bundle_fd") \
        == "$DIAG_BUNDLE_IDENTITY" \
    && $(/usr/bin/stat -Lc '%d:%i:%a:%u' "/proc/self/fd/$source_fd") \
        == "$DIAG_SOURCE_IDENTITY" \
    && $(/usr/bin/stat -Lc '%d:%i:%a:%u' "/proc/self/fd/$site_fd") \
        == "$PYTHON_SITE_X86_64_IDENTITY" \
    && $(/usr/bin/stat -Lc '%d:%i:%a:%u' "/proc/self/fd/$reservation_fd") \
        == "$DIAG_RESERVATION_IDENTITY" \
    && $(/usr/bin/stat -Lc '%d:%i:%a:%u' "/proc/self/fd/$output_parent_fd") \
        == "$DIAG_OUTPUT_PARENT_IDENTITY" ]] || fail
readonly BOUND_BUNDLE_ROOT="/proc/self/fd/$bundle_fd"
readonly BOUND_SOURCE_ROOT="/proc/self/fd/$source_fd"
readonly BOUND_SITE_ROOT="/proc/self/fd/$site_fd"
readonly BOUND_RESERVATION="/proc/self/fd/$reservation_fd"
readonly BOUND_OUTPUT_PARENT="/proc/self/fd/$output_parent_fd"

[[ -d $BOUND_BUNDLE_ROOT \
    && $(/usr/bin/stat -Lc '%a:%u:%h' -- "$BOUND_BUNDLE_ROOT" 2>/dev/null) \
        == "700:$(/usr/bin/id -u):2" ]] || fail
shopt -s nullglob dotglob
bundle_entries=("$BOUND_BUNDLE_ROOT"/*)
shopt -u nullglob dotglob
(( ${#bundle_entries[@]} == 6 )) || fail
for entry in "${bundle_entries[@]}"; do
    case ${entry##*/} in
        README.md|finalize_vmvm_task_free_v2.py|launch_vmvm_task_free_v2.py|probe_vmvm_task_free_v2.py|\
            run_vmvm_task_free_v2.sbatch|test_vmvm_task_free_v2.py) ;;
        *) fail ;;
    esac
done

digest_file() {
    local output rc
    set +e
    output=$(/usr/bin/sha256sum -- "$1" 2>/dev/null)
    rc=$?
    set -e
    (( rc == 0 )) || fail
    printf '%s' "${output%% *}"
}

git_capture() {
    local root=$1
    shift
    set +e
    GIT_ATTR_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
        GIT_NO_REPLACE_OBJECTS=1 GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0 \
        /usr/bin/git -c core.fsmonitor=false -c core.hooksPath=/dev/null \
        -c core.untrackedCache=false -C "$root" "$@" 2>/dev/null
    local rc=$?
    set -e
    return "$rc"
}

validate_source() {
    local root=$1
    local value status_rc ignored_rc vmvm_rc
    [[ -d $root ]] || fail
    value=$(git_capture "$root" rev-parse --verify HEAD) || fail
    [[ $value == "$SOURCE_REVISION" ]] || fail
    value=$(git_capture "$root" rev-parse 'HEAD^{tree}') || fail
    [[ $value == "$SOURCE_TREE" ]] || fail
    value=$(git_capture "$root" symbolic-ref -q HEAD) && status_rc=0 || status_rc=$?
    (( status_rc == 1 )) && [[ -z $value ]] || fail
    value=$(git_capture "$root" status --porcelain=v1 --untracked-files=all --ignore-submodules=none) \
        || fail
    [[ -z $value ]] || fail
    value=$(git_capture "$root" ls-files --others --ignored --exclude-standard -- \
        ':(glob)**/*.py' ':(glob)**/*.pyc' ':(glob)**/*.so' ':(glob)**/*.pyd' \
        ':(glob)**/sitecustomize.py' ':(glob)**/usercustomize.py') && ignored_rc=0 || ignored_rc=$?
    (( ignored_rc == 0 )) && [[ -z $value ]] || fail
    for binding in \
        "deps/verifiers:$VERIFIERS_REVISION" \
        "deps/renderers:$RENDERERS_REVISION" \
        "deps/pydantic-config:$PYDANTIC_CONFIG_REVISION"; do
        local dependency=${binding%%:*}
        local revision=${binding#*:}
        value=$(git_capture "$root" rev-parse "HEAD:$dependency") || fail
        [[ $value == "$revision" ]] || fail
        value=$(git_capture "$root/$dependency" rev-parse HEAD) || fail
        [[ $value == "$revision" ]] || fail
        value=$(git_capture "$root/$dependency" status --porcelain=v1 --untracked-files=all) || fail
        [[ -z $value ]] || fail
        value=$(git_capture "$root/$dependency" ls-files --others --ignored --exclude-standard -- \
            ':(glob)**/*.py' ':(glob)**/*.pyc' ':(glob)**/*.so' ':(glob)**/*.pyd' \
            ':(glob)**/sitecustomize.py' ':(glob)**/usercustomize.py') \
            && ignored_rc=0 || ignored_rc=$?
        (( ignored_rc == 0 )) && [[ -z $value ]] || fail
    done
    set +e
    value=$(
        cd "$root" &&
        /usr/bin/sha256sum environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/*.py \
            | /usr/bin/sha256sum | /usr/bin/cut -d' ' -f1
    )
    vmvm_rc=$?
    set -e
    (( vmvm_rc == 0 )) && [[ $value == "$VMVM_SHA256" ]] || fail
}

validate_file() {
    local path=$1 mode=$2 digest=$3 owner=${4:-$(/usr/bin/id -u)}
    [[ -f $path && ! -L $path \
        && $(/usr/bin/stat -Lc '%a:%u:%h' -- "$path" 2>/dev/null) == "$mode:$owner:1" \
        && $(digest_file "$path") == "$digest" ]] || fail
}

[[ $DIAG_LAUNCHER_PATH == "$DIAG_BUNDLE_ROOT/launch_vmvm_task_free_v2.py" \
    && $DIAG_WRAPPER_PATH == "$DIAG_BUNDLE_ROOT/run_vmvm_task_free_v2.sbatch" \
    && $DIAG_PROBE_PATH == "$DIAG_BUNDLE_ROOT/probe_vmvm_task_free_v2.py" \
    && $DIAG_FINALIZER_PATH == "$DIAG_BUNDLE_ROOT/finalize_vmvm_task_free_v2.py" ]] || fail
validate_file "$BOUND_BUNDLE_ROOT/launch_vmvm_task_free_v2.py" 500 "$DIAG_LAUNCHER_SHA256"
validate_file "$BOUND_BUNDLE_ROOT/run_vmvm_task_free_v2.sbatch" 500 "$DIAG_WRAPPER_SHA256"
validate_file "$BOUND_BUNDLE_ROOT/probe_vmvm_task_free_v2.py" 500 "$DIAG_PROBE_SHA256"
validate_file "$BOUND_BUNDLE_ROOT/finalize_vmvm_task_free_v2.py" 500 "$DIAG_FINALIZER_SHA256"
[[ $(digest_file "${BASH_SOURCE[0]}") == "$DIAG_WRAPPER_SHA256" ]] || fail
validate_file "$DIAG_AUTHORIZATION" 400 "$DIAG_AUTHORIZATION_FILE_SHA256"
validate_file "$UV_BIN_X86_64" 755 "$X86_UV_SHA256"
validate_file "$VACLI_BIN" 755 "$VACLI_SHA256" 0
validate_source "$BOUND_SOURCE_ROOT"

# A released allocation may start before its permit is durably committed.
readonly gate_deadline=$((SECONDS + DIAG_WRAPPER_GATE_TIMEOUT_SECONDS))
while :; do
    [[ ! -e "$BOUND_RESERVATION/submission_failure.json" ]] || fail
    if [[ -f $BOUND_RESERVATION/job_authorization.json \
        && -f $BOUND_RESERVATION/activation_permit.json \
        && -f $BOUND_RESERVATION/submission_receipt.json \
        && $(/usr/bin/stat -Lc '%F:%a:%u' -- "$BOUND_RESERVATION" 2>/dev/null) \
            == "directory:500:$(/usr/bin/id -u)" ]]; then
        break
    fi
    (( SECONDS < gate_deadline )) || fail
    /usr/bin/sleep 1
done

exec {probe_fd}<"$BOUND_BUNDLE_ROOT/probe_vmvm_task_free_v2.py" || fail
exec {uv_fd}<"$UV_BIN_X86_64" || fail
readonly BOUND_PROBE="/proc/self/fd/$probe_fd"
readonly BOUND_UV="/proc/self/fd/$uv_fd"
validate_file "$BOUND_PROBE" 500 "$DIAG_PROBE_SHA256"
validate_file "$BOUND_UV" 755 "$X86_UV_SHA256"

preflight_output=""
set +e
preflight_output=$(
    "$BOUND_UV" run --no-project --offline --python "$PYTHON_BIN_X86_64" \
        python3 -I -S -B "$BOUND_PROBE" --validate-batch \
        --source-root "$BOUND_SOURCE_ROOT" --site-root "$BOUND_SITE_ROOT" \
        --scratch-root "$DIAG_SCRATCH_ROOT" \
        --output-dir "$BOUND_OUTPUT_PARENT/${DIAG_OUTPUT_ROOT##*/}" \
        --completion-receipt "$BOUND_OUTPUT_PARENT/${DIAG_COMPLETION_RECEIPT##*/}" 2>&1
)
preflight_rc=$?
set -e
[[ $preflight_rc == 0 && $preflight_output == '{"state":"admitted"}' ]] || fail

# Publication-adjacent source and executable validation. No task/dataset input
# is opened anywhere in this wrapper or its probe.
validate_file "$BOUND_PROBE" 500 "$DIAG_PROBE_SHA256"
validate_source "$BOUND_SOURCE_ROOT"
[[ ! -e $DIAG_OUTPUT_ROOT && ! -L $DIAG_OUTPUT_ROOT \
    && ! -e $DIAG_COMPLETION_RECEIPT && ! -L $DIAG_COMPLETION_RECEIPT \
    && ! -e $DIAG_SCRATCH_ROOT && ! -L $DIAG_SCRATCH_ROOT ]] || fail
environment_sha256=""
set +e
environment_sha256=$(digest_file "$BOUND_RESERVATION/slurm_environment.bin")
environment_rc=$?
set -e
(( environment_rc == 0 )) && [[ $environment_sha256 =~ ^[0-9a-f]{64}$ ]] || fail
readonly environment_sha256
submission_receipt_sha256=""
set +e
submission_receipt_sha256=$(digest_file "$BOUND_RESERVATION/submission_receipt.json")
submission_receipt_rc=$?
set -e
(( submission_receipt_rc == 0 )) \
    && [[ $submission_receipt_sha256 =~ ^[0-9a-f]{64}$ ]] || fail
readonly submission_receipt_sha256
job_authorization_sha256=""
set +e
job_authorization_sha256=$(digest_file "$BOUND_RESERVATION/job_authorization.json")
job_authorization_rc=$?
set -e
(( job_authorization_rc == 0 )) \
    && [[ $job_authorization_sha256 =~ ^[0-9a-f]{64}$ ]] || fail
readonly job_authorization_sha256

probe_output=""
set +e
probe_output=$(
    "$BOUND_UV" run --no-project --offline --python "$PYTHON_BIN_X86_64" \
        python3 -I -S -B "$BOUND_PROBE" \
        --source-root "$BOUND_SOURCE_ROOT" --site-root "$BOUND_SITE_ROOT" \
        --scratch-root "$DIAG_SCRATCH_ROOT" \
        --output-dir "$BOUND_OUTPUT_PARENT/${DIAG_OUTPUT_ROOT##*/}" \
        --completion-receipt "$BOUND_OUTPUT_PARENT/${DIAG_COMPLETION_RECEIPT##*/}" \
        --environment-sha256 "$environment_sha256" \
        --authorization-file-sha256 "$DIAG_AUTHORIZATION_FILE_SHA256" \
        --authorization-sha256 "$DIAG_AUTHORIZATION_SHA256" \
        --job-authorization-sha256 "$job_authorization_sha256" \
        --job-id "$SLURM_JOB_ID" --job-name "$DIAG_JOB_NAME" \
        --submission-receipt-sha256 "$submission_receipt_sha256" 2>&1
)
probe_rc=$?
set -e
validate_file "$BOUND_PROBE" 500 "$DIAG_PROBE_SHA256"
validate_source "$BOUND_SOURCE_ROOT"
if (( probe_rc != 0 )) \
    || [[ ! $probe_output =~ ^\{"failure_categories":[0-9]+,"passed":[0-9]+,"stages":48,"state":"awaiting_external_completion"\}$ ]]; then
    fail
fi
[[ $(/usr/bin/stat -Lc '%a:%u' -- "$BOUND_OUTPUT_PARENT/${DIAG_OUTPUT_ROOT##*/}") \
    == "500:$(/usr/bin/id -u)" \
    && ! -e "$BOUND_OUTPUT_PARENT/${DIAG_COMPLETION_RECEIPT##*/}" ]] || fail
printf '%s\n' "$probe_output"
