#!/usr/bin/bash -p
#SBATCH --job-name=k3-mobius-2499-8103
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=7-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=72
#SBATCH --mem=96G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_mobius_2499_8103_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_mobius_2499_8103_%j.log

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
server_dir="$workflow_dir/configs/eval/servers/cpu-132-021_8103"
expected_revision=${KIMI_PRODUCTION_EXPECTED_PRIME_RL_REVISION:?}
selector=${KIMI_PRODUCTION_SELECTOR:?}
selector_receipt=${KIMI_PRODUCTION_SELECTOR_RECEIPT:?}
selector_receipt_sha256=${KIMI_PRODUCTION_SELECTOR_RECEIPT_SHA256:?}
promotion=${KIMI_PRODUCTION_PROMOTION:?}
promotion_sha256=${KIMI_PRODUCTION_PROMOTION_SHA256:?}
concurrency=${KIMI_PRODUCTION_CONCURRENCY:?}
dataset=${KIMI_PRODUCTION_DATASET:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9}
image_manifest=${KIMI_PRODUCTION_IMAGE_MANIFEST:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.sandoq.json}
deployment_root=${KIMI_PRODUCTION_DEPLOYMENT_ROOT:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/kimi-k3-deployment-cpu132021-rollover-20260923-v2}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_ram_prime_f7313db4}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
eval_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals
generation_dir="$eval_root/kimi_k3_production_generation_cpu-132-021_8103_${SLURM_JOB_ID:?}"
output_dir="$eval_root/mobius_kimi_k3_sandoq_cpu-132-021_8103_${SLURM_JOB_ID}_2499"
manifest="$generation_dir/direct_kimi_workers.json"
urls_file="$generation_dir/worker_urls.private.txt"
ports_file="$generation_dir/router_ports.private.txt"
resolved_config="$generation_dir/mobius_kimi_k3_sandoq_2499.toml"
launch_certificate="$generation_dir/kimi_sandoq_launch.json"
router_log="$generation_dir/direct_router.log"
router_stats="$generation_dir/direct_router_stats.private.json"
deployment_snapshot="$generation_dir/deployment_source"
provider_profile="$workflow_dir/configs/provider_context/use2/kimi_sandoq_firecracker_host.json"
provider_profile_sha256=7dd88ca6c6cde5ed5b22bf8f621462a46425f939478f79469e31da2e582b27df
miniswe_compatibility_receipt=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/qwen-miniswe246-sandoq-3step-20260921/run-1537041/receipt.json
miniswe_compatibility_sha256=cee344d3c9bc3c18f602a0ad217ade7395db263d50cd8d4c428507a21de86220
template="$server_dir/mobius_kimi_k3_max_sandoq_2499.template.toml"
router_pid=

cleanup_router() {
    status=$?
    trap - EXIT INT TERM
    if [[ -n "$router_pid" ]] && kill -0 "$router_pid" 2>/dev/null; then
        kill -TERM -- "-$router_pid" 2>/dev/null || true
        wait "$router_pid" 2>/dev/null || true
    fi
    exit "$status"
}
trap cleanup_router EXIT INT TERM

[[ "$concurrency" =~ ^[1-9][0-9]*$ ]] || blocked concurrency_invalid
(( concurrency <= 64 )) || blocked concurrency_invalid
# The selector receipt is rederived from every selected task's canonical
# metadata and proves that agent and verifier requests fit the qualified
# 2-CPU / 4-GiB / 10-GiB Firecracker envelope before create-launch succeeds.
[[ "$expected_revision" =~ ^[0-9a-f]{40}$ ]] || blocked source_identity_invalid
[[ "$(git -C "$project_dir" rev-parse HEAD)" == "$expected_revision" ]] || blocked source_identity_invalid
[[ -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]] \
    || blocked source_identity_invalid
[[ -x "$x86_uv" && -d "$x86_site/pydantic" && -d "$sandoq_site/sandoq_client" ]] \
    || blocked runtime_unavailable
[[ -f "$provider_profile" && ! -L "$provider_profile" \
    && "$(sha256sum -- "$provider_profile" | cut -d' ' -f1)" == "$provider_profile_sha256" ]] \
    || blocked provider_profile_invalid
