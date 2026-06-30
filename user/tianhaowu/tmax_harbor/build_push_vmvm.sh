#!/usr/bin/env bash
# build_push_vmvm.sh — build TMax->harbor task images on a leased VMVM VM and push
# them to vmvm-registry (so vmvm-tb can run them with image_source=vmvm_registry).
#
# Usage: build_push_vmvm.sh <task-list-file> [harbor_root]
#   task-list-file: one task_id per line
#   harbor_root:    default /checkpoint/ram/tianhaowu/datasets/tmax15k_harbor
#
# Per task: scp environment/ build context to the VM, `podman build`, push to
# vmvm-registry.fbinfra.net/terminal_bench/<task_id>:latest, clean up disk.
# Adapted from push_vmvm_batch.sh (lease/health/re-lease logic reused).
set -u

TASK_FILE="${1:?Usage: $0 <task-list-file> [harbor_root]}"
HARBOR="${2:-/checkpoint/ram/tianhaowu/datasets/tmax15k_harbor}"

# Live log on shared FS (SLURM stdout is buffered; this gives real-time visibility).
LIVE_LOG="/checkpoint/ram/tianhaowu/tmax_build_logs/live_$(hostname)_$$.log"
exec > >(stdbuf -oL tee -a "$LIVE_LOG") 2>&1
echo "[live] $(date) host=$(hostname) task_file=$TASK_FILE -> $LIVE_LOG"

VACLI=/public/fbpkgs/x86_64/vacli/latest/vacli
TENANT="async_2347641"
VMVM_PREFIX="vmvm-registry.fbinfra.net/terminal_bench"
DONE_FILE="/checkpoint/ram/tianhaowu/tmax_build_done.txt"
FAIL_FILE="/checkpoint/ram/tianhaowu/tmax_build_fail.txt"
NONCE=$(head -c4 /dev/urandom | xxd -p)
LOG="/tmp/vacli_build_${NONCE}.log"
CTL="/tmp/vacli_build_ctl_${NONCE}"
SSH_PORT=""
VACLI_PID=""
touch "$DONE_FILE" "$FAIL_FILE"

cleanup() { [ -n "$VACLI_PID" ] && kill "$VACLI_PID" 2>/dev/null || true; rm -f "$LOG" "${CTL}"*; }
trap cleanup EXIT

lease_vm() {
    for attempt in $(seq 1 40); do
        echo "[lease] attempt $attempt/40..."; rm -f "$LOG"
        stdbuf -oL "$VACLI" --x2p --faas-tenant-id "$TENANT" \
            lease --ttl 10800s --auto-renew --tunnel-ports 22 --release-on-exit > "$LOG" 2>&1 &
        VACLI_PID=$!
        for i in $(seq 1 120); do
            kill -0 "$VACLI_PID" 2>/dev/null || { echo "[lease] vacli died; last log lines:"; tail -10 "$LOG" 2>/dev/null | sed 's/^/    | /'; sleep 8; break; }
            local port; port=$(grep -oP '"local_port":\K\d+' "$LOG" 2>/dev/null | head -1) || true
            [ -n "$port" ] && { SSH_PORT="$port"; echo "[lease] tunnel port=$port"; return 0; }
            sleep 2
        done
    done
    echo "FATAL: could not lease VM"; return 1
}
ssh_cmd() {
    ssh -n -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o ControlMaster=auto -o ControlPath="$CTL" -o ControlPersist=600 \
        -p "$SSH_PORT" root@localhost "$@" 2>/dev/null
}
transfer_ctx() {  # transfer_ctx <local_ctx_dir> <remote_dir> : tar over ssh tunnel (scp is flaky)
    tar czf - -C "$1" . | ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o ControlPath="$CTL" -p "$SSH_PORT" root@localhost "tar xzf - -C '$2'"
}
wait_sshd() {
    echo "[sshd] waiting..."
    for i in $(seq 1 30); do ssh_cmd true && { echo "[sshd] ready"; return 0; }; sleep 2; done
    echo "[sshd] FATAL"; return 1
}

build_one() {
    local task="$1"
    local ctx="$HARBOR/tasks/$task/environment"
    local dst="${VMVM_PREFIX}/${task}:latest"
    [ -f "$ctx/Dockerfile" ] || { echo "  no Dockerfile"; return 1; }
    ssh_cmd "rm -rf /tmp/ctx_$task && mkdir -p /tmp/ctx_$task" || return 1
    if ! transfer_ctx "$ctx" "/tmp/ctx_$task"; then
        echo "  context transfer failed"; return 1
    fi
    if ! ssh_cmd "cd /tmp/ctx_$task && podman build -t '$dst' . 2>&1 | tail -3"; then
        echo "  build failed"; ssh_cmd "rm -rf /tmp/ctx_$task; podman rmi '$dst' 2>/dev/null || true"; return 1
    fi
    if ! ssh_cmd "podman push --tls-verify=false '$dst'"; then
        echo "  push failed"; ssh_cmd "rm -rf /tmp/ctx_$task; podman rmi '$dst' 2>/dev/null || true"; return 1
    fi
    ssh_cmd "rm -rf /tmp/ctx_$task; podman rmi '$dst' 2>/dev/null || true"
    return 0
}

lease_vm || exit 1
wait_sshd || exit 1
ok=0; fail=0; skip=0; idx=0; total=$(grep -cve '^[[:space:]]*$' "$TASK_FILE")
while IFS= read -r task; do
    [ -z "$task" ] && continue
    idx=$((idx+1))
    grep -qxF "$task" "$DONE_FILE" 2>/dev/null && { skip=$((skip+1)); continue; }
    echo ""; echo "[$idx/$total] building $task"
    ssh_cmd true || { echo "  re-leasing..."; kill "$VACLI_PID" 2>/dev/null; rm -f "${CTL}"*; lease_vm && wait_sshd || break; }
    if build_one "$task"; then
        echo "$task" >> "$DONE_FILE"; ok=$((ok+1)); echo "  -> OK (ok=$ok fail=$fail)"
    else
        echo "$task" >> "$FAIL_FILE"; fail=$((fail+1)); echo "  -> FAIL (ok=$ok fail=$fail)"
    fi
done < "$TASK_FILE"
echo ""; echo "=== build complete: ok=$ok fail=$fail skip=$skip total=$total ==="
