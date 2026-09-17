#!/bin/bash
#SBATCH --job-name=tb-qwen-direct
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_direct_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_direct_%j.log

set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf 'The direct Qwen launcher does not accept eval overrides; use a pinned config\n' >&2
    exit 2
fi
for forbidden in \
    INFERENCE_BASE_URL \
    INFERENCE_DEPLOYMENT_ID \
    INFERENCE_JOB_ID \
    INFERENCE_PROXY_INFO \
    INFERENCE_PROXY_URL \
    DIRECT_QWEN_MANIFEST_SHA256 \
    DIRECT_QWEN_ROUTER_POLICY \
    DIRECT_QWEN_REQUEST_ID_HEADERS; do
    if [[ -n ${!forbidden:-} ]]; then
        printf '%s is forbidden for the direct-worker launcher\n' "$forbidden" >&2
        exit 2
    fi
done
if [[ -n ${OPENAI_API_KEY:-} && ${OPENAI_API_KEY} != EMPTY ]]; then
    printf 'The direct-worker launcher accepts only OPENAI_API_KEY=EMPTY\n' >&2
    exit 2
fi

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
deployment_root=${DIRECT_QWEN_DEPLOYMENT_ROOT:-/checkpoint/ram/shared/vllm_deployments_v2/shared_qwen38_2p4t}
router_site=${DIRECT_ROUTER_SITE:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/vllm_router_x86_64_0.1.26}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
resume_dir=${RESUME_DIR:-}
approved_task_file=${DIRECT_QWEN_APPROVED_TASK_FILE:-}
approved_task_file_sha256=${DIRECT_QWEN_APPROVED_TASK_FILE_SHA256:-}

if [[ -z "$approved_task_file" || -z "$approved_task_file_sha256" ]]; then
    printf '%s\n' \
        'DIRECT_QWEN_APPROVED_TASK_FILE and DIRECT_QWEN_APPROVED_TASK_FILE_SHA256 are required' >&2
    exit 2
fi

if [[ -n "$resume_dir" ]]; then
    output_dir=$resume_dir
    eval_config="$resume_dir/config.toml"
else
    output_dir=${OUTPUT_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/qwen_direct_${SLURM_JOB_ID}}
    eval_config=${EVAL_CONFIG:-}
    if [[ -z "$eval_config" ]]; then
        printf 'EVAL_CONFIG with an approved task_file and task_file_sha256 is required\n' >&2
        exit 2
    fi
fi

if [[ "$(uname -m)" != x86_64 || ! -d "$x86_site/pydantic" ]]; then
    printf 'Missing x86_64 evaluator runtime/dependencies\n' >&2
    exit 2
fi
if [[ ! -x "$x86_uv" ]]; then
    printf 'Missing x86_64 uv binary: %s\n' "$x86_uv" >&2
    exit 2
fi
if [[ ! -d "$router_site/site-packages/vllm_router-0.1.26.dist-info" \
    || ! -f "$router_site/STAGED" \
    || "$(sed -n '1p' "$router_site/STAGED" 2>/dev/null)" != "vllm-router=0.1.26" \
    || "$(sed -n '2p' "$router_site/STAGED" 2>/dev/null)" != "platform=x86_64-manylinux_2_28" \
    || ! -f "$router_site/requirements.sha256" \
    || "$(sha256sum "$router_site/requirements.txt" 2>/dev/null | cut -d' ' -f1)" != "$(cat "$router_site/requirements.sha256" 2>/dev/null)" ]]; then
    printf 'Missing pinned direct-router runtime: %s\n' "$router_site" >&2
    exit 2
fi
if [[ ! -r "$eval_config" ]]; then
    printf 'Missing evaluation config: %s\n' "$eval_config" >&2
    exit 2
fi
cd "$project_dir"

mkdir -p "$output_dir" /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs
exec 8>"$output_dir/.direct_router.lock"
if ! flock -n 8; then
    printf 'Another direct router owns %s\n' "$output_dir" >&2
    exit 2
fi

runtime_dir=$(mktemp -d "${SLURM_TMPDIR:-/tmp}/tb-qwen-router-${SLURM_JOB_ID}.XXXXXX")
urls_file="$runtime_dir/worker_urls.txt"
ports_file="$runtime_dir/ports.txt"
router_log="$output_dir/direct_router.log"
manifest="$output_dir/direct_workers.json"
router_pid=
eval_pid=
cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [[ -n "$eval_pid" ]] && kill -0 "$eval_pid" 2>/dev/null; then
        kill -TERM "$eval_pid" 2>/dev/null || true
        wait "$eval_pid" 2>/dev/null || true
    fi
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

