#!/usr/bin/env bash
set -euo pipefail
umask 077

project_dir=${PROJECT_DIR:?Set PROJECT_DIR}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_ram_prime_f7313db4}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
eval_config=${EVAL_CONFIG:?Set EVAL_CONFIG}
eval_config_sha256=${DIRECT_KIMI_EVAL_CONFIG_SHA256:-}
output_dir=${OUTPUT_DIR:?Set OUTPUT_DIR}
role=${DIRECT_KIMI_ROLE:?Set DIRECT_KIMI_ROLE}
approved_task_file=${DIRECT_KIMI_APPROVED_TASK_FILE:?Set DIRECT_KIMI_APPROVED_TASK_FILE}
approved_task_file_sha256=${DIRECT_KIMI_APPROVED_TASK_FILE_SHA256:?Set DIRECT_KIMI_APPROVED_TASK_FILE_SHA256}
approved_task_count=${DIRECT_KIMI_APPROVED_TASK_COUNT:?Set DIRECT_KIMI_APPROVED_TASK_COUNT}
rollout_concurrency=${DIRECT_KIMI_ROLLOUT_CONCURRENCY:?Set DIRECT_KIMI_ROLLOUT_CONCURRENCY}
worker_manifest=${DIRECT_KIMI_WORKER_MANIFEST:?Set DIRECT_KIMI_WORKER_MANIFEST}
worker_manifest_sha256=${DIRECT_KIMI_WORKER_MANIFEST_SHA256:?Set DIRECT_KIMI_WORKER_MANIFEST_SHA256}
client_base_url=${DIRECT_KIMI_BASE_URL:?Set DIRECT_KIMI_BASE_URL}
expected_revision=${DIRECT_KIMI_EXPECTED_PRIME_RL_REVISION:?Set DIRECT_KIMI_EXPECTED_PRIME_RL_REVISION}
preflight_only=${DIRECT_KIMI_PREFLIGHT_ONLY:-0}
sandbox_provider=${DIRECT_KIMI_SANDBOX_PROVIDER:-sandoq}
execution_mode=${DIRECT_KIMI_EXECUTION_MODE:-certified}
router_capacity_profile=${DIRECT_KIMI_ROUTER_CAPACITY_PROFILE:-legacy-c24}
endpoint_identifier=${DIRECT_KIMI_ENDPOINT_IDENTIFIER:-}
endpoint_walltime_profile=${KIMI_ENDPOINT_WALLTIME_PROFILE:-legacy}
endpoint_minimum_remaining_seconds=${KIMI_ENDPOINT_MINIMUM_REMAINING_SECONDS:-324000}
endpoint_walltime_receipt=
endpoint_walltime_receipt_file_sha256=

if [[ "$role" != kimi-direct-smoke && "$role" != kimi-direct-capacity-smoke \
    && "$role" != kimi-direct-tb4 \
    && "$role" != kimi-direct-tb4-diagnostic \
    && "$role" != kimi-direct-tb4-sandoq-fallback-diagnostic ]]; then
    printf 'Invalid direct Kimi stage role\n' >&2
    exit 2
fi
if [[ "$role" == kimi-direct-capacity-smoke ]]; then
    if [[ "$sandbox_provider" != sandoq || "$execution_mode" != certified \
        || "$rollout_concurrency" != 64 \
        || "$router_capacity_profile" != sandoq-c64-w2-v1 \
        || "$endpoint_identifier" != cpu-132-021_8103 ]]; then
        printf 'Direct Kimi capacity smoke requires the exact bounded c64-w2 profile\n' >&2
        exit 2
    fi
elif [[ "$router_capacity_profile" != legacy-c24 || -n "$endpoint_identifier" ]]; then
    printf 'Legacy direct Kimi stages require the default c24 router profile\n' >&2
    exit 2
fi
if [[ "$execution_mode" != certified && "$execution_mode" != diagnostic \
    && "$execution_mode" != sandoq-fallback-diagnostic ]]; then
    printf 'Invalid direct Kimi execution mode\n' >&2
    exit 2
