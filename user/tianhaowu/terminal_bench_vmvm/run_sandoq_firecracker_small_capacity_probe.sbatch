#!/usr/bin/bash -p
#SBATCH --job-name=sandoq-small-capacity-soak
#SBATCH --partition=cpu_x86
#SBATCH --account=ram
#SBATCH --time=00:15:00
#SBATCH --signal=B:TERM@180
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/sandoq_small_capacity_soak_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/sandoq_small_capacity_soak_%j.log

set +x
set -euo pipefail
umask 077

kind=sandoq-firecracker-small-capacity-soak
blocked() {
    printf '{"kind":"%s","state":"blocked"}\n' "$kind" >&2
    exit 2
}

group_exists() {
    kill -0 -- "-$1" 2>/dev/null
}

wait_group_empty() {
    local pgid=$1
    local timeout=$2
    local deadline=$((SECONDS + timeout))
    while group_exists "$pgid"; do
        (( SECONDS < deadline )) || return 1
        sleep 1
    done
}

terminate_group() {
    local pgid=$1
    group_exists "$pgid" || return 0
    kill -INT -- "-$pgid" 2>/dev/null || true
    if ! wait_group_empty "$pgid" 120; then
        kill -TERM -- "-$pgid" 2>/dev/null || true
        if ! wait_group_empty "$pgid" 20; then
            kill -KILL -- "-$pgid" 2>/dev/null || true
            wait_group_empty "$pgid" 10 || return 1
        fi
    fi
}

