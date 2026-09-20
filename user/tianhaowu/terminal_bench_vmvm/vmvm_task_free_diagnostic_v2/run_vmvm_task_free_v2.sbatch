#!/usr/bin/bash
# Task-free, aggregate-only VMVM pre-lease admission diagnostic.

set -euo pipefail
umask 077

exec {public_stdout_fd}>&1 || exit 2
exec {public_stderr_fd}>&2 || exit 2
exec >/dev/null 2>&1 || exit 2
readonly public_stdout_fd public_stderr_fd

failure_stage=entry
identity_bundle=not_checked
identity_source=not_checked
identity_site=not_checked
identity_reservation=not_checked
identity_output_parent=not_checked
missing_required=()
empty_required=()

required_name_allowed() {
    local candidate=$1 required
    for required in "${required_environment[@]}"; do
        [[ $candidate != "$required" ]] || return 0
    done
    return 1
}

print_required_names() {
    local destination=$1 name separator=""
    shift
    printf '[' >&"$destination"
    for name in "$@"; do
        printf '%s"%s"' "$separator" "$name" >&"$destination"
        separator=,
    done
    printf ']' >&"$destination"
}

fail() {
    local stage=$failure_stage identity variable
    local bundle=$identity_bundle output_parent=$identity_output_parent
    local reservation=$identity_reservation site=$identity_site source=$identity_source
    local required
    local -a missing=("${missing_required[@]}") empty=("${empty_required[@]}")
    case $stage in
        entry|required_environment|forbidden_environment|fixed_environment|\
            path_shape|digest_shape|identity_shape|count_shape|directory_open|\
            directory_identity|bundle_inventory|bundle_artifacts|runtime_resolution|\
            runtime_artifacts|source_attestation|activation_gate|executable_binding|\
            sealed_builder|uv_sanitizer|uv_environment|uv_probe_exec|\
            probe_admission|probe_response|post_preflight_source|\
            namespace_freshness|lineage_hashes|internal) ;;
        *) stage=internal ;;
    esac
    for variable in bundle output_parent reservation site source; do
        identity=${!variable}
        case $identity in
            match|not_checked|unreadable|device_only|inode_only|mode_only|owner_only|multiple) ;;
            *)
                printf -v "$variable" %s not_checked
                stage=internal
                ;;
        esac
    done
    if [[ $stage == required_environment ]]; then
        for required in "${missing[@]}" "${empty[@]}"; do
            if ! required_name_allowed "$required"; then
                missing=()
                empty=()
                stage=internal
                break
            fi
        done
    fi
    if [[ $stage == required_environment ]]; then
        printf '{"code":"diagnostic_job_failed","required_environment":{"empty":' \
            >&"$public_stderr_fd"
        print_required_names "$public_stderr_fd" "${empty[@]}"
        printf ',"missing":' >&"$public_stderr_fd"
        print_required_names "$public_stderr_fd" "${missing[@]}"
        printf '},"stage":"required_environment","state":"failed"}\n' \
            >&"$public_stderr_fd"
        exit 2
    fi
    printf '{"code":"diagnostic_job_failed","directory_identities":{"bundle":"%s","output_parent":"%s","reservation":"%s","site":"%s","source":"%s"},"stage":"%s","state":"failed"}\n' \
        "$bundle" "$output_parent" "$reservation" "$site" "$source" "$stage" \
        >&"$public_stderr_fd"
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
readonly VACLI_RESOLVED=/infra/public/fbpkgs/x86_64/vacli/794/vacli
readonly DIRECTORY_IDENTITY_POLICY=nfs_portable_inode_mode_uid_v1

