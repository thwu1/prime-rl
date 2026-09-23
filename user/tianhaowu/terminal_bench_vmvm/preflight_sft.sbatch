#!/bin/bash
#SBATCH --job-name=sft-render-preflight
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=12:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/sft_render_preflight_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/sft_render_preflight_%j.log

set -euo pipefail
umask 077

required=(
    SFT_PREFLIGHT_PROJECT_DIR
    SFT_PREFLIGHT_EXPECTED_REVISION
    SFT_PREFLIGHT_EXPORT_ROOT
    SFT_PREFLIGHT_MANIFEST_SHA256
    SFT_PREFLIGHT_REQUIRE_EXACT_PROVIDER_JSON
    SFT_PREFLIGHT_TOKENIZER_SNAPSHOT
    SFT_PREFLIGHT_TOKENIZER_SHA256
    SFT_PREFLIGHT_OUTPUT
)
for variable in "${required[@]}"; do
    [[ -n ${!variable:-} ]] || { printf '{"code":"required_environment_missing","state":"error"}\n'; exit 2; }
done
if [[ $SFT_PREFLIGHT_REQUIRE_EXACT_PROVIDER_JSON != 0 \
    && $SFT_PREFLIGHT_REQUIRE_EXACT_PROVIDER_JSON != 1 ]]; then
    printf '{"code":"provider_json_expectation_invalid","state":"error"}\n'
    exit 2
fi
[[ $(uname -m) == x86_64 ]] || { printf '{"code":"x86_64_required","state":"error"}\n'; exit 2; }

project_dir=$SFT_PREFLIGHT_PROJECT_DIR
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
python_bin=${PYTHON_BIN_X86_64:-python3}
renderer_wheel_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/preflight_wheels
renderer_wheel_name=renderers_044d9e2541f6a911cacae9da353fc063911ef1f8/renderers-0.1.8.dev42+g044d9e254-py3-none-any.whl
renderer_wheel_default="$renderer_wheel_root/$renderer_wheel_name"
renderer_wheel=${SFT_PREFLIGHT_RENDERER_WHEEL:-$renderer_wheel_default}
renderer_wheel_sha256=604753c8dcccc99eb59157c7159e1d80701b707b5be30d6fa6e9dda93f3a7602
[[ -x $x86_uv && -d $x86_site && -f $workflow_dir/preflight_sft.py \
    && -f $renderer_wheel && ! -L $renderer_wheel \
    && "$(sha256sum "$renderer_wheel" | cut -d' ' -f1)" == "$renderer_wheel_sha256" ]] \
    || { printf '{"code":"x86_runtime_unavailable","state":"error"}\n'; exit 2; }

provider_json_flag=--no-expected-require-exact-provider-json
if [[ $SFT_PREFLIGHT_REQUIRE_EXACT_PROVIDER_JSON == 1 ]]; then
    provider_json_flag=--expected-require-exact-provider-json
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/src:$project_dir/packages/prime-rl-configs/src"
export PYTHONPATH="$PYTHONPATH:$project_dir/deps/renderers:$renderer_wheel"
export PYTHONPATH="$PYTHONPATH:$project_dir/deps/pydantic-config/src:$x86_site"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/preflight_sft.py" \
    --export-root "$SFT_PREFLIGHT_EXPORT_ROOT" \
    --expected-manifest-sha256 "$SFT_PREFLIGHT_MANIFEST_SHA256" \
    --project-dir "$project_dir" \
    --expected-project-revision "$SFT_PREFLIGHT_EXPECTED_REVISION" \
    "$provider_json_flag" \
    --tokenizer-snapshot-path "$SFT_PREFLIGHT_TOKENIZER_SNAPSHOT" \
    --expected-tokenizer-snapshot-sha256 "$SFT_PREFLIGHT_TOKENIZER_SHA256" \
    --output "$SFT_PREFLIGHT_OUTPUT"
