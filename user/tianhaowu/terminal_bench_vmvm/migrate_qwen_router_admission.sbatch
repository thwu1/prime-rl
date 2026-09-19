#!/bin/bash
#SBATCH --job-name=qwen-cap32-migrate
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=00:20:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_cap32_migrate_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_cap32_migrate_%j.log

set -euo pipefail

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
source_dir=${SOURCE_DIR:-}
output_dir=${OUTPUT_DIR:-}

if [[ "$(uname -m)" != x86_64 || ! -x "$x86_uv" || ! -d "$x86_site/pydantic" ]]; then
    printf 'Pinned x86_64 migration runtime is unavailable\n' >&2
    exit 2
fi
if [[ -z "$source_dir" || -z "$output_dir" ]]; then
    printf 'SOURCE_DIR and OUTPUT_DIR are required\n' >&2
    exit 2
fi
if [[ ! -d "$source_dir" || -e "$output_dir" || -L "$output_dir" ]]; then
    printf 'Migration source must exist and destination must not exist\n' >&2
    exit 2
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site"
cd "$project_dir"
exec "$x86_uv" run --no-project --offline --python python3 \
    python3 "$workflow_dir/migrate_qwen_router_affinity.py" migrate-admission \
    --source-dir "$source_dir" \
    --output-dir "$output_dir"
