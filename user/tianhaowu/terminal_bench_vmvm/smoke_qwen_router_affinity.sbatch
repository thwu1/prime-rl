#!/bin/bash
#SBATCH --job-name=qwen-affinity-smoke
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=00:10:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=4G
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_affinity_smoke_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_affinity_smoke_%j.log

set -euo pipefail

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
router_site=${DIRECT_ROUTER_SITE:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/vllm_router_x86_64_0.1.26}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}

if [[ "$(uname -m)" != x86_64 \
    || ! -x "$x86_uv" \
    || ! -d "$router_site/site-packages/vllm_router-0.1.26.dist-info" ]]; then
    printf 'Pinned x86_64 vllm-router runtime is unavailable\n' >&2
    exit 2
fi

exec "$x86_uv" run --no-project --offline --python python3 \
    python3 "$workflow_dir/smoke_qwen_router_affinity.py" \
    --router-site "$router_site/site-packages"
