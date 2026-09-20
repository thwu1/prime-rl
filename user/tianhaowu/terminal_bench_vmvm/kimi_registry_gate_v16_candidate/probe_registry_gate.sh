#!/usr/bin/bash -p
set +x
set -euo pipefail
shopt -u varredir_close
umask 077

blocked() {
    /usr/bin/printf 'gate_category=%s\n' "$1" >&2
    exit 2
}

[[ $# == 0 ]] || blocked allocation_identity
[[ "$-" != *x* ]] || blocked private_environment
[[ "${SLURM_CLUSTER_NAME:-}" == fair-cw-use2-3 \
    && "${SLURM_JOB_NAME:-}" == "${GATE_JOB_NAME:-}" \
    && "${SLURM_JOB_PARTITION:-}" == g3 \
    && "${SLURM_JOB_ACCOUNT:-}" == ram \
    && "${SLURM_JOB_NUM_NODES:-}" == 1 \
    && "${SLURM_NTASKS:-}" == 1 \
    && "${SLURM_CPUS_PER_TASK:-}" == 4 \
    && "${SLURM_GPUS_ON_NODE:-}" == 1 \
    && "${SLURM_RESTART_COUNT:-0}" == 0 \
    && "${SLURM_STEP_ID:-}" =~ ^[0-9]+$ \
    && "${SLURM_STEP_NUM_NODES:-}" == 1 \
    && "${SLURM_STEP_NUM_TASKS:-}" == 1 ]] \
    || blocked allocation_identity

readonly worker="${GATE_SOURCE_ROOT}/vllm_tools/serve_api_v2/src/serve_api_v2/worker/worker_vllm.sh"
readonly aws_creds="${GATE_SOURCE_ROOT}/vllm_tools/serve_api_v2/src/serve_api_v2/worker/aws_creds.sh"
readonly expected_source_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/ram-common-b1f0aa6
readonly expected_image=588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/vllm-openai:kimi-k3-kda-logprobs-fix-v2-20260916@sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20
readonly tools_manifest=${GATE_LOCAL_TOOL_MANIFEST:-}
readonly scrubber=${GATE_LOCAL_SCRUBBER:-}
[[ "${GATE_SOURCE_ROOT:-}" == "$expected_source_root" \
    && "${GATE_SOURCE_REVISION:-}" == b1f0aa6c1aabcad9182d85a694faaa2eaa3d0f6e \
    && "${GATE_SOURCE_TREE:-}" == b205ec0f4e2f03f3b3cf5c9e7df7035a49df6772 \
    && "${GATE_IMAGE:-}" == "$expected_image" \
    && "${GATE_IMAGE_DIGEST:-}" == sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20 \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$worker")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$aws_creds")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/sha256sum -- "$worker" | /usr/bin/cut -d' ' -f1)" == "${GATE_WORKER_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- "$aws_creds" | /usr/bin/cut -d' ' -f1)" == "${GATE_AWS_CREDS_SHA256:-}" \
    && ( "$tools_manifest" == /var/slurm-tmp/k3-registry-pull-v16.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /var/slurm-tmp/*/k3-registry-pull-v16.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /tmp/k3-registry-pull-v16.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /tmp/*/k3-registry-pull-v16.batch.*.*/compute_tools.sha256 ) \
    && "$tools_manifest" != /proc/self/fd/* \
    && "$tools_manifest" == "$(/usr/bin/readlink -f -- "$tools_manifest" 2>/dev/null)" \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$tools_manifest")" == 'regular file:400:656177:1' \
    && "$(/usr/bin/sha256sum -- "$tools_manifest" | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" \
    && ( "$scrubber" == /var/slurm-tmp/k3-registry-pull-v16.batch.*.*/scrub_private_tree.py \
        || "$scrubber" == /var/slurm-tmp/*/k3-registry-pull-v16.batch.*.*/scrub_private_tree.py \
        || "$scrubber" == /tmp/k3-registry-pull-v16.batch.*.*/scrub_private_tree.py \
        || "$scrubber" == /tmp/*/k3-registry-pull-v16.batch.*.*/scrub_private_tree.py ) \
    && "$scrubber" != /proc/self/fd/* \
    && "$scrubber" == "$(/usr/bin/readlink -f -- "$scrubber" 2>/dev/null)" \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$scrubber")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/sha256sum -- "$scrubber" | /usr/bin/cut -d' ' -f1)" == "${GATE_SCRUBBER_SHA256:-}" ]] \
    || blocked source_identity
