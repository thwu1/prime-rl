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
readonly podman_guard="${GATE_BUNDLE}/podman_guard.sh"
readonly scrubber=${GATE_LOCAL_SCRUBBER:-}
readonly expected_source_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/ram-common-b1f0aa6
readonly expected_image=588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/vllm-openai:kimi-k3-kda-logprobs-fix-v2-20260916@sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20
readonly tools_manifest=${GATE_LOCAL_TOOL_MANIFEST:-}
[[ "${GATE_SOURCE_ROOT:-}" == "$expected_source_root" \
    && "${GATE_SOURCE_REVISION:-}" == b1f0aa6c1aabcad9182d85a694faaa2eaa3d0f6e \
    && "${GATE_SOURCE_TREE:-}" == b205ec0f4e2f03f3b3cf5c9e7df7035a49df6772 \
    && "${GATE_IMAGE:-}" == "$expected_image" \
    && "${GATE_IMAGE_DIGEST:-}" == sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20 \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$worker")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$aws_creds")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/sha256sum -- "$worker" | /usr/bin/cut -d' ' -f1)" == "${GATE_WORKER_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- "$aws_creds" | /usr/bin/cut -d' ' -f1)" == "${GATE_AWS_CREDS_SHA256:-}" \
    && ( "$tools_manifest" == /var/slurm-tmp/k3-registry-pull-v23.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /var/slurm-tmp/*/k3-registry-pull-v23.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /tmp/k3-registry-pull-v23.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /tmp/*/k3-registry-pull-v23.batch.*.*/compute_tools.sha256 ) \
    && "$tools_manifest" != /proc/self/fd/* \
    && "$tools_manifest" == "$(/usr/bin/readlink -f -- "$tools_manifest" 2>/dev/null)" \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$tools_manifest")" == 'regular file:400:656177:1' \
    && "$(/usr/bin/sha256sum -- "$tools_manifest" | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" \
    && "$podman_guard" == /checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t134500z_v23/podman_guard.sh \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$podman_guard")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/sha256sum -- "$podman_guard" | /usr/bin/cut -d' ' -f1)" == "${GATE_PODMAN_GUARD_SHA256:-}" \
    && ( "$scrubber" == /var/slurm-tmp/k3-registry-pull-v23.batch.*.*/scrub_private_tree.py \
        || "$scrubber" == /var/slurm-tmp/*/k3-registry-pull-v23.batch.*.*/scrub_private_tree.py \
        || "$scrubber" == /tmp/k3-registry-pull-v23.batch.*.*/scrub_private_tree.py \
        || "$scrubber" == /tmp/*/k3-registry-pull-v23.batch.*.*/scrub_private_tree.py ) \
    && "$scrubber" != /proc/self/fd/* \
    && "$scrubber" == "$(/usr/bin/readlink -f -- "$scrubber" 2>/dev/null)" \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$scrubber")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/sha256sum -- "$scrubber" | /usr/bin/cut -d' ' -f1)" == "${GATE_SCRUBBER_SHA256:-}" ]] \
    || blocked probe_source_identity
worker_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$worker") || blocked probe_source_identity
aws_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$aws_creds") || blocked probe_source_identity
tools_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest") || blocked probe_source_identity
guard_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$podman_guard") || blocked probe_source_identity
scrubber_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$scrubber") || blocked probe_source_identity
podman_guard_fd=-1
scrubber_fd=-1
if ! exec 9<"$worker" 8<"$aws_creds" 7<"$tools_manifest" \
    {podman_guard_fd}<"$podman_guard" {scrubber_fd}<"$scrubber" 2>/dev/null; then
    blocked probe_source_identity
fi
[[ "$worker_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/9)" \
    && "$worker_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$worker")" \
    && "$aws_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/8)" \
    && "$aws_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$aws_creds")" \
    && "$tools_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/7)" \
    && "$tools_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest")" \
    && "$guard_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "/proc/self/fd/$podman_guard_fd")" \
    && "$guard_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$podman_guard")" \
    && "$scrubber_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "/proc/self/fd/$scrubber_fd")" \
    && "$scrubber_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$scrubber")" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/9 | /usr/bin/cut -d' ' -f1)" == "${GATE_WORKER_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/8 | /usr/bin/cut -d' ' -f1)" == "${GATE_AWS_CREDS_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/7 | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- "/proc/self/fd/$podman_guard_fd" | /usr/bin/cut -d' ' -f1)" == "${GATE_PODMAN_GUARD_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- "/proc/self/fd/$scrubber_fd" | /usr/bin/cut -d' ' -f1)" == "${GATE_SCRUBBER_SHA256:-}" ]] \
    || blocked probe_source_identity
