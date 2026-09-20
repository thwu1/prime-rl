#!/usr/bin/bash -p
#SBATCH --job-name=k3-reg-auth-062100-v1
#SBATCH --partition=g3
#SBATCH --account=ram
#SBATCH --qos=g3_lowest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --gres=gpu:1
#SBATCH --time=00:10:00
#SBATCH --exclude=g3-136-221,g3-136-247,g3-136-251,g3-136-253
#SBATCH --no-requeue
#SBATCH --export=NONE
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/k3_registry_auth_probe_20260920t062100z_v1/slurm-%j.log

set +x
set -euo pipefail
umask 077
export PATH=/usr/bin:/bin
export HOME=/storage/home/tianhaowu
export USER=tianhaowu
export LOGNAME=tianhaowu
unset BASH_ENV ENV CDPATH GLOBIGNORE
unset LD_AUDIT LD_LIBRARY_PATH LD_PRELOAD
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP
[[ "$-" != *x* ]] || exit 2

readonly output_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/k3_registry_auth_probe_20260920t062100z_v1
readonly expected_job_name=k3-reg-auth-062100-v1
readonly dev_account=588845226011
readonly dev_region=us-east-2
readonly dev_host=588845226011.dkr.ecr.us-east-2.amazonaws.com
readonly prod_account=168653207203
readonly prod_region=us-east-2
readonly prod_host=168653207203.dkr.ecr.us-east-2.amazonaws.com

probe_dir=
token=
encoded=
why=
active_pid=
private_home=
private_runtime=
private_config=
private_docker=