fi
if [[ "$role" == kimi-direct-tb4-sandoq-fallback-diagnostic ]]; then
    if [[ "$execution_mode" != sandoq-fallback-diagnostic || "$sandbox_provider" != sandoq ]]; then
        printf 'Fallback direct Kimi role requires its Sandoq diagnostic execution mode\n' >&2
        exit 2
    fi
    launch_plan=${DIRECT_KIMI_FALLBACK_PLAN:?Set DIRECT_KIMI_FALLBACK_PLAN}
    launch_plan_sha256=${DIRECT_KIMI_FALLBACK_PLAN_SHA256:?Set DIRECT_KIMI_FALLBACK_PLAN_SHA256}
    launch_lane=${DIRECT_KIMI_FALLBACK_LANE:?Set DIRECT_KIMI_FALLBACK_LANE}
    case "$launch_lane" in
        memory_8g)
            expected_launch_stage=sandoq-fallback-memory-8g
            expected_launch_count=17
            expected_launch_concurrency=6
            ;;
        memory_16g)
            expected_launch_stage=sandoq-fallback-memory-16g
            expected_launch_count=4
            expected_launch_concurrency=2
            ;;
        *) printf 'Fallback diagnostic lane is invalid\n' >&2; exit 2 ;;
    esac
    verified_launch=$(
        PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site" \
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$workflow_dir/prepare_kimi_tb4_sandoq_fallback.py" verify \
            --launch-plan "$launch_plan" --launch-plan-sha256 "$launch_plan_sha256" \
            --lane "$launch_lane" --format tsv
    )
    IFS=$'\t' read -r verified_stage verified_provider verified_config verified_config_sha256 \
        verified_selector verified_selector_sha256 verified_count verified_concurrency verified_output \
        verified_manifest verified_manifest_sha256 verified_partition verified_extra <<< "$verified_launch"
    if [[ -n "$verified_extra" || "$verified_launch" == *$'\n'* \
        || "$eval_config" != "$verified_config" \
        || "$eval_config_sha256" != "$verified_config_sha256" \
        || "$approved_task_file" != "$verified_selector" \
        || "$approved_task_file_sha256" != "$verified_selector_sha256" \
        || "$approved_task_count" != "$verified_count" \
        || "$rollout_concurrency" != "$verified_concurrency" \
        || "$expected_launch_count" != "$verified_count" \
        || "$expected_launch_concurrency" != "$verified_concurrency" \
        || "$expected_launch_stage" != "$verified_stage" \
        || "$output_dir" != "$verified_output" \
        || "$sandbox_provider" != "$verified_provider" \
        || "${DIRECT_KIMI_RESOURCE_MANIFEST:?Set DIRECT_KIMI_RESOURCE_MANIFEST}" != "$verified_manifest" \
        || "${DIRECT_KIMI_RESOURCE_MANIFEST_SHA256:?Set DIRECT_KIMI_RESOURCE_MANIFEST_SHA256}" != "$verified_manifest_sha256" \
        || "${DIRECT_KIMI_PROVIDER_PARTITION_DIR:?Set DIRECT_KIMI_PROVIDER_PARTITION_DIR}" != "$verified_partition" ]]; then
        printf 'Fallback diagnostic launch plan binding failed\n' >&2
        exit 2
    fi
elif [[ "$role" == kimi-direct-tb4-diagnostic ]]; then
    if [[ "$execution_mode" != diagnostic ]]; then
        printf 'Diagnostic direct Kimi role requires diagnostic execution mode\n' >&2
        exit 2
    fi
    launch_plan=${DIRECT_KIMI_LAUNCH_PLAN:?Set DIRECT_KIMI_LAUNCH_PLAN}
    launch_plan_sha256=${DIRECT_KIMI_LAUNCH_PLAN_SHA256:?Set DIRECT_KIMI_LAUNCH_PLAN_SHA256}
    launch_role=${DIRECT_KIMI_LAUNCH_ROLE:?Set DIRECT_KIMI_LAUNCH_ROLE}
    expected_launch_stage=provider-split-legacy
    expected_launch_count=31
    expected_launch_concurrency=24
    if [[ "$launch_role" == large_provider ]]; then
        expected_launch_stage=provider-split-large
        expected_launch_count=32
        expected_launch_concurrency=4
    elif [[ "$launch_role" != legacy_sandoq ]]; then
        printf 'Diagnostic launch role is invalid\n' >&2
        exit 2
    fi
    verified_launch=$(
        PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site" \
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$workflow_dir/prepare_kimi_tb4_provider_split_launch.py" verify \
            --launch-plan "$launch_plan" --launch-plan-sha256 "$launch_plan_sha256" \
            --role "$launch_role" --format tsv
    )
    IFS=$'\t' read -r verified_stage verified_provider verified_config verified_config_sha256 \
        verified_selector verified_selector_sha256 verified_count verified_concurrency verified_output \
        verified_manifest verified_manifest_sha256 verified_partition verified_extra <<< "$verified_launch"
    if [[ -n "$verified_extra" || "$verified_launch" == *$'\n'* \
        || "$eval_config" != "$verified_config" \
        || "$eval_config_sha256" != "$verified_config_sha256" \
        || "$approved_task_file" != "$verified_selector" \
        || "$approved_task_file_sha256" != "$verified_selector_sha256" \
        || "$approved_task_count" != "$verified_count" \
        || "$rollout_concurrency" != "$verified_concurrency" \
        || "$expected_launch_count" != "$verified_count" \
        || "$expected_launch_concurrency" != "$verified_concurrency" \
        || "$expected_launch_stage" != "$verified_stage" \
        || "$output_dir" != "$verified_output" \
        || "$sandbox_provider" != "$verified_provider" \
        || "${DIRECT_KIMI_RESOURCE_MANIFEST:?Set DIRECT_KIMI_RESOURCE_MANIFEST}" != "$verified_manifest" \
        || "${DIRECT_KIMI_RESOURCE_MANIFEST_SHA256:?Set DIRECT_KIMI_RESOURCE_MANIFEST_SHA256}" != "$verified_manifest_sha256" \
        || "${DIRECT_KIMI_PROVIDER_PARTITION_DIR:?Set DIRECT_KIMI_PROVIDER_PARTITION_DIR}" != "$verified_partition" ]]; then
        printf 'Diagnostic launch plan binding failed\n' >&2
        exit 2
    fi