/usr/bin/sha256sum -c --strict /proc/self/fd/7 >/dev/null 2>&1 || blocked probe_source_identity
[[ "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- /usr/bin/podman)" == 'regular file:755:0:1' \
    && "$(/usr/bin/sha256sum -- /usr/bin/podman | /usr/bin/cut -d' ' -f1)" == f93ee492920150e229b9b41729bfe675073a4df0569ee5d570a8106b5a64506a \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- /usr/bin/ucloud)" == 'regular file:755:0:1' \
    && "$(/usr/bin/sha256sum -- /usr/bin/ucloud | /usr/bin/cut -d' ' -f1)" == aa634b8765d4c08aea0f2e514fdc3d07cc121555f79c0d6634258c952d5f8960 ]] \
    || blocked probe_source_identity

tls_identity=
tls_source=
for tls_name in THRIFT_TLS_CL_CERT_PATH THRIFT_TLS_CL_KEY_PATH; do
    tls_path=${!tls_name:-}
    [[ "$tls_path" == /* && "$tls_path" == "$(/usr/bin/readlink -f -- "$tls_path")" \
        && "$(/usr/bin/stat -Lc '%F:%a:%u:%h:%s' -- "$tls_path")" == "regular file:500:${GATE_EXPECTED_UID}:1:${GATE_TLS_SIZE}" \
        && "$(/usr/bin/sha256sum -- "$tls_path" | /usr/bin/cut -d' ' -f1)" == "${GATE_TLS_SHA256:-}" ]] \
        || blocked probe_source_identity
    this_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tls_path") \
        || blocked probe_source_identity
    [[ -z "$tls_identity" || "$this_identity" == "$tls_identity" ]] \
        || blocked probe_source_identity
    tls_identity=$this_identity
    tls_source=$tls_path
done
if ! exec 4<"$tls_source" 2>/dev/null; then
    blocked probe_source_identity
fi
[[ "$tls_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/4)" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/4 | /usr/bin/cut -d' ' -f1)" == "${GATE_TLS_SHA256:-}" ]] \
    || blocked probe_source_identity
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
private_dir_paths=()
private_dir_fds=()
private_dir_anchors=()
private_dir_identities=()
private_dir_manifests=()
storage_conf_fd=-1
storage_conf_identity=
storage_conf_clean=0
local_tls_fd=-1
local_tls_identity=
local_tls_clean=0
inspect_fd=-1
inspect_identity=
inspect_clean=0
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
private_runtime_armed=0
podman_guard_alias=
podman_guard_alias_anchor=
podman_guard_alias_identity=
podman_guard_alias_clean=0

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
        :
    else
        exit "$pending_signal_status"
    fi
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

private_dirs_bound() {
    local index path fd anchor identity
    private_root_named_bound || return 1
    ((${#private_dir_paths[@]} == 7 \
        && ${#private_dir_fds[@]} == 7 \
        && ${#private_dir_anchors[@]} == 7 \
        && ${#private_dir_identities[@]} == 7)) || return 1
    for index in "${!private_dir_paths[@]}"; do
        path=${private_dir_paths[$index]}
        fd=${private_dir_fds[$index]}
        anchor=${private_dir_anchors[$index]}
        identity=${private_dir_identities[$index]}
        [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 \
            && -d "$anchor" && ! -L "$anchor" \
            && "$identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$anchor" 2>/dev/null || true)" \
            && -d "$path" && ! -L "$path" \
            && "$identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$path" 2>/dev/null || true)" ]] \
            || return 1
    done
}

retained_private_dirs_bound() {
    local index fd anchor identity
    ((${#private_dir_fds[@]} == 7 \
        && ${#private_dir_anchors[@]} == 7 \
        && ${#private_dir_identities[@]} == 7)) || return 1
    for index in "${!private_dir_fds[@]}"; do
        fd=${private_dir_fds[$index]}
        anchor=${private_dir_anchors[$index]}
        identity=${private_dir_identities[$index]}
        [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 \
            && -d "$anchor" && ! -L "$anchor" \
            && "$identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$anchor" 2>/dev/null || true)" ]] \
            || return 1
    done
}

mount_free_anchored_tree() {
    local anchor=$1 resolved mountpoint
    resolved=$(/usr/bin/readlink -f -- "$anchor" 2>/dev/null) || return 1
    [[ "$resolved" == /* ]] || return 1
    # mountinfo identifies bind mounts even when they share st_dev with the
    # parent. Generated roots contain no mountinfo escape characters.
    while IFS=' ' read -r _ _ _ _ mountpoint _; do
        case "$mountpoint" in
            "$resolved"|"$resolved"/*) return 1 ;;
        esac
    done < /proc/self/mountinfo
}

preflight_anchored_directory() {
    local anchor=$1 identity=$2 records dev inode uid kind links path root_dev manifest
    [[ -d "$anchor" && ! -L "$anchor" \
        && "$identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$anchor" 2>/dev/null || true)" ]] \
        || return 1
    mount_free_anchored_tree "$anchor" || return 1
    root_dev=${identity%%:*}
    records=$(/usr/bin/timeout --signal=TERM --kill-after=3s 12s \
        /usr/bin/find "$anchor" -xdev -mindepth 1 -printf '%D:%i:%U:%y:%n:%p\n' 2>/dev/null) \
        || return 1
    while IFS=: read -r dev inode uid kind links path; do
        [[ -z "$dev" ]] && continue
        [[ "$dev" == "$root_dev" && "$inode" =~ ^[0-9]+$ \
            && "$uid" == "${GATE_EXPECTED_UID}" && -n "$path" ]] || return 1
        case "$kind" in
            d) ;;
            f) [[ "$links" == 1 ]] || return 1 ;;
            l)
                [[ "$links" == 1 && -n "${podman_guard_alias_anchor:-}" \
                    && "$path" == "$podman_guard_alias_anchor" \
                    && "$dev:$inode:$uid:$links" == "$podman_guard_alias_identity" \
                    && "$(/usr/bin/readlink -- "$path" 2>/dev/null || true)" == "/proc/self/fd/$podman_guard_fd" ]] \
                    || return 1
                ;;
            *) return 1 ;;
        esac
    done <<< "$records"
    manifest=$(/usr/bin/printf '%s' "$records" | /usr/bin/sha256sum | /usr/bin/cut -d' ' -f1) \
        || return 1
    [[ "$manifest" =~ ^[0-9a-f]{64}$ ]] || return 1
    /usr/bin/printf '%s\n' "$manifest"
}

scrub_anchored_directory() {
    local fd=$1 anchor=$2 identity=$3 expected_manifest=$4 observed_manifest leftover remaining timeout_seconds root_dev
    observed_manifest=$(preflight_anchored_directory "$anchor" "$identity") || return 1
    [[ "$observed_manifest" == "$expected_manifest" ]] || return 1
    [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 \
        && "$identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "/proc/self/fd/$fd" 2>/dev/null || true)" ]] \
        || return 1
    remaining=$((cleanup_deadline - SECONDS))
    (( remaining > 5 )) || return 1
    timeout_seconds=$((remaining - 5))
    root_dev=${identity%%:*}
    /usr/bin/timeout --signal=TERM --kill-after=5s "${timeout_seconds}s" \
        /usr/bin/python3.12 -I -S -B "/proc/self/fd/$scrubber_fd" \
        "${GATE_EXPECTED_UID}" "$root_dev" "$fd:" >/dev/null 2>&1 \
        || return 1
    leftover=$(/usr/bin/timeout --signal=TERM --kill-after=1s 3s \
        /usr/bin/find "$anchor" -xdev -mindepth 1 ! -type d -print -quit 2>/dev/null) \
        || return 1
    [[ -z "$leftover" ]]
}

preflight_exact_probe_file() {
    local fd=$1 expected_dev_inode=$2 observed
    [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 \
        && "$expected_dev_inode" =~ ^[0-9]+:[0-9]+$ ]] || return 1
    observed=$(/usr/bin/stat -Lc '%d:%i:%u:%h' -- "/proc/self/fd/$fd" 2>/dev/null) \
        || return 1
    [[ -f "/proc/self/fd/$fd" \
        && ( "$observed" == "${expected_dev_inode}:${GATE_EXPECTED_UID}:0" \
            || "$observed" == "${expected_dev_inode}:${GATE_EXPECTED_UID}:1" ) ]]
}

scrub_exact_probe_file() {
    local fd=$1 expected_dev_inode=$2 entry_name=$3 remaining timeout_seconds helper_rc root_dev
    preflight_exact_probe_file "$fd" "$expected_dev_inode" || return 1
    /usr/bin/timeout --signal=TERM --kill-after=1s 2s \
        /usr/bin/chmod 600 -- "/proc/self/fd/$fd" 2>/dev/null || return 1
    /usr/bin/timeout --signal=TERM --kill-after=1s 5s \
        /usr/bin/truncate -s 0 -- "/proc/self/fd/$fd" 2>/dev/null || return 1
    [[ -f "/proc/self/fd/$fd" \
        && "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "/proc/self/fd/$fd" 2>/dev/null)" \
            =~ ^${expected_dev_inode}:600:${GATE_EXPECTED_UID}:[01]:0$ ]] \
        || return 1
    remaining=$((cleanup_deadline - SECONDS))
    (( remaining > 2 )) || return 1
    timeout_seconds=$((remaining - 1))
    root_dev=${private_root_identity%%:*}
    if /usr/bin/timeout --signal=TERM --kill-after=1s "${timeout_seconds}s" \
        /usr/bin/python3.12 -I -S -B "/proc/self/fd/$scrubber_fd" \
        --bound-file "${GATE_EXPECTED_UID}" "$root_dev" "$private_root_fd" "$entry_name" "$fd" \
        >/dev/null 2>&1; then
        helper_rc=0
    else
        helper_rc=$?
    fi
    case "$helper_rc" in
        0) return 0 ;;
        42) return 42 ;;
        *) return 1 ;;
    esac
}

wait_cleanup_child() {
    local pid=$1 status
    while true; do
        if wait "$pid"; then
            return 0
        fi
        status=$?
        # A trapped signal interrupts Bash's wait while the exact cleanup
        # child remains alive. Keep ownership and wait for its real status.
        if [[ -n "$pending_signal" ]] && /usr/bin/kill -0 -- "$pid" 2>/dev/null; then
            continue
        fi
        return "$status"
    done
}

remove_guard_alias() {
    local observed
    (( podman_guard_alias_clean == 0 )) || return 0
    [[ -n "$podman_guard_alias_anchor" && -n "$podman_guard_alias_identity" ]] || return 0
    observed=$(/usr/bin/stat -c '%d:%i:%u:%h' -- "$podman_guard_alias_anchor" 2>/dev/null || true)
    [[ -L "$podman_guard_alias_anchor" \
        && "$observed" == "$podman_guard_alias_identity" \
        && "$(/usr/bin/readlink -- "$podman_guard_alias_anchor" 2>/dev/null || true)" == "/proc/self/fd/$podman_guard_fd" ]] \
        || return 1
    /usr/bin/unlink -- "$podman_guard_alias_anchor" 2>/dev/null || return 1
    [[ ! -e "$podman_guard_alias_anchor" && ! -L "$podman_guard_alias_anchor" ]] || return 1
    podman_guard_alias_clean=1
}

close_probe_private_fds() {
    local index fd result=0
    for index in "${!private_dir_fds[@]}"; do
        fd=${private_dir_fds[$index]}
        if [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 ]]; then
            exec {fd}<&- || result=1
        fi
    done
    private_dir_fds=()
    for fd in "$storage_conf_fd" "$local_tls_fd" "$inspect_fd"; do
        if [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 ]]; then
            exec {fd}>&- || result=1
        fi
    done
    storage_conf_fd=-1
    local_tls_fd=-1
    inspect_fd=-1
    if [[ "$podman_guard_fd" =~ ^[0-9]+$ && "$podman_guard_fd" -ge 10 ]]; then
        exec {podman_guard_fd}<&- || result=1
        podman_guard_fd=-1
    fi
    if [[ "$scrubber_fd" =~ ^[0-9]+$ && "$scrubber_fd" -ge 10 ]]; then
        exec {scrubber_fd}<&- || result=1
        scrubber_fd=-1
    fi
    if [[ "$private_root_fd" =~ ^[0-9]+$ && "$private_root_fd" -ge 10 ]]; then
        exec {private_root_fd}<&- || result=1
        private_root_fd=-1
    fi
    (( result == 0 ))
}

scrub_private_contents() {
    local index pid fd identity path clean manifest preflight_output result=0 observed child_result
    local named_now anchored_after unexpected storage_named tls_named inspect_named
    local pids=()
    private_root_bound || return 1
    cleanup_checkpoint probe_scrub_start

    # Trust boundary: only this probe and its supervised Podman children may
    # mutate the mode-0700 private tree. Cleanup starts after those children are
    # reaped. Within that boundary, validate every target globally before the
    # first chmod/truncate/delete, then require the same inode manifest again at
    # each anchored directory's mutation boundary. A hostile process with the
    # same uid is outside this authorization boundary and invalidates the gate.
    mount_free_anchored_tree "$private_root_anchor" || return 1
    unexpected=$(/usr/bin/timeout --signal=TERM --kill-after=1s 3s \
        /usr/bin/find "$private_root_anchor" -xdev -mindepth 1 -maxdepth 1 \
            ! -name graphroot ! -name runroot ! -name xdg-runtime ! -name xdg-config \
            ! -name xdg-data ! -name home ! -name tmp ! -name storage.conf \
            ! -name tls-combined.pem ! -name inspect -print -quit 2>/dev/null) \
        || return 1
    [[ -z "$unexpected" ]] || return 1
    cleanup_checkpoint probe_after_global_root_preflight
    private_dir_manifests=()
    if (( private_runtime_armed )); then
        ((${#private_dir_fds[@]} == 7 \
            && ${#private_dir_anchors[@]} == 7 \
            && ${#private_dir_identities[@]} == 7)) || return 1
        preflight_output=$(
            child_result=0
            child_pids=()
            for index in "${!private_dir_anchors[@]}"; do
                (
                    manifest=$(preflight_anchored_directory \
                        "${private_dir_anchors[$index]}" "${private_dir_identities[$index]}") \
                        || exit 1
                    /usr/bin/printf '%s:%s\n' "$index" "$manifest"
                ) &
                child_pids+=("$!")
            done
            for pid in "${child_pids[@]}"; do
                wait "$pid" || child_result=1
            done
            (( child_result == 0 ))
        ) || return 1
        while IFS=: read -r index manifest; do
            [[ "$index" =~ ^[0-9]+$ && "$manifest" =~ ^[0-9a-f]{64}$ \
                && -z "${private_dir_manifests[$index]+x}" ]] || return 1
            private_dir_manifests[$index]=$manifest
        done <<< "$preflight_output"
    fi
    ((${#private_dir_manifests[@]} == ${#private_dir_anchors[@]} || ! private_runtime_armed)) \
        || return 1
    if (( private_runtime_armed )); then
        for index in "${!private_dir_anchors[@]}"; do
            [[ -n "${private_dir_manifests[$index]:-}" ]] || return 1
        done
    fi
    cleanup_checkpoint probe_after_directory_preflight
    for fd in "$storage_conf_fd" "$local_tls_fd" "$inspect_fd"; do
        case "$fd" in
            "$storage_conf_fd") identity=$storage_conf_identity; path=$storage_conf; clean=$storage_conf_clean ;;
            "$local_tls_fd") identity=$local_tls_identity; path=$local_tls; clean=$local_tls_clean ;;
            "$inspect_fd") identity=$inspect_identity; path=$inspect_file; clean=$inspect_clean ;;
            *) return 1 ;;
        esac
        if [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 ]]; then
            preflight_exact_probe_file "$fd" "$identity" || return 1
            observed=$(/usr/bin/stat -c '%d:%i' -- "$path" 2>/dev/null || true)
            if (( clean )); then
                [[ -z "$observed" ]] || cleanup_root_drift=1
            else
                [[ "$observed" == "$identity" ]] || cleanup_root_drift=1
            fi
        elif [[ "$fd" != -1 || -n "$identity" ]]; then
            return 1
        fi
    done
    cleanup_checkpoint probe_after_exact_preflight

    # The exact guard alias is the only authorized symlink. It was included in
    # the global preflight above; remove it through the retained tmp-dir anchor
    # before the no-follow scrubber validates and mutates any directory.
    cleanup_checkpoint probe_before_guard_alias_removal
    remove_guard_alias || return 1
    cleanup_checkpoint probe_after_guard_alias_removal
    if (( podman_guard_alias_clean )); then
        for index in "${!private_dir_paths[@]}"; do
            if [[ "${private_dir_paths[$index]}" == "$private_tmp" ]]; then
                manifest=$(preflight_anchored_directory \
                    "${private_dir_anchors[$index]}" "${private_dir_identities[$index]}") \
                    || return 1
                private_dir_manifests[$index]=$manifest
            fi
        done
    fi

    # All targets passed the global phase. Run the independent anchored scrubs
    # concurrently so the signal bound is the slowest scrub, not their sum.
    cleanup_checkpoint probe_before_directory_scrub
    if (( private_runtime_armed )); then
        for index in "${!private_dir_anchors[@]}"; do
            scrub_anchored_directory "${private_dir_fds[$index]}" "${private_dir_anchors[$index]}" \
                "${private_dir_identities[$index]}" "${private_dir_manifests[$index]}" &
            pids+=("$!")
        done
    fi
    cleanup_checkpoint probe_after_directory_scrub
    for fd in "$storage_conf_fd" "$local_tls_fd" "$inspect_fd"; do
        case "$fd" in
            "$storage_conf_fd") identity=$storage_conf_identity; path=storage.conf; clean=$storage_conf_clean ;;
            "$local_tls_fd") identity=$local_tls_identity; path=tls-combined.pem; clean=$local_tls_clean ;;
            "$inspect_fd") identity=$inspect_identity; path=inspect; clean=$inspect_clean ;;
            *) return 1 ;;
        esac
        if [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 ]] && (( clean == 0 )); then
            cleanup_checkpoint "probe_before_${path}_scrub"
            if scrub_exact_probe_file "$fd" "$identity" "$path"; then
                child_result=0
            else
                child_result=$?
            fi
            case "$child_result" in
                0)
                    case "$path" in
                        storage.conf) storage_conf_clean=1 ;;
                        tls-combined.pem) local_tls_clean=1 ;;
                        inspect) inspect_clean=1 ;;
                    esac
                    ;;
                42)
                    cleanup_root_drift=1
                    case "$path" in
                        storage.conf) storage_conf_clean=1 ;;
                        tls-combined.pem) local_tls_clean=1 ;;
                        inspect) inspect_clean=1 ;;
                    esac
                    ;;
                *) result=1 ;;
            esac
            cleanup_checkpoint "probe_after_${path}_scrub"
        fi
    done
    for pid in "${pids[@]}"; do
        wait_cleanup_child "$pid" || result=1
    done
    # Never remove the main or top-level directory names. The children are
    # verified empty and the main root contains only those children plus three
    # zero-length bound files, eliminating stat-to-rmdir replacement races.
    cleanup_checkpoint probe_before_postflight
    if (( private_runtime_armed )); then
        retained_private_dirs_bound || result=1
        for index in "${!private_dir_paths[@]}"; do
            observed=$(/usr/bin/stat -c '%d:%i:%a:%u' -- "${private_dir_paths[$index]}" 2>/dev/null || true)
            if [[ "$observed" != "${private_dir_identities[$index]}" ]]; then
                cleanup_root_drift=1
            fi
        done
    else
        result=1
    fi
    named_now=$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private_root" 2>/dev/null || true)
    anchored_after=$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$private_root_anchor" 2>/dev/null || true)
    [[ "$anchored_after" == "$private_root_identity" ]] || result=1
    [[ "$named_now" == "$private_root_identity" ]] || cleanup_root_drift=1
    storage_named=$(/usr/bin/stat -c '%d:%i:%a:%u:%h:%s' -- "$storage_conf" 2>/dev/null || true)
    tls_named=$(/usr/bin/stat -c '%d:%i:%a:%u:%h:%s' -- "$local_tls" 2>/dev/null || true)
    inspect_named=$(/usr/bin/stat -c '%d:%i:%a:%u:%h:%s' -- "$inspect_file" 2>/dev/null || true)
    [[ -z "$storage_named" ]] || cleanup_root_drift=1
    [[ -z "$tls_named" ]] || cleanup_root_drift=1
    [[ -z "$inspect_named" ]] || cleanup_root_drift=1
    unexpected=$(/usr/bin/timeout --signal=TERM --kill-after=1s 3s \
        /usr/bin/find "$private_root_anchor" -xdev -mindepth 1 -maxdepth 1 \
        ! -name graphroot ! -name runroot ! -name xdg-runtime ! -name xdg-config \
        ! -name xdg-data ! -name home ! -name tmp ! -name storage.conf \
        ! -name tls-combined.pem ! -name inspect -print -quit 2>/dev/null) \
        || result=1
    [[ -z "$unexpected" ]] || result=1
    cleanup_checkpoint probe_after_postflight
    (( result == 0 ))
}

retain_private_root() {
    local result=0
    cleanup_checkpoint probe_before_in_progress
    cleanup_in_progress=1
    cleanup_checkpoint probe_in_progress
    scrub_private_contents || result=1
    cleanup_checkpoint probe_after_scrub
    if (( result == 0 )); then
        cleanup_checkpoint probe_before_fd_close
        close_probe_private_fds || result=1
        cleanup_checkpoint probe_after_fd_close
    fi
    if (( result == 0 )); then
        cleanup_checkpoint probe_before_complete
        if (( cleanup_root_drift )); then
            cleanup_outcome=retained_drift
        else
            cleanup_complete=1
            cleanup_outcome=retained_empty
        fi
        cleanup_checkpoint probe_after_complete
    fi
    cleanup_checkpoint probe_before_in_progress_clear
    cleanup_in_progress=0
    cleanup_checkpoint probe_after_in_progress
    (( result == 0 && cleanup_complete == 1 && cleanup_root_drift == 0 ))
}

cleanup_private_tree() {
    local attempt=0 result=1
    if (( cleanup_complete )); then
        [[ "$cleanup_outcome" == retained_empty ]] && return 0
        return 1
    fi
    cleanup_checkpoint probe_before_cleanup_running
    cleanup_running=1
    cleanup_checkpoint probe_cleanup_running
    if ! [[ "$private_root_fd" =~ ^[0-9]+$ && "$private_root_fd" -ge 10 ]]; then
        if [[ -z "$private_root" ]]; then
            cleanup_complete=1
            cleanup_outcome=retained_empty
            result=0
        fi
    else
        if (( cleanup_deadline == 0 )); then
            cleanup_deadline=$((SECONDS + 125))
        fi
        while (( cleanup_complete == 0 && attempt < cleanup_retry_limit && SECONDS < cleanup_deadline )); do
            cleanup_checkpoint probe_before_attempt
            attempt=$((attempt + 1))
            if retain_private_root; then
                cleanup_checkpoint probe_after_attempt
                break
            fi
            cleanup_checkpoint probe_after_attempt
        done
        if (( cleanup_complete == 1 )) && [[ "$cleanup_outcome" == retained_empty ]]; then
            result=0
        fi
    fi
    cleanup_checkpoint probe_before_cleanup_running_clear
    cleanup_running=0
    cleanup_checkpoint probe_after_cleanup_running
    (( result == 0 ))
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
    close_probe_private_fds >/dev/null 2>&1 || true
    if [[ -n "$pending_signal" ]]; then
        saved=$pending_signal_status
    fi
    exit "$saved"
}
trap exit_cleanup EXIT
trap 'handle_signal HUP' HUP
trap 'handle_signal INT' INT
trap 'handle_signal TERM' TERM
private_root=$(/usr/bin/mktemp -d "$local_parent/k3-registry-pull-v23.${SLURM_JOB_ID}.${SLURM_STEP_ID}.XXXXXX") \
    || blocked private_environment
[[ "$private_root" == "$local_parent"/k3-registry-pull-v23."${SLURM_JOB_ID}"."${SLURM_STEP_ID}".* \
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
readonly private_tmp=$private_root/tmp
readonly storage_conf=$private_root/storage.conf
readonly inspect_file=$private_root/inspect
readonly local_tls=$private_root/tls-combined.pem
/usr/bin/mkdir -m 700 -- "$graphroot" "$runroot" "$xdg_runtime" "$xdg_config" "$private_home" "$private_tmp" \
    || blocked private_environment
/usr/bin/printf '[storage]\ndriver = "overlay"\ngraphroot = "%s"\nrunroot = "%s"\n' \
    "$graphroot" "$runroot" > "$storage_conf" \
    || blocked private_environment
/usr/bin/chmod 600 "$storage_conf" || blocked private_environment
/usr/bin/touch "$local_tls" 2>/dev/null || blocked private_environment
/usr/bin/chmod 600 "$local_tls" 2>/dev/null || blocked private_environment
/usr/bin/touch "$inspect_file" 2>/dev/null || blocked private_environment
/usr/bin/chmod 600 "$inspect_file" 2>/dev/null || blocked private_environment
exec {storage_conf_fd}<>"$storage_conf" 2>/dev/null || blocked private_environment
storage_conf_identity=$(/usr/bin/stat -Lc '%d:%i' -- "/proc/self/fd/$storage_conf_fd") \
    || blocked private_environment
exec {local_tls_fd}<>"$local_tls" 2>/dev/null || blocked private_environment
# Arm the immutable TLS inode identity before the first byte is copied. Any
# signal/error after this point can scrub the exact retained descriptor even if
# the final mode/hash validation has not run yet.
local_tls_identity=$(/usr/bin/stat -Lc '%d:%i' -- "/proc/self/fd/$local_tls_fd") \
    || blocked private_environment
exec {inspect_fd}<>"$inspect_file" 2>/dev/null || blocked private_environment
inspect_identity=$(/usr/bin/stat -Lc '%d:%i' -- "/proc/self/fd/$inspect_fd") \
    || blocked private_environment
/usr/bin/cp -- /proc/self/fd/4 "/proc/self/fd/$local_tls_fd" 2>/dev/null || blocked private_environment
/usr/bin/chmod 500 "/proc/self/fd/$local_tls_fd" 2>/dev/null || blocked private_environment
[[ "$(/usr/bin/stat -c '%a:%u:%h' -- "$storage_conf")" == "600:${GATE_EXPECTED_UID}:1" ]] \
    || blocked private_environment
[[ "$local_tls" == "$(/usr/bin/readlink -f -- "$local_tls" 2>/dev/null)" \
    && -f "$local_tls" && ! -L "$local_tls" \
    && "$(/usr/bin/stat -c '%a:%u:%h:%s' -- "$local_tls")" == "500:${GATE_EXPECTED_UID}:1:${GATE_TLS_SIZE}" \
    && "$(/usr/bin/sha256sum -- "$local_tls" | /usr/bin/cut -d' ' -f1)" == "${GATE_TLS_SHA256:-}" ]] \
    || blocked private_environment
[[ "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$storage_conf_fd")" \
        == "${storage_conf_identity}:600:${GATE_EXPECTED_UID}:1" \
    && "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$local_tls_fd")" \
        == "${local_tls_identity}:500:${GATE_EXPECTED_UID}:1" \
    && "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$inspect_fd")" \
        == "${inspect_identity}:600:${GATE_EXPECTED_UID}:1" \
    && "${storage_conf_identity}:600:${GATE_EXPECTED_UID}:1" == "$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$storage_conf")" \
    && "${local_tls_identity}:500:${GATE_EXPECTED_UID}:1" == "$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$local_tls")" \
    && "${inspect_identity}:600:${GATE_EXPECTED_UID}:1" == "$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$inspect_file")" ]] \
    || blocked private_environment
exec 4<&-

export HOME=$private_home
export XDG_RUNTIME_DIR=$xdg_runtime
export XDG_CONFIG_HOME=$xdg_config
export XDG_DATA_HOME=$private_root/xdg-data
export CONTAINERS_STORAGE_CONF=$storage_conf
export TMPDIR=$private_tmp
export THRIFT_TLS_CL_CERT_PATH=$local_tls
export THRIFT_TLS_CL_KEY_PATH=$local_tls
/usr/bin/mkdir -m 700 -- "$XDG_DATA_HOME" || blocked private_environment
for private_path in "$private_root" "$graphroot" "$runroot" "$xdg_runtime" \
    "$xdg_config" "$XDG_DATA_HOME" "$private_home" "$private_tmp"; do
    [[ "$private_path" != /proc/self/fd/* \
        && ( "$private_path" == "$private_root" || "$private_path" == "$private_root"/* ) ]] \
        || blocked private_environment
    [[ "$private_path" == "$(/usr/bin/readlink -f -- "$private_path" 2>/dev/null)" \
        && -d "$private_path" && ! -L "$private_path" \
        && "$(/usr/bin/stat -c '%a:%u' -- "$private_path")" == "700:${GATE_EXPECTED_UID}" ]] \
        || blocked private_environment
done
unset private_path
graphroot_fd=-1
runroot_fd=-1
xdg_runtime_fd=-1
xdg_config_fd=-1
xdg_data_fd=-1
private_home_fd=-1
private_tmp_fd=-1
if ! exec {graphroot_fd}<"$graphroot" {runroot_fd}<"$runroot" \
    {xdg_runtime_fd}<"$xdg_runtime" {xdg_config_fd}<"$xdg_config" \
    {xdg_data_fd}<"$XDG_DATA_HOME" {private_home_fd}<"$private_home" \
    {private_tmp_fd}<"$private_tmp" 2>/dev/null; then
    blocked private_environment
fi
private_dir_paths=("$graphroot" "$runroot" "$xdg_runtime" "$xdg_config" "$XDG_DATA_HOME" "$private_home" "$private_tmp")
private_dir_fds=("$graphroot_fd" "$runroot_fd" "$xdg_runtime_fd" "$xdg_config_fd" "$xdg_data_fd" "$private_home_fd" "$private_tmp_fd")
for private_fd_value in "${private_dir_fds[@]}"; do
    private_dir_anchors+=("/proc/self/fd/${private_fd_value}/.")
    private_dir_identities+=("$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "/proc/self/fd/${private_fd_value}/." 2>/dev/null)")
done
unset private_fd_value
private_dirs_bound || blocked private_environment
readonly podman_guard_alias=$private_tmp/podman
/usr/bin/ln -s -- "/proc/self/fd/$podman_guard_fd" "$podman_guard_alias" 2>/dev/null \
    || blocked private_environment
podman_guard_alias_anchor=${private_dir_anchors[6]}/podman
podman_guard_alias_identity=$(/usr/bin/stat -c '%d:%i:%u:%h' -- "$podman_guard_alias_anchor" 2>/dev/null) \
    || blocked private_environment
[[ -L "$podman_guard_alias" \
    && -L "$podman_guard_alias_anchor" \
    && "$podman_guard_alias_identity" == "$(/usr/bin/stat -c '%d:%i:%u:%h' -- "$podman_guard_alias" 2>/dev/null)" \
    && "$podman_guard_alias_identity" == *":${GATE_EXPECTED_UID}:1" \
    && "$(/usr/bin/readlink -- "$podman_guard_alias" 2>/dev/null)" == "/proc/self/fd/$podman_guard_fd" \
    && "${guard_before%:*}" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "$podman_guard_alias" 2>/dev/null)" ]] \
    || blocked private_environment
export GATE_PRIVATE_ROOT_PATH=$private_root
export GATE_PRIVATE_ROOT_ANCHOR=$private_root_anchor
export GATE_PRIVATE_ROOT_IDENTITY=$private_root_identity
export GATE_PODMAN_GUARD_FD=$podman_guard_fd
export GATE_PODMAN_GUARD_IDENTITY=${guard_before%:*}
export GATE_PODMAN_GUARD_ALIAS=$podman_guard_alias
for index in "${!private_dir_paths[@]}"; do
    export "GATE_PRIVATE_PATH_${index}=${private_dir_paths[$index]}"
    export "GATE_PRIVATE_ANCHOR_${index}=${private_dir_anchors[$index]}"
    export "GATE_PRIVATE_IDENTITY_${index}=${private_dir_identities[$index]}"
    readonly "GATE_PRIVATE_PATH_${index}" "GATE_PRIVATE_ANCHOR_${index}" \
        "GATE_PRIVATE_IDENTITY_${index}"
done
unset index
readonly GATE_PRIVATE_ROOT_PATH GATE_PRIVATE_ROOT_ANCHOR GATE_PRIVATE_ROOT_IDENTITY
readonly GATE_PODMAN_GUARD_FD GATE_PODMAN_GUARD_IDENTITY GATE_PODMAN_GUARD_ALIAS
readonly GATE_PODMAN_GUARD_SHA256 GATE_EXPECTED_UID
export PATH=$private_tmp:/usr/bin:/bin
private_runtime_armed=1

private_dirs_bound || blocked private_environment
store=$(/usr/bin/podman info --format '{{.Store.GraphRoot}}|{{.Store.RunRoot}}|{{.Store.GraphDriverName}}' 2>/dev/null) \
    || blocked podman_info
private_dirs_bound || blocked private_environment
[[ "$store" == "$graphroot|$runroot|overlay" ]] || blocked podman_info
unset store
set +e
private_dirs_bound || blocked private_environment
/usr/bin/podman image exists "$GATE_IMAGE" >/dev/null 2>&1
cold_exists_rc=$?
set -e
private_dirs_bound || blocked private_environment
if (( cold_exists_rc != 1 )); then
    blocked podman_info
fi
unset cold_exists_rc
private_dirs_bound || blocked private_environment

# Source only the reviewed registry functions in a child shell. Its hardened
# registry trap therefore cannot replace this probe's job-local cleanup trap.
# No worker main, model path, GPU enumeration, container construction, or
# podman run entry point is invoked.
private_dirs_bound || blocked private_environment
(
    source /proc/self/fd/8 || blocked probe_source_identity
    source /proc/self/fd/9 || blocked probe_source_identity
    exec 7<&- 8<&- 9<&-
    exec {scrubber_fd}<&-
    _container_registry_arm_cleanup
    private_dirs_bound || blocked private_environment
    _container_registry_login "$GATE_IMAGE"
    private_dirs_bound || blocked private_environment
    auth_path=${_CONTAINER_REGISTRY_AUTH_PATH:-}
    auth_fd=-1
    [[ "$auth_path" == "$xdg_runtime"/serve-api-v2-registry-auth.* \
        && "$(/usr/bin/stat -c '%a:%u:%h' -- "$auth_path")" == "600:${GATE_EXPECTED_UID}:1" ]] \
        || blocked registry_login
    exec {auth_fd}<>"$auth_path" 2>/dev/null || blocked registry_login
    auth_identity=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$auth_path") \
        || blocked registry_login
    [[ "$auth_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$auth_fd")" ]] \
        || blocked registry_login
    private_dirs_bound || blocked private_environment
    _container_registry_pull "$GATE_IMAGE"
    private_dirs_bound || blocked private_environment
    _container_registry_disarm_cleanup
    private_dirs_bound || blocked private_environment
    /usr/bin/timeout --signal=TERM --kill-after=1s 5s \
        /usr/bin/truncate -s 0 -- "/proc/self/fd/$auth_fd" 2>/dev/null \
        || blocked private_cleanup
    auth_after=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "/proc/self/fd/$auth_fd") \
        || blocked private_cleanup
    [[ ! -e "$auth_path" && ! -L "$auth_path" && -z "${REGISTRY_AUTH_FILE+x}" ]] \
        || blocked private_cleanup
    [[ "${auth_after%:*:*:*:*}" == "${auth_identity%:*:*:*}" \
        && "$auth_after" == *":600:${GATE_EXPECTED_UID}:0:0" ]] \
        || blocked private_cleanup
    exec {auth_fd}>&-
)
private_dirs_bound || blocked private_cleanup
if ! leftover_auth=$(/usr/bin/find "${private_dir_anchors[2]}" -xdev \
    -name 'serve-api-v2-registry-auth.*' -print -quit); then
    blocked private_cleanup
fi
if [[ -n "$leftover_auth" ]]; then
    blocked private_cleanup
fi
unset leftover_auth

private_dirs_bound || blocked private_cleanup
: > "/proc/self/fd/$inspect_fd" || blocked private_environment
/usr/bin/podman image inspect \
    --format '{{.Digest}}|{{.Os}}|{{.Architecture}}|{{join .RepoDigests ","}}' \
    "$GATE_IMAGE" > "/proc/self/fd/$inspect_fd" 2>/dev/null \
    || blocked image_identity
private_dirs_bound || blocked private_cleanup
IFS='|' read -r observed_digest observed_os observed_arch observed_repodigests < "/proc/self/fd/$inspect_fd" \
    || blocked image_identity
[[ "$observed_digest" == "$GATE_IMAGE_DIGEST" \
    && "$observed_os" == linux && "$observed_arch" == arm64 \
    && ",$observed_repodigests," == *,*"@${GATE_IMAGE_DIGEST}"*,* ]] \
    || blocked image_identity
: > "/proc/self/fd/$inspect_fd"
unset observed_digest observed_os observed_arch observed_repodigests

private_dirs_bound || blocked private_cleanup
store=$(/usr/bin/podman info --format '{{.Store.GraphRoot}}|{{.Store.RunRoot}}' 2>/dev/null) \
    || blocked private_cleanup
private_dirs_bound || blocked private_cleanup
[[ "$store" == "$graphroot|$runroot" ]] || blocked private_cleanup
private_dirs_bound || blocked private_cleanup
/usr/bin/podman image rm --force "$GATE_IMAGE" >/dev/null 2>&1 \
    || blocked private_cleanup
private_dirs_bound || blocked private_cleanup
set +e
private_dirs_bound || blocked private_cleanup
/usr/bin/podman image exists "$GATE_IMAGE" >/dev/null 2>&1
image_exists_rc=$?
set -e
private_dirs_bound || blocked private_cleanup
if (( image_exists_rc == 0 )); then
    blocked private_cleanup
elif (( image_exists_rc != 1 )); then
    blocked private_cleanup
fi
unset store image_exists_rc
private_dirs_bound || blocked private_cleanup

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
/usr/bin/printf '{"category":"success","image_digest":"%s","kind":"k3-registry-pull-gate-v23","platform":"linux/arm64","state":"complete"}\n' \
    "$GATE_IMAGE_DIGEST"
