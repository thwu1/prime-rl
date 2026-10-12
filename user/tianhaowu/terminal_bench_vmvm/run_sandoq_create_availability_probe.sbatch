#!/usr/bin/bash -p
#SBATCH --job-name=sandoq-create-availability
#SBATCH --partition=cpu_x86
#SBATCH --account=ram
#SBATCH --time=00:15:00
#SBATCH --signal=B:TERM@180
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/sandoq_create_availability_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/sandoq_create_availability_%j.log

set +x
set -euo pipefail
umask 077

blocked() {
    printf '{"kind":"sandoq-create-availability","state":"blocked"}\n' >&2
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
project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
probe="$workflow_dir/probe_sandoq_create_availability.py"
launcher="$workflow_dir/run_sandoq_create_availability_probe.sbatch"
expected_revision=${SANDOQ_CREATE_PROBE_EXPECTED_REVISION:?}
expected_probe_sha256=${SANDOQ_CREATE_PROBE_SHA256:?}
expected_launcher_sha256=${SANDOQ_CREATE_PROBE_LAUNCHER_SHA256:?}
x86_uv=/storage/home/tianhaowu/.local/x86_64/bin/uv
x86_site=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64
sandoq_site=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_sdk1_82068
expected_site_sha256=df69cadb16edc799fcb62ea4fc144ee5d5572fe58fcd3e2bd6d165c607e02962
expected_sdk_version=1.0.0.2026.9.23.82068.0+hg1a1d394e50c5
output_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/sandoq-create-availability-20260926
output_dir="$output_root/run-${SLURM_JOB_ID:?}"
temporary_receipt="$output_dir/receipt.json.tmp"
receipt="$output_dir/receipt.json"

[[ "$expected_revision" =~ ^[0-9a-f]{40}$ \
    && "${SLURM_JOB_ID}" =~ ^[1-9][0-9]*$ \
    && "$(git -C "$project_dir" rev-parse HEAD)" == "$expected_revision" \
    && -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all --ignore-submodules=all)" ]] || blocked
[[ "$expected_probe_sha256" =~ ^[0-9a-f]{64}$ \
    && "$expected_launcher_sha256" =~ ^[0-9a-f]{64}$ \
    && -f "$probe" && ! -L "$probe" \
    && -f "$launcher" && ! -L "$launcher" \
    && "$(sha256sum -- "$probe" | cut -d' ' -f1)" == "$expected_probe_sha256" \
    && "$(sha256sum -- "$launcher" | cut -d' ' -f1)" == "$expected_launcher_sha256" \
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
trap 'rm -f -- "$temporary_receipt"' EXIT

set +e
setsid env \
    -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    -u http_proxy -u https_proxy -u all_proxy \
    -u SANDOQ_TUNNEL_HTTPS_PROXY -u SANDOQ_AUTH_TOKEN -u FIRECRACKER_KEY \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="$project_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/extensions/sandoq:$sandoq_site:$x86_site" \
    "$x86_uv" run --no-project --offline --python python3 python "$probe" \
    >"$temporary_receipt" 2>/dev/null &
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
[[ -f "$temporary_receipt" && ! -L "$temporary_receipt" \
    && "$(stat -c '%u:%a' -- "$temporary_receipt")" == "$(id -u):600" ]] || blocked

env PYTHONDONTWRITEBYTECODE=1 "$x86_uv" run --no-project --offline --python python3 \
    python - "$temporary_receipt" "$expected_sdk_version" >/dev/null 2>&1 <<'PY' || blocked
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_sdk_version = sys.argv[2]
raw = path.read_bytes()
if not raw.endswith(b"\n") or raw.count(b"\n") != 1 or len(raw) > 4096:
    raise SystemExit(2)
value = json.loads(raw)
expected = {
    "sdk_version",
    "transport_mode",
    "mtls_available",
    "create_state",
    "response_received",
    "session_returned",
    "cleanup_verified",
    "elapsed_seconds",
}
if (
    not isinstance(value, dict)
    or set(value) != expected
    or value["sdk_version"] != expected_sdk_version
    or value["transport_mode"] != "proxy"
    or value["mtls_available"] is not True
    or not all(
        isinstance(value[name], bool)
        for name in ("response_received", "session_returned", "cleanup_verified")
    )
    or not isinstance(value["create_state"], str)
    or isinstance(value["elapsed_seconds"], bool)
    or not isinstance(value["elapsed_seconds"], (int, float))
):
    raise SystemExit(2)
PY

mv -- "$temporary_receipt" "$receipt"
chmod 600 -- "$receipt"
trap - EXIT
if (( probe_status == 0 )); then
    printf '{"kind":"sandoq-create-availability","state":"passed"}\n'
    exit 0
fi
printf '{"kind":"sandoq-create-availability","state":"unavailable"}\n'
exit 2
