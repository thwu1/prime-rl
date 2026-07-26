#!/usr/bin/env bash
# push_vmvm_batch.sh — mirror docker.io optimbench-tb images to vmvm-registry in batch
#
# Usage: push_vmvm_batch.sh <task-list-file> [start_idx] [count]
#   task-list-file: one task name per line
#   start_idx:      0-based offset into the file (default: 0)
#   count:          how many tasks to process (default: 100)
#
# Leases a single VM and pushes all tasks through it, cleaning up disk after each.
# Tracks progress in a done-file so re-runs skip already-pushed tasks.
#
# Designed to run via srun --overlap on an existing slurm job, or inside sbatch.

set -u

TASK_FILE="${1:?Usage: $0 <task-list-file> [start_idx] [count]}"
START="${2:-0}"
COUNT="${3:-100}"

VACLI="${VACLI:-/public/fbpkgs/x86_64/vacli/latest/vacli}"
TENANT="${TENANT:-async_2347641}"
DOCKERIO_PREFIX="${DOCKERIO_PREFIX:-docker.io/tianhao0122/optimbench-tb}"
VMVM_PREFIX="${VMVM_PREFIX:-vmvm-registry.fbinfra.net/terminal_bench}"
DONE_FILE="${DONE_FILE:-/checkpoint/ram/tianhaowu/vmvm_push_done.txt}"
FAIL_FILE="${FAIL_FILE:-/checkpoint/ram/tianhaowu/vmvm_push_fail.txt}"
TASK_ATTEMPTS="${TASK_ATTEMPTS:-3}"
RETRY_DELAY="${RETRY_DELAY:-10}"
NONCE=$(head -c4 /dev/urandom | xxd -p)
LOG="/tmp/vacli_batch_${NONCE}.log"
CTL="/tmp/vacli_batch_ctl_${NONCE}"
REMOTE_ERR="/tmp/vacli_batch_err_${NONCE}.log"
SSH_PORT=""
VACLI_PID=""

