#!/bin/bash
#SBATCH --job-name=sft-render-length-filter
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=12:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/sft_render_length_filter_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/sft_render_length_filter_%j.log

set -euo pipefail
umask 077

required=(
    SFT_FILTER_PROJECT_DIR
    SFT_FILTER_EXPECTED_REVISION
    SFT_FILTER_SOURCE_ROOT
    SFT_FILTER_SOURCE_MANIFEST_SHA256
    SFT_FILTER_OUTPUT_ROOT
    SFT_FILTER_TOKENIZER_SNAPSHOT
    SFT_FILTER_TOKENIZER_SHA256
)
for variable in "${required[@]}"; do
    [[ -n ${!variable:-} ]] || { printf '{"code":"required_environment_missing","state":"error"}\n'; exit 2; }
done
[[ $(uname -m) == x86_64 ]] || { printf '{"code":"x86_64_required","state":"error"}\n'; exit 2; }

project_dir=$SFT_FILTER_PROJECT_DIR
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
python_bin=${PYTHON_BIN_X86_64:-python3}
[[ -x $x86_uv && -d $x86_site && -f $workflow_dir/filter_sft_render_length.py ]] \
    || { printf '{"code":"x86_runtime_unavailable","state":"error"}\n'; exit 2; }

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/src:$project_dir/packages/prime-rl-configs/src"
export PYTHONPATH="$PYTHONPATH:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/filter_sft_render_length.py" \
    --source-root "$SFT_FILTER_SOURCE_ROOT" \
    --source-manifest-sha256 "$SFT_FILTER_SOURCE_MANIFEST_SHA256" \
    --output-root "$SFT_FILTER_OUTPUT_ROOT" \
    --project-dir "$project_dir" \
    --expected-project-revision "$SFT_FILTER_EXPECTED_REVISION" \
    --tokenizer-snapshot "$SFT_FILTER_TOKENIZER_SNAPSHOT" \
    --tokenizer-sha256 "$SFT_FILTER_TOKENIZER_SHA256"
