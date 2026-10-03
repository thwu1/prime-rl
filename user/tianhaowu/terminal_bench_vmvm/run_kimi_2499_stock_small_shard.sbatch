#!/usr/bin/bash -p
#SBATCH --job-name=k3-2499-stock-small
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=7-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=72
#SBATCH --mem=96G
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@1800
#SBATCH --array=0-39%1
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_2499_stock_small_%A_%a.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_2499_stock_small_%A_%a.log

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
expected_revision=${KIMI_STOCK_SMALL_EXPECTED_PRIME_RL_REVISION:?}
plan=${KIMI_STOCK_SMALL_PLAN:?}
plan_sha256=${KIMI_STOCK_SMALL_PLAN_SHA256:?}
shard_index=${SLURM_ARRAY_TASK_ID:?}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_sdk1_82068}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
provider_profile="$workflow_dir/configs/provider_context/use2/cpu-132-021_8103/kimi_sandoq_firecracker_small_host.json"
provider_profile_sha256=247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084
router_pid=
provider_supervisor_pid=

slurm_duration_seconds() {
    local value=$1 days=0 hours minutes seconds
    if [[ "$value" =~ ^([0-9]+)-([0-9]{1,2}):([0-9]{2}):([0-9]{2})$ ]]; then
        days=${BASH_REMATCH[1]}
        hours=${BASH_REMATCH[2]}
        minutes=${BASH_REMATCH[3]}
        seconds=${BASH_REMATCH[4]}
    elif [[ "$value" =~ ^([0-9]+):([0-9]{2}):([0-9]{2})$ ]]; then
        hours=${BASH_REMATCH[1]}
        minutes=${BASH_REMATCH[2]}
        seconds=${BASH_REMATCH[3]}
    else
        return 1
    fi
    printf '%s\n' "$(( 10#$days * 86400 + 10#$hours * 3600 + 10#$minutes * 60 + 10#$seconds ))"
}

cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [[ -n "$provider_supervisor_pid" ]] && kill -0 -- "-$provider_supervisor_pid" 2>/dev/null; then
        kill -TERM -- "-$provider_supervisor_pid" 2>/dev/null || true
        wait "$provider_supervisor_pid" 2>/dev/null || true
    fi
    if [[ -n "$router_pid" ]] && kill -0 -- "-$router_pid" 2>/dev/null; then
        kill -TERM -- "-$router_pid" 2>/dev/null || true
        wait "$router_pid" 2>/dev/null || true
    fi
    exit "$status"
}
trap cleanup EXIT INT TERM

[[ "$shard_index" =~ ^([0-9]|[12][0-9]|3[0-9])$ ]] || blocked shard_index_invalid
[[ "$expected_revision" =~ ^[0-9a-f]{40}$ ]] || blocked source_identity_invalid
[[ "$(git -C "$project_dir" rev-parse HEAD)" == "$expected_revision" ]] || blocked source_identity_invalid
[[ -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]] || blocked source_identity_invalid
[[ -z "$(git -C "$project_dir/deps/verifiers" status --porcelain=v1 --untracked-files=all)" ]] \
    || blocked source_identity_invalid
[[ "$(git -C "$project_dir/deps/verifiers" rev-parse HEAD)" == 36b0dff6c18affb3d40b7c46d5836381d568050b ]] \
    || blocked source_identity_invalid
[[ -x "$x86_uv" && -d "$x86_site/pydantic" && -d "$sandoq_site/sandoq_client" ]] \
    || blocked runtime_unavailable

minimum_job_remaining_seconds=475200
scheduler_walltime=$(squeue -h -j "${SLURM_JOB_ID:?}" -o '%L|%l|%e') \
    || blocked job_walltime_unavailable
IFS='|' read -r job_time_left job_time_limit job_end_time job_walltime_extra <<< "$scheduler_walltime"
job_time_left_seconds=$(slurm_duration_seconds "$job_time_left") || blocked job_walltime_invalid
job_time_limit_seconds=$(slurm_duration_seconds "$job_time_limit") || blocked job_walltime_invalid
job_end_epoch=$(date -u -d "$job_end_time" +%s) || blocked job_walltime_invalid
if [[ -n "$job_walltime_extra" || "$scheduler_walltime" == *$'\n'* ]] \
    || (( job_time_left_seconds < minimum_job_remaining_seconds \
        || job_time_limit_seconds < minimum_job_remaining_seconds \
        || job_end_epoch - $(date +%s) < minimum_job_remaining_seconds )); then
    blocked job_walltime_insufficient
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${SLURM_TMPDIR:-/tmp}/kimi-stock-small-pycache-${SLURM_JOB_ID:?}"
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site"

binding=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/kimi_stock_small_shards.py" shard \
        --plan "$plan" --plan-sha256 "$plan_sha256" --index "$shard_index" --format tsv
)
IFS=$'\t' read -r verified_revision verified_index task_count task_file task_sha256 \
    eval_config eval_config_sha256 shard_root endpoint_identifier deployment_root stock_capacity \
    stock_capacity_sha256 endpoint_jobs_sha256 binding_extra <<< "$binding"
