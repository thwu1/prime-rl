#!/usr/bin/bash -p
#SBATCH --job-name=k3-tb4-shared-union
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=4-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=48G
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@1800
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_shared_union_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_shared_union_%j.log

set +x
set -euo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1

blocked() {
    printf '{"code":"%s","state":"blocked"}\n' "$1" >&2
    exit 2
}

(( $# == 0 )) || blocked arguments_forbidden
(( BASH_VERSINFO[0] >= 5 )) || blocked bash_version_unsupported
job_wall_limit=$(squeue -h -j "$SLURM_JOB_ID" -o '%l')
[[ "$job_wall_limit" == 4-00:00:00 ]] || blocked slurm_walltime_contract_invalid

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
server_dir="$workflow_dir/configs/eval/servers/cpu-132-021_8103"
expected_revision=${KIMI_TB4_SHARED_UNION_EXPECTED_PRIME_RL_REVISION:?Set KIMI_TB4_SHARED_UNION_EXPECTED_PRIME_RL_REVISION}
launch_plan=${KIMI_TB4_MINISWE_UNION_PLAN:?Set KIMI_TB4_MINISWE_UNION_PLAN}
launch_plan_sha256=${KIMI_TB4_MINISWE_UNION_PLAN_SHA256:?Set KIMI_TB4_MINISWE_UNION_PLAN_SHA256}
smoke_checkpoint=${KIMI_SANDOQ_SMOKE_CHECKPOINT:?Set KIMI_SANDOQ_SMOKE_CHECKPOINT}
smoke_checkpoint_sha256=${KIMI_SANDOQ_SMOKE_CHECKPOINT_SHA256:?Set KIMI_SANDOQ_SMOKE_CHECKPOINT_SHA256}
capacity_certificate=${KIMI_SANDOQ_CAPACITY_CERTIFICATE:?Set KIMI_SANDOQ_CAPACITY_CERTIFICATE}
capacity_certificate_sha256=${KIMI_SANDOQ_CAPACITY_CERTIFICATE_SHA256:?Set KIMI_SANDOQ_CAPACITY_CERTIFICATE_SHA256}

deployment_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/kimi-k3-deployment-cpu132021-rollover-20260924-v3
dataset_dir=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/tb4-prebuilt-v4.0.0/tasks
official_selector="$workflow_dir/configs/eval/tb4_qwen_a95b_miniswe.tasks.txt"
eval_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_sdk1_82068}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
provider_profile="$workflow_dir/configs/provider_context/use2/kimi_sandoq_firecracker_host.json"
provider_profile_sha256=7dd88ca6c6cde5ed5b22bf8f621462a46425f939478f79469e31da2e582b27df
miniswe_compatibility_sha256=cee344d3c9bc3c18f602a0ad217ade7395db263d50cd8d4c428507a21de86220
ecr_token_file=/storage/home/tianhaowu/.config/oci-runner/ecr-token
ecr_token_metadata=${OCI_RUNNER_ECR_TOKEN_METADATA_PATH:-/storage/home/tianhaowu/.config/oci-runner/ecr-rotation.state.json}
capacity_private_key=/storage/home/tianhaowu/.config/vmvm-capacity-attestor/kimi-tb4-use2-1-ed25519.pem
capacity_public_key="$server_dir/vmvm_capacity_attestor_ed25519.pub.pem"

control_dir="$eval_root/kimi_k3_tb4_shared_union_${SLURM_JOB_ID}_control"
generation_dir="$eval_root/kimi_k3_tb4_shared_union_${SLURM_JOB_ID}_generation"
union_output="$eval_root/kimi_k3_tb4_shared_union_${SLURM_JOB_ID}_certified"
manifest="$generation_dir/direct_kimi_workers.json"
urls_file="$generation_dir/worker_urls.private.txt"
ports_file="$generation_dir/router_ports.private.txt"
deployment_snapshot="$generation_dir/deployment_source"
router_log="$control_dir/direct_router.private.log"
router_stats="$control_dir/direct_router_stats.private.json"
capacity_gate="$control_dir/kimi_tb4_w2_launch_gate.json"
load_gate="$control_dir/kimi_endpoint_load_gate.json"
sandoq_walltime_gate="$control_dir/sandoq_endpoint_walltime_gate.json"
vmvm_walltime_gate="$control_dir/vmvm_endpoint_walltime_gate.json"
start_marker="$control_dir/start.json"
sandoq_ready_marker="$control_dir/sandoq.ready.json"
vmvm_ready_marker="$control_dir/vmvm.ready.json"
router_pid=
sandoq_pid=
vmvm_pid=
sandoq_started=0

emergency_sandoq_cleanup() {
    source_output=${sandoq_output:-}
    source_event_log="$source_output/pool_events.jsonl"
    source_wal="$source_output/control/sandoq-pool.wal.jsonl"
    [[ "$sandoq_started" == 1 && -n "$source_output" && -d "$source_output" \
        && ( -f "$source_event_log" || -f "$source_wal" ) ]] || return 0
    fallback_dir="$control_dir/emergency_sandoq_cleanup"
    [[ ! -e "$fallback_dir" && ! -L "$fallback_dir" ]] || return 1
    mkdir "$fallback_dir"
    chmod 0700 "$fallback_dir"
    if [[ -f "$source_event_log" ]]; then
        cp -- "$source_event_log" "$fallback_dir/pool_events.jsonl"
        chmod 0600 "$fallback_dir/pool_events.jsonl"
    fi
    if [[ -f "$source_wal" ]]; then
        cp -- "$source_wal" "$fallback_dir/sandoq-pool.wal.jsonl"
        chmod 0600 "$fallback_dir/sandoq-pool.wal.jsonl"
        fallback_wal_args=(--wal "$fallback_dir/sandoq-pool.wal.jsonl")
    else
        fallback_wal_args=()
    fi
    env PROJECT_DIR="$project_dir" SANDOQ_PROVIDER_TERMINATION_GRACE_SECONDS=600 \
        "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" supervise \
        --profile "$provider_profile" --profile-sha256 "$provider_profile_sha256" \
        --concurrency 1 --lease-create-cap 1 --startup-timeout-seconds 3600 \
        --lease-profile standard \
        --ecr-token-file "$ecr_token_file" --ecr-token-metadata "$ecr_token_metadata" \
        --project-root "$project_dir" --sandoq-site "$sandoq_site" \
        -- "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/sandoq_pool_cleanup.py" \
        --output-dir "$fallback_dir" --concurrency 32 --live-only "${fallback_wal_args[@]}"
}

wait_pid_bounded() {
    pid=$1
    timeout_seconds=$2
    process_group=$3
    [[ "$pid" =~ ^[1-9][0-9]*$ && "$timeout_seconds" =~ ^[1-9][0-9]*$ \
        && ( "$process_group" == 0 || "$process_group" == 1 ) ]] || return 2
    deadline=$(( $(date +%s) + timeout_seconds ))
    target=$pid
    [[ "$process_group" == 0 ]] || target=-$pid
    while kill -0 -- "$target" 2>/dev/null && (( $(date +%s) < deadline )); do
        sleep 1
    done
    if kill -0 -- "$target" 2>/dev/null; then
        if [[ "$process_group" == 1 ]]; then
            kill -KILL -- "-$pid" 2>/dev/null || true
        else
            kill -KILL "$pid" 2>/dev/null || true
        fi
        wait "$pid" 2>/dev/null || true
        return 1
    fi
    wait "$pid" 2>/dev/null || true
}

drain_recorded_evaluator() {
    pgid_file=$1
    timeout_seconds=$2
    [[ ! -e "$pgid_file" && ! -L "$pgid_file" ]] && return 0
    [[ -f "$pgid_file" && ! -L "$pgid_file" \
        && "$(stat -c '%a:%h:%u' -- "$pgid_file")" == "600:1:$(id -u)" ]] || return 2
    evaluator_pgid=$(<"$pgid_file")
    [[ "$evaluator_pgid" =~ ^[1-9][0-9]*$ && "$evaluator_pgid" != "$$" ]] || return 2
    kill -0 -- "-$evaluator_pgid" 2>/dev/null || return 0
    kill -INT -- "-$evaluator_pgid" 2>/dev/null || true
    deadline=$(( $(date +%s) + timeout_seconds ))
    while kill -0 -- "-$evaluator_pgid" 2>/dev/null && (( $(date +%s) < deadline )); do
        sleep 1
    done
    if kill -0 -- "-$evaluator_pgid" 2>/dev/null; then
        kill -TERM -- "-$evaluator_pgid" 2>/dev/null || true
        sleep 10
    fi
    if kill -0 -- "-$evaluator_pgid" 2>/dev/null; then
        kill -KILL -- "-$evaluator_pgid" 2>/dev/null || true
        return 1
    fi
}

stop_children() {
    child_cleanup_status=0
    if [[ -n "$vmvm_pid" ]] && kill -0 "$vmvm_pid" 2>/dev/null; then
        kill -TERM -- "-$vmvm_pid" 2>/dev/null || true
    fi
    if [[ -n "$sandoq_pid" ]] && kill -0 "$sandoq_pid" 2>/dev/null; then
        kill -TERM -- "-$sandoq_pid" 2>/dev/null || true
    fi
    if [[ -n "$router_pid" ]] && kill -0 "$router_pid" 2>/dev/null; then
        kill -TERM -- "-$router_pid" 2>/dev/null || true
    fi
    set +e
    [[ -z "$vmvm_pid" ]] || wait_pid_bounded "$vmvm_pid" 420 1 || child_cleanup_status=1
    [[ -z "$sandoq_pid" ]] || wait_pid_bounded "$sandoq_pid" 660 1 || child_cleanup_status=1
    drain_recorded_evaluator "${vmvm_output:-/nonexistent}/control/evaluator.pgid" 420 \
        || child_cleanup_status=1
    drain_recorded_evaluator "${sandoq_output:-/nonexistent}/control/evaluator.pgid" 420 \
        || child_cleanup_status=1
    [[ -z "$router_pid" ]] || wait_pid_bounded "$router_pid" 60 1 || child_cleanup_status=1
    emergency_sandoq_cleanup || child_cleanup_status=1
    set -e
    if (( child_cleanup_status != 0 )); then
        printf '{"code":"shared_union_cleanup_failed","state":"blocked"}\n' >&2
    fi
    return "$child_cleanup_status"
}

cleanup() {
    status=$?
    trap - EXIT INT TERM
    set +e
    stop_children
    cleanup_status=$?
    set -e
    if (( cleanup_status != 0 )); then
        status=2
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ "$expected_revision" =~ ^[0-9a-f]{40}$ \
    && "$(git -C "$project_dir" rev-parse HEAD)" == "$expected_revision" \
    && -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" \
    && -z "$(git -C "$project_dir/deps/verifiers" status --porcelain=v1 --untracked-files=all)" \
    && -z "$(git -C "$project_dir/deps/renderers" status --porcelain=v1 --untracked-files=all)" \
    && "$(git -C "$project_dir/deps/verifiers" rev-parse HEAD)" \
        == 3df6efa9e9f6bdc8a013df7759a03074aec79111 ]] \
    || blocked source_identity_invalid
[[ -x "$x86_uv" && -d "$x86_site/pydantic" && -d "$sandoq_site/sandoq_client" \
    && -f "$provider_profile" && ! -L "$provider_profile" \
    && "$(sha256sum -- "$provider_profile" | cut -d' ' -f1)" == "$provider_profile_sha256" \
    && -f "$capacity_private_key" && ! -L "$capacity_private_key" \
    && "$(stat -c '%a' -- "$capacity_private_key")" == 600 \
    && -f "$capacity_public_key" && ! -L "$capacity_public_key" \
    && "$(sha256sum -- "$capacity_public_key" | cut -d' ' -f1)" \
        == c5c6b7d6476b78bffe56666ca353ad71b9f3a11cd9a8219cabb5a81c43f95857 ]] \
    || blocked pinned_runtime_invalid
for binding in \
    "$launch_plan:$launch_plan_sha256" \
    "$smoke_checkpoint:$smoke_checkpoint_sha256" \
    "$capacity_certificate:$capacity_certificate_sha256"; do
    path=${binding%:*}
    digest=${binding##*:}
    [[ "$path" == /* && "$digest" =~ ^[0-9a-f]{64}$ \
        && -f "$path" && ! -L "$path" \
        && "$(stat -c '%a:%h:%u' -- "$path")" == "600:1:$(id -u)" \
        && "$(sha256sum -- "$path" | cut -d' ' -f1)" == "$digest" ]] \
        || blocked sealed_input_invalid
done
for path in "$control_dir" "$generation_dir" "$union_output"; do
    [[ ! -e "$path" && ! -L "$path" ]] || blocked output_namespace_not_fresh
done

export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site"
verify_lane() {
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/prepare_kimi_tb4_miniswe246_union.py" verify \
        --launch-plan "$launch_plan" --launch-plan-sha256 "$launch_plan_sha256" \
        --role "$1" --format tsv
}

sandoq_lane=$(verify_lane sandoq_firecracker)
vmvm_lane=$(verify_lane vmvm_cpu)
IFS=$'\t' read -r sandoq_stage sandoq_provider sandoq_config sandoq_config_sha256 \
    sandoq_selector sandoq_selector_sha256 sandoq_count sandoq_concurrency sandoq_output \
    resource_manifest resource_manifest_sha256 sandoq_adapter sandoq_extra <<< "$sandoq_lane"
IFS=$'\t' read -r vmvm_stage vmvm_provider vmvm_config vmvm_config_sha256 \
    vmvm_selector vmvm_selector_sha256 vmvm_count vmvm_concurrency vmvm_output \
    vmvm_resource_manifest vmvm_resource_manifest_sha256 vmvm_adapter vmvm_extra <<< "$vmvm_lane"
[[ "$sandoq_stage" == tb4-miniswe246-sandoq-union \
    && "$sandoq_provider" == sandoq && "$sandoq_count" == 52 && "$sandoq_concurrency" == 48 \
    && "$vmvm_stage" == tb4-miniswe246-vmvm-union \
    && "$vmvm_provider" == vmvm && "$vmvm_count" == 11 && "$vmvm_concurrency" == 11 \
    && "$sandoq_adapter" == kimi-tb4-miniswe246-provider-union-v1 \
    && "$vmvm_adapter" == "$sandoq_adapter" \
    && "$resource_manifest" == "$vmvm_resource_manifest" \
    && "$resource_manifest_sha256" == "$vmvm_resource_manifest_sha256" \
    && -z "$sandoq_extra" && -z "$vmvm_extra" \
    && "$sandoq_lane" != *$'\n'* && "$vmvm_lane" != *$'\n'* \
    && ! -e "$sandoq_output" && ! -L "$sandoq_output" \
    && ! -e "$vmvm_output" && ! -L "$vmvm_output" ]] \
    || blocked union_plan_invalid

mkdir "$control_dir" "$generation_dir"
chmod 0700 "$control_dir" "$generation_dir"
exec 8>"$generation_dir/.direct_router.lock"
chmod 0600 "$generation_dir/.direct_router.lock"
flock -n 8 || blocked router_lock_unavailable

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" snapshot-source \
    --deployment-root "$deployment_root" --output-root "$deployment_snapshot" >/dev/null
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" prepare \
    --deployment-root "$deployment_snapshot" --output-root "$generation_dir" \
    --manifest "$manifest" --urls-output "$urls_file" --ports-output "$ports_file" --probe \
    --capacity-profile sandoq-c64-w2-v1 --endpoint-identifier cpu-132-021_8103 \
    --request-timeout-seconds 144000
manifest_sha256=$(sha256sum -- "$manifest" | cut -d' ' -f1)
mapfile -t worker_urls <"$urls_file"
mapfile -t router_ports <"$ports_file"
[[ ${#worker_urls[@]} -eq 24 && ${#router_ports[@]} -eq 2 ]] \
    || blocked worker_generation_invalid
router_port=${router_ports[0]}
metrics_port=${router_ports[1]}

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/kimi_tb4_w2_gate.py" \
    --capacity-certificate "$capacity_certificate" \
    --capacity-certificate-sha256 "$capacity_certificate_sha256" \
    --worker-manifest "$manifest" --worker-manifest-sha256 "$manifest_sha256" \
    --selector "$official_selector" --dataset-dir "$dataset_dir" \
    --expected-revision "$expected_revision" --sandoq-site "$sandoq_site" \
    --union-launch-plan "$launch_plan" --union-launch-plan-sha256 "$launch_plan_sha256" \
    --output "$capacity_gate" >/dev/null
capacity_gate_sha256=$(sha256sum -- "$capacity_gate" | cut -d' ' -f1)

common_env=(
    PROJECT_DIR="$project_dir"
    DIRECT_KIMI_ROLE=kimi-direct-tb4
    DIRECT_KIMI_WORKER_MANIFEST="$manifest"
    DIRECT_KIMI_WORKER_MANIFEST_SHA256="$manifest_sha256"
    DIRECT_KIMI_BASE_URL="http://127.0.0.1:${router_port}/v1"
    DIRECT_KIMI_EXPECTED_PRIME_RL_REVISION="$expected_revision"
    DIRECT_KIMI_PREFLIGHT_ONLY=0
    DIRECT_KIMI_EXECUTION_MODE=certified
    DIRECT_KIMI_ROUTER_CAPACITY_PROFILE=sandoq-c64-w2-v1
    DIRECT_KIMI_ENDPOINT_IDENTIFIER=cpu-132-021_8103
    DIRECT_KIMI_CAPACITY_CERTIFICATE="$capacity_certificate"
    DIRECT_KIMI_CAPACITY_CERTIFICATE_SHA256="$capacity_certificate_sha256"
    DIRECT_KIMI_CAPACITY_GATE_RECEIPT="$capacity_gate"
    DIRECT_KIMI_CAPACITY_GATE_RECEIPT_SHA256="$capacity_gate_sha256"
    DIRECT_KIMI_SMOKE_CHECKPOINT="$smoke_checkpoint"
    DIRECT_KIMI_SMOKE_CHECKPOINT_SHA256="$smoke_checkpoint_sha256"
    DIRECT_KIMI_ZERO_MODEL_RESUME_ATTEMPTS=0
    DIRECT_KIMI_PRECAPTURED_ENDPOINT_LOAD_GATE="$load_gate"
    KIMI_SHARED_UNION_START_MARKER="$start_marker"
    KIMI_SHARED_UNION_LOAD_GATE_SHA_FILE="$control_dir/load-gate.sha256"
    KIMI_SHARED_UNION_BARRIER_TIMEOUT_SECONDS=7200
    SANDOQ_PROVIDER_TERMINATION_GRACE_SECONDS=600
)
sandoq_env=(
    "${common_env[@]}"
    EVAL_CONFIG="$sandoq_config"
    DIRECT_KIMI_EVAL_CONFIG_SHA256="$sandoq_config_sha256"
    OUTPUT_DIR="$sandoq_output"
    DIRECT_KIMI_APPROVED_TASK_FILE="$sandoq_selector"
    DIRECT_KIMI_APPROVED_TASK_FILE_SHA256="$sandoq_selector_sha256"
    DIRECT_KIMI_APPROVED_TASK_COUNT=52
    DIRECT_KIMI_ROLLOUT_CONCURRENCY=48
    DIRECT_KIMI_SANDBOX_PROVIDER=sandoq
    DIRECT_KIMI_MINISWE_COMPATIBILITY_RECEIPT_SHA256="$miniswe_compatibility_sha256"
    KIMI_ENDPOINT_WALLTIME_PROFILE=tb4-extended-c48-w2-two-wave-v1
    KIMI_ENDPOINT_MINIMUM_REMAINING_SECONDS=345600
    DIRECT_KIMI_PRECAPTURED_ENDPOINT_WALLTIME_GATE="$sandoq_walltime_gate"
    KIMI_SHARED_UNION_WALLTIME_SHA_FILE="$control_dir/sandoq-walltime.sha256"
    KIMI_SHARED_UNION_READY_MARKER="$sandoq_ready_marker"
)
vmvm_env=(
    "${common_env[@]}"
    EVAL_CONFIG="$vmvm_config"
    DIRECT_KIMI_EVAL_CONFIG_SHA256="$vmvm_config_sha256"
    OUTPUT_DIR="$vmvm_output"
    DIRECT_KIMI_APPROVED_TASK_FILE="$vmvm_selector"
    DIRECT_KIMI_APPROVED_TASK_FILE_SHA256="$vmvm_selector_sha256"
    DIRECT_KIMI_APPROVED_TASK_COUNT=11
    DIRECT_KIMI_ROLLOUT_CONCURRENCY=11
    DIRECT_KIMI_SANDBOX_PROVIDER=vmvm
    DIRECT_KIMI_RESOURCE_MANIFEST_SHA256="$resource_manifest_sha256"
    DIRECT_KIMI_CAPACITY_PRIVATE_KEY="$capacity_private_key"
    DIRECT_KIMI_CAPACITY_PUBLIC_KEY="$capacity_public_key"
    VACLI_MAX_CONCURRENT_LEASES=11
    KIMI_ENDPOINT_WALLTIME_PROFILE=tb4-extended-vmvm-union11-c11-v1
    KIMI_ENDPOINT_MINIMUM_REMAINING_SECONDS=345600
    DIRECT_KIMI_PRECAPTURED_ENDPOINT_WALLTIME_GATE="$vmvm_walltime_gate"
    KIMI_SHARED_UNION_WALLTIME_SHA_FILE="$control_dir/vmvm-walltime.sha256"
    KIMI_SHARED_UNION_READY_MARKER="$vmvm_ready_marker"
)

while IFS= read -r variable_name; do
    if [[ ${variable_name,,} == *_proxy ]]; then
        unset "$variable_name"
    fi
done < <(compgen -e)
setsid env "${sandoq_env[@]}" \
    "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" supervise \
    --profile "$provider_profile" --profile-sha256 "$provider_profile_sha256" \
    --concurrency 64 --lease-create-cap 4 --startup-timeout-seconds 3600 \
    --lease-profile kimi-tb4-long \
    --ecr-token-file "$ecr_token_file" --ecr-token-metadata "$ecr_token_metadata" \
    --project-root "$project_dir" --sandoq-site "$sandoq_site" \
    -- /usr/bin/bash -p "$workflow_dir/run_kimi_tb4_shared_union_lane.sh" &
sandoq_pid=$!
sandoq_started=1
setsid env "${vmvm_env[@]}" \
    /usr/bin/bash -p "$workflow_dir/run_kimi_tb4_shared_union_lane.sh" &
vmvm_pid=$!

for attempt in $(seq 1 3660); do
    kill -0 "$sandoq_pid" 2>/dev/null || blocked sandoq_lane_failed_before_barrier
    kill -0 "$vmvm_pid" 2>/dev/null || blocked vmvm_lane_failed_before_barrier
    if [[ -f "$sandoq_ready_marker" && ! -L "$sandoq_ready_marker" \
        && -f "$vmvm_ready_marker" && ! -L "$vmvm_ready_marker" ]]; then
        break
    fi
    (( attempt < 3660 )) || blocked lane_barrier_timeout
    sleep 1
done
for marker in "$sandoq_ready_marker" "$vmvm_ready_marker"; do
    [[ "$(stat -c '%a:%h:%u' -- "$marker")" == "600:1:$(id -u)" \
        && "$(<"$marker")" == '{"state":"ready"}' ]] \
        || blocked lane_ready_marker_invalid
done

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/kimi_endpoint_walltime_gate.py" capture \
    --manifest "$manifest" --manifest-sha256 "$manifest_sha256" \
    --profile tb4-extended-c48-w2-two-wave-v1 \
    --minimum-remaining-seconds 345600 --task-count 52 \
    --output "$sandoq_walltime_gate" >/dev/null
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/kimi_endpoint_walltime_gate.py" capture \
    --manifest "$manifest" --manifest-sha256 "$manifest_sha256" \
    --profile tb4-extended-vmvm-union11-c11-v1 \
    --minimum-remaining-seconds 345600 --task-count 11 \
    --output "$vmvm_walltime_gate" >/dev/null
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/kimi_endpoint_load_gate.py" \
    --manifest "$manifest" --manifest-sha256 "$manifest_sha256" \
    --worker-urls "$urls_file" --output "$load_gate" >/dev/null
sandoq_walltime_gate_sha256=$(sha256sum -- "$sandoq_walltime_gate" | cut -d' ' -f1)
vmvm_walltime_gate_sha256=$(sha256sum -- "$vmvm_walltime_gate" | cut -d' ' -f1)
load_gate_sha256=$(sha256sum -- "$load_gate" | cut -d' ' -f1)

# The lane processes already inherited their environments. Publish the digests
# through owner-only files that the barrier wrapper imports immediately before
# executing the inner stage.
printf '%s\n' "$sandoq_walltime_gate_sha256" >"$control_dir/sandoq-walltime.sha256"
printf '%s\n' "$vmvm_walltime_gate_sha256" >"$control_dir/vmvm-walltime.sha256"
printf '%s\n' "$load_gate_sha256" >"$control_dir/load-gate.sha256"
chmod 0600 "$control_dir/sandoq-walltime.sha256" "$control_dir/vmvm-walltime.sha256" \
    "$control_dir/load-gate.sha256"

setsid "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_router.py" \
    --worker-urls-file "$urls_file" --host 127.0.0.1 --port "$router_port" \
    --metrics-port "$metrics_port" --capacity-profile sandoq-c64-w2-v1 \
    --endpoint-identifier cpu-132-021_8103 --request-timeout-seconds 144000 \
    >"$router_log" 2>&1 &
router_pid=$!
for attempt in $(seq 1 120); do
    kill -0 "$router_pid" 2>/dev/null || blocked router_start_failed
    active_workers=$(
        curl --noproxy '*' --fail --silent --show-error --max-time 10 \
            "http://127.0.0.1:${metrics_port}/metrics" 2>/dev/null \
            | awk '$1 == "vllm_router_active_workers" {print $2}' | tail -n 1
    ) || true
    if [[ "$active_workers" == 24 ]] \
        && curl --noproxy '*' --fail --silent --show-error --max-time 10 \
            "http://127.0.0.1:${router_port}/v1/models" >/dev/null; then
        break
    fi
    (( attempt < 120 )) || blocked router_start_timeout
    sleep 1
done

set -o noclobber
printf '{"state":"start"}\n' >"$start_marker"
set +o noclobber
chmod 0600 "$start_marker"

remaining_lanes=2
while (( remaining_lanes > 0 )); do
    wait_targets=("$router_pid")
    [[ -z "$sandoq_pid" ]] || wait_targets+=("$sandoq_pid")
    [[ -z "$vmvm_pid" ]] || wait_targets+=("$vmvm_pid")
    completed_pid=
    set +e
    wait -n -p completed_pid "${wait_targets[@]}"
    completed_status=$?
    set -e
    [[ -n "$completed_pid" ]] || blocked child_wait_failed
    if [[ "$completed_pid" == "$router_pid" ]]; then
        router_pid=
        blocked router_exited_during_evaluation
    fi
    (( completed_status == 0 )) || blocked provider_lane_failed
    if [[ "$completed_pid" == "$sandoq_pid" ]]; then
        sandoq_pid=
    elif [[ "$completed_pid" == "$vmvm_pid" ]]; then
        vmvm_pid=
    else
        blocked child_wait_identity_invalid
    fi
    remaining_lanes=$((remaining_lanes - 1))
done

kill -0 "$router_pid" 2>/dev/null || blocked router_exited_before_certification
active_workers=$(
    curl --noproxy '*' --fail --silent --show-error --max-time 10 \
        "http://127.0.0.1:${metrics_port}/metrics" \
        | awk '$1 == "vllm_router_active_workers" {print $2}' | tail -n 1
)
curl --noproxy '*' --fail --silent --show-error --max-time 10 \
    "http://127.0.0.1:${router_port}/stats" --output "$router_stats"
chmod 0600 "$router_stats"
for lane_output in "$sandoq_output" "$vmvm_output"; do
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/direct_kimi_workers.py" certify-router \
        --manifest "$manifest" --manifest-sha256 "$manifest_sha256" \
        --active-workers "$active_workers" --router-stats "$router_stats" \
        --eval-run-identity "$lane_output/eval_run_identity.json" \
        --eval-invocations "$lane_output/eval_invocations.jsonl" \
        --provenance "$lane_output/provenance.txt" \
        --output "$lane_output/direct_kimi_router_final.json"
done
kill -TERM -- "-$router_pid"
wait "$router_pid" 2>/dev/null || true
router_pid=
flock -u 8

sandoq_lane_certificate="$sandoq_output/provider_partition_certificate.json"
vmvm_lane_certificate="$vmvm_output/provider_partition_certificate.json"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/certify_kimi_tb4_miniswe246_union.py" certify-lane \
    --role sandoq_firecracker --run-dir "$sandoq_output" \
    --launch-plan "$launch_plan" --launch-plan-sha256 "$launch_plan_sha256" \
    --expected-revision "$expected_revision" \
    --output "$sandoq_lane_certificate" >/dev/null
vmvm_capacity_receipt="$vmvm_output/control/vmvm_capacity_receipt.json"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/certify_kimi_tb4_miniswe246_union.py" certify-lane \
    --role vmvm_cpu --run-dir "$vmvm_output" \
    --launch-plan "$launch_plan" --launch-plan-sha256 "$launch_plan_sha256" \
    --expected-revision "$expected_revision" \
    --capacity-receipt "$vmvm_capacity_receipt" \
    --capacity-receipt-sha256 "$(sha256sum -- "$vmvm_capacity_receipt" | cut -d' ' -f1)" \
    --capacity-public-key "$capacity_public_key" \
    --capacity-public-key-sha256 "$(sha256sum -- "$capacity_public_key" | cut -d' ' -f1)" \
    --output "$vmvm_lane_certificate" >/dev/null
sandoq_lane_certificate_sha256=$(sha256sum -- "$sandoq_lane_certificate" | cut -d' ' -f1)
vmvm_lane_certificate_sha256=$(sha256sum -- "$vmvm_lane_certificate" | cut -d' ' -f1)
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/certify_kimi_tb4_miniswe246_union.py" merge \
    --launch-plan "$launch_plan" --launch-plan-sha256 "$launch_plan_sha256" \
    --expected-revision "$expected_revision" \
    --sandoq-certificate "$sandoq_lane_certificate" \
    --sandoq-certificate-sha256 "$sandoq_lane_certificate_sha256" \
    --vmvm-certificate "$vmvm_lane_certificate" \
    --vmvm-certificate-sha256 "$vmvm_lane_certificate_sha256" \
    --output "$union_output"

printf '{"admission":64,"capacity_certificate_sha256":"%s","capacity_gate_sha256":"%s","effective_forwarded":48,"job_id":"%s","launch_plan_sha256":"%s","load_gate_sha256":"%s","manifest_sha256":"%s","provider_counts":{"sandoq":52,"vmvm":11,"unsupported":3},"sandoq_lane_certificate_sha256":"%s","sandoq_walltime_gate_sha256":"%s","smoke_checkpoint_sha256":"%s","source_revision":"%s","state":"passed","union_certificate_sha256":"%s","vmvm_lane_certificate_sha256":"%s","vmvm_walltime_gate_sha256":"%s"}\n' \
    "$capacity_certificate_sha256" "$capacity_gate_sha256" "$SLURM_JOB_ID" \
    "$launch_plan_sha256" "$load_gate_sha256" "$manifest_sha256" \
    "$sandoq_lane_certificate_sha256" "$sandoq_walltime_gate_sha256" \
    "$smoke_checkpoint_sha256" "$expected_revision" \
    "$(sha256sum -- "$union_output/certificate.json" | cut -d' ' -f1)" \
    "$vmvm_lane_certificate_sha256" "$vmvm_walltime_gate_sha256" \
    >"$control_dir/shared_union_receipt.json"
chmod 0600 "$control_dir/shared_union_receipt.json"
trap - EXIT INT TERM
printf '{"job_id":"%s","state":"passed"}\n' "$SLURM_JOB_ID"
