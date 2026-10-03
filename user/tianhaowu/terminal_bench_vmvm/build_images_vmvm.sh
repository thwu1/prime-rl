#!/usr/bin/env bash
# Build and push one slice of a prepare_build_plan.py TSV on a leased VMVM host.
set -uo pipefail

plan=${1:?usage: build_images_vmvm.sh BUILD_PLAN.tsv}
status_root=${STATUS_ROOT:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/build_status}
log_root=${BUILD_LOG_ROOT:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/build_logs}
vacli=${VACLI_BIN:-/public/fbpkgs/x86_64/vacli/stable/vacli}
tenant=${VMVM_TENANT_ID:-async_2347641}
lease_ttl=${VMVM_BUILD_LEASE_TTL:-10800s}

if [[ ! -f "$plan" ]]; then
    printf 'build plan does not exist: %s\n' "$plan" >&2
    exit 2
fi
mkdir -p "$status_root" "$log_root"

nonce="${SLURM_JOB_ID:-manual}_${SLURM_ARRAY_TASK_ID:-0}_$$"
lease_log="/tmp/tb_vmvm_build_lease_${nonce}.log"
control_path="/tmp/tb_vmvm_build_ssh_${nonce}"
vacli_pid=
ssh_port=

cleanup() {
    if [[ -n "$vacli_pid" ]]; then
        kill "$vacli_pid" 2>/dev/null || true
        wait "$vacli_pid" 2>/dev/null || true
    fi
    rm -f -- "$lease_log" "${control_path}"* 2>/dev/null || true
}
trap cleanup EXIT INT TERM

lease_vm() {
    local attempt index
    for attempt in $(seq 1 "${VACLI_LEASE_RETRIES:-20}"); do
        : > "$lease_log"
        "$vacli" --x2p --faas-tenant-id "$tenant" \
            lease --ttl "$lease_ttl" --auto-renew --tunnel-ports 22 --release-on-exit \
            > "$lease_log" 2>&1 &
        vacli_pid=$!
        for index in $(seq 1 120); do
            if ! kill -0 "$vacli_pid" 2>/dev/null; then
                break
            fi
            ssh_port=$(grep -oE '"local_port":[[:space:]]*[0-9]+' "$lease_log" \
                | head -n 1 | grep -oE '[0-9]+$' || true)
            if [[ -n "$ssh_port" ]]; then
                return 0
            fi
            sleep 2
        done
        kill "$vacli_pid" 2>/dev/null || true
        wait "$vacli_pid" 2>/dev/null || true
        vacli_pid=
        sleep $((attempt < 5 ? attempt * 2 : 10))
    done
    printf 'failed to lease VMVM after %s attempts (vacli output withheld because it contains credentials)\n' \
        "${VACLI_LEASE_RETRIES:-20}" >&2
    return 1
}

ssh_cmd() {
    ssh -n \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR \
        -o ControlMaster=auto \
        -o ControlPath="$control_path" \
        -o ControlPersist=600 \
        -p "$ssh_port" root@localhost "$@"
}

wait_sshd() {
    local attempt
    for attempt in $(seq 1 60); do
        if ssh_cmd true 2>/dev/null; then
            return 0
        fi
        sleep 2
    done
    return 1
}

transfer_context() {
    local source=$1 target=$2
    tar -czf - -C "$source" . | ssh \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR \
        -o ControlPath="$control_path" \
        -p "$ssh_port" root@localhost "tar -xzf - -C '$target'"
}

write_status() {
    local target=$1 state=$2 task=$3 role=$4 digest=$5 image=$6 detail=$7
    local temporary="${target}.${nonce}.tmp"
    printf '{"state":"%s","task":"%s","role":"%s","context_sha256":"%s","image":"%s","detail":"%s","unix_time":%s}\n' \
        "$state" "$task" "$role" "$digest" "$image" "$detail" "$(date +%s)" > "$temporary"
    mv -f -- "$temporary" "$target"
}

build_one() {
    local task=$1 role=$2 digest=$3 context=$4 image=$5 index=$6
    local status_dir="$status_root/${image##*:}"
    local status="$status_dir/${task}.${role}.json"
    local build_log="$log_root/${task}.${role}.${nonce}.log"
    local remote_dir="/tmp/tb_build_${nonce}_${index}"
    mkdir -p "$status_dir"

    if [[ -f "$status" ]] \
        && grep -qF '"state":"success"' "$status" \
        && grep -qF "\"context_sha256\":\"$digest\"" "$status" \
        && grep -qF "\"image\":\"$image\"" "$status"; then
        printf '[%s] skip %s %s (matching successful status)\n' "$index" "$task" "$role"
        return 0
    fi
    if [[ ! -f "$context/Dockerfile" ]]; then
        write_status "$status" failed "$task" "$role" "$digest" "$image" missing_Dockerfile
        return 1
    fi
    if ! ssh_cmd "mkdir -p '$remote_dir'"; then
        return 75
    fi
    if ! transfer_context "$context" "$remote_dir"; then
        write_status "$status" failed "$task" "$role" "$digest" "$image" transfer_failed
        return 1
    fi
    if ! ssh_cmd "bash -l -c \"cd '$remote_dir' && podman build --pull=missing --tag '$image' .\"" \
        > "$build_log" 2>&1; then
        write_status "$status" failed "$task" "$role" "$digest" "$image" build_failed
        ssh_cmd "rm -r -- '$remote_dir'; podman rmi '$image' >/dev/null 2>&1 || true" || true
        return 1
    fi
    if ! ssh_cmd "bash -l -c \"podman push --tls-verify=false '$image'\"" \
        >> "$build_log" 2>&1; then
        write_status "$status" failed "$task" "$role" "$digest" "$image" push_failed
        ssh_cmd "rm -r -- '$remote_dir'; podman rmi '$image' >/dev/null 2>&1 || true" || true
        return 1
    fi
    write_status "$status" success "$task" "$role" "$digest" "$image" ok
    ssh_cmd "rm -r -- '$remote_dir'; podman rmi '$image' >/dev/null 2>&1 || true" || true
    return 0
}

lease_vm || exit 1
wait_sshd || { printf 'leased VMVM SSH did not become ready\n' >&2; exit 1; }

ok=0
failed=0
skipped=0
index=0
while IFS=$'\t' read -r task role digest context image; do
    [[ -n "$task" ]] || continue
    index=$((index + 1))
    if ! [[ "$task" =~ ^[a-z0-9][a-z0-9._-]*$ && "$role" =~ ^(agent|verifier)$ ]]; then
        printf 'unsafe build-plan row: task=%q role=%q\n' "$task" "$role" >&2
        failed=$((failed + 1))
        continue
    fi
    printf '[%s] build %s %s -> %s\n' "$index" "$task" "$role" "$image"
    if ! ssh_cmd true >/dev/null 2>&1; then
        kill "$vacli_pid" 2>/dev/null || true
        wait "$vacli_pid" 2>/dev/null || true
        vacli_pid=
        rm -f -- "${control_path}"* 2>/dev/null || true
        lease_vm && wait_sshd || exit 1
    fi
    build_one "$task" "$role" "$digest" "$context" "$image" "$index"
    status=$?
    if [[ "$status" -eq 0 ]]; then
        ok=$((ok + 1))
    elif [[ "$status" -eq 75 ]]; then
        printf 'VMVM transport failed; leave task without terminal status for resume\n' >&2
        exit 75
    else
        failed=$((failed + 1))
    fi
done < "$plan"

printf 'build slice complete: ok=%d failed=%d skipped=%d total=%d\n' "$ok" "$failed" "$skipped" "$index"
[[ "$failed" -eq 0 ]]
