#!/usr/bin/bash
# Task-free, one-cell VMVM renewer-owner and forced-resume diagnostic.

set -euo pipefail
umask 077

if [[ ${VMVM_DIRECTORY_BINDING_STAGE:-} == bound \
    && ${VMVM_PUBLIC_STDOUT_FD:-} =~ ^([3-9]|[1-9][0-9]+)$ \
    && ${VMVM_PUBLIC_STDERR_FD:-} =~ ^([3-9]|[1-9][0-9]+)$ \
    && -e /proc/self/fd/${VMVM_PUBLIC_STDOUT_FD:-0} \
    && -e /proc/self/fd/${VMVM_PUBLIC_STDERR_FD:-0} ]]; then
    public_stdout_fd=$VMVM_PUBLIC_STDOUT_FD
    public_stderr_fd=$VMVM_PUBLIC_STDERR_FD
else
    exec {public_stdout_fd}>&1 || exit 2
    exec {public_stderr_fd}>&2 || exit 2
fi
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
            probe_admission|probe_response|post_admission_source|\
            namespace_freshness|lineage_hashes|probe_execution|probe_aggregate|\
            post_diagnostic_source|signal|internal) ;;
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

readonly SOURCE_REVISION=9d7841b36bafcd58769041925b00deba7c25ffca
readonly SOURCE_TREE=7f4027723ab036b888b1baee8c0d51c962653f68
readonly VERIFIERS_REVISION=615b1a30ee3d23cf8d835b64174229c19da887bc
readonly RENDERERS_REVISION=044d9e2541f6a911cacae9da353fc063911ef1f8
readonly PYDANTIC_CONFIG_REVISION=896ade4e69d8d8dff2d4b0a431b7e1c7c12d638f
readonly BACKEND_SHA256=13ba697362a00f8ee8112d2459a7d1c62e5f6b4c02a84c33ac662a7b0ac9f60a
readonly BACKEND_RELATIVE_PATH=environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/backend.py
readonly X86_UV_SHA256=ec831939765474162efb6c8c813e2b10908b26b04eaf98ac3e2972fa12d189b9
readonly VACLI_SHA256=8be49a764bd0fac1a3ef2bef053ced556d18397d44642660eb8a2d22a7c235b3
readonly VACLI_RESOLVED=/infra/public/fbpkgs/x86_64/vacli/794/vacli
readonly DIRECTORY_IDENTITY_POLICY=nfs_portable_inode_mode_uid_anchored_v2
readonly JOB_SECONDS=5400 SIGNAL_LEAD_SECONDS=600 STAGE_TIMEOUT_SECONDS=1800
readonly ADMISSION_TIMEOUT_SECONDS=300 SUPERVISOR_TIMEOUT_SECONDS=2700
readonly TIMEOUT_KILL_GRACE_SECONDS=120 TIMEOUT_KILL_GRACE_COUNT=2
readonly FINALIZATION_BUDGET_SECONDS=600
(( STAGE_TIMEOUT_SECONDS < SUPERVISOR_TIMEOUT_SECONDS \
    && DIAG_WRAPPER_GATE_TIMEOUT_SECONDS + ADMISSION_TIMEOUT_SECONDS \
        + SUPERVISOR_TIMEOUT_SECONDS + FINALIZATION_BUDGET_SECONDS \
        + TIMEOUT_KILL_GRACE_COUNT * TIMEOUT_KILL_GRACE_SECONDS \
    < JOB_SECONDS - SIGNAL_LEAD_SECONDS )) || fail

readonly DIRECTORY_BINDER_PROGRAM='
import os
import fcntl
import hashlib
import stat
import sys

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
LABELS = ("bundle", "source", "site", "reservation", "output_parent")
MAX_WRAPPER_BYTES = 1 << 20
OWNER_UID = 656177
READ_CHUNK_BYTES = 1 << 14
WRAPPER_MODE = 0o500


class BindingError(RuntimeError):
    def __init__(self, label):
        self.label = label


def signature(descriptor):
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        raise BindingError("not_checked")
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid


def file_signature(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def directory_event_signature(info):
    if not stat.S_ISDIR(info.st_mode):
        raise BindingError("bundle")
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def expected_wrapper():
    digest = os.environ.get("DIAG_WRAPPER_SHA256", "")
    size_value = os.environ.get("DIAG_WRAPPER_SIZE", "")
    if (
        len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or not size_value.isdecimal()
        or str(int(size_value)) != size_value
    ):
        raise BindingError("bundle")
    size = int(size_value)
    if size < 1 or size > MAX_WRAPPER_BYTES:
        raise BindingError("bundle")
    return digest, size


def read_verified_wrapper(bundle_fd, wrapper_path):
    expected_digest, expected_size = expected_wrapper()
    name = os.path.basename(wrapper_path)
    descriptor = -1
    try:
        bundle_before = os.fstat(bundle_fd)
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=bundle_fd,
        )
        before = os.fstat(descriptor)
        named_before = os.stat(name, dir_fd=bundle_fd, follow_symlinks=False)
        if (
            file_signature(before) != file_signature(named_before)
            or not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != WRAPPER_MODE
            or os.getuid() != OWNER_UID
            or before.st_uid != OWNER_UID
            or before.st_nlink != 1
            or before.st_size != expected_size
        ):
            raise BindingError("bundle")
        raw = bytearray()
        while len(raw) < expected_size:
            chunk = os.read(descriptor, min(READ_CHUNK_BYTES, expected_size - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        extra = os.read(descriptor, 1)
        after = os.fstat(descriptor)
        named_after = os.stat(name, dir_fd=bundle_fd, follow_symlinks=False)
        bundle_after = os.fstat(bundle_fd)
    except OSError as error:
        raise BindingError("bundle") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        directory_event_signature(bundle_before) != directory_event_signature(bundle_after)
        or file_signature(before) != file_signature(after)
        or file_signature(before) != file_signature(named_after)
        or len(raw) != expected_size
        or extra
        or hashlib.sha256(raw).hexdigest() != expected_digest
    ):
        raise BindingError("bundle")
    return bytes(raw)


def sealed_wrapper(raw):
    flags = os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING
    required_seals = (
        fcntl.F_SEAL_WRITE
        | fcntl.F_SEAL_GROW
        | fcntl.F_SEAL_SHRINK
        | fcntl.F_SEAL_SEAL
        | 0x20  # F_SEAL_EXEC; absent from Python 3.12 fcntl constants.
    )
    allowed_seals = required_seals | 0x10  # Kernel may imply F_SEAL_FUTURE_WRITE.
    descriptor = os.memfd_create("vmvm-owner-wrapper-v2", flags)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written < 1:
                raise BindingError("bundle")
            offset += written
        os.fchmod(descriptor, WRAPPER_MODE)
        os.fsync(descriptor)
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, required_seals)
        status = os.fstat(descriptor)
        observed_seals = fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)
        if (
            observed_seals & required_seals != required_seals
            or observed_seals & ~allowed_seals
            or not stat.S_ISREG(status.st_mode)
            or stat.S_IMODE(status.st_mode) != WRAPPER_MODE
            or os.getuid() != OWNER_UID
            or status.st_uid != OWNER_UID
            or status.st_nlink != 0
            or status.st_size != len(raw)
            or os.pread(descriptor, len(raw) + 1, 0) != raw
        ):
            raise BindingError("bundle")
        os.set_inheritable(descriptor, True)
        if not os.get_inheritable(descriptor):
            raise BindingError("bundle")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def open_anchored_directory(raw_path, label):
    if (
        not raw_path.startswith("/")
        or raw_path.startswith("//")
        or raw_path != os.path.normpath(raw_path)
        or any(part in ("", ".", "..") for part in raw_path.split("/")[1:])
    ):
        raise BindingError(label)
    components = raw_path.split("/")[1:]
    chains = []
    result = -1
    try:
        for _pass in range(2):
            chain = [os.open("/", FLAGS)]
            chains.append(chain)
            for component in components:
                chain.append(os.open(component, FLAGS, dir_fd=chain[-1]))
        if [[signature(descriptor) for descriptor in chain] for chain in chains][0] != [
            signature(descriptor) for descriptor in chains[1]
        ]:
            raise BindingError(label)
        result = os.dup(chains[0][-1])
        return result
    except OSError as error:
        raise BindingError(label) from error
    finally:
        for chain in chains:
            for descriptor in reversed(chain):
                os.close(descriptor)


def abort(label):
    identities = {name: "not_checked" for name in LABELS}
    if label in identities:
        identities[label] = "unreadable"
    payload = (
        "{\"code\":\"diagnostic_job_failed\",\"directory_identities\":"
        "{\"bundle\":\"%s\",\"output_parent\":\"%s\","
        "\"reservation\":\"%s\",\"site\":\"%s\",\"source\":\"%s\"},"
        "\"stage\":\"directory_open\",\"state\":\"failed\"}\n"
        % (
            identities["bundle"],
            identities["output_parent"],
            identities["reservation"],
            identities["site"],
            identities["source"],
        )
    ).encode("ascii")
    try:
        os.write(int(sys.argv[2]), payload)
    except BaseException:
        pass
    raise SystemExit(2)


def main():
    if len(sys.argv) != 9:
        raise BindingError("not_checked")
    public_fds = [int(sys.argv[1]), int(sys.argv[2])]
    if any(descriptor < 3 for descriptor in public_fds):
        raise BindingError("not_checked")
    wrapper_path = sys.argv[3]
    raw_paths = dict(zip(LABELS, sys.argv[4:], strict=True))
    descriptors = {
        label: open_anchored_directory(raw_paths[label], label) for label in LABELS
    }
    if (
        os.path.dirname(wrapper_path) != raw_paths["bundle"]
        or os.path.basename(wrapper_path) != "run_vmvm_owner_lifecycle_v2.sbatch"
    ):
        raise BindingError("bundle")
    wrapper_raw = read_verified_wrapper(descriptors["bundle"], wrapper_path)
    wrapper_fd = sealed_wrapper(wrapper_raw)
    inherited = [*public_fds, *descriptors.values(), wrapper_fd]
    if len(set(inherited)) != len(inherited):
        raise BindingError("not_checked")
    for descriptor in inherited:
        os.set_inheritable(descriptor, True)
    environment = dict(os.environ)
    environment.update(
        {
            "VMVM_DIRECTORY_BINDING_STAGE": "bound",
            "VMVM_PUBLIC_STDOUT_FD": str(public_fds[0]),
            "VMVM_PUBLIC_STDERR_FD": str(public_fds[1]),
            **{
                f"VMVM_BOUND_{label.upper()}_FD": str(descriptor)
                for label, descriptor in descriptors.items()
            },
        }
    )
    os.execve(
        "/usr/bin/bash",
        ["/usr/bin/bash", f"/proc/self/fd/{wrapper_fd}"],
        environment,
    )


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        abort(error.label if isinstance(error, BindingError) else "not_checked")
'

