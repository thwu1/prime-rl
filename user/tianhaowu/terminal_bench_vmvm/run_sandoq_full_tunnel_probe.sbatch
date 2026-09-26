#!/usr/bin/bash -p
#SBATCH --job-name=sandoq-full-tunnel
#SBATCH --partition=cpu_x86
#SBATCH --account=ram
#SBATCH --time=00:10:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/sandoq_full_tunnel_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/sandoq_full_tunnel_%j.log

set +x
set -euo pipefail
umask 077

blocked() {
    printf '{"kind":"sandoq-firecracker-tunnel-capability","state":"blocked"}\n' >&2
    exit 2
}

(( $# == 0 )) || blocked
project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
probe="$workflow_dir/probe_sandoq_full_tunnel.py"
expected_revision=${SANDOQ_FULL_TUNNEL_EXPECTED_REVISION:?}
expected_probe_sha256=${SANDOQ_FULL_TUNNEL_PROBE_SHA256:?}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_sdk1_82068}
output_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/sandoq-full-tunnel-20260922
output_dir="$output_root/run-${SLURM_JOB_ID:?}"

[[ "$expected_revision" =~ ^[0-9a-f]{40}$ \
    && "$(git -C "$project_dir" rev-parse HEAD)" == "$expected_revision" \
    && -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]] || blocked
[[ "$expected_probe_sha256" =~ ^[0-9a-f]{64}$ \
    && -f "$probe" && ! -L "$probe" \
    && "$(sha256sum -- "$probe" | cut -d' ' -f1)" == "$expected_probe_sha256" \
    && -x "$x86_uv" && -d "$sandoq_site/sandoq_client" ]] || blocked
[[ ! -e "$output_dir" && ! -L "$output_dir" ]] || blocked
install -d -m 700 -- "$output_root"
mkdir -m 700 -- "$output_dir"

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
unset SANDOQ_TUNNEL_HTTPS_PROXY SANDOQ_AUTH_TOKEN FIRECRACKER_KEY
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$project_dir/extensions/sandoq:$sandoq_site"

exec "$x86_uv" run --no-project --offline --python python3 \
    "$probe" --output "$output_dir/receipt.json"
