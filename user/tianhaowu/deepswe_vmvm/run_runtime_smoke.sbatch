#!/bin/bash
#SBATCH --job-name=deepswe-vmvm-smoke
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=00:10:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_vmvm/logs/runtime_smoke_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/deepswe_vmvm/logs/runtime_smoke_%j.log

set -euo pipefail

project_dir=/storage/home/tianhaowu/prime-rl
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
python_bin=${PYTHON_BIN_X86_64:-python3}
mkdir -p /checkpoint/ram/tianhaowu/deepswe_vmvm/logs
cd "$project_dir"

if [[ "$(uname -m)" != x86_64 || ! -x "$x86_uv" || ! -d "$x86_site/pydantic" ]]; then
    printf 'Missing x86_64 runtime dependencies\n' >&2
    exit 2
fi

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/environments/vmvm_tb_v2:$x86_site${PYTHONPATH:+:$PYTHONPATH}"

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 user/tianhaowu/deepswe_vmvm/smoke_runtime.py
