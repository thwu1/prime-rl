#!/usr/bin/bash -p
set +x
set -euo pipefail
umask 077

blocked() {
    printf '{"code":"%s","state":"blocked"}\n' "$1" >&2
    exit 2
}

(( $# == 0 )) || blocked arguments_forbidden

project_dir=${PROJECT_DIR:?}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_sdk1_82068}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
eval_config=${EVAL_CONFIG:?}
output_dir=${OUTPUT_DIR:?}
role=${DIRECT_KIMI_ROLE:?}
approved_task_file=${DIRECT_KIMI_APPROVED_TASK_FILE:?}
approved_task_file_sha256=${DIRECT_KIMI_APPROVED_TASK_FILE_SHA256:?}
approved_task_count=${DIRECT_KIMI_APPROVED_TASK_COUNT:?}
rollout_concurrency=${DIRECT_KIMI_ROLLOUT_CONCURRENCY:?}
worker_manifest=${DIRECT_KIMI_WORKER_MANIFEST:?}
worker_manifest_sha256=${DIRECT_KIMI_WORKER_MANIFEST_SHA256:?}
client_base_url=${DIRECT_KIMI_BASE_URL:?}
expected_revision=${DIRECT_KIMI_EXPECTED_PRIME_RL_REVISION:?}
launch_certificate=${DIRECT_KIMI_PRODUCTION_LAUNCH:?}
launch_certificate_sha256=${DIRECT_KIMI_PRODUCTION_LAUNCH_SHA256:?}
rotation_state=${KIMI_ECR_ROTATION_STATE_FILE:?}

[[ "$role" == kimi-direct-mobius && "$approved_task_count" == 2499 ]] \
    || blocked production_role_invalid
[[ "$rollout_concurrency" =~ ^[1-9][0-9]*$ ]] || blocked production_concurrency_invalid
(( rollout_concurrency <= 64 )) || blocked production_concurrency_invalid
[[ ${SANDOQ_PROVIDER_CONTEXT_ACTIVE:-} == 1 \
    && -n ${SANDOQ_PROVIDER_CONTEXT_RECEIPT:-} \
    && ${OCI_RUNNER_ENVIRONMENT:-} == oci-runner-firecracker \
    && ${OCI_RUNNER_TOKEN_FILE:-} == /home/tianhaowu/.config/oci-runner/firecracker-token \
    && ${SANDOQ_EFFECTIVE_TASK_NETWORK:-} == public \
    && ${OCI_RUNNER_TASK_NETWORK:-} == host \
    && ${OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK:-} == 0 \
    && ${SANDOQ_PROVIDER_PROFILE_SHA256:-} == 7dd88ca6c6cde5ed5b22bf8f621462a46425f939478f79469e31da2e582b27df \
    && ${SANDOQ_RUNTIME_SMOKE_RECEIPT_SHA256:-} == 39108c28f052f4689e863fedaa81430b479915797a4e6836ed090344c5ee3276 \
    && ${SANDOQ_RUNTIME_RESOURCE_RECEIPT_SHA256:-} == ce3fc3ed2ead1aaf8c71fc35e5dae324f1be9d51b4e7fffff7bc99d1a47adbf6 \
    && ${DIRECT_KIMI_MINISWE_COMPATIBILITY_RECEIPT_SHA256:-} == cee344d3c9bc3c18f602a0ad217ade7395db263d50cd8d4c428507a21de86220 \
    && ${SANDOQ_LEASE_PROFILE:-} == kimi-tb4-long \
    && ${OCI_RUNNER_LEASE_DURATION:-} == 12h \
    && ${OCI_RUNNER_POOL_RENEW_INTERVAL:-} == 5m \
    && ${OCI_RUNNER_MANAGED_SHELL_RECOVERY:-} == 1 \
    ]] \
    || blocked provider_context_invalid
[[ ${OCI_RUNNER_POOL_SIZE:-} == "$rollout_concurrency" ]] || blocked provider_capacity_mismatch
[[ "$(git -C "$project_dir" rev-parse HEAD)" == "$expected_revision" \
    && -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" \
    && -z "$(git -C "$project_dir/deps/verifiers" status --porcelain=v1 --untracked-files=all)" \
    && -z "$(git -C "$project_dir/deps/renderers" status --porcelain=v1 --untracked-files=all)" ]] \
    || blocked source_identity_invalid
[[ "$(git -C "$project_dir/deps/verifiers" rev-parse HEAD)" \
    == 3df6efa9e9f6bdc8a013df7759a03074aec79111 ]] \
    || blocked source_identity_invalid
[[ -x "$x86_uv" && -d "$x86_site/pydantic" && -d "$sandoq_site/sandoq_client" ]] \
    || blocked runtime_unavailable
for path in "$eval_config" "$approved_task_file" "$worker_manifest" "$launch_certificate" "$rotation_state"; do
    [[ -f "$path" && ! -L "$path" ]] || blocked production_input_invalid
done
[[ ! -e "$output_dir" && ! -L "$output_dir" ]] || blocked output_namespace_not_fresh

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${SLURM_TMPDIR:-/tmp}/kimi-production-pycache-${SLURM_JOB_ID:?}"
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site"

verified=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/kimi_sandoq_production.py" validate-launch \
        --launch "$launch_certificate" \
        --launch-sha256 "$launch_certificate_sha256" \
        --format tsv
)
IFS=$'\t' read -r verified_config verified_selector verified_selector_sha256 \
    verified_manifest verified_manifest_sha256 verified_output verified_concurrency verified_extra \
    <<< "$verified"
if [[ -n "$verified_extra" || "$verified" == *$'\n'* \
    || "$verified_config" != "$eval_config" \
    || "$verified_selector" != "$approved_task_file" \
    || "$verified_selector_sha256" != "$approved_task_file_sha256" \
    || "$verified_manifest" != "$worker_manifest" \
    || "$verified_manifest_sha256" != "$worker_manifest_sha256" \
    || "$verified_output" != "$output_dir" \
    || "$verified_concurrency" != "$rollout_concurrency" ]]; then
    blocked launch_binding_invalid
fi

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" verify \
    --receipt "$SANDOQ_PROVIDER_CONTEXT_RECEIPT" >/dev/null \
    || blocked provider_context_invalid

mkdir -p "$output_dir/control"
chmod 0700 "$output_dir" "$output_dir/control"
export PRIME_RL_OUTPUT_DIR="$output_dir"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" snapshot \
    --receipt "$SANDOQ_PROVIDER_CONTEXT_RECEIPT" \
    --output "$output_dir/sandoq-provider-context.json" >/dev/null \
    || blocked provider_context_snapshot_invalid
pool_socket_dir="${SLURM_TMPDIR:-/tmp}/oci-runner-pool-${UID}"
mkdir -p "$pool_socket_dir"
chmod 0700 "$pool_socket_dir"
export OCI_RUNNER_POOL_SOCKET="$pool_socket_dir/${SLURM_JOB_ID}.sock"
export OCI_RUNNER_POOL_WAL="$output_dir/control/sandoq-pool.wal.jsonl"
export OCI_RUNNER_POOL_EVENT_LOG="$output_dir/pool_events.jsonl"
for stale in inputs config.toml results.jsonl provenance.txt eval_run_identity.json \
    eval_invocations.jsonl pool_cleanup_audit.json sandoq_cleanup_audit.json \
    direct_kimi_router_final.json ecr_rotation_audit.json; do
    [[ ! -e "$output_dir/$stale" && ! -L "$output_dir/$stale" ]] \
        || blocked stale_output_evidence
done

cd "$project_dir"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/snapshot_eval_inputs.py" "$eval_config" "$output_dir/inputs"
approval_metadata=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/validate_task_approval.py" \
        --inputs-dir "$output_dir/inputs" \
        --approved-task-file "$approved_task_file" \
        --approved-task-file-sha256 "$approved_task_file_sha256" \
        --approved-config "$eval_config" \
        --approved-config-sha256 "$(sha256sum -- "$eval_config" | cut -d' ' -f1)"
)
IFS=$'\t' read -r validated_task_sha256 validated_task_count approval_extra <<< "$approval_metadata"
[[ "$validated_task_sha256" == "$approved_task_file_sha256" \
    && "$validated_task_count" == 2499 \
    && -z "$approval_extra" \
    && "$approval_metadata" != *$'\n'* ]] \
    || blocked task_approval_invalid

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
import sys

distributions = [
    distribution
    for distribution in metadata.distributions(path=[sys.argv[1]])
    if distribution.metadata["Name"].lower().replace("_", "-") == "sandoq-client"
]
if len(distributions) != 1:
    raise SystemExit(2)
print(distributions[0].version)
PY
)
image_manifest_sha256=$(sha256sum -- "$output_dir/inputs/image_manifest.json" | cut -d' ' -f1)
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
    router.get("capacity_profile", "-"),
    router.get("per_worker_capacity", 0),
    sep="\t",
)
PY
)
IFS=$'\t' read -r direct_spec_sha256 direct_endpoint_bundle_sha256 direct_capacity_profile \
    direct_per_worker_capacity manifest_extra <<< "$manifest_metadata"