required_environment=(
    DIAG_ACTIVATION_PERMIT DIAG_AUTHORIZATION DIAG_AUTHORIZATION_FILE_SHA256
    DIAG_AUTHORIZATION_SHA256
    DIAG_BUNDLE_IDENTITY DIAG_BUNDLE_PORTABLE_IDENTITY DIAG_BUNDLE_ROOT
    DIAG_COMPLETION_RECEIPT DIAG_DIRECTORY_IDENTITY_POLICY DIAG_FINALIZER_PATH
    DIAG_FINALIZER_SHA256 DIAG_JOB_AUTHORIZATION
    DIAG_JOB_NAME DIAG_LAUNCHER_PATH DIAG_LAUNCHER_SHA256 DIAG_OUTPUT_ROOT
    DIAG_OUTPUT_PARENT_IDENTITY DIAG_OUTPUT_PARENT_PORTABLE_IDENTITY
    DIAG_PROBE_PATH DIAG_PROBE_SHA256 DIAG_RESERVATION
    DIAG_RESERVATION_IDENTITY DIAG_RESERVATION_PORTABLE_IDENTITY
    DIAG_SCRATCH_ROOT DIAG_SOURCE_IDENTITY DIAG_SOURCE_PORTABLE_IDENTITY
    DIAG_SOURCE_REVISION DIAG_SOURCE_ROOT
    DIAG_SOURCE_TREE DIAG_SUBMISSION_RECEIPT DIAG_VMVM_SHA256
    DIAG_WRAPPER_GATE_TIMEOUT_SECONDS DIAG_WRAPPER_PATH DIAG_WRAPPER_SHA256
    HOME LANG LC_ALL LOGNAME PATH PYTHONDONTWRITEBYTECODE PYTHON_BIN_X86_64
    PYTHON_SITE_X86_64 PYTHON_SITE_X86_64_ENTRY_COUNT
    PYTHON_SITE_X86_64_IDENTITY PYTHON_SITE_X86_64_PORTABLE_IDENTITY
    PYTHON_SITE_X86_64_MANIFEST_SHA256
    PYTHON_SITE_X86_64_TOTAL_BYTES SLURM_EXPORT_ENV TZ USER UV_BIN_X86_64 VACLI_BIN
    VACLI_CONTAINER_PRIVILEGED VACLI_IMAGE_PULL_TIMEOUT_SECONDS
    VACLI_LEASE_RETRIES VACLI_MAX_CONCURRENT_LEASES VACLI_MAX_PULL_RETRIES
    THRIFT_TLS_CL_CERT_PATH THRIFT_TLS_CL_KEY_PATH X2P_ENV X2P_CFG_ENV
    X2P_PROXY_URL
)
failure_stage=required_environment
for variable in "${required_environment[@]}"; do
    if [[ -z ${!variable+x} ]]; then
        missing_required+=("$variable")
    elif [[ -z ${!variable} ]]; then
        empty_required+=("$variable")
    fi
