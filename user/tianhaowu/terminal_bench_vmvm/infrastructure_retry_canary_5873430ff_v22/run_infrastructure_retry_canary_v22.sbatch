#!/bin/bash
#SBATCH --job-name=mobius-infra-retry-v22
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=7-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue

set -euo pipefail
umask 077

pre_admission_stage=bootstrap

fail() {
    local safe_stage
    case ${pre_admission_stage:-unknown} in
        bootstrap|artifact_binding|environment_binding|tls_binding|permit_wait|admission_artifacts|admission_receipts|source_binding|runtime_binding)
            safe_stage=$pre_admission_stage
            ;;
        *)
            safe_stage=unknown
            ;;
    esac
    /usr/bin/printf '{"code":"job_binding_failed","stage":"%s"}\n' \
        "$safe_stage" >&2
    exit 2
}

readonly SOURCE_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-5873430ff-v22
readonly WORKFLOW="$SOURCE_ROOT/user/tianhaowu/terminal_bench_vmvm"
readonly RUN_ORACLE="$WORKFLOW/run_oracle.sbatch"
readonly ARTIFACT_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/infrastructure_retry_canary_5873430ff_v22
readonly LAUNCHER="$ARTIFACT_ROOT/launch_infrastructure_retry_canary_v22.py"
readonly GENERATOR="$ARTIFACT_ROOT/build_infrastructure_retry_selection_v22.py"
readonly PACKAGING_SNAPSHOT="$ARTIFACT_ROOT/packaging-26.3-py3-none-any.whl.snapshot.json"
readonly PACKAGING_SNAPSHOT_SHA256=6025752344370d775f1a22e6c9d3f3bfaa57f9b5e17e2b296088864dfdc14761
readonly JOB_WRAPPER=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/infrastructure_retry_canary_5873430ff_v22/run_infrastructure_retry_canary_v22.sbatch
readonly DATASET=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9
readonly IMAGE_MANIFEST_EXPECTED=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.json
readonly TASK_FILE_EXPECTED=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/mobius_infrastructure_retry_selection_5873430ff_v22/retry.tasks.txt
readonly ROLE_FILE_EXPECTED=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/mobius_infrastructure_retry_selection_5873430ff_v22/selection_roles.private.json
readonly SELECTION_RECEIPT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/mobius_infrastructure_retry_selection_5873430ff_v22/selection_receipt.json
readonly OUTPUT_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/mobius_infrastructure_retry_run_5873430ff_v22
readonly RESERVATION_EXPECTED="${OUTPUT_ROOT}.launch-reservation"
readonly SOURCE_REVISION=5873430ffbabc32672368c7df74f56023865d2b5
readonly SOURCE_TREE=e7d9d5a8cf4ca06b9ff6496ea4318154c6fcd730
readonly VERIFIERS_REVISION=615b1a30ee3d23cf8d835b64174229c19da887bc
readonly RENDERERS_REVISION=044d9e2541f6a911cacae9da353fc063911ef1f8
readonly PYDANTIC_CONFIG_REVISION=896ade4e69d8d8dff2d4b0a431b7e1c7c12d638f
readonly DATASET_REVISION_EXPECTED=ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366
readonly RUN_ORACLE_SHA256=9f4e746a5a05217f43c684b1d5737a846555d284ea0fb924466358181e0d253c
readonly VMVM_SHA256=1e7c8ac2906a45d8212d609b5900fdc3d30f91ba73d4bcdb1c36dfc8bfdd09e2
readonly IMAGE_MANIFEST_SHA256_EXPECTED=118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009

require_directory() {
    local path=$1
    local expected_mode=$2
    local observed_stat
    local observed_canonical
    [[ ! -L "$path" ]] || fail
    if observed_canonical=$(/usr/bin/readlink -e -- "$path" 2>/dev/null); then
        :
    else
        fail
    fi
    if observed_stat=$(/usr/bin/stat -c '%F|%a|%U' -- "$path" 2>/dev/null); then
        :
    else
        fail
    fi
    [[ "$observed_canonical" == "$path" ]] || fail
    [[ "$observed_stat" == "directory|$expected_mode|tianhaowu" ]] || fail
}

capture_git() {
    local repository=$1
    shift
    if GIT_CAPTURE=$(
        /usr/bin/env -i \
            HOME=/nonexistent \
            PATH=/usr/bin:/bin \
            GIT_ATTR_NOSYSTEM=1 \
            GIT_CONFIG_GLOBAL=/dev/null \
            GIT_CONFIG_NOSYSTEM=1 \
            GIT_CONFIG_SYSTEM=/dev/null \
            GIT_NO_REPLACE_OBJECTS=1 \
            GIT_OPTIONAL_LOCKS=0 \
            GIT_TERMINAL_PROMPT=0 \
            LC_ALL=C \
            /usr/bin/git -C "$repository" "$@" </dev/null 2>/dev/null
    ); then
        GIT_RC=0
    else
        GIT_RC=$?
    fi
}

require_git_equal() {
    local repository=$1
    local expected=$2
    shift 2
    capture_git "$repository" "$@"
    (( GIT_RC == 0 )) || fail
    [[ "$GIT_CAPTURE" == "$expected" ]] || fail
}

require_git_empty() {
    local repository=$1
    shift
    capture_git "$repository" "$@"
    (( GIT_RC == 0 )) || fail
    [[ -z "$GIT_CAPTURE" ]] || fail
}

capture_sha256() {
    local path=$1
    if SHA_CAPTURE=$(/usr/bin/sha256sum -- "$path" 2>/dev/null); then
        SHA_RC=0
    else
        SHA_RC=$?
    fi
}

require_file() {
    local path=$1
    local expected_mode=$2
    local expected_sha=$3
    local observed_canonical
    local observed_stat
    [[ ! -L "$path" ]] || fail
    if observed_canonical=$(/usr/bin/readlink -e -- "$path" 2>/dev/null); then
        :
    else
        fail
    fi
    if observed_stat=$(/usr/bin/stat -c '%F|%a|%h|%U' -- "$path" 2>/dev/null); then
        :
    else
        fail
    fi
    [[ "$observed_canonical" == "$path" ]] || fail
    [[ "$observed_stat" == "regular file|$expected_mode|1|tianhaowu" ]] || fail
    capture_sha256 "$path"
    (( SHA_RC == 0 )) || fail
    [[ "$SHA_CAPTURE" == "$expected_sha  $path" ]] || fail
}