[[ "$direct_spec_sha256" =~ ^[0-9a-f]{64}$ \
    && "$direct_endpoint_bundle_sha256" =~ ^[0-9a-f]{64}$ \
    && "$direct_capacity_profile" == sandoq-c64-w2-v1 \
    && "$direct_per_worker_capacity" == 2 \
    && -z "$manifest_extra" \
    && "$manifest_metadata" != *$'\n'* ]] \
    || blocked worker_manifest_invalid

case "$SANDOQ_TRANSPORT_MODE" in
    auto) sandoq_transport_proxy_policy=official-client-auto ;;
    loopback) sandoq_transport_proxy_policy=official-client-supervised-loopback-connect-proxy ;;
    *) blocked transport_mode_invalid ;;
esac
identity_args=(
    --mode fresh
    --role kimi-direct-mobius
    --sandbox-provider sandoq
    --output-dir "$output_dir"
    --inputs-dir "$output_dir/inputs"
    --client-base-url "$client_base_url"
    --expected-model Kimi-K3
    --approved-task-file-sha256 "$validated_task_sha256"
    --approved-task-count "$validated_task_count"
    --approved-config-sha256 "$(sha256sum -- "$eval_config" | cut -d' ' -f1)"
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
    --direct-provider-concurrency 64
    --direct-per-worker-capacity "$direct_per_worker_capacity"
    --direct-request-timeout-seconds 43200
    --direct-retries 0
    --direct-worker-count 24
    --promotion-certificate "$launch_certificate"
    --promotion-certificate-sha256 "$launch_certificate_sha256"
    --dataset-revision ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366
    --invocation-host "$(hostname)"
    --slurm-job-id "$SLURM_JOB_ID"
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
    --sandoq-tunnel-policy native-sandoq-reverse-tunnel
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
    --sandoq-allow-dockerhub-fallback "$OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK"
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
    --sandoq-managed-shell-recovery definitive-404-410-single-replay-v1
)
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/eval_run_identity.py" "${identity_args[@]}" >/dev/null