elif [[ "$execution_mode" != certified ]]; then
    printf 'Diagnostic execution mode requires diagnostic role\n' >&2
    exit 2
fi
if [[ "$preflight_only" != 0 && "$preflight_only" != 1 ]]; then
    printf 'DIRECT_KIMI_PREFLIGHT_ONLY must be 0 or 1\n' >&2
    exit 2
fi
if [[ "$execution_mode" != certified && "$preflight_only" != 0 ]]; then
    printf 'The sealed diagnostic plan is actual-only; use a distinct plan for preflight\n' >&2
    exit 2
fi
if [[ "$sandbox_provider" != sandoq && "$sandbox_provider" != vmvm ]]; then
    printf 'Direct Kimi stage requires a supported sandbox provider\n' >&2
    exit 2
fi
expected_sandoq_lease_profile=standard
expected_sandoq_lease_duration=1h
expected_managed_shell_recovery=0
managed_shell_recovery_policy=disabled
if [[ "$role" == kimi-direct-smoke || "$role" == kimi-direct-tb4 \
    || "$role" == kimi-direct-tb4-diagnostic \
    || "$role" == kimi-direct-tb4-sandoq-fallback-diagnostic ]]; then
    expected_sandoq_lease_profile=kimi-tb4-long
    expected_sandoq_lease_duration=12h
    expected_managed_shell_recovery=1
    managed_shell_recovery_policy=definitive-404-410-single-replay-v1
fi
native_miniswe=0
if [[ "$sandbox_provider" == sandoq \
    && "${OCI_RUNNER_ENVIRONMENT:-}" == oci-runner-firecracker ]]; then
    native_miniswe=1
fi
if [[ "$native_miniswe" == 1 ]] \
    && [[ "$role" != kimi-direct-smoke && "$role" != kimi-direct-capacity-smoke && "$role" != kimi-direct-tb4 ]]; then
    printf 'Native MiniSWE Sandoq context is not approved for this stage role\n' >&2
    exit 2
fi
if [[ "$sandbox_provider" == sandoq ]] \
    && [[ ${SANDOQ_PROVIDER_CONTEXT_ACTIVE:-} != 1 \
        || -z ${SANDOQ_PROVIDER_CONTEXT_RECEIPT:-} \
        || "$SANDOQ_EFFECTIVE_TASK_NETWORK" != public \
        || "$SANDOQ_LEASE_PROFILE" != "$expected_sandoq_lease_profile" \
        || "$OCI_RUNNER_LEASE_DURATION" != "$expected_sandoq_lease_duration" \
        || "$OCI_RUNNER_POOL_RENEW_INTERVAL" != 5m \
        || "$OCI_RUNNER_MANAGED_SHELL_RECOVERY" != "$expected_managed_shell_recovery" \
        || ( "$native_miniswe" == 1 && "$OCI_RUNNER_ENVIRONMENT" != oci-runner-firecracker ) \
        || ( "$native_miniswe" == 1 && "${OCI_RUNNER_TASK_NETWORK:-}" != host ) \
        || ( "$native_miniswe" == 1 && "${OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK:-}" != 0 ) \
        || ( "$native_miniswe" == 1 && "${SANDOQ_PROVIDER_PROFILE_SHA256:-}" != 7dd88ca6c6cde5ed5b22bf8f621462a46425f939478f79469e31da2e582b27df ) \
        || ( "$native_miniswe" == 1 && "${SANDOQ_RUNTIME_SMOKE_RECEIPT_SHA256:-}" != 39108c28f052f4689e863fedaa81430b479915797a4e6836ed090344c5ee3276 ) \
        || ( "$native_miniswe" == 1 && "${SANDOQ_RUNTIME_RESOURCE_RECEIPT_SHA256:-}" != ce3fc3ed2ead1aaf8c71fc35e5dae324f1be9d51b4e7fffff7bc99d1a47adbf6 ) \
        || ( "$native_miniswe" == 1 && "${DIRECT_KIMI_MINISWE_COMPATIBILITY_RECEIPT_SHA256:-}" != cee344d3c9bc3c18f602a0ad217ade7395db263d50cd8d4c428507a21de86220 ) \
        || ( "$native_miniswe" == 0 && "$OCI_RUNNER_ENVIRONMENT" != oci-runner ) \
        || ( "$native_miniswe" == 0 && -n ${OCI_RUNNER_TASK_NETWORK:-} ) ]]; then
    printf 'Direct Kimi stage requires its exact sealed Sandoq context\n' >&2
    exit 2