worker_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$worker") || blocked source_identity
aws_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$aws_creds") || blocked source_identity
tools_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest") || blocked source_identity
scrubber_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$scrubber") || blocked source_identity
scrubber_fd=-1
if ! exec 9<"$worker" 8<"$aws_creds" 7<"$tools_manifest" {scrubber_fd}<"$scrubber" 2>/dev/null; then
    blocked source_identity
fi
[[ "$worker_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/9)" \
    && "$worker_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$worker")" \
    && "$aws_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/8)" \
    && "$aws_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$aws_creds")" \
    && "$tools_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/7)" \
    && "$tools_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest")" \
    && "$scrubber_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "/proc/self/fd/$scrubber_fd")" \
    && "$scrubber_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$scrubber")" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/9 | /usr/bin/cut -d' ' -f1)" == "${GATE_WORKER_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/8 | /usr/bin/cut -d' ' -f1)" == "${GATE_AWS_CREDS_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/7 | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- "/proc/self/fd/$scrubber_fd" | /usr/bin/cut -d' ' -f1)" == "${GATE_SCRUBBER_SHA256:-}" ]] \
    || blocked source_identity
/usr/bin/sha256sum -c --strict /proc/self/fd/7 >/dev/null 2>&1 || blocked source_identity
[[ "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- /usr/bin/podman)" == 'regular file:755:0:1' \
    && "$(/usr/bin/sha256sum -- /usr/bin/podman | /usr/bin/cut -d' ' -f1)" == f93ee492920150e229b9b41729bfe675073a4df0569ee5d570a8106b5a64506a \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- /usr/bin/ucloud)" == 'regular file:755:0:1' \
    && "$(/usr/bin/sha256sum -- /usr/bin/ucloud | /usr/bin/cut -d' ' -f1)" == aa634b8765d4c08aea0f2e514fdc3d07cc121555f79c0d6634258c952d5f8960 ]] \
    || blocked source_identity

tls_identity=
tls_source=
for tls_name in THRIFT_TLS_CL_CERT_PATH THRIFT_TLS_CL_KEY_PATH; do
    tls_path=${!tls_name:-}
    [[ "$tls_path" == /* && "$tls_path" == "$(/usr/bin/readlink -f -- "$tls_path")" \
        && "$(/usr/bin/stat -Lc '%F:%a:%u:%h:%s' -- "$tls_path")" == "regular file:500:${GATE_EXPECTED_UID}:1:${GATE_TLS_SIZE}" \
        && "$(/usr/bin/sha256sum -- "$tls_path" | /usr/bin/cut -d' ' -f1)" == "${GATE_TLS_SHA256:-}" ]] \
        || blocked source_identity
    this_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tls_path") \
        || blocked source_identity
    [[ -z "$tls_identity" || "$this_identity" == "$tls_identity" ]] \
        || blocked source_identity
    tls_identity=$this_identity
    tls_source=$tls_path
done
if ! exec 4<"$tls_source" 2>/dev/null; then
    blocked source_identity
fi
[[ "$tls_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/4)" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/4 | /usr/bin/cut -d' ' -f1)" == "${GATE_TLS_SHA256:-}" ]] \
    || blocked source_identity
unset tls_name tls_path this_identity tls_identity tls_source

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
unset http_proxy https_proxy all_proxy no_proxy
unset _CONTAINERS_USERNS_CONFIGURED _CONTAINERS_ROOTLESS_UID _CONTAINERS_ROOTLESS_GID
unset REGISTRY_AUTH_FILE DOCKER_CONFIG
unset CUDA_VISIBLE_DEVICES

readonly local_parent=${SLURM_TMPDIR:-/var/slurm-tmp}
[[ "$local_parent" == /var/slurm-tmp || "$local_parent" == /var/slurm-tmp/* \
    || "$local_parent" == /tmp || "$local_parent" == /tmp/* ]] \
    || blocked private_environment
[[ "$local_parent" != /proc/self/fd/* \
    && "$local_parent" == "$(/usr/bin/readlink -f -- "$local_parent" 2>/dev/null)" \
    && -d "$local_parent" && ! -L "$local_parent" ]] \
    || blocked private_environment
private_root=
private_root_before=
private_root_identity=
private_root_fd=-1
private_root_anchor=
private_root_anchor_trusted=0
graphroot_fd=-1
runroot_fd=-1
xdg_runtime_fd=-1
local_tls_fd=-1
graphroot_identity=
runroot_identity=
xdg_runtime_identity=
local_tls_identity=
local_tls_anchor=
local_tls_clean=0
cleanup_complete=0
cleanup_outcome=sensitive_residue
cleanup_root_drift=0
cleanup_running=0
cleanup_in_progress=0
cleanup_exit_running=0
cleanup_deadline=0
cleanup_retry_limit=3
pending_signal=
pending_signal_status=130

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

handle_signal() {
    remember_signal "$1"
    if (( cleanup_running || cleanup_in_progress || cleanup_exit_running )); then
        return
    fi
    exit "$pending_signal_status"
}

private_root_bound() {
    [[ "$private_root_anchor_trusted" == 1 \
        && "$private_root_fd" =~ ^[0-9]+$ && "$private_root_fd" -ge 10 \
        && -d "$private_root_anchor" && ! -L "$private_root_anchor" \
        && "$private_root_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$private_root_anchor" 2>/dev/null || true)" ]]
}

private_root_named_bound() {
    private_root_bound \
        && [[ -d "$private_root" && ! -L "$private_root" \
            && "$private_root_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private_root" 2>/dev/null || true)" ]]
}

scrub_retained_tls() {
    local after expected_base expected_dev_inode expected_uid named opened
    [[ -n "$local_tls_identity" ]] || return 0
    (( local_tls_clean == 0 )) || return 0
    [[ "$local_tls_fd" =~ ^[0-9]+$ && "$local_tls_fd" -ge 10 ]] || return 1
    expected_base=${local_tls_identity%:*}
    expected_dev_inode=${local_tls_identity%:*:*:*}
    expected_uid=${local_tls_identity%:*}
    expected_uid=${expected_uid##*:}
    opened=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$local_tls_fd" 2>/dev/null || true)
    [[ "$opened" == "$expected_base:0" || "$opened" == "$expected_base:1" \
        || "$opened" == "$expected_dev_inode:600:$expected_uid:0" \
        || "$opened" == "$expected_dev_inode:600:$expected_uid:1" ]] || return 1
    /usr/bin/chmod 600 -- "/proc/self/fd/$local_tls_fd" 2>/dev/null || return 1
    /usr/bin/truncate -s 0 -- "/proc/self/fd/$local_tls_fd" 2>/dev/null || return 1
    /usr/bin/sync -f "/proc/self/fd/$local_tls_fd" 2>/dev/null || return 1
    cleanup_checkpoint probe_after_tls_truncate
    after=$(/usr/bin/stat -Lc '%d:%i:%u:%h:%s' -- "/proc/self/fd/$local_tls_fd" 2>/dev/null || true)
    [[ "$after" == "$expected_dev_inode:$expected_uid:0:0" \
        || "$after" == "$expected_dev_inode:$expected_uid:1:0" ]] || return 1
    if [[ -e "$local_tls_anchor" || -L "$local_tls_anchor" ]]; then
        named=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$local_tls_anchor" 2>/dev/null || true)
        if [[ "$named" == "$expected_dev_inode:600:$expected_uid:1" ]]; then
            /usr/bin/unlink -- "$local_tls_anchor" 2>/dev/null || return 1
            after=$(/usr/bin/stat -Lc '%d:%i:%u:%h:%s' -- "/proc/self/fd/$local_tls_fd" 2>/dev/null || true)
            [[ "$after" == "$expected_dev_inode:$expected_uid:0:0" ]] || return 1
        else
            cleanup_root_drift=1
        fi
    else
        cleanup_root_drift=1
    fi
    if exec {local_tls_fd}<&-; then
        local_tls_fd=-1
        local_tls_clean=1
    else
        return 1
    fi
}

scrub_private_contents() {
    local child_name child_fd child_identity named exclusions= remaining root_dev timeout_seconds
    local -a scrub_specs=()
    private_root_bound || return 1
    scrub_retained_tls || return 1
    cleanup_checkpoint probe_after_tls
    if (( cleanup_root_drift )); then
        exclusions=tls-combined.pem
    fi
    for child_name in graphroot runroot xdg-runtime; do
        case "$child_name" in
            graphroot) child_fd=$graphroot_fd; child_identity=$graphroot_identity ;;
            runroot) child_fd=$runroot_fd; child_identity=$runroot_identity ;;
            xdg-runtime) child_fd=$xdg_runtime_fd; child_identity=$xdg_runtime_identity ;;
            *) return 1 ;;
        esac
        [[ -n "$child_identity" ]] || continue
        [[ "$child_fd" =~ ^[0-9]+$ && "$child_fd" -ge 10 \
            && "$child_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "/proc/self/fd/$child_fd" 2>/dev/null || true)" ]] \
            || return 1
        named=$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private_root_anchor/$child_name" 2>/dev/null || true)
        if [[ "$named" != "$child_identity" ]]; then
            cleanup_root_drift=1
            [[ -z "$exclusions" ]] || exclusions+=,
            exclusions+=$child_name
        fi
        scrub_specs+=("$child_fd:")
    done
    cleanup_checkpoint probe_before_fd_scrub
    remaining=$((cleanup_deadline - SECONDS))
    (( remaining > 0 )) || return 1
    timeout_seconds=$((remaining < 90 ? remaining : 90))
    root_dev=${private_root_identity%%:*}
    scrub_specs+=("$private_root_fd:$exclusions")
    /usr/bin/timeout --signal=TERM --kill-after=5s "${timeout_seconds}s" \
        /usr/bin/python3.12 -I -S -B "/proc/self/fd/$scrubber_fd" \
        "${GATE_EXPECTED_UID}" "$root_dev" "${scrub_specs[@]}" \
        >/dev/null 2>&1 \
        || return 1
    cleanup_checkpoint probe_after_fd_scrub
    [[ "$private_root_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$private_root_anchor" 2>/dev/null || true)" ]] \
        || return 1
}

remove_private_root() {
    local anchored_after= named_now= rc=0
    cleanup_checkpoint probe_before_in_progress
    cleanup_in_progress=1
    cleanup_checkpoint probe_in_progress
    scrub_private_contents || rc=1
    cleanup_checkpoint probe_after_scrub
    cleanup_checkpoint probe_before_named_stat
    if [[ -e "$private_root" || -L "$private_root" ]]; then
        named_now=$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private_root" 2>/dev/null || true)
        [[ "$named_now" == "$private_root_identity" ]] || cleanup_root_drift=1
    else
        cleanup_root_drift=1
    fi
    cleanup_checkpoint probe_after_named_stat
    if (( rc == 0 )); then
        cleanup_checkpoint probe_before_retained_root_proof
        anchored_after=$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$private_root_anchor" 2>/dev/null) || rc=1
        [[ "$anchored_after" == "$private_root_identity" ]] || rc=1
    fi
    cleanup_checkpoint probe_after_retained_root_proof
    if (( rc == 0 )); then
        cleanup_checkpoint probe_before_fd_close
        if [[ "$graphroot_fd" =~ ^[0-9]+$ && "$graphroot_fd" -ge 10 ]]; then
            exec {graphroot_fd}<&- && graphroot_fd=-1 || rc=1
        fi
        if [[ "$runroot_fd" =~ ^[0-9]+$ && "$runroot_fd" -ge 10 ]]; then
            exec {runroot_fd}<&- && runroot_fd=-1 || rc=1
        fi
        if [[ "$xdg_runtime_fd" =~ ^[0-9]+$ && "$xdg_runtime_fd" -ge 10 ]]; then
            exec {xdg_runtime_fd}<&- && xdg_runtime_fd=-1 || rc=1
        fi
        if [[ "$private_root_fd" =~ ^[0-9]+$ && "$private_root_fd" -ge 10 ]]; then
            exec {private_root_fd}<&- && private_root_fd=-1 || rc=1
        fi
    fi
    cleanup_checkpoint probe_after_fd_close
    if (( rc == 0 )); then
        cleanup_checkpoint probe_before_complete
        cleanup_complete=1
        if (( cleanup_root_drift )); then
            cleanup_outcome=retained_drift
        else
            cleanup_outcome=retained_empty
        fi
    fi
    cleanup_checkpoint probe_after_complete
    cleanup_checkpoint probe_before_in_progress_clear
    cleanup_in_progress=0
    cleanup_checkpoint probe_after_in_progress
    (( rc == 0 && cleanup_complete == 1 ))
}

cleanup_private_tree() {
    local attempt=0 rc=1
    if (( cleanup_complete )); then
        [[ "$cleanup_outcome" == retained_empty ]]
        return
    fi
    cleanup_checkpoint probe_before_cleanup_running
    cleanup_running=1
    cleanup_checkpoint probe_cleanup_running
    if ! [[ "$private_root_fd" =~ ^[0-9]+$ && "$private_root_fd" -ge 10 ]]; then
        if [[ -z "$private_root" ]]; then
            cleanup_complete=1
            cleanup_outcome=retained_empty
            rc=0
        fi
    else
        if (( cleanup_deadline == 0 )); then
            cleanup_deadline=$((SECONDS + 90))
        fi
        while (( cleanup_complete == 0 && attempt < cleanup_retry_limit && SECONDS < cleanup_deadline )); do
            cleanup_checkpoint probe_before_attempt
            attempt=$((attempt + 1))
            if remove_private_root; then
                cleanup_checkpoint probe_after_attempt
                break
            fi
            cleanup_checkpoint probe_after_attempt
        done
        if (( cleanup_complete == 1 )) && [[ "$cleanup_outcome" == retained_empty ]]; then
            rc=0
        fi
    fi
    cleanup_checkpoint probe_before_cleanup_running_clear
    cleanup_running=0
    cleanup_checkpoint probe_after_cleanup_running
    (( rc == 0 ))
}

exit_cleanup() {
    local saved=$? cleanup_failed=0
    trap - EXIT
    cleanup_exit_running=1
    unset REGISTRY_AUTH_FILE DOCKER_CONFIG
    if ! cleanup_private_tree >/dev/null 2>&1; then
        cleanup_failed=1
        (( saved != 0 )) || saved=3
    fi
    if (( cleanup_failed )); then
        if [[ "$cleanup_outcome" == retained_drift ]]; then
            /usr/bin/printf 'gate_category=private_cleanup_retained\n' >&2
        else
            /usr/bin/printf 'gate_category=private_cleanup_sensitive\n' >&2
        fi
    fi
    if [[ "$private_root_fd" =~ ^[0-9]+$ && "$private_root_fd" -ge 10 ]]; then
        exec {private_root_fd}<&- || true
    fi
    if [[ "$graphroot_fd" =~ ^[0-9]+$ && "$graphroot_fd" -ge 10 ]]; then
        exec {graphroot_fd}<&- || true
    fi
    if [[ "$runroot_fd" =~ ^[0-9]+$ && "$runroot_fd" -ge 10 ]]; then
        exec {runroot_fd}<&- || true
    fi
    if [[ "$xdg_runtime_fd" =~ ^[0-9]+$ && "$xdg_runtime_fd" -ge 10 ]]; then
        exec {xdg_runtime_fd}<&- || true
    fi
    if [[ "$local_tls_fd" =~ ^[0-9]+$ && "$local_tls_fd" -ge 10 ]]; then
        exec {local_tls_fd}<&- || true
    fi
    if [[ "$scrubber_fd" =~ ^[0-9]+$ && "$scrubber_fd" -ge 10 ]]; then
        exec {scrubber_fd}<&- || true
    fi
    if [[ -n "$pending_signal" ]]; then
        saved=$pending_signal_status
    fi
    exit "$saved"
}
trap exit_cleanup EXIT
trap 'handle_signal HUP' HUP
trap 'handle_signal INT' INT
trap 'handle_signal TERM' TERM
private_root=$(/usr/bin/mktemp -d "$local_parent/k3-registry-pull-v16.${SLURM_JOB_ID}.${SLURM_STEP_ID}.XXXXXX") \
    || blocked private_environment
[[ "$private_root" == "$local_parent"/k3-registry-pull-v16."${SLURM_JOB_ID}"."${SLURM_STEP_ID}".* \
    && -d "$private_root" && ! -L "$private_root" ]] \
    || blocked private_environment
private_root_before=$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private_root" 2>/dev/null) \
    || blocked private_environment
[[ "$private_root_before" == *":700:${GATE_EXPECTED_UID}" \
    && "$(/usr/bin/stat -c '%h' -- "$private_root" 2>/dev/null)" == 2 ]] \
    || blocked private_environment
if ! exec {private_root_fd}<"$private_root" 2>/dev/null; then
    blocked private_environment
fi
private_root_anchor=/proc/self/fd/${private_root_fd}/.
private_root_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$private_root_anchor" 2>/dev/null) \
    || blocked private_environment
[[ "$private_root_before" == "$private_root_identity" \
    && "$private_root_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private_root" 2>/dev/null)" \
    && -d "$private_root_anchor" && ! -L "$private_root_anchor" ]] \
    || blocked private_environment
readonly private_root private_root_identity private_root_anchor
initial_entry=$(/usr/bin/find "$private_root_anchor" -xdev -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null) \
    || blocked private_environment
[[ -z "$initial_entry" ]] || blocked private_environment
unset initial_entry
private_root_anchor_trusted=1
readonly graphroot=$private_root/graphroot
readonly runroot=$private_root/runroot
readonly xdg_runtime=$private_root/xdg-runtime
readonly xdg_config=$private_root/xdg-config
readonly private_home=$private_root/home
readonly storage_conf=$private_root/storage.conf
readonly inspect_file=$private_root/inspect
readonly local_tls=$private_root/tls-combined.pem
local_tls_anchor=$private_root_anchor/tls-combined.pem
readonly local_tls_anchor
/usr/bin/mkdir -m 700 -- "$graphroot" "$runroot" "$xdg_runtime" "$xdg_config" "$private_home" \
    || blocked private_environment
if ! exec {graphroot_fd}<"$graphroot" 2>/dev/null \
    || ! exec {runroot_fd}<"$runroot" 2>/dev/null \
    || ! exec {xdg_runtime_fd}<"$xdg_runtime" 2>/dev/null; then
    blocked private_environment
fi
graphroot_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "/proc/self/fd/$graphroot_fd" 2>/dev/null) \
    || blocked private_environment
runroot_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "/proc/self/fd/$runroot_fd" 2>/dev/null) \
    || blocked private_environment
xdg_runtime_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "/proc/self/fd/$xdg_runtime_fd" 2>/dev/null) \
    || blocked private_environment
[[ "$graphroot_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$graphroot" 2>/dev/null)" \
    && "$runroot_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$runroot" 2>/dev/null)" \
    && "$xdg_runtime_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$xdg_runtime" 2>/dev/null)" ]] \
    || blocked private_environment
/usr/bin/printf '[storage]\ndriver = "overlay"\ngraphroot = "%s"\nrunroot = "%s"\n' \
    "$graphroot" "$runroot" > "$storage_conf" \
    || blocked private_environment
/usr/bin/chmod 600 "$storage_conf" || blocked private_environment
/usr/bin/cp -- /proc/self/fd/4 "$local_tls" 2>/dev/null || blocked private_environment
if ! exec {local_tls_fd}<>"$local_tls" 2>/dev/null; then
    blocked private_environment
fi
/usr/bin/chmod 500 "$local_tls" 2>/dev/null || blocked private_environment
local_tls_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$local_tls_fd" 2>/dev/null) \
    || blocked private_environment
[[ "$(/usr/bin/stat -c '%a:%u:%h' -- "$storage_conf")" == "600:${GATE_EXPECTED_UID}:1" ]] \
    || blocked private_environment
[[ "$local_tls" == "$(/usr/bin/readlink -f -- "$local_tls" 2>/dev/null)" \
    && -f "$local_tls" && ! -L "$local_tls" \
    && "$(/usr/bin/stat -c '%a:%u:%h:%s' -- "$local_tls")" == "500:${GATE_EXPECTED_UID}:1:${GATE_TLS_SIZE}" \
    && "$local_tls_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$local_tls" 2>/dev/null)" \
    && "$(/usr/bin/sha256sum -- "$local_tls" | /usr/bin/cut -d' ' -f1)" == "${GATE_TLS_SHA256:-}" ]] \
    || blocked private_environment
exec 4<&-

export HOME=$private_home
export XDG_RUNTIME_DIR=$xdg_runtime
export XDG_CONFIG_HOME=$xdg_config
export XDG_DATA_HOME=$private_root/xdg-data
export CONTAINERS_STORAGE_CONF=$storage_conf
export TMPDIR=$private_root
export THRIFT_TLS_CL_CERT_PATH=$local_tls
export THRIFT_TLS_CL_KEY_PATH=$local_tls
/usr/bin/mkdir -m 700 -- "$XDG_DATA_HOME" || blocked private_environment
for private_path in "$private_root" "$graphroot" "$runroot" "$xdg_runtime" \
    "$xdg_config" "$XDG_DATA_HOME" "$private_home"; do
    [[ "$private_path" != /proc/self/fd/* \
        && ( "$private_path" == "$private_root" || "$private_path" == "$private_root"/* ) ]] \
        || blocked private_environment
    [[ "$private_path" == "$(/usr/bin/readlink -f -- "$private_path" 2>/dev/null)" \
        && -d "$private_path" && ! -L "$private_path" \
        && "$(/usr/bin/stat -c '%a:%u' -- "$private_path")" == "700:${GATE_EXPECTED_UID}" ]] \
        || blocked private_environment
done
unset private_path
private_root_named_bound || blocked private_environment

private_root_named_bound || blocked private_environment
store=$(/usr/bin/podman info --format '{{.Store.GraphRoot}}|{{.Store.RunRoot}}|{{.Store.GraphDriverName}}' 2>/dev/null) \
    || blocked podman_info
[[ "$store" == "$graphroot|$runroot|overlay" ]] || blocked podman_info
unset store
set +e
/usr/bin/podman image exists "$GATE_IMAGE" >/dev/null 2>&1
cold_exists_rc=$?
set -e
if (( cold_exists_rc != 1 )); then
    blocked podman_info
fi
unset cold_exists_rc
private_root_named_bound || blocked private_environment

# Source only the reviewed registry functions in a child shell. Its hardened
# registry trap therefore cannot replace this probe's job-local cleanup trap.
# No worker main, model path, GPU enumeration, container construction, or
# podman run entry point is invoked.
private_root_named_bound || blocked private_environment
(
    source /proc/self/fd/8 || blocked source_identity
    source /proc/self/fd/9 || blocked source_identity
    exec 7<&- 8<&- 9<&-
    exec {scrubber_fd}<&- {private_root_fd}<&- {graphroot_fd}<&- {runroot_fd}<&- {xdg_runtime_fd}<&- {local_tls_fd}<&-
    _container_registry_arm_cleanup
    _container_registry_login "$GATE_IMAGE"
    auth_path=${_CONTAINER_REGISTRY_AUTH_PATH:-}
    [[ "$auth_path" == "$xdg_runtime"/serve-api-v2-registry-auth.* \
        && "$(/usr/bin/stat -c '%a:%u:%h' -- "$auth_path")" == "600:${GATE_EXPECTED_UID}:1" ]] \
        || blocked registry_login
    _container_registry_pull "$GATE_IMAGE"
    _container_registry_disarm_cleanup
    [[ ! -e "$auth_path" && ! -L "$auth_path" && -z "${REGISTRY_AUTH_FILE+x}" ]] \
        || blocked private_cleanup
)
private_root_named_bound || blocked private_cleanup
if ! leftover_auth=$(/usr/bin/find "$xdg_runtime" -xdev -name 'serve-api-v2-registry-auth.*' -print -quit); then
    blocked private_cleanup
fi
if [[ -n "$leftover_auth" ]]; then
    blocked private_cleanup
fi
unset leftover_auth

/usr/bin/podman image inspect \
    --format '{{.Digest}}|{{.Os}}|{{.Architecture}}|{{join .RepoDigests ","}}' \
    "$GATE_IMAGE" > "$inspect_file" 2>/dev/null \
    || blocked image_identity
private_root_named_bound || blocked private_cleanup
/usr/bin/chmod 600 "$inspect_file" || blocked private_environment
IFS='|' read -r observed_digest observed_os observed_arch observed_repodigests < "$inspect_file" \
    || blocked image_identity
[[ "$observed_digest" == "$GATE_IMAGE_DIGEST" \
    && "$observed_os" == linux && "$observed_arch" == arm64 \
    && ",$observed_repodigests," == *,*"@${GATE_IMAGE_DIGEST}"*,* ]] \
    || blocked image_identity
: > "$inspect_file"
/usr/bin/unlink -- "$inspect_file" || blocked private_cleanup
unset observed_digest observed_os observed_arch observed_repodigests

store=$(/usr/bin/podman info --format '{{.Store.GraphRoot}}|{{.Store.RunRoot}}' 2>/dev/null) \
    || blocked private_cleanup
[[ "$store" == "$graphroot|$runroot" ]] || blocked private_cleanup
/usr/bin/podman image rm --force "$GATE_IMAGE" >/dev/null 2>&1 \
    || blocked private_cleanup
set +e
/usr/bin/podman image exists "$GATE_IMAGE" >/dev/null 2>&1
image_exists_rc=$?
set -e
if (( image_exists_rc == 0 )); then
    blocked private_cleanup
elif (( image_exists_rc != 1 )); then
    blocked private_cleanup
fi
unset store image_exists_rc
private_root_named_bound || blocked private_cleanup

if ! cleanup_private_tree; then
    if [[ "$cleanup_outcome" == retained_drift ]]; then
        blocked private_cleanup_retained
    fi
    blocked private_cleanup_sensitive
fi
if [[ -n "$pending_signal" ]]; then
    exit "$pending_signal_status"
fi
trap - EXIT HUP INT TERM
/usr/bin/printf '{"category":"success","image_digest":"%s","kind":"k3-registry-pull-gate-v16","platform":"linux/arm64","state":"complete"}\n' \
    "$GATE_IMAGE_DIGEST"
