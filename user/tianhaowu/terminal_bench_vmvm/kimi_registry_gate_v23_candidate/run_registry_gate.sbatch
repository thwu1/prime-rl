#!/usr/bin/bash -p
set +x
set -euo pipefail
shopt -u varredir_close
umask 077
readonly expected_digest=sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20
readonly expected_image=588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/vllm-openai:kimi-k3-kda-logprobs-fix-v2-20260916@sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20
readonly expected_bundle=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t143000z_v23
readonly expected_result=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/k3_registry_pull_gate_20260920t143000z_v23/job_result.json
# Preserve the two inherited Slurm log descriptors solely for identity proof
# and the one allowlisted result. Silence every other command by construction.
exec 8>&1 4>&2 >/dev/null 2>/dev/null || exit 3

emit() {
    local category=$1 state=blocked
    [[ "$category" == success ]] && state=complete
    local raw temp temp_meta result_sha published=0
    raw=$(/usr/bin/printf '{"category":"%s","image_digest":"%s","kind":"k3-registry-pull-gate-v23","platform":"linux/arm64","state":"%s"}\n' \
        "$category" "$expected_digest" "$state")
    raw+=$'\n'
    if [[ "${GATE_JOB_RESULT:-}" == "$expected_result" \
        && "$(/usr/bin/stat -c '%F:%a:%u' -- "${GATE_JOB_RESULT%/*}" 2>/dev/null || true)" == 'directory:700:656177' \
        && ! -e "$GATE_JOB_RESULT" && ! -L "$GATE_JOB_RESULT" ]]; then
        temp=${GATE_JOB_RESULT}."${SLURM_JOB_ID:-unknown}"."$RANDOM".tmp
        if (set -o noclobber; /usr/bin/printf '%s' "$raw" > "$temp") 2>/dev/null \
            && /usr/bin/chmod 400 "$temp" 2>/dev/null \
            && /usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/sync -f "$temp" 2>/dev/null \
            && /usr/bin/ln -- "$temp" "$GATE_JOB_RESULT" 2>/dev/null \
            && [[ "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$temp")" == 'regular file:400:656177:2' \
                && "$(/usr/bin/stat -Lc '%d:%i' -- "$temp")" == "$(/usr/bin/stat -Lc '%d:%i' -- "$GATE_JOB_RESULT")" ]] \
            && /usr/bin/unlink -- "$temp" 2>/dev/null \
            && [[ ! -e "$temp" && ! -L "$temp" \
                && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$GATE_JOB_RESULT")" == 'regular file:400:656177:1' ]]; then
            result_sha=$(/usr/bin/printf '%s' "$raw" | /usr/bin/sha256sum | /usr/bin/cut -d' ' -f1)
            if [[ "$result_sha" == "$(/usr/bin/sha256sum -- "$GATE_JOB_RESULT" | /usr/bin/cut -d' ' -f1)" ]] \
                && /usr/bin/timeout --signal=TERM --kill-after=2s 8s \
                    /usr/bin/sync -f "${GATE_JOB_RESULT%/*}" 2>/dev/null; then
                published=1
            fi
        fi
        if [[ -e "$temp" || -L "$temp" ]]; then
            temp_meta=$(/usr/bin/stat -c '%F:%u:%h' -- "$temp" 2>/dev/null || true)
            if [[ "$temp_meta" == 'regular file:656177:1' ]]; then
                /usr/bin/chmod 600 -- "$temp" 2>/dev/null \
                    && /usr/bin/truncate -s 0 -- "$temp" 2>/dev/null \
                    && /usr/bin/unlink -- "$temp" 2>/dev/null || true
            elif [[ "$temp_meta" == 'regular file:656177:2' \
                && "$(/usr/bin/stat -c '%d:%i' -- "$temp" 2>/dev/null || true)" == "$(/usr/bin/stat -c '%d:%i' -- "$GATE_JOB_RESULT" 2>/dev/null || true)" ]]; then
                /usr/bin/unlink -- "$temp" 2>/dev/null || true
            fi
        fi
    fi
    /usr/bin/printf '%s' "$raw" >&8
    (( published == 1 ))
}

block() {
    emit "$1" || exit 3
    exit 2
}

[[ $# == 0 && "$-" != *x* ]] || block allocation_identity
[[ "${GATE_BUNDLE:-}" == "$expected_bundle" \
    && "${GATE_IMAGE:-}" == "$expected_image" && "${GATE_IMAGE_DIGEST:-}" == "$expected_digest" \
    && "${SLURM_CLUSTER_NAME:-}" == fair-cw-use2-3 \
    && "${SLURM_JOB_NAME:-}" == "${GATE_JOB_NAME:-}" \
    && "${SLURM_JOB_PARTITION:-}" == g3 \
    && "${SLURM_JOB_ACCOUNT:-}" == ram \
    && "${SLURM_JOB_NUM_NODES:-}" == 1 \
    && "${SLURM_NTASKS:-}" == 1 \
    && "${SLURM_CPUS_PER_TASK:-}" == 4 \
    && "${SLURM_GPUS_ON_NODE:-}" == 1 \
    && "${SLURM_RESTART_COUNT:-0}" == 0 ]] \
    || block allocation_identity

readonly probe=$expected_bundle/probe_registry_gate.sh
readonly classifier=$expected_bundle/classify_registry_error.sh
readonly tools_manifest=$expected_bundle/compute_tools.sha256
script_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "${BASH_SOURCE[0]}" 2>/dev/null) \
    || block source_identity
classifier_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$classifier" 2>/dev/null) \
    || block source_identity
probe_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$probe" 2>/dev/null) \
    || block source_identity
tools_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest" 2>/dev/null) \
    || block source_identity
if ! exec 9<"${BASH_SOURCE[0]}" 7<"$classifier" 6<"$probe" 5<"$tools_manifest" 2>/dev/null; then
    block source_identity
fi
[[ -f /proc/self/fd/9 && -f /proc/self/fd/7 && -f /proc/self/fd/6 && -f /proc/self/fd/5 \
    && "$script_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/9)" \
    && "$script_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "${BASH_SOURCE[0]}")" \
    && "$classifier_before" == *':500:656177:1:'* \
    && "$classifier_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/7)" \
    && "$classifier_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$classifier")" \
    && "$probe_before" == *':500:656177:1:'* \
    && "$probe_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/6)" \
    && "$probe_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$probe")" \
    && "$tools_before" == *':400:656177:1:'* \
    && "$tools_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/5)" \
    && "$tools_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest")" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/9 | /usr/bin/cut -d' ' -f1)" == "${GATE_BATCH_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/7 | /usr/bin/cut -d' ' -f1)" == "${GATE_CLASSIFIER_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/6 | /usr/bin/cut -d' ' -f1)" == "${GATE_PROBE_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/5 | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" ]] \
    || block source_identity
/usr/bin/sha256sum -c --strict /proc/self/fd/5 >/dev/null 2>&1 \
    || block compute_tools_identity
source /proc/self/fd/7 || block source_identity

qos=${SLURM_JOB_QOS:-}
if [[ -z "$qos" ]]; then
    qos=$(/usr/bin/squeue -M fair-cw-use2-3 -h -j "$SLURM_JOB_ID" -o '%q' 2>/dev/null | /usr/bin/tr -d '[:space:]') \
        || block allocation_identity
fi
[[ "$qos" == g3_lowest ]] || block allocation_identity
unset qos

node=${SLURMD_NODENAME:-}
if [[ -z "$node" ]]; then
    node=$(/usr/bin/scontrol -M fair-cw-use2-3 show hostnames "$SLURM_JOB_NODELIST" 2>/dev/null) \
        || block allocation_identity
fi
[[ "$node" == g3-154-201 ]] \
    || block allocation_identity

log=${GATE_BUNDLE%/watchers/*}/logs/k3_registry_pull_gate_20260920t143000z_v23/slurm-${SLURM_JOB_ID}.log
stable_log_reads=0
last_log_identity=
for _ in {1..30}; do
    /usr/bin/chmod 600 /proc/self/fd/8 /proc/self/fd/4 2>/dev/null || true
    path_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "$log" 2>/dev/null || true)
    stdout_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- /proc/self/fd/8 2>/dev/null || true)
    stderr_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- /proc/self/fd/4 2>/dev/null || true)
    if [[ "$path_identity" == "$stdout_identity" && "$stdout_identity" == "$stderr_identity" \
        && -f "$log" && ! -L "$log" && "$path_identity" == *':600:656177:1' ]]; then
        if [[ "$path_identity" == "$last_log_identity" ]]; then
            stable_log_reads=$((stable_log_reads + 1))
        else
            stable_log_reads=1
            last_log_identity=$path_identity
        fi
        (( stable_log_reads >= 2 )) && break
    else
        stable_log_reads=0
        last_log_identity=
    fi
    /usr/bin/sleep 1
done
(( stable_log_reads >= 2 )) || block private_environment

readonly local_parent=${SLURM_TMPDIR:-/var/slurm-tmp}
[[ "$local_parent" == /var/slurm-tmp || "$local_parent" == /var/slurm-tmp/* \
    || "$local_parent" == /tmp || "$local_parent" == /tmp/* ]] \
    || block private_environment
[[ "$local_parent" != /proc/self/fd/* \
    && "$local_parent" == "$(/usr/bin/readlink -f -- "$local_parent" 2>/dev/null)" \
    && -d "$local_parent" && ! -L "$local_parent" ]] \
    || block private_environment
private=
private_before=
private_identity=
private_fd=-1
private_anchor=
private_anchor_trusted=0
stdout=
stderr=
local_tools=
local_tools_export=
stdout_fd=-1
stderr_fd=-1
local_tools_fd=-1
stdout_identity=
stderr_identity=
local_tools_identity=
cleanup_complete=0
cleanup_attempted=0

close_batch_private_fds() {
    if [[ "$stdout_fd" =~ ^[0-9]+$ && "$stdout_fd" -ge 10 ]]; then
        exec {stdout_fd}>&- || true
        stdout_fd=-1
    fi
    if [[ "$stderr_fd" =~ ^[0-9]+$ && "$stderr_fd" -ge 10 ]]; then
        exec {stderr_fd}>&- || true
        stderr_fd=-1
    fi
    if [[ "$local_tools_fd" =~ ^[0-9]+$ && "$local_tools_fd" -ge 10 ]]; then
        exec {local_tools_fd}<&- || true
        local_tools_fd=-1
    fi
    if [[ "$private_fd" =~ ^[0-9]+$ && "$private_fd" -ge 10 ]]; then
        exec {private_fd}<&- || true
        private_fd=-1
    fi
}

batch_mount_free() {
    local resolved mountpoint
    resolved=$(/usr/bin/readlink -f -- "$private_anchor" 2>/dev/null) || return 1
    [[ "$resolved" == /* ]] || return 1
    while IFS=' ' read -r _ _ _ _ mountpoint _; do
        case "$mountpoint" in
            "$resolved"|"$resolved"/*) return 1 ;;
        esac
    done < /proc/self/mountinfo
}

preflight_batch_contents() {
    local fd expected observed leftover
    [[ "$private_anchor_trusted" == 1 \
        && "$private_fd" =~ ^[0-9]+$ && "$private_fd" -ge 10 \
        && -d "$private_anchor" && ! -L "$private_anchor" \
        && "$private_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$private_anchor" 2>/dev/null || true)" ]] \
        || return 1
    batch_mount_free || return 1
    leftover=$(/usr/bin/timeout --signal=TERM --kill-after=1s 3s \
        /usr/bin/find "$private_anchor" -xdev -mindepth 1 -maxdepth 1 \
            ! -name stdout ! -name stderr ! -name compute_tools.sha256 -print -quit 2>/dev/null) \
        || return 1
    [[ -z "$leftover" ]] || return 1
    for fd in "$stdout_fd" "$stderr_fd" "$local_tools_fd"; do
        case "$fd" in
            "$stdout_fd") expected=$stdout_identity ;;
            "$stderr_fd") expected=$stderr_identity ;;
            "$local_tools_fd") expected=$local_tools_identity ;;
            *) return 1 ;;
        esac
        [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 && -n "$expected" ]] || return 1
        observed=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$fd" 2>/dev/null) \
            || return 1
        [[ -f "/proc/self/fd/$fd" && "$observed" == "$expected" ]] || return 1
    done
}

scrub_exact_batch_file() {
    local fd=$1 expected=$2 observed
    observed=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$fd" 2>/dev/null) \
        || return 1
    [[ -f "/proc/self/fd/$fd" && "$observed" == "$expected" ]] || return 1
    /usr/bin/timeout --signal=TERM --kill-after=1s 2s \
        /usr/bin/chmod 600 -- "/proc/self/fd/$fd" 2>/dev/null || return 1
    /usr/bin/timeout --signal=TERM --kill-after=1s 5s \
        /usr/bin/truncate -s 0 -- "/proc/self/fd/$fd" 2>/dev/null || return 1
}

scrub_batch_contents() {
    local fd expected path path_observed leftover pid failed=0
    local pids=()
    # The mode-0700 batch root is writable only by this job. After the nested
    # step is reaped, validate every retained target and mount before the first
    # mutation; each FD is revalidated at its mutation boundary.
    preflight_batch_contents || return 1
    for fd in "$stdout_fd" "$stderr_fd" "$local_tools_fd"; do
        case "$fd" in
            "$stdout_fd") expected=$stdout_identity ;;
            "$stderr_fd") expected=$stderr_identity ;;
            "$local_tools_fd") expected=$local_tools_identity ;;
            *) return 1 ;;
        esac
        scrub_exact_batch_file "$fd" "$expected" &
        pids+=("$!")
    done
    for pid in "${pids[@]}"; do
        wait "$pid" || failed=1
    done

    # Verify that every retained name still resolves to the exact scrubbed
    # inode. A replacement is preserved and makes cleanup fail closed.
    for path in "$stdout" "$stderr" "$local_tools"; do
        case "$path" in
            "$stdout") expected=$stdout_identity ;;
            "$stderr") expected=$stderr_identity ;;
            "$local_tools") expected=$local_tools_identity ;;
            *) return 1 ;;
        esac
        path_observed=$(/usr/bin/stat -c '%d:%i:%a:%u:%h:%s' -- "$path" 2>/dev/null || true)
        [[ "${path_observed%:*:*:*:*}" == "${expected%:*:*:*}" \
            && "$path_observed" == *':600:656177:1:0' ]] \
            || failed=1
    done
    leftover=$(/usr/bin/timeout --signal=TERM --kill-after=1s 3s \
        /usr/bin/find "$private_anchor" -xdev -mindepth 1 -maxdepth 1 \
            ! -name stdout ! -name stderr ! -name compute_tools.sha256 -print -quit 2>/dev/null) \
        || failed=1
    [[ -z "$leftover" ]] || failed=1
    (( failed == 0 ))
}

retain_batch_root() {
    local anchored_after named_now result=0
    cleanup_attempted=1
    scrub_batch_contents || result=1
    anchored_after=$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$private_anchor" 2>/dev/null) || result=1
    [[ "$anchored_after" == "$private_identity" ]] || result=1
    named_now=$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private" 2>/dev/null || true)
    [[ "$named_now" == "$private_identity" ]] || result=1
    close_batch_private_fds
    (( result == 0 ))
}

early_cleanup() {
    local saved=$?
    trap - EXIT HUP INT TERM
    if (( ! cleanup_complete && ! cleanup_attempted )) \
        && [[ "$private_fd" =~ ^[0-9]+$ && "$private_fd" -ge 10 ]]; then
        retain_batch_root >/dev/null 2>&1 || true
    fi
    close_batch_private_fds
    exit "$saved"
}
early_signal() {
    trap - HUP INT TERM
    emit interrupted || exit 3
    exit 130
}
trap early_cleanup EXIT
trap early_signal HUP INT TERM
private=$(/usr/bin/mktemp -d "$local_parent/k3-registry-pull-v23.batch.${SLURM_JOB_ID}.XXXXXX" 2>/dev/null) \
    || block private_environment
readonly private
[[ "$private" != /proc/self/fd/* \
    && "$private" == "$(/usr/bin/readlink -f -- "$private" 2>/dev/null)" \
    && -d "$private" && ! -L "$private" ]] \
    || block private_environment
private_before=$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private" 2>/dev/null) \
    || block private_environment
[[ "$private_before" == *':700:656177' \
    && "$(/usr/bin/stat -c '%h' -- "$private" 2>/dev/null)" == 2 ]] \
    || block private_environment
if ! exec {private_fd}<"$private" 2>/dev/null; then
    block private_environment
fi
private_anchor=/proc/self/fd/${private_fd}/.
private_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$private_anchor" 2>/dev/null) \
    || block private_environment
readonly private_identity private_anchor
[[ "$private_before" == "$private_identity" \
    && "$private_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private" 2>/dev/null)" \
    && -d "$private_anchor" && ! -L "$private_anchor" ]] \
    || block private_environment
initial_entry=$(/usr/bin/find "$private_anchor" -xdev -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null) \
    || block private_environment
[[ -z "$initial_entry" ]] || block private_environment
unset initial_entry
private_anchor_trusted=1
stdout=$private_anchor/stdout
stderr=$private_anchor/stderr
local_tools=$private_anchor/compute_tools.sha256
local_tools_export=$private/compute_tools.sha256
readonly stdout stderr local_tools local_tools_export
/usr/bin/touch "$stdout" "$stderr" 2>/dev/null \
    || block private_environment
/usr/bin/chmod 600 "$stdout" "$stderr" 2>/dev/null \
    || block private_environment
/usr/bin/cp -- /proc/self/fd/5 "$local_tools" 2>/dev/null \
    || block private_environment
/usr/bin/chmod 400 "$local_tools" 2>/dev/null \
    || block private_environment
if ! exec {stdout_fd}<>"$stdout" {stderr_fd}<>"$stderr" {local_tools_fd}<"$local_tools" 2>/dev/null; then
    block private_environment
fi
stdout_identity=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$stdout" 2>/dev/null) \
    || block private_environment
stderr_identity=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$stderr" 2>/dev/null) \
    || block private_environment
local_tools_identity=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$local_tools" 2>/dev/null) \
    || block private_environment
[[ -f "$stdout" && ! -L "$stdout" && -f "$stderr" && ! -L "$stderr" \
    && -f "$local_tools" && ! -L "$local_tools" \
    && "$stdout_identity" == *':600:656177:1' \
    && "$stderr_identity" == *':600:656177:1' \
    && "$local_tools_identity" == *':400:656177:1' \
    && "$stdout_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$stdout_fd")" \
    && "$stderr_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$stderr_fd")" \
    && "$local_tools_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$local_tools_fd")" \
    && "$(/usr/bin/sha256sum -- "$local_tools" 2>/dev/null | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" ]] \
    || block private_environment
readonly stdout_identity stderr_identity local_tools_identity
readonly stdout_stream=/proc/self/fd/${stdout_fd}
readonly stderr_stream=/proc/self/fd/${stderr_fd}
export GATE_LOCAL_TOOL_MANIFEST=$local_tools_export

cleanup_private_tree() {
    retain_batch_root
}

cleanup() {
    local saved=$?
    trap - EXIT HUP INT TERM
    if (( ! cleanup_complete && ! cleanup_attempted )) \
        && [[ "$private_fd" =~ ^[0-9]+$ && "$private_fd" -ge 10 ]]; then
        retain_batch_root >/dev/null 2>&1 || true
    fi
    close_batch_private_fds
    exit "$saved"
}
active_pid=
spawning=0
pending_signal=

stop_child() {
    local _ group
    [[ "${active_pid:-}" =~ ^[0-9]+$ ]] || return 0
    group=-$active_pid
    if /usr/bin/kill -0 -- "$group" 2>/dev/null || /usr/bin/kill -0 -- "$active_pid" 2>/dev/null; then
        /usr/bin/kill -TERM -- "$group" 2>/dev/null || true
        /usr/bin/kill -TERM -- "$active_pid" 2>/dev/null || true
        # Seven directory scrubs and the exact-file scrubs run concurrently;
        # the complete globally preflighted probe fallback is bounded at 125 seconds.
        # Allow 160 seconds after TERM before escalating the whole step group.
        for _ in {1..1600}; do
            if ! /usr/bin/kill -0 -- "$group" 2>/dev/null \
                && ! /usr/bin/kill -0 -- "$active_pid" 2>/dev/null; then
                break
            fi
            /usr/bin/sleep 0.1
        done
        if /usr/bin/kill -0 -- "$group" 2>/dev/null || /usr/bin/kill -0 -- "$active_pid" 2>/dev/null; then
            /usr/bin/kill -KILL -- "$group" 2>/dev/null || true
            /usr/bin/kill -KILL -- "$active_pid" 2>/dev/null || true
            for _ in {1..50}; do
                if ! /usr/bin/kill -0 -- "$group" 2>/dev/null \
                    && ! /usr/bin/kill -0 -- "$active_pid" 2>/dev/null; then
                    break
                fi
                /usr/bin/sleep 0.1
            done
        fi
    fi
    if /usr/bin/kill -0 -- "$group" 2>/dev/null || /usr/bin/kill -0 -- "$active_pid" 2>/dev/null; then
        return 1
    fi
    active_pid=
    return 0
}

handle_signal() {
    local name=$1
    if (( spawning )); then
        pending_signal=$name
        return
    fi
    trap - HUP INT TERM
    if ! stop_child; then
        if cleanup_private_tree; then
            cleanup_complete=1
            emit internal || exit 3
        else
            emit private_cleanup || exit 3
        fi
        exit 130
    fi
    if cleanup_private_tree; then
        cleanup_complete=1
        emit interrupted || exit 3
    else
        emit private_cleanup || exit 3
    fi
    exit 130
}

trap cleanup EXIT
trap 'handle_signal HUP' HUP
trap 'handle_signal INT' INT
trap 'handle_signal TERM' TERM

set +e
spawning=1
(
    exec </proc/self/fd/6 >&"$stdout_fd" 2>&"$stderr_fd"
    exec {private_fd}<&-
    exec {stdout_fd}>&- {stderr_fd}>&- {local_tools_fd}<&-
    exec 4>&- 5>&- 6>&- 7>&- 8>&- 9>&-
    exec /usr/bin/setsid /usr/bin/timeout --signal=TERM --kill-after=150s 1560s \
        /usr/bin/srun -M fair-cw-use2-3 --overlap --nodes=1 --ntasks=1 -w "$node" \
        --gpus-per-node=1 --cpus-per-task=4 --cpu-bind=none --export=ALL \
        /usr/bin/bash -p -s
) &
active_pid=$!
spawn_group_ready=0
for _ in {1..100}; do
    if /usr/bin/kill -0 -- "-$active_pid" 2>/dev/null; then
        spawn_group_ready=1
        break
    fi
    /usr/bin/kill -0 -- "$active_pid" 2>/dev/null || break
    /usr/bin/sleep 0.01
done
spawning=0
if [[ -n "$pending_signal" ]]; then
    handle_signal "$pending_signal"
fi
if (( ! spawn_group_ready )) && /usr/bin/kill -0 -- "$active_pid" 2>/dev/null; then
    if stop_child; then
        rc=125
    else
        if cleanup_private_tree; then
            cleanup_complete=1
            emit internal || exit 3
        else
            emit private_cleanup || exit 3
        fi
        exit 1
    fi
else
    wait "$active_pid"
    rc=$?
    active_pid=
fi
set -e

success='{"category":"success","image_digest":"sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20","kind":"k3-registry-pull-gate-v23","platform":"linux/arm64","state":"complete"}'
if (( rc == 0 )) && [[ "$(/usr/bin/stat -Lc '%s' "$stdout_stream")" -eq $((${#success} + 1)) \
    && "$(<"$stdout_stream")" == "$success" ]]; then
    if ! cleanup_private_tree; then
        trap - HUP INT TERM
        emit private_cleanup || exit 3
        exit 1
    fi
    cleanup_complete=1
    trap - HUP INT TERM
    emit success || exit 3
    exit 0
fi

if classify_registry_error_file "$stderr_stream" "$rc" "$stderr_identity"; then
    category=$REGISTRY_SAFE_CATEGORY
else
    category=internal
fi
if cleanup_private_tree; then
    cleanup_complete=1
else
    category=private_cleanup
fi
trap - HUP INT TERM
emit "$category" || exit 3
exit 1