validate_tls_credentials() {
    /usr/bin/env -i \
        HOME=/nonexistent LANG=C LC_ALL=C PATH=/usr/bin:/bin \
        PYTHONDONTWRITEBYTECODE=1 \
        THRIFT_TLS_CL_CERT_PATH="$THRIFT_TLS_CL_CERT_PATH" \
        THRIFT_TLS_CL_KEY_PATH="$THRIFT_TLS_CL_KEY_PATH" \
        RETRY_THRIFT_TLS_CL_CERT_SHA256="$RETRY_THRIFT_TLS_CL_CERT_SHA256" \
        RETRY_THRIFT_TLS_CL_KEY_SHA256="$RETRY_THRIFT_TLS_CL_KEY_SHA256" \
        /usr/bin/python3 -I -S -B - <<'PY' >/dev/null 2>/dev/null
import base64
import binascii
import hashlib
import os
import pathlib
import re
import stat

expected_environment = {
    "HOME", "LANG", "LC_ALL", "PATH", "PYTHONDONTWRITEBYTECODE",
    "THRIFT_TLS_CL_CERT_PATH", "THRIFT_TLS_CL_KEY_PATH",
    "RETRY_THRIFT_TLS_CL_CERT_SHA256", "RETRY_THRIFT_TLS_CL_KEY_SHA256",
}

if (
    set(os.environ) != expected_environment
    or os.environ.get("HOME") != "/nonexistent"
    or os.environ.get("LANG") != "C"
    or os.environ.get("LC_ALL") != "C"
    or os.environ.get("PATH") != "/usr/bin:/bin"
    or os.environ.get("PYTHONDONTWRITEBYTECODE") != "1"
):
    raise SystemExit(2)


def identity(value):
    return (
        value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid,
        value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
    )


block_pattern = re.compile(
    rb"-----BEGIN ([A-Z][A-Z0-9 ]*)-----\r?\n"
    rb"([A-Za-z0-9+/=\r\n]+?)"
    rb"-----END \1-----"
)


def pem_profile(raw):
    labels = []
    position = 0
    for match in block_pattern.finditer(raw):
        if raw[position:match.start()].strip(b" \t\r\n"):
            return "invalid"
        compact = b"".join(match.group(2).split())
        if not compact:
            return "invalid"
        try:
            decoded = base64.b64decode(compact, validate=True)
        except (ValueError, binascii.Error):
            return "invalid"
        if not decoded:
            return "invalid"
        labels.append(match.group(1))
        position = match.end()
    if raw[position:].strip(b" \t\r\n"):
        return "invalid"
    return (
        "combined"
        if len(labels) == 3
        and labels.count(b"CERTIFICATE") == 2
        and labels.count(b"RSA PRIVATE KEY") == 1
        else "other"
    )


observed = []
for path_name, digest_name in (
    ("THRIFT_TLS_CL_CERT_PATH", "RETRY_THRIFT_TLS_CL_CERT_SHA256"),
    ("THRIFT_TLS_CL_KEY_PATH", "RETRY_THRIFT_TLS_CL_KEY_SHA256"),
):
    raw_path = os.environ[path_name]
    expected_digest = os.environ[digest_name]
    raw_path_object = pathlib.Path(raw_path)
    parent_fd = descriptor = fresh_parent = fresh_descriptor = -1
    try:
        if (
            not raw_path
            or "\x00" in raw_path
            or "\n" in raw_path
            or "\r" in raw_path
            or not raw_path_object.is_absolute()
            or raw_path_object != pathlib.Path(os.path.normpath(raw_path_object))
            or len(expected_digest) != 64
            or any(character not in "0123456789abcdef" for character in expected_digest)
        ):
            raise ValueError
        descriptor = os.open(
            raw_path_object,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        before = os.fstat(descriptor)
        canonical_raw = os.readlink(f"/proc/self/fd/{descriptor}")
        path = pathlib.Path(canonical_raw)
        if (
            not canonical_raw
            or canonical_raw.endswith(" (deleted)")
            or "\x00" in canonical_raw
            or "\n" in canonical_raw
            or "\r" in canonical_raw
            or not path.is_absolute()
            or path != pathlib.Path(os.path.normpath(path))
            or path.parent.resolve(strict=True) != path.parent
            or path.resolve(strict=True) != path
            or path.is_symlink()
            or path != raw_path_object
        ):
            raise ValueError
        parent_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        visible_before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            identity(before) != identity(visible_before)
            or not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o500
            or before.st_uid != 656177
            or before.st_nlink != 1
            or before.st_size != 5580
        ):
            raise ValueError
        chunks = []
        offset = 0
        while offset < before.st_size:
            block = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
            if not block:
                raise ValueError
            chunks.append(block)
            offset += len(block)
        raw = b"".join(chunks)
        digest = hashlib.sha256(raw).hexdigest()
        after = os.fstat(descriptor)
        visible_after = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        fresh_parent = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        fresh_descriptor = os.open(
            raw_path_object,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        if (
            identity(before) != identity(after)
            or identity(after) != identity(visible_after)
            or identity(after) != identity(os.fstat(fresh_descriptor))
            or (os.fstat(parent_fd).st_dev, os.fstat(parent_fd).st_ino)
            != (os.fstat(fresh_parent).st_dev, os.fstat(fresh_parent).st_ino)
            or os.readlink(f"/proc/self/fd/{fresh_descriptor}") != str(path)
            or digest != expected_digest
        ):
            raise ValueError
        observed.append((path, expected_digest, identity(after)[:2], pem_profile(raw)))
    finally:
        for candidate in (fresh_descriptor, fresh_parent, descriptor, parent_fd):
            if candidate >= 0:
                os.close(candidate)
same_path = observed[0][0] == observed[1][0]
same_digest = observed[0][1] == observed[1][1]
same_inode = observed[0][2] == observed[1][2]
if any((same_path, same_digest, same_inode)) and not (
    same_path
    and same_digest
    and same_inode
    and observed[0][3] == "combined"
    and observed[1][3] == "combined"
):
    raise SystemExit(2)
PY
}

validate_x2p_environment() {
    local binding name digest_name value expected_digest observed
    for binding in \
        X2P_ENV:RETRY_X2P_ENV_SHA256 \
        X2P_CFG_ENV:RETRY_X2P_CFG_ENV_SHA256 \
        X2P_PROXY_URL:RETRY_X2P_PROXY_URL_SHA256; do
        name=${binding%%:*}
        digest_name=${binding#*:}
        value=${!name}
        expected_digest=${!digest_name}
        [[ -n "$value" && "$value" != *$'\n'* && "$value" != *$'\r'* \
            && ${#value} -le 4096 && "$expected_digest" =~ ^[0-9a-f]{64}$ ]] || return 1
        if observed=$(printf '%s' "$value" | /usr/bin/sha256sum); then
            :
        else
            return 1
        fi
        [[ ${observed%%  *} == "$expected_digest" ]] || return 1
    done
}

if (( $# != 0 )); then
    fail
fi
[[ ${SLURM_JOB_ID:-} =~ ^[1-9][0-9]*$ ]] || fail
readonly PYCACHE_ROOT="/tmp/mobius-infrastructure-retry-v22-${SLURM_JOB_ID}.pycache"
pre_admission_stage=artifact_binding
require_directory "$ARTIFACT_ROOT" 700
[[ ${RETRY_JOB_WRAPPER_SHA256:-} =~ ^[0-9a-f]{64}$ ]] || fail
require_file "$JOB_WRAPPER" 500 "$RETRY_JOB_WRAPPER_SHA256"
if [[ ! -f ${BASH_SOURCE[0]} || -L ${BASH_SOURCE[0]} ]]; then
    fail
fi
capture_sha256 "${BASH_SOURCE[0]}"
(( SHA_RC == 0 )) || fail
[[ "${SHA_CAPTURE%%  *}" == "$RETRY_JOB_WRAPPER_SHA256" ]] || fail
pre_admission_stage=environment_binding
required_environment=(
    HOME LANG LC_ALL LOGNAME PATH PYTHONDONTWRITEBYTECODE
    PYTHON_BIN_X86_64 PYTHON_SITE_X86_64 SLURM_EXPORT_ENV TZ USER UV_BIN_X86_64
    PROJECT_DIR DATASET_DIR DATASET_REVISION IMAGE_PREFIX IMAGE_TAG IMAGE_MANIFEST
    IMAGE_MANIFEST_SHA256 TASK_FILE TASK_FILE_SHA256 SELECTION_ROLE_FILE
    SELECTION_ROLE_FILE_SHA256 OUTPUT_DIR MAX_CONCURRENT INFRA_RETRIES
    SETUP_TIMEOUT VALIDATE_TIMEOUT SESSION_TIMEOUT TIMEOUT_MULTIPLIER
    RESOURCE_MULTIPLIER ORACLE_SOLUTION_NETWORK_MODE MINIMUM_PASS_RATE
    MINIMUM_VALID VACLI_LEASE_RETRIES VACLI_MAX_CONCURRENT_LEASES
    VACLI_MAX_PULL_RETRIES VACLI_IMAGE_PULL_TIMEOUT_SECONDS
    VACLI_CONTAINER_PRIVILEGED RERUN_INVALID USE_DECLARED_IMAGES ENABLE_COMPOSE
    SELECTION_RECEIPT_FILE_SHA256 SELECTION_RECEIPT_SHA256 RETRY_EXCEPTION_CLASS
    ASYNCIO_TIMEOUT_MAX_ATTEMPTS BROAD_HARNESS_ERROR_RETRY
    RETRY_RESERVATION RETRY_EXPECTED_JOB_NAME RETRY_LAUNCH_TOKEN
    RETRY_LAUNCHER_SHA256 RETRY_GENERATOR_SHA256 RETRY_SOURCE_REVISION
    RETRY_SOURCE_TREE RETRY_VERIFIERS_REVISION RETRY_VMVM_SHA256
    RETRY_AUTHORIZATION_FILE RETRY_AUTHORIZATION_SHA256
    RETRY_ACTIVATION_PERMIT_FILE RETRY_ACTIVATION_PERMIT_SHA256
    RETRY_SUBMISSION_RECEIPT RETRY_WRAPPER_GATE_TIMEOUT_SECONDS
    THRIFT_TLS_CL_CERT_PATH THRIFT_TLS_CL_KEY_PATH
    RETRY_THRIFT_TLS_CL_CERT_SHA256 RETRY_THRIFT_TLS_CL_KEY_SHA256
    X2P_ENV X2P_CFG_ENV X2P_PROXY_URL
    RETRY_X2P_ENV_SHA256 RETRY_X2P_CFG_ENV_SHA256
    RETRY_X2P_PROXY_URL_SHA256
)
for variable in "${required_environment[@]}"; do
    [[ -n ${!variable:-} ]] || fail
done
if [[ "$PROJECT_DIR" != "$SOURCE_ROOT" \
    || "$HOME" != /storage/home/tianhaowu \
    || "$LANG" != C \
    || "$LC_ALL" != C \
    || "$LOGNAME" != tianhaowu \
    || "$PATH" != /usr/bin:/bin \
    || "$PYTHONDONTWRITEBYTECODE" != 1 \
    || "$PYTHON_BIN_X86_64" != python3 \
    || "$PYTHON_SITE_X86_64" != /checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64 \
    || "$SLURM_EXPORT_ENV" != NONE \
    || "$TZ" != UTC \
    || "$USER" != tianhaowu \
    || "$UV_BIN_X86_64" != /storage/home/tianhaowu/.local/x86_64/bin/uv \
    || "$DATASET_DIR" != "$DATASET" \
    || "$DATASET_REVISION" != "$DATASET_REVISION_EXPECTED" \
    || "$IMAGE_PREFIX" != vmvm-registry.fbinfra.net/terminal_bench \
    || "$IMAGE_TAG" != mobius-9b6988a3faf0 \
    || "$IMAGE_MANIFEST" != "$IMAGE_MANIFEST_EXPECTED" \
    || "$IMAGE_MANIFEST_SHA256" != "$IMAGE_MANIFEST_SHA256_EXPECTED" \
    || "$TASK_FILE" != "$TASK_FILE_EXPECTED" \
    || "$SELECTION_ROLE_FILE" != "$ROLE_FILE_EXPECTED" \
    || "$OUTPUT_DIR" != "$OUTPUT_ROOT" \
    || "$MAX_CONCURRENT" != 4 \
    || "$INFRA_RETRIES" != 4 \
    || "$SETUP_TIMEOUT" != 7200 \
    || "$VALIDATE_TIMEOUT" != 21600 \
    || "$SESSION_TIMEOUT" != 43200 \
    || "$TIMEOUT_MULTIPLIER" != 4 \
    || "$RESOURCE_MULTIPLIER" != 2 \
    || "$ORACLE_SOLUTION_NETWORK_MODE" != public \
    || "$MINIMUM_PASS_RATE" != 0 \
    || "$MINIMUM_VALID" != 10 \
    || "$VACLI_LEASE_RETRIES" != 20 \
    || "$VACLI_MAX_CONCURRENT_LEASES" != 2 \
    || "$VACLI_MAX_PULL_RETRIES" != 20 \
    || "$VACLI_IMAGE_PULL_TIMEOUT_SECONDS" != 7200 \
    || "$VACLI_CONTAINER_PRIVILEGED" != 1 \
    || "$RERUN_INVALID" != 0 \
    || "$USE_DECLARED_IMAGES" != 0 \
    || "$ENABLE_COMPOSE" != 0 \
    || "$RETRY_EXCEPTION_CLASS" != SandboxError \
    || "$ASYNCIO_TIMEOUT_MAX_ATTEMPTS" != 1 \
    || "$BROAD_HARNESS_ERROR_RETRY" != 0 \
    || "$RETRY_RESERVATION" != "$RESERVATION_EXPECTED" \
    || ! "$RETRY_LAUNCHER_SHA256" =~ ^[0-9a-f]{64}$ \
    || "$RETRY_GENERATOR_SHA256" != 4b13ea20ebf4b63057c752efe86044aa2f54a52e87426ec033fbd8e087334fad \
    || "$RETRY_SOURCE_REVISION" != "$SOURCE_REVISION" \
    || "$RETRY_SOURCE_TREE" != "$SOURCE_TREE" \
    || "$RETRY_VERIFIERS_REVISION" != "$VERIFIERS_REVISION" \
    || "$RETRY_VMVM_SHA256" != "$VMVM_SHA256" \
    || ! "$RETRY_LAUNCH_TOKEN" =~ ^[0-9a-f]{24}$ \
    || "$RETRY_EXPECTED_JOB_NAME" != "mirc-${RETRY_LAUNCH_TOKEN}" \
    || "${SLURM_JOB_NAME:-}" != "$RETRY_EXPECTED_JOB_NAME" \
    || "$RETRY_AUTHORIZATION_FILE" != "$RETRY_RESERVATION/job_authorization_${RETRY_LAUNCH_TOKEN}.json" \
    || "$RETRY_ACTIVATION_PERMIT_FILE" != "$RETRY_RESERVATION/activation_permit_${RETRY_LAUNCH_TOKEN}.json" \
    || "$RETRY_SUBMISSION_RECEIPT" != "$RETRY_RESERVATION/submission_receipt.json" \
    || "$RETRY_WRAPPER_GATE_TIMEOUT_SECONDS" != 900 \
    || ! "$RETRY_AUTHORIZATION_SHA256" =~ ^[0-9a-f]{64}$ \
    || ! "$RETRY_ACTIVATION_PERMIT_SHA256" =~ ^[0-9a-f]{64}$ \
    || ! "$TASK_FILE_SHA256" =~ ^[0-9a-f]{64}$ \
    || ! "$SELECTION_ROLE_FILE_SHA256" =~ ^[0-9a-f]{64}$ \
    || ! "$SELECTION_RECEIPT_FILE_SHA256" =~ ^[0-9a-f]{64}$ \
    || ! "$SELECTION_RECEIPT_SHA256" =~ ^[0-9a-f]{64}$ \
    || ! "$RETRY_THRIFT_TLS_CL_CERT_SHA256" =~ ^[0-9a-f]{64}$ \
    || ! "$RETRY_THRIFT_TLS_CL_KEY_SHA256" =~ ^[0-9a-f]{64}$ \
    || ! "$RETRY_X2P_ENV_SHA256" =~ ^[0-9a-f]{64}$ \
    || ! "$RETRY_X2P_CFG_ENV_SHA256" =~ ^[0-9a-f]{64}$ \
    || ! "$RETRY_X2P_PROXY_URL_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    fail
fi
validate_x2p_environment || fail
for variable in "${!BASH_FUNC_@}" "${!LD_@}" "${!GIT_@}"; do
    [[ -z "$variable" ]] || fail
done
for variable in "${!UV_@}"; do
    [[ "$variable" == UV_BIN_X86_64 ]] || fail
done
for variable in "${!PYTHON_@}"; do
    [[ "$variable" == PYTHON_BIN_X86_64 \
        || "$variable" == PYTHON_SITE_X86_64 ]] || fail
done
if [[ -n ${BASH_ENV+x} || -n ${ENV+x} || -n ${CDPATH+x} \
    || -n ${PYTHONHOME+x} || -n ${PYTHONPATH+x} || -n ${PYTHONSTARTUP+x} \
    || -n ${PYTHONINSPECT+x} || -n ${PYTHONPYCACHEPREFIX+x} \
    || -n ${PYTHONNOUSERSITE+x} || -n ${PYTHONSAFEPATH+x} \
    || -n ${VIRTUAL_ENV+x} || -n ${CONDA_PREFIX+x} ]]; then
    fail
fi
pre_admission_stage=tls_binding
validate_tls_credentials || fail

# The held job is released before its final activation permit is published.
# Wait here, before source checks, cache creation, VMVM setup, or output writes.
pre_admission_stage=permit_wait
gate_deadline=$((SECONDS + RETRY_WRAPPER_GATE_TIMEOUT_SECONDS))
while :; do
    [[ ! -e "$RETRY_RESERVATION/submission_failure.json" \
        && ! -L "$RETRY_RESERVATION/submission_failure.json" ]] || fail
    if [[ -f "$RETRY_AUTHORIZATION_FILE" \
        && -f "$RETRY_ACTIVATION_PERMIT_FILE" \
        && -f "$RETRY_SUBMISSION_RECEIPT" \
        && $(/usr/bin/stat -c '%F|%a|%U' -- "$RETRY_RESERVATION" 2>/dev/null || :) \
            == 'directory|500|tianhaowu' ]]; then
        break
    fi
    (( SECONDS < gate_deadline )) || fail
    /usr/bin/sleep 1
done

pre_admission_stage=admission_artifacts
require_directory "$RETRY_RESERVATION" 500
require_file "$RETRY_AUTHORIZATION_FILE" 400 "$RETRY_AUTHORIZATION_SHA256"
require_file "$RETRY_ACTIVATION_PERMIT_FILE" 400 "$RETRY_ACTIVATION_PERMIT_SHA256"
require_file "$LAUNCHER" 500 "$RETRY_LAUNCHER_SHA256"
require_file "$GENERATOR" 500 "$RETRY_GENERATOR_SHA256"
require_file "$PACKAGING_SNAPSHOT" 400 "$PACKAGING_SNAPSHOT_SHA256"
if gate_children=$(
    /usr/bin/find "$RETRY_RESERVATION" -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null \
        | /usr/bin/sort
); then
    :
else
    fail
fi
expected_gate_children=$(/usr/bin/printf '%s\n' \
    "$(/usr/bin/basename "$RETRY_ACTIVATION_PERMIT_FILE")" \
    "$(/usr/bin/basename "$RETRY_AUTHORIZATION_FILE")" \
    launch_intent.json slurm_environment.bin submission_receipt.json \
    | /usr/bin/sort)
[[ "$gate_children" == "$expected_gate_children" ]] || fail
[[ ! -e "$RETRY_RESERVATION/submission_failure.json" \
    && ! -L "$RETRY_RESERVATION/submission_failure.json" ]] || fail
for gate_file in \
    "$RETRY_RESERVATION/launch_intent.json" \
    "$RETRY_RESERVATION/slurm_environment.bin" \
    "$RETRY_SUBMISSION_RECEIPT"; do
    [[ ! -L "$gate_file" ]] || fail
    [[ $(/usr/bin/stat -c '%F|%a|%h|%U' -- "$gate_file" 2>/dev/null || :) \
        == 'regular file|400|1|tianhaowu' ]] || fail
done

# Validate the three canonical envelopes and bind the final receipt to this
# exact Slurm allocation.  Isolated system Python avoids the execution source.
pre_admission_stage=admission_receipts
/usr/bin/python3 -I -S -B - \
    "$RETRY_AUTHORIZATION_FILE" "$RETRY_AUTHORIZATION_SHA256" \
    "$RETRY_ACTIVATION_PERMIT_FILE" "$RETRY_ACTIVATION_PERMIT_SHA256" \
    "$RETRY_SUBMISSION_RECEIPT" "$RETRY_RESERVATION/slurm_environment.bin" \
    "$SLURM_JOB_ID" "$RETRY_EXPECTED_JOB_NAME" "$RETRY_LAUNCH_TOKEN" \
    "$RETRY_RESERVATION" "$RETRY_JOB_WRAPPER_SHA256" \
    <<'PY' >/dev/null 2>/dev/null || fail
import hashlib
import json
import os
import pathlib
import re
import sys


def pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def load(path, expected_file_hash, envelope_field):
    raw = pathlib.Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_file_hash:
        raise ValueError("hash")
    value = json.loads(raw, object_pairs_hook=pairs)
    seal = value.pop(envelope_field)
    canonical = json.dumps(
        value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    if seal != hashlib.sha256(canonical).hexdigest():
        raise ValueError("seal")
    return value


(
    auth_path,
    auth_hash,
    permit_path,
    permit_hash,
    receipt_path,
    environment_path,
    job_id,
    job_name,
    token,
    reservation,
    wrapper_hash,
) = sys.argv[1:]
auth = load(auth_path, auth_hash, "authorization_sha256")
permit = load(permit_path, permit_hash, "activation_permit_sha256")
receipt_raw = pathlib.Path(receipt_path).read_bytes()
receipt_hash = hashlib.sha256(receipt_raw).hexdigest()
receipt = json.loads(receipt_raw, object_pairs_hook=pairs)
receipt_seal = receipt.pop("submission_receipt_sha256")
canonical = json.dumps(
    receipt, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
).encode()
if receipt_seal != hashlib.sha256(canonical).hexdigest():
    raise ValueError("receipt")
scheduler = receipt.get("scheduler", {})
lifecycle = receipt.get("lifecycle", {})
held = lifecycle.get("held_validation", {})
release = lifecycle.get("release", {})
selection = receipt.get("selection", {})
auth_selection = auth.get("selection", {})
expected_selection = {
    "receipt_file_sha256": os.environ["SELECTION_RECEIPT_FILE_SHA256"],
    "receipt_sha256": os.environ["SELECTION_RECEIPT_SHA256"],
    "task_file_sha256": os.environ["TASK_FILE_SHA256"],
    "role_file_sha256": os.environ["SELECTION_ROLE_FILE_SHA256"],
    "selected": 19,
    "retry_candidates": 15,
    "controls": 4,
}
expected_x2p = {
    "X2P_ENV": os.environ["RETRY_X2P_ENV_SHA256"],
    "X2P_CFG_ENV": os.environ["RETRY_X2P_CFG_ENV_SHA256"],
    "X2P_PROXY_URL": os.environ["RETRY_X2P_PROXY_URL_SHA256"],
}
expected_policy = {
    "sandbox_error": {
        "retry_scope": "exception_type_only",
        "infra_retries": 4,
        "maximum_attempts": 5,
    },
    "asyncio_timeout_error": {
        "retry_scope": "none",
        "infra_retries": 0,
        "maximum_attempts": 1,
    },
    "timeout_category_candidates": {
        "count": 11,
        "classification_only": True,
        "category_does_not_enable_retries": True,
    },
    "timeout_bounds_seconds": {"setup": 7200, "validate": 21600, "session": 43200},
    "broad_harness_error_retry": False,
}
expected_acceptance = {
    "minimum_valid": 10,
    "all_controls_valid": True,
    "minimum_retry_recoveries": 6,
    "projected_union_valid": 2500,
}
expected_import_closure = {
    "packaging": {
        "name": "packaging",
        "version": "26.3",
        "wheel_sha256": "d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c",
        "wheel_size": 129956,
        "member_count": 29,
        "member_manifest_sha256": "d02fb4c0b14244ef8a78ef2b91c29d988754c230c977089eb0c65eb5152e6ea4",
        "snapshot": {
            "path": (
                "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/"
                "infrastructure_retry_canary_5873430ff_v22/"
                "packaging-26.3-py3-none-any.whl.snapshot.json"
            ),
            "sha256": "6025752344370d775f1a22e6c9d3f3bfaa57f9b5e17e2b296088864dfdc14761",
            "mode": "0400",
            "uid": 656177,
            "nlink": 1,
        },
        "loader": "restricted_in_memory_exact_wheel_sources_v1",
        "site_imports": False,
        "pyc_reads": False,
    }
}


allocation_categories = {
    "NumNodes": {"expected_one", "missing", "other", "zero"},
    "NodeList": {"assigned_or_other", "empty", "missing", "null_token"},
    "BatchHost": {"assigned_or_other", "empty", "missing", "null_token"},
}
mismatch_field_allowlist = {
    "Account", "Command", "Dependency", "JobId", "JobName", "MinMemoryNode",
    "NumCPUs", "NumNodes", "Partition", "QOS", "Requeue", "Restarts",
    "StdErr", "StdOut", "TimeLimit", "UserId", "WorkDir",
    "activation_JobState", "activation_NodeList", "activation_accounting",
    "activation_hold", "activation_squeue", "candidate_provenance",
    "cancellation_accounting",
    "cancellation_allocation", "cancellation_allocation_state",
    "cancellation_squeue", "cancellation_steps", "held_BatchHost",
    "held_JobState", "held_NodeList", "held_Priority", "held_Reason",
    "held_StartTime", "held_accounting", "held_squeue", "held_steps",
    "missing_JobId", "missing_JobName", "missing_UserId", "scontrol_record",
    "scontrol_unavailable",
}


def valid_fields(value):
    return (
        isinstance(value, list)
        and all(isinstance(field, str) and field in mismatch_field_allowlist for field in value)
        and value == sorted(set(value))
    )


def valid_occurrences(value, observed, polls):
    return (
        isinstance(value, dict)
        and set(value) == set(observed)
        and all(type(count) is int and 1 <= count <= polls for count in value.values())
    )


def valid_allocation_counts(counts, final, polls):
    if (
        not isinstance(counts, dict)
        or not isinstance(final, dict)
        or set(counts) != set(allocation_categories)
        or set(final) != set(allocation_categories)
    ):
        return False
    return all(
        isinstance(counts[field], dict)
        and set(counts[field]) == allowed
        and all(
            type(count) is int and count >= 0 for count in counts[field].values()
        )
        and sum(counts[field].values()) == polls
        and final[field] in allowed
        and counts[field][final[field]] >= 1
        for field, allowed in allocation_categories.items()
    )


def valid_poll(value, *, held_gate):
    if not isinstance(value, dict):
        return False
    generic = {
        "consecutive_exact",
        "converged",
        "deadline_seconds",
        "elapsed_milliseconds",
        "explicit_conflict_fields",
        "final_mismatch_fields",
        "final_scontrol_allocation_categories",
        "identity_status",
        "max_iterations",
        "mismatch_field_count",
        "mismatch_field_occurrences",
        "observed_mismatch_fields",
        "polls",
        "scontrol_allocation_category_counts",
        "telemetry_schema",
    }
    extras = (
        {
            "final_held_accounting_status",
            "final_pre_authorization_mismatch_fields",
            "held_accounting_status_counts",
            "post_authorization_mismatch_fields",
            "required_consecutive",
        }
        if held_gate
        else {"attempts", "command_outcome", "observed_state", "state_class"}
    )
    polls = value.get("polls")
    observed = value.get("observed_mismatch_fields")
    final = value.get("final_mismatch_fields")
    deadline = 982 if held_gate else 742
    max_iterations = 493 if held_gate else 373
    if not (
        set(value) == generic | extras
        and value.get("telemetry_schema") == "deadline_poll_v1"
        and value.get("deadline_seconds") == deadline
        and value.get("max_iterations") == max_iterations
        and type(polls) is int
        and 2 <= polls <= max_iterations
        and type(value.get("converged")) is bool
        and value.get("identity_status")
            in {"converged", "explicit_identity_conflict", "unavailable_or_incomplete"}
        and type(value.get("consecutive_exact")) is int
        and 0 <= value.get("consecutive_exact") <= polls
        and type(value.get("elapsed_milliseconds")) is int
        and value.get("elapsed_milliseconds") >= 0
        and valid_fields(observed)
        and value.get("mismatch_field_count") == len(observed)
        and valid_fields(final)
        and set(final).issubset(observed)
        and valid_fields(value.get("explicit_conflict_fields"))
        and set(value.get("explicit_conflict_fields")).issubset(
            {"JobId", "JobName", "UserId"}
        )
        and set(value.get("explicit_conflict_fields")).issubset(observed)
        and valid_occurrences(value.get("mismatch_field_occurrences"), observed, polls)
        and valid_allocation_counts(
            value.get("scontrol_allocation_category_counts"),
            value.get("final_scontrol_allocation_categories"),
            polls,
        )
        and value.get("converged") is True
        and value.get("identity_status") == "converged"
        and value.get("explicit_conflict_fields") == []
        and type(value.get("consecutive_exact")) is int
        and value.get("consecutive_exact") >= 2
        and final == []
    ):
        return False
    if held_gate:
        accounting = value.get("held_accounting_status_counts")
        return (
            value.get("required_consecutive") == 2
            and isinstance(accounting, dict)
            and set(accounting) == {"absent", "exact", "shape", "unavailable"}
            and all(type(count) is int and count >= 0 for count in accounting.values())
            and sum(accounting.values()) == polls
            and value.get("final_held_accounting_status")
            in {"absent", "exact", "shape", "unavailable"}
            and accounting[value.get("final_held_accounting_status")] >= 1
            and value.get("final_pre_authorization_mismatch_fields") == []
            and value.get("post_authorization_mismatch_fields") == []
        )
    return (
        value.get("attempts") == 1
        and value.get("command_outcome") in {"completed", "nonzero", "unknown"}
        and value.get("state_class") == "active"
        and value.get("observed_state") in {"PENDING", "CONFIGURING", "RUNNING"}
    )


if not (
    set(auth)
        == {
            "authorization_path",
            "cluster",
            "held_identity_required_consecutive",
            "job_name",
            "job_wrapper_sha256",
            "kind",
            "launch_token",
            "launcher_sha256",
            "module_import_closure",
            "reservation",
            "schema_version",
            "selection",
            "source_revision",
            "source_tree",
            "state",
            "verifiers_revision",
            "vmvm_tb_v2_sha256",
            "x2p_environment_sha256",
        }
    and auth.get("schema_version") == 1
    and auth.get("kind") == "terminal_bench_vmvm_infrastructure_retry_v22_job_authorization"
    and auth.get("state") == "held_identity_authorized"
    and auth.get("cluster") == "fair-cw-use2-3"
    and auth.get("job_name") == job_name
    and auth.get("launch_token") == token
    and auth.get("reservation") == reservation
    and auth.get("authorization_path") == auth_path
    and auth.get("launcher_sha256") == os.environ["RETRY_LAUNCHER_SHA256"]
    and auth.get("job_wrapper_sha256") == wrapper_hash
    and auth.get("source_revision") == os.environ["RETRY_SOURCE_REVISION"]
    and auth.get("source_tree") == os.environ["RETRY_SOURCE_TREE"]
    and auth.get("verifiers_revision") == os.environ["RETRY_VERIFIERS_REVISION"]
    and auth.get("vmvm_tb_v2_sha256") == os.environ["RETRY_VMVM_SHA256"]
    and auth.get("x2p_environment_sha256") == expected_x2p
    and auth.get("module_import_closure") == expected_import_closure
    and auth.get("held_identity_required_consecutive") == 2
    and auth_selection == expected_selection
    and set(permit)
        == {
            "authorization_sha256",
            "cluster",
            "job_name",
            "job_wrapper_sha256",
            "kind",
            "launch_token",
            "reservation",
            "schema_version",
            "state",
            "submission_receipt",
        }
    and permit.get("schema_version") == 1
    and permit.get("kind") == "terminal_bench_vmvm_infrastructure_retry_v22_activation_permit"
    and permit.get("state") == "activate"
    and permit.get("cluster") == "fair-cw-use2-3"
    and permit.get("job_name") == job_name
    and permit.get("launch_token") == token
    and permit.get("reservation") == reservation
    and permit.get("authorization_sha256") == auth_hash
    and permit.get("submission_receipt") == receipt_path
    and permit.get("job_wrapper_sha256") == wrapper_hash
    and receipt.get("kind") == "terminal_bench_vmvm_infrastructure_retry_v22_submission"
    and receipt.get("state") == "submitted"
    and receipt.get("code") is None
    and set(receipt)
        == {
            "acceptance",
            "attempt_policy",
            "automatic_union_or_promotion",
            "code",
            "environment_sha256",
            "generator_sha256",
            "intent_sha256",
            "job_wrapper_sha256",
            "kind",
            "launcher_sha256",
            "lifecycle",
            "module_import_closure",
            "scheduler",
            "schema_version",
            "selection",
            "source_revision",
            "source_tree",
            "state",
            "verifiers_revision",
            "vmvm_tb_v2_sha256",
            "x2p_environment_sha256",
        }
    and receipt.get("schema_version") == 1
    and receipt.get("launcher_sha256") == os.environ["RETRY_LAUNCHER_SHA256"]
    and receipt.get("generator_sha256") == os.environ["RETRY_GENERATOR_SHA256"]
    and receipt.get("source_revision") == auth.get("source_revision")
    and receipt.get("source_tree") == auth.get("source_tree")
    and receipt.get("source_revision") == os.environ["RETRY_SOURCE_REVISION"]
    and receipt.get("source_tree") == os.environ["RETRY_SOURCE_TREE"]
    and receipt.get("verifiers_revision") == os.environ["RETRY_VERIFIERS_REVISION"]
    and receipt.get("vmvm_tb_v2_sha256") == os.environ["RETRY_VMVM_SHA256"]
    and receipt.get("x2p_environment_sha256") == expected_x2p
    and receipt.get("job_wrapper_sha256") == wrapper_hash
    and receipt.get("attempt_policy") == expected_policy
    and receipt.get("module_import_closure") == expected_import_closure
    and receipt.get("acceptance") == expected_acceptance
    and receipt.get("environment_sha256")
        == hashlib.sha256(pathlib.Path(environment_path).read_bytes()).hexdigest()
    and receipt.get("intent_sha256")
        == hashlib.sha256(
            (pathlib.Path(reservation) / "launch_intent.json").read_bytes()
        ).hexdigest()
    and set(scheduler)
        == {
            "cluster",
            "job_id",
            "job_name",
            "launch_token",
            "submission_attempts",
            "submitted_held",
            "time_limit",
        }
    and scheduler.get("cluster") == "fair-cw-use2-3"
    and scheduler.get("job_id") == job_id
    and scheduler.get("job_name") == job_name
    and scheduler.get("launch_token") == token
    and scheduler.get("submission_attempts") == 1
    and scheduler.get("submitted_held") is True
    and scheduler.get("time_limit") == "7-00:00:00"
    and set(lifecycle)
        == {
            "activation_permit",
            "authorization",
            "cancellation",
            "held_validation",
            "protocol",
            "release",
        }
    and lifecycle.get("protocol") == "held_two_phase_deadline_v2"
    and lifecycle.get("authorization")
        == {"mode": "0400", "path": auth_path, "sha256": auth_hash}
    and lifecycle.get("activation_permit")
        == {
            "mode": "0400",
            "path": permit_path,
            "published_last": True,
            "sha256": permit_hash,
        }
    and lifecycle.get("cancellation") is None
    and valid_poll(held, held_gate=True)
    and valid_poll(release, held_gate=False)
    and selection == expected_selection
    and selection == auth_selection
    and receipt.get("automatic_union_or_promotion") is False
    and receipt_hash == hashlib.sha256(pathlib.Path(receipt_path).read_bytes()).hexdigest()
):
    raise ValueError("binding")
PY

pre_admission_stage=source_binding
require_directory "$SOURCE_ROOT" 755
require_directory "$DATASET" 755

require_git_equal "$SOURCE_ROOT" "$SOURCE_REVISION" rev-parse --verify HEAD
require_git_equal "$SOURCE_ROOT" "$SOURCE_TREE" rev-parse 'HEAD^{tree}'
capture_git "$SOURCE_ROOT" symbolic-ref -q HEAD
(( GIT_RC == 1 )) || fail
[[ -z "$GIT_CAPTURE" ]] || fail
require_git_empty "$SOURCE_ROOT" status --porcelain=v1 --untracked-files=all --ignore-submodules=none
require_git_empty "$SOURCE_ROOT" ls-files --others --ignored --exclude-standard -- ':(glob)**/_version.py'
for binding in \
    "deps/verifiers:$VERIFIERS_REVISION" \
    "deps/renderers:$RENDERERS_REVISION" \
    "deps/pydantic-config:$PYDANTIC_CONFIG_REVISION"; do
    dependency=${binding%%:*}
    revision=${binding#*:}
    require_git_equal "$SOURCE_ROOT" "$revision" rev-parse "HEAD:$dependency"
    require_git_equal "$SOURCE_ROOT/$dependency" "$revision" rev-parse HEAD
    capture_git "$SOURCE_ROOT/$dependency" symbolic-ref -q HEAD
    (( GIT_RC == 1 )) || fail
    [[ -z "$GIT_CAPTURE" ]] || fail
    require_git_empty "$SOURCE_ROOT/$dependency" status --porcelain=v1 --untracked-files=all
    require_git_empty "$SOURCE_ROOT/$dependency" ls-files --others --ignored --exclude-standard -- ':(glob)**/_version.py'
done

require_git_equal "$DATASET" "$DATASET_REVISION_EXPECTED" rev-parse --verify HEAD
capture_git "$DATASET" symbolic-ref -q HEAD
(( GIT_RC == 1 )) || fail
[[ -z "$GIT_CAPTURE" ]] || fail
require_git_empty "$DATASET" status --porcelain=v1 --untracked-files=all --ignore-submodules=none
require_git_empty "$DATASET" ls-files --others --ignored --exclude-standard -- ':(glob)**/_version.py'

require_file "$RUN_ORACLE" 644 "$RUN_ORACLE_SHA256"
require_file "$IMAGE_MANIFEST_EXPECTED" 644 "$IMAGE_MANIFEST_SHA256_EXPECTED"
require_file "$TASK_FILE_EXPECTED" 600 "$TASK_FILE_SHA256"
require_file "$ROLE_FILE_EXPECTED" 600 "$SELECTION_ROLE_FILE_SHA256"
require_file "$SELECTION_RECEIPT" 600 "$SELECTION_RECEIPT_FILE_SHA256"

if task_count=$(/usr/bin/wc -l <"$TASK_FILE_EXPECTED" 2>/dev/null); then
    :
else
    fail
fi
[[ "$task_count" == 19 ]] || fail
if observed_vmvm_sha256=$(
    cd "$SOURCE_ROOT"
    /usr/bin/sha256sum environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/*.py \
        | /usr/bin/sha256sum \
        | /usr/bin/cut -d' ' -f1
); then
    :
else
    fail
fi
[[ "$observed_vmvm_sha256" == "$VMVM_SHA256" ]] || fail
[[ ! -e "$OUTPUT_ROOT" && ! -L "$OUTPUT_ROOT" ]] || fail
[[ ! -e "$PYCACHE_ROOT" && ! -L "$PYCACHE_ROOT" ]] || fail
pre_admission_stage=runtime_binding
if /usr/bin/mkdir --mode=0700 -- "$PYCACHE_ROOT" 2>/dev/null; then
    :
else
    fail
fi
/usr/bin/chmod 0500 -- "$PYCACHE_ROOT" || fail
require_directory "$PYCACHE_ROOT" 500
set +e
PYCACHE_CONTENT=$(
    /usr/bin/find "$PYCACHE_ROOT" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null
)
PYCACHE_FIND_RC=$?
set -e
if (( PYCACHE_FIND_RC != 0 )) || [[ -n "$PYCACHE_CONTENT" ]]; then
    fail
fi

unset PYTHONHOME PYTHONPATH
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export PYTHONSAFEPATH=1
export PYTHONPYCACHEPREFIX="$PYCACHE_ROOT"

# Reopen and rehash both caller-bound credentials at the last batch-admission
# boundary.  The validator has an exact env allowlist and emits no path, digest,
# or file content on any outcome.
validate_tls_credentials || fail

# run_oracle.py retries only SandboxError. asyncio.TimeoutError and every broad
# harness/unknown exception remain single-attempt; the exact source hash above
# makes this semantic part of the launch binding.
exec /bin/bash "$RUN_ORACLE"
