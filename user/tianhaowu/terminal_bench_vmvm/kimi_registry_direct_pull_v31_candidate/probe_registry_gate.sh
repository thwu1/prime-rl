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
readonly expected_source_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/ram-common-35f08dd
readonly expected_image=588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/vllm-openai:kimi-k3-kda-logprobs-fix-v2-20260916@sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20
readonly tools_manifest=${GATE_LOCAL_TOOL_MANIFEST:-}
[[ "${GATE_SOURCE_ROOT:-}" == "$expected_source_root" \
    && "${GATE_SOURCE_REVISION:-}" == 35f08dd04e9cbad34d56b6c386c7874679b21b3c \
    && "${GATE_SOURCE_TREE:-}" == 19b7a066b0631dab87a8187127ed2229756e26e9 \
    && "${GATE_IMAGE:-}" == "$expected_image" \
    && "${GATE_IMAGE_DIGEST:-}" == sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20 \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$worker")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$aws_creds")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/sha256sum -- "$worker" | /usr/bin/cut -d' ' -f1)" == "${GATE_WORKER_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- "$aws_creds" | /usr/bin/cut -d' ' -f1)" == "${GATE_AWS_CREDS_SHA256:-}" \
    && ( "$tools_manifest" == /var/slurm-tmp/k3-registry-direct-pull-v31.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /var/slurm-tmp/*/k3-registry-direct-pull-v31.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /tmp/k3-registry-direct-pull-v31.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /tmp/*/k3-registry-direct-pull-v31.batch.*.*/compute_tools.sha256 ) \
    && "$tools_manifest" != /proc/self/fd/* \
    && "$tools_manifest" == "$(/usr/bin/readlink -f -- "$tools_manifest" 2>/dev/null)" \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$tools_manifest")" == 'regular file:400:656177:1' \
    && "$(/usr/bin/sha256sum -- "$tools_manifest" | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" \
    && "$podman_guard" == /checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_direct_pull_gate_20260920t193000z_v31/podman_guard.sh \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$podman_guard")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/sha256sum -- "$podman_guard" | /usr/bin/cut -d' ' -f1)" == "${GATE_PODMAN_GUARD_SHA256:-}" \
    && ( "$scrubber" == /var/slurm-tmp/k3-registry-direct-pull-v31.batch.*.*/scrub_private_tree.py \
        || "$scrubber" == /var/slurm-tmp/*/k3-registry-direct-pull-v31.batch.*.*/scrub_private_tree.py \
        || "$scrubber" == /tmp/k3-registry-direct-pull-v31.batch.*.*/scrub_private_tree.py \
        || "$scrubber" == /tmp/*/k3-registry-direct-pull-v31.batch.*.*/scrub_private_tree.py ) \
    && "$scrubber" != /proc/self/fd/* \
    && "$scrubber" == "$(/usr/bin/readlink -f -- "$scrubber" 2>/dev/null)" \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$scrubber")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/sha256sum -- "$scrubber" | /usr/bin/cut -d' ' -f1)" == "${GATE_SCRUBBER_SHA256:-}" ]] \
    || blocked probe_source_identity
