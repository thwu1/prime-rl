#!/usr/bin/bash -p
#SBATCH --job-name=vmvm-vacli-versions-074900-v1b
#SBATCH --partition=cpu_x86
#SBATCH --account=ram
#SBATCH --qos=cpu_x86_lowest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:15:00
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/vmvm_vacli_versions_20260920t074900z_v1b/slurm-%j.log

set +x
set -euo pipefail
umask 077
export PATH=/usr/bin:/bin
export HOME=/storage/home/tianhaowu
export USER=tianhaowu
export LOGNAME=tianhaowu
export LANG=C
export LC_ALL=C
unset BASH_ENV ENV CDPATH GLOBIGNORE
unset LD_AUDIT LD_LIBRARY_PATH LD_PRELOAD
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
unset http_proxy https_proxy all_proxy no_proxy
[[ "$-" != *x* ]] || exit 2

readonly output_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/vmvm_vacli_versions_20260920t074900z_v1b
readonly expected_job_name=vmvm-vacli-versions-074900-v1b
readonly client_788=/public/fbpkgs/x86_64/vacli/788/vacli
readonly client_788_sha256=c9ab15d9886f7d5845dba6de8b7cbc8368bbfe6e53da3f32f239d8a520a28224
readonly client_794=/public/fbpkgs/x86_64/vacli/794/vacli
readonly client_794_sha256=8be49a764bd0fac1a3ef2bef053ced556d18397d44642660eb8a2d22a7c235b3
readonly expected_marker=VMVM_CLIENT_OK

probe_dir=
probe_fd=
probe_anchor=
probe_identity=
active_pid=
active_log_fd=
active_pgid=
spawning=0
pending_signal=
pending_status=

blocked() {
    /usr/bin/printf '{"category":"%s","state":"blocked"}\n' "$1"
    exit 2
}

validate_probe_root() {
    [[ "${probe_dir:-}" =~ ^/tmp/vmvm-vacli-versions-v1\.[A-Za-z0-9]{6}$ \
        && "${probe_fd:-}" =~ ^[0-9]+$ \
        && "${probe_identity:-}" =~ ^[0-9]+:[0-9]+:[0-9a-f]+:656177$ \
        && "${probe_anchor:-}" == "/proc/$$/fd/${probe_fd}" \
        && -d "$probe_anchor" \
        && "$(/usr/bin/stat -Lc '%d:%i:%f:%u' -- "$probe_anchor" 2>/dev/null)" \
            == "$probe_identity" ]]
}

zero_active_log() {
    [[ -z "${active_log_fd:-}" ]] && return 0
    [[ "$active_log_fd" =~ ^[0-9]+$ \
        && -f "/proc/$$/fd/$active_log_fd" \
        && "$(/usr/bin/stat -Lc '%a:%u:%h' -- "/proc/$$/fd/$active_log_fd" 2>/dev/null)" \
            == 600:656177:0 ]] || return 1
    : > "/proc/$$/fd/$active_log_fd" || return 1
    /usr/bin/sync -f "/proc/$$/fd/$active_log_fd" 2>/dev/null || return 1
    [[ "$(/usr/bin/stat -Lc '%s' -- "/proc/$$/fd/$active_log_fd")" == 0 ]] \
        || return 1
    exec {active_log_fd}>&-
    active_log_fd=
}