[[ -f "$miniswe_compatibility_receipt" && ! -L "$miniswe_compatibility_receipt" \
    && "$(stat -c '%a:%h:%u' -- "$miniswe_compatibility_receipt")" == "600:1:$(id -u)" \
    && "$(sha256sum -- "$miniswe_compatibility_receipt" | cut -d' ' -f1)" \
        == "$miniswe_compatibility_sha256" ]] \
    || blocked miniswe_compatibility_invalid
for path in "$selector" "$selector_receipt" "$promotion" "$dataset" "$image_manifest" "$template"; do
    [[ -e "$path" && ! -L "$path" ]] || blocked launch_input_invalid
done
[[ ! -e "$generation_dir" && ! -L "$generation_dir" && ! -e "$output_dir" && ! -L "$output_dir" ]] \
    || blocked output_namespace_not_fresh

mkdir -m 700 -- "$generation_dir"
exec 8>"$generation_dir/.direct_router.lock"
chmod 0600 "$generation_dir/.direct_router.lock"
flock -n 8 || blocked router_generation_busy

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${SLURM_TMPDIR:-/tmp}/kimi-production-pycache-${SLURM_JOB_ID}"
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site"

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" snapshot-source \
    --deployment-root "$deployment_root" --output-root "$deployment_snapshot" >/dev/null

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" prepare \
    --deployment-root "$deployment_snapshot" \
    --output-root "$generation_dir" \
    --manifest "$manifest" \
    --urls-output "$urls_file" \
    --ports-output "$ports_file" \
    --capacity-profile sandoq-c64-v1 \
    --endpoint-identifier cpu-132-021_8103 \
    --probe
manifest_sha256=$(sha256sum -- "$manifest" | cut -d' ' -f1)

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/kimi_sandoq_production.py" create-launch \
    --project-root "$project_dir" \
    --expected-revision "$expected_revision" \
    --source "$workflow_dir/configs/eval/mobius_valid_tasks_2500.txt" \
    --dataset "$dataset" \
    --selector "$selector" \
    --selector-receipt "$selector_receipt" \
    --selector-receipt-sha256 "$selector_receipt_sha256" \
    --template "$template" \
    --image-manifest "$image_manifest" \
    --worker-manifest "$manifest" \
    --worker-manifest-sha256 "$manifest_sha256" \
    --promotion "$promotion" \
    --promotion-sha256 "$promotion_sha256" \
    --concurrency "$concurrency" \
    --run-output-dir "$output_dir" \
    --config-output "$resolved_config" \
    --launch-output "$launch_certificate" \
    --private-output-root "$generation_dir" >/dev/null
launch_sha256=$(sha256sum -- "$launch_certificate" | cut -d' ' -f1)

