#!/bin/bash
#SBATCH --job-name=vmvm-verify
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=06:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=/checkpoint/ram/tianhaowu/vmvm_push_logs/verify_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/vmvm_push_logs/verify_%j.log

set -u
VACLI=/public/fbpkgs/x86_64/vacli/latest/vacli
LOG="/tmp/vacli_vfy_$$.log"
CTL="/tmp/vacli_vfy_ctl_$$"

stdbuf -oL "$VACLI" --x2p --faas-tenant-id async_2347641 \
    lease --ttl 21600s --auto-renew --tunnel-ports 22 --release-on-exit > "$LOG" 2>&1 &
PID=$!
PORT=""
for i in $(seq 1 120); do
    PORT=$(grep -oP '"local_port":\K\d+' "$LOG" 2>/dev/null | head -1) || true
    [ -n "$PORT" ] && break
    kill -0 $PID 2>/dev/null || { echo "vacli died"; exit 1; }
    sleep 2
done
[ -z "$PORT" ] && { echo "timeout"; exit 1; }

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ControlMaster=auto -o ControlPath=$CTL -o ControlPersist=300"
SSH="ssh -n $SSH_OPTS -p $PORT root@localhost"
SCP="scp $SSH_OPTS -P $PORT"

for i in $(seq 1 20); do $SSH true 2>/dev/null && break; sleep 2; done
echo "SSH ready"

$SCP /checkpoint/ram/tianhaowu/vmvm_push_done.txt root@localhost:/tmp/tasks.txt 2>/dev/null
$SCP /storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/scripts/verify_vmvm.sh root@localhost:/tmp/verify.sh 2>/dev/null
$SSH "chmod +x /tmp/verify.sh && bash /tmp/verify.sh" 2>/dev/null

kill $PID 2>/dev/null
