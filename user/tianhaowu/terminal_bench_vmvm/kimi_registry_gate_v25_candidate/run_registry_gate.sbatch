#!/usr/bin/bash -p
set +x
set -euo pipefail
shopt -u varredir_close
umask 077
readonly expected_digest=sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20
readonly expected_image=588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/vllm-openai:kimi-k3-kda-logprobs-fix-v2-20260916@sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20
readonly expected_bundle=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t150000z_v25
readonly expected_result=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/k3_registry_pull_gate_20260920t150000z_v25/job_result.json
readonly expected_compute_manifest_entries=33
readonly teardown_budget_seconds=210
readonly publication_reserve_seconds=20
teardown_deadline=0
cleanup_deadline=0
publication_started=0
publication_in_progress=0
publication_finished=0
publication_rc=1
publication_category=
writer_state=absent
active_pid=
active_group_id=
spawning=0
scrubber_exec_fd=-1
# Preserve the two inherited Slurm log descriptors solely for identity proof
# and the one allowlisted result. Silence every other command by construction.
exec 8>&1 4>&2 || exit 3
exec >/dev/null 2>/dev/null || exit 3

arm_teardown_deadline() {
    local cleanup_limit
    if (( teardown_deadline == 0 )); then
        teardown_deadline=$((SECONDS + teardown_budget_seconds))
    fi
    cleanup_limit=$((teardown_deadline - publication_reserve_seconds))
    if (( cleanup_deadline == 0 || cleanup_deadline > cleanup_limit )); then
        cleanup_deadline=$cleanup_limit
    fi
}

active_writer_live() {
    writer_group_live || writer_pid_live
}

writer_pid_live() {
    [[ "${active_pid:-}" =~ ^[0-9]+$ ]] \
        && /usr/bin/kill -0 -- "$active_pid" 2>/dev/null
}

writer_group_live() {
    [[ "${active_group_id:-}" =~ ^[0-9]+$ ]] \
        && /usr/bin/kill -0 -- "-$active_group_id" 2>/dev/null
}

signal_writer() {
    local signal_name=$1
    if [[ "${active_group_id:-}" =~ ^[0-9]+$ ]]; then
        /usr/bin/kill -"$signal_name" -- "-$active_group_id" 2>/dev/null || true
    fi
    if [[ "${active_pid:-}" =~ ^[0-9]+$ ]]; then
        /usr/bin/kill -"$signal_name" -- "$active_pid" 2>/dev/null || true
    fi
}

mark_live_writer_cleanup_unproven() {
    writer_state=unproven
    cleanup_outcome=live_writer_cleanup_unproven
}

mark_writer_quiesced() {
    [[ "${writer_state:-absent}" != unproven ]] || return 1
    active_pid=
    active_group_id=
    spawning=0
    writer_state=quiesced
}

writer_cleanup_allowed() {
    (( ${spawning:-0} == 0 )) \
        && [[ "${writer_state:-absent}" == absent || "${writer_state:-absent}" == quiesced ]] \
        && ! active_writer_live
}

publication_checkpoint() {
    :
}

publication_child_checkpoint() {
    :
}