fi
if [[ "$(git -C "$project_dir" rev-parse HEAD)" != "$expected_revision" \
    || -n "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" \
    || -n "$(git -C "$project_dir/deps/verifiers" status --porcelain=v1 --untracked-files=all)" \
    || -n "$(git -C "$project_dir/deps/renderers" status --porcelain=v1 --untracked-files=all)" ]]; then
    printf 'Direct Kimi stage requires the exact clean source closure\n' >&2
    exit 2
fi
if [[ "$(git -C "$project_dir/deps/verifiers" rev-parse HEAD)" \
    != f9dcefb73ac341de5f707600d54dba838ad1ce97 ]]; then
    printf 'Direct Kimi stage requires the approved Verifiers revision\n' >&2
    exit 2
fi
if [[ ! -d "$x86_site/pydantic" || ! -x "$x86_uv" \
    || ( "$sandbox_provider" == sandoq && ! -d "$sandoq_site/sandoq_client" ) ]]; then
    printf 'Direct Kimi x86 dependency closure is unavailable\n' >&2
    exit 2
fi
for path in "$eval_config" "$approved_task_file" "$worker_manifest"; do
    if [[ ! -f "$path" || -L "$path" ]]; then
        printf 'Direct Kimi stage input is unavailable or unsafe\n' >&2
        exit 2
    fi
done
if [[ -e "$output_dir" || -L "$output_dir" ]]; then
    printf 'Direct Kimi stage requires a fresh output directory\n' >&2
    exit 2
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site"
cd "$project_dir"
if [[ "$sandbox_provider" == sandoq ]]; then
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" verify \
        --receipt "$SANDOQ_PROVIDER_CONTEXT_RECEIPT" >/dev/null
fi

mkdir -p "$output_dir/control"
chmod 0700 "$output_dir" "$output_dir/control"
export PRIME_RL_OUTPUT_DIR="$output_dir"
if [[ "$native_miniswe" == 1 ]]; then
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" snapshot \
        --receipt "$SANDOQ_PROVIDER_CONTEXT_RECEIPT" \
        --output "$output_dir/sandoq-provider-context.json" >/dev/null \
        || blocked provider_context_snapshot_invalid
fi
if [[ "$sandbox_provider" == sandoq ]]; then
    pool_socket_dir="${SLURM_TMPDIR:-/tmp}/oci-runner-pool-${UID}"
    mkdir -p "$pool_socket_dir"
    chmod 0700 "$pool_socket_dir"
    export OCI_RUNNER_POOL_SOCKET="$pool_socket_dir/${SLURM_JOB_ID}.sock"
    export OCI_RUNNER_POOL_WAL="$output_dir/control/sandoq-pool.wal.jsonl"
    export OCI_RUNNER_POOL_EVENT_LOG="$output_dir/pool_events.jsonl"
fi
for stale in inputs config.toml results.jsonl provenance.txt eval_run_identity.json eval_invocations.jsonl \
    pool_cleanup_audit.json sandoq_cleanup_audit.json direct_kimi_router_final.json; do
    if [[ -e "$output_dir/$stale" || -L "$output_dir/$stale" ]]; then
        printf 'Direct Kimi stage found stale output evidence\n' >&2
        exit 2
    fi
done

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/snapshot_eval_inputs.py" "$eval_config" "$output_dir/inputs"
approval_config_args=()
if [[ -n "$eval_config_sha256" ]]; then
    approval_config_args=(
        --approved-config "$eval_config"
        --approved-config-sha256 "$eval_config_sha256"
    )
fi
approval_metadata=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/validate_task_approval.py" \
        --inputs-dir "$output_dir/inputs" \
        --approved-task-file "$approved_task_file" \
        --approved-task-file-sha256 "$approved_task_file_sha256" \
        "${approval_config_args[@]}"
)
IFS=$'\t' read -r validated_task_sha256 validated_task_count approval_extra <<< "$approval_metadata"
if [[ "$validated_task_sha256" != "$approved_task_file_sha256" \
    || ! "$validated_task_count" =~ ^[1-9][0-9]*$ \
    || "$validated_task_count" != "$approved_task_count" \
    || -n "$approval_extra" || "$approval_metadata" == *$'\n'* ]]; then
    printf 'Direct Kimi task approval validation failed\n' >&2
    exit 2
fi

clean_tree_sha256=$(printf '' | sha256sum | cut -d' ' -f1)
sandoq_site_sha256=
sandoq_client_version=
if [[ "$sandbox_provider" == sandoq ]]; then
    sandoq_site_sha256=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" python3 - "$sandoq_site" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
digest = hashlib.sha256()
paths = sorted(
    (path for path in root.rglob("*") if path.is_file() and path.suffix != ".pyc" and not path.name.startswith(".")),
    key=lambda path: path.relative_to(root).as_posix(),
)
for path in paths:
    digest.update(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}\n".encode())
print(digest.hexdigest())
PY
    )
    sandoq_client_version=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" python3 - "$sandoq_site" <<'PY'
