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
    && "${SLURMD_NODENAME:-}" == g3-154-201 \
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
    && ( "$tools_manifest" == /var/slurm-tmp/k3-registry-pull-v20.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /var/slurm-tmp/*/k3-registry-pull-v20.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /tmp/k3-registry-pull-v20.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /tmp/*/k3-registry-pull-v20.batch.*.*/compute_tools.sha256 ) \
    && "$tools_manifest" != /proc/self/fd/* \
    && "$tools_manifest" == "$(/usr/bin/readlink -f -- "$tools_manifest" 2>/dev/null)" \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$tools_manifest")" == 'regular file:400:656177:1' \
    && "$(/usr/bin/sha256sum -- "$tools_manifest" | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" \
    && "$podman_guard" == /checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t122000z_v20/podman_guard.sh \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$podman_guard")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/sha256sum -- "$podman_guard" | /usr/bin/cut -d' ' -f1)" == "${GATE_PODMAN_GUARD_SHA256:-}" ]] \
    || blocked source_identity
worker_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$worker") || blocked source_identity
aws_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$aws_creds") || blocked source_identity
tools_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest") || blocked source_identity
guard_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$podman_guard") || blocked source_identity
podman_guard_fd=-1
if ! exec 9<"$worker" 8<"$aws_creds" 7<"$tools_manifest" {podman_guard_fd}<"$podman_guard" 2>/dev/null; then
    blocked source_identity
fi
[[ "$worker_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/9)" \
    && "$worker_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$worker")" \
    && "$aws_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/8)" \
    && "$aws_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$aws_creds")" \
    && "$tools_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/7)" \
    && "$tools_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest")" \
    && "$guard_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "/proc/self/fd/$podman_guard_fd")" \
    && "$guard_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$podman_guard")" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/9 | /usr/bin/cut -d' ' -f1)" == "${GATE_WORKER_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/8 | /usr/bin/cut -d' ' -f1)" == "${GATE_AWS_CREDS_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/7 | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- "/proc/self/fd/$podman_guard_fd" | /usr/bin/cut -d' ' -f1)" == "${GATE_PODMAN_GUARD_SHA256:-}" ]] \
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
private_dir_paths=()
private_dir_fds=()
private_dir_anchors=()
private_dir_identities=()
private_dir_manifests=()
storage_conf_fd=-1
storage_conf_identity=
local_tls_fd=-1
local_tls_identity=
inspect_fd=-1
inspect_identity=
cleanup_complete=0
cleanup_attempted=0
private_runtime_armed=0

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
            f|l) [[ "$links" == 1 ]] || return 1 ;;
            *) return 1 ;;
        esac
    done <<< "$records"
    manifest=$(/usr/bin/printf '%s' "$records" | /usr/bin/sha256sum | /usr/bin/cut -d' ' -f1) \
        || return 1
    [[ "$manifest" =~ ^[0-9a-f]{64}$ ]] || return 1
    /usr/bin/printf '%s\n' "$manifest"
}

scrub_anchored_directory() {
    local anchor=$1 identity=$2 expected_manifest=$3 observed_manifest leftover
    observed_manifest=$(preflight_anchored_directory "$anchor" "$identity") || return 1
    [[ "$observed_manifest" == "$expected_manifest" ]] || return 1
    /usr/bin/timeout --signal=TERM --kill-after=3s 10s \
        /usr/bin/find "$anchor" -xdev -mindepth 1 -uid "${GATE_EXPECTED_UID}" \
            \( -type d -o \( -type f -links 1 \) \) \
            -exec /usr/bin/chmod u+rwx -- '{}' + 2>/dev/null \
        || return 1
    /usr/bin/timeout --signal=TERM --kill-after=3s 15s \
        /usr/bin/find "$anchor" -xdev -mindepth 1 -type f \
            -uid "${GATE_EXPECTED_UID}" -links 1 \
            -exec /usr/bin/truncate -s 0 -- '{}' + 2>/dev/null \
        || return 1
    /usr/bin/timeout --signal=TERM --kill-after=5s 30s \
        /usr/bin/find "$anchor" -xdev -mindepth 1 -depth \
            \( \( -type d -o \( -type l -links 1 \) \) -uid "${GATE_EXPECTED_UID}" \
                -o -type f -uid "${GATE_EXPECTED_UID}" -links 1 \) -delete 2>/dev/null \
        || return 1
    leftover=$(/usr/bin/timeout --signal=TERM --kill-after=1s 3s \
        /usr/bin/find "$anchor" -xdev -mindepth 1 -print -quit 2>/dev/null) \
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
        && "$observed" == "${expected_dev_inode}:${GATE_EXPECTED_UID}:1" ]]
}

scrub_exact_probe_file() {
    local fd=$1 expected_dev_inode=$2
    preflight_exact_probe_file "$fd" "$expected_dev_inode" || return 1
    /usr/bin/timeout --signal=TERM --kill-after=1s 2s \
        /usr/bin/chmod 600 -- "/proc/self/fd/$fd" 2>/dev/null || return 1
    /usr/bin/timeout --signal=TERM --kill-after=1s 5s \
        /usr/bin/truncate -s 0 -- "/proc/self/fd/$fd" 2>/dev/null || return 1
    [[ -f "/proc/self/fd/$fd" \
        && "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "/proc/self/fd/$fd" 2>/dev/null)" \
            == "${expected_dev_inode}:600:${GATE_EXPECTED_UID}:1:0" ]]
}

close_probe_private_fds() {
    local index fd
    for index in "${!private_dir_fds[@]}"; do
        fd=${private_dir_fds[$index]}
        if [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 ]]; then
            exec {fd}<&- || true
        fi
    done
    private_dir_fds=()
    for fd in "$storage_conf_fd" "$local_tls_fd" "$inspect_fd"; do
        if [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 ]]; then
            exec {fd}>&- || true
        fi
    done
    storage_conf_fd=-1
    local_tls_fd=-1
    inspect_fd=-1
    if [[ "$podman_guard_fd" =~ ^[0-9]+$ && "$podman_guard_fd" -ge 10 ]]; then
        exec {podman_guard_fd}<&- || true
        podman_guard_fd=-1
    fi
    if [[ "$private_root_fd" =~ ^[0-9]+$ && "$private_root_fd" -ge 10 ]]; then
        exec {private_root_fd}<&- || true
        private_root_fd=-1
    fi
}

scrub_private_contents() {
    local index pid fd identity manifest preflight_output result=0
    local named_now anchored_after unexpected storage_named tls_named inspect_named
    local pids=()
    private_root_bound || return 1

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
    for fd in "$storage_conf_fd" "$local_tls_fd" "$inspect_fd"; do
        case "$fd" in
            "$storage_conf_fd") identity=$storage_conf_identity ;;
            "$local_tls_fd") identity=$local_tls_identity ;;
            "$inspect_fd") identity=$inspect_identity ;;
            *) return 1 ;;
        esac
        if [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 ]]; then
            preflight_exact_probe_file "$fd" "$identity" || return 1
        elif [[ "$fd" != -1 || -n "$identity" ]]; then
            return 1
        fi
    done

    # All targets passed the global phase. Run the independent anchored scrubs
    # concurrently so the signal bound is the slowest scrub, not their sum.
    if (( private_runtime_armed )); then
        for index in "${!private_dir_anchors[@]}"; do
            scrub_anchored_directory "${private_dir_anchors[$index]}" \
                "${private_dir_identities[$index]}" "${private_dir_manifests[$index]}" &
            pids+=("$!")
        done
    fi
    for fd in "$storage_conf_fd" "$local_tls_fd" "$inspect_fd"; do
        case "$fd" in
            "$storage_conf_fd") identity=$storage_conf_identity ;;
            "$local_tls_fd") identity=$local_tls_identity ;;
            "$inspect_fd") identity=$inspect_identity ;;
            *) return 1 ;;
        esac
        if [[ "$fd" =~ ^[0-9]+$ && "$fd" -ge 10 ]]; then
            scrub_exact_probe_file "$fd" "$identity" &
            pids+=("$!")
        fi
    done
    for pid in "${pids[@]}"; do
        wait "$pid" || result=1
    done
    # Never remove the main or top-level directory names. The children are
    # verified empty and the main root contains only those children plus three
    # zero-length bound files, eliminating stat-to-rmdir replacement races.
    if (( private_runtime_armed )); then
        private_dirs_bound || result=1
    else
        result=1
    fi
    named_now=$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private_root" 2>/dev/null || true)
    anchored_after=$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$private_root_anchor" 2>/dev/null || true)
    [[ "$named_now" == "$private_root_identity" && "$anchored_after" == "$private_root_identity" ]] \
        || result=1
    storage_named=$(/usr/bin/stat -c '%d:%i:%a:%u:%h:%s' -- "$storage_conf" 2>/dev/null || true)
    tls_named=$(/usr/bin/stat -c '%d:%i:%a:%u:%h:%s' -- "$local_tls" 2>/dev/null || true)
    inspect_named=$(/usr/bin/stat -c '%d:%i:%a:%u:%h:%s' -- "$inspect_file" 2>/dev/null || true)
    [[ "$storage_named" == "${storage_conf_identity}:600:${GATE_EXPECTED_UID}:1:0" \
        && "$tls_named" == "${local_tls_identity}:600:${GATE_EXPECTED_UID}:1:0" \
        && "$inspect_named" == "${inspect_identity}:600:${GATE_EXPECTED_UID}:1:0" ]] \
        || result=1
    unexpected=$(/usr/bin/timeout --signal=TERM --kill-after=1s 3s \
        /usr/bin/find "$private_root_anchor" -xdev -mindepth 1 -maxdepth 1 \
        ! -name graphroot ! -name runroot ! -name xdg-runtime ! -name xdg-config \
        ! -name xdg-data ! -name home ! -name tmp ! -name storage.conf \
        ! -name tls-combined.pem ! -name inspect -print -quit 2>/dev/null) \
        || result=1
    [[ -z "$unexpected" ]] || result=1
    (( result == 0 ))
}

retain_private_root() {
    local result=0
    cleanup_attempted=1
    scrub_private_contents || result=1
    close_probe_private_fds
    (( result == 0 ))
}

early_cleanup() {
    local saved=$?
    trap - EXIT HUP INT TERM
    if (( ! cleanup_complete && ! cleanup_attempted )) \
        && [[ "$private_root_fd" =~ ^[0-9]+$ && "$private_root_fd" -ge 10 ]]; then
        retain_private_root >/dev/null 2>&1 || true
    fi
    close_probe_private_fds
    exit "$saved"
}
trap early_cleanup EXIT
trap 'exit 130' HUP INT TERM
private_root=$(/usr/bin/mktemp -d "$local_parent/k3-registry-pull-v20.${SLURM_JOB_ID}.${SLURM_STEP_ID}.XXXXXX") \
    || blocked private_environment
[[ "$private_root" == "$local_parent"/k3-registry-pull-v20."${SLURM_JOB_ID}"."${SLURM_STEP_ID}".* \
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
[[ -L "$podman_guard_alias" \
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

cleanup_private_tree() {
    retain_private_root
}

cleanup() {
    local saved=$?
    trap - EXIT HUP INT TERM
    unset REGISTRY_AUTH_FILE DOCKER_CONFIG
    if (( ! cleanup_complete && ! cleanup_attempted )) \
        && [[ "$private_root_fd" =~ ^[0-9]+$ && "$private_root_fd" -ge 10 ]]; then
        retain_private_root >/dev/null 2>&1 || true
    fi
    close_probe_private_fds
    exit "$saved"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

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
    source /proc/self/fd/8 || blocked source_identity
    source /proc/self/fd/9 || blocked source_identity
    exec 7<&- 8<&- 9<&-
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
    blocked private_cleanup
fi
cleanup_complete=1
trap - EXIT HUP INT TERM
/usr/bin/printf '{"category":"success","image_digest":"%s","kind":"k3-registry-pull-gate-v20","platform":"linux/arm64","state":"complete"}\n' \
    "$GATE_IMAGE_DIGEST"