stop_active() {
    local i
    [[ "${active_pid:-}" =~ ^[0-9]+$ ]] || return 0
    if [[ "${active_pgid:-}" == "$active_pid" ]] \
        && /usr/bin/kill -0 -- "-$active_pgid" 2>/dev/null; then
        /usr/bin/kill -TERM -- "-$active_pgid" 2>/dev/null \
            || /usr/bin/kill -TERM -- "$active_pid" 2>/dev/null || true
    elif /usr/bin/kill -0 "$active_pid" 2>/dev/null; then
        /usr/bin/kill -TERM -- "$active_pid" 2>/dev/null || true
    fi
    for i in {1..50}; do
        # Reaping a dead direct child is nonblocking and lets an otherwise
        # empty process group disappear before the escalation decision.
        if ! pid_is_running "$active_pid"; then
            wait "$active_pid" 2>/dev/null || true
        fi
        if [[ "${active_pgid:-}" == "$active_pid" ]]; then
            /usr/bin/kill -0 -- "-$active_pgid" 2>/dev/null || break
        else
            pid_is_running "$active_pid" || break
        fi
        /usr/bin/sleep 0.1
    done
    # Kill the whole verified group even when its direct child has already
    # become a zombie; descendants can otherwise survive their group leader.
    if [[ "${active_pgid:-}" == "$active_pid" ]] \
        && /usr/bin/kill -0 -- "-$active_pgid" 2>/dev/null; then
        /usr/bin/kill -KILL -- "-$active_pgid" 2>/dev/null \
            || /usr/bin/kill -KILL -- "$active_pid" 2>/dev/null || true
    elif pid_is_running "$active_pid"; then
        /usr/bin/kill -KILL -- "$active_pid" 2>/dev/null || true
    fi
    for i in {1..50}; do
        if ! pid_is_running "$active_pid"; then
            break
        fi
        /usr/bin/sleep 0.1
    done
    if pid_is_running "$active_pid"; then
        return 1
    fi
    # A dead or zombie direct child makes wait nonblocking; reap it only after
    # the bounded liveness proof above, then prove its exact PID disappeared.
    wait "$active_pid" 2>/dev/null || true
    [[ ! -e "/proc/$active_pid" ]] || return 1
    if [[ "${active_pgid:-}" == "$active_pid" ]]; then
        for i in {1..50}; do
            /usr/bin/kill -0 -- "-$active_pgid" 2>/dev/null || break
            /usr/bin/sleep 0.1
        done
        /usr/bin/kill -0 -- "-$active_pgid" 2>/dev/null && return 1
    fi
    active_pid=
    active_pgid=
}

