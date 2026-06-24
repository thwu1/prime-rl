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

VACLI=/public/fbpkgs/x86_64/vacli/latest/vacli
TENANT="async_2347641"
DOCKERIO_PREFIX="docker.io/tianhao0122/optimbench-tb"
VMVM_PREFIX="vmvm-registry.fbinfra.net/terminal_bench"
DONE_FILE="/checkpoint/ram/tianhaowu/vmvm_push_done.txt"
FAIL_FILE="/checkpoint/ram/tianhaowu/vmvm_push_fail.txt"
NONCE=$(head -c4 /dev/urandom | xxd -p)
LOG="/tmp/vacli_batch_${NONCE}.log"
CTL="/tmp/vacli_batch_ctl_${NONCE}"
SSH_PORT=""
VACLI_PID=""

touch "$DONE_FILE" "$FAIL_FILE"

# Extract our slice of tasks into a temp file (avoids here-string issues)
SLICE="/tmp/vmvm_slice_${NONCE}.txt"
sed -n "$((START + 1)),$((START + COUNT))p" "$TASK_FILE" > "$SLICE"
TOTAL=$(wc -l < "$SLICE")
echo "=== Batch push: $TOTAL tasks (offset=$START) on $(hostname) at $(date) ==="

cleanup() {
    [ -n "$VACLI_PID" ] && kill "$VACLI_PID" 2>/dev/null || true
    rm -f "$LOG" "${CTL}"* "$SLICE"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
lease_vm() {
    for attempt in 1 2 3 4 5; do
        echo "[lease] attempt $attempt/5..."
        rm -f "$LOG"
        stdbuf -oL "$VACLI" --x2p \
            --faas-tenant-id "$TENANT" \
            lease --ttl 7200s --auto-renew \
            --tunnel-ports 22 --release-on-exit > "$LOG" 2>&1 &
        VACLI_PID=$!

        for i in $(seq 1 120); do
            if ! kill -0 "$VACLI_PID" 2>/dev/null; then
                echo "[lease] vacli died, retrying..."
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
        -o ControlMaster=auto -o ControlPath="$CTL" -o ControlPersist=300 \
        -p "$SSH_PORT" root@localhost "$@" 2>/dev/null
}

wait_sshd() {
    echo "[sshd] waiting..."
    for i in $(seq 1 30); do
        ssh_cmd true && { echo "[sshd] ready"; return 0; }
        sleep 2
    done
    echo "[sshd] FATAL: sshd never came up"
    return 1
}

check_ssh() {
    ssh_cmd true
}

# ---------------------------------------------------------------------------
push_one() {
    local task="$1"
    local src="${DOCKERIO_PREFIX}:${task}"
    local dst="${VMVM_PREFIX}/${task}:latest"

    if ! ssh_cmd "bash -l -c 'podman pull --quiet=false $src'"; then
        echo "  pull failed"
        return 1
    fi

    if ! ssh_cmd "podman tag '$src' '$dst'"; then
        echo "  tag failed"
        ssh_cmd "podman rmi '$src' 2>/dev/null || true"
        return 1
    fi

    if ! ssh_cmd "bash -l -c 'podman push --tls-verify=false $dst'"; then
        echo "  push failed"
        ssh_cmd "podman rmi '$src' '$dst' 2>/dev/null || true"
        return 1
    fi

    # Cleanup disk
    ssh_cmd "podman rmi '$src' '$dst' 2>/dev/null || true"
    return 0
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
        kill "$VACLI_PID" 2>/dev/null || true
        rm -f "${CTL}"*
        if ! lease_vm || ! wait_sshd; then
            echo "FATAL: re-lease failed, aborting"
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
            kill "$VACLI_PID" 2>/dev/null || true
            rm -f "${CTL}"*
            if ! lease_vm || ! wait_sshd; then
                echo "FATAL: re-lease failed, aborting"
                break
            fi
            consecutive_fails=0
        fi
    fi
done < "$SLICE"

echo ""
echo "=== Batch complete: ok=$ok fail=$fail skip=$skip total=$TOTAL ==="
