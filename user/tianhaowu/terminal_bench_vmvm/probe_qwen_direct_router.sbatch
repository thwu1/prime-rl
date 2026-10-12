#!/bin/bash
#SBATCH --job-name=qwen-router-probe
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=00:15:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_router_probe_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_router_probe_%j.log

# Infrastructure-only readiness check. It never opens a task dataset or sends a
# model completion request.
set -euo pipefail

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
deployment_root=${DIRECT_QWEN_DEPLOYMENT_ROOT:-/checkpoint/ram/shared/vllm_deployments_v2/shared_qwen38_2p4t}
router_site=${DIRECT_ROUTER_SITE:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/vllm_router_x86_64_0.1.26}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}

if [[ "$(uname -m)" != x86_64 \
    || ! -x "$x86_uv" \
    || ! -d "$router_site/site-packages/vllm_router-0.1.26.dist-info" ]]; then
    printf 'Pinned x86 direct-router runtime is unavailable\n' >&2
    exit 2
fi
cd "$project_dir"
runtime_dir=$(mktemp -d "${SLURM_TMPDIR:-/tmp}/qwen-router-probe-${SLURM_JOB_ID}.XXXXXX")
router_log="$runtime_dir/router.log"
router_pid=
cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [[ -n "$router_pid" ]] && kill -0 "$router_pid" 2>/dev/null; then
        kill -TERM -- "-$router_pid" 2>/dev/null || true
        wait "$router_pid" 2>/dev/null || true
    fi
    rm -rf -- "$runtime_dir"
    exit "$status"
}
trap cleanup EXIT INT TERM

while IFS= read -r variable_name; do
    if [[ ${variable_name,,} == *_proxy ]]; then
        unset "$variable_name"
    fi
done < <(compgen -e)

mapfile -t worker_urls < <(
    PYTHONPATH="$workflow_dir" "$python_bin" -c \
        'import sys; from pathlib import Path; from direct_qwen_workers import load_workers, probe_workers; workers, _, _ = load_workers(Path(sys.argv[1])); probe_workers(workers); print("\n".join(worker.url for worker in workers))' \
        "$deployment_root"
)
if [[ ${#worker_urls[@]} -ne 16 ]]; then
    printf 'Pinned Qwen deployment did not yield exactly 16 workers\n' >&2
    exit 2
fi

router_port=$((20000 + SLURM_JOB_ID % 10000))
metrics_port=$((40000 + SLURM_JOB_ID % 10000))
setsid env PYTHONPATH="$router_site/site-packages" \
    "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 -c 'from vllm_router.launch_router import main; main()' \
        --policy consistent_hash \
        --request-id-headers x-session-id \
        --host 127.0.0.1 \
        --port "$router_port" \
        --prometheus-host 127.0.0.1 \
        --prometheus-port "$metrics_port" \
        --worker-startup-timeout-secs 60 \
        --request-timeout-secs 7500 \
        --disable-retries \
        --max-concurrent-requests 8 \
        --queue-size 0 \
        --log-level warning \
        --worker-urls "${worker_urls[@]}" > "$router_log" 2>&1 &
router_pid=$!

for attempt in $(seq 1 60); do
    if ! kill -0 "$router_pid" 2>/dev/null; then
        printf 'Direct Qwen router exited during infrastructure probe\n' >&2
        sed -n '1,80p' "$router_log" >&2
        exit 2
    fi
    active_workers=$(
        curl --noproxy '*' --fail --silent --show-error --max-time 10 \
            "http://127.0.0.1:${metrics_port}/metrics" 2>/dev/null \
            | awk '$1 == "vllm_router_active_workers" {print $2}' \
            | tail -n 1
    ) || true
    if [[ "$active_workers" == 16 ]] \
        && curl --noproxy '*' --fail --silent --show-error --max-time 10 \
            "http://127.0.0.1:${router_port}/v1/models" >/dev/null; then
        printf '{"active_workers":16,"model_route_ready":true,"ok":true}\n'
        exit 0
    fi
    if [[ "$attempt" -eq 60 ]]; then
        printf 'Direct Qwen router did not expose exactly 16 active workers\n' >&2
        exit 2
    fi
    sleep 5
done
