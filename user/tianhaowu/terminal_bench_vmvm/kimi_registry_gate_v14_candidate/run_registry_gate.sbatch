#!/usr/bin/bash -p
set +x
set -euo pipefail
umask 077
readonly expected_digest=sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20
readonly expected_image=588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/vllm-openai:kimi-k3-kda-logprobs-fix-v2-20260916@sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20
readonly expected_bundle=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t064500z_v14
readonly expected_result=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/k3_registry_pull_gate_20260920t064500z_v14/job_result.json
# Preserve the two inherited Slurm log descriptors solely for identity proof
# and the one allowlisted result. Silence every other command by construction.
exec 8>&1 4>&2 >/dev/null 2>/dev/null || exit 3

emit() {
    local category=$1 state=blocked
    [[ "$category" == success ]] && state=complete
    local raw temp temp_meta result_sha published=0
    raw=$(/usr/bin/printf '{"category":"%s","image_digest":"%s","kind":"k3-registry-pull-gate-v14","platform":"linux/arm64","state":"%s"}\n' \
        "$category" "$expected_digest" "$state")
    raw+=$'\n'
    if [[ "${GATE_JOB_RESULT:-}" == "$expected_result" \
        && "$(/usr/bin/stat -c '%F:%a:%u' -- "${GATE_JOB_RESULT%/*}" 2>/dev/null || true)" == 'directory:700:656177' \
        && ! -e "$GATE_JOB_RESULT" && ! -L "$GATE_JOB_RESULT" ]]; then
        temp=${GATE_JOB_RESULT}."${SLURM_JOB_ID:-unknown}"."$RANDOM".tmp
        if (set -o noclobber; /usr/bin/printf '%s' "$raw" > "$temp") 2>/dev/null \
            && /usr/bin/chmod 400 "$temp" 2>/dev/null \
            && /usr/bin/sync -f "$temp" 2>/dev/null \
            && /usr/bin/ln -- "$temp" "$GATE_JOB_RESULT" 2>/dev/null \
            && [[ "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$temp")" == 'regular file:400:656177:2' \
                && "$(/usr/bin/stat -Lc '%d:%i' -- "$temp")" == "$(/usr/bin/stat -Lc '%d:%i' -- "$GATE_JOB_RESULT")" ]] \
            && /usr/bin/unlink -- "$temp" 2>/dev/null \
            && [[ ! -e "$temp" && ! -L "$temp" \
                && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$GATE_JOB_RESULT")" == 'regular file:400:656177:1' ]]; then
            result_sha=$(/usr/bin/printf '%s' "$raw" | /usr/bin/sha256sum | /usr/bin/cut -d' ' -f1)
            if [[ "$result_sha" == "$(/usr/bin/sha256sum -- "$GATE_JOB_RESULT" | /usr/bin/cut -d' ' -f1)" ]] \
                && /usr/bin/sync -f "${GATE_JOB_RESULT%/*}" 2>/dev/null; then
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
    || block source_identity
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
[[ "$node" =~ ^g3-[0-9]{3}-[0-9]{3}$ && "$node" != g3-136-221 \
    && "$node" != g3-136-247 && "$node" != g3-136-251 && "$node" != g3-136-253 ]] \
    || block allocation_identity

log=${GATE_BUNDLE%/watchers/*}/logs/k3_registry_pull_gate_20260920t064500z_v14/slurm-${SLURM_JOB_ID}.log
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
private_identity=
stdout=
stderr=
local_tools=
cleanup_complete=0
early_cleanup() {
    local saved=$?
    trap - EXIT HUP INT TERM
    if (( ! cleanup_complete )) \
        && [[ -n "${private:-}" && "$private" == "$local_parent"/k3-registry-pull-v14.batch."${SLURM_JOB_ID}".* \
        && -d "$private" && ! -L "$private" \
        && ( -z "${private_identity:-}" \
            || "$private_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$private" 2>/dev/null || true)" ) ]]; then
        for early_owned in "${stdout:-}" "${stderr:-}" "${local_tools:-}"; do
            if [[ -n "$early_owned" && -f "$early_owned" && ! -L "$early_owned" \
                && "$(/usr/bin/stat -c '%u:%h' -- "$early_owned" 2>/dev/null || true)" == '656177:1' ]]; then
                /usr/bin/chmod 600 -- "$early_owned" 2>/dev/null || true
                /usr/bin/truncate -s 0 -- "$early_owned" 2>/dev/null || true
            fi
        done
        /usr/bin/timeout --signal=TERM --kill-after=5s 30s \
            /usr/bin/rm -r -- "$private" 2>/dev/null || true
    fi
    exit "$saved"
}
early_signal() {
    trap - HUP INT TERM
    emit interrupted || exit 3
    exit 130
}
trap early_cleanup EXIT
trap early_signal HUP INT TERM
private=$(/usr/bin/mktemp -d "$local_parent/k3-registry-pull-v14.batch.${SLURM_JOB_ID}.XXXXXX" 2>/dev/null) \
    || block private_environment
readonly private
private_identity=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$private" 2>/dev/null) \
    || block private_environment
readonly private_identity
[[ "$private" != /proc/self/fd/* \
    && "$private" == "$(/usr/bin/readlink -f -- "$private" 2>/dev/null)" \
    && -d "$private" && ! -L "$private" \
    && "$private_identity" == *':700:656177:2' ]] \
    || block private_environment
stdout=$private/stdout
stderr=$private/stderr
local_tools=$private/compute_tools.sha256
readonly stdout stderr local_tools
/usr/bin/touch "$stdout" "$stderr" 2>/dev/null \
    || block private_environment
/usr/bin/chmod 600 "$stdout" "$stderr" 2>/dev/null \
    || block private_environment
/usr/bin/cp -- /proc/self/fd/5 "$local_tools" 2>/dev/null \
    || block private_environment
/usr/bin/chmod 400 "$local_tools" 2>/dev/null \
    || block private_environment
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
    && "$(/usr/bin/sha256sum -- "$local_tools" 2>/dev/null | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" ]] \
    || block private_environment
export GATE_LOCAL_TOOL_MANIFEST=$local_tools

cleanup_private_tree() {
    [[ "$private" == "$local_parent"/k3-registry-pull-v14.batch."${SLURM_JOB_ID}".* \
        && -d "$private" && ! -L "$private" \
        && "$private_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$private" 2>/dev/null || true)" \
        && -f "$stdout" && ! -L "$stdout" && -f "$stderr" && ! -L "$stderr" \
        && -f "$local_tools" && ! -L "$local_tools" \
        && "$stdout_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$stdout" 2>/dev/null || true)" \
        && "$stderr_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$stderr" 2>/dev/null || true)" \
        && "$local_tools_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$local_tools" 2>/dev/null || true)" ]] \
        || return 1
    /usr/bin/truncate -s 0 -- "$stdout" 2>/dev/null || return 1
    /usr/bin/truncate -s 0 -- "$stderr" 2>/dev/null || return 1
    /usr/bin/chmod 600 -- "$local_tools" 2>/dev/null || return 1
    /usr/bin/truncate -s 0 -- "$local_tools" 2>/dev/null || return 1
    /usr/bin/unlink -- "$stdout" 2>/dev/null || return 1
    /usr/bin/unlink -- "$stderr" 2>/dev/null || return 1
    /usr/bin/unlink -- "$local_tools" 2>/dev/null || return 1
    /usr/bin/rmdir -- "$private" 2>/dev/null || return 1
    [[ ! -e "$private" && ! -L "$private" ]]
}

cleanup() {
    local saved=$?
    trap - EXIT HUP INT TERM
    if (( ! cleanup_complete )) \
        && [[ -n "${private:-}" && "$private" == "$local_parent"/k3-registry-pull-v14.batch."${SLURM_JOB_ID}".* \
        && -d "$private" && ! -L "$private" \
        && "$private_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$private" 2>/dev/null || true)" ]]; then
        for owned in "$stdout" "$stderr" "$local_tools"; do
            if [[ -f "$owned" && ! -L "$owned" \
                && "$(/usr/bin/stat -c '%u:%h' -- "$owned" 2>/dev/null || true)" == '656177:1' ]]; then
                /usr/bin/chmod 600 -- "$owned" 2>/dev/null || true
                /usr/bin/truncate -s 0 -- "$owned" 2>/dev/null || true
            fi
        done
        /usr/bin/timeout --signal=TERM --kill-after=5s 30s \
            /usr/bin/chmod -R u+w "$private" 2>/dev/null || true
        /usr/bin/timeout --signal=TERM --kill-after=5s 30s \
            /usr/bin/rm -r -- "$private" 2>/dev/null || true
    fi
    exit "$saved"
}
active_pid=
spawning=0
pending_signal=

stop_child() {
    local _ group
    [[ "${active_pid:-}" =~ ^[0-9]+$ ]] || return 0
    group=-$active_pid
    if /usr/bin/kill -0 -- "$group" 2>/dev/null; then
        /usr/bin/kill -TERM -- "$group" 2>/dev/null || true
        for _ in {1..350}; do
            /usr/bin/kill -0 -- "$group" 2>/dev/null || break
            /usr/bin/sleep 0.1
        done
        if /usr/bin/kill -0 -- "$group" 2>/dev/null; then
            /usr/bin/kill -KILL -- "$group" 2>/dev/null || true
            for _ in {1..100}; do
                /usr/bin/kill -0 -- "$group" 2>/dev/null || break
                /usr/bin/sleep 0.1
            done
        fi
    fi
    if /usr/bin/kill -0 -- "$group" 2>/dev/null; then
        return 1
    fi
    wait "$active_pid" 2>/dev/null || true
    active_pid=
    return 0
}

handle_signal() {
    local name=$1
    if (( spawning )) && [[ -z "${active_pid:-}" ]]; then
        pending_signal=$name
        return
    fi
    trap - HUP INT TERM
    if ! stop_child; then
        cleanup_complete=1
        emit internal || exit 3
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
/usr/bin/setsid /usr/bin/timeout --signal=TERM --kill-after=30s 1740s \
    /usr/bin/srun -M fair-cw-use2-3 --overlap --nodes=1 --ntasks=1 -w "$node" \
    --gpus-per-node=1 --cpus-per-task=4 --cpu-bind=none --export=ALL \
    /usr/bin/bash -p -s >"$stdout" 2>"$stderr" < /proc/self/fd/6 \
    4>&- 5>&- 6>&- 7>&- 8>&- 9>&- &
active_pid=$!
spawning=0
if [[ -n "$pending_signal" ]]; then
    handle_signal "$pending_signal"
fi
wait "$active_pid"
rc=$?
active_pid=
set -e

success='{"category":"success","image_digest":"sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20","kind":"k3-registry-pull-gate-v14","platform":"linux/arm64","state":"complete"}'
if (( rc == 0 )) && [[ "$(/usr/bin/stat -c '%s' "$stdout")" -eq $((${#success} + 1)) \
    && "$(<"$stdout")" == "$success" ]]; then
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

if classify_registry_error_file "$stderr" "$rc"; then
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