cleanup() {
    local saved=$? item failed=0
    trap - EXIT HUP INT TERM
    unset token encoded why
    if [[ "${active_pid:-}" =~ ^[0-9]+$ ]] \
        && /usr/bin/kill -0 "$active_pid" 2>/dev/null; then
        /usr/bin/kill -TERM "$active_pid" 2>/dev/null || true
        wait "$active_pid" 2>/dev/null || true
    fi
    active_pid=
    if [[ -n "${probe_dir:-}" && -d "$probe_dir" && ! -L "$probe_dir" ]]; then
        /usr/bin/chmod u+w "$probe_dir" 2>/dev/null || failed=1
        for item in \
            auth-dev-env.json error-dev-env \
            auth-dev-explicit.json error-dev-explicit \
            auth-prod-env.json error-prod-env \
            auth-prod-explicit.json error-prod-explicit \
            fifo-dev-env fifo-dev-explicit fifo-prod-env fifo-prod-explicit \
            token-dev token-prod \
            home/.config/containers/auth.json home/.docker/config.json home/.dockercfg \
            runtime/containers/auth.json config/containers/auth.json \
            docker/config.json; do
            if [[ -f "$probe_dir/$item" && ! -L "$probe_dir/$item" \
                && ( "$item" == auth-* || "$item" == token-* \
                    || "$item" == */auth.json \
                    || "$item" == */config.json || "$item" == */.dockercfg ) \
                && "$(/usr/bin/stat -c '%u:%a:%h' -- "$probe_dir/$item" 2>/dev/null || true)" == 656177:600:1 ]]; then
                : > "$probe_dir/$item" 2>/dev/null || failed=1
            fi
            if [[ -e "$probe_dir/$item" || -L "$probe_dir/$item" ]]; then
                /usr/bin/unlink -- "$probe_dir/$item" 2>/dev/null || failed=1
            fi
        done
        for item in \
            home/.config/containers home/.config home/.docker home \
            runtime/containers runtime config/containers config docker; do
            if [[ -d "$probe_dir/$item" && ! -L "$probe_dir/$item" ]]; then
                /usr/bin/rmdir -- "$probe_dir/$item" 2>/dev/null || failed=1
            fi
        done
        /usr/bin/rmdir -- "$probe_dir" 2>/dev/null || failed=1
    fi
    if (( failed )); then
        /usr/bin/printf '{"category":"private_cleanup_failed","state":"blocked"}\n' >&2
        exit 3
    fi
    exit "$saved"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

blocked() {
    /usr/bin/printf '{"category":"%s","state":"blocked"}\n' "$1"
    exit 2
}

[[ "${SLURM_CLUSTER_NAME:-}" == fair-cw-use2-3 \
    && "${SLURM_JOB_NAME:-}" == "$expected_job_name" \
    && "${SLURM_JOB_PARTITION:-}" == g3 \
    && "${SLURM_JOB_ACCOUNT:-}" == ram \
    && "${SLURM_JOB_NUM_NODES:-}" == 1 \
    && "${SLURM_NTASKS:-}" == 1 \
    && "${SLURM_CPUS_PER_TASK:-}" == 4 \
    && "${SLURM_MEM_PER_NODE:-}" == 8192 \
    && "${SLURM_GPUS_ON_NODE:-}" == 1 \
    && "${SLURM_RESTART_COUNT:-0}" == 0 ]] \
    || blocked allocation_identity
observed_qos=${SLURM_JOB_QOS:-}
if [[ -z "$observed_qos" ]]; then
    observed_qos=$(/usr/bin/timeout --signal=TERM --kill-after=2s 10s \
        /usr/bin/squeue -h -j "$SLURM_JOB_ID" -o '%q' 2>/dev/null \
        | /usr/bin/tr -d '[:space:]') \
        || blocked allocation_qos_query
fi
[[ "$observed_qos" == g3_lowest ]] || blocked allocation_qos
unset observed_qos
for tls_name in THRIFT_TLS_CL_CERT_PATH THRIFT_TLS_CL_KEY_PATH; do
    tls_path=${!tls_name:-}
    [[ "$tls_path" == /* ]] || blocked credential_path
    tls_canonical=$(/usr/bin/readlink -f -- "$tls_path" 2>/dev/null) \
        || blocked credential_path
    [[ -n "$tls_canonical" \
        && "$(/usr/bin/stat -Lc '%F:%a:%u:%h:%s' -- "$tls_canonical" 2>/dev/null)" \
            == 'regular file:500:656177:1:5580' ]] \
        || blocked credential_identity
    printf -v "$tls_name" '%s' "$tls_canonical"
    export "$tls_name"
done
unset tls_name tls_path tls_canonical
[[ "${EXPECTED_PROBE_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] \
    || blocked expected_hash
[[ "$(/usr/bin/sha256sum -- "${BASH_SOURCE[0]}" | /usr/bin/cut -d' ' -f1)" \
    == "$EXPECTED_PROBE_SHA256" ]] \
    || blocked script_hash
[[ -x /usr/bin/ucloud && -x /usr/bin/podman && -x /usr/bin/timeout ]] \
    || blocked tool_identity
[[ -d "$output_root" && ! -L "$output_root" \
    && "$(/usr/bin/stat -c '%a:%u' -- "$output_root")" == 700:656177 ]] \
    || blocked output_root

# This mirrors the worker's direct-egress contract. Inherited loopback proxy
# variables are unusable from a compute node and must reach neither ucloud nor
# podman. No variable value is recorded.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
unset http_proxy https_proxy all_proxy no_proxy
unset REGISTRY_AUTH_FILE DOCKER_CONFIG
unset XDG_CONFIG_HOME XDG_DATA_HOME XDG_RUNTIME_DIR
unset CONTAINERS_CONF CONTAINERS_REGISTRIES_CONF CONTAINERS_STORAGE_CONF
unset _CONTAINERS_USERNS_CONFIGURED _CONTAINERS_ROOTLESS_UID _CONTAINERS_ROOTLESS_GID
unset CUDA_VISIBLE_DEVICES

probe_dir=$(/usr/bin/mktemp -d /tmp/k3-registry-auth-v1.XXXXXX) \
    || blocked temporary_directory
[[ -d "$probe_dir" && ! -L "$probe_dir" \
    && "$(/usr/bin/stat -c '%a:%u:%h' -- "$probe_dir")" == 700:656177:2 ]] \
    || blocked temporary_directory_identity

private_home=$probe_dir/home
private_runtime=$probe_dir/runtime
private_config=$probe_dir/config
private_docker=$probe_dir/docker
/usr/bin/mkdir -m 700 \
    "$private_home" "$private_home/.config" "$private_home/.config/containers" \
    "$private_home/.docker" "$private_runtime" "$private_runtime/containers" \
    "$private_config" "$private_config/containers" "$private_docker" \
    || blocked private_environment
for private_directory in \
    "$private_home" "$private_home/.config" "$private_home/.config/containers" \
    "$private_home/.docker" "$private_runtime" "$private_runtime/containers" \
    "$private_config" "$private_config/containers" "$private_docker"; do
    [[ "$(/usr/bin/stat -c '%a:%u' -- "$private_directory")" == 700:656177 ]] \
        || blocked private_environment_identity
done
printf '{}\n' > "$private_runtime/containers/auth.json"
printf '{}\n' > "$private_config/containers/auth.json"
printf '{}\n' > "$private_home/.config/containers/auth.json"
printf '{"credHelpers":{"%s":"k3-probe-missing","%s":"k3-probe-missing"}}\n' \
    "$dev_host" "$prod_host" > "$private_docker/config.json"
printf '{"credHelpers":{"%s":"k3-probe-missing","%s":"k3-probe-missing"}}\n' \
    "$dev_host" "$prod_host" > "$private_home/.docker/config.json"
for private_file in \
    "$private_runtime/containers/auth.json" \
    "$private_config/containers/auth.json" \
    "$private_home/.config/containers/auth.json" \
    "$private_docker/config.json" "$private_home/.docker/config.json"; do
    /usr/bin/chmod 600 "$private_file" || blocked private_environment_mode
    [[ "$(/usr/bin/stat -c '%a:%u:%h' -- "$private_file")" == 600:656177:1 ]] \
        || blocked private_environment_file_identity
done

classify_error() {
    local rc=$1 error_file=$2 lowered
    lowered=$(/usr/bin/tr '[:upper:]' '[:lower:]' < "$error_file") \
        || blocked diagnostic_read
    if (( rc == 0 )); then
        CLASS_RESULT=success
    elif (( rc == 127 )); then
        CLASS_RESULT=client_missing
    elif (( rc == 124 || rc == 137 )); then
        CLASS_RESULT=timeout
    elif [[ "$lowered" == *unauthorized* \
        || "$lowered" == *"authentication required"* \
        || "$lowered" == *"invalid username/password"* \
        || "$lowered" == *"invalid credentials"* ]]; then
        CLASS_RESULT=authentication
    elif [[ "$lowered" == *"access denied"* \
        || "$lowered" == *"requested access to the resource is denied"* \
        || "$lowered" == *insufficient_scope* \
        || "$lowered" == *forbidden* ]]; then
        CLASS_RESULT=authorization
    elif [[ "$lowered" == *"manifest unknown"* \
        || "$lowered" == *"name unknown"* \
        || "$lowered" == *"repository does not exist"* ]]; then
        CLASS_RESULT=image_missing
    elif [[ "$lowered" == *"certificate signed by unknown authority"* \
        || "$lowered" == *x509:* ]]; then
        CLASS_RESULT=certificate
    elif [[ "$lowered" == *"credential helper"* \
        || "$lowered" == *"executable file not found"* ]]; then
        CLASS_RESULT=credential_helper
    elif [[ "$lowered" == *"dial tcp: lookup"* \
        || "$lowered" == *"server misbehaving"* \
        || "$lowered" == *"temporary failure in name resolution"* \
        || "$lowered" == *"name or service not known"* \
        || "$lowered" == *"no such host"* ]]; then
        CLASS_RESULT=dns
    elif [[ "$lowered" == *"i/o timeout"* \
        || "$lowered" == *"tls handshake timeout"* \
        || "$lowered" == *"context deadline exceeded"* \
        || "$lowered" == *"connection timed out"* \
        || "$lowered" == *"operation timed out"* ]]; then
        CLASS_RESULT=timeout
    elif [[ "$lowered" == *"network is unreachable"* \
        || "$lowered" == *"no route to host"* \
        || "$lowered" == *"connection reset by peer"* \
        || "$lowered" == *"connection refused"* \
        || "$lowered" == *"connection aborted"* \
        || "$lowered" == *"connection closed"* \
        || "$lowered" == *"broken pipe"* ]]; then
        CLASS_RESULT=network
    elif [[ "$lowered" == *"permission denied"* \
        || "$lowered" == *"operation not permitted"* ]]; then
        CLASS_RESULT=local_permission
    else
        CLASS_RESULT=unclassified
    fi
    unset lowered
}

run_login() {
    local label=$1 host=$2 mode=$3
    local auth_file=$probe_dir/auth-$label-$mode.json
    local error_file=$probe_dir/error-$label-$mode
    local fifo=$probe_dir/fifo-$label-$mode
    local rc write_rc error_bytes error_sha

    printf '{"auths":{"%s":{"auth":"%s"}}}\n' "$host" "$encoded" \
        > "$auth_file" \
        || blocked auth_write
    /usr/bin/chmod 600 "$auth_file" || blocked auth_mode
    : > "$error_file"
    /usr/bin/chmod 600 "$error_file" || blocked error_mode
    /usr/bin/mkfifo -m 600 -- "$fifo" || blocked fifo_create
    [[ "$(/usr/bin/stat -c '%a:%u:%h' -- "$auth_file")" == 600:656177:1 \
        && "$(/usr/bin/stat -c '%a:%u:%h' -- "$error_file")" == 600:656177:1 \
        && "$(/usr/bin/stat -c '%a:%u:%h' -- "$fifo")" == 600:656177:1 ]] \
        || blocked private_file_identity

    set +e
    if [[ "$mode" == env ]]; then
        HOME="$private_home" XDG_RUNTIME_DIR="$private_runtime" \
            XDG_CONFIG_HOME="$private_config" DOCKER_CONFIG="$private_docker" \
            REGISTRY_AUTH_FILE="$auth_file" \
            /usr/bin/timeout --signal=TERM --kill-after=5s 30s \
            /usr/bin/podman login --username AWS --password-stdin "$host" \
            < "$fifo" >/dev/null 2>"$error_file" &
    else
        HOME="$private_home" XDG_RUNTIME_DIR="$private_runtime" \
            XDG_CONFIG_HOME="$private_config" DOCKER_CONFIG="$private_docker" \
            /usr/bin/timeout --signal=TERM --kill-after=5s 30s \
            /usr/bin/podman login --authfile "$auth_file" \
            --username AWS --password-stdin "$host" \
            < "$fifo" >/dev/null 2>"$error_file" &
    fi
    active_pid=$!
    printf '%s' "$token" > "$fifo"
    write_rc=$?
    wait "$active_pid"
    rc=$?
    active_pid=
    set -e
    (( write_rc == 0 )) || blocked credential_pipe

    classify_error "$rc" "$error_file"
    error_bytes=$(/usr/bin/stat -c '%s' -- "$error_file") \
        || blocked diagnostic_metadata
    error_sha=$(/usr/bin/sha256sum -- "$error_file" | /usr/bin/cut -d' ' -f1) \
        || blocked diagnostic_digest
    printf -v "${label}_${mode}_class" '%s' "$CLASS_RESULT"
    printf -v "${label}_${mode}_rc" '%s' "$rc"
    printf -v "${label}_${mode}_bytes" '%s' "$error_bytes"
    printf -v "${label}_${mode}_sha" '%s' "$error_sha"

    /usr/bin/unlink -- "$auth_file" "$error_file" "$fifo" \
        || blocked private_file_cleanup
    [[ ! -e "$auth_file" && ! -L "$auth_file" \
        && ! -e "$error_file" && ! -L "$error_file" \
        && ! -e "$fifo" && ! -L "$fifo" ]] \
        || blocked private_file_cleanup
}

probe_host() {
    local label=$1 account=$2 region=$3 host=$4 mint_rc
    local token_file=$probe_dir/token-$label
    : > "$token_file"
    /usr/bin/chmod 600 "$token_file" || blocked token_file_mode
    [[ "$(/usr/bin/stat -c '%a:%u:%h' -- "$token_file")" == 600:656177:1 ]] \
        || blocked token_file_identity
    set +e
    /usr/bin/timeout --signal=TERM --kill-after=5s 30s \
        /usr/bin/ucloud ecr get-credentials \
        --account "$account" --region "$region" \
        > "$token_file" 2>/dev/null &
    active_pid=$!
    wait "$active_pid"
    mint_rc=$?
    active_pid=
    set -e
    token=$(<"$token_file")
    if (( mint_rc != 0 )) || [[ -z "$token" ]]; then
        : > "$token_file" || blocked token_file_cleanup
        /usr/bin/unlink -- "$token_file" || blocked token_file_cleanup
        unset token
        printf -v "${label}_env_class" '%s' mint_failed
        printf -v "${label}_explicit_class" '%s' mint_failed
        printf -v "${label}_env_rc" '%s' "$mint_rc"
        printf -v "${label}_explicit_rc" '%s' "$mint_rc"
        printf -v "${label}_env_bytes" '%s' 0
        printf -v "${label}_explicit_bytes" '%s' 0
        printf -v "${label}_env_sha" '%s' none
        printf -v "${label}_explicit_sha" '%s' none
        return
    fi
    encoded=$(printf 'AWS:%s' "$token" | /usr/bin/base64 -w0) \
        || blocked credential_encoding
    : > "$token_file" || blocked token_file_cleanup
    /usr/bin/unlink -- "$token_file" || blocked token_file_cleanup
    run_login "$label" "$host" env
    run_login "$label" "$host" explicit
    unset token encoded
}

probe_host dev "$dev_account" "$dev_region" "$dev_host"
probe_host prod "$prod_account" "$prod_region" "$prod_host"

/usr/bin/unlink -- \
    "$private_runtime/containers/auth.json" \
    "$private_config/containers/auth.json" \
    "$private_home/.config/containers/auth.json" \
    "$private_docker/config.json" "$private_home/.docker/config.json" \
    || blocked private_environment_cleanup
for private_directory in \
    "$private_home/.config/containers" "$private_home/.config" \
    "$private_home/.docker" "$private_home" "$private_runtime/containers" \
    "$private_runtime" "$private_config/containers" "$private_config" \
    "$private_docker"; do
    /usr/bin/rmdir -- "$private_directory" || blocked private_environment_cleanup
done
private_home=
private_runtime=
private_config=
private_docker=
/usr/bin/rmdir -- "$probe_dir" || blocked temporary_directory_cleanup
probe_dir=
log_path=$output_root/slurm-${SLURM_JOB_ID}.log
/usr/bin/chmod 600 "$log_path" 2>/dev/null || blocked output_log_mode
[[ "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$log_path")" \
    == 'regular file:600:656177:1' ]] \
    || blocked output_log_identity

/usr/bin/printf '{"dev":{"env":{"bytes":%s,"category":"%s","rc":%s,"stderr_sha256":"%s"},"explicit":{"bytes":%s,"category":"%s","rc":%s,"stderr_sha256":"%s"}},"kind":"k3-registry-auth-probe-v1","prod":{"env":{"bytes":%s,"category":"%s","rc":%s,"stderr_sha256":"%s"},"explicit":{"bytes":%s,"category":"%s","rc":%s,"stderr_sha256":"%s"}},"proxy_environment":"scrubbed","pull_attempted":false,"state":"complete"}\n' \
    "$dev_env_bytes" "$dev_env_class" "$dev_env_rc" "$dev_env_sha" \
    "$dev_explicit_bytes" "$dev_explicit_class" "$dev_explicit_rc" "$dev_explicit_sha" \
    "$prod_env_bytes" "$prod_env_class" "$prod_env_rc" "$prod_env_sha" \
    "$prod_explicit_bytes" "$prod_explicit_class" "$prod_explicit_rc" "$prod_explicit_sha"
