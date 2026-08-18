#!/usr/bin/env bash
# build_diagnose.sh — build a small task list on one leased VM, capturing the FULL
# podman build output per task to /checkpoint/.../tmax_build_logs/diag_<task>.log.
# Pushes successes to vmvm-registry. For diagnosing stubborn build failures.
set -u
TASK_FILE="${1:?usage: build_diagnose.sh <task-list>}"
HARBOR=/checkpoint/ram/tianhaowu/datasets/tmax15k_harbor
VACLI=/public/fbpkgs/x86_64/vacli/latest/vacli
TENANT="async_2347641"
VMVM_PREFIX="vmvm-registry.fbinfra.net/terminal_bench"
DIAG=/checkpoint/ram/tianhaowu/tmax_build_logs
NONCE=$(head -c4 /dev/urandom | xxd -p)
LOG="/tmp/vacli_diag_${NONCE}.log"; CTL="/tmp/vacli_diag_ctl_${NONCE}"; SSH_PORT=""; VACLI_PID=""
LIVE="$DIAG/diag_live_$(hostname)_$$.log"; exec > >(stdbuf -oL tee -a "$LIVE") 2>&1
cleanup(){ [ -n "$VACLI_PID" ] && kill "$VACLI_PID" 2>/dev/null||true; rm -f "$LOG" "${CTL}"*; }
trap cleanup EXIT
lease_vm(){ for a in $(seq 1 40); do echo "[lease $a]"; rm -f "$LOG"
  stdbuf -oL "$VACLI" --x2p --faas-tenant-id "$TENANT" lease --ttl 7200s --auto-renew --tunnel-ports 22 --release-on-exit >"$LOG" 2>&1 & VACLI_PID=$!
  for i in $(seq 1 120); do kill -0 "$VACLI_PID" 2>/dev/null||{ echo "  died"; sleep 8; break; }
    p=$(grep -oP '"local_port":\K\d+' "$LOG" 2>/dev/null|head -1)||true; [ -n "$p" ]&&{ SSH_PORT=$p; echo "  port=$p"; return 0; }; sleep 2; done; done; return 1; }
ssh_cmd(){ ssh -n -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ControlMaster=auto -o ControlPath="$CTL" -o ControlPersist=600 -p "$SSH_PORT" root@localhost "$@" 2>/dev/null; }
xfer(){ tar czf - -C "$1" . | ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ControlPath="$CTL" -p "$SSH_PORT" root@localhost "tar xzf - -C '$2'"; }
wait_sshd(){ for i in $(seq 1 30); do ssh_cmd true&&return 0; sleep 2; done; return 1; }
lease_vm||exit 1; wait_sshd||exit 1
while IFS= read -r t; do [ -z "$t" ]&&continue
  ctx="$HARBOR/tasks/$t/environment"; dst="$VMVM_PREFIX/$t:latest"; out="$DIAG/diag_$t.log"
  echo "=== BUILD $t ==="
  ssh_cmd "rm -rf /tmp/c_$t && mkdir -p /tmp/c_$t"
  xfer "$ctx" "/tmp/c_$t" || { echo "TRANSFER_FAIL $t"|tee "$out"; continue; }
  if ssh_cmd "cd /tmp/c_$t && podman build -t '$dst' . 2>&1" > "$out" 2>&1; then
    echo "BUILD_OK $t"; ssh_cmd "podman push --tls-verify=false '$dst'" && echo "$t" >> /checkpoint/ram/tianhaowu/tmax_build_done.txt
    ssh_cmd "podman rmi '$dst' 2>/dev/null||true"
  else
    echo "BUILD_FAIL $t -> $out (last lines:)"; tail -5 "$out"
  fi
  ssh_cmd "rm -rf /tmp/c_$t"
done < "$TASK_FILE"
echo "=== diagnose done ==="
