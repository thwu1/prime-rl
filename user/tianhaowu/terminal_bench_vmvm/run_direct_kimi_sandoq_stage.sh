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
output_dir=${OUTPUT_DIR:?Set OUTPUT_DIR}
role=${DIRECT_KIMI_ROLE:?Set DIRECT_KIMI_ROLE}
approved_task_file=${DIRECT_KIMI_APPROVED_TASK_FILE:?Set DIRECT_KIMI_APPROVED_TASK_FILE}
approved_task_file_sha256=${DIRECT_KIMI_APPROVED_TASK_FILE_SHA256:?Set DIRECT_KIMI_APPROVED_TASK_FILE_SHA256}
worker_manifest=${DIRECT_KIMI_WORKER_MANIFEST:?Set DIRECT_KIMI_WORKER_MANIFEST}
worker_manifest_sha256=${DIRECT_KIMI_WORKER_MANIFEST_SHA256:?Set DIRECT_KIMI_WORKER_MANIFEST_SHA256}
client_base_url=${DIRECT_KIMI_BASE_URL:?Set DIRECT_KIMI_BASE_URL}
expected_revision=${DIRECT_KIMI_EXPECTED_PRIME_RL_REVISION:?Set DIRECT_KIMI_EXPECTED_PRIME_RL_REVISION}
preflight_only=${DIRECT_KIMI_PREFLIGHT_ONLY:-0}

if [[ "$role" != kimi-direct-smoke && "$role" != kimi-direct-tb4 ]]; then
    printf 'Invalid direct Kimi stage role\n' >&2
    exit 2
fi
if [[ "$preflight_only" != 0 && "$preflight_only" != 1 ]]; then
    printf 'DIRECT_KIMI_PREFLIGHT_ONLY must be 0 or 1\n' >&2
    exit 2
fi
if [[ ${SANDOQ_PROVIDER_CONTEXT_ACTIVE:-} != 1 \
    || -z ${SANDOQ_PROVIDER_CONTEXT_RECEIPT:-} \
    || "$OCI_RUNNER_ENVIRONMENT" != oci-runner \
    || "$SANDOQ_EFFECTIVE_TASK_NETWORK" != public \
    || -n ${OCI_RUNNER_TASK_NETWORK:-} ]]; then
    printf 'Direct Kimi stage requires the sealed public-network Sandoq context\n' >&2
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
    != 80e58e7e2b194e9c1b8dc0990c00b7a839127eea ]]; then
    printf 'Direct Kimi stage requires the approved Verifiers revision\n' >&2
    exit 2
fi
if [[ ! -d "$x86_site/pydantic" || ! -d "$sandoq_site/sandoq_client" || ! -x "$x86_uv" ]]; then
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
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" verify \
    --receipt "$SANDOQ_PROVIDER_CONTEXT_RECEIPT" >/dev/null

mkdir -p "$output_dir/control"
pool_socket_dir="${SLURM_TMPDIR:-/tmp}/oci-runner-pool-${UID}"
mkdir -p "$pool_socket_dir"
chmod 0700 "$pool_socket_dir"
export OCI_RUNNER_POOL_SOCKET="$pool_socket_dir/${SLURM_JOB_ID}.sock"
export PRIME_RL_OUTPUT_DIR="$output_dir"
export OCI_RUNNER_POOL_WAL="$output_dir/control/sandoq-pool.wal.jsonl"
export OCI_RUNNER_POOL_EVENT_LOG="$output_dir/pool_events.jsonl"
for stale in inputs config.toml results.jsonl provenance.txt eval_run_identity.json eval_invocations.jsonl \
    pool_cleanup_audit.json sandoq_cleanup_audit.json direct_kimi_router_final.json; do
    if [[ -e "$output_dir/$stale" || -L "$output_dir/$stale" ]]; then
        printf 'Direct Kimi stage found stale output evidence\n' >&2
        exit 2
    fi
done

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/snapshot_eval_inputs.py" "$eval_config" "$output_dir/inputs"
approval_metadata=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/validate_task_approval.py" \
        --inputs-dir "$output_dir/inputs" \
        --approved-task-file "$approved_task_file" \
        --approved-task-file-sha256 "$approved_task_file_sha256"
)
IFS=$'\t' read -r validated_task_sha256 validated_task_count approval_extra <<< "$approval_metadata"
if [[ "$validated_task_sha256" != "$approved_task_file_sha256" \
    || ! "$validated_task_count" =~ ^[1-9][0-9]*$ \
    || -n "$approval_extra" || "$approval_metadata" == *$'\n'* ]]; then
    printf 'Direct Kimi task approval validation failed\n' >&2
    exit 2
fi

clean_tree_sha256=$(printf '' | sha256sum | cut -d' ' -f1)
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
image_manifest_sha256=$(sha256sum "$output_dir/inputs/image_manifest.json" | cut -d' ' -f1)
manifest_metadata=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" python3 - "$worker_manifest" <<'PY'
import sys
from pathlib import Path
from direct_kimi_workers import validate_saved_manifest