done
(( ${#missing_required[@]} == 0 && ${#empty_required[@]} == 0 )) || fail
failure_stage=forbidden_environment
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
        || $variable == PYTHON_SITE_X86_64_PORTABLE_IDENTITY \
        || $variable == PYTHON_SITE_X86_64_MANIFEST_SHA256 \
        || $variable == PYTHON_SITE_X86_64_TOTAL_BYTES ]] || fail
done
if [[ -n ${BASH_ENV+x} || -n ${ENV+x} || -n ${CDPATH+x} || -n ${UV+x} \
    || -n ${PYTHONHOME+x} || -n ${PYTHONPATH+x} || -n ${PYTHONSTARTUP+x} \
    || -n ${PYTHONINSPECT+x} || -n ${PYTHONPYCACHEPREFIX+x} \
    || -n ${PYTHONNOUSERSITE+x} || -n ${PYTHONSAFEPATH+x} \
    || -n ${VIRTUAL_ENV+x} || -n ${CONDA_PREFIX+x} ]]; then
    fail
fi

failure_stage=fixed_environment
if [[ $DIAG_SOURCE_REVISION != "$SOURCE_REVISION" \
    || $DIAG_SOURCE_TREE != "$SOURCE_TREE" \
    || $DIAG_VMVM_SHA256 != "$VMVM_SHA256" \
    || $DIAG_DIRECTORY_IDENTITY_POLICY != "$DIRECTORY_IDENTITY_POLICY" \
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
failure_stage=path_shape
for value in "$DIAG_BUNDLE_ROOT" "$DIAG_LAUNCHER_PATH" "$DIAG_WRAPPER_PATH" \
    "$DIAG_PROBE_PATH" "$DIAG_FINALIZER_PATH" "$DIAG_SOURCE_ROOT" \
    "$DIAG_OUTPUT_ROOT" "$DIAG_COMPLETION_RECEIPT" \
    "$DIAG_RESERVATION" "$DIAG_SCRATCH_ROOT" "$DIAG_AUTHORIZATION" \
    "$DIAG_JOB_AUTHORIZATION" "$DIAG_ACTIVATION_PERMIT" \
    "$DIAG_SUBMISSION_RECEIPT" "$PYTHON_SITE_X86_64" "$UV_BIN_X86_64" \
    "$VACLI_BIN" "$THRIFT_TLS_CL_CERT_PATH" "$THRIFT_TLS_CL_KEY_PATH"; do
    [[ $value == /* && $value != *$'\n'* && $value != *$'\r'* ]] || fail
done
for value in "$DIAG_BUNDLE_ROOT" "$DIAG_SOURCE_ROOT" "$PYTHON_SITE_X86_64" \
    "$DIAG_RESERVATION" "${DIAG_OUTPUT_ROOT%/*}"; do
    [[ ! -L $value && $(/usr/bin/readlink -f -- "$value") == "$value" ]] || fail
done
failure_stage=digest_shape
for value in "$DIAG_AUTHORIZATION_FILE_SHA256" "$DIAG_AUTHORIZATION_SHA256" \
    "$DIAG_LAUNCHER_SHA256" \
    "$DIAG_WRAPPER_SHA256" "$DIAG_PROBE_SHA256" "$DIAG_FINALIZER_SHA256" \
    "$PYTHON_SITE_X86_64_MANIFEST_SHA256"; do
    [[ $value =~ ^[0-9a-f]{64}$ ]] || fail
done
failure_stage=identity_shape
for value in "$DIAG_BUNDLE_IDENTITY" "$DIAG_OUTPUT_PARENT_IDENTITY" \
    "$DIAG_RESERVATION_IDENTITY" "$DIAG_SOURCE_IDENTITY" \
    "$PYTHON_SITE_X86_64_IDENTITY"; do
    [[ $value =~ ^[0-9]+:[0-9]+:[0-9]+:[0-9]+$ ]] || fail
done
for value in "$DIAG_BUNDLE_PORTABLE_IDENTITY" \
    "$DIAG_OUTPUT_PARENT_PORTABLE_IDENTITY" \
    "$DIAG_RESERVATION_PORTABLE_IDENTITY" "$DIAG_SOURCE_PORTABLE_IDENTITY" \
    "$PYTHON_SITE_X86_64_PORTABLE_IDENTITY"; do
    [[ $value =~ ^[0-9]+:[0-9]+:[0-9]+$ ]] || fail
done
failure_stage=count_shape
[[ $PYTHON_SITE_X86_64_ENTRY_COUNT =~ ^[1-9][0-9]*$ \
    && $PYTHON_SITE_X86_64_TOTAL_BYTES =~ ^[1-9][0-9]*$ ]] || fail

classify_directory_identity() {
    local fd=$1 expected=$2
    local raw device inode permissions owner
    local expected_device expected_inode expected_mode expected_owner mask=0
    raw=$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "/proc/self/fd/$fd") || {
        printf unreadable
        return
    }
    IFS=: read -r device inode permissions owner <<< "$raw"
    IFS=: read -r expected_device expected_inode expected_mode expected_owner <<< "$expected"
    if [[ ! $device =~ ^[0-9]+$ || ! $inode =~ ^[0-9]+$ \
        || ! $permissions =~ ^[0-7]+$ || ! $owner =~ ^[0-9]+$ ]]; then
        printf unreadable
        return
    fi
    [[ $device == "$expected_device" ]] || mask=$((mask | 1))
    [[ $inode == "$expected_inode" ]] || mask=$((mask | 2))
    [[ $((8#$permissions)) == "$expected_mode" ]] || mask=$((mask | 4))
    [[ $owner == "$expected_owner" ]] || mask=$((mask | 8))
    case $mask in
        0) printf match ;;
        1) printf device_only ;;
        2) printf inode_only ;;
        4) printf mode_only ;;
        8) printf owner_only ;;
        *) printf multiple ;;
    esac
}

portable_directory_identity() {
    local fd=$1 raw inode permissions owner
    raw=$(/usr/bin/stat -Lc '%i:%a:%u' -- "/proc/self/fd/$fd") || return 1
    IFS=: read -r inode permissions owner <<< "$raw"
    [[ $inode =~ ^[0-9]+$ && $permissions =~ ^[0-7]+$ && $owner =~ ^[0-9]+$ ]] \
        || return 1
    printf '%s:%s:%s' "$inode" "$((8#$permissions))" "$owner"
}

failure_stage=directory_open
exec {bundle_fd}<"$DIAG_BUNDLE_ROOT" || {
    identity_bundle=unreadable
    fail
}
exec {source_fd}<"$DIAG_SOURCE_ROOT" || {
    identity_source=unreadable
    fail
}
exec {site_fd}<"$PYTHON_SITE_X86_64" || {
    identity_site=unreadable
    fail
}
exec {reservation_fd}<"$DIAG_RESERVATION" || {
    identity_reservation=unreadable
    fail
}
exec {output_parent_fd}<"${DIAG_OUTPUT_ROOT%/*}" || {
    identity_output_parent=unreadable
    fail
}
failure_stage=directory_identity
identity_bundle=$(classify_directory_identity "$bundle_fd" "$DIAG_BUNDLE_IDENTITY")
identity_source=$(classify_directory_identity "$source_fd" "$DIAG_SOURCE_IDENTITY")
identity_site=$(classify_directory_identity "$site_fd" "$PYTHON_SITE_X86_64_IDENTITY")
identity_reservation=$(classify_directory_identity "$reservation_fd" "$DIAG_RESERVATION_IDENTITY")
identity_output_parent=$(classify_directory_identity "$output_parent_fd" "$DIAG_OUTPUT_PARENT_IDENTITY")
[[ $identity_bundle == match || $identity_bundle == device_only ]] \
    && [[ $identity_source == match || $identity_source == device_only ]] \
    && [[ $identity_site == match || $identity_site == device_only ]] \
    && [[ $identity_reservation == match || $identity_reservation == device_only ]] \
    && [[ $identity_output_parent == match || $identity_output_parent == device_only ]] \
    && [[ $(portable_directory_identity "$bundle_fd") == "$DIAG_BUNDLE_PORTABLE_IDENTITY" ]] \
    && [[ $(portable_directory_identity "$source_fd") == "$DIAG_SOURCE_PORTABLE_IDENTITY" ]] \
    && [[ $(portable_directory_identity "$site_fd") == "$PYTHON_SITE_X86_64_PORTABLE_IDENTITY" ]] \
    && [[ $(portable_directory_identity "$reservation_fd") == "$DIAG_RESERVATION_PORTABLE_IDENTITY" ]] \
    && [[ $(portable_directory_identity "$output_parent_fd") == "$DIAG_OUTPUT_PARENT_PORTABLE_IDENTITY" ]] \
    || fail
readonly BOUND_BUNDLE_ROOT="/proc/self/fd/$bundle_fd"
readonly BOUND_SOURCE_ROOT="/proc/self/fd/$source_fd"
readonly BOUND_SITE_ROOT="/proc/self/fd/$site_fd"
readonly BOUND_RESERVATION="/proc/self/fd/$reservation_fd"
readonly BOUND_OUTPUT_PARENT="/proc/self/fd/$output_parent_fd"

failure_stage=bundle_inventory
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
    (( rc == 0 )) || return 1
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

validate_fd_file() {
    local path=$1 mode=$2 digest=$3 authorized_path=$4
    local owner=${5:-$(/usr/bin/id -u)} fd target observed authorized
    [[ $path =~ ^/proc/self/fd/([3-9]|[1-9][0-9]+)$ ]] || fail
    fd=${BASH_REMATCH[1]}
    [[ -r /proc/self/fd/$fd ]] || fail
    target=$(/usr/bin/readlink -- "/proc/self/fd/$fd") || fail
    [[ $target == "$authorized_path" ]] || fail
    observed=$(/usr/bin/stat -Lc '%F:%d:%i:%a:%u:%h:%s' -- "/proc/self/fd/$fd") \
        || fail
    authorized=$(/usr/bin/stat -Lc '%F:%d:%i:%a:%u:%h:%s' -- "$authorized_path") \
        || fail
    [[ $observed == "regular file:"* \
        && $observed == "$authorized" \
        && $observed == *":$mode:$owner:1:"* \
        && $(digest_file "/proc/self/fd/$fd") == "$digest" ]] || fail
}

failure_stage=bundle_artifacts
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
failure_stage=runtime_resolution
[[ $(/usr/bin/readlink -f -- "$UV_BIN_X86_64") == "$UV_BIN_X86_64" \
    && $(/usr/bin/readlink -f -- "$VACLI_BIN") == "$VACLI_RESOLVED" \
    && $(/usr/bin/stat -Lc '%d:%i' -- "$VACLI_BIN") \
        == $(/usr/bin/stat -Lc '%d:%i' -- "$VACLI_RESOLVED") ]] || fail
failure_stage=runtime_artifacts
validate_file "$UV_BIN_X86_64" 755 "$X86_UV_SHA256"
validate_file "$VACLI_BIN" 755 "$VACLI_SHA256" 0
validate_file "$VACLI_RESOLVED" 755 "$VACLI_SHA256" 0
failure_stage=source_attestation
validate_source "$BOUND_SOURCE_ROOT"

# A released allocation may start before its permit is durably committed.
failure_stage=activation_gate
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

failure_stage=executable_binding
exec {probe_fd}<"$BOUND_BUNDLE_ROOT/probe_vmvm_task_free_v2.py" || fail
exec {uv_fd}<"$UV_BIN_X86_64" || fail
readonly BOUND_PROBE="/proc/self/fd/$probe_fd"
readonly BOUND_UV="/proc/self/fd/$uv_fd"
validate_fd_file "$BOUND_PROBE" 500 "$DIAG_PROBE_SHA256" "$DIAG_PROBE_PATH"
validate_fd_file "$BOUND_UV" 755 "$X86_UV_SHA256" "$UV_BIN_X86_64"

# uv has a fixed, verified three-field child-environment delta. Restore the
# authorized environment before the sealed probe observes it, and reject any
# additional mutation by comparing the complete restored environment digest.
readonly UV_SANITIZER_PROGRAM='
import hashlib
import os
import sys

EXPECTED_PATH = "/usr/local/bin:/usr/bin:/bin"
EXPECTED_UV = "/memfd:vmvm-uv-v2 (deleted)"
RESTORED_PATH = "/usr/bin:/bin"


def fail(status=124):
    raise SystemExit(status)


def environment_sha256(environment):
    digest = hashlib.sha256()
    for name in sorted(environment):
        encoded_name = os.fsencode(name)
        encoded_value = os.fsencode(environment[name])
        if b"=" in encoded_name or b"\0" in encoded_name or b"\0" in encoded_value:
            fail()
        digest.update(encoded_name)
        digest.update(b"=")
        digest.update(encoded_value)
        digest.update(b"\0")
    return digest.hexdigest()


def main():
    if len(sys.argv) < 3 or sys.argv[0] != "-c":
        fail()
    probe_path = sys.argv[1]
    expected_environment_sha256 = sys.argv[2]
    environment = dict(os.environ)
    probe_fd = environment.get("DIAG_EXEC_PROBE_FD", "")
    if (
        not probe_fd.isdigit()
        or probe_path != f"/proc/self/fd/{probe_fd}"
        or len(expected_environment_sha256) != 64
        or any(value not in "0123456789abcdef" for value in expected_environment_sha256)
        or environment.get("UV_RUN_RECURSION_DEPTH") != "1"
        or environment.get("UV") != EXPECTED_UV
        or environment.get("PATH") != EXPECTED_PATH
    ):
        fail()
    del environment["UV_RUN_RECURSION_DEPTH"]
    del environment["UV"]
    environment["PATH"] = RESTORED_PATH
    if environment_sha256(environment) != expected_environment_sha256:
        fail(123)
    try:
        os.execve(
            "/proc/self/exe",
            ["/proc/self/exe", "-I", "-S", "-B", probe_path, *sys.argv[3:]],
            environment,
        )
    except OSError:
        fail(122)


try:
    main()
except (UnicodeError, ValueError):
    fail()
'

# Copy each executable from its already-bound descriptor into a sealed anonymous
# inode. The original pathname is never consulted by exec or by the Python
# interpreter after this point.
readonly SEALED_EXEC_PROGRAM='
import fcntl
import hashlib
import os
import stat
import sys

REQUIRED_SEALS = (
    fcntl.F_SEAL_SEAL
    | fcntl.F_SEAL_SHRINK
    | fcntl.F_SEAL_GROW
    | fcntl.F_SEAL_WRITE
    | 0x20  # F_SEAL_EXEC; absent from Python 3.12 fcntl constants.
)


def fail():
    raise SystemExit(125)


def environment_sha256(environment):
    digest = hashlib.sha256()
    for name in sorted(environment):
        encoded_name = os.fsencode(name)
        encoded_value = os.fsencode(environment[name])
        if b"=" in encoded_name or b"\0" in encoded_name or b"\0" in encoded_value:
            fail()
        digest.update(encoded_name)
        digest.update(b"=")
        digest.update(encoded_value)
        digest.update(b"\0")
    return digest.hexdigest()


def copy_sealed(source_fd, name, expected_digest, expected_mode, maximum):
    try:
        before = os.fstat(source_fd)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != expected_mode
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum
        ):
            fail()
        sealed_fd = os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        digest = hashlib.sha256()
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(source_fd, min(1 << 20, before.st_size - offset), offset)
            if not chunk:
                fail()
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(sealed_fd, view)
                if written <= 0:
                    fail()
                view = view[written:]
            offset += len(chunk)
        after = os.fstat(source_fd)
        if (
            any(getattr(before, field) != getattr(after, field) for field in stable)
            or digest.hexdigest() != expected_digest
        ):
            fail()
        os.fchmod(sealed_fd, expected_mode)
        fcntl.fcntl(sealed_fd, fcntl.F_ADD_SEALS, REQUIRED_SEALS)
        sealed = os.fstat(sealed_fd)
        sealed_digest = hashlib.sha256()
        sealed_offset = 0
        while sealed_offset < sealed.st_size:
            sealed_chunk = os.pread(
                sealed_fd,
                min(1 << 20, sealed.st_size - sealed_offset),
                sealed_offset,
            )
            if not sealed_chunk:
                fail()
            sealed_digest.update(sealed_chunk)
            sealed_offset += len(sealed_chunk)
        if (
            not stat.S_ISREG(sealed.st_mode)
            or stat.S_IMODE(sealed.st_mode) != expected_mode
            or sealed.st_uid != os.getuid()
            or sealed.st_nlink != 0
            or sealed.st_size != before.st_size
            or fcntl.fcntl(sealed_fd, fcntl.F_GET_SEALS) & REQUIRED_SEALS != REQUIRED_SEALS
            or sealed_digest.hexdigest() != expected_digest
        ):
            fail()
        os.set_inheritable(sealed_fd, True)
        return sealed_fd
    except (OSError, ValueError):
        fail()


probe_source_fd = int(sys.argv[1])
probe_digest = sys.argv[2]
uv_source_fd = int(sys.argv[3])
uv_digest = sys.argv[4]
probe_fd = copy_sealed(probe_source_fd, "vmvm-probe-v2", probe_digest, 0o500, 2 << 20)
uv_fd = copy_sealed(uv_source_fd, "vmvm-uv-v2", uv_digest, 0o755, 64 << 20)
os.close(probe_source_fd)
os.close(uv_source_fd)
public_stdout_fd = int(sys.argv[5])
public_stderr_fd = int(sys.argv[6])
for public_fd in (public_stdout_fd, public_stderr_fd):
    try:
        os.close(public_fd)
    except OSError:
        pass
environment = dict(os.environ)
environment["DIAG_EXEC_PROBE_FD"] = str(probe_fd)
environment["DIAG_EXEC_UV_FD"] = str(uv_fd)
authorized_environment_sha256 = environment_sha256(environment)
uv_path = f"/proc/self/fd/{uv_fd}"
probe_path = f"/proc/self/fd/{probe_fd}"
if (
    sys.argv[7:].count("__VMVM_PROBE__") != 1
    or sys.argv[7:].count("__VMVM_AUTHORIZED_ENVIRONMENT_SHA256__") != 1
):
    fail()
arguments = [
    probe_path
    if value == "__VMVM_PROBE__"
    else authorized_environment_sha256
    if value == "__VMVM_AUTHORIZED_ENVIRONMENT_SHA256__"
    else value
    for value in sys.argv[7:]
]
try:
    os.execve(uv_path, [uv_path, *arguments], environment)
except OSError:
    fail()
'

run_sealed_probe() {
    /usr/bin/python3 -I -S -B -c "$SEALED_EXEC_PROGRAM" \
        "$probe_fd" "$DIAG_PROBE_SHA256" "$uv_fd" "$X86_UV_SHA256" \
        "$public_stdout_fd" "$public_stderr_fd" \
        run --no-project --offline --python "$PYTHON_BIN_X86_64" \
        python3 -I -S -B -c "$UV_SANITIZER_PROGRAM" \
        __VMVM_PROBE__ __VMVM_AUTHORIZED_ENVIRONMENT_SHA256__ "$@"
}

failure_stage=sealed_builder
preflight_output=""
set +e
preflight_output=$(
    run_sealed_probe --validate-batch \
        --source-root "$BOUND_SOURCE_ROOT" --site-root "$BOUND_SITE_ROOT" \
        --scratch-root "$DIAG_SCRATCH_ROOT" \
        --output-dir "$BOUND_OUTPUT_PARENT/${DIAG_OUTPUT_ROOT##*/}" \
        --completion-receipt "$BOUND_OUTPUT_PARENT/${DIAG_COMPLETION_RECEIPT##*/}" 2>&1
)
preflight_rc=$?
set -e
if (( preflight_rc == 125 )); then
    fail
fi
if (( preflight_rc == 124 )); then
    failure_stage=uv_sanitizer
    fail
fi
if (( preflight_rc == 123 )); then
    failure_stage=uv_environment
    fail
fi
if (( preflight_rc == 122 )); then
    failure_stage=uv_probe_exec
    fail
fi
if (( preflight_rc != 0 )); then
    failure_stage=probe_admission
    fail
fi
if [[ $preflight_output != '{"state":"admitted"}' ]]; then
    failure_stage=probe_response
    fail
fi

# Publication-adjacent source and executable validation. No task/dataset input
# is opened anywhere in this wrapper or its probe.
failure_stage=post_preflight_source
validate_fd_file "$BOUND_PROBE" 500 "$DIAG_PROBE_SHA256" "$DIAG_PROBE_PATH"
validate_source "$BOUND_SOURCE_ROOT"
failure_stage=namespace_freshness
[[ ! -e $DIAG_OUTPUT_ROOT && ! -L $DIAG_OUTPUT_ROOT \
    && ! -e $DIAG_COMPLETION_RECEIPT && ! -L $DIAG_COMPLETION_RECEIPT \
    && ! -e $DIAG_SCRATCH_ROOT && ! -L $DIAG_SCRATCH_ROOT ]] || fail
failure_stage=lineage_hashes
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
printf '{"directory_identities":{"bundle":"%s","output_parent":"%s","reservation":"%s","site":"%s","source":"%s"},"stage":"prelease_admission","state":"passed"}\n' \
    "$identity_bundle" "$identity_output_parent" "$identity_reservation" \
    "$identity_site" "$identity_source" >&"$public_stdout_fd"
