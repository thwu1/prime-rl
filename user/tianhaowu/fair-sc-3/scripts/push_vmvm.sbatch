#!/bin/bash
#SBATCH --job-name=vmvm-push
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=/checkpoint/ram/tianhaowu/vmvm_push_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/vmvm_push_%j.log

set -euo pipefail

TASK="${1:?Usage: sbatch push_vmvm.sbatch <task-name>}"
VACLI=/public/fbpkgs/x86_64/vacli/latest/vacli
SRC="docker.io/tianhao0122/optimbench-tb:${TASK}"
DST="vmvm-registry.fbinfra.net/terminal_bench/${TASK}:latest"
TENANT="async_2347641"
NONCE=$(head -c4 /dev/urandom | xxd -p)
LOG="/tmp/vacli_push_${NONCE}.log"
CTL="/tmp/vacli_push_ctl_${NONCE}"

cleanup() {
    [ -n "${VACLI_PID:-}" ] && kill "$VACLI_PID" 2>/dev/null || true
    rm -f "$LOG" "${CTL}"*
}
trap cleanup EXIT

echo "=== Mirroring: ${SRC} → ${DST} ==="
echo "Host: $(hostname), Time: $(date)"

# Lease a VM (retry up to 5 times)
SSH_PORT=""
for attempt in 1 2 3 4 5; do
    echo "[lease] attempt $attempt/5..."
    rm -f "$LOG"
    stdbuf -oL "$VACLI" --x2p \
        --faas-tenant-id "$TENANT" \
        lease --ttl 600s --auto-renew \
        --tunnel-ports 22 --release-on-exit > "$LOG" 2>&1 &
    VACLI_PID=$!

    for i in $(seq 1 90); do
        if grep -qP '"22":\s*\d+' "$LOG" 2>/dev/null; then
            SSH_PORT=$(grep -oP '"22":\s*\K\d+' "$LOG")
            echo "[lease] tunnel on port $SSH_PORT"
            break 2
        fi
        if ! kill -0 "$VACLI_PID" 2>/dev/null; then
            echo "[lease] vacli died, retrying..."
            sleep 5
            break
        fi
        sleep 2
    done
done

if [ -z "$SSH_PORT" ]; then
    echo "FATAL: could not lease VM after 5 attempts"
    exit 1
fi

SSH_CMD="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ControlMaster=auto -o ControlPath=$CTL -o ControlPersist=120 -p $SSH_PORT root@localhost"

# Wait for sshd
echo "[sshd] waiting..."
for i in $(seq 1 30); do
    if $SSH_CMD true 2>/dev/null; then echo "[sshd] ready"; break; fi
    sleep 2
done

# Pull from docker.io
echo "[pull] pulling $SRC..."
$SSH_CMD "bash -l -c 'podman pull --quiet=false $SRC'"

# Tag for vmvm-registry
echo "[tag] tagging as $DST..."
$SSH_CMD "podman tag '$SRC' '$DST'"

# Push to vmvm-registry
echo "[push] pushing to vmvm-registry..."
$SSH_CMD "bash -l -c 'podman push --tls-verify=false $DST'"

# Verify
echo "[verify] verifying pull from vmvm-registry..."
$SSH_CMD "podman rmi '$DST' 2>/dev/null || true"
$SSH_CMD "bash -l -c 'podman pull --tls-verify=false $DST'"

echo "=== SUCCESS: ${TASK} mirrored to vmvm-registry ==="
