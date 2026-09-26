#!/bin/bash
#SBATCH --job-name=toolathlon-nemotron-inference
#SBATCH --partition=h100
#SBATCH --qos=h100_ram_high
#SBATCH --account=ram
#SBATCH --time=24:00:00
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:8
#SBATCH --exclusive
#SBATCH --output=/checkpoint/ram/tianhaowu/toolathlon_vmvm/inference-%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/toolathlon_vmvm/inference-%j.log

set -euo pipefail

project_dir=/storage/home/tianhaowu/prime-rl
config_path="${TOOLATHLON_INFERENCE_CONFIG:-$project_dir/user/tianhaowu/toolathlon_vmvm/nemotron_super_inference_4node_262k_h100_v2.toml}"
output_dir="${TOOLATHLON_INFERENCE_OUTPUT_DIR:-/checkpoint/ram/tianhaowu/toolathlon_vmvm/nemotron_super_base_inference_4node_262k_h100_v2}"

export PROJECT_DIR="$project_dir"
export CONFIG_PATH="$config_path"
export OUTPUT_DIR="$output_dir"
export ROUTER_PORT=8000
export BACKEND_PORT=8100
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export HF_HOME=/checkpoint/ram-h100-2/tianhaowu/.cache/huggingface
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TRITON_CACHE_DIR="/tmp/triton-cache-$USER-$SLURM_JOB_ID"
export VLLM_CACHE_ROOT="/tmp/vllm-cache-$USER-$SLURM_JOB_ID"
export FLASHINFER_WORKSPACE_BASE="/tmp/flashinfer-$USER-$SLURM_JOB_ID"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

mkdir -p "$OUTPUT_DIR/logs/inference"
rm -f "$OUTPUT_DIR/logs/inference/"*.log
ln -sfn inference/node_0.log "$OUTPUT_DIR/logs/inference.log"

mapfile -t hostnames < <(scontrol show hostnames "$SLURM_JOB_NODELIST")
export HOSTNAMES_STR="${hostnames[*]}"
router_url="http://${hostnames[0]}:$ROUTER_PORT/v1"
printf 'HOSTNAMES=%s\n' "$HOSTNAMES_STR"
printf 'INFER_URL=%s\n' "$router_url"

srun bash -s <<'CLEANUP_SH'
pkill -9 -f "[p]ython.*prime_rl" 2>/dev/null || true
pkill -9 -f "[t]orchrun" 2>/dev/null || true
pkill -9 -f "[v]llm-router" 2>/dev/null || true
pkill -9 -f "[v]llm" 2>/dev/null || true
pkill -9 -f "[p]rime_rl" 2>/dev/null || true
pkill -9 "vllm" 2>/dev/null || true
pkill -9 "vllm::.*" 2>/dev/null || true
rm -rf /dev/shm/vllm-* /dev/shm/vllm_* /tmp/vllm-* /tmp/vllm_* \
  /tmp/torch-* /tmp/torchelastic_* 2>/dev/null || true
CLEANUP_SH

srun --kill-on-bad-exit=1 bash -c '
set -o pipefail

cd "$PROJECT_DIR"
source "$UV_PROJECT_ENVIRONMENT/bin/activate"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

node_rank=$SLURM_PROCID
local_ip=$(hostname -I | awk "{print \$1}")
node_log="$OUTPUT_DIR/logs/inference/node_${node_rank}.log"
printf "INFER_NODE_RANK=%s LOCAL_IP=%s\n" "$node_rank" "$local_ip" | tee "$node_log"

ib_hca=$(ibv_devinfo 2>/dev/null | sed -n -e "/hca_id/p" -e "/link_layer:/p" | grep -B1 InfiniBand | grep hca_id | sed -e "s/^hca_id://g" | tr -d "[[:blank:]]" | paste -sd,)
if [[ -n "$ib_hca" ]]; then
  export NCCL_IB_HCA="$ib_hca"
fi

uv run --no-sync inference @ "$CONFIG_PATH" \
  --server.host 0.0.0.0 \
  --server.port "$BACKEND_PORT" \
  --parallel.dp 1 \
  --data-parallel-size-local 1 \
  --api-server-count 1 \
  2>&1 | tee -a "$node_log" &
engine_pipeline_pid=$!

if (( node_rank == 0 )); then
  read -ra nodes <<< "$HOSTNAMES_STR"
  deadline=$((SECONDS + 7200))
  while true; do
    all_ready=1
    worker_urls=()
    for node in "${nodes[@]}"; do
      worker_url="http://$node:$BACKEND_PORT"
      worker_urls+=("$worker_url")
      if ! curl --noproxy "*" --fail --silent --max-time 10 \
        "$worker_url/v1/models" >/dev/null; then
        all_ready=0
      fi
    done
    if (( all_ready == 1 )); then
      break
    fi
    if ! kill -0 "$engine_pipeline_pid" 2>/dev/null; then
      wait "$engine_pipeline_pid"
      exit $?
    fi
    if (( SECONDS >= deadline )); then
      echo "Inference backends did not become ready within 7200 seconds" >&2
      exit 1
    fi
    sleep 15
  done

  printf "All %d inference backends are ready\n" "${#worker_urls[@]}"
  vllm-router \
    --policy consistent_hash \
    --request-id-headers x-session-id \
    --host 0.0.0.0 \
    --port "$ROUTER_PORT" \
    --worker-startup-timeout-secs 120 \
    --log-level debug \
    --worker-urls "${worker_urls[@]}" \
    >> "$OUTPUT_DIR/logs/inference/router.log" 2>&1 &
fi

wait -n
status=$?
for pid in $(jobs -p); do
  kill -TERM "$pid" 2>/dev/null || true
done
exit "$status"
'