(( $# == 0 )) || blocked
concurrency=${SANDOQ_SMALL_CAPACITY_CONCURRENCY:-}
[[ "$concurrency" == 24 || "$concurrency" == 64 ]] || blocked
kind="sandoq-firecracker-small-c${concurrency}-soak"
project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
probe="$workflow_dir/probe_sandoq_firecracker_small_capacity.py"
launcher="$workflow_dir/run_sandoq_firecracker_small_capacity_probe.sbatch"
profile="$workflow_dir/configs/provider_context/use2/cpu-132-021_8103/kimi_sandoq_firecracker_small_host.json"
expected_revision=${SANDOQ_SMALL_CAPACITY_EXPECTED_REVISION:?}
expected_probe_sha256=${SANDOQ_SMALL_CAPACITY_PROBE_SHA256:?}
expected_launcher_sha256=${SANDOQ_SMALL_CAPACITY_LAUNCHER_SHA256:?}
expected_profile_sha256=${SANDOQ_SMALL_CAPACITY_PROFILE_SHA256:?}
x86_uv=/storage/home/tianhaowu/.local/x86_64/bin/uv
x86_site=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64
sandoq_site=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_sdk1_82068
expected_site_sha256=df69cadb16edc799fcb62ea4fc144ee5d5572fe58fcd3e2bd6d165c607e02962
expected_sdk_version=1.0.0.2026.9.23.82068.0+hg1a1d394e50c5
output_root="/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/sandoq-firecracker-small-c${concurrency}-soak-20260927"
output_dir="$output_root/run-${SLURM_JOB_ID:?}"
receipt="$output_dir/receipt.json"

[[ "$expected_revision" =~ ^[0-9a-f]{40}$ \
    && "${SLURM_JOB_ID}" =~ ^[1-9][0-9]*$ \
    && "$(git -C "$project_dir" rev-parse HEAD)" == "$expected_revision" \
    && -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all --ignore-submodules=all)" ]] || blocked
[[ "$expected_probe_sha256" =~ ^[0-9a-f]{64}$ \
    && "$expected_launcher_sha256" =~ ^[0-9a-f]{64}$ \
    && "$expected_profile_sha256" =~ ^[0-9a-f]{64}$ \
    && -f "$probe" && ! -L "$probe" \
    && -f "$launcher" && ! -L "$launcher" \
    && -f "$profile" && ! -L "$profile" \
    && "$(sha256sum -- "$probe" | cut -d' ' -f1)" == "$expected_probe_sha256" \
    && "$(sha256sum -- "$launcher" | cut -d' ' -f1)" == "$expected_launcher_sha256" \
    && "$(sha256sum -- "$profile" | cut -d' ' -f1)" == "$expected_profile_sha256" \
    && -x "$x86_uv" \
    && -d "$x86_site" && ! -L "$x86_site" \
    && "$(realpath -e -- "$x86_site")" == "$x86_site" \
    && -d "$sandoq_site/sandoq_client" ]] || blocked

observed_site_sha256=$(
    "$x86_uv" run --no-project --offline --python python3 python - "$sandoq_site" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
paths = sorted(
    (
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix != ".pyc" and not path.name.startswith(".")
    ),
    key=lambda path: path.relative_to(root).as_posix(),
)
digest = hashlib.sha256()
for path in paths:
    relative = path.relative_to(root).as_posix()
    digest.update(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}\n".encode())
print(digest.hexdigest())
PY
)
observed_sdk_version=$(
    env PYTHONPATH="$sandoq_site" "$x86_uv" run --no-project --offline --python python3 \
        python -c 'from sandoq_client._version import installed_version; print(installed_version())'
)
[[ "$observed_site_sha256" == "$expected_site_sha256" \
    && "$observed_sdk_version" == "$expected_sdk_version" ]] || blocked

if [[ -e "$output_root" || -L "$output_root" ]]; then
    [[ -d "$output_root" && ! -L "$output_root" \
        && "$(realpath -e -- "$output_root")" == "$output_root" \
        && "$(stat -c '%u:%a' -- "$output_root")" == "$(id -u):700" ]] || blocked
else
    install -d -m 700 -- "$output_root"
fi
[[ ! -e "$output_dir" && ! -L "$output_dir" ]] || blocked
mkdir -m 700 -- "$output_dir"
[[ "$(stat -c '%u:%a' -- "$output_dir")" == "$(id -u):700" ]] || blocked

probe_pid=""
stop_requested=0
stop_probe() {
    stop_requested=1
    if [[ "$probe_pid" =~ ^[1-9][0-9]*$ ]]; then
        terminate_group "$probe_pid" || true
    fi
}
trap stop_probe TERM INT HUP

set +e
setsid env \
    -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    -u http_proxy -u https_proxy -u all_proxy \
    -u SANDOQ_TUNNEL_HTTPS_PROXY -u SANDOQ_AUTH_TOKEN -u FIRECRACKER_KEY \
    -u OCI_RUNNER_TOKEN -u OCI_RUNNER_TOKEN_FILE \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="$project_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/extensions/sandoq:$sandoq_site:$x86_site" \
    "$x86_uv" run --no-project --offline --python python3 python "$probe" \
    --concurrency "$concurrency" --profile "$profile" --output "$receipt" 2>/dev/null &
probe_pid=$!
wait "$probe_pid"
probe_status=$?
set -e

if group_exists "$probe_pid"; then
    terminate_group "$probe_pid" || blocked
    probe_status=2
fi
trap - TERM INT HUP
(( stop_requested == 0 )) || blocked
[[ -f "$receipt" && ! -L "$receipt" \
    && "$(stat -c '%u:%a' -- "$receipt")" == "$(id -u):600" ]] || blocked

env PYTHONDONTWRITEBYTECODE=1 "$x86_uv" run --no-project --offline --python python3 \
    python - "$receipt" "$expected_sdk_version" "$expected_profile_sha256" "$probe_status" "$concurrency" \
    >/dev/null 2>&1 <<'PY' || blocked
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_sdk_version = sys.argv[2]
expected_profile_sha256 = sys.argv[3]
probe_status = int(sys.argv[4])
concurrency = int(sys.argv[5])
kind = f"sandoq-firecracker-small-c{concurrency}-soak"
raw = path.read_bytes()
if not raw.endswith(b"\n") or raw.count(b"\n") != 1 or len(raw) > 16 * 1024:
    raise SystemExit(2)
value = json.loads(raw)
expected = {
    "schema_version",
    "kind",
    "state",
    "environment",
    "profile_sha256",
    "sdk_version",
    "transport_mode",
    "mtls_available",
    "requested_concurrency",
    "create_attempts",
    "sessions_returned",
    "simultaneous_ready_verified",
    "create_failure_counts",
    "delete_attempts",
    "typed_404_verified",
    "cleanup_failures",
    "client_close_verified",
    "elapsed_seconds",
    "slurm_job_id",
}
failure_keys = {
    "connection_failure",
    "invalid_session",
    "session_failure",
    "timed_out",
    "unexpected_failure",
}
if (
    not isinstance(value, dict)
    or set(value) != expected
    or value["schema_version"] != 1
    or concurrency not in (24, 64)
    or value["kind"] != kind
    or value["environment"] != "oci-runner-firecracker-small"
    or value["profile_sha256"] != expected_profile_sha256
    or value["sdk_version"] != expected_sdk_version
    or value["transport_mode"] != "proxy"
    or value["mtls_available"] is not True
    or value["requested_concurrency"] != concurrency
    or value["create_attempts"] != concurrency
    or not isinstance(value["create_failure_counts"], dict)
    or set(value["create_failure_counts"]) != failure_keys
    or any(type(count) is not int or count < 0 for count in value["create_failure_counts"].values())
    or type(value["elapsed_seconds"]) not in (int, float)
    or not isinstance(value["client_close_verified"], bool)
):
    raise SystemExit(2)
passed = (
    value["state"] == "passed"
    and value["sessions_returned"] == concurrency
    and value["simultaneous_ready_verified"] == concurrency
    and not any(value["create_failure_counts"].values())
    and value["delete_attempts"] == concurrency
    and value["typed_404_verified"] == concurrency
    and value["cleanup_failures"] == 0
    and value["client_close_verified"] is True
)
if (probe_status == 0) != passed:
    raise SystemExit(2)
if probe_status not in (0, 2):
    raise SystemExit(2)
PY

if (( probe_status == 0 )); then
    printf '{"kind":"%s","state":"passed"}\n' "$kind"
    exit 0
fi
printf '{"kind":"%s","state":"unavailable"}\n' "$kind"
exit 2