import importlib.metadata as metadata

distributions = [
    distribution
    for distribution in metadata.distributions(path=[__import__("sys").argv[1]])
    if distribution.metadata["Name"].lower().replace("_", "-") == "sandoq-client"
]
if len(distributions) != 1:
    raise SystemExit(2)
print(distributions[0].version)
PY
    )
fi
image_manifest_sha256=$(sha256sum "$output_dir/inputs/image_manifest.json" | cut -d' ' -f1)
manifest_metadata=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" python3 - "$worker_manifest" <<'PY'
import sys
from pathlib import Path
from direct_kimi_workers import validate_saved_manifest

manifest = validate_saved_manifest(Path(sys.argv[1]))
router = manifest["router"]
print(
    manifest["source_spec_sha256"],
    manifest["endpoint_bundle_sha256"],
    router.get("capacity_profile", "legacy-c24"),
    router.get("endpoint_identifier", "-"),
    router["max_concurrent_requests"],
    router.get("per_worker_capacity", 1),
    router["request_timeout_seconds"],
    sep="\t",
)
PY
)
IFS=$'\t' read -r direct_spec_sha256 direct_endpoint_bundle_sha256 direct_capacity_profile \
    direct_endpoint_identifier direct_router_concurrency direct_per_worker_capacity \
    direct_request_timeout manifest_extra \
    <<< "$manifest_metadata"
expected_endpoint_identifier=${endpoint_identifier:--}
expected_router_concurrency=24
expected_per_worker_capacity=1
if [[ "$router_capacity_profile" == sandoq-c64-w2-v1 ]]; then
    expected_router_concurrency=64
    expected_per_worker_capacity=2
fi
if [[ ! "$direct_spec_sha256" =~ ^[0-9a-f]{64}$ \
    || ! "$direct_endpoint_bundle_sha256" =~ ^[0-9a-f]{64}$ \
    || "$direct_capacity_profile" != "$router_capacity_profile" \
    || "$direct_endpoint_identifier" != "$expected_endpoint_identifier" \
    || "$direct_router_concurrency" != "$expected_router_concurrency" \
    || "$direct_per_worker_capacity" != "$expected_per_worker_capacity" \
    || ( "$direct_request_timeout" != 43200 && "$direct_request_timeout" != 144000 ) \
    || -n "$manifest_extra" || "$manifest_metadata" == *$'\n'* ]]; then
    printf 'Direct Kimi worker manifest validation failed\n' >&2
    exit 2
fi

if [[ "$direct_request_timeout" == 144000 ]]; then
    if [[ "$endpoint_walltime_profile" != tb4-extended-c24-two-wave-v1 \
        || "$role" != kimi-direct-tb4 || "$rollout_concurrency" != 24 \
        || ! "$approved_task_count" =~ ^[1-9][0-9]*$ \
        || "$approved_task_count" -le 24 || "$approved_task_count" -gt 48 \
        || ! "$endpoint_minimum_remaining_seconds" =~ ^[1-9][0-9]*$ \
        || "$endpoint_minimum_remaining_seconds" -lt 324000 ]]; then
        printf 'Extended direct Kimi TB4 requires its sealed 90-hour endpoint walltime profile\n' >&2
        exit 2
    fi
    endpoint_walltime_receipt="$(dirname -- "$worker_manifest")/direct_kimi_endpoint_walltime_gate.json"
    if [[ -e "$endpoint_walltime_receipt" || -L "$endpoint_walltime_receipt" ]]; then
        printf 'Direct Kimi endpoint walltime receipt namespace is not fresh\n' >&2
        exit 2
    fi
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/kimi_endpoint_walltime_gate.py" capture \
        --manifest "$worker_manifest" \
        --manifest-sha256 "$worker_manifest_sha256" \
        --profile "$endpoint_walltime_profile" \
        --minimum-remaining-seconds "$endpoint_minimum_remaining_seconds" \
        --task-count "$approved_task_count" \
        --output "$endpoint_walltime_receipt"
    endpoint_walltime_receipt_file_sha256=$(sha256sum -- "$endpoint_walltime_receipt" | cut -d' ' -f1)
elif [[ "$endpoint_walltime_profile" != legacy \
    || -n ${KIMI_ENDPOINT_MINIMUM_REMAINING_SECONDS:-} ]]; then
    printf 'Legacy direct Kimi runs cannot consume an endpoint walltime profile\n' >&2
    exit 2
fi

