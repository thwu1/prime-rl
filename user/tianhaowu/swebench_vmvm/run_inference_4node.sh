#!/bin/bash

set -euo pipefail

: "${SWEBENCH_INFERENCE_CONFIG:?Set SWEBENCH_INFERENCE_CONFIG}"
: "${SWEBENCH_INFERENCE_OUTPUT_ROOT:?Set SWEBENCH_INFERENCE_OUTPUT_ROOT}"
: "${SWEBENCH_EXPECTED_MODEL:?Set SWEBENCH_EXPECTED_MODEL}"
: "${SLURM_JOB_ID:?This launcher must run inside a Slurm allocation}"
: "${SLURM_JOB_NODELIST:?This launcher must run inside a Slurm allocation}"

project_dir=${PROJECT_DIR:-/storage/home/tianhaowu/prime-rl}
replicas=${SWEBENCH_INFERENCE_REPLICAS:-4}
router_port=${SWEBENCH_ROUTER_PORT:-8000}
backend_port=${SWEBENCH_BACKEND_PORT:-8100}
output_dir="$SWEBENCH_INFERENCE_OUTPUT_ROOT/run_${SLURM_JOB_ID}"

if [ "${SLURM_NNODES:-0}" -ne "$replicas" ]; then
    printf 'Expected %s inference nodes, got %s\n' "$replicas" "${SLURM_NNODES:-0}" >&2
    exit 1
fi

mapfile -t hostnames < <(scontrol show hostnames "$SLURM_JOB_NODELIST")
if [ "${#hostnames[@]}" -ne "$replicas" ]; then
    printf 'Expected %s hostnames, got %s\n' "$replicas" "${#hostnames[@]}" >&2
    exit 1
fi

mkdir -p "$output_dir/logs/inference"
config_path=$(realpath "$SWEBENCH_INFERENCE_CONFIG")
launcher_path=$(realpath "${SWEBENCH_INFERENCE_LAUNCHER:?Set SWEBENCH_INFERENCE_LAUNCHER}")
helper_path=$(realpath "${BASH_SOURCE[0]}")
cp "$config_path" "$output_dir/inference_config.toml"
cp "$launcher_path" "$output_dir/inference_launcher.sbatch"
cp "$helper_path" "$output_dir/inference_launcher_helper.sh"
printf '%s\n' "$SLURM_JOB_ID" > "$output_dir/inference_slurm_job.txt"

export PROJECT_DIR="$project_dir"
export CONFIG_PATH="$config_path"
export OUTPUT_DIR="$output_dir"
export EXPECTED_MODEL="$SWEBENCH_EXPECTED_MODEL"
export HOSTNAMES_STR="${hostnames[*]}"
export REPLICA_COUNT="$replicas"
export ROUTER_PORT="$router_port"
export BACKEND_PORT="$backend_port"
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export HF_HOME=/checkpoint/ram-h100-2/tianhaowu/.cache/huggingface
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export VLLM_ALLOW_LONG_MAX_MODEL_LEN=1
export TRITON_CACHE_DIR="/tmp/triton-cache-$USER-$SLURM_JOB_ID"
export VLLM_CACHE_ROOT="/tmp/vllm-cache-$USER-$SLURM_JOB_ID"
export FLASHINFER_WORKSPACE_BASE="/tmp/flashinfer-$USER-$SLURM_JOB_ID"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

router_url="http://${hostnames[0]}:${router_port}/v1"
printf 'INFERENCE_REPLICAS=%s\n' "$replicas"
printf 'INFERENCE_HOSTS=%s\n' "$HOSTNAMES_STR"
printf 'INFER_URL=%s\n' "$router_url"

srun --kill-on-bad-exit=1 --ntasks="$replicas" --ntasks-per-node=1 bash -c '
set -uo pipefail

cd "$PROJECT_DIR"
source "$UV_PROJECT_ENVIRONMENT/bin/activate"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

node_rank=$SLURM_PROCID
local_ip=$(hostname -I | awk "{print \$1}")
node_log="$OUTPUT_DIR/logs/inference/node_${node_rank}.log"
printf "INFER_NODE_RANK=%s LOCAL_IP=%s\n" "$node_rank" "$local_ip" | tee "$node_log"

ib_hca=$(ibv_devinfo 2>/dev/null | sed -n -e "/hca_id/p" -e "/link_layer:/p" | grep -B1 InfiniBand | grep hca_id | sed -e "s/^hca_id://g" | tr -d "[[:blank:]]" | paste -sd,)
if [ -n "$ib_hca" ]; then
    export NCCL_IB_HCA="$ib_hca"
fi
export NCCL_RAS_ENABLE=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:False

cleanup() {
    for pid in $(jobs -p); do
        kill -TERM "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

uv run --no-sync inference @ "$CONFIG_PATH" \
    --output-dir "$OUTPUT_DIR" \
    --server.host 0.0.0.0 \
    --server.port "$BACKEND_PORT" \
    --parallel.dp 1 \
    --data-parallel-size-local 1 \
    --api-server-count 1 \
    2>&1 | tee -a "$node_log" &
engine_pipeline_pid=$!

if [ "$node_rank" -eq 0 ]; then
    read -ra nodes <<< "$HOSTNAMES_STR"
    deadline=$((SECONDS + 7200))
    while true; do
        all_ready=1
        worker_urls=()
        for node in "${nodes[@]}"; do
            worker_url="http://${node}:${BACKEND_PORT}"
            worker_urls+=("$worker_url")
            if ! curl --noproxy "*" --fail --silent --max-time 10 \
                "$worker_url/v1/models" >/dev/null; then
                all_ready=0
            fi
        done
        if [ "$all_ready" -eq 1 ]; then
            break
        fi
        if ! kill -0 "$engine_pipeline_pid" 2>/dev/null; then
            wait "$engine_pipeline_pid"
            exit $?
        fi
        if [ "$SECONDS" -ge "$deadline" ]; then
            printf "Inference backends did not become ready within 7200 seconds\n" >&2
            exit 1
        fi
        sleep 15
    done

    printf "All %s inference replicas are ready for %s\n" "$REPLICA_COUNT" "$EXPECTED_MODEL"
    vllm-router \
        --policy consistent_hash \
        --request-id-headers x-session-id \
        --host 0.0.0.0 \
        --port "$ROUTER_PORT" \
        --worker-startup-timeout-secs 4200 \
        --log-level debug \
        --worker-urls "${worker_urls[@]}" \
        >> "$OUTPUT_DIR/logs/inference/router.log" 2>&1 &
fi

wait -n
status=$?
printf "[%s] inference component exited with status %s\n" "$(hostname)" "$status" >&2
exit "$status"
'
