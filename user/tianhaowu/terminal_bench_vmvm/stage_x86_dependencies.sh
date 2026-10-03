#!/usr/bin/env bash
# Run from the ARM login node to stage x86_64 wheels for network-isolated CPU jobs.
set -euo pipefail

project_dir=${PROJECT_DIR:-$(git rev-parse --show-toplevel)}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
target=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
requirements=${X86_REQUIREMENTS:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/requirements_x86_64.txt}
uv_bin=${UV_BIN:-uv}

mkdir -p "$target" "$(dirname "$requirements")"
# See deps/renderers/pyproject.toml: the checkout follows a historical .dev41
# tag, which hatch-vcs cannot increment without an explicit PEP 440 version.
export SETUPTOOLS_SCM_PRETEND_VERSION=0.1.8.dev42
"$uv_bin" export \
    --project "$workflow_dir" \
    --locked \
    --no-dev \
    --no-emit-local \
    --no-hashes \
    --output-file "$requirements"

# Run outside prime-rl so its root-level transformer override cannot leak into
# this independently locked dependency set.
(
    cd /tmp
    "$uv_bin" pip install \
        --target "$target" \
        --python-platform x86_64-unknown-linux-gnu \
        --python-version 3.12 \
        --requirements "$requirements"
)

printf 'staged x86_64 Python dependencies at %s\n' "$target"