required_environment=(
    DIAG_ACTIVATION_PERMIT DIAG_AUTHORIZATION DIAG_AUTHORIZATION_FILE_SHA256
    DIAG_AUTHORIZATION_SHA256
    DIAG_BUNDLE_IDENTITY DIAG_BUNDLE_PORTABLE_IDENTITY DIAG_BUNDLE_ROOT
    DIAG_COMPLETION_RECEIPT DIAG_PROBE_FAILURE_RECEIPT
    DIAG_DIRECTORY_IDENTITY_POLICY DIAG_FINALIZER_PATH
    DIAG_FINALIZER_SHA256 DIAG_JOB_AUTHORIZATION
    DIAG_JOB_NAME DIAG_LAUNCHER_PATH DIAG_LAUNCHER_SHA256 DIAG_OUTPUT_ROOT
    DIAG_OUTPUT_PARENT_IDENTITY DIAG_OUTPUT_PARENT_PORTABLE_IDENTITY
    DIAG_PROBE_PATH DIAG_PROBE_SHA256 DIAG_RESERVATION
    DIAG_RESERVATION_IDENTITY DIAG_RESERVATION_PORTABLE_IDENTITY
    DIAG_SCRATCH_ROOT DIAG_SOURCE_IDENTITY DIAG_SOURCE_PORTABLE_IDENTITY
    DIAG_SOURCE_REVISION DIAG_SOURCE_ROOT
    DIAG_SOURCE_TREE DIAG_SUBMISSION_RECEIPT DIAG_BACKEND_SHA256
    DIAG_WRAPPER_GATE_TIMEOUT_SECONDS DIAG_WRAPPER_PATH DIAG_WRAPPER_SHA256
    DIAG_WRAPPER_SIZE
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
bound_environment=(
    VMVM_BOUND_BUNDLE_FD VMVM_BOUND_OUTPUT_PARENT_FD VMVM_BOUND_RESERVATION_FD
    VMVM_BOUND_SITE_FD VMVM_BOUND_SOURCE_FD VMVM_DIRECTORY_BINDING_STAGE
    VMVM_PUBLIC_STDERR_FD VMVM_PUBLIC_STDOUT_FD
)
directory_binding_ready=0
if [[ -z ${VMVM_DIRECTORY_BINDING_STAGE+x} ]]; then
    for variable in "${bound_environment[@]}"; do
        [[ -z ${!variable+x} ]] || fail
    done
elif [[ $VMVM_DIRECTORY_BINDING_STAGE == bound ]]; then
    directory_binding_ready=1
    for variable in "${bound_environment[@]}"; do
        [[ -n ${!variable:-} ]] || fail
    done
    for variable in VMVM_BOUND_BUNDLE_FD VMVM_BOUND_OUTPUT_PARENT_FD \
        VMVM_BOUND_RESERVATION_FD VMVM_BOUND_SITE_FD VMVM_BOUND_SOURCE_FD \
        VMVM_PUBLIC_STDERR_FD VMVM_PUBLIC_STDOUT_FD; do
        [[ ${!variable} =~ ^([3-9]|[1-9][0-9]+)$ && -e /proc/self/fd/${!variable} ]] || fail
    done
else
    fail
fi

failure_stage=fixed_environment
if [[ $DIAG_SOURCE_REVISION != "$SOURCE_REVISION" \
    || $DIAG_SOURCE_TREE != "$SOURCE_TREE" \
    || $DIAG_BACKEND_SHA256 != "$BACKEND_SHA256" \
    || $DIAG_DIRECTORY_IDENTITY_POLICY != "$DIRECTORY_IDENTITY_POLICY" \
    || $DIAG_WRAPPER_GATE_TIMEOUT_SECONDS != 600 \
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
    || $VACLI_LEASE_RETRIES != 1 \
    || $VACLI_MAX_CONCURRENT_LEASES != 1 \
    || $VACLI_MAX_PULL_RETRIES != 1 ]]; then
    fail
fi
failure_stage=path_shape
for value in "$DIAG_BUNDLE_ROOT" "$DIAG_LAUNCHER_PATH" "$DIAG_WRAPPER_PATH" \
    "$DIAG_PROBE_PATH" "$DIAG_FINALIZER_PATH" "$DIAG_SOURCE_ROOT" \
    "$DIAG_OUTPUT_ROOT" "$DIAG_COMPLETION_RECEIPT" "$DIAG_PROBE_FAILURE_RECEIPT" \
    "$DIAG_RESERVATION" "$DIAG_SCRATCH_ROOT" "$DIAG_AUTHORIZATION" \
    "$DIAG_JOB_AUTHORIZATION" "$DIAG_ACTIVATION_PERMIT" \
    "$DIAG_SUBMISSION_RECEIPT" "$PYTHON_SITE_X86_64" "$UV_BIN_X86_64" \
    "$VACLI_BIN" "$THRIFT_TLS_CL_CERT_PATH" "$THRIFT_TLS_CL_KEY_PATH"; do
    [[ $value == /* && $value != *$'\n'* && $value != *$'\r'* ]] || fail
done
failure_stage=digest_shape
for value in "$DIAG_AUTHORIZATION_FILE_SHA256" "$DIAG_AUTHORIZATION_SHA256" \
    "$DIAG_BACKEND_SHA256" "$DIAG_LAUNCHER_SHA256" \
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
    && $PYTHON_SITE_X86_64_TOTAL_BYTES =~ ^[1-9][0-9]*$ \
    && $DIAG_WRAPPER_SIZE =~ ^[1-9][0-9]*$ ]] || fail

if (( directory_binding_ready == 0 )); then
    failure_stage=directory_open
    exec /usr/bin/python3 -I -S -B -c "$DIRECTORY_BINDER_PROGRAM" \
        "$public_stdout_fd" "$public_stderr_fd" "$DIAG_WRAPPER_PATH" \
        "$DIAG_BUNDLE_ROOT" "$DIAG_SOURCE_ROOT" "$PYTHON_SITE_X86_64" \
        "$DIAG_RESERVATION" "${DIAG_OUTPUT_ROOT%/*}"
fi

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
bundle_fd=$VMVM_BOUND_BUNDLE_FD
source_fd=$VMVM_BOUND_SOURCE_FD
site_fd=$VMVM_BOUND_SITE_FD
reservation_fd=$VMVM_BOUND_RESERVATION_FD
output_parent_fd=$VMVM_BOUND_OUTPUT_PARENT_FD
unset VMVM_BOUND_BUNDLE_FD VMVM_BOUND_OUTPUT_PARENT_FD VMVM_BOUND_RESERVATION_FD
unset VMVM_BOUND_SITE_FD VMVM_BOUND_SOURCE_FD VMVM_DIRECTORY_BINDING_STAGE
unset VMVM_PUBLIC_STDERR_FD VMVM_PUBLIC_STDOUT_FD
[[ -d /proc/self/fd/$bundle_fd \
    && $(/usr/bin/readlink -- "/proc/self/fd/$bundle_fd") == "$DIAG_BUNDLE_ROOT" ]] || {
    identity_bundle=unreadable
    fail
}
[[ -d /proc/self/fd/$source_fd \
    && $(/usr/bin/readlink -- "/proc/self/fd/$source_fd") == "$DIAG_SOURCE_ROOT" ]] || {
    identity_source=unreadable
    fail
}
[[ -d /proc/self/fd/$site_fd \
    && $(/usr/bin/readlink -- "/proc/self/fd/$site_fd") == "$PYTHON_SITE_X86_64" ]] || {
    identity_site=unreadable
    fail
}
[[ -d /proc/self/fd/$reservation_fd \
    && $(/usr/bin/readlink -- "/proc/self/fd/$reservation_fd") == "$DIAG_RESERVATION" ]] || {
    identity_reservation=unreadable
    fail
}
[[ -d /proc/self/fd/$output_parent_fd \
    && $(/usr/bin/readlink -- "/proc/self/fd/$output_parent_fd") == "${DIAG_OUTPUT_ROOT%/*}" ]] || {
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
        README.md|finalize_vmvm_owner_lifecycle_v2.py|launch_vmvm_owner_lifecycle_v2.py|probe_vmvm_owner_lifecycle_v2.py|\
            run_vmvm_owner_lifecycle_v2.sbatch|test_vmvm_owner_lifecycle_v2.py) ;;
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
    local value status_rc ignored_rc
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
}

readonly BACKEND_VALIDATOR_PROGRAM='
import hashlib
import os
import stat
import sys


def abort():
    raise SystemExit(126)


def main():
    if len(sys.argv) != 3 or not sys.argv[1].isdigit():
        abort()
    descriptor = os.dup(int(sys.argv[1]))
    try:
        for component in ("environments", "vmvm_tb_v2", "vmvm_tb_v2", "_vacli"):
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
                abort()
        backend = os.open("backend.py", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor)
        before = os.fstat(backend)
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(backend, 1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(backend)
        fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
        if (
            any(getattr(before, field) != getattr(after, field) for field in fields)
            or not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o444
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or size != before.st_size
            or digest.hexdigest() != sys.argv[2]
        ):
            abort()
    except (OSError, ValueError):
        abort()


main()
'

validate_backend() {
    /usr/bin/python3 -I -S -B -c "$BACKEND_VALIDATOR_PROGRAM" "$source_fd" "$BACKEND_SHA256" \
        >/dev/null 2>&1 || fail
}

readonly COMPUTE_CLEANUP_VALIDATOR_PROGRAM='
import hashlib
import json
import os
import stat
import sys


def abort():
    raise SystemExit(127)


def identity(descriptor):
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        abort()
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "owner_uid": info.st_uid,
    }


def anchored(path):
    if not path.startswith("/") or os.path.normpath(path) != path:
        abort()
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    for component in path.split("/")[1:]:
        if not component or component in (".", ".."):
            abort()
        child = os.open(
            component,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=descriptor,
        )
        os.close(descriptor)
        descriptor = child
    return descriptor


def main():
    if len(sys.argv) != 4 or not sys.argv[1].isdigit() or "/" in sys.argv[2]:
        abort()
    output_fd = os.open(
        sys.argv[2],
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=int(sys.argv[1]),
    )
    certificate_fd = os.open("diagnostic_certificate.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=output_fd)
    before = os.fstat(certificate_fd)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o400
        or before.st_uid != os.getuid()
        or before.st_nlink != 1
        or not 0 < before.st_size <= (1 << 20)
    ):
        abort()
    raw = os.read(certificate_fd, before.st_size + 1)
    after = os.fstat(certificate_fd)
    fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
    if any(getattr(before, field) != getattr(after, field) for field in fields) or len(raw) != before.st_size:
        abort()
    try:
        certificate = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        abort()
    if json.dumps(certificate, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n" != raw:
        abort()
    expected = certificate.get("execution_inputs", {}).get("scratch_cleanup_attestation")
    if (
        not isinstance(expected, dict)
        or set(expected)
        != {"path_sha256", "retained_empty", "root_identity_sha256", "scope", "verified"}
        or expected.get("path_sha256") != hashlib.sha256(os.fsencode(sys.argv[3])).hexdigest()
        or expected.get("retained_empty") is not True
        or expected.get("scope") != "compute_node_local"
        or expected.get("verified") is not True
    ):
        abort()
    scratch_fd = anchored(sys.argv[3])
    observed = identity(scratch_fd)
    encoded = json.dumps(observed, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    if (
        observed["mode"] != 0o700
        or observed["owner_uid"] != os.getuid()
        or hashlib.sha256(encoded).hexdigest() != expected.get("root_identity_sha256")
    ):
        abort()
    if os.listdir(scratch_fd):
        abort()


main()
'

validate_compute_cleanup_attestation() {
    /usr/bin/python3 -I -S -B -c "$COMPUTE_CLEANUP_VALIDATOR_PROGRAM" \
        "$output_parent_fd" "${DIAG_OUTPUT_ROOT##*/}" "$DIAG_SCRATCH_ROOT" \
        >/dev/null 2>&1 || fail
}

readonly FAILURE_CLEANUP_VALIDATOR_PROGRAM='
import os
import stat
import sys


def anchored(path):
    if not path.startswith("/") or path.startswith("//") or os.path.normpath(path) != path:
        raise OSError
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    for component in path.split("/")[1:]:
        if not component or component in (".", ".."):
            raise OSError
        child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
        os.close(descriptor)
        descriptor = child
    return descriptor


def main():
    if len(sys.argv) == 2:
        path = sys.argv[1]
        parent_fd = anchored(os.path.dirname(path))
        name = os.path.basename(path)
    elif len(sys.argv) == 3 and sys.argv[1].isdigit() and "/" not in sys.argv[2]:
        parent_fd = os.dup(int(sys.argv[1]))
        name = sys.argv[2]
    else:
        raise SystemExit(2)
    if not name or name in (".", ".."):
        raise SystemExit(2)
    try:
        try:
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            print("verified", end="")
            return
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            observed = os.fstat(descriptor)
            fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink")
            if (
                any(getattr(named, field) != getattr(observed, field) for field in fields)
                or not stat.S_ISDIR(observed.st_mode)
                or stat.S_IMODE(observed.st_mode) != 0o700
                or observed.st_uid != os.getuid()
                or os.listdir(descriptor)
            ):
                raise OSError
            print("verified", end="")
        finally:
            os.close(descriptor)
    except OSError:
        print("unverified", end="")
    finally:
        os.close(parent_fd)


main()
'

failure_cleanup_status() {
    local path=$1
    /usr/bin/python3 -I -S -B -c "$FAILURE_CLEANUP_VALIDATOR_PROGRAM" \
        "$path" 2>/dev/null || printf unverified
}

failure_cleanup_status_at() {
    local parent_fd=$1 name=$2
    /usr/bin/python3 -I -S -B -c "$FAILURE_CLEANUP_VALIDATOR_PROGRAM" \
        "$parent_fd" "$name" 2>/dev/null || printf unverified
}

readonly FAILURE_RECEIPT_WRITER_PROGRAM='
import ctypes
import errno
import hashlib
import json
import os
import re
import signal
import stat
import sys

RENAME_NOREPLACE = 1
SHA = re.compile(r"[0-9a-f]{64}")
FAILURES = {
    "backend_cancelled", "backend_container", "backend_fifo_wiring",
    "backend_lease", "backend_sshd", "backend_tunnel", "child_invalid",
    "child_output_overflow", "child_timeout", "cleanup_failed",
    "command_result_invalid", "direct_client_failed", "lease_budget_exceeded",
    "renewer_identity_reused", "renewer_not_alive", "resume_failed",
    "runtime_initial_workdir_rc255", "runtime_other", "source_binding_invalid",
    "site_binding_invalid", "stage_result_invalid", "thread_failed", "unclassified",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def same(left, right):
    fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def rename_noreplace(parent_fd, source, target):
    renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    result = renameat2(
        parent_fd,
        os.fsencode(source),
        parent_fd,
        os.fsencode(target),
        RENAME_NOREPLACE,
    )
    if result != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def main():
    if len(sys.argv) != 13:
        raise SystemExit(2)
    parent_fd = int(sys.argv[1])
    target, failure_class, cleanup_status = sys.argv[2:5]
    hashes = sys.argv[5:11]
    job_id, job_name = sys.argv[11:13]
    parent = os.fstat(parent_fd)
    if (
        parent_fd < 3
        or "/" in target
        or target in ("", ".", "..")
        or failure_class not in FAILURES
        or cleanup_status not in {"verified", "unverified"}
        or any(SHA.fullmatch(value) is None for value in hashes)
        or re.fullmatch(r"[1-9][0-9]*", job_id) is None
        or re.fullmatch(r"vmvm-owner-v2-[0-9a-f]{24}", job_name) is None
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.getuid()
    ):
        raise SystemExit(2)
    (
        authorization_file_sha256,
        authorization_sha256,
        environment_sha256,
        job_authorization_sha256,
        submission_receipt_sha256,
        probe_sha256,
    ) = hashes
    payload = canonical({
        "artifact_type": "vmvm_owner_lifecycle_probe_failure_receipt_v2",
        "authorization_file_sha256": authorization_file_sha256,
        "authorization_sha256": authorization_sha256,
        "backend_sha256": "13ba697362a00f8ee8112d2459a7d1c62e5f6b4c02a84c33ac662a7b0ac9f60a",
        "cleanup_status": cleanup_status,
        "diagnostic_only": True,
        "environment_sha256": environment_sha256,
        "failure_class": failure_class,
        "job": {"cluster": "fair-cw-use2-3", "job_id": job_id, "job_name": job_name},
        "job_authorization_sha256": job_authorization_sha256,
        "model_endpoint_accessed": False,
        "probe_sha256": probe_sha256,
        "production_authorized": False,
        "schema_version": 1,
        "source_revision": "9d7841b36bafcd58769041925b00deba7c25ffca",
        "state": "failed",
        "submission_receipt_sha256": submission_receipt_sha256,
        "task_data_accessed": False,
    }) + b"\n"
    blocked = {signal.SIGHUP, signal.SIGINT, signal.SIGTERM}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    temporary = f".vmvm-owner-v2-failure-{os.getpid()}-{os.getrandom(16).hex()}"
    descriptor = -1
    published = False
    identity = None
    try:
        try:
            os.stat(target, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(errno.EEXIST, "destination exists")
        descriptor = os.open(
            temporary,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_fd,
        )
        identity = os.fstat(descriptor)
        if (
            not stat.S_ISREG(identity.st_mode)
            or stat.S_IMODE(identity.st_mode) != 0o600
            or identity.st_uid != os.getuid()
            or identity.st_nlink != 1
            or identity.st_size != 0
        ):
            raise OSError
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written < 1:
                raise OSError
            offset += written
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
        final = os.fstat(descriptor)
        if (
            not stat.S_ISREG(final.st_mode)
            or stat.S_IMODE(final.st_mode) != 0o400
            or final.st_uid != os.getuid()
            or final.st_nlink != 1
            or final.st_size != len(payload)
            or os.pread(descriptor, len(payload) + 1, 0) != payload
        ):
            raise OSError
        rename_noreplace(parent_fd, temporary, target)
        published = True
        named = os.stat(target, dir_fd=parent_fd, follow_symlinks=False)
        if not same(final, named):
            raise OSError
        os.fsync(parent_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not published and identity is not None:
            try:
                named = os.stat(temporary, dir_fd=parent_fd, follow_symlinks=False)
                if named.st_dev == identity.st_dev and named.st_ino == identity.st_ino:
                    os.unlink(temporary, dir_fd=parent_fd)
                    os.fsync(parent_fd)
            except OSError:
                pass
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


main()
'

publish_probe_failure() {
    local primary=$1 cleanup=$2 writer_rc receipt_interrupted=0
    trap 'receipt_interrupted=1' HUP INT TERM
    set +e
    /usr/bin/python3 -I -S -B -c "$FAILURE_RECEIPT_WRITER_PROGRAM" \
        "$output_parent_fd" "${DIAG_PROBE_FAILURE_RECEIPT##*/}" \
        "$primary" "$cleanup" "$DIAG_AUTHORIZATION_FILE_SHA256" \
        "$DIAG_AUTHORIZATION_SHA256" "$environment_sha256" \
        "$job_authorization_sha256" "$submission_receipt_sha256" \
        "$DIAG_PROBE_SHA256" "$SLURM_JOB_ID" "$DIAG_JOB_NAME" \
        >/dev/null 2>&1
    writer_rc=$?
    set -e
    trap interrupt_probe HUP INT TERM
    (( writer_rc == 0 )) || fail
    printf '{"cleanup_status":"%s","code":"diagnostic_probe_failed","failure_class":"%s","state":"failed"}\n' \
        "$cleanup" "$primary" >&"$public_stderr_fd"
    exit 2
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
[[ $DIAG_LAUNCHER_PATH == "$DIAG_BUNDLE_ROOT/launch_vmvm_owner_lifecycle_v2.py" \
    && $DIAG_WRAPPER_PATH == "$DIAG_BUNDLE_ROOT/run_vmvm_owner_lifecycle_v2.sbatch" \
    && $DIAG_PROBE_PATH == "$DIAG_BUNDLE_ROOT/probe_vmvm_owner_lifecycle_v2.py" \
    && $DIAG_FINALIZER_PATH == "$DIAG_BUNDLE_ROOT/finalize_vmvm_owner_lifecycle_v2.py" ]] || fail
validate_file "$BOUND_BUNDLE_ROOT/launch_vmvm_owner_lifecycle_v2.py" 500 "$DIAG_LAUNCHER_SHA256"
validate_file "$BOUND_BUNDLE_ROOT/run_vmvm_owner_lifecycle_v2.sbatch" 500 "$DIAG_WRAPPER_SHA256"
[[ $(/usr/bin/stat -Lc '%s' -- "$BOUND_BUNDLE_ROOT/run_vmvm_owner_lifecycle_v2.sbatch") \
    == "$DIAG_WRAPPER_SIZE" ]] || fail
validate_file "$BOUND_BUNDLE_ROOT/probe_vmvm_owner_lifecycle_v2.py" 500 "$DIAG_PROBE_SHA256"
validate_file "$BOUND_BUNDLE_ROOT/finalize_vmvm_owner_lifecycle_v2.py" 500 "$DIAG_FINALIZER_SHA256"
[[ $(/usr/bin/stat -Lc '%s' -- "${BASH_SOURCE[0]}") == "$DIAG_WRAPPER_SIZE" \
    && $(digest_file "${BASH_SOURCE[0]}") == "$DIAG_WRAPPER_SHA256" ]] || fail
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
validate_backend

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
exec {probe_fd}<"$BOUND_BUNDLE_ROOT/probe_vmvm_owner_lifecycle_v2.py" || fail
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
EXPECTED_UV = "/memfd:vmvm-owner-uv-v2 (deleted)"
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
probe_fd = copy_sealed(probe_source_fd, "vmvm-owner-probe-v2", probe_digest, 0o500, 2 << 20)
uv_fd = copy_sealed(uv_source_fd, "vmvm-owner-uv-v2", uv_digest, 0o755, 64 << 20)
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
    local timeout_seconds=$1
    shift
    exec /usr/bin/setsid --wait \
        /usr/bin/timeout --foreground --signal=TERM --kill-after="$TIMEOUT_KILL_GRACE_SECONDS" \
        "$timeout_seconds" \
        /usr/bin/python3 -I -S -B -c "$SEALED_EXEC_PROGRAM" \
        "$probe_fd" "$DIAG_PROBE_SHA256" "$uv_fd" "$X86_UV_SHA256" \
        "$public_stdout_fd" "$public_stderr_fd" \
        run --no-project --offline --python "$PYTHON_BIN_X86_64" \
        python3 -I -S -B -c "$UV_SANITIZER_PROGRAM" \
        __VMVM_PROBE__ __VMVM_AUTHORIZED_ENVIRONMENT_SHA256__ "$@"
}

active_probe_pid=0
interrupt_probe() {
    trap '' HUP INT TERM
    failure_stage=signal
    if (( active_probe_pid > 1 )); then
        /usr/bin/kill -TERM -- "-$active_probe_pid" 2>/dev/null || true
        (
            /usr/bin/sleep "$TIMEOUT_KILL_GRACE_SECONDS"
            /usr/bin/kill -KILL -- "-$active_probe_pid" 2>/dev/null || true
        ) &
        local killer_pid=$!
        set +e
        wait "$active_probe_pid" 2>/dev/null
        /usr/bin/kill -TERM "$killer_pid" 2>/dev/null
        wait "$killer_pid" 2>/dev/null
        set -e
    fi
    fail
}
trap interrupt_probe HUP INT TERM

failure_stage=sealed_builder
admission_output=""
set +e
admission_output=$(
    run_sealed_probe "$ADMISSION_TIMEOUT_SECONDS" --validate-batch \
        --source-root "$BOUND_SOURCE_ROOT" --site-root "$BOUND_SITE_ROOT" \
        --scratch-root "$DIAG_SCRATCH_ROOT" \
        --output-dir "$BOUND_OUTPUT_PARENT/${DIAG_OUTPUT_ROOT##*/}" \
        --completion-receipt "$BOUND_OUTPUT_PARENT/${DIAG_COMPLETION_RECEIPT##*/}" 2>&1
)
admission_rc=$?
set -e
if (( admission_rc == 125 )); then
    fail
fi
if (( admission_rc == 124 )); then
    failure_stage=uv_sanitizer
    fail
fi
if (( admission_rc == 123 )); then
    failure_stage=uv_environment
    fail
fi
if (( admission_rc == 122 )); then
    failure_stage=uv_probe_exec
    fail
fi
if (( admission_rc != 0 )); then
    failure_stage=probe_admission
    fail
fi
if [[ $admission_output != '{"state":"admitted"}' ]]; then
    failure_stage=probe_response
    fail
fi

# Publication-adjacent source and executable validation. No task/dataset input
# is opened anywhere in this wrapper or its probe.
failure_stage=post_admission_source
validate_fd_file "$BOUND_PROBE" 500 "$DIAG_PROBE_SHA256" "$DIAG_PROBE_PATH"
validate_source "$BOUND_SOURCE_ROOT"
validate_backend
failure_stage=namespace_freshness
[[ ! -e $DIAG_OUTPUT_ROOT && ! -L $DIAG_OUTPUT_ROOT \
    && ! -e $DIAG_COMPLETION_RECEIPT && ! -L $DIAG_COMPLETION_RECEIPT \
    && ! -e $DIAG_PROBE_FAILURE_RECEIPT && ! -L $DIAG_PROBE_FAILURE_RECEIPT \
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

failure_stage=probe_execution
probe_output=""
probe_lines=()
set +e
coproc DIAGNOSTIC_RUN {
    run_sealed_probe "$SUPERVISOR_TIMEOUT_SECONDS" \
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
}
active_probe_pid=$DIAGNOSTIC_RUN_PID
mapfile -t probe_lines <&"${DIAGNOSTIC_RUN[0]}"
read_rc=$?
wait "$active_probe_pid"
probe_rc=$?
active_probe_pid=0
set -e
readonly probe_output_pattern='^\{"cells":1,"failure_categories":0,"passed":1,"state":"awaiting_external_completion"\}$'
probe_success=0
if (( read_rc == 0 && probe_rc == 0 && ${#probe_lines[@]} == 1 )) \
    && [[ ${probe_lines[0]} =~ $probe_output_pattern ]]; then
    probe_success=1
fi
if (( probe_success == 0 )); then
    primary_failure=unclassified
    reported_cleanup=unverified
    readonly probe_failure_pattern='^\{"cleanup_status":"(verified|unverified)","failure_class":"(backend_cancelled|backend_container|backend_fifo_wiring|backend_lease|backend_sshd|backend_tunnel|child_invalid|child_output_overflow|child_timeout|cleanup_failed|command_result_invalid|direct_client_failed|lease_budget_exceeded|renewer_identity_reused|renewer_not_alive|resume_failed|runtime_initial_workdir_rc255|runtime_other|source_binding_invalid|site_binding_invalid|stage_result_invalid|thread_failed|unclassified)","state":"diagnostic_failed"\}$'
    if (( read_rc == 0 && probe_rc == 2 && ${#probe_lines[@]} == 1 )) \
        && [[ ${probe_lines[0]} =~ $probe_failure_pattern ]]; then
        reported_cleanup=${BASH_REMATCH[1]}
        primary_failure=${BASH_REMATCH[2]}
    elif (( probe_rc == 124 )); then
        primary_failure=child_timeout
    fi
    observed_scratch_cleanup=$(failure_cleanup_status "$DIAG_SCRATCH_ROOT")
    observed_output_cleanup=$(failure_cleanup_status_at "$output_parent_fd" "${DIAG_OUTPUT_ROOT##*/}")
    [[ $observed_scratch_cleanup == verified || $observed_scratch_cleanup == unverified ]] \
        || observed_scratch_cleanup=unverified
    [[ $observed_output_cleanup == verified || $observed_output_cleanup == unverified ]] \
        || observed_output_cleanup=unverified
    cleanup_status=unverified
    if [[ $reported_cleanup == verified && $observed_scratch_cleanup == verified \
        && $observed_output_cleanup == verified ]]; then
        cleanup_status=verified
    fi
    publish_probe_failure "$primary_failure" "$cleanup_status"
fi
probe_output=${probe_lines[0]}

failure_stage=post_diagnostic_source
validate_fd_file "$BOUND_PROBE" 500 "$DIAG_PROBE_SHA256" "$DIAG_PROBE_PATH"
validate_source "$BOUND_SOURCE_ROOT"
validate_backend

failure_stage=probe_aggregate
[[ $probe_output =~ $probe_output_pattern ]] || fail
validate_compute_cleanup_attestation
readonly BOUND_OUTPUT_ROOT="$BOUND_OUTPUT_PARENT/${DIAG_OUTPUT_ROOT##*/}"
[[ $(/usr/bin/stat -Lc '%F:%a:%u' -- "$BOUND_OUTPUT_ROOT" 2>/dev/null) \
        == "directory:500:$(/usr/bin/id -u)" \
    && $(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$BOUND_OUTPUT_ROOT/diagnostic_certificate.json" 2>/dev/null) \
        == "regular file:400:$(/usr/bin/id -u):1" \
    && $(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$BOUND_OUTPUT_ROOT/completion_request.json" 2>/dev/null) \
        == "regular file:400:$(/usr/bin/id -u):1" \
    && ! -e "$BOUND_OUTPUT_PARENT/${DIAG_COMPLETION_RECEIPT##*/}" \
    && ! -e "$BOUND_OUTPUT_PARENT/${DIAG_PROBE_FAILURE_RECEIPT##*/}" \
    && -d $DIAG_SCRATCH_ROOT && ! -L $DIAG_SCRATCH_ROOT \
    && $(/usr/bin/stat -Lc '%F:%a:%u' -- "$DIAG_SCRATCH_ROOT" 2>/dev/null) \
        == "directory:700:$(/usr/bin/id -u)" ]] || fail
shopt -s nullglob dotglob
scratch_entries=("$DIAG_SCRATCH_ROOT"/*)
shopt -u nullglob dotglob
(( ${#scratch_entries[@]} == 0 )) || fail
printf '%s\n' "$probe_output" >&"$public_stdout_fd"
