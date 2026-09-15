#!/bin/bash
# traplib.sh — Signal-safe process lifecycle management library
#
# Source this file: . /app/traplib.sh
#
# Functions:
#   traplib_init              Set up signal handlers and internal state
#   traplib_push_handler      Register a cleanup command (LIFO order)
#   traplib_mktemp_dir        Create a managed temp directory
#   traplib_spawn_group       Launch a command in its own process group
#   traplib_wait_ready        Wait for readiness on a named pipe
#   traplib_wait_pid          Wait for a child process with timeout
#   traplib_run_exclusive     Run command under exclusive file lock
#   traplib_critical_section  Run command with deferred signal delivery
#   traplib_safe_pipe         Connect two commands via a monitored pipe
#   traplib_supervise         Supervise a command with restart on failure


declare -a _TRAPLIB_HANDLERS=()
declare -a _TRAPLIB_TMPDIRS=()
declare -a _TRAPLIB_PGROUPS=()
declare -a _TRAPLIB_DEFERRED_SIGNALS=()
_TRAPLIB_DIRS_REGISTRY=""
_TRAPLIB_SAVED_STATUS=0

_traplib_run_cleanup() {
    local sig="${1:-EXIT}"
    _TRAPLIB_SAVED_STATUS=$?

    local i
    for ((i=0; i<${#_TRAPLIB_HANDLERS[@]}; i++)); do
        eval "${_TRAPLIB_HANDLERS[$i]}"
    done

    local pgid
    for pgid in "${_TRAPLIB_PGROUPS[@]}"; do
        kill "$pgid" 2>/dev/null
    done

    local d
    for d in "${_TRAPLIB_TMPDIRS[@]}"; do
        [ -d "$d" ] && rm -rf "$d"
    done

    if [ "$sig" != "EXIT" ]; then
        local sig_num
        case "$sig" in
            TERM) sig_num=15 ;;
            INT)  sig_num=2 ;;
            HUP)  sig_num=1 ;;
            *)    sig_num=15 ;;
        esac
        exit $((128 + sig_num))
    fi
}

traplib_init() {
    _TRAPLIB_DIRS_REGISTRY=$(mktemp /tmp/traplib_reg.XXXXXX)
    trap '_traplib_run_cleanup EXIT' EXIT
    trap '_traplib_run_cleanup TERM' TERM
    trap '_traplib_run_cleanup INT' INT
    trap '_traplib_run_cleanup HUP' HUP
}

traplib_push_handler() {
    _TRAPLIB_HANDLERS+=("$1")
}

traplib_mktemp_dir() {
    local d
    d=$(mktemp -d "/tmp/traplib.XXXXXX") || return 1
    _TRAPLIB_TMPDIRS+=("$d")
    printf '%s\n' "$d"
}

traplib_spawn_group() {
    "$@" &
    local pid=$!
    _TRAPLIB_PGROUPS+=("$pid")
    printf '%s\n' "$pid"
}

traplib_wait_ready() {
    local fifo_path="$1"
    local timeout="${2:-10}"
    local result
    result=$(cat "$fifo_path")
    printf '%s\n' "$result"
}

traplib_wait_pid() {
    local pid="$1"
    local timeout="${2:-30}"
    sleep "$timeout" &
    local timer=$!
    wait "$timer" 2>/dev/null
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
}

traplib_run_exclusive() {
    local lockfile="$1"
    shift
    exec 9>"$lockfile"
    flock -s 9
    "$@"
    local rc=$?
    flock -u 9
    exec 9>&-
    return "$rc"
}

traplib_critical_section() {
    trap '' TERM INT HUP
    "$@"
    local rc=$?
    trap '_traplib_run_cleanup TERM' TERM
    trap '_traplib_run_cleanup INT' INT
    trap '_traplib_run_cleanup HUP' HUP
    return "$rc"
}

traplib_safe_pipe() {
    local src_cmd="$1"
    local sink_cmd="$2"
    local pipe_dir
    pipe_dir=$(mktemp -d "/tmp/traplib_pipe.XXXXXX")
    local pipe_path="$pipe_dir/fifo"
    mkfifo "$pipe_path"

    eval "$src_cmd" < /dev/null > "$pipe_path" &
    local src_pid=$!

    eval "$sink_cmd" < "$pipe_path" &
    local sink_pid=$!

    wait "$src_pid" 2>/dev/null
    local rc=$?

    rm -rf "$pipe_dir"
    return "$rc"
}

traplib_supervise() {
    local max_restarts="$1"
    shift
    local restart_count=0
    local child_pid

    while true; do
        "$@" &
        child_pid=$!

        wait "$child_pid" 2>/dev/null
        local exit_rc=$?

        [ "$exit_rc" -eq 0 ] && return 0

        restart_count=$((restart_count + 1))
        if [ "$restart_count" -ge "$max_restarts" ]; then
            return "$exit_rc"
        fi

        sleep 0.5
    done
}