readonly GATE_IMAGE GATE_IMAGE_DIGEST
worker_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$worker") || blocked probe_source_identity
aws_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$aws_creds") || blocked probe_source_identity
tools_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest") || blocked probe_source_identity
guard_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$podman_guard") || blocked probe_source_identity
scrubber_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$scrubber") || blocked probe_source_identity
podman_guard_fd=-1
scrubber_fd=-1
if ! { exec 9<"$worker" 8<"$aws_creds" 7<"$tools_manifest" \
    {podman_guard_fd}<"$podman_guard" {scrubber_fd}<"$scrubber"; } 2>/dev/null; then
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
if ! { exec 4<"$tls_source"; } 2>/dev/null; then
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
unset CONTAINERS_REGISTRIES_CONF CONTAINERS_REGISTRIES_CONF_DIR REGISTRIES_CONFIG_PATH
unset STORAGE_DRIVER STORAGE_OPTS
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
runroot_anchor=
runroot_identity=
storage_conf_fd=-1
storage_conf_identity=
storage_conf_sha=
storage_conf_clean=0
local_tls_fd=-1
local_tls_identity=
local_tls_clean=0
inspect_fd=-1
inspect_identity=
inspect_clean=0
writer_state_required=0
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
    ((${#private_dir_paths[@]} == 6 \
        && ${#private_dir_fds[@]} == 6 \
        && ${#private_dir_anchors[@]} == 6 \
        && ${#private_dir_identities[@]} == 6)) || return 1
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
    [[ "$runroot" == "$xdg_runtime/containers" \
        && "$runroot_anchor" == "${private_dir_anchors[1]}/containers" \
        && -d "$runroot" && ! -L "$runroot" \
        && -d "$runroot_anchor" && ! -L "$runroot_anchor" \
        && "$runroot_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$runroot" 2>/dev/null || true)" \
        && "$runroot_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$runroot_anchor" 2>/dev/null || true)" ]] \
        || return 1
}

retained_private_dirs_bound() {
    local index fd anchor identity
    ((${#private_dir_fds[@]} == 6 \
        && ${#private_dir_anchors[@]} == 6 \
        && ${#private_dir_identities[@]} == 6)) || return 1
    for index in "${!private_dir_fds[@]}"; do
        fd=${private_dir_fds[$index]}
        anchor=${private_dir_anchors[$index]}
        identity=${private_dir_identities[$index]}
        [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 \
            && -d "$anchor" && ! -L "$anchor" \
            && "$identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$anchor" 2>/dev/null || true)" ]] \
            || return 1
    done
    [[ -d "$runroot_anchor" && ! -L "$runroot_anchor" \
        && "$runroot_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$runroot_anchor" 2>/dev/null || true)" ]] \
        || return 1
}

writer_state_file_bound() {
    [[ "$inspect_fd" =~ ^[0-9]+$ && "$inspect_fd" -ge 10 \
        && "$inspect_identity" == "$(/usr/bin/stat -Lc '%d:%i' -- "/proc/self/fd/$inspect_fd" 2>/dev/null || true)" \
        && "${inspect_identity}:600:${GATE_EXPECTED_UID}:1" \
            == "$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$inspect_file" 2>/dev/null || true)" ]]
}

set_writer_state() {
    local state=$1
    case "$state" in armed|quiesced) ;; *) return 1 ;; esac
    writer_state_file_bound || return 1
    builtin printf -- 'gate_writer_state=%s\n' "$state" > "/proc/self/fd/$inspect_fd" \
        || return 1
    /usr/bin/sync -f "/proc/self/fd/$inspect_fd" 2>/dev/null || return 1
    writer_state_file_bound || return 1
    [[ "$(<"/proc/self/fd/$inspect_fd")" == "gate_writer_state=$state" ]]
}

writer_is_quiesced() {
    (( writer_state_required == 1 )) \
        && writer_state_file_bound \
        && [[ "$(<"/proc/self/fd/$inspect_fd")" == gate_writer_state=quiesced ]]
}

image_identity_matches() {
    local image=$1 expected_digest=$2 observed_digest=$3 observed_os=$4 observed_arch=$5
    local observed_repodigests=$6 target_without_digest target_leaf target_repo expected_repo_digest
    [[ "$expected_digest" =~ ^sha256:[0-9a-f]{64}$ \
        && "$image" == *"@$expected_digest" ]] || return 1
    target_without_digest=${image%@*}
    target_leaf=${target_without_digest##*/}
    if [[ "$target_leaf" == *:* ]]; then
        target_repo=${target_without_digest%:*}
    else
        target_repo=$target_without_digest
    fi
    expected_repo_digest=${target_repo}@${expected_digest}
    [[ "$observed_digest" == "$expected_digest" \
        && "$observed_os" == linux && "$observed_arch" == arm64 \
        && ",$observed_repodigests," == *",$expected_repo_digest,"* ]]
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
            ! -name graphroot ! -name xdg-runtime ! -name xdg-config \
            ! -name xdg-data ! -name home ! -name tmp ! -name storage.conf \
            ! -name tls-combined.pem ! -name inspect -print -quit 2>/dev/null) \
        || return 1
    [[ -z "$unexpected" ]] || return 1
    cleanup_checkpoint probe_after_global_root_preflight
    private_dir_manifests=()
    if (( private_runtime_armed )); then
        ((${#private_dir_fds[@]} == 6 \
            && ${#private_dir_anchors[@]} == 6 \
            && ${#private_dir_identities[@]} == 6)) || return 1
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
        ! -name graphroot ! -name xdg-runtime ! -name xdg-config \
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
    if (( private_runtime_armed && writer_state_required )) && ! writer_is_quiesced; then
        cleanup_outcome=live_writer_cleanup_unproven
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
        case "$cleanup_outcome" in
            retained_drift) /usr/bin/printf 'gate_category=private_cleanup_retained\n' >&2 ;;
            live_writer_cleanup_unproven) /usr/bin/printf 'gate_category=live_writer_cleanup_unproven\n' >&2 ;;
            *) /usr/bin/printf 'gate_category=private_cleanup_sensitive\n' >&2 ;;
        esac
    else
        /usr/bin/printf 'gate_cleanup=retained_empty\n' >&2
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
private_root=$(/usr/bin/mktemp -d "$local_parent/k3-registry-direct-pull-v31.${SLURM_JOB_ID}.${SLURM_STEP_ID}.XXXXXX") \
    || blocked private_environment
[[ "$private_root" == "$local_parent"/k3-registry-direct-pull-v31."${SLURM_JOB_ID}"."${SLURM_STEP_ID}".* \
    && -d "$private_root" && ! -L "$private_root" ]] \
    || blocked private_environment
private_root_before=$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private_root" 2>/dev/null) \
    || blocked private_environment
[[ "$private_root_before" == *":700:${GATE_EXPECTED_UID}" \
    && "$(/usr/bin/stat -c '%h' -- "$private_root" 2>/dev/null)" == 2 ]] \
    || blocked private_environment
if ! { exec {private_root_fd}<"$private_root"; } 2>/dev/null; then
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
readonly xdg_runtime=$private_root/xdg-runtime
readonly runroot=$xdg_runtime/containers
readonly xdg_config=$private_root/xdg-config
readonly private_home=$private_root/home
readonly private_tmp=$private_root/tmp
readonly storage_conf=$private_root/storage.conf
readonly inspect_file=$private_root/inspect
readonly local_tls=$private_root/tls-combined.pem
/usr/bin/mkdir -m 700 -- "$graphroot" "$xdg_runtime" "$xdg_config" "$private_home" "$private_tmp" \
    || blocked private_environment
/usr/bin/mkdir -m 700 -- "$runroot" \
    || blocked private_environment
/usr/bin/printf '[storage]\ndriver = "overlay"\ngraphroot = "%s"\nrunroot = "%s"\nrootless_storage_path = "%s"\n' \
    "$graphroot" "$runroot" "$graphroot" > "$storage_conf" \
    || blocked private_environment
/usr/bin/chmod 600 "$storage_conf" || blocked private_environment
/usr/bin/touch "$local_tls" 2>/dev/null || blocked private_environment
/usr/bin/chmod 600 "$local_tls" 2>/dev/null || blocked private_environment
/usr/bin/touch "$inspect_file" 2>/dev/null || blocked private_environment
/usr/bin/chmod 600 "$inspect_file" 2>/dev/null || blocked private_environment
{ exec {storage_conf_fd}<>"$storage_conf"; } 2>/dev/null || blocked private_environment
storage_conf_identity=$(/usr/bin/stat -Lc '%d:%i' -- "/proc/self/fd/$storage_conf_fd") \
    || blocked private_environment
storage_conf_sha=$(/usr/bin/sha256sum -- "/proc/self/fd/$storage_conf_fd" | /usr/bin/cut -d' ' -f1) \
    || blocked private_environment
[[ "$storage_conf_sha" =~ ^[0-9a-f]{64}$ ]] || blocked private_environment
{ exec {local_tls_fd}<>"$local_tls"; } 2>/dev/null || blocked private_environment
# Arm the immutable TLS inode identity before the first byte is copied. Any
# signal/error after this point can scrub the exact retained descriptor even if
# the final mode/hash validation has not run yet.
local_tls_identity=$(/usr/bin/stat -Lc '%d:%i' -- "/proc/self/fd/$local_tls_fd") \
    || blocked private_environment
{ exec {inspect_fd}<>"$inspect_file"; } 2>/dev/null || blocked private_environment
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
xdg_runtime_fd=-1
xdg_config_fd=-1
xdg_data_fd=-1
private_home_fd=-1
private_tmp_fd=-1
if ! { exec {graphroot_fd}<"$graphroot" {xdg_runtime_fd}<"$xdg_runtime" \
    {xdg_config_fd}<"$xdg_config" \
    {xdg_data_fd}<"$XDG_DATA_HOME" {private_home_fd}<"$private_home" \
    {private_tmp_fd}<"$private_tmp"; } 2>/dev/null; then
    blocked private_environment
fi
private_dir_paths=("$graphroot" "$xdg_runtime" "$xdg_config" "$XDG_DATA_HOME" "$private_home" "$private_tmp")
private_dir_fds=("$graphroot_fd" "$xdg_runtime_fd" "$xdg_config_fd" "$xdg_data_fd" "$private_home_fd" "$private_tmp_fd")
for private_fd_value in "${private_dir_fds[@]}"; do
    private_dir_anchors+=("/proc/self/fd/${private_fd_value}/.")
    private_dir_identities+=("$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "/proc/self/fd/${private_fd_value}/." 2>/dev/null)")
done
unset private_fd_value
runroot_anchor=${private_dir_anchors[1]}/containers
runroot_identity=$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$runroot" 2>/dev/null) \
    || blocked private_environment
[[ "$runroot_identity" == "${private_root_identity%%:*}:"*":700:${GATE_EXPECTED_UID}" \
    && "$runroot_identity" == *":700:${GATE_EXPECTED_UID}" \
    && "$runroot_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$runroot_anchor" 2>/dev/null)" ]] \
    || blocked private_environment
readonly runroot_anchor runroot_identity
private_dirs_bound || blocked private_environment
readonly podman_guard_alias=$private_tmp/podman
/usr/bin/ln -s -- "/proc/self/fd/$podman_guard_fd" "$podman_guard_alias" 2>/dev/null \
    || blocked private_environment
podman_guard_alias_anchor=${private_dir_anchors[5]}/podman
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
export GATE_EXPECTED_GRAPHROOT=$graphroot
export GATE_EXPECTED_RUNROOT=$runroot
export GATE_EXPECTED_RUNROOT_ANCHOR=$runroot_anchor
export GATE_EXPECTED_RUNROOT_IDENTITY=$runroot_identity
export GATE_EXPECTED_XDG_RUNTIME=$xdg_runtime
export GATE_EXPECTED_XDG_DATA=$XDG_DATA_HOME
export GATE_EXPECTED_STORAGE_CONF=$storage_conf
export GATE_EXPECTED_STORAGE_CONF_IDENTITY=$storage_conf_identity
export GATE_EXPECTED_STORAGE_CONF_SHA256=$storage_conf_sha
export GATE_WRITER_STATE_FD=$inspect_fd
export GATE_WRITER_STATE_IDENTITY=${inspect_identity}:600:${GATE_EXPECTED_UID}:1
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
readonly GATE_EXPECTED_GRAPHROOT GATE_EXPECTED_RUNROOT GATE_EXPECTED_RUNROOT_ANCHOR
readonly GATE_EXPECTED_RUNROOT_IDENTITY GATE_EXPECTED_XDG_RUNTIME GATE_EXPECTED_XDG_DATA
readonly GATE_EXPECTED_STORAGE_CONF
readonly GATE_EXPECTED_STORAGE_CONF_IDENTITY GATE_EXPECTED_STORAGE_CONF_SHA256
readonly GATE_WRITER_STATE_FD GATE_WRITER_STATE_IDENTITY
export PATH=$private_tmp:/usr/bin:/bin
private_runtime_armed=1
set_writer_state quiesced || blocked private_environment
writer_state_required=1

private_dirs_bound || blocked private_environment
set_writer_state armed || blocked live_writer_cleanup_unproven
set +e
store=$(/usr/bin/timeout --signal=TERM --kill-after=3s 15s \
    /usr/bin/podman info --format '{{.Store.GraphRoot}}|{{.Store.RunRoot}}|{{.Store.GraphDriverName}}' \
    2>/dev/null)
store_rc=$?
set -e
set_writer_state quiesced || blocked live_writer_cleanup_unproven
(( store_rc == 0 )) || blocked podman_info_command
private_dirs_bound || blocked private_environment
IFS='|' read -r observed_graphroot observed_runroot observed_driver < <(/usr/bin/printf '%s\n' "$store") \
    || blocked podman_info_shape
[[ -n "$observed_graphroot" && -n "$observed_runroot" && -n "$observed_driver" \
    && "$store" == "$observed_graphroot|$observed_runroot|$observed_driver" ]] \
    || blocked podman_info_shape
[[ "$observed_graphroot" == "$graphroot" ]] || blocked podman_store_graphroot
[[ "$observed_runroot" == "$runroot" ]] || blocked podman_store_runroot
[[ "$observed_driver" == overlay ]] || blocked podman_store_driver
unset store store_rc observed_graphroot observed_runroot observed_driver
private_dirs_bound || blocked private_environment
set_writer_state armed || blocked live_writer_cleanup_unproven
set +e
/usr/bin/timeout --signal=TERM --kill-after=3s 15s \
    /usr/bin/podman image exists "$GATE_IMAGE" >/dev/null 2>&1
cold_exists_rc=$?
set -e
set_writer_state quiesced || blocked live_writer_cleanup_unproven
private_dirs_bound || blocked private_environment
case "$cold_exists_rc" in
    0) blocked podman_info_image_present ;;
    1) ;;
    *) blocked podman_info_image_check ;;
esac
unset cold_exists_rc
private_dirs_bound || blocked private_environment

# Source only the reviewed cleanup and auth-file helpers in a child shell. The
# gate below performs one mint, one offline lookup, and at most one guarded,
# digest-pinned pull. It never invokes a network login or a retry loop.
private_dirs_bound || blocked private_environment
(
    source /proc/self/fd/8 || blocked probe_source_identity
    source /proc/self/fd/9 || blocked probe_source_identity
    exec 7<&- 8<&- 9<&-
    exec {scrubber_fd}<&-

    abandon_live_writer() {
        local status=${1:-3}
        # Do not let the sourced credential cleanup mutate files that a child
        # may still have open.  The parent probe also sees the armed handshake
        # and retains the entire private tree for controller reconciliation.
        trap - EXIT HUP INT TERM
        _CONTAINER_REGISTRY_ACTIVE_PID=
        _CONTAINER_REGISTRY_SPAWNING=0
        builtin printf -- 'gate_category=live_writer_cleanup_unproven\n' >&2
        [[ "$status" =~ ^[1-9][0-9]*$ && "$status" -le 255 ]] || status=3
        exit "$status"
    }

    # Override the sourced handler while its cleanup traps are armed.  Waiting
    # for GNU timeout alone is insufficient evidence that a failed guard left
    # no Podman descendant.  The guard writes `quiesced` only after it reaps its
    # exact child; without that proof, retain auth, raw output, and storage.
    _container_registry_signal_exit() {
        local signal_name=$1 status=$2 active_pid=${_CONTAINER_REGISTRY_ACTIVE_PID:-}
        if (( _CONTAINER_REGISTRY_SPAWNING )) \
            && [[ -z "${_CONTAINER_REGISTRY_ACTIVE_PID:-}" ]]; then
            if [[ -z "${_CONTAINER_REGISTRY_PENDING_SIGNAL:-}" ]]; then
                _CONTAINER_REGISTRY_PENDING_SIGNAL=$signal_name
                _CONTAINER_REGISTRY_PENDING_STATUS=$status
            fi
            return 0
        fi
        trap - EXIT HUP INT TERM
        if [[ "$active_pid" =~ ^[1-9][0-9]*$ ]]; then
            if /usr/bin/kill -0 -- "$active_pid" 2>/dev/null; then
                /usr/bin/kill -TERM -- "$active_pid" 2>/dev/null || true
            fi
            wait "$active_pid" 2>/dev/null || true
        fi
        _CONTAINER_REGISTRY_ACTIVE_PID=
        _CONTAINER_REGISTRY_SPAWNING=0
        writer_is_quiesced || abandon_live_writer "$status"
        if ! _container_registry_cleanup; then
            builtin printf -- 'gate_category=private_cleanup_sensitive\n' >&2
        fi
        exit "$status"
    }

    classify_token() {
        local value=$1 decoded_prefix= length=${#1}
        if (( length == 0 )); then
            DIAG_TOKEN_SHAPE=empty
            DIAG_TOKEN_SIZE=none
            return
        elif (( length < 2048 )); then
            DIAG_TOKEN_SIZE=lt2k
        elif (( length < 4096 )); then
            DIAG_TOKEN_SIZE=b2k_4k
        elif (( length < 8192 )); then
            DIAG_TOKEN_SIZE=b4k_8k
        elif (( length <= 16384 )); then
            DIAG_TOKEN_SIZE=b8k_16k
        else
            DIAG_TOKEN_SIZE=gt16k
        fi
        if [[ "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
            DIAG_TOKEN_SHAPE=multiline
        elif [[ "$value" == \{* || "$value" == \[* ]]; then
            DIAG_TOKEN_SHAPE=json
        elif [[ "$value" == export\ * || "$value" == AWS_*=* ]]; then
            DIAG_TOKEN_SHAPE=env_export
        elif [[ "$value" == AWS:* ]]; then
            DIAG_TOKEN_SHAPE=literal_basic
        elif (( length < 2048 )); then
            DIAG_TOKEN_SHAPE=too_short
        elif (( length > 16384 )); then
            DIAG_TOKEN_SHAPE=too_long
        elif [[ ! "$value" =~ ^[A-Za-z0-9_+/-]+={0,2}$ ]]; then
            DIAG_TOKEN_SHAPE=bad_charset
        else
            decoded_prefix=$(builtin printf -- '%s' "$value" \
                | /usr/bin/base64 -d 2>/dev/null \
                | /usr/bin/cut -c1-4) || decoded_prefix=
            if [[ "$decoded_prefix" == AWS: ]]; then
                DIAG_TOKEN_SHAPE=encoded_basic
            else
                DIAG_TOKEN_SHAPE=valid_text
            fi
        fi
    }

    guard_stage() {
        local path=$1
        if /usr/bin/grep -Fqx 'gate_guard_stage=precondition' "$path" 2>/dev/null; then
            /usr/bin/printf precondition
        elif /usr/bin/grep -Fqx 'gate_guard_stage=postcondition' "$path" 2>/dev/null; then
            /usr/bin/printf postcondition
        elif /usr/bin/grep -Fqx 'gate_guard_stage=child' "$path" 2>/dev/null; then
            /usr/bin/printf child
        else
            /usr/bin/printf none
        fi
    }

    classify_pull() {
        local path=$1 rc=$2 why= status_re
        DIAG_GUARD_STAGE=$(guard_stage "$path")
        case "$DIAG_GUARD_STAGE" in
            precondition) DIAG_OUTCOME=guard_precondition; return ;;
            postcondition) DIAG_OUTCOME=guard_postcondition; return ;;
        esac
        why=$(<"$path")
        why=${why,,}
        if ! /usr/bin/grep -qEv '^(gate_guard_stage=child)?$' "$path" 2>/dev/null; then
            if (( rc == 125 )); then
                DIAG_OUTCOME=empty_125
            elif (( rc == 124 || rc == 137 )); then
                DIAG_OUTCOME=timeout
            else
                DIAG_OUTCOME=empty_other
            fi
            return
        fi
        if (( rc == 124 || rc == 137 )); then
            DIAG_OUTCOME=timeout
            return
        fi
        status_re='(status([[:space:]]*code)?|http(/[0-9.]+|[[:space:]]+status)?)[[:space:]]*[:=]?[[:space:]]*(400|401|403|404|4[0-9][0-9]|5[0-9][0-9])([^0-9]|$)'
        if [[ "$why" =~ $status_re ]]; then
            case "${BASH_REMATCH[4]}" in
                400) DIAG_OUTCOME=http_400 ;;
                401) DIAG_OUTCOME=http_401 ;;
                403) DIAG_OUTCOME=http_403 ;;
                404) DIAG_OUTCOME=http_404 ;;
                4*) DIAG_OUTCOME=http_other4xx ;;
                5*) DIAG_OUTCOME=http_5xx ;;
            esac
        elif [[ "$why" == *"authorization token"*"expired"* \
            || "$why" == *"reauthenticate"* || "$why" == *"token has expired"* ]]; then
            DIAG_OUTCOME=expired
        elif [[ "$why" == *"not authorized"* || "$why" == *"not authorised"* \
            || "$why" == *"unauthorized"* || "$why" == *"unauthorised"* ]]; then
            DIAG_OUTCOME=not_authorized
        elif [[ "$why" == *"denied"* || "$why" == *"forbidden"* \
            || "$why" == *"invalid username/password"* \
            || "$why" == *"credentials"*"not accepted"* ]]; then
            DIAG_OUTCOME=denied
        elif [[ "$why" == *"authentication required"* || "$why" == *"auth challenge"* \
            || "$why" == *"bearer realm"* || "$why" == *"no credentials"* ]]; then
            DIAG_OUTCOME=auth_challenge
        elif [[ "$why" == *"manifest unknown"* || "$why" == *"name unknown"* \
            || "$why" == *"repository does not exist"* || "$why" == *"image not known"* ]]; then
            DIAG_OUTCOME=image_missing
        elif [[ "$why" == *"no image found in manifest list"* \
            || "$why" == *"no matching manifest"* || "$why" == *"unsupported platform"* ]]; then
            DIAG_OUTCOME=platform
        elif [[ "$why" == *"digest mismatch"* || "$why" == *"checksum mismatch"* \
            || "$why" == *"invalid manifest"* ]]; then
            DIAG_OUTCOME=image_identity
        elif [[ "$why" == *"no space left"* || "$why" == *"overlay"* \
            || "$why" == *"storage"* || "$why" == *"unpack"* ]]; then
            DIAG_OUTCOME=storage
        elif [[ "$why" == *"auth.json"* || "$why" == *"credential file"* \
            || "$why" == *"storing credentials"* || "$why" == *"saving credentials"* \
            || "$why" == *"recorded"*"credentials"* ]]; then
            DIAG_OUTCOME=writeback
        elif [[ "$why" == *"registries.conf"* || "$why" == *"registry config"* \
            || "$why" == *"error parsing"* ]]; then
            DIAG_OUTCOME=config
        elif [[ "$why" == *"x509:"* || "$why" == *"certificate"* \
            || "$why" == *"tls"* || "$why" == *"ssl"* ]]; then
            DIAG_OUTCOME=tls
        elif [[ "$why" == *"proxy"* || "$why" == *"connect tunnel"* ]]; then
            DIAG_OUTCOME=proxy
        elif [[ "$why" == *"dial tcp"* || "$why" == *"lookup"* || "$why" == *"timeout"* \
            || "$why" == *"deadline exceeded"* || "$why" == *"connection"* \
            || "$why" == *"network"* || "$why" == *"no route"* || "$why" == *"eof"* ]]; then
            DIAG_OUTCOME=transport
        elif (( rc == 125 )) && [[ "$DIAG_GUARD_STAGE" == child ]]; then
            DIAG_OUTCOME=guard_child
        else
            DIAG_OUTCOME=unknown
        fi
    }

    diagnostic_pull_once() {
        local image=$1 host=${1%%/*} acct region token= encoded= auth_path= auth_seed_sha=
        local lookup_file= pull_file= lookup_size=0 pull_size=0 lookup_oversize=0
        local mint_rc=0 lookup_rc=0 lookup_user= pull_rc=0
        local image_rm_rc=0 image_exists_rc=0
        DIAG_OUTCOME=unknown
        DIAG_TOKEN_SHAPE=not_seen
        DIAG_TOKEN_SIZE=none
        DIAG_OFFLINE=not_run
        DIAG_GUARD_STAGE=not_run
        case "$host" in *.dkr.ecr.*.amazonaws.com) ;; *) DIAG_OUTCOME=config; return ;;
        esac
        acct=${host%%.*}
        region=${host#*.dkr.ecr.}
        region=${region%%.*}
        if token=$(/usr/bin/timeout --foreground --signal=TERM --kill-after=5s 30s \
            /usr/bin/ucloud ecr get-credentials --account "$acct" --region "$region" \
                --outform text 2>/dev/null); then
            mint_rc=0
        else
            mint_rc=$?
        fi
        classify_token "$token"
        if (( mint_rc != 0 )); then
            if (( mint_rc == 124 || mint_rc == 137 )); then
                DIAG_OUTCOME=mint_timeout
            else
                DIAG_OUTCOME=mint_broker
            fi
            unset token
            return
        elif [[ "$DIAG_TOKEN_SHAPE" == empty ]]; then
            DIAG_OUTCOME=mint_empty
            unset token
            return
        elif [[ "$DIAG_TOKEN_SHAPE" != valid_text ]]; then
            DIAG_OUTCOME=token_shape
            unset token
            return
        fi
        if ! auth_path=$(/usr/bin/mktemp "${XDG_RUNTIME_DIR}/serve-api-v2-registry-auth.XXXXXX" 2>/dev/null); then
            DIAG_OUTCOME=authfile_create
            unset token
            return
        fi
        _CONTAINER_REGISTRY_AUTH_PATH=$auth_path
        export REGISTRY_AUTH_FILE=$auth_path
        if ! /usr/bin/chmod 600 -- "$auth_path" 2>/dev/null \
            || ! _container_registry_validate_auth_file "$auth_path"; then
            DIAG_OUTCOME=authfile_create
            unset token
            return
        fi
        if ! { exec {auth_fd}<>"$auth_path"; } 2>/dev/null; then
            DIAG_OUTCOME=authfile_create
            unset token
            return
        fi
        auth_identity=$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$auth_path") \
            || { DIAG_OUTCOME=authfile_create; unset token; return; }
        if [[ "$auth_identity" != "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$auth_fd")" ]] \
            || ! encoded=$(builtin printf -- 'AWS:%s' "$token" | /usr/bin/base64 -w0) \
            || ! _container_registry_write_auth_file "$auth_path" "$host" "$encoded"; then
            DIAG_OUTCOME=authfile_create
            unset token encoded
            return
        fi
        auth_seed_sha=$(/usr/bin/sha256sum -- "$auth_path" | /usr/bin/cut -d' ' -f1) \
            || { DIAG_OUTCOME=authfile_create; unset token encoded; return; }
        export GATE_EXPECTED_AUTH_PATH=$auth_path
        export GATE_EXPECTED_REGISTRY_HOST=$host
        export GATE_EXPECTED_IMAGE=$image
        export GATE_EXPECTED_AUTH_IDENTITY=$auth_identity
        export GATE_EXPECTED_AUTH_SHA256=$auth_seed_sha
        readonly GATE_EXPECTED_AUTH_PATH GATE_EXPECTED_REGISTRY_HOST GATE_EXPECTED_IMAGE
        readonly GATE_EXPECTED_AUTH_IDENTITY GATE_EXPECTED_AUTH_SHA256

        if ! lookup_file=$(/usr/bin/mktemp "${TMPDIR}/registry-lookup.XXXXXX" 2>/dev/null); then
            DIAG_OUTCOME=authfile_lookup
            unset token encoded
            return
        fi
        _CONTAINER_REGISTRY_TMP_PATH=$lookup_file
        _container_registry_begin_spawn
        /usr/bin/timeout --signal=TERM --kill-after=5s 10s \
            podman login --authfile "$auth_path" --get-login "$host" \
            </dev/null >"$lookup_file" 2>&1 &
        _container_registry_publish_pid "$!"
        if wait "${_CONTAINER_REGISTRY_ACTIVE_PID}"; then lookup_rc=0; else lookup_rc=$?; fi
        _CONTAINER_REGISTRY_ACTIVE_PID=
        writer_is_quiesced || abandon_live_writer
        lookup_size=$(/usr/bin/stat -Lc '%s' -- "$lookup_file" 2>/dev/null || true)
        if [[ ! "$lookup_size" =~ ^[0-9]+$ ]] || (( lookup_size > 64 )); then
            lookup_oversize=1
            lookup_user=
        else
            lookup_user=$(<"$lookup_file")
        fi
        DIAG_GUARD_STAGE=$(guard_stage "$lookup_file")
        if ! _container_registry_clear_tmp; then
            DIAG_OUTCOME=authfile_lookup
            unset token encoded lookup_user
            return
        fi
        if (( lookup_oversize )); then
            DIAG_OFFLINE=failed
            DIAG_OUTCOME=authfile_lookup
            unset token encoded lookup_user
            return
        elif (( lookup_rc != 0 )); then
            DIAG_OFFLINE=failed
            case "$DIAG_GUARD_STAGE" in
                precondition) DIAG_OUTCOME=guard_precondition ;;
                postcondition) DIAG_OUTCOME=guard_postcondition ;;
                *) DIAG_OUTCOME=authfile_lookup ;;
            esac
            unset token encoded lookup_user
            return
        elif [[ "$lookup_user" != AWS ]]; then
            DIAG_OFFLINE=wrong_user
            DIAG_OUTCOME=authfile_lookup
            unset token encoded lookup_user
            return
        elif [[ "$auth_seed_sha" != "$(/usr/bin/sha256sum -- "$auth_path" 2>/dev/null \
            | /usr/bin/cut -d' ' -f1)" ]]; then
            DIAG_OFFLINE=failed
            DIAG_OUTCOME=writeback
            unset token encoded lookup_user
            return
        fi
        DIAG_OFFLINE=ok
        unset token encoded lookup_user

        if ! pull_file=$(/usr/bin/mktemp "${TMPDIR}/registry-pull.XXXXXX" 2>/dev/null); then
            DIAG_OUTCOME=unknown
            return
        fi
        _CONTAINER_REGISTRY_TMP_PATH=$pull_file
        _container_registry_begin_spawn
        /usr/bin/timeout --signal=TERM --kill-after=10s 300s \
            podman pull --authfile "$auth_path" --platform linux/arm64 \
                --tls-verify=true --quiet "$image" \
            </dev/null >"$pull_file" 2>&1 &
        _container_registry_publish_pid "$!"
        if wait "${_CONTAINER_REGISTRY_ACTIVE_PID}"; then pull_rc=0; else pull_rc=$?; fi
        _CONTAINER_REGISTRY_ACTIVE_PID=
        writer_is_quiesced || abandon_live_writer
        DIAG_GUARD_STAGE=$(guard_stage "$pull_file")
        if [[ "$auth_seed_sha" != "$(/usr/bin/sha256sum -- "$auth_path" 2>/dev/null \
            | /usr/bin/cut -d' ' -f1)" ]]; then
            DIAG_OUTCOME=writeback
        elif ! pull_size=$(/usr/bin/stat -Lc '%s' -- "$pull_file" 2>/dev/null) \
            || [[ ! "$pull_size" =~ ^[0-9]+$ ]] || (( pull_size > 1048576 )); then
            DIAG_OUTCOME=unknown
        elif (( pull_rc == 0 )); then
            set_writer_state armed || abandon_live_writer
            if /usr/bin/timeout --signal=TERM --kill-after=3s 15s \
                /usr/bin/podman image inspect \
                    --format '{{.Digest}}|{{.Os}}|{{.Architecture}}|{{join .RepoDigests ","}}' \
                    "$image" > "/proc/self/fd/$inspect_fd" 2>/dev/null \
                && IFS='|' read -r observed_digest observed_os observed_arch observed_repodigests \
                    < "/proc/self/fd/$inspect_fd" \
                && [[ "$(/usr/bin/grep -c '^' "/proc/self/fd/$inspect_fd" 2>/dev/null || true)" == 1 ]] \
                && image_identity_matches "$image" "$GATE_IMAGE_DIGEST" \
                    "$observed_digest" "$observed_os" "$observed_arch" \
                    "$observed_repodigests"; then
                DIAG_OUTCOME=success
            else
                DIAG_OUTCOME=image_identity
            fi
            set_writer_state quiesced || abandon_live_writer
            unset observed_digest observed_os observed_arch observed_repodigests
        else
            classify_pull "$pull_file" "$pull_rc"
        fi
        if ! _container_registry_clear_tmp; then
            DIAG_OUTCOME=writeback
        fi
        private_dirs_bound || blocked private_environment
        set_writer_state armed || abandon_live_writer
        if /usr/bin/timeout --signal=TERM --kill-after=5s 60s \
            /usr/bin/podman image rm --force "$image" >/dev/null 2>&1; then
            image_rm_rc=0
        else
            image_rm_rc=$?
        fi
        set_writer_state quiesced || abandon_live_writer
        private_dirs_bound || blocked private_environment
        set_writer_state armed || abandon_live_writer
        if /usr/bin/timeout --signal=TERM --kill-after=3s 15s \
            /usr/bin/podman image exists "$image" >/dev/null 2>&1; then
            image_exists_rc=0
        else
            image_exists_rc=$?
        fi
        set_writer_state quiesced || abandon_live_writer
        private_dirs_bound || blocked private_environment
        if (( image_exists_rc != 1 || (pull_rc == 0 && image_rm_rc != 0) )); then
            DIAG_OUTCOME=image_cleanup
        fi
        unset image_rm_rc image_exists_rc
        unset token encoded lookup_user
    }

    auth_fd=-1
    auth_identity=
    _container_registry_arm_cleanup
    private_dirs_bound || blocked private_environment
    diagnostic_pull_once "$GATE_IMAGE"
    private_dirs_bound || blocked private_environment
    auth_path=${_CONTAINER_REGISTRY_AUTH_PATH:-}
    if [[ -n "$auth_path" ]]; then
        [[ "$auth_path" == "$xdg_runtime"/serve-api-v2-registry-auth.* \
            && "$auth_fd" =~ ^[0-9]+$ && "$auth_fd" -ge 10 \
            && "$auth_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u:%h' -- "$auth_path")" \
            && "$auth_identity" == *":600:${GATE_EXPECTED_UID}:1" ]] \
            || blocked registry_pull
        [[ "$auth_identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "/proc/self/fd/$auth_fd")" ]] \
            || blocked registry_pull
    fi
    _container_registry_disarm_cleanup
    private_dirs_bound || blocked private_environment
    if (( auth_fd >= 0 )); then
        /usr/bin/timeout --signal=TERM --kill-after=1s 5s \
            /usr/bin/truncate -s 0 -- "/proc/self/fd/$auth_fd" 2>/dev/null \
            || blocked private_cleanup
        /usr/bin/timeout --signal=TERM --kill-after=1s 5s \
            /usr/bin/sync -f "/proc/self/fd/$auth_fd" 2>/dev/null \
            || blocked private_cleanup
        auth_after=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "/proc/self/fd/$auth_fd") \
            || blocked private_cleanup
        [[ ! -e "$auth_path" && ! -L "$auth_path" && -z "${REGISTRY_AUTH_FILE+x}" ]] \
            || blocked private_cleanup
        [[ "${auth_after%:*:*:*:*}" == "${auth_identity%:*:*:*}" \
            && "$auth_after" == *":600:${GATE_EXPECTED_UID}:0:0" ]] \
            || blocked private_cleanup
        exec {auth_fd}>&-
    else
        [[ -z "$auth_path" && -z "${REGISTRY_AUTH_FILE+x}" ]] || blocked private_cleanup
    fi
    if [[ "$DIAG_OUTCOME" != success ]]; then
        case "$DIAG_OUTCOME" in
            image_identity) safe_category=image_identity ;;
            image_cleanup) safe_category=image_remove ;;
            mint_broker|mint_timeout|mint_empty|token_shape|authfile_create|authfile_lookup|\
            guard_precondition|guard_child|guard_postcondition|http_400|http_401|http_403|\
            http_404|http_other4xx|http_5xx|expired|not_authorized|denied|auth_challenge|\
            config|writeback|tls|proxy|transport|timeout|image_missing|platform|storage|\
            empty_125|empty_other|unknown)
                safe_category=pull_${DIAG_OUTCOME}
                ;;
            *) safe_category=pull_unknown ;;
        esac
        /usr/bin/printf 'gate_category=%s\n' "$safe_category" >&2
        exit 2
    fi
)
private_dirs_bound || blocked private_cleanup
if ! leftover_auth=$(/usr/bin/find "${private_dir_anchors[1]}" -xdev \
    -name 'serve-api-v2-registry-auth.*' -print -quit); then
    blocked private_cleanup
fi
if [[ -n "$leftover_auth" ]]; then
    blocked private_cleanup
fi
unset leftover_auth

private_dirs_bound || blocked private_cleanup

if ! cleanup_private_tree; then
    if [[ "$cleanup_outcome" == retained_drift ]]; then
        blocked private_cleanup_retained
    fi
    blocked private_cleanup_sensitive
fi
/usr/bin/printf 'gate_cleanup=retained_empty\n' >&2
if [[ -n "$pending_signal" ]]; then
    exit "$pending_signal_status"
fi
trap - EXIT HUP INT TERM
/usr/bin/printf '{"category":"success","image_digest":"%s","kind":"k3-registry-direct-pull-gate-v31","platform":"linux/arm64","state":"complete"}\n' \
    "$GATE_IMAGE_DIGEST"
