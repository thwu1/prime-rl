#!/usr/bin/bash -p
#SBATCH --job-name=k3-tb4-union-cert
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_union_cert_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_union_cert_%j.log

set +x
set -euo pipefail
umask 077

blocked() {
    printf '{"code":"%s","state":"blocked"}\n' "$1" >&2
    exit 2
}

(( $# == 0 )) || blocked arguments_forbidden
project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
expected_revision=${KIMI_TB4_UNION_EXPECTED_PRIME_RL_REVISION:?}
launch_plan=${KIMI_TB4_MINISWE_UNION_PLAN:?}
launch_plan_sha256=${KIMI_TB4_MINISWE_UNION_PLAN_SHA256:?}
sandoq_certificate=${KIMI_TB4_UNION_SANDOQ_CERTIFICATE:?}
sandoq_certificate_sha256=${KIMI_TB4_UNION_SANDOQ_CERTIFICATE_SHA256:?}
vmvm_certificate=${KIMI_TB4_UNION_VMVM_CERTIFICATE:?}
vmvm_certificate_sha256=${KIMI_TB4_UNION_VMVM_CERTIFICATE_SHA256:?}
output=${KIMI_TB4_UNION_OUTPUT:?}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}

[[ "$expected_revision" =~ ^[0-9a-f]{40}$ \
    && "$(git -C "$project_dir" rev-parse HEAD)" == "$expected_revision" \
    && -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" \
    && "$(git -C "$project_dir/deps/verifiers" rev-parse HEAD)" \
        == 3df6efa9e9f6bdc8a013df7759a03074aec79111 ]] \
    || blocked source_identity_invalid
[[ "$launch_plan" == /* && "$sandoq_certificate" == /* \
    && "$vmvm_certificate" == /* && "$output" == /* ]] || blocked path_not_absolute
[[ -x "$x86_uv" && -d "$x86_site" && ! -e "$output" && ! -L "$output" ]] || blocked output_invalid
for binding in \
    "$launch_plan:$launch_plan_sha256" \
    "$sandoq_certificate:$sandoq_certificate_sha256" \
    "$vmvm_certificate:$vmvm_certificate_sha256"; do
    path=${binding%:*}
    digest=${binding##*:}
    [[ "$digest" =~ ^[0-9a-f]{64}$ && -f "$path" && ! -L "$path" \
        && "$(stat -c '%a:%h:%u' -- "$path")" == "600:1:$(id -u)" \
        && "$(sha256sum -- "$path" | cut -d' ' -f1)" == "$digest" ]] \
        || blocked certificate_input_invalid
done

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site"
exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/certify_kimi_tb4_miniswe246_union.py" merge \
    --launch-plan "$launch_plan" --launch-plan-sha256 "$launch_plan_sha256" \
    --sandoq-certificate "$sandoq_certificate" \
    --sandoq-certificate-sha256 "$sandoq_certificate_sha256" \
    --vmvm-certificate "$vmvm_certificate" \
    --vmvm-certificate-sha256 "$vmvm_certificate_sha256" \
    --output "$output"
