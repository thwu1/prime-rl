#!/usr/bin/bash -p
set +x
set -euo pipefail

private_dirs_bound() {
    local index path_name anchor_name identity_name path anchor identity
    [[ "${GATE_PRIVATE_ROOT_PATH:-}" == /* \
        && "${GATE_PRIVATE_ROOT_ANCHOR:-}" =~ ^/proc/self/fd/[1-9][0-9]*/\.$ \
        && -d "$GATE_PRIVATE_ROOT_PATH" && ! -L "$GATE_PRIVATE_ROOT_PATH" \
        && -d "$GATE_PRIVATE_ROOT_ANCHOR" && ! -L "$GATE_PRIVATE_ROOT_ANCHOR" \
        && "${GATE_PRIVATE_ROOT_IDENTITY:-}" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$GATE_PRIVATE_ROOT_PATH" 2>/dev/null || true)" \
        && "$GATE_PRIVATE_ROOT_IDENTITY" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$GATE_PRIVATE_ROOT_ANCHOR" 2>/dev/null || true)" ]] \
        || return 1
    for index in 0 1 2 3 4 5; do
        path_name=GATE_PRIVATE_PATH_$index
        anchor_name=GATE_PRIVATE_ANCHOR_$index
        identity_name=GATE_PRIVATE_IDENTITY_$index
        path=${!path_name:-}
        anchor=${!anchor_name:-}
        identity=${!identity_name:-}
        [[ "$path" == "$GATE_PRIVATE_ROOT_PATH"/* \
            && "$anchor" =~ ^/proc/self/fd/[1-9][0-9]*/\.$ \
            && -d "$path" && ! -L "$path" \
            && -d "$anchor" && ! -L "$anchor" \
            && "$identity" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$path" 2>/dev/null || true)" \
            && "$identity" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$anchor" 2>/dev/null || true)" ]] \
            || return 1
    done
    [[ "${GATE_EXPECTED_GRAPHROOT:-}" == "${GATE_PRIVATE_PATH_0:-}" \
        && "${GATE_EXPECTED_XDG_RUNTIME:-}" == "${GATE_PRIVATE_PATH_1:-}" \
        && "${GATE_EXPECTED_XDG_DATA:-}" == "${GATE_PRIVATE_PATH_3:-}" \
        && "${GATE_EXPECTED_RUNROOT:-}" == "${GATE_EXPECTED_XDG_RUNTIME:-}/containers" \
        && "${GATE_EXPECTED_RUNROOT_ANCHOR:-}" == "${GATE_PRIVATE_ANCHOR_1:-}/containers" \
        && -d "${GATE_EXPECTED_RUNROOT:-}" && ! -L "${GATE_EXPECTED_RUNROOT:-}" \
        && -d "${GATE_EXPECTED_RUNROOT_ANCHOR:-}" && ! -L "${GATE_EXPECTED_RUNROOT_ANCHOR:-}" \
        && "${GATE_EXPECTED_RUNROOT_IDENTITY:-}" == "$(/usr/bin/stat -c '%d:%i:%a:%u' -- "$GATE_EXPECTED_RUNROOT" 2>/dev/null || true)" \
        && "$GATE_EXPECTED_RUNROOT_IDENTITY" == "$(/usr/bin/stat -Lc '%d:%i:%a:%u' -- "$GATE_EXPECTED_RUNROOT_ANCHOR" 2>/dev/null || true)" \
        && "${CONTAINERS_STORAGE_CONF:-}" == "${GATE_EXPECTED_STORAGE_CONF:-}" \
        && "$CONTAINERS_STORAGE_CONF" == "$GATE_PRIVATE_ROOT_PATH/storage.conf" \
        && "$CONTAINERS_STORAGE_CONF" == "$(/usr/bin/readlink -f -- "$CONTAINERS_STORAGE_CONF" 2>/dev/null || true)" \
        && "${GATE_EXPECTED_STORAGE_CONF_IDENTITY:-}" == "$(/usr/bin/stat -c '%d:%i' -- "$CONTAINERS_STORAGE_CONF" 2>/dev/null || true)" \
        && "$(/usr/bin/stat -c '%a:%u:%h' -- "$CONTAINERS_STORAGE_CONF" 2>/dev/null || true)" == "600:${GATE_EXPECTED_UID}:1" \
        && "$(/usr/bin/sha256sum -- "$CONTAINERS_STORAGE_CONF" 2>/dev/null | /usr/bin/cut -d' ' -f1)" == "${GATE_EXPECTED_STORAGE_CONF_SHA256:-}" \
        && "${XDG_RUNTIME_DIR:-}" == "${GATE_EXPECTED_XDG_RUNTIME:-}" \
        && "${XDG_CONFIG_HOME:-}" == "${GATE_PRIVATE_PATH_2:-}" \
        && "${XDG_DATA_HOME:-}" == "${GATE_EXPECTED_XDG_DATA:-}" \
        && "${HOME:-}" == "${GATE_PRIVATE_PATH_4:-}" \
        && "${TMPDIR:-}" == "${GATE_PRIVATE_PATH_5:-}" \
        && "${PATH:-}" == "${GATE_PRIVATE_PATH_5:-}:/usr/bin:/bin" \
        && -z "${STORAGE_DRIVER+x}" && -z "${STORAGE_OPTS+x}" ]] \
        || return 1
}

