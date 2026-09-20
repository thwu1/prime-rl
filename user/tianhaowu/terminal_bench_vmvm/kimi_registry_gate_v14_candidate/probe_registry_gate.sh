#!/usr/bin/bash -p
set +x
set -euo pipefail
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
[[ "${GATE_SOURCE_ROOT:-}" == "$expected_source_root" \
    && "${GATE_SOURCE_REVISION:-}" == b1f0aa6c1aabcad9182d85a694faaa2eaa3d0f6e \
    && "${GATE_SOURCE_TREE:-}" == b205ec0f4e2f03f3b3cf5c9e7df7035a49df6772 \
    && "${GATE_IMAGE:-}" == "$expected_image" \
    && "${GATE_IMAGE_DIGEST:-}" == sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20 \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$worker")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$aws_creds")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/sha256sum -- "$worker" | /usr/bin/cut -d' ' -f1)" == "${GATE_WORKER_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- "$aws_creds" | /usr/bin/cut -d' ' -f1)" == "${GATE_AWS_CREDS_SHA256:-}" \
    && ( "$tools_manifest" == /var/slurm-tmp/k3-registry-pull-v14.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /var/slurm-tmp/*/k3-registry-pull-v14.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /tmp/k3-registry-pull-v14.batch.*.*/compute_tools.sha256 \
        || "$tools_manifest" == /tmp/*/k3-registry-pull-v14.batch.*.*/compute_tools.sha256 ) \
    && "$tools_manifest" != /proc/self/fd/* \
    && "$tools_manifest" == "$(/usr/bin/readlink -f -- "$tools_manifest" 2>/dev/null)" \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$tools_manifest")" == 'regular file:400:656177:1' \
    && "$(/usr/bin/sha256sum -- "$tools_manifest" | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" ]] \
    || blocked source_identity
worker_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$worker") || blocked source_identity
aws_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$aws_creds") || blocked source_identity
tools_before=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest") || blocked source_identity
if ! exec 9<"$worker" 8<"$aws_creds" 7<"$tools_manifest" 2>/dev/null; then
    blocked source_identity
fi
[[ "$worker_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/9)" \
    && "$worker_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$worker")" \
    && "$aws_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/8)" \
    && "$aws_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$aws_creds")" \
    && "$tools_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- /proc/self/fd/7)" \
    && "$tools_before" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h:%s' -- "$tools_manifest")" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/9 | /usr/bin/cut -d' ' -f1)" == "${GATE_WORKER_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/8 | /usr/bin/cut -d' ' -f1)" == "${GATE_AWS_CREDS_SHA256:-}" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/7 | /usr/bin/cut -d' ' -f1)" == "${GATE_TOOL_MANIFEST_SHA256:-}" ]] \
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
private_root_identity=
cleanup_complete=0
early_cleanup() {
    local saved=$?
    trap - EXIT HUP INT TERM
    if (( ! cleanup_complete )) \
        && [[ -n "${private_root:-}" \
        && "$private_root" == "$local_parent"/k3-registry-pull-v14."${SLURM_JOB_ID}"."${SLURM_STEP_ID}".* \
        && -d "$private_root" && ! -L "$private_root" \
        && ( -z "${private_root_identity:-}" \
            || "$private_root_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private_root" 2>/dev/null || true)" ) ]]; then
        /usr/bin/timeout --signal=TERM --kill-after=5s 30s \
            /usr/bin/find "$private_root" -xdev -user "${GATE_EXPECTED_UID}" \
                \( -type d -o \( -type f -links 1 \) \) \
                -exec /usr/bin/chmod u+rwx -- '{}' + 2>/dev/null || true
        /usr/bin/timeout --signal=TERM --kill-after=5s 60s \
            /usr/bin/find "$private_root" -xdev -type f -user "${GATE_EXPECTED_UID}" -links 1 \
                -exec /usr/bin/truncate -s 0 -- '{}' + 2>/dev/null || true
        /usr/bin/timeout --signal=TERM --kill-after=5s 120s \
            /usr/bin/rm -r -- "$private_root" 2>/dev/null || true
    fi
    exit "$saved"
}
trap early_cleanup EXIT
trap 'exit 130' HUP INT TERM
private_root=$(/usr/bin/mktemp -d "$local_parent/k3-registry-pull-v14.${SLURM_JOB_ID}.${SLURM_STEP_ID}.XXXXXX") \
    || blocked private_environment
private_root_identity=$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private_root" 2>/dev/null) \
    || blocked private_environment
[[ "$private_root" == "$local_parent"/k3-registry-pull-v14."${SLURM_JOB_ID}"."${SLURM_STEP_ID}".* \
    && -d "$private_root" && ! -L "$private_root" \
    && "$private_root_identity" == *":700:${GATE_EXPECTED_UID}" \
    && "$(/usr/bin/stat -c '%a:%u:%h' -- "$private_root" 2>/dev/null)" == "700:${GATE_EXPECTED_UID}:2" ]] \
    || blocked private_environment
readonly private_root private_root_identity
readonly graphroot=$private_root/graphroot
readonly runroot=$private_root/runroot
readonly xdg_runtime=$private_root/xdg-runtime
readonly xdg_config=$private_root/xdg-config
readonly private_home=$private_root/home
readonly storage_conf=$private_root/storage.conf
readonly inspect_file=$private_root/inspect
readonly local_tls=$private_root/tls-combined.pem
/usr/bin/mkdir -m 700 -- "$graphroot" "$runroot" "$xdg_runtime" "$xdg_config" "$private_home" \
    || blocked private_environment
/usr/bin/printf '[storage]\ndriver = "overlay"\ngraphroot = "%s"\nrunroot = "%s"\n' \
    "$graphroot" "$runroot" > "$storage_conf" \
    || blocked private_environment
/usr/bin/chmod 600 "$storage_conf" || blocked private_environment
/usr/bin/cp -- /proc/self/fd/4 "$local_tls" 2>/dev/null || blocked private_environment
/usr/bin/chmod 500 "$local_tls" 2>/dev/null || blocked private_environment
[[ "$(/usr/bin/stat -c '%a:%u:%h' -- "$storage_conf")" == "600:${GATE_EXPECTED_UID}:1" ]] \
    || blocked private_environment
[[ "$local_tls" == "$(/usr/bin/readlink -f -- "$local_tls" 2>/dev/null)" \
    && -f "$local_tls" && ! -L "$local_tls" \
    && "$(/usr/bin/stat -c '%a:%u:%h:%s' -- "$local_tls")" == "500:${GATE_EXPECTED_UID}:1:${GATE_TLS_SIZE}" \
    && "$(/usr/bin/sha256sum -- "$local_tls" | /usr/bin/cut -d' ' -f1)" == "${GATE_TLS_SHA256:-}" ]] \
    || blocked private_environment

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

cleanup_private_tree() {
    [[ "$private_root" == "$local_parent"/k3-registry-pull-v14."${SLURM_JOB_ID}"."${SLURM_STEP_ID}".* \
        && -d "$private_root" && ! -L "$private_root" \
        && "$private_root_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private_root" 2>/dev/null || true)" ]] \
        || return 1
    /usr/bin/timeout --signal=TERM --kill-after=5s 30s \
        /usr/bin/find "$private_root" -xdev -user "${GATE_EXPECTED_UID}" \
            \( -type d -o \( -type f -links 1 \) \) \
            -exec /usr/bin/chmod u+rwx -- '{}' + 2>/dev/null \
        || return 1
    /usr/bin/timeout --signal=TERM --kill-after=5s 60s \
        /usr/bin/find "$private_root" -xdev -type f -user "${GATE_EXPECTED_UID}" -links 1 \
            -exec /usr/bin/truncate -s 0 -- '{}' + 2>/dev/null \
        || return 1
    /usr/bin/timeout --signal=TERM --kill-after=5s 120s \
        /usr/bin/rm -r -- "$private_root" 2>/dev/null \
        || return 1
    [[ ! -e "$private_root" && ! -L "$private_root" ]]
}

cleanup() {
    local saved=$?
    trap - EXIT HUP INT TERM
    unset REGISTRY_AUTH_FILE DOCKER_CONFIG
    if (( ! cleanup_complete )) \
        && [[ -n "${private_root:-}" && "$private_root" == "$local_parent"/k3-registry-pull-v14."${SLURM_JOB_ID}"."${SLURM_STEP_ID}".* \
        && -d "$private_root" && ! -L "$private_root" \
        && "$private_root_identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$private_root" 2>/dev/null || true)" ]]; then
        /usr/bin/timeout --signal=TERM --kill-after=5s 30s \
            /usr/bin/find "$private_root" -xdev -user "${GATE_EXPECTED_UID}" \
                \( -type d -o \( -type f -links 1 \) \) \
                -exec /usr/bin/chmod u+rwx -- '{}' + 2>/dev/null || true
        /usr/bin/timeout --signal=TERM --kill-after=5s 60s \
            /usr/bin/find "$private_root" -xdev -type f -user "${GATE_EXPECTED_UID}" -links 1 \
                -exec /usr/bin/truncate -s 0 -- '{}' + 2>/dev/null || true
        /usr/bin/timeout --signal=TERM --kill-after=5s 120s \
            /usr/bin/rm -r -- "$private_root" 2>/dev/null || true
    fi
    exit "$saved"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

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

# Source only the reviewed registry functions in a child shell. Its hardened
# registry trap therefore cannot replace this probe's job-local cleanup trap.
# No worker main, model path, GPU enumeration, container construction, or
# podman run entry point is invoked.
(
    source /proc/self/fd/8 || blocked source_identity
    source /proc/self/fd/9 || blocked source_identity
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

if ! cleanup_private_tree; then
    blocked private_cleanup
fi
cleanup_complete=1
trap - EXIT HUP INT TERM
/usr/bin/printf '{"category":"success","image_digest":"%s","kind":"k3-registry-pull-gate-v14","platform":"linux/arm64","state":"complete"}\n' \
    "$GATE_IMAGE_DIGEST"
