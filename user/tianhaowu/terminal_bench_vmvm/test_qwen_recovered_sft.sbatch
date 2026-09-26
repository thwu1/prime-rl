#!/bin/bash
#SBATCH --job-name=qwen-recovered-sft-tests
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_recovered_sft_tests_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_recovered_sft_tests_%j.log

set -euo pipefail
umask 077

fail() {
    printf '{"code":"%s","state":"error"}\n' "$1" >&2
    exit 2
}

(( $# == 0 )) || fail arguments_forbidden
project=${QWEN_RECOVERED_SFT_TEST_PROJECT_DIR:-}
revision=${QWEN_RECOVERED_SFT_TEST_EXPECTED_REVISION:-}
[[ -n $project && -n $revision && $revision =~ ^[0-9a-f]{40}$ ]] \
    || fail required_environment_invalid
[[ $(uname -m) == x86_64 ]] || fail x86_64_required
project=$(realpath -e -- "$project")
[[ "$(git -C "$project" rev-parse --show-toplevel)" == "$project" \
    && "$(git -C "$project" rev-parse HEAD)" == "$revision" \
    && "$(git -C "$project" rev-parse --abbrev-ref HEAD)" == HEAD \
    && -z "$(git -C "$project" status --porcelain=v1 --untracked-files=all)" ]] \
    || fail source_identity_invalid

workflow="$project/user/tianhaowu/terminal_bench_vmvm"
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
python_bin=${PYTHON_BIN_X86_64:-python3}
test_file="$workflow/tests/test_finalize_qwen_recovered_sft.py"
[[ -x $x86_uv && -d $x86_site && -f $test_file && ! -L $test_file ]] \
    || fail x86_runtime_unavailable

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow:$project/src:$project/packages/prime-rl-configs/src"
export PYTHONPATH="$PYTHONPATH:$project/environments/vmvm_tb_v2:$project/deps/verifiers"
export PYTHONPATH="$PYTHONPATH:$project/deps/renderers:$project/deps/pydantic-config/src:$x86_site"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
cd "$project"
exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 -m pytest -q "$test_file"