guard_fail() {
    case "${1:-}" in
        precondition|child|postcondition) ;;
        *) return 125 ;;
    esac
    /usr/bin/printf '\ngate_guard_stage=%s\n' "$1" >&2
    exit 125
}

auth_path_bound() {
    [[ "${GATE_EXPECTED_AUTH_PATH:-}" == "${GATE_EXPECTED_XDG_RUNTIME:-}"/serve-api-v2-registry-auth.* \
        && "$GATE_EXPECTED_AUTH_PATH" == "${REGISTRY_AUTH_FILE:-}" \
        && "$GATE_EXPECTED_AUTH_PATH" == "$(/usr/bin/readlink -f -- "$GATE_EXPECTED_AUTH_PATH" 2>/dev/null || true)" \
        && "$(/usr/bin/stat -c '%F:%a:%u:%h' -- "$GATE_EXPECTED_AUTH_PATH" 2>/dev/null || true)" \
            == "regular file:600:${GATE_EXPECTED_UID}:1" ]]
}

valid_login_call=0
if [[ $# == 5 && "$1" == login && "$2" == --authfile \
    && "$3" == "${GATE_EXPECTED_AUTH_PATH:-}" && "$4" == --get-login \
    && "$5" == "${GATE_EXPECTED_REGISTRY_HOST:-}" \
    && "$3" == "${REGISTRY_AUTH_FILE:-}" \
    && "$(/usr/bin/readlink -f -- /proc/self/fd/0 2>/dev/null || true)" == /dev/null ]]; then
    valid_login_call=1
elif [[ $# == 7 && "$1" == login && "$2" == --authfile \
    && "$3" == "${GATE_EXPECTED_AUTH_PATH:-}" && "$4" == --username && "$5" == AWS \
    && "$6" == --password-stdin && "$7" == "${GATE_EXPECTED_REGISTRY_HOST:-}" \
    && "$3" == "${REGISTRY_AUTH_FILE:-}" && -p /proc/self/fd/0 ]]; then
    valid_login_call=1
fi
[[ $valid_login_call == 1 \
    && "${BASH_SOURCE[0]}" == "${GATE_PODMAN_GUARD_ALIAS:-}" \
    && -L "${BASH_SOURCE[0]}" \
    && "$(/usr/bin/readlink -- "${BASH_SOURCE[0]}" 2>/dev/null)" \
        == "/proc/self/fd/${GATE_PODMAN_GUARD_FD:-invalid}" ]] \
    || guard_fail precondition
unset valid_login_call
guard_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "${BASH_SOURCE[0]}" 2>/dev/null) \
    || guard_fail precondition