cleanup_public_temp() {
    local opened named result_inode dev_inode uid nlink size exact_named=0
    if [[ "${publish_temp_fd:--1}" =~ ^[0-9]+$ && "$publish_temp_fd" -ge 10 ]]; then
        opened=$(/usr/bin/stat -Lc '%d:%i:%u:%h:%s' -- "/proc/self/fd/$publish_temp_fd" 2>/dev/null || true)
        if [[ "$opened" =~ ^[0-9]+:[0-9]+:${publish_expected_uid}:[012]:[0-9]+$ ]]; then
            dev_inode=${opened%:*:*:*}
            if [[ -e "$publish_temp" || -L "$publish_temp" ]]; then
                named=$(/usr/bin/stat -c '%d:%i:%u:%h:%s' -- "$publish_temp" 2>/dev/null || true)
                [[ "$named" == "$opened" ]] && exact_named=1
            fi
            result_inode=$(/usr/bin/stat -c '%d:%i' -- "$publish_result" 2>/dev/null || true)
            if [[ "$result_inode" == "$dev_inode" && "$opened" == *':2:'* ]]; then
                publish_committed=1
            fi
            if (( publish_committed == 0 )); then
                /usr/bin/chmod 600 -- "/proc/self/fd/$publish_temp_fd" 2>/dev/null || true
                /usr/bin/truncate -s 0 -- "/proc/self/fd/$publish_temp_fd" 2>/dev/null || true
                /usr/bin/sync -f "/proc/self/fd/$publish_temp_fd" 2>/dev/null || true
            fi
        fi
        exec {publish_temp_fd}>&- || true
        publish_temp_fd=-1
    fi
    if [[ -e "${publish_temp:-}" || -L "${publish_temp:-}" ]]; then
        named=$(/usr/bin/stat -c '%d:%i:%u:%h:%s' -- "$publish_temp" 2>/dev/null || true)
        dev_inode=${publish_temp_identity%:*}
        uid=${publish_temp_identity##*:}
        nlink=${named%:*}
        nlink=${nlink##*:}
        size=${named##*:}
        if [[ -n "${publish_temp_identity:-}" && "$named" == "$dev_inode:$uid:1:0" ]]; then
            /usr/bin/unlink -- "$publish_temp" 2>/dev/null || true
        elif (( publish_committed )) \
            && [[ -n "${publish_temp_identity:-}" && "$named" == "$dev_inode:$uid:2:$size" \
                && "$size" =~ ^[0-9]+$ \
                && "$dev_inode" == "$(/usr/bin/stat -c '%d:%i' -- "$publish_result" 2>/dev/null || true)" ]]; then
            /usr/bin/unlink -- "$publish_temp" 2>/dev/null || true
        fi
    fi
}

publish_payload() {
    local raw=$1 temp=$2 result=$3 required_result=$4 expected_uid=$5
    local result_sha published=0 output_written=0 payload_written=0 opened named result_meta
    local pdev pino pmode puid pnlink psize
    publish_temp=$temp
    publish_result=$result
    publish_expected_uid=$expected_uid
    publish_temp_fd=-1
    publish_temp_identity=
    publish_committed=0
    publication_parent_pid=$6
    set +x
    umask 077
    trap cleanup_public_temp EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM
    if [[ "$result" == "$required_result" \
        && "$temp" == "$result".*.tmp \
        && "$(/usr/bin/stat -c '%F:%a:%u' -- "${result%/*}" 2>/dev/null || true)" == "directory:700:${expected_uid}" \
        && ! -e "$result" && ! -L "$result" ]]; then
        publication_child_checkpoint child_before_temp_open
        set -o noclobber
        if { exec {publish_temp_fd}>"$temp"; } 2>/dev/null; then
            set +o noclobber
            publication_child_checkpoint child_after_temp_open
            opened=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "/proc/self/fd/$publish_temp_fd" 2>/dev/null || true)
            named=$(/usr/bin/stat -c '%d:%i:%a:%u:%h:%s' -- "$temp" 2>/dev/null || true)
            if [[ "$opened" == "$named" && "$opened" == *":600:${expected_uid}:1:0" ]]; then
                IFS=: read -r pdev pino pmode puid pnlink psize <<< "$opened"
                publish_temp_identity=$pdev:$pino:$puid
                publication_child_checkpoint child_after_temp_identity
                if /usr/bin/printf '%s' "$raw" >&"$publish_temp_fd"; then
                    payload_written=1
                    publication_child_checkpoint child_after_temp_write
                fi
                if (( payload_written )) \
                    && /usr/bin/chmod 400 -- "/proc/self/fd/$publish_temp_fd" 2>/dev/null \
                    && /usr/bin/sync -f "/proc/self/fd/$publish_temp_fd" 2>/dev/null; then
                    publication_child_checkpoint child_after_temp_sync
                    opened=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "/proc/self/fd/$publish_temp_fd" 2>/dev/null || true)
                    named=$(/usr/bin/stat -c '%d:%i:%a:%u:%h:%s' -- "$temp" 2>/dev/null || true)
                    if [[ "$opened" == "$named" && "$opened" == *":400:${expected_uid}:1:${#raw}" ]]; then
                        publication_child_checkpoint child_before_link
                        if /usr/bin/ln -- "$temp" "$result" 2>/dev/null; then
                            publish_committed=1
                        elif [[ "$(/usr/bin/stat -c '%d:%i' -- "$result" 2>/dev/null || true)" == "${publish_temp_identity%:*}" \
                            && "$(/usr/bin/stat -Lc '%h' -- "/proc/self/fd/$publish_temp_fd" 2>/dev/null || true)" == 2 ]]; then
                            publish_committed=1
                        fi
                        publication_child_checkpoint child_after_link
                    fi
                fi
            fi
            if (( publish_committed )); then
                result_meta=$(/usr/bin/stat -Lc '%d:%i:%F:%a:%u:%h:%s' -- "$result" 2>/dev/null || true)
                if [[ "$result_meta" == "${publish_temp_identity%:*}:regular file:400:${expected_uid}:2:${#raw}" ]]; then
                    publication_child_checkpoint child_before_temp_close
                    exec {publish_temp_fd}>&-
                    publish_temp_fd=-1
                    publication_child_checkpoint child_after_temp_close
                    publication_child_checkpoint child_before_temp_unlink
                    if /usr/bin/unlink -- "$temp" 2>/dev/null; then
                        publication_child_checkpoint child_after_temp_unlink
                    fi
                    if [[ ! -e "$temp" && ! -L "$temp" \
                        && "$(/usr/bin/stat -Lc '%d:%i:%F:%a:%u:%h:%s' -- "$result" 2>/dev/null || true)" == "${publish_temp_identity%:*}:regular file:400:${expected_uid}:1:${#raw}" ]]; then
                        result_sha=$(/usr/bin/printf '%s' "$raw" | /usr/bin/sha256sum | /usr/bin/cut -d' ' -f1)
                        if [[ "$result_sha" == "$(/usr/bin/sha256sum -- "$result" 2>/dev/null | /usr/bin/cut -d' ' -f1)" ]] \
                            && /usr/bin/sync -f "${result%/*}" 2>/dev/null; then
                            published=1
                            publication_child_checkpoint child_after_result_sync
                        fi
                    fi
                fi
            fi
        fi
        set +o noclobber
    fi
    publication_child_checkpoint child_before_fd8
    if /usr/bin/printf '%s' "$raw" >&8; then
        output_written=1
        publication_child_checkpoint child_after_fd8
        if ! /usr/bin/sync -f /proc/self/fd/8 2>/dev/null; then
            output_written=0
        fi
        publication_child_checkpoint child_after_fd8_sync
    fi
    (( published == 1 && output_written == 1 ))
}

emit() {
    local category=$1 state=blocked raw temp publisher_source remaining duration rc
    if (( publication_started )); then
        return "$publication_rc"
    fi
    if ! writer_cleanup_allowed; then
        mark_live_writer_cleanup_unproven
        category=live_writer_cleanup_unproven
    fi
    publication_checkpoint parent_before_started
    (( publication_started = 1, publication_in_progress = 1 ))
    publication_category=$category
    publication_checkpoint parent_after_started
    [[ "$category" == success ]] && state=complete
    arm_teardown_deadline
    raw=$(/usr/bin/printf '{"category":"%s","image_digest":"%s","kind":"k3-registry-pull-gate-v25","platform":"linux/arm64","state":"%s"}\n' \
        "$category" "$expected_digest" "$state")
    raw+=$'\n'
    temp=${GATE_JOB_RESULT:-$expected_result}."${SLURM_JOB_ID:-unknown}"."$RANDOM".tmp
    remaining=$((teardown_deadline - SECONDS))
    if (( remaining <= 2 )); then
        publication_rc=1
        publication_finished=1
        publication_in_progress=0
        return 1
    fi
    duration=$((remaining - 1))
    if ! publisher_source=$(declare -f cleanup_public_temp publication_child_checkpoint publish_payload); then
        publication_rc=1
        publication_finished=1
        publication_in_progress=0
        return 1
    fi
    publication_checkpoint parent_before_publisher
    if /usr/bin/timeout --signal=TERM --kill-after=1s "${duration}s" \
        /usr/bin/bash -p -c "$publisher_source"$'\n''publish_payload "$@"' \
        gate-publisher "$raw" "$temp" "${GATE_JOB_RESULT:-}" "$expected_result" 656177 "$BASHPID" \
        >/dev/null 2>/dev/null; then
        rc=0
    else
        rc=$?
    fi
    publication_checkpoint parent_after_publisher
    publication_rc=$rc
    publication_finished=1
    publication_checkpoint parent_before_in_progress_clear
    publication_in_progress=0
    publication_checkpoint parent_after_in_progress_clear
    return "$publication_rc"
}

finish_publication() {
    local category=$1 status=$2
    if [[ -n "${pending_signal:-}" \
        && "$category" != private_cleanup_retained \
        && "$category" != private_cleanup_sensitive \
        && "$category" != live_writer_cleanup_unproven ]]; then
        category=interrupted
    fi
    if ! emit "$category"; then
        status=3
    fi
    if [[ -n "${pending_signal:-}" ]]; then
        status=$pending_signal_status
    fi
    trap - HUP INT TERM
    exit "$status"
}

block() {
    local category=$1
    if declare -F cleanup_private_tree >/dev/null \
        && [[ -n "${private:-}" || "${private_fd:--1}" =~ ^[0-9]+$ ]]; then
        arm_teardown_deadline
        if ! cleanup_private_tree; then
            case "${cleanup_outcome:-sensitive_residue}" in
                retained_drift) category=private_cleanup_retained ;;
                live_writer_cleanup_unproven) category=live_writer_cleanup_unproven ;;
                *) category=private_cleanup_sensitive ;;
            esac
        fi
    fi
    finish_publication "$category" 2
}

compute_manifest_attestation() {
    local manifest=$1 expected_entries=$2 line expected tool actual_line actual metadata
    local index=0 mismatch_count=0 mismatch_bitmap= mismatch=0
    COMPUTE_MANIFEST_CATEGORY=
    while IFS= read -r line; do
        (( index < expected_entries )) || return 2
        if [[ "$line" =~ ^([0-9a-f]{64})[[:space:]][[:space:]](/usr/bin/[A-Za-z0-9._+-]+)$ ]]; then
            expected=${BASH_REMATCH[1]}
            tool=${BASH_REMATCH[2]}
        else
            return 2
        fi
        metadata=$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$tool" 2>/dev/null || true)
        actual_line=$(/usr/bin/sha256sum -- "$tool" 2>/dev/null || true)
        actual=${actual_line%% *}
        mismatch=0
        if [[ "$metadata" != 'regular file:755:0:1' || "$actual" != "$expected" ]]; then
            mismatch_count=$((mismatch_count + 1))
            mismatch=1
        fi
        mismatch_bitmap+=$mismatch
        index=$((index + 1))
    done < "$manifest"
    (( index == expected_entries )) || return 2
    if (( mismatch_count > 0 )); then
        printf -v COMPUTE_MANIFEST_CATEGORY \
            'source_compute_manifest_c%02d_b%s' "$mismatch_count" "$mismatch_bitmap"
        return 1
    fi
    return 0
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
readonly scrubber=$expected_bundle/scrub_private_tree.py
readonly tools_manifest=$expected_bundle/compute_tools.sha256
script_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "${BASH_SOURCE[0]}" 2>/dev/null) \
    || block source_spool_identity
if ! { exec 9<"${BASH_SOURCE[0]}"; } 2>/dev/null; then
    block source_spool_identity
fi
[[ -f /proc/self/fd/9 \
    && "$script_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/9 2>/dev/null)" \
    && "$script_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "${BASH_SOURCE[0]}" 2>/dev/null)" ]] \
    || block source_spool_identity
[[ "$(/usr/bin/sha256sum -- /proc/self/fd/9 2>/dev/null | /usr/bin/cut -d' ' -f1)" \
    == "${GATE_BATCH_SHA256:-}" ]] \
    || block source_spool_hash
classifier_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$classifier" 2>/dev/null) \
    || block source_bundle_identity
probe_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$probe" 2>/dev/null) \
    || block source_bundle_identity
tools_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest" 2>/dev/null) \
    || block source_bundle_identity
scrubber_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$scrubber" 2>/dev/null) \
    || block source_bundle_identity
if ! { exec 7<"$classifier" 6<"$probe" 5<"$tools_manifest" 3<"$scrubber"; } 2>/dev/null; then
    block source_bundle_identity
fi
scrubber_exec_fd=3
[[ -f /proc/self/fd/7 && -f /proc/self/fd/6 && -f /proc/self/fd/5 && -f /proc/self/fd/3 \
    && "$classifier_before" == *':500:656177:1:'* \
    && "$classifier_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/7 2>/dev/null)" \
    && "$classifier_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$classifier" 2>/dev/null)" \
    && "$probe_before" == *':500:656177:1:'* \
    && "$probe_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/6 2>/dev/null)" \
    && "$probe_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$probe" 2>/dev/null)" \
    && "$tools_before" == *':400:656177:1:'* \
    && "$tools_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/5 2>/dev/null)" \
    && "$tools_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest" 2>/dev/null)" \
    && "$scrubber_before" == *':500:656177:1:'* \
    && "$scrubber_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/3 2>/dev/null)" \
    && "$scrubber_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$scrubber" 2>/dev/null)" ]] \
    || block source_bundle_identity
[[ "$(/usr/bin/sha256sum -- /proc/self/fd/7 2>/dev/null | /usr/bin/cut -d' ' -f1)" == "${GATE_CLASSIFIER_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/6 2>/dev/null | /usr/bin/cut -d' ' -f1)" == "${GATE_PROBE_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/5 2>/dev/null | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/3 2>/dev/null | /usr/bin/cut -d' ' -f1)" == "${GATE_SCRUBBER_SHA256:-}" ]] \
    || block source_bundle_hash
source /proc/self/fd/7 || block source_bundle_hash
if compute_manifest_attestation /proc/self/fd/5 "$expected_compute_manifest_entries"; then
    :
else
    compute_manifest_rc=$?
    if (( compute_manifest_rc == 1 )) \
        && [[ "$COMPUTE_MANIFEST_CATEGORY" =~ ^source_compute_manifest_c([0-9]{2})_b([01]{33})$ ]]; then
        block "$COMPUTE_MANIFEST_CATEGORY"
    fi
    block source_bundle_hash
fi

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

log=${GATE_BUNDLE%/watchers/*}/logs/k3_registry_pull_gate_20260920t150000z_v25/slurm-${SLURM_JOB_ID}.log
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
local_scrubber=
local_scrubber_export=
stdout_fd=-1
stderr_fd=-1
local_tools_fd=-1
local_scrubber_fd=-1
stdout_clean=0
stderr_clean=0
local_tools_clean=0
local_scrubber_clean=0
stdout_identity=
stderr_identity=
local_tools_identity=
local_scrubber_identity=
cleanup_complete=0
cleanup_outcome=sensitive_residue
cleanup_root_drift=0
cleanup_running=0
cleanup_in_progress=0
cleanup_exit_running=0
cleanup_retry_limit=3
pending_signal=
pending_signal_status=130
signal_handling=0

cleanup_checkpoint() {
    :
}

remember_signal() {
    pending_signal=$1
    case "$1" in
        HUP) pending_signal_status=129 ;;
        INT) pending_signal_status=130 ;;
        TERM) pending_signal_status=143 ;;
        *) pending_signal_status=130 ;;
    esac
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
    local owned expected expected_base expected_dev_inode expected_uid observed opened leftover owned_fd already_clean
    [[ "$private_anchor_trusted" == 1 \
        && "$private_fd" =~ ^[0-9]+$ && "$private_fd" -ge 10 \
        && -d "$private_anchor" && ! -L "$private_anchor" \
        && "$private_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$private_anchor" 2>/dev/null || true)" ]] \
        || return 1
    batch_mount_free || return 1
    leftover=$(/usr/bin/timeout --signal=TERM --kill-after=1s 3s \
        /usr/bin/find "$private_anchor" -xdev -mindepth 1 -maxdepth 1 \
            ! -name stdout ! -name stderr ! -name compute_tools.sha256 \
            ! -name scrub_private_tree.py -print -quit 2>/dev/null) \
        || return 1
    [[ -z "$leftover" ]] || return 1
    for owned in "$stdout" "$stderr" "$local_tools" "$local_scrubber"; do
        case "$owned" in
            "$stdout") expected=$stdout_identity; owned_fd=$stdout_fd; already_clean=$stdout_clean ;;
            "$stderr") expected=$stderr_identity; owned_fd=$stderr_fd; already_clean=$stderr_clean ;;
            "$local_tools") expected=$local_tools_identity; owned_fd=$local_tools_fd; already_clean=$local_tools_clean ;;
            "$local_scrubber") expected=$local_scrubber_identity; owned_fd=$local_scrubber_fd; already_clean=$local_scrubber_clean ;;
            *) return 1 ;;
        esac
        if (( already_clean )); then
            [[ "$owned_fd" == -1 ]] || return 1
            if [[ -e "$owned" || -L "$owned" ]]; then
                cleanup_root_drift=1
            fi
            continue
        fi
        [[ "$owned_fd" =~ ^[0-9]+$ && "$owned_fd" -ge 10 && -n "$expected" ]] || return 1
        expected_base=${expected%:*}
        expected_dev_inode=${expected%:*:*:*}
        expected_uid=${expected%:*}
        expected_uid=${expected_uid##*:}
        opened=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$owned_fd" 2>/dev/null || true)
        [[ "$opened" == "$expected_base:0" || "$opened" == "$expected_base:1" \
            || "$opened" == "$expected_dev_inode:600:$expected_uid:1" \
            || "$opened" == "$expected_dev_inode:600:$expected_uid:0" ]] \
            || return 1
        observed=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$owned" 2>/dev/null || true)
        if [[ "$observed" != "$opened" ]]; then
            cleanup_root_drift=1
        fi
    done
}

scrub_batch_contents() {
    local owned expected expected_base expected_dev_inode expected_uid observed opened after leftover
    local boundary owned_fd already_clean entry_name root_dev remaining timeout_seconds helper_rc failed=0
    if ! writer_cleanup_allowed; then
        mark_live_writer_cleanup_unproven
        return 1
    fi
    preflight_batch_contents || return 1
    cleanup_checkpoint batch_scrub_start
    for owned in "$stdout" "$stderr" "$local_tools" "$local_scrubber"; do
        [[ -n "$owned" ]] || continue
        case "$owned" in
            "$stdout") expected=$stdout_identity; boundary=stdout; entry_name=stdout; owned_fd=$stdout_fd; already_clean=$stdout_clean ;;
            "$stderr") expected=$stderr_identity; boundary=stderr; entry_name=stderr; owned_fd=$stderr_fd; already_clean=$stderr_clean ;;
            "$local_tools") expected=$local_tools_identity; boundary=tools; entry_name=compute_tools.sha256; owned_fd=$local_tools_fd; already_clean=$local_tools_clean ;;
            "$local_scrubber") expected=$local_scrubber_identity; boundary=scrubber; entry_name=scrub_private_tree.py; owned_fd=$local_scrubber_fd; already_clean=$local_scrubber_clean ;;
            *) return 1 ;;
        esac
        (( already_clean == 0 )) || continue
        cleanup_checkpoint "batch_before_${boundary}"
        [[ "$owned_fd" =~ ^[0-9]+$ && "$owned_fd" -ge 10 ]] \
            || { failed=1; continue; }
        expected_base=${expected%:*}
        expected_dev_inode=${expected%:*:*:*}
        expected_uid=${expected%:*}
        expected_uid=${expected_uid##*:}
        opened=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$owned_fd" 2>/dev/null || true)
        [[ "$opened" == "$expected_base:0" || "$opened" == "$expected_base:1" \
            || "$opened" == "$expected_dev_inode:600:$expected_uid:0" \
            || "$opened" == "$expected_dev_inode:600:$expected_uid:1" ]] \
            || { failed=1; continue; }
        if [[ -e "$owned" || -L "$owned" ]]; then
            observed=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$owned" 2>/dev/null || true)
            cleanup_checkpoint "batch_after_${boundary}_stat"
            if [[ "$observed" != "$opened" || ! -f "$owned" || -L "$owned" ]]; then
                cleanup_root_drift=1
            fi
        else
            cleanup_root_drift=1
        fi
        # The helper must remain executable until Python has compiled it. For
        # the helper's own inode, its bound process performs the chmod,
        # truncate, fsync, and unlink. All other raw files are scrubbed once in
        # this shell and re-proved by the helper before unlinkat.
        if [[ "$boundary" != scrubber ]]; then
            /usr/bin/chmod 600 -- "/proc/self/fd/$owned_fd" 2>/dev/null || { failed=1; continue; }
            cleanup_checkpoint "batch_after_${boundary}_chmod"
            /usr/bin/truncate -s 0 -- "/proc/self/fd/$owned_fd" 2>/dev/null || { failed=1; continue; }
            /usr/bin/sync -f "/proc/self/fd/$owned_fd" 2>/dev/null || { failed=1; continue; }
            cleanup_checkpoint "batch_after_${boundary}_truncate"
            after=$(/usr/bin/stat -Lc '%d:%i:%u:%h:%s' -- "/proc/self/fd/$owned_fd" 2>/dev/null || true)
            [[ "$after" == "$expected_dev_inode:$expected_uid:0:0" \
                || "$after" == "$expected_dev_inode:$expected_uid:1:0" ]] \
                || { failed=1; continue; }
        fi
        cleanup_checkpoint "batch_before_${boundary}_unlink"
        remaining=$((cleanup_deadline - SECONDS))
        if (( remaining <= 2 )); then
            failed=1
            continue
        fi
        timeout_seconds=$((remaining - 1))
        root_dev=${private_identity%%:*}
        if /usr/bin/timeout --signal=TERM --kill-after=1s "${timeout_seconds}s" \
            /usr/bin/python3.12 -I -S -B "/proc/self/fd/$scrubber_exec_fd" \
            --bound-file "$expected_uid" "$root_dev" "$private_fd" "$entry_name" "$owned_fd" \
            >/dev/null 2>&1; then
            helper_rc=0
        else
            helper_rc=$?
        fi
        case "$helper_rc" in
            0) ;;
            42) cleanup_root_drift=1 ;;
            *) failed=1; continue ;;
        esac
        cleanup_checkpoint "batch_after_${boundary}_unlink"
        after=$(/usr/bin/stat -Lc '%d:%i:%u:%h:%s' -- "/proc/self/fd/$owned_fd" 2>/dev/null || true)
        if (( helper_rc == 0 )); then
            [[ "$after" == "$expected_dev_inode:$expected_uid:0:0" ]] \
                || { failed=1; continue; }
        else
            [[ "$after" == "$expected_dev_inode:$expected_uid:1:0" ]] \
                || { failed=1; continue; }
        fi
        case "$boundary" in
            stdout) exec {stdout_fd}<&- && { stdout_fd=-1; stdout_clean=1; } || failed=1 ;;
            stderr) exec {stderr_fd}<&- && { stderr_fd=-1; stderr_clean=1; } || failed=1 ;;
            tools) exec {local_tools_fd}<&- && { local_tools_fd=-1; local_tools_clean=1; } || failed=1 ;;
            scrubber) exec {local_scrubber_fd}<&- && { local_scrubber_fd=-1; local_scrubber_clean=1; } || failed=1 ;;
            *) failed=1 ;;
        esac
        cleanup_checkpoint "batch_after_${boundary}"
    done
    cleanup_checkpoint batch_before_empty_check
    leftover=$(/usr/bin/timeout --signal=TERM --kill-after=1s 3s \
        /usr/bin/find "$private_anchor" -xdev -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null) \
        || failed=1
    cleanup_checkpoint batch_after_empty_check
    if [[ -n "$leftover" ]]; then
        if (( cleanup_root_drift )); then
            :
        else
            failed=1
        fi
    fi
    (( failed == 0 ))
}

remove_batch_root() {
    local anchored_after= named_now= rc=0
    if ! writer_cleanup_allowed; then
        mark_live_writer_cleanup_unproven
        return 1
    fi
    cleanup_checkpoint batch_before_in_progress
    cleanup_in_progress=1
    cleanup_checkpoint batch_in_progress
    scrub_batch_contents || rc=1
    cleanup_checkpoint batch_after_scrub
    cleanup_checkpoint batch_before_named_stat
    if [[ -e "$private" || -L "$private" ]]; then
        named_now=$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private" 2>/dev/null || true)
        [[ "$named_now" == "$private_identity" ]] || cleanup_root_drift=1
    else
        cleanup_root_drift=1
    fi
    cleanup_checkpoint batch_after_named_stat
    if (( rc == 0 )); then
        cleanup_checkpoint batch_before_retained_root_proof
        anchored_after=$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$private_anchor" 2>/dev/null) || rc=1
        [[ "$anchored_after" == "$private_identity" ]] || rc=1
    fi
    cleanup_checkpoint batch_after_retained_root_proof
    if (( rc == 0 )); then
        cleanup_checkpoint batch_before_fd_close
        if exec {private_fd}<&-; then
            private_fd=-1
        else
            rc=1
        fi
    fi
    cleanup_checkpoint batch_after_fd_close
    if (( rc == 0 )); then
        cleanup_checkpoint batch_before_complete
        if (( cleanup_root_drift )); then
            cleanup_outcome=retained_drift
        else
            cleanup_complete=1
            cleanup_outcome=retained_empty
        fi
    fi
    cleanup_checkpoint batch_after_complete
    cleanup_checkpoint batch_before_in_progress_clear
    cleanup_in_progress=0
    cleanup_checkpoint batch_after_in_progress
    (( rc == 0 && cleanup_complete == 1 && cleanup_root_drift == 0 ))
}

cleanup_private_tree() {
    local attempt=0 rc=1
    if ! writer_cleanup_allowed; then
        mark_live_writer_cleanup_unproven
        return 1
    fi
    if (( cleanup_complete )); then
        [[ "$cleanup_outcome" == retained_empty ]] && return 0
        return 1
    fi
    cleanup_checkpoint batch_before_cleanup_running
    cleanup_running=1
    cleanup_checkpoint batch_cleanup_running
    if ! [[ "$private_fd" =~ ^[0-9]+$ && "$private_fd" -ge 10 ]]; then
        if [[ -z "$private" ]]; then
            cleanup_complete=1
            cleanup_outcome=retained_empty
            rc=0
        fi
    else
        if (( cleanup_deadline == 0 )); then
            cleanup_deadline=$((SECONDS + 90))
        fi
        while (( cleanup_complete == 0 && attempt < cleanup_retry_limit && SECONDS < cleanup_deadline )); do
            cleanup_checkpoint batch_before_attempt
            attempt=$((attempt + 1))
            if remove_batch_root; then
                cleanup_checkpoint batch_after_attempt
                break
            fi
            cleanup_checkpoint batch_after_attempt
        done
        if (( cleanup_complete == 1 )) && [[ "$cleanup_outcome" == retained_empty ]]; then
            rc=0
        fi
    fi
    cleanup_checkpoint batch_before_cleanup_running_clear
    cleanup_running=0
    cleanup_checkpoint batch_after_cleanup_running
    (( rc == 0 ))
}

exit_cleanup() {
    local saved=$?
    trap - EXIT
    cleanup_exit_running=1
    if declare -F arm_teardown_deadline >/dev/null; then
        arm_teardown_deadline
    fi
    if [[ "${writer_state:-absent}" != absent \
        && "${writer_state:-absent}" != quiesced \
        && "${writer_state:-absent}" != unproven ]] \
        && declare -F stop_child >/dev/null; then
        if ! stop_child; then
            mark_live_writer_cleanup_unproven
        fi
    fi
    if [[ "${writer_state:-absent}" == unproven ]]; then
        # A descendant still owns the private streams.  Never truncate or
        # unlink beneath it; publish only the truthful fail-closed category.
        if (( publication_started == 0 )); then
            if ! emit live_writer_cleanup_unproven; then
                saved=3
            fi
        elif [[ "$publication_category" != live_writer_cleanup_unproven ]]; then
            saved=3
        fi
    elif ! cleanup_private_tree >/dev/null 2>&1 && (( saved == 0 )); then
        saved=3
    fi
    if [[ "$private_fd" =~ ^[0-9]+$ && "$private_fd" -ge 10 ]]; then
        exec {private_fd}<&- || true
    fi
    if [[ "$stdout_fd" =~ ^[0-9]+$ && "$stdout_fd" -ge 10 ]]; then
        exec {stdout_fd}<&- || true
    fi
    if [[ "$stderr_fd" =~ ^[0-9]+$ && "$stderr_fd" -ge 10 ]]; then
        exec {stderr_fd}<&- || true
    fi
    if [[ "$local_tools_fd" =~ ^[0-9]+$ && "$local_tools_fd" -ge 10 ]]; then
        exec {local_tools_fd}<&- || true
    fi
    if [[ "$local_scrubber_fd" =~ ^[0-9]+$ && "$local_scrubber_fd" -ge 10 ]]; then
        exec {local_scrubber_fd}<&- || true
    fi
    if [[ -n "$pending_signal" ]]; then
        saved=$pending_signal_status
    fi
    exit "$saved"
}
early_signal() {
    remember_signal "$1"
    arm_teardown_deadline
    if (( publication_started && publication_in_progress )); then
        :
    elif (( publication_started )); then
        exit "$pending_signal_status"
    elif (( cleanup_running || cleanup_in_progress || cleanup_exit_running || signal_handling )); then
        :
    else
        signal_handling=1
        arm_teardown_deadline
        if cleanup_private_tree; then
            finish_publication interrupted "$pending_signal_status"
        else
            if [[ "$cleanup_outcome" == retained_drift ]]; then
                finish_publication private_cleanup_retained "$pending_signal_status"
            fi
            finish_publication private_cleanup_sensitive "$pending_signal_status"
        fi
    fi
}
trap exit_cleanup EXIT
trap 'early_signal HUP' HUP
trap 'early_signal INT' INT
trap 'early_signal TERM' TERM
private=$(/usr/bin/mktemp -d "$local_parent/k3-registry-pull-v25.batch.${SLURM_JOB_ID}.XXXXXX" 2>/dev/null) \
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
if ! { exec {private_fd}<"$private"; } 2>/dev/null; then
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
local_scrubber=$private_anchor/scrub_private_tree.py
local_scrubber_export=$private/scrub_private_tree.py
readonly stdout stderr local_tools local_tools_export local_scrubber local_scrubber_export
/usr/bin/touch "$stdout" "$stderr" 2>/dev/null \
    || block private_environment
if ! { exec {stdout_fd}<>"$stdout"; } 2>/dev/null \
    || ! { exec {stderr_fd}<>"$stderr"; } 2>/dev/null; then
    block private_environment
fi
/usr/bin/chmod 600 "$stdout" "$stderr" 2>/dev/null \
    || block private_environment
/usr/bin/cp -- /proc/self/fd/5 "$local_tools" 2>/dev/null \
    || block private_environment
/usr/bin/chmod 600 "$local_tools" 2>/dev/null \
    || block private_environment
if ! { exec {local_tools_fd}<>"$local_tools"; } 2>/dev/null; then
    block private_environment
fi
/usr/bin/chmod 400 "$local_tools" 2>/dev/null \
    || block private_environment
/usr/bin/cp -- /proc/self/fd/3 "$local_scrubber" 2>/dev/null \
    || block private_environment
/usr/bin/chmod 600 "$local_scrubber" 2>/dev/null \
    || block private_environment
if ! { exec {local_scrubber_fd}<>"$local_scrubber"; } 2>/dev/null; then
    block private_environment
fi
/usr/bin/chmod 500 "$local_scrubber" 2>/dev/null \
    || block private_environment
stdout_identity=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$stdout" 2>/dev/null) \
    || block private_environment
stderr_identity=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$stderr" 2>/dev/null) \
    || block private_environment
local_tools_identity=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$local_tools" 2>/dev/null) \
    || block private_environment
local_scrubber_identity=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$local_scrubber" 2>/dev/null) \
    || block private_environment
[[ -f "$stdout" && ! -L "$stdout" && -f "$stderr" && ! -L "$stderr" \
    && -f "$local_tools" && ! -L "$local_tools" && -f "$local_scrubber" && ! -L "$local_scrubber" \
    && "$stdout_identity" == *':600:656177:1' \
    && "$stderr_identity" == *':600:656177:1' \
    && "$local_tools_identity" == *':400:656177:1' \
    && "$local_scrubber_identity" == *':500:656177:1' \
    && "$stdout_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$stdout_fd" 2>/dev/null)" \
    && "$stderr_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$stderr_fd" 2>/dev/null)" \
    && "$local_tools_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$local_tools_fd" 2>/dev/null)" \
    && "$local_scrubber_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$local_scrubber_fd" 2>/dev/null)" \
    && "$(/usr/bin/sha256sum -- "$local_tools" 2>/dev/null | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- "$local_scrubber" 2>/dev/null | /usr/bin/cut -d' ' -f1)" == "${GATE_SCRUBBER_SHA256:-}" ]] \
    || block private_environment
readonly stdout_stream=/proc/self/fd/${stdout_fd}
readonly stderr_stream=/proc/self/fd/${stderr_fd}
export GATE_LOCAL_TOOL_MANIFEST=$local_tools_export
export GATE_LOCAL_SCRUBBER=$local_scrubber_export

stop_child() {
    local child_term_deadline child_kill_deadline
    case "${writer_state:-absent}" in
        absent|quiesced) return 0 ;;
        unproven) return 1 ;;
        spawning)
            if [[ ! "${active_pid:-}" =~ ^[0-9]+$ || ! "${active_group_id:-}" =~ ^[0-9]+$ ]]; then
                mark_live_writer_cleanup_unproven
                return 1
            fi
            ;;
        live|pid_reaped) ;;
        *) mark_live_writer_cleanup_unproven; return 1 ;;
    esac
    arm_teardown_deadline
    child_term_deadline=$((teardown_deadline - 50))
    child_kill_deadline=$((teardown_deadline - 45))
    if active_writer_live; then
        signal_writer TERM
        # The guarded probe fallback is bounded at 125 seconds. Preserve fifty
        # seconds of this one 210-second teardown for outer cleanup/publication.
        while (( SECONDS < child_term_deadline )); do
            if ! active_writer_live; then
                break
            fi
            /usr/bin/sleep 0.1
        done
        if active_writer_live; then
            signal_writer KILL
            while (( SECONDS < child_kill_deadline )); do
                if ! active_writer_live; then
                    break
                fi
                /usr/bin/sleep 0.1
            done
        fi
    fi
    if active_writer_live; then
        mark_live_writer_cleanup_unproven
        return 1
    fi
    if [[ "${active_pid:-}" =~ ^[0-9]+$ ]]; then
        wait "$active_pid" 2>/dev/null || true
        active_pid=
    fi
    mark_writer_quiesced
}

finish_reaped_writer() {
    active_pid=
    [[ "${writer_state:-absent}" != unproven ]] || return 1
    writer_state=pid_reaped
    if writer_group_live; then
        stop_child
    else
        mark_writer_quiesced
    fi
}

handle_signal() {
    local name=$1
    remember_signal "$name"
    # TERM@240 is one total teardown budget.  Arm it before checking any
    # lifecycle flag so a signal with no active child cannot start a later,
    # fresh cleanup or publication window.
    arm_teardown_deadline
    if (( publication_started && publication_in_progress )); then
        :
    elif (( publication_started )); then
        exit "$pending_signal_status"
    elif (( spawning || cleanup_running || cleanup_in_progress || cleanup_exit_running || signal_handling )); then
        :
    else
        signal_handling=1
        if ! stop_child; then
            finish_publication live_writer_cleanup_unproven "$pending_signal_status"
        fi
        if cleanup_private_tree; then
            finish_publication interrupted "$pending_signal_status"
        else
            if [[ "$cleanup_outcome" == retained_drift ]]; then
                finish_publication private_cleanup_retained "$pending_signal_status"
            fi
            finish_publication private_cleanup_sensitive "$pending_signal_status"
        fi
    fi
}

trap exit_cleanup EXIT
trap 'handle_signal HUP' HUP
trap 'handle_signal INT' INT
trap 'handle_signal TERM' TERM

set +e
spawning=1
writer_state=spawning
(
    exec </proc/self/fd/6 >&"$stdout_fd" 2>&"$stderr_fd"
    exec {private_fd}<&- {stdout_fd}<&- {stderr_fd}<&- {local_tools_fd}<&- {local_scrubber_fd}<&-
    exec 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&-
    exec /usr/bin/setsid /usr/bin/timeout --signal=TERM --kill-after=150s 1560s \
        /usr/bin/srun -M fair-cw-use2-3 --overlap --nodes=1 --ntasks=1 -w "$node" \
        --gpus-per-node=1 --cpus-per-task=4 --cpu-bind=none --export=ALL \
        /usr/bin/bash -p -s
) &
active_pid=$!
active_group_id=$active_pid
writer_state=live
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
        finish_publication live_writer_cleanup_unproven 1
    fi
else
    wait "$active_pid"
    rc=$?
    if ! finish_reaped_writer; then
        finish_publication live_writer_cleanup_unproven 1
    fi
fi
arm_teardown_deadline
set -e

success='{"category":"success","image_digest":"sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20","kind":"k3-registry-pull-gate-v25","platform":"linux/arm64","state":"complete"}'
cleanup_proof_count=$(/usr/bin/grep -Fxc 'gate_cleanup=retained_empty' "$stderr_stream" 2>/dev/null || true)
if (( rc == 0 )) && [[ "$(/usr/bin/stat -Lc '%s' "$stdout_stream")" -eq $((${#success} + 1)) \
    && "$(<"$stdout_stream")" == "$success" \
    && "$cleanup_proof_count" == 1 ]] \
    && ! /usr/bin/grep -q '^gate_category=' "$stderr_stream" 2>/dev/null; then
    if ! cleanup_private_tree; then
        if [[ "$cleanup_outcome" == retained_drift ]]; then
            finish_publication private_cleanup_retained 1
        fi
        finish_publication private_cleanup_sensitive 1
    fi
    finish_publication success 0
fi
unset cleanup_proof_count

if classify_registry_error_file "$stderr_stream" "$rc" "$stderr_identity"; then
    category=$REGISTRY_SAFE_CATEGORY
else
    category=internal
fi
if cleanup_private_tree; then
    :
else
    if [[ "$cleanup_outcome" == retained_drift ]]; then
        category=private_cleanup_retained
    else
        category=private_cleanup_sensitive
    fi
fi
finish_publication "$category" 1