manifest = validate_saved_manifest(Path(sys.argv[1]))
print(manifest["source_spec_sha256"], manifest["endpoint_bundle_sha256"], sep="\t")
PY
)
IFS=$'\t' read -r direct_spec_sha256 direct_endpoint_bundle_sha256 manifest_extra <<< "$manifest_metadata"
if [[ ! "$direct_spec_sha256" =~ ^[0-9a-f]{64}$ \
    || ! "$direct_endpoint_bundle_sha256" =~ ^[0-9a-f]{64}$ \
    || -n "$manifest_extra" || "$manifest_metadata" == *$'\n'* ]]; then
    printf 'Direct Kimi worker manifest validation failed\n' >&2
    exit 2
fi

case "$SANDOQ_TRANSPORT_MODE" in
    auto) sandoq_transport_proxy_policy=official-client-auto ;;
    loopback) sandoq_transport_proxy_policy=official-client-supervised-loopback-connect-proxy ;;
    *) printf 'Direct Kimi Sandoq transport mode is invalid\n' >&2; exit 2 ;;
esac
identity_args=(
    --mode fresh
    --role "$role"
    --sandbox-provider sandoq
    --output-dir "$output_dir"
    --inputs-dir "$output_dir/inputs"
    --client-base-url "$client_base_url"
    --expected-model Kimi-K3
    --approved-task-file-sha256 "$validated_task_sha256"
    --approved-task-count "$validated_task_count"
    --dataset-archive /checkpoint/ram/tianhaowu/terminal_bench_vmvm/downloads/terminal-bench-prebuilt-v4.0.0.tar.gz
    --dataset-archive-sha256 6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e
    --dataset-content-sha256 564a42a4e2ce0a5efd23758656e4e419b3566a36234dfc09bae1029bc15326b2
    --project-root "$project_dir"
    --prime-rl-commit "$expected_revision"
    --prime-rl-tree-sha256 "$clean_tree_sha256"
    --verifiers-commit "$(git -C "$project_dir/deps/verifiers" rev-parse HEAD)"
    --verifiers-tree-sha256 "$clean_tree_sha256"
    --renderers-commit "$(git -C "$project_dir/deps/renderers" rev-parse HEAD)"
    --renderers-tree-sha256 "$clean_tree_sha256"
    --sandoq-provider-commit f7313db42eea4b3be8bcbe16a8072f73cf6abed5
    --sandoq-provider-tree 9cb669ad045a67e92bbd0a04fb353489457003aa
    --sandoq-client-version "$sandoq_client_version"
    --sandoq-site "$sandoq_site"
    --sandoq-site-sha256 "$sandoq_site_sha256"
    --derived-image-manifest-sha256 "$image_manifest_sha256"
    --sandoq-environment "$OCI_RUNNER_ENVIRONMENT"
    --sandoq-task-network "$SANDOQ_EFFECTIVE_TASK_NETWORK"
    --sandoq-pool-size "$OCI_RUNNER_POOL_SIZE"
    --sandoq-pool-min-size "$OCI_RUNNER_POOL_MIN_SIZE"
    --sandoq-tunnel-policy host-interception-no-tunnel
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
    --sandoq-allow-dockerhub-fallback 1
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
    --sandoq-lease-duration "$OCI_RUNNER_LEASE_DURATION"
    --sandoq-pool-renew-interval "$OCI_RUNNER_POOL_RENEW_INTERVAL"
    --direct-worker-manifest "$worker_manifest"
    --direct-worker-manifest-sha256 "$worker_manifest_sha256"
    --direct-spec-sha256 "$direct_spec_sha256"
    --direct-endpoint-bundle-sha256 "$direct_endpoint_bundle_sha256"
    --direct-router-policy consistent_hash
    --direct-request-id-headers x-session-id
    --direct-provider-concurrency 24
    --direct-request-timeout-seconds 43200
    --direct-retries 0
    --direct-worker-count 24
    --invocation-host "$(hostname)"
    --slurm-job-id "$SLURM_JOB_ID"
)
if [[ "$role" == kimi-direct-tb4 ]]; then
    identity_args+=(
        --smoke-checkpoint "${DIRECT_KIMI_SMOKE_CHECKPOINT:?Set DIRECT_KIMI_SMOKE_CHECKPOINT}"
        --smoke-checkpoint-sha256 "${DIRECT_KIMI_SMOKE_CHECKPOINT_SHA256:?Set DIRECT_KIMI_SMOKE_CHECKPOINT_SHA256}"
    )
fi
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/eval_run_identity.py" "${identity_args[@]}" >/dev/null
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
set +e
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 -c 'from verifiers.v1.cli.eval.main import main; main()' --resume "$output_dir"
eval_status=$?
set -e
cleanup_status=0
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
if [[ "$eval_status" -ne 0 ]]; then
    exit "$eval_status"
fi
exit "$cleanup_status"