if [[ -n "$binding_extra" || "$binding" == *$'\n'* \
    || "$verified_revision" != "$expected_revision" \
    || "$verified_index" != "$shard_index" \
    || ! "$task_count" =~ ^(62|63)$ \
    || ! "$endpoint_identifier" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ \
    || "$deployment_root" != /checkpoint/ram/shared/vllm_deployments_v2/"$endpoint_identifier" \
    || "$stock_capacity" != /* \
    || ! "$stock_capacity_sha256" =~ ^[0-9a-f]{64}$ \
    || ! "$endpoint_jobs_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    blocked shard_binding_invalid
fi

if [[ ! -e "$shard_root" ]]; then
    mkdir -m 0700 -- "$shard_root"
fi
[[ -d "$shard_root" && ! -L "$shard_root" \
    && "$(stat -c '%a:%u' -- "$shard_root")" == "700:$(id -u)" ]] \
    || blocked shard_root_invalid
exec 7>"$shard_root/.launch.lock"
chmod 0600 "$shard_root/.launch.lock"
flock -n 7 || blocked shard_launch_active
if [[ -e "$shard_root/complete.json" ]]; then
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/kimi_stock_small_shards.py" validate-completion \
        --plan "$plan" --plan-sha256 "$plan_sha256" --index "$shard_index" >/dev/null
    printf '{"shard":%s,"state":"already-complete"}\n' "$shard_index"
    exit 0
fi

# A completed shard is the only cross-job resume boundary. Never create a
# second model-bearing attempt for a partially written shard.
shopt -s nullglob
prior_attempts=("$shard_root"/attempt-*)
shopt -u nullglob
(( ${#prior_attempts[@]} == 0 )) || blocked partial_attempt_requires_manual_recovery

generation_dir="$shard_root/generation-${SLURM_JOB_ID}"
output_dir="$shard_root/attempt-${SLURM_JOB_ID}"
manifest="$generation_dir/direct_kimi_workers.json"
urls_file="$generation_dir/worker_urls.private.txt"
ports_file="$generation_dir/router_ports.private.txt"
router_log="$generation_dir/direct_router.log"
router_stats="$generation_dir/direct_router_stats.private.json"
deployment_snapshot="$generation_dir/deployment_source"
launch="$generation_dir/shard-launch.json"
[[ ! -e "$generation_dir" && ! -L "$generation_dir" \
    && ! -e "$output_dir" && ! -L "$output_dir" ]] || blocked attempt_namespace_not_fresh
mkdir -m 0700 -- "$generation_dir"
exec 8>"$generation_dir/.direct_router.lock"
chmod 0600 "$generation_dir/.direct_router.lock"
flock -n 8 || blocked router_generation_busy

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" snapshot-source \
    --deployment-root "$deployment_root" --output-root "$deployment_snapshot" \
    --capacity-profile sandoq-stock-single-c64-v1 \
    --stock-capacity-receipt "$stock_capacity" \
    --stock-capacity-receipt-sha256 "$stock_capacity_sha256" >/dev/null
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" prepare \
    --deployment-root "$deployment_snapshot" --output-root "$generation_dir" \
    --manifest "$manifest" --urls-output "$urls_file" --ports-output "$ports_file" \
    --capacity-profile sandoq-stock-single-c64-v1 \
    --endpoint-identifier "$endpoint_identifier" \
    --stock-capacity-receipt "$stock_capacity" \
    --stock-capacity-receipt-sha256 "$stock_capacity_sha256" \
    --request-timeout-seconds 144000 --probe >/dev/null
manifest_sha256=$(sha256sum -- "$manifest" | cut -d' ' -f1)

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/kimi_stock_small_shards.py" create-launch \
    --plan "$plan" --plan-sha256 "$plan_sha256" --index "$shard_index" \
    --worker-manifest "$manifest" --worker-manifest-sha256 "$manifest_sha256" \
    --run-dir "$output_dir" --output "$launch" >/dev/null
launch_sha256=$(sha256sum -- "$launch" | cut -d' ' -f1)

mapfile -t worker_urls < "$urls_file"
mapfile -t router_ports < "$ports_file"
[[ ${#worker_urls[@]} -eq 1 && ${#router_ports[@]} -eq 2 ]] || blocked router_generation_invalid
router_port=${router_ports[0]}
metrics_port=${router_ports[1]}
while IFS= read -r variable_name; do
    [[ ${variable_name,,} == *_proxy ]] && unset "$variable_name"
done < <(compgen -e)
setsid "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_router.py" \
    --worker-urls-file "$urls_file" --host 127.0.0.1 --port "$router_port" \
    --metrics-port "$metrics_port" --capacity-profile sandoq-stock-single-c64-v1 \
    --endpoint-identifier "$endpoint_identifier" \
    --request-timeout-seconds 144000 >"$router_log" 2>&1 &
router_pid=$!
for attempt in $(seq 1 120); do
    kill -0 "$router_pid" 2>/dev/null || blocked router_start_failed
    active_workers=$(
        curl --noproxy '*' --fail --silent --show-error --max-time 10 \
            "http://127.0.0.1:${metrics_port}/metrics" 2>/dev/null \
            | awk '$1 == "vllm_router_active_workers" {print $2}' | tail -n 1
    ) || true
    if [[ "$active_workers" == 1 ]] \
        && curl --noproxy '*' --fail --silent --show-error --max-time 10 \
            "http://127.0.0.1:${router_port}/v1/models" >/dev/null; then
        break
    fi
    (( attempt < 120 )) || blocked router_start_failed
    sleep 1
done

stage_env=(
    PROJECT_DIR="$project_dir"
    EVAL_CONFIG="$eval_config"
    DIRECT_KIMI_EVAL_CONFIG_SHA256="$eval_config_sha256"
    OUTPUT_DIR="$output_dir"
    DIRECT_KIMI_ROLE=kimi-direct-mobius
    DIRECT_KIMI_APPROVED_TASK_FILE="$task_file"
    DIRECT_KIMI_APPROVED_TASK_FILE_SHA256="$task_sha256"
    DIRECT_KIMI_APPROVED_TASK_COUNT="$task_count"
    DIRECT_KIMI_ROLLOUT_CONCURRENCY=64
    DIRECT_KIMI_WORKER_MANIFEST="$manifest"
    DIRECT_KIMI_WORKER_MANIFEST_SHA256="$manifest_sha256"
    DIRECT_KIMI_BASE_URL="http://127.0.0.1:${router_port}/v1"
    DIRECT_KIMI_EXPECTED_PRIME_RL_REVISION="$expected_revision"
    DIRECT_KIMI_PREFLIGHT_ONLY=0
    DIRECT_KIMI_SANDBOX_PROVIDER=sandoq
    DIRECT_KIMI_EXECUTION_MODE=certified
    DIRECT_KIMI_ROUTER_CAPACITY_PROFILE=sandoq-stock-single-c64-v1
    DIRECT_KIMI_ENDPOINT_IDENTIFIER="$endpoint_identifier"
    DIRECT_KIMI_PRODUCTION_LAUNCH="$launch"
    DIRECT_KIMI_PRODUCTION_LAUNCH_SHA256="$launch_sha256"
    DIRECT_KIMI_ZERO_MODEL_RESUME_ATTEMPTS=0
    KIMI_ENDPOINT_WALLTIME_PROFILE=tb4-extended-c24-stock-single-three-wave-v1
    KIMI_ENDPOINT_MINIMUM_REMAINING_SECONDS=172800
)
ecr_token_file=${OCI_RUNNER_ECR_TOKEN_FILE:-/storage/home/tianhaowu/.config/oci-runner/ecr-token}
ecr_token_metadata=${OCI_RUNNER_ECR_TOKEN_METADATA_PATH:-/storage/home/tianhaowu/.config/oci-runner/ecr-rotation.state.json}
set +e
setsid env "${stage_env[@]}" SANDOQ_PROVIDER_TERMINATION_GRACE_SECONDS=600 \
    "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" supervise \
    --profile "$provider_profile" --profile-sha256 "$provider_profile_sha256" \
    --concurrency 64 --lease-create-cap 4 --startup-timeout-seconds 3600 \
    --lease-profile kimi-tb4-long --ecr-token-file "$ecr_token_file" \
    --ecr-token-metadata "$ecr_token_metadata" --project-root "$project_dir" \
    --sandoq-site "$sandoq_site" \
    -- /usr/bin/bash -p "$workflow_dir/run_direct_kimi_sandoq_stage.sh" &
provider_supervisor_pid=$!
wait "$provider_supervisor_pid"
stage_status=$?
provider_supervisor_pid=
set -e
(( stage_status == 0 )) || exit "$stage_status"

kill -0 "$router_pid" 2>/dev/null || blocked router_exited_early
active_workers=$(
    curl --noproxy '*' --fail --silent --show-error --max-time 10 \
        "http://127.0.0.1:${metrics_port}/metrics" \
        | awk '$1 == "vllm_router_active_workers" {print $2}' | tail -n 1
)
curl --noproxy '*' --fail --silent --show-error --max-time 10 \
    "http://127.0.0.1:${router_port}/stats" --output "$router_stats"
chmod 0600 "$router_stats"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" certify-router \
    --manifest "$manifest" --manifest-sha256 "$manifest_sha256" \
    --active-workers "$active_workers" --router-stats "$router_stats" \
    --eval-run-identity "$output_dir/eval_run_identity.json" \
    --eval-invocations "$output_dir/eval_invocations.jsonl" \
    --provenance "$output_dir/provenance.txt" \
    --allow-terminal-upstream-statuses \
    --output "$output_dir/direct_kimi_router_final.json" >/dev/null
kill -TERM -- "-$router_pid"
wait "$router_pid" 2>/dev/null || true
router_pid=
flock -u 8

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/kimi_stock_small_shards.py" certify-shard \
    --plan "$plan" --plan-sha256 "$plan_sha256" --index "$shard_index" \
    --launch "$launch" --launch-sha256 "$launch_sha256" --run-dir "$output_dir"