mapfile -t worker_urls < "$urls_file"
mapfile -t router_ports < "$ports_file"
[[ ${#worker_urls[@]} -eq 24 && ${#router_ports[@]} -eq 2 ]] || blocked router_generation_invalid
router_port=${router_ports[0]}
metrics_port=${router_ports[1]}

while IFS= read -r variable_name; do
    [[ ${variable_name,,} == *_proxy ]] && unset "$variable_name"
done < <(compgen -e)
setsid "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_router.py" \
    --worker-urls-file "$urls_file" \
    --host 127.0.0.1 \
    --port "$router_port" \
    --metrics-port "$metrics_port" \
    --capacity-profile sandoq-c64-v1 \
    --endpoint-identifier cpu-132-021_8103 >"$router_log" 2>&1 &
router_pid=$!

for attempt in $(seq 1 120); do
    kill -0 "$router_pid" 2>/dev/null || blocked router_start_failed
    active_workers=$(
        curl --noproxy '*' --fail --silent --show-error --max-time 10 \
            "http://127.0.0.1:${metrics_port}/metrics" 2>/dev/null \
            | awk '$1 == "vllm_router_active_workers" {print $2}' \
            | tail -n 1
    ) || true
    if [[ "$active_workers" == 24 ]] \
        && curl --noproxy '*' --fail --silent --show-error --max-time 10 \
            "http://127.0.0.1:${router_port}/v1/models" >/dev/null; then
        break
    fi
    (( attempt < 120 )) || blocked router_start_failed
    sleep 1
done

stage_env=(
    PROJECT_DIR="$project_dir"
    EVAL_CONFIG="$resolved_config"
    OUTPUT_DIR="$output_dir"
    DIRECT_KIMI_ROLE=kimi-direct-mobius
    DIRECT_KIMI_APPROVED_TASK_FILE="$selector"
    DIRECT_KIMI_APPROVED_TASK_FILE_SHA256="$(sha256sum -- "$selector" | cut -d' ' -f1)"
    DIRECT_KIMI_APPROVED_TASK_COUNT=2499
    DIRECT_KIMI_ROLLOUT_CONCURRENCY="$concurrency"
    DIRECT_KIMI_WORKER_MANIFEST="$manifest"
    DIRECT_KIMI_WORKER_MANIFEST_SHA256="$manifest_sha256"
    DIRECT_KIMI_BASE_URL="http://127.0.0.1:${router_port}/v1"
    DIRECT_KIMI_EXPECTED_PRIME_RL_REVISION="$expected_revision"
    DIRECT_KIMI_PRODUCTION_LAUNCH="$launch_certificate"
    DIRECT_KIMI_PRODUCTION_LAUNCH_SHA256="$launch_sha256"
    DIRECT_KIMI_MINISWE_COMPATIBILITY_RECEIPT_SHA256="$miniswe_compatibility_sha256"
)
ecr_token_file=${OCI_RUNNER_ECR_TOKEN_FILE:-/storage/home/tianhaowu/.config/oci-runner/ecr-token}
ecr_token_metadata=${OCI_RUNNER_ECR_TOKEN_METADATA_PATH:-${ecr_token_file}.metadata.json}
set +e
env "${stage_env[@]}" \
    "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" supervise \
    --profile "$provider_profile" \
    --profile-sha256 "$provider_profile_sha256" \
    --concurrency "$concurrency" \
    --lease-create-cap "$(( concurrency < 4 ? concurrency : 4 ))" \
    --startup-timeout-seconds 3600 \
    --lease-profile kimi-tb4-long \
    --ecr-token-file "$ecr_token_file" \
    --ecr-token-metadata "$ecr_token_metadata" \
    --project-root "$project_dir" \
    --sandoq-site "$sandoq_site" \
    -- /usr/bin/bash -p "$workflow_dir/run_direct_kimi_sandoq_production_stage.sh"
stage_status=$?
set -e

if [[ ! -f "$output_dir/eval_run_identity.json" \
    || ! -f "$output_dir/eval_invocations.jsonl" \
    || ! -f "$output_dir/provenance.txt" ]]; then
    (( stage_status != 0 )) && exit "$stage_status"
    blocked terminal_artifacts_missing
fi
kill -0 "$router_pid" 2>/dev/null || blocked router_exited_early
active_workers=$(
    curl --noproxy '*' --fail --silent --show-error --max-time 10 \
        "http://127.0.0.1:${metrics_port}/metrics" \
        | awk '$1 == "vllm_router_active_workers" {print $2}' \
        | tail -n 1
)
curl --noproxy '*' --fail --silent --show-error --max-time 10 \
    "http://127.0.0.1:${router_port}/stats" --output "$router_stats"
chmod 0600 "$router_stats"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" certify-router \
    --manifest "$manifest" \
    --manifest-sha256 "$manifest_sha256" \
    --active-workers "$active_workers" \
    --router-stats "$router_stats" \
    --eval-run-identity "$output_dir/eval_run_identity.json" \
    --eval-invocations "$output_dir/eval_invocations.jsonl" \
    --provenance "$output_dir/provenance.txt" \
    --output "$output_dir/direct_kimi_router_final.json"

kill -TERM -- "-$router_pid"
wait "$router_pid" 2>/dev/null || true
router_pid=
flock -u 8
printf '{"concurrency":%s,"selected_tasks":2499,"state":"terminal-artifacts-ready"}\n' "$concurrency"
exit "$stage_status"
