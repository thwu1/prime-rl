#!/usr/bin/env bash
# Run on a slurm node: lease a VM, verify a slice of tasks via registry API.
# Usage: verify_vmvm_batch.sh <task-list-file> <start_idx> <count>
set -u

TASK_FILE="${1:?Usage: $0 <task-list> <start> <count>}"
START="${2:-0}"
COUNT="${3:-100}"

VACLI=/public/fbpkgs/x86_64/vacli/latest/vacli
NONCE=$(head -c4 /dev/urandom | xxd -p)
LOG="/tmp/vacli_vfy_${NONCE}.log"
CTL="/tmp/vacli_vfy_ctl_${NONCE}"
SLICE="/tmp/vfy_slice_${NONCE}.txt"
RESULT_DIR="/checkpoint/ram/tianhaowu/vmvm_verify_results"
mkdir -p "$RESULT_DIR"

sed -n "$((START + 1)),$((START + COUNT))p" "$TASK_FILE" > "$SLICE"
TOTAL=$(wc -l < "$SLICE")
echo "=== Verify worker: offset=$START count=$TOTAL on $(hostname) ==="

cleanup() {
    [ -n "${PID:-}" ] && kill "$PID" 2>/dev/null || true
    rm -f "$LOG" "${CTL}"* "$SLICE"
}
trap cleanup EXIT

# Lease VM
stdbuf -oL "$VACLI" --x2p --faas-tenant-id async_2347641 \
    lease --ttl 3600s --auto-renew --tunnel-ports 22 --release-on-exit > "$LOG" 2>&1 &
PID=$!
PORT=""
for i in $(seq 1 120); do
    PORT=$(grep -oP '"local_port":\K\d+' "$LOG" 2>/dev/null | head -1) || true
    [ -n "$PORT" ] && break
    kill -0 $PID 2>/dev/null || { echo "vacli died"; exit 1; }
    sleep 2
done
[ -z "$PORT" ] && { echo "timeout"; exit 1; }

SSH="ssh -n -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ControlMaster=auto -o ControlPath=$CTL -o ControlPersist=300 -p $PORT root@localhost"
SCP="scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ControlMaster=auto -o ControlPath=$CTL -o ControlPersist=300 -P $PORT"

for i in $(seq 1 20); do $SSH true 2>/dev/null && break; sleep 2; done

# Upload tasks and verify script
$SCP "$SLICE" root@localhost:/tmp/tasks.txt 2>/dev/null
$SCP /storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/scripts/verify_vmvm.sh root@localhost:/tmp/verify.sh 2>/dev/null
$SSH "chmod +x /tmp/verify.sh && bash /tmp/verify.sh" 2>/dev/null | tee "$RESULT_DIR/verify_${START}.txt"

kill $PID 2>/dev/null