pid_is_running() {
    local pid=$1 line state
    [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/stat" ]] || return 1
    line=$(<"/proc/$pid/stat") || return 1
    state=${line#*) }
    state=${state%% *}
    [[ "$state" != Z && "$state" != X ]]
}

close_empty_probe_root() {
    local entries
    [[ -z "${probe_fd:-}" ]] && return 0
    validate_probe_root || return 1
    entries=$(/usr/bin/find -H "$probe_anchor" -mindepth 1 -maxdepth 1 \
        -printf x -quit 2>/dev/null) || return 1
    [[ -z "$entries" ]] || return 1
    exec {probe_fd}<&-
    probe_fd=
    probe_anchor=
    probe_identity=
    probe_dir=
}

cleanup() {
    local saved=$? failed=0
    trap - EXIT HUP INT TERM
    stop_active || failed=1
    zero_active_log || failed=1
    close_empty_probe_root || failed=1
    if (( failed )); then
        /usr/bin/printf '{"category":"private_cleanup_failed","state":"blocked"}\n' >&2
        exit 3
    fi
    exit "$saved"
}

signal_exit() {
    local signal_name=$1 status=$2 failed=0
    # Defer through both PID publication and process-group convergence so
    # cleanup never has to act on a partially bound child lifecycle.
    if (( spawning )); then
        if [[ -z "${pending_signal:-}" ]]; then
            pending_signal=$signal_name
            pending_status=$status
        fi
        return 0
    fi
    trap - EXIT HUP INT TERM
    stop_active || failed=1
    zero_active_log || failed=1
    close_empty_probe_root || failed=1
    if (( ! failed )); then
        /usr/bin/printf '{"category":"signal_%s","state":"blocked"}\n' "$signal_name" >&2
    else
        /usr/bin/printf '{"category":"signal_cleanup_failed","state":"blocked"}\n' >&2
        status=3
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'signal_exit hup 129' HUP
trap 'signal_exit int 130' INT
trap 'signal_exit term 143' TERM

[[ "${SLURM_CLUSTER_NAME:-}" == fair-cw-use2-3 \
    && "${SLURM_JOB_NAME:-}" == "$expected_job_name" \
    && "${SLURM_JOB_PARTITION:-}" == cpu_x86 \
    && "${SLURM_JOB_ACCOUNT:-}" == ram \
    && "${SLURM_JOB_NUM_NODES:-}" == 1 \
    && "${SLURM_NTASKS:-}" == 1 \
    && "${SLURM_CPUS_PER_TASK:-}" == 2 \
    && "${SLURM_MEM_PER_NODE:-}" == 4096 \
    && "${SLURM_RESTART_COUNT:-0}" == 0 \
    && "$(/usr/bin/uname -m)" == x86_64 ]] || blocked allocation_identity
observed_qos=${SLURM_JOB_QOS:-}
if [[ -z "$observed_qos" ]]; then
    observed_qos=$(/usr/bin/timeout --signal=TERM --kill-after=2s 10s \
        /usr/bin/squeue -h -j "$SLURM_JOB_ID" -o '%q' 2>/dev/null \
        | /usr/bin/tr -d '[:space:]') || blocked allocation_qos_query
fi
[[ "$observed_qos" == cpu_x86_lowest ]] || blocked allocation_qos
unset observed_qos
[[ "${EXPECTED_PROBE_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] || blocked expected_hash
[[ "$(/usr/bin/sha256sum -- "${BASH_SOURCE[0]}" | /usr/bin/cut -d' ' -f1)" \
    == "$EXPECTED_PROBE_SHA256" ]] || blocked script_hash
[[ -d "$output_root" && ! -L "$output_root" \
    && "$(/usr/bin/stat -c '%a:%u:%h' -- "$output_root")" == 700:656177:2 ]] \
    || blocked output_root
for required_name in X2P_ENV X2P_CFG_ENV X2P_PROXY_URL \
    THRIFT_TLS_CL_CERT_PATH THRIFT_TLS_CL_KEY_PATH; do
    [[ -n "${!required_name:-}" && "${!required_name}" != *$'\n'* \
        && "${!required_name}" != *$'\r'* ]] || blocked transport_environment
done
unset required_name
for tls_name in THRIFT_TLS_CL_CERT_PATH THRIFT_TLS_CL_KEY_PATH; do
    tls_path=${!tls_name}
    [[ "$tls_path" == /* ]] || blocked credential_path
    tls_canonical=$(/usr/bin/readlink -f -- "$tls_path" 2>/dev/null) \
        || blocked credential_path
    [[ "$(/usr/bin/stat -Lc '%F:%a:%u:%h:%s' -- "$tls_canonical" 2>/dev/null)" \
        == 'regular file:500:656177:1:5580' ]] || blocked credential_identity
    printf -v "$tls_name" '%s' "$tls_canonical"
    export "$tls_name"
done
unset tls_name tls_path tls_canonical
for client_spec in \
    "$client_788:$client_788_sha256:423517072" \
    "$client_794:$client_794_sha256:425568088"; do
    client_path=${client_spec%%:*}
    client_rest=${client_spec#*:}
    client_sha=${client_rest%%:*}
    client_size=${client_rest##*:}
    [[ -f "$client_path" && ! -L "$client_path" \
        && "$(/usr/bin/stat -Lc '%F:%a:%u:%g:%h:%s' -- "$client_path")" \
            == "regular file:755:0:0:1:$client_size" \
        && "$(/usr/bin/sha256sum -- "$client_path" | /usr/bin/cut -d' ' -f1)" \
            == "$client_sha" ]] || blocked client_identity
done
unset client_spec client_path client_rest client_sha client_size

probe_dir=$(/usr/bin/mktemp -d /tmp/vmvm-vacli-versions-v1.XXXXXX) \
    || blocked temporary_directory
[[ -d "$probe_dir" && ! -L "$probe_dir" \
    && "$(/usr/bin/stat -c '%a:%u:%h' -- "$probe_dir")" == 700:656177:2 ]] \
    || blocked temporary_directory_identity
exec {probe_fd}<"$probe_dir" || blocked temporary_directory_descriptor
probe_anchor=/proc/$$/fd/$probe_fd
probe_identity=$(/usr/bin/stat -Lc '%d:%i:%f:%u' -- "$probe_anchor" 2>/dev/null) \
    || blocked temporary_directory_descriptor
validate_probe_root || blocked temporary_directory_binding

classify_log() {
    local rc=$1 log_fd=$2 lowered marker_count bytes
    [[ -f "/proc/$$/fd/$log_fd" \
        && "$(/usr/bin/stat -Lc '%a:%u:%h' -- "/proc/$$/fd/$log_fd")" \
            == 600:656177:0 ]] || blocked diagnostic_identity
    bytes=$(/usr/bin/stat -Lc '%s' -- "/proc/$$/fd/$log_fd") \
        || blocked diagnostic_metadata
    (( bytes <= 1048576 )) || blocked diagnostic_size
    marker_count=$({ /usr/bin/grep -aFo -- "$expected_marker" "/proc/$$/fd/$log_fd" \
        2>/dev/null || true; } | /usr/bin/wc -l) || blocked diagnostic_read
    lowered=$(/usr/bin/tr '[:upper:]' '[:lower:]' < "/proc/$$/fd/$log_fd") \
        || blocked diagnostic_read
    if (( rc == 0 && marker_count == 1 )); then
        CASE_CLASS=success
    elif (( rc == 124 || rc == 137 )); then
        CASE_CLASS=timeout
    elif [[ "$lowered" == *"glibc_"* || "$lowered" == *"version glibc"* ]]; then
        CASE_CLASS=glibc
    elif [[ "$lowered" == *"isconfigeratoravailable"* \
        || "$lowered" == *configerator* ]]; then
        CASE_CLASS=configerator
    elif [[ "$lowered" == *faasuserexception* \
        || "$lowered" == *"connection refused"* ]]; then
        CASE_CLASS=lease_backend
    elif [[ "$lowered" == *"tunnel"* && "$lowered" == *"not ready"* \
        || "$lowered" == *"died before tunnel"* ]]; then
        CASE_CLASS=tunnel
    elif [[ "$lowered" == *"certificate"* || "$lowered" == *x509* \
        || "$lowered" == *tls* ]]; then
        CASE_CLASS=tls
    elif [[ "$lowered" == *unauthorized* || "$lowered" == *forbidden* \
        || "$lowered" == *credential* ]]; then
        CASE_CLASS=authorization
    elif [[ "$lowered" == *"sshd"* || "$lowered" == *"ssh"* ]]; then
        CASE_CLASS=ssh
    elif [[ "$lowered" == *unavailable* ]]; then
        CASE_CLASS=unavailable
    else
        CASE_CLASS=other
    fi
    if (( bytes == 0 )); then
        CASE_BYTES=empty
    elif (( bytes < 4096 )); then
        CASE_BYTES=lt4k
    elif (( bytes < 65536 )); then
        CASE_BYTES=lt64k
    else
        CASE_BYTES=ge64k
    fi
    CASE_MARKERS=$marker_count
    unset lowered
}

run_client() {
    local label=$1 client=$2 rc=0 observed_pgid= _pgid_wait
    validate_probe_root || blocked temporary_directory_replaced
    set -o noclobber
    exec {active_log_fd}>"$probe_anchor/$label.raw" || blocked diagnostic_create
    set +o noclobber
    /usr/bin/chmod 600 "/proc/$$/fd/$active_log_fd" || blocked diagnostic_mode
    /usr/bin/unlink -- "$probe_anchor/$label.raw" || blocked diagnostic_unlink
    [[ "$(/usr/bin/stat -Lc '%a:%u:%h:%s' -- "/proc/$$/fd/$active_log_fd")" \
        == 600:656177:0:0 ]] || blocked diagnostic_identity

    spawning=1
    /usr/bin/setsid /usr/bin/timeout --signal=TERM --kill-after=10s 180s \
        "$client" --x2p --faas-tenant-id async_2347641 lease \
        --ttl 60s --auto-renew --release-on-exit \
        --ssh-cmd '/usr/bin/sleep 75; /usr/bin/printf VMVM_CLIENT_OK' \
        >&"$active_log_fd" 2>&1 &
    active_pid=$!
    # setsid's intended process-group ID is its child PID. Bind that inference
    # before sampling so a fast-exiting leader cannot hide surviving members.
    active_pgid=$active_pid
    observed_pgid=$(/usr/bin/ps -o pgid= -p "$active_pid" 2>/dev/null \
        | /usr/bin/tr -d '[:space:]') || true
    for _pgid_wait in {1..50}; do
        [[ "$observed_pgid" == "$active_pid" ]] && break
        /usr/bin/kill -0 "$active_pid" 2>/dev/null || break
        /usr/bin/sleep 0.1
        observed_pgid=$(/usr/bin/ps -o pgid= -p "$active_pid" 2>/dev/null \
            | /usr/bin/tr -d '[:space:]') || true
    done
    spawning=0
    if [[ "$observed_pgid" != "$active_pid" ]] \
        && /usr/bin/kill -0 "$active_pid" 2>/dev/null; then
        signal_exit process_group 125
    fi
    if [[ -n "$pending_signal" ]]; then
        local signal_name=$pending_signal status=$pending_status
        pending_signal=
        pending_status=
        signal_exit "$signal_name" "$status"
    fi
    set +e
    wait "$active_pid"
    rc=$?
    set -e
    if /usr/bin/kill -0 -- "-$active_pid" 2>/dev/null; then
        stop_active || blocked ordinary_process_group_cleanup
        blocked ordinary_process_group_survived
    fi
    [[ ! -e "/proc/$active_pid" ]] || blocked ordinary_process_pid_survived
    active_pid=
    active_pgid=
    classify_log "$rc" "$active_log_fd"
    printf -v "${label}_class" '%s' "$CASE_CLASS"
    printf -v "${label}_rc" '%s' "$rc"
    printf -v "${label}_bytes" '%s' "$CASE_BYTES"
    printf -v "${label}_markers" '%s' "$CASE_MARKERS"
    zero_active_log || blocked diagnostic_cleanup
}

run_client v794_a "$client_794"
run_client v788_a "$client_788"
run_client v788_b "$client_788"
run_client v794_b "$client_794"
close_empty_probe_root || blocked private_environment_cleanup

log_path=$output_root/slurm-${SLURM_JOB_ID}.log
/usr/bin/chmod 600 "$log_path" 2>/dev/null || blocked output_log_mode
[[ -f "$log_path" && ! -L "$log_path" \
    && "$(/usr/bin/stat -Lc '%a:%u:%h' -- "$log_path")" == 600:656177:1 ]] \
    || blocked output_log_identity

/usr/bin/printf '{"kind":"vmvm-vacli-version-probe-v1","network_scope":"lease-and-fixed-75s-ssh-command-only","private_root":"retained-empty-mode0700","v788_a":{"bytes":"%s","category":"%s","marker_count":%s,"rc":%s},"v788_b":{"bytes":"%s","category":"%s","marker_count":%s,"rc":%s},"v794_a":{"bytes":"%s","category":"%s","marker_count":%s,"rc":%s},"v794_b":{"bytes":"%s","category":"%s","marker_count":%s,"rc":%s},"state":"complete"}\n' \
    "$v788_a_bytes" "$v788_a_class" "$v788_a_markers" "$v788_a_rc" \
    "$v788_b_bytes" "$v788_b_class" "$v788_b_markers" "$v788_b_rc" \
    "$v794_a_bytes" "$v794_a_class" "$v794_a_markers" "$v794_a_rc" \
    "$v794_b_bytes" "$v794_b_class" "$v794_b_markers" "$v794_b_rc"
