#!/usr/bin/env bash
# Stage the pinned x86-only router without modifying the live evaluator dependencies.
set -euo pipefail

project_dir=${PROJECT_DIR:-$(git rev-parse --show-toplevel)}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
target=${DIRECT_ROUTER_SITE:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/vllm_router_x86_64_0.1.26}
uv_bin=${UV_BIN:-uv}

if [[ -e "$target" ]]; then
    if [[ -f "$target/STAGED" \
        && -d "$target/site-packages/vllm_router-0.1.26.dist-info" \
        && "$(sed -n '1p' "$target/STAGED")" == "vllm-router=0.1.26" \
        && "$(sed -n '2p' "$target/STAGED")" == "platform=x86_64-manylinux_2_28" \
        && -f "$target/requirements.sha256" \
        && "$(sha256sum "$target/requirements.txt" | cut -d' ' -f1)" == "$(cat "$target/requirements.sha256")" ]]; then
        printf 'Pinned direct router is already staged at %s\n' "$target"
        exit 0
    fi
    printf 'Refusing to replace an incomplete direct-router path: %s\n' "$target" >&2
    exit 2
fi

mkdir -p "$(dirname "$target")"
temporary=$(mktemp -d "${target}.tmp.XXXXXX")
cleanup() {
    rm -rf -- "$temporary"
}
trap cleanup EXIT

export SETUPTOOLS_SCM_PRETEND_VERSION=0.1.8.dev42
"$uv_bin" export \
    --project "$workflow_dir" \
    --locked \
    --only-group direct-router \
    --no-emit-project \
    --no-header \
    --output-file "$temporary/requirements.txt"
(
    cd /tmp
    "$uv_bin" pip install \
        --target "$temporary/site-packages" \
        --python-platform x86_64-manylinux_2_28 \
        --python-version 3.12 \
        --only-binary :all: \
        --require-hashes \
        --requirements "$temporary/requirements.txt"
)

test -d "$temporary/site-packages/vllm_router-0.1.26.dist-info"
router_extension=$(find "$temporary/site-packages" -maxdepth 1 -type f -name 'vllm_router_rs*.so' -print -quit)
if [[ -z "$router_extension" ]] || ! file "$router_extension" | grep -q 'x86-64'; then
    printf 'Staged router does not contain the expected x86-64 extension\n' >&2
    exit 2
fi
sha256sum "$temporary/requirements.txt" | cut -d' ' -f1 > "$temporary/requirements.sha256"
printf 'vllm-router=0.1.26\nplatform=x86_64-manylinux_2_28\n' > "$temporary/STAGED"
chmod -R a-w "$temporary"
mv -T -- "$temporary" "$target"
trap - EXIT
printf 'Staged pinned direct router at %s\n' "$target"