[[ "$TASK_ATTEMPTS" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid TASK_ATTEMPTS: $TASK_ATTEMPTS" >&2; exit 2; }
[[ "$RETRY_DELAY" =~ ^[0-9]+$ ]] || { echo "Invalid RETRY_DELAY: $RETRY_DELAY" >&2; exit 2; }

mkdir -p "$(dirname "$DONE_FILE")" "$(dirname "$FAIL_FILE")"
touch "$DONE_FILE" "$FAIL_FILE"

# Extract our slice of tasks into a temp file (avoids here-string issues)
SLICE="/tmp/vmvm_slice_${NONCE}.txt"
sed -n "$((START + 1)),$((START + COUNT))p" "$TASK_FILE" > "$SLICE"
TOTAL=$(wc -l < "$SLICE")
echo "=== Batch push: $TOTAL tasks (offset=$START) on $(hostname) at $(date) ==="

cleanup() {
    release_vm
    rm -f "$LOG" "$REMOTE_ERR" "$SLICE"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
release_vm() {
    if [ -n "$VACLI_PID" ]; then
        kill "$VACLI_PID" 2>/dev/null || true
        wait "$VACLI_PID" 2>/dev/null || true
    fi
    VACLI_PID=""
    SSH_PORT=""
    rm -f "${CTL}"*
}

lease_vm() {
    for attempt in 1 2 3 4 5; do
        echo "[lease] attempt $attempt/5..."
        release_vm
        rm -f "$LOG"
        stdbuf -oL "$VACLI" --x2p \
            --faas-tenant-id "$TENANT" \
            lease --ttl 7200s --auto-renew \
            --tunnel-ports 22 --release-on-exit > "$LOG" 2>&1 &
        VACLI_PID=$!

        for i in $(seq 1 120); do
            if ! kill -0 "$VACLI_PID" 2>/dev/null; then
                echo "[lease] vacli died, retrying..."
                wait "$VACLI_PID" 2>/dev/null || true
                VACLI_PID=""
                sleep 5
                break
            fi
            local port
            port=$(grep -oP '"local_port":\K\d+' "$LOG" 2>/dev/null | head -1) || true
            if [ -n "$port" ]; then
                echo "[lease] tunnel port=$port"
                SSH_PORT="$port"
                return 0
            fi
            sleep 2
        done
    done
    echo "FATAL: could not lease VM after 5 attempts"
    return 1
}

ssh_cmd() {
    ssh -n -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=2 \
        -o ControlMaster=auto -o ControlPath="$CTL" -o ControlPersist=300 \
        -p "$SSH_PORT" root@localhost "$@"
}

remote_cmd() {
    : > "$REMOTE_ERR"
    if ssh_cmd "$@" 2>"$REMOTE_ERR"; then
        return 0
    fi
    echo "  remote stderr (tail):" >&2
    tail -40 "$REMOTE_ERR" >&2 || true
    return 1
}

wait_sshd() {
    echo "[sshd] waiting..."
    for i in $(seq 1 30); do
        ssh_cmd true >/dev/null 2>&1 && { echo "[sshd] ready"; return 0; }
        sleep 2
    done
    echo "[sshd] FATAL: sshd never came up"
    return 1
}

check_ssh() {
    ssh_cmd true >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
push_one_once() {
    local task="$1"
    local src="${DOCKERIO_PREFIX}:${task}"
    local dst="${VMVM_PREFIX}/${task}:latest"

    if ! remote_cmd "bash -l -c 'podman pull --quiet=false $src'"; then
        echo "  pull failed"
        ssh_cmd "podman rmi '$src' '$dst' 2>/dev/null || true" >/dev/null 2>&1 || true
        return 1
    fi

    if ! remote_cmd "podman tag '$src' '$dst'"; then
        echo "  tag failed"
        ssh_cmd "podman rmi '$src' 2>/dev/null || true" >/dev/null 2>&1 || true
        return 1
    fi

    if ! remote_cmd "bash -l -c 'podman push --tls-verify=false $dst'"; then
        echo "  push failed"
        ssh_cmd "podman rmi '$src' '$dst' 2>/dev/null || true" >/dev/null 2>&1 || true
        return 1
    fi

    # Cleanup disk
    ssh_cmd "podman rmi '$src' '$dst' 2>/dev/null || true" >/dev/null 2>&1 || true
    return 0
}

push_one() {
    local task="$1"
    local attempt

    for attempt in $(seq 1 "$TASK_ATTEMPTS"); do
        if push_one_once "$task"; then
            return 0
        fi
        echo "  task attempt $attempt/$TASK_ATTEMPTS failed"
        [ "$attempt" -lt "$TASK_ATTEMPTS" ] || break

        if [ "$attempt" -eq $((TASK_ATTEMPTS - 1)) ]; then
            echo "  re-leasing a fresh VM before final attempt"
            release_vm
            lease_vm && wait_sshd || return 1
        elif ! check_ssh; then
            echo "  SSH unhealthy; re-leasing VM"
            release_vm
            lease_vm && wait_sshd || return 1
        fi
        sleep $((RETRY_DELAY * attempt + RANDOM % 5))
    done
    return 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
lease_vm || exit 1
wait_sshd || exit 1

ok=0
fail=0
skip=0
idx=0
consecutive_fails=0
aborted=0

while IFS= read -r task; do
    idx=$((idx + 1))
    [ -z "$task" ] && continue

    # Skip already-done
    if grep -qxF "$task" "$DONE_FILE" 2>/dev/null; then
        skip=$((skip + 1))
        continue
    fi

    echo ""
    echo "[$idx/$TOTAL] $task"

    # Health check: is the VM still alive?
    if ! check_ssh; then
        echo "  SSH died — re-leasing VM..."
        release_vm
        if ! lease_vm || ! wait_sshd; then
            echo "FATAL: re-lease failed, aborting"
            aborted=1
            break
        fi
    fi

    if push_one "$task"; then
        echo "$task" >> "$DONE_FILE"
        ok=$((ok + 1))
        consecutive_fails=0
        echo "  -> OK  (done=$ok fail=$fail skip=$skip)"
    else
        echo "$task" >> "$FAIL_FILE"
        fail=$((fail + 1))
        consecutive_fails=$((consecutive_fails + 1))
        echo "  -> FAIL (done=$ok fail=$fail skip=$skip)"
        if [ "$consecutive_fails" -ge 5 ]; then
            echo "5 consecutive failures — re-leasing VM..."
            release_vm
            if ! lease_vm || ! wait_sshd; then
                echo "FATAL: re-lease failed, aborting"
                aborted=1
                break
            fi
            consecutive_fails=0
        fi
    fi
done < "$SLICE"

echo ""
echo "=== Batch complete: ok=$ok fail=$fail skip=$skip total=$TOTAL ==="
(( fail == 0 && aborted == 0 ))