cleanup_command="$output_dir/control/ecr_cleanup_command.json"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/kimi_sandoq_production.py" cleanup-command \
    --project-root "$project_dir" \
    --expected-revision "$expected_revision" \
    --output-dir "$output_dir" \
    --owner "$SANDOQ_OWNER" \
    --pool-socket "$OCI_RUNNER_POOL_SOCKET" \
    --output "$cleanup_command" >/dev/null

exec 9>"$output_dir/.writer.lock"
flock -n 9 || blocked writer_active
export OPENAI_API_KEY=EMPTY
guard_log="$output_dir/control/ecr_guard_events.jsonl"
eval_log="$output_dir/control/evaluator.private.log"
set +e
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/sandoq_ecr_rotation.py" guard \
    --token-file "$OCI_RUNNER_ECR_TOKEN_FILE" \
    --state-file "$rotation_state" \
    --event-log "$guard_log" \
    --cleanup-command-json "$cleanup_command" \
    -- env DIRECT_KIMI_ZERO_MODEL_RESUME_ATTEMPTS=${DIRECT_KIMI_ZERO_MODEL_RESUME_ATTEMPTS:-1} \
        /usr/bin/bash -p "$workflow_dir/run_eval_with_zero_model_resume.sh" \
    >"$eval_log" 2>&1
eval_status=$?
set -e

[[ -s "$output_dir/sandoq_cleanup_audit.json" ]] || blocked verified_cleanup_missing
exit "$eval_status"