prepare_args=(
    "$workflow_dir/direct_qwen_workers.py"
    --deployment-root "$deployment_root"
    --eval-config "$eval_config"
    --manifest "$manifest"
    --urls-output "$urls_file"
    --ports-output "$ports_file"
    --approved-task-file "$approved_task_file"
    --approved-task-file-sha256 "$approved_task_file_sha256"
)
if [[ -n "$resume_dir" ]]; then
    prepare_args+=(--resume)
fi
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "${prepare_args[@]}"

mapfile -t worker_urls < "$urls_file"
mapfile -t ports < "$ports_file"
if [[ ${#worker_urls[@]} -ne 16 || ${#ports[@]} -ne 7 ]]; then
    printf 'Direct-worker runtime files are incomplete\n' >&2
    exit 2
fi
router_port=${ports[0]}
metrics_port=${ports[1]}
router_max_concurrent=${ports[2]}
router_queue_size=${ports[3]}
router_queue_timeout=${ports[4]}
router_policy=${ports[5]}
router_request_id_header=${ports[6]}
if [[ ! "$router_max_concurrent" =~ ^[1-9][0-9]*$ ]] \
    || (( router_max_concurrent > 16 )) \
    || [[ ! "$router_queue_size" =~ ^[0-9]+$ ]] \
    || (( router_queue_size >= 64 )) \
    || [[ ! "$router_queue_timeout" =~ ^[1-9][0-9]*$ ]] \
    || [[ "$router_policy" != consistent_hash ]] \
    || [[ "$router_request_id_header" != x-session-id ]]; then
    printf 'Direct Qwen router concurrency is invalid\n' >&2
    exit 2
fi
manifest_sha256=$(sha256sum -- "$manifest" | cut -d' ' -f1)
if [[ ! "$manifest_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'Direct Qwen router manifest digest is invalid\n' >&2
    exit 2
fi

router_args=(
    -c 'from vllm_router.launch_router import main; main()'
    --policy "$router_policy"
    --request-id-headers "$router_request_id_header"
    --host 127.0.0.1
    --port "$router_port"
    --prometheus-host 127.0.0.1
    --prometheus-port "$metrics_port"
    --worker-startup-timeout-secs 60
    --request-timeout-secs 7500
    --disable-retries
    --max-concurrent-requests "$router_max_concurrent"
    --queue-size "$router_queue_size"
    --queue-timeout-secs "$router_queue_timeout"
    --log-level warning
    --worker-urls "${worker_urls[@]}"
)
setsid env PYTHONPATH="$router_site/site-packages" \
    "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "${router_args[@]}" > "$router_log" 2>&1 &
router_pid=$!

router_url="http://127.0.0.1:${router_port}"
metrics_url="http://127.0.0.1:${metrics_port}/metrics"
for attempt in $(seq 1 60); do
    if ! kill -0 "$router_pid" 2>/dev/null; then
        printf 'Direct Qwen router exited during startup; see %s\n' "$router_log" >&2
        exit 2
    fi
    models_ready=0
    active_workers=
    if curl --noproxy '*' --fail --silent --show-error --max-time 10 \
        "$router_url/v1/models" >/dev/null 2>&1; then
        models_ready=1
    fi
    active_workers=$(
        curl --noproxy '*' --fail --silent --show-error --max-time 10 \
            "$metrics_url" 2>/dev/null \
            | awk '$1 == "vllm_router_active_workers" {print $2}' \
            | tail -n 1
    ) || true
    if [[ "$models_ready" -eq 1 && "$active_workers" == 16 ]]; then
        break
    fi
    if [[ "$attempt" -eq 60 ]]; then
        printf 'Direct Qwen router did not expose exactly 16 active workers\n' >&2
        exit 2
    fi
    sleep 5
done

export PROJECT_DIR="$project_dir"
export OUTPUT_DIR="$output_dir"
export INFERENCE_BASE_URL="$router_url/v1"
export OPENAI_API_KEY=EMPTY
export VACLI_MAX_CONCURRENT_LEASES=2
export DIRECT_QWEN_MANIFEST_SHA256="$manifest_sha256"
export DIRECT_QWEN_ROUTER_POLICY="$router_policy"
export DIRECT_QWEN_REQUEST_ID_HEADERS="$router_request_id_header"
if [[ -n "$resume_dir" ]]; then
    export RESUME_DIR="$resume_dir"
else
    export EVAL_CONFIG="$eval_config"
fi

bash "$workflow_dir/run_eval.sbatch" &
eval_pid=$!
wait "$eval_pid"
eval_pid=
