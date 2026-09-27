#!/usr/bin/bash -p
#SBATCH --job-name=k3-small-task-image-c64
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --signal=B:TERM@1800
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=72
#SBATCH --mem=96G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_small_task_image_c64_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_small_task_image_c64_%j.log

set +x
set -euo pipefail
umask 077

kind=kimi-k3-stock-small-task-image-c64-soak
blocked() {
    printf '{"code":"%s","kind":"%s","state":"blocked"}\n' "$1" "$kind" >&2
    exit 2
}

(( $# == 0 )) || blocked arguments_forbidden

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
tool="$workflow_dir/kimi_stock_small_task_image_soak.py"
launcher="$workflow_dir/run_kimi_stock_small_task_image_soak.sbatch"
provider_profile="$workflow_dir/configs/provider_context/use2/cpu-132-021_8103/kimi_sandoq_firecracker_small_host.json"
provider_profile_sha256=247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084
expected_revision=${KIMI_TASK_IMAGE_SOAK_EXPECTED_REVISION:?}
plan=${KIMI_TASK_IMAGE_SOAK_PLAN:?}
plan_sha256=${KIMI_TASK_IMAGE_SOAK_PLAN_SHA256:?}
output_root=${KIMI_TASK_IMAGE_SOAK_OUTPUT_ROOT:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/kimi-stock-small-task-image-c64-soak-20260927}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_sdk1_82068}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
ecr_token_file=${OCI_RUNNER_ECR_TOKEN_FILE:-/storage/home/tianhaowu/.config/oci-runner/ecr-token}
ecr_token_metadata=${OCI_RUNNER_ECR_TOKEN_METADATA_PATH:-/storage/home/tianhaowu/.config/oci-runner/ecr-rotation.state.json}
deployment_root=${KIMI_TASK_IMAGE_SOAK_DEPLOYMENT_ROOT:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/kimi-k3-stock-single-1593665-20260927-v1}

[[ "$expected_revision" =~ ^[0-9a-f]{40}$ \
    && "$plan_sha256" =~ ^[0-9a-f]{64}$ \
    && "${SLURM_JOB_ID:-}" =~ ^[1-9][0-9]*$ \
    && -f "$tool" && ! -L "$tool" \
    && -f "$launcher" && ! -L "$launcher" \
    && -f "$provider_profile" && ! -L "$provider_profile" \
    && "$(sha256sum -- "$provider_profile" | cut -d' ' -f1)" == "$provider_profile_sha256" \
    && -x "$x86_uv" && -d "$x86_site/pydantic" && -d "$sandoq_site/sandoq_client" ]] \
    || blocked launch_inputs_invalid
[[ "$(git -C "$project_dir" rev-parse HEAD)" == "$expected_revision" \
    && -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" \
    && -z "$(git -C "$project_dir/deps/verifiers" status --porcelain=v1 --untracked-files=all)" \
    && "$(git -C "$project_dir/deps/verifiers" rev-parse HEAD)" == 36b0dff6c18affb3d40b7c46d5836381d568050b ]] \
    || blocked source_identity_invalid

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${SLURM_TMPDIR:-/tmp}/k3-task-image-soak-pycache-${SLURM_JOB_ID}"
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site"

binding=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$tool" verify --plan "$plan" --plan-sha256 "$plan_sha256" --format tsv
) || blocked plan_invalid
IFS=$'\t' read -r verified_revision selected_tasks selector_sha256 binding_extra <<< "$binding"
[[ -z "$binding_extra" && "$binding" != *$'\n'* \
    && "$verified_revision" == "$expected_revision" \
    && "$selected_tasks" == 2499 \
    && "$selector_sha256" =~ ^[0-9a-f]{64}$ ]] || blocked plan_binding_invalid

if [[ -e "$output_root" || -L "$output_root" ]]; then
    [[ -d "$output_root" && ! -L "$output_root" \
        && "$(realpath -e -- "$output_root")" == "$output_root" \
        && "$(stat -c '%u:%a' -- "$output_root")" == "$(id -u):700" ]] \
        || blocked output_root_invalid
else
    install -d -m 0700 -- "$output_root"
fi
run_dir="$output_root/run-${SLURM_JOB_ID}"
[[ ! -e "$run_dir" && ! -L "$run_dir" ]] || blocked output_not_fresh
mkdir -m 0700 -- "$run_dir"
mkdir -m 0700 -- "$run_dir/control"

# Capture the exact stock endpoint epoch and at least six days of remaining
# walltime before any of the 64 task sandboxes can be started.
generation_dir="$run_dir/endpoint-generation"
deployment_snapshot="$generation_dir/deployment_source"
worker_manifest="$generation_dir/direct_kimi_workers.json"
worker_urls="$generation_dir/worker_urls.private.txt"
router_ports="$generation_dir/router_ports.private.txt"
walltime_receipt="$run_dir/endpoint-walltime.json"
mkdir -m 0700 -- "$generation_dir"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" snapshot-source \
    --deployment-root "$deployment_root" --output-root "$deployment_snapshot" \
    --capacity-profile sandoq-stock-single-c64-v1 >/dev/null 2>&1 \
    || blocked endpoint_snapshot_failed
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" prepare \
    --deployment-root "$deployment_snapshot" --output-root "$generation_dir" \
    --manifest "$worker_manifest" --urls-output "$worker_urls" --ports-output "$router_ports" \
    --capacity-profile sandoq-stock-single-c64-v1 \
    --endpoint-identifier tianhaowu-kimi-k3-stock-eval-20260927 \
    --request-timeout-seconds 144000 --probe >/dev/null 2>&1 \
    || blocked endpoint_manifest_failed
worker_manifest_sha256=$(sha256sum -- "$worker_manifest" | cut -d' ' -f1)
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/kimi_endpoint_walltime_gate.py" capture \
    --manifest "$worker_manifest" --manifest-sha256 "$worker_manifest_sha256" \
    --profile tb4-extended-c24-stock-single-three-wave-v1 \
    --minimum-remaining-seconds 518400 --task-count 64 \
    --deployment tianhaowu-kimi-k3-stock-eval-20260927 \
    --output "$walltime_receipt" >/dev/null 2>&1 \
    || blocked endpoint_walltime_failed
walltime_receipt_sha256=$(sha256sum -- "$walltime_receipt" | cut -d' ' -f1)

pool_socket_dir="${SLURM_TMPDIR:-/tmp}/oci-runner-pool-$(id -u)"
mkdir -p -m 0700 -- "$pool_socket_dir"
export PRIME_RL_OUTPUT_DIR="$run_dir"
export OCI_RUNNER_POOL_SOCKET="$pool_socket_dir/${SLURM_JOB_ID}.sock"
export OCI_RUNNER_POOL_WAL="$run_dir/control/sandoq-pool.wal.jsonl"
export OCI_RUNNER_POOL_EVENT_LOG="$run_dir/pool_events.jsonl"

set +e
env SANDOQ_PROVIDER_TERMINATION_GRACE_SECONDS=1200 \
    "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" supervise \
    --profile "$provider_profile" --profile-sha256 "$provider_profile_sha256" \
    --concurrency 64 --lease-create-cap 8 --startup-timeout-seconds 3600 \
    --lease-profile kimi-tb4-long --ecr-token-file "$ecr_token_file" \
    --ecr-token-metadata "$ecr_token_metadata" --project-root "$project_dir" \
    --sandoq-site "$sandoq_site" \
    -- "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$tool" run --plan "$plan" --plan-sha256 "$plan_sha256" --output "$run_dir" \
    --worker-manifest "$worker_manifest" --worker-manifest-sha256 "$worker_manifest_sha256" \
    --walltime-receipt "$walltime_receipt" --walltime-receipt-sha256 "$walltime_receipt_sha256" \
    >/dev/null 2>&1
run_status=$?
set -e
(( run_status == 0 )) || blocked task_image_soak_failed

receipt="$run_dir/receipt.json"
result=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$tool" certify --plan "$plan" --plan-sha256 "$plan_sha256" \
        --run-root "$run_dir" --output "$receipt"
) || blocked certification_failed
receipt_sha256=$(sha256sum -- "$receipt" | cut -d' ' -f1)
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$tool" validate-receipt --receipt "$receipt" \
    --receipt-sha256 "$receipt_sha256" --expected-revision "$expected_revision" \
    >/dev/null || blocked receipt_revalidation_failed
printf '%s\n' "$result"
