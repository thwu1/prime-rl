#!/bin/bash

cat > /app/traplib.sh << 'TRAPLIB_EOF'
#!/bin/bash
# traplib.sh — Signal-safe process lifecycle management library
#
# Source this file: . /app/traplib.sh


declare -a _TRAPLIB_HANDLERS=()
declare -a _TRAPLIB_PGROUPS=()
declare -a _TRAPLIB_DEFERRED_SIGNALS=()
_TRAPLIB_DIRS_REGISTRY=""
_TRAPLIB_CLEANED=0
_TRAPLIB_SAVED_STATUS=0

_traplib_run_cleanup() {
    # FIX 1: capture $? BEFORE local declaration clobbers it
    _TRAPLIB_SAVED_STATUS=$?
    local sig="${1:-EXIT}"

    # FIX 2: idempotency guard — prevent double cleanup from signal+EXIT cascade
    if [ "$_TRAPLIB_CLEANED" -eq 1 ]; then
        if [ "$sig" != "EXIT" ]; then
            trap - "$sig"
            kill -s "$sig" $$
        fi
        return
    fi
    _TRAPLIB_CLEANED=1

    # FIX 3: disarm EXIT trap to prevent re-fire after signal cleanup
    trap - EXIT

    # FIX 13: disable errexit during cleanup so failing handlers don't abort
    local _traplib_oldopts
    _traplib_oldopts=$(set +o)
    set +e

    # FIX 5: reverse iteration for LIFO handler order
    local i
    for ((i=${#_TRAPLIB_HANDLERS[@]}-1; i>=0; i--)); do
        eval "${_TRAPLIB_HANDLERS[$i]}"
    done

    # FIX 8: kill process groups with negative PGID, with individual PID fallback
    # and SIGKILL escalation for stubborn processes
    local pgid
    for pgid in "${_TRAPLIB_PGROUPS[@]}"; do
        kill -- -"$pgid" 2>/dev/null
        kill "$pgid" 2>/dev/null
    done
    sleep 0.1
    for pgid in "${_TRAPLIB_PGROUPS[@]}"; do
        kill -9 -- -"$pgid" 2>/dev/null
        kill -9 "$pgid" 2>/dev/null
    done

    # FIX 6: read from file-based registry (survives subshells)
    if [ -n "$_TRAPLIB_DIRS_REGISTRY" ] && [ -f "$_TRAPLIB_DIRS_REGISTRY" ]; then
        local d
        while IFS= read -r d; do
            [ -d "$d" ] && rm -rf "$d"
        done < "$_TRAPLIB_DIRS_REGISTRY"
        rm -f "$_TRAPLIB_DIRS_REGISTRY"
    fi

    # Restore shell options
    eval "$_traplib_oldopts" 2>/dev/null

    # FIX 4: re-raise signal with default disposition for WIFSIGNALED
    if [ "$sig" != "EXIT" ]; then
        trap - "$sig"
        kill -s "$sig" $$
    fi
}

traplib_init() {
    # FIX 14: guard against re-initialization — preserve existing registry
    if [ -n "$_TRAPLIB_DIRS_REGISTRY" ] && [ -f "$_TRAPLIB_DIRS_REGISTRY" ]; then
        return 0
    fi
    _TRAPLIB_DIRS_REGISTRY=$(mktemp /tmp/traplib_reg.XXXXXX)
    _TRAPLIB_CLEANED=0
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
    # FIX 6: append to file-based registry (persists across subshells)
    echo "$d" >> "$_TRAPLIB_DIRS_REGISTRY"
    printf '%s\n' "$d"
}

traplib_spawn_group() {
    # FIX 8: use setsid for process group isolation
    setsid "$@" &
    local pid=$!
    _TRAPLIB_PGROUPS+=("$pid")
    printf '%s\n' "$pid"
}

traplib_wait_ready() {
    local fifo_path="$1"
    local timeout="${2:-10}"
    local result
    # FIX 9: use timeout command, clean up FIFO after read
    result=$(timeout "$timeout" cat "$fifo_path" 2>/dev/null) || {
        rm -f "$fifo_path"
        return 1
    }
    rm -f "$fifo_path"
    printf '%s\n' "$result"
}

traplib_wait_pid() {
    local pid="$1"
    local timeout="${2:-30}"
    # FIX 7: background timer + wait for target PID (returns when target exits)
    ( sleep "$timeout" && kill "$pid" 2>/dev/null ) &
    local timer=$!
    wait "$pid" 2>/dev/null
    local rc=$?
    kill "$timer" 2>/dev/null
    wait "$timer" 2>/dev/null
    return "$rc"
}

traplib_run_exclusive() {
    local lockfile="$1"
    shift
    exec 9>"$lockfile"
    # FIX 10: exclusive lock (not shared)
    flock -x 9
    # FIX 11: register handler for lock file cleanup on exit
    traplib_push_handler "rm -f '${lockfile}'"
    "$@"
    local rc=$?
    flock -u 9
    exec 9>&-
    return "$rc"
}

traplib_critical_section() {
    # FIX 12: defer signals via queueing handler instead of ignoring (trap '')
    _TRAPLIB_DEFERRED_SIGNALS=()
    trap '_TRAPLIB_DEFERRED_SIGNALS+=(TERM)' TERM
    trap '_TRAPLIB_DEFERRED_SIGNALS+=(INT)' INT
    trap '_TRAPLIB_DEFERRED_SIGNALS+=(HUP)' HUP
    "$@"
    local rc=$?
    # Restore normal signal handlers
    trap '_traplib_run_cleanup TERM' TERM
    trap '_traplib_run_cleanup INT' INT
    trap '_traplib_run_cleanup HUP' HUP
    # Re-deliver any deferred signals
    local _deferred
    for _deferred in "${_TRAPLIB_DEFERRED_SIGNALS[@]}"; do
        kill -s "$_deferred" $$
        break
    done
    return "$rc"
}

traplib_safe_pipe() {
    local src_cmd="$1"
    local sink_cmd="$2"
    local pipe_dir
    pipe_dir=$(mktemp -d "/tmp/traplib_pipe.XXXXXX")
    # FIX 17: register pipe dir for cleanup on abnormal exit
    echo "$pipe_dir" >> "$_TRAPLIB_DIRS_REGISTRY"
    local pipe_path="$pipe_dir/fifo"
    mkfifo "$pipe_path"

    # FIX 15: track both processes for cleanup, use setsid for isolation
    setsid bash -c "$src_cmd" < /dev/null > "$pipe_path" &
    local src_pid=$!
    _TRAPLIB_PGROUPS+=("$src_pid")

    setsid bash -c "$sink_cmd" < "$pipe_path" &
    local sink_pid=$!
    _TRAPLIB_PGROUPS+=("$sink_pid")

    # FIX 16: wait for consumer (sink) — that is whose exit status matters
    wait "$sink_pid" 2>/dev/null
    local rc=$?

    # Kill producer if still running
    kill -- -"$src_pid" 2>/dev/null
    wait "$src_pid" 2>/dev/null

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
        # FIX 19: track supervised child for cleanup
        _TRAPLIB_PGROUPS+=("$child_pid")

        wait "$child_pid" 2>/dev/null
        local exit_rc=$?

        [ "$exit_rc" -eq 0 ] && return 0

        restart_count=$((restart_count + 1))
        # FIX 18: use -gt not -ge for correct restart count
        if [ "$restart_count" -gt "$max_restarts" ]; then
            return "$exit_rc"
        fi

        # Stop restarting if cleanup has started
        [ "$_TRAPLIB_CLEANED" -eq 1 ] && return 1

        sleep 0.5
    done
}
TRAPLIB_EOF