identity_args=(
    --mode fresh
    --role "$role"
    --sandbox-provider "$sandbox_provider"
    --output-dir "$output_dir"
    --inputs-dir "$output_dir/inputs"
    --client-base-url "$client_base_url"
    --expected-model Kimi-K3
    --approved-task-file-sha256 "$validated_task_sha256"
    --approved-task-count "$validated_task_count"
    --project-root "$project_dir"
    --prime-rl-commit "$expected_revision"
    --prime-rl-tree-sha256 "$clean_tree_sha256"
    --verifiers-commit "$(git -C "$project_dir/deps/verifiers" rev-parse HEAD)"
    --verifiers-tree-sha256 "$clean_tree_sha256"
    --renderers-commit "$(git -C "$project_dir/deps/renderers" rev-parse HEAD)"
    --renderers-tree-sha256 "$clean_tree_sha256"
    --direct-worker-manifest "$worker_manifest"
    --direct-worker-manifest-sha256 "$worker_manifest_sha256"
    --direct-spec-sha256 "$direct_spec_sha256"
    --direct-endpoint-bundle-sha256 "$direct_endpoint_bundle_sha256"
    --direct-router-policy consistent_hash
    --direct-request-id-headers x-session-id
    --direct-provider-concurrency "$direct_router_concurrency"
    --direct-request-timeout-seconds "$direct_request_timeout"
    --direct-retries 0
    --direct-worker-count 24
    --invocation-host "$(hostname)"
    --slurm-job-id "$SLURM_JOB_ID"
)
if [[ "$router_capacity_profile" == sandoq-c64-w2-v1 ]]; then
    identity_args+=(--direct-per-worker-capacity "$direct_per_worker_capacity")
fi
if [[ -n "$eval_config_sha256" ]]; then
    identity_args+=(--approved-config-sha256 "$eval_config_sha256")
fi
if [[ "$sandbox_provider" == sandoq ]]; then
    case "$SANDOQ_TRANSPORT_MODE" in
        auto) sandoq_transport_proxy_policy=official-client-auto ;;
        loopback) sandoq_transport_proxy_policy=official-client-supervised-loopback-connect-proxy ;;
        *) printf 'Direct Kimi Sandoq transport mode is invalid\n' >&2; exit 2 ;;
    esac
    sandoq_tunnel_policy=host-interception-no-tunnel
    sandoq_allow_dockerhub_fallback=1
    if [[ "$native_miniswe" == 1 ]]; then
        sandoq_tunnel_policy=native-sandoq-reverse-tunnel
        sandoq_allow_dockerhub_fallback=0
    fi
    identity_args+=(
        --sandoq-provider-commit 4890302104d76220cef791c86d2009168597d35f
        --sandoq-provider-tree 33f092a3982916660e12f472588e6ce34a906fc2
        --sandoq-client-version "$sandoq_client_version"
        --sandoq-site "$sandoq_site"
        --sandoq-site-sha256 "$sandoq_site_sha256"
        --derived-image-manifest-sha256 "$image_manifest_sha256"
        --sandoq-environment "$OCI_RUNNER_ENVIRONMENT"
        --sandoq-task-network "$SANDOQ_EFFECTIVE_TASK_NETWORK"
        --sandoq-pool-size "$OCI_RUNNER_POOL_SIZE"
        --sandoq-pool-min-size "$OCI_RUNNER_POOL_MIN_SIZE"
        --sandoq-tunnel-policy "$sandoq_tunnel_policy"
        --sandoq-base-url "$OCI_RUNNER_BASE_URL"
        --sandoq-owner "$SANDOQ_OWNER"
        --sandoq-transport-proxy-policy "$sandoq_transport_proxy_policy"
        --sandoq-pool-socket "$OCI_RUNNER_POOL_SOCKET"
        --sandoq-pool-wal "$OCI_RUNNER_POOL_WAL"
        --sandoq-pool-event-log "$OCI_RUNNER_POOL_EVENT_LOG"
        --sandoq-use-ecr "$OCI_RUNNER_USE_ECR"
        --sandoq-ecr-registry "$OCI_RUNNER_ECR_REGISTRY"
        --sandoq-ecr-region "$OCI_RUNNER_ECR_REGION"
        --sandoq-ecr-pull-through-prefix "$OCI_RUNNER_ECR_PULL_THROUGH_PREFIX"
        --sandoq-ecr-token-file "$OCI_RUNNER_ECR_TOKEN_FILE"
        --sandoq-allow-dockerhub-fallback "$sandoq_allow_dockerhub_fallback"
        --sandoq-create-deadline "$OCI_RUNNER_CREATE_DEADLINE"
        --sandoq-pull-timeout "$OCI_RUNNER_PULL_TIMEOUT"
        --sandoq-pull-poll-max-errors "$OCI_RUNNER_PULL_POLL_MAX_ERRORS"
        --sandoq-gateway-retry-attempts "$OCI_RUNNER_GATEWAY_RETRY_ATTEMPTS"
        --sandoq-gateway-retry-interval "$OCI_RUNNER_GATEWAY_RETRY_INTERVAL"
        --sandoq-podman-ignore-chown-errors "$OCI_RUNNER_PODMAN_IGNORE_CHOWN_ERRORS"
        --sandoq-require-resource-limits "$OCI_RUNNER_REQUIRE_RESOURCE_LIMITS"
        --sandoq-exec-timeout-ceiling "$OCI_RUNNER_EXEC_TIMEOUT_CEILING"
        --sandoq-task-pids-limit "$OCI_RUNNER_TASK_PIDS_LIMIT"
        --sandoq-observability "$OCI_RUNNER_OBSERVABILITY"
        --sandoq-pool-heartbeat-timeout "$OCI_RUNNER_POOL_HEARTBEAT_TIMEOUT"
        --sandoq-pool-create-workers "$OCI_RUNNER_POOL_CREATE_WORKERS"
        --sandoq-pool-bootstrap-workers "$OCI_RUNNER_POOL_BOOTSTRAP_WORKERS"
        --sandoq-pool-bootstrap-per-image "$OCI_RUNNER_POOL_BOOTSTRAP_PER_IMAGE"
        --sandoq-pool-drain-workers "$OCI_RUNNER_POOL_DRAIN_WORKERS"
        --sandoq-pool-drain-timeout "$OCI_RUNNER_POOL_DRAIN_TIMEOUT"
        --sandoq-pool-renew-workers "$OCI_RUNNER_POOL_RENEW_WORKERS"
        --sandoq-session-reuse "$OCI_RUNNER_SESSION_REUSE"
        --sandoq-pool-max-reuse-count "$OCI_RUNNER_POOL_MAX_REUSE_COUNT"
        --sandoq-pool-reuse-jitter "$OCI_RUNNER_POOL_REUSE_JITTER"
        --sandoq-image-cache-max-entries "$OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES"
        --sandoq-secret-cache-ttl "$OCI_RUNNER_SECRET_CACHE_TTL"
        --sandoq-lease-profile "$SANDOQ_LEASE_PROFILE"
        --sandoq-lease-duration "$OCI_RUNNER_LEASE_DURATION"
        --sandoq-pool-renew-interval "$OCI_RUNNER_POOL_RENEW_INTERVAL"
        --sandoq-managed-shell-recovery "$managed_shell_recovery_policy"
    )
