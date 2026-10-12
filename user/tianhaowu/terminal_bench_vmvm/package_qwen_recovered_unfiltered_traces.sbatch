#!/bin/bash
#SBATCH --job-name=qwen-recovered-package
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_recovered_package_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_recovered_package_%j.log

set -euo pipefail
umask 077
export PATH=/usr/local/bin:/usr/bin:/bin

fail() {
    printf '{"code":"%s","state":"error"}\n' "$1" >&2
    exit 2
}

project=${QWEN_V6_PACKAGE_PROJECT_DIR:-}
expected_revision=${QWEN_V6_PACKAGE_EXPECTED_PROJECT_REVISION:-}
expected_packager_sha256=${QWEN_V6_PACKAGE_PACKAGER_SHA256:-}
expected_worker_sha256=${QWEN_V6_PACKAGE_WORKER_SHA256:-}
[[ -n $project && $expected_revision =~ ^[0-9a-f]{40}$ \
    && $expected_packager_sha256 =~ ^[0-9a-f]{64}$ \
    && $expected_worker_sha256 =~ ^[0-9a-f]{64}$ ]] \
    || fail package_environment_invalid
packager="$project/user/tianhaowu/terminal_bench_vmvm/package_qwen_recovered_unfiltered_traces.sh"
worker="$project/user/tianhaowu/terminal_bench_vmvm/package_qwen_recovered_unfiltered_traces.sbatch"
[[ -f $packager && ! -L $packager && -f $worker && ! -L $worker \
    && "$(git -C "$project" rev-parse --show-toplevel)" == "$project" \
    && "$(git -C "$project" rev-parse HEAD)" == "$expected_revision" \
    && -z "$(git -C "$project" status --porcelain=v1 --untracked-files=all)" \
    && "$(sha256sum "$packager" | cut -d' ' -f1)" == "$expected_packager_sha256" \
    && "$(sha256sum "$worker" | cut -d' ' -f1)" == "$expected_worker_sha256" ]] \
    || fail package_source_invalid

exec bash "$packager"
