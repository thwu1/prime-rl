#!/usr/bin/bash -p
#SBATCH --job-name=k3-small-image-c1-probe
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=03:00:00
#SBATCH --signal=B:TERM@900
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_small_image_c1_probe_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_small_image_c1_probe_%j.log

set +x
set -euo pipefail
umask 077

kind=kimi-k3-stock-small-single-image-provisioning-probe
blocked() {
    printf '{"code":"%s","kind":"%s","state":"blocked"}\n' "$1" "$kind" >&2
    exit 2
}

(( $# == 0 )) || blocked arguments_forbidden

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
tool="$workflow_dir/kimi_stock_small_single_image_probe.py"
launcher="$workflow_dir/run_kimi_stock_small_single_image_probe.sbatch"
provider_profile="$workflow_dir/configs/provider_context/use2/cpu-132-021_8103/kimi_sandoq_firecracker_small_host.json"
provider_profile_sha256=247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084
expected_revision=${KIMI_SINGLE_IMAGE_PROBE_EXPECTED_REVISION:?}
plan=${KIMI_SINGLE_IMAGE_PROBE_PLAN:?}
plan_sha256=${KIMI_SINGLE_IMAGE_PROBE_PLAN_SHA256:?}
output_root=${KIMI_SINGLE_IMAGE_PROBE_OUTPUT_ROOT:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/kimi-stock-small-single-image-probe-20260928}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_sdk1_82068}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
ecr_token_file=${OCI_RUNNER_ECR_TOKEN_FILE:-/storage/home/tianhaowu/.config/oci-runner/ecr-token}
ecr_token_metadata=${OCI_RUNNER_ECR_TOKEN_METADATA_PATH:-/storage/home/tianhaowu/.config/oci-runner/ecr-rotation.state.json}

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
export PYTHONPYCACHEPREFIX="${SLURM_TMPDIR:-/tmp}/k3-single-image-probe-pycache-${SLURM_JOB_ID}"
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site"

binding=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$tool" verify --plan "$plan" --plan-sha256 "$plan_sha256" --format tsv
) || blocked plan_invalid
IFS=$'\t' read -r verified_revision concurrency probe_attempts binding_extra <<< "$binding"
[[ -z "$binding_extra" && "$binding" != *$'\n'* \
    && "$verified_revision" == "$expected_revision" \
    && "$concurrency" == 1 \
    && "$probe_attempts" == 3 ]] || blocked plan_binding_invalid

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

pool_socket_dir="${SLURM_TMPDIR:-/tmp}/oci-runner-pool-$(id -u)"
mkdir -p -m 0700 -- "$pool_socket_dir"
export PRIME_RL_OUTPUT_DIR="$run_dir"
export OCI_RUNNER_POOL_SOCKET="$pool_socket_dir/${SLURM_JOB_ID}.sock"
export OCI_RUNNER_POOL_WAL="$run_dir/control/sandoq-pool.wal.jsonl"
export OCI_RUNNER_POOL_EVENT_LOG="$run_dir/pool_events.jsonl"
export KIMI_SINGLE_IMAGE_PROBE_STATUS_FILE="$run_dir/control/single-image-probe-status.json"

set +e
env SANDOQ_PROVIDER_TERMINATION_GRACE_SECONDS=600 \
    "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" supervise \
    --profile "$provider_profile" --profile-sha256 "$provider_profile_sha256" \
    --concurrency 1 --lease-create-cap 1 --startup-timeout-seconds 1800 \
    --lease-profile kimi-tb4-long --ecr-token-file "$ecr_token_file" \
    --ecr-token-metadata "$ecr_token_metadata" --project-root "$project_dir" \
    --sandoq-site "$sandoq_site" \
    -- "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$tool" run --plan "$plan" --plan-sha256 "$plan_sha256" --output "$run_dir" \
    >/dev/null 2>&1
run_status=$?
set -e
if (( run_status != 0 )); then
    child_code=single_image_probe_failed
    if [[ -f "$KIMI_SINGLE_IMAGE_PROBE_STATUS_FILE" && ! -L "$KIMI_SINGLE_IMAGE_PROBE_STATUS_FILE" \
        && "$(stat -c '%u:%a' -- "$KIMI_SINGLE_IMAGE_PROBE_STATUS_FILE")" == "$(id -u):600" ]]; then
        parsed_code=$(
            jq -er \
                'if (keys | sort) == ["code","kind","schema_version","state"] and .schema_version == 1 and .kind == "kimi-k3-stock-small-single-image-provisioning-probe" and .state == "blocked" and (.code | type) == "string" then .code else error("invalid") end' \
                "$KIMI_SINGLE_IMAGE_PROBE_STATUS_FILE" 2>/dev/null
        ) || parsed_code=
        if [[ "$parsed_code" =~ ^[a-z][a-z0-9_]{0,127}$ ]]; then
            child_code=$parsed_code
        fi
    fi
    blocked "$child_code"
fi

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