else
    vmvm_tb_v2_sha256=$(
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 - "$project_dir" <<'PY'
import sys
from pathlib import Path
from eval_run_identity import _vmvm_source_sha256

print(_vmvm_source_sha256(Path(sys.argv[1])))
PY
    )
    identity_args+=(
        --vmvm-tb-v2-sha256 "$vmvm_tb_v2_sha256"
        --vacli-bin "${VACLI_BIN:-/public/fbpkgs/x86_64/vacli/stable/vacli}"
        --vacli-max-concurrent-leases "${VACLI_MAX_CONCURRENT_LEASES:-4}"
        --vacli-lease-retries "${VACLI_LEASE_RETRIES:-20}"
        --vacli-max-pull-retries "${VACLI_MAX_PULL_RETRIES:-20}"
        --vacli-image-pull-timeout-seconds "${VACLI_IMAGE_PULL_TIMEOUT_SECONDS:-3600}"
        --vacli-container-privileged "${VACLI_CONTAINER_PRIVILEGED:-1}"
    )
fi
if [[ ( "$role" == kimi-direct-smoke || "$role" == kimi-direct-capacity-smoke ) ]] \
    && [[ "$(python3 - "$eval_config" <<'PY'
import sys
import tomllib
with open(sys.argv[1], "rb") as handle:
    print(tomllib.load(handle).get("taskset", {}).get("dataset_revision", ""))
PY
)" == ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366 ]]; then
    identity_args+=(--dataset-revision ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366)
else
    identity_args+=(
        --dataset-archive /checkpoint/ram/tianhaowu/terminal_bench_vmvm/downloads/terminal-bench-prebuilt-v4.0.0.tar.gz
        --dataset-archive-sha256 6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e
        --dataset-content-sha256 564a42a4e2ce0a5efd23758656e4e419b3566a36234dfc09bae1029bc15326b2
    )
fi
if [[ "$role" == kimi-direct-tb4 ]]; then
    identity_args+=(
        --smoke-checkpoint "${DIRECT_KIMI_SMOKE_CHECKPOINT:?Set DIRECT_KIMI_SMOKE_CHECKPOINT}"
        --smoke-checkpoint-sha256 "${DIRECT_KIMI_SMOKE_CHECKPOINT_SHA256:?Set DIRECT_KIMI_SMOKE_CHECKPOINT_SHA256}"
    )
fi
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/eval_run_identity.py" "${identity_args[@]}" >/dev/null
if [[ "$sandbox_provider" == vmvm ]]; then
    capacity_private_key=${DIRECT_KIMI_CAPACITY_PRIVATE_KEY:?Set DIRECT_KIMI_CAPACITY_PRIVATE_KEY}
    capacity_public_key=${DIRECT_KIMI_CAPACITY_PUBLIC_KEY:?Set DIRECT_KIMI_CAPACITY_PUBLIC_KEY}
    resource_manifest_sha256=${DIRECT_KIMI_RESOURCE_MANIFEST_SHA256:?Set DIRECT_KIMI_RESOURCE_MANIFEST_SHA256}
    for path in "$capacity_private_key" "$capacity_public_key"; do
        if [[ ! -f "$path" || -L "$path" ]]; then
            printf 'Direct Kimi capacity signing input is unavailable or unsafe\n' >&2
            exit 2
        fi
    done
    if [[ "$(stat -c '%a' "$capacity_private_key")" != 600 ]]; then
        printf 'Direct Kimi capacity private key is not mode 0600\n' >&2
        exit 2
    fi
    capacity_request="$output_dir/control/vmvm_capacity_request.json"
    capacity_receipt="$output_dir/control/vmvm_capacity_receipt.json"
    capacity_binding=$(
        "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 -m vmvm_tb_v2._vacli.capacity_attestor \
        --eval-run-identity "$output_dir/eval_run_identity.json" \
        --eval-invocations "$output_dir/eval_invocations.jsonl" \
        --provenance "$output_dir/provenance.txt" \
        --manifest-sha256 "$resource_manifest_sha256" \
        --selector-sha256 "$validated_task_sha256" \
        --public-key "$capacity_public_key" \
        --output "$capacity_request"
    )
    IFS=$'\t' read -r capacity_identity_sha256 capacity_invocation_sha256 capacity_extra <<< "$capacity_binding"
    if [[ ! "$capacity_identity_sha256" =~ ^[0-9a-f]{64}$ \
        || ! "$capacity_invocation_sha256" =~ ^[0-9a-f]{64}$ \
        || -n "$capacity_extra" || "$capacity_binding" == *$'\n'* ]]; then
        printf 'Direct Kimi capacity binding is invalid\n' >&2
        exit 2
    fi
    export VMVM_CLEANUP_RECEIPT_LOG="$output_dir/control/vmvm_cleanup_receipts.jsonl"
    export VMVM_CLEANUP_RUN_IDENTITY_SHA256="$capacity_identity_sha256"
    export VMVM_CAPACITY_REQUEST="$capacity_request"
    export VMVM_CAPACITY_RECEIPT="$capacity_receipt"
    export VMVM_CAPACITY_PRIVATE_KEY="$capacity_private_key"
fi
if [[ "$preflight_only" == 1 ]]; then
    printf 'direct-kimi-identity-preflight-ok\n'
    exit 0
fi

exec 9>"$output_dir/.writer.lock"
if ! flock -n 9; then
    printf 'Another evaluator owns the direct Kimi stage\n' >&2
    exit 2
fi
export OPENAI_API_KEY=EMPTY
eval_log="$output_dir/control/evaluator.private.log"
set +e
DIRECT_KIMI_ZERO_MODEL_RESUME_ATTEMPTS=${DIRECT_KIMI_ZERO_MODEL_RESUME_ATTEMPTS:-1} \
    /usr/bin/bash -p "$workflow_dir/run_eval_with_zero_model_resume.sh" \
    >"$eval_log" 2>&1
eval_status=$?
set -e
cleanup_status=0
if [[ "$sandbox_provider" == sandoq ]]; then
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/sandoq_pool_cleanup.py" \
        --output-dir "$output_dir" --base-url "$OCI_RUNNER_BASE_URL" --owner "$SANDOQ_OWNER" \
        --concurrency "$OCI_RUNNER_POOL_DRAIN_WORKERS" || cleanup_status=$?
    if [[ "$cleanup_status" -eq 0 ]]; then
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$workflow_dir/sanitize_sandoq_cleanup_audit.py" \
            --raw-audit "$output_dir/pool_cleanup_audit.json" \
            --event-log "$OCI_RUNNER_POOL_EVENT_LOG" --wal "$OCI_RUNNER_POOL_WAL" \
            --drain-marker "${OCI_RUNNER_POOL_SOCKET%.sock}.drained.json" \
            --output "$output_dir/sandoq_cleanup_audit.json" || cleanup_status=$?
    fi
elif [[ ! -s "$output_dir/control/vmvm_runtime_lifecycle.jsonl" \
    || ! -s "$output_dir/control/vmvm_cleanup_receipts.jsonl" \
    || ! -s "$output_dir/control/vmvm_capacity_receipt.json" ]]; then
    cleanup_status=1
fi
if [[ -n "$endpoint_walltime_receipt" ]]; then
    if [[ "$(sha256sum -- "$endpoint_walltime_receipt" | cut -d' ' -f1)" \
        != "$endpoint_walltime_receipt_file_sha256" ]]; then
        printf 'Direct Kimi endpoint walltime receipt changed during evaluation\n' >&2
        exit 2
    fi
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/kimi_endpoint_walltime_gate.py" validate \
        --manifest "$worker_manifest" \
        --manifest-sha256 "$worker_manifest_sha256" \
        --profile "$endpoint_walltime_profile" \
        --minimum-remaining-seconds "$endpoint_minimum_remaining_seconds" \
        --task-count "$approved_task_count" \
        --receipt "$endpoint_walltime_receipt" >/dev/null
fi
if [[ "$eval_status" -ne 0 ]]; then
    exit "$eval_status"
fi
exit "$cleanup_status"