[[ "$guard_identity" == "${GATE_PODMAN_GUARD_IDENTITY:-}" \
    && "$guard_identity" == *':500:656177:1' \
    && "${GATE_EXPECTED_REGISTRY_HOST:-}" == *.dkr.ecr.*.amazonaws.com \
    && -z "${HTTP_PROXY+x}" && -z "${HTTPS_PROXY+x}" && -z "${ALL_PROXY+x}" \
    && -z "${http_proxy+x}" && -z "${https_proxy+x}" && -z "${all_proxy+x}" \
    && -z "${CONTAINERS_REGISTRIES_CONF+x}" \
    && -z "${CONTAINERS_REGISTRIES_CONF_DIR+x}" && -z "${REGISTRIES_CONFIG_PATH+x}" \
    && "$(/usr/bin/sha256sum -- "${BASH_SOURCE[0]}" 2>/dev/null | /usr/bin/cut -d' ' -f1)" \
        == "${GATE_PODMAN_GUARD_SHA256:-}" \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- /usr/bin/podman 2>/dev/null)" == 'regular file:755:0:1' \
    && "$(/usr/bin/sha256sum -- /usr/bin/podman 2>/dev/null | /usr/bin/cut -d' ' -f1)" \
        == f93ee492920150e229b9b41729bfe675073a4df0569ee5d570a8106b5a64506a ]] \
    || guard_fail precondition
private_dirs_bound && auth_path_bound || guard_fail precondition

active_pid=
active_identity=
pending_signal=0
spawning=0
forward_signal() {
    local number=$1
    pending_signal=$number
    if (( ! spawning )) && [[ "${active_pid:-}" =~ ^[1-9][0-9]*$ ]]; then
        /usr/bin/kill -TERM -- "$active_pid" 2>/dev/null || true
    fi
}
process_identity() {
    local child=$1 raw rest owner
    local -a fields=()
    [[ "$child" =~ ^[1-9][0-9]*$ ]] || return 1
    IFS= read -r raw < "/proc/$child/stat" || return 1
    rest=${raw##*) }
    read -r -a fields <<< "$rest"
    ((${#fields[@]} >= 20)) || return 1
    owner=$(/usr/bin/stat -Lc '%u' -- "/proc/$child" 2>/dev/null) || return 1
    [[ "${fields[1]}" == "$$" && "$owner" == "${GATE_EXPECTED_UID}" ]] || return 1
    /usr/bin/printf '%s:%s:%s:%s\n' "$child" "${fields[1]}" "${fields[19]}" "$owner"
}
stop_and_reap_child() {
    local child=$1 identity=$2 current watchdog=
    [[ "$child" =~ ^[1-9][0-9]*$ ]] || return 1
    if ! /usr/bin/kill -0 -- "$child" 2>/dev/null; then
        wait "$child" 2>/dev/null || true
        return 0
    fi
    current=$(process_identity "$child") || return 1
    [[ -z "$identity" || "$identity" == "$current" ]] || return 1
    identity=$current
    /usr/bin/kill -TERM -- "$child" 2>/dev/null || true
    (
        /usr/bin/sleep 2
        if [[ "$identity" == "$(process_identity "$child" 2>/dev/null || true)" ]]; then
            /usr/bin/kill -KILL -- "$child" 2>/dev/null || true
        fi
    ) &
    watchdog=$!
    set +e
    wait "$child" 2>/dev/null
    set -e
    /usr/bin/kill -KILL -- "$watchdog" 2>/dev/null || true
    wait "$watchdog" 2>/dev/null || true
    ! /usr/bin/kill -0 -- "$child" 2>/dev/null
}
trap 'forward_signal 129' HUP
trap 'forward_signal 130' INT
trap 'forward_signal 143' TERM

set +e
spawning=1
/usr/bin/podman "$@" &
active_pid=$!
active_identity=$(process_identity "$active_pid" 2>/dev/null || true)
spawning=0
if (( pending_signal != 0 )); then
    trap '' HUP INT TERM
    stop_and_reap_child "$active_pid" "$active_identity" || guard_fail child
    rc=$pending_signal
else
    wait "$active_pid"
    rc=$?
    trap '' HUP INT TERM
    if (( pending_signal != 0 )); then
        stop_and_reap_child "$active_pid" "$active_identity" || guard_fail child
        rc=$pending_signal
    fi
fi
active_pid=
active_identity=
set -e
private_dirs_bound && auth_path_bound || guard_fail postcondition
if (( rc != 0 )); then
    /usr/bin/printf '\ngate_guard_stage=child\n' >&2
fi
exit "$rc"
