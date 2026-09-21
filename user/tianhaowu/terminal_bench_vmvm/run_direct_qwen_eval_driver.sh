#!/bin/bash
# shellcheck shell=bash

set -euo pipefail
umask 077

preflight_only=0
if (( $# == 1 )) && [[ $1 == --preflight ]]; then
    preflight_only=1
elif (( $# != 0 )); then
    printf 'The direct Qwen eval driver accepts only --preflight\n' >&2
    exit 2
fi

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_ram_prime_f7313db4}
sandoq_extension="$project_dir/extensions/sandoq"
sandoq_provider_commit=4890302104d76220cef791c86d2009168597d35f
sandoq_provider_tree=33f092a3982916660e12f472588e6ce34a906fc2
resume_dir=${RESUME_DIR:-}
output_dir=${OUTPUT_DIR:?The direct Qwen wrapper must set OUTPUT_DIR}
inference_base_url=${INFERENCE_BASE_URL:?The direct Qwen wrapper must set INFERENCE_BASE_URL}
approved_task_file=${DIRECT_QWEN_APPROVED_TASK_FILE:?Missing direct Qwen task approval}
approved_task_file_sha256=${DIRECT_QWEN_APPROVED_TASK_FILE_SHA256:?Missing direct Qwen task approval hash}
source_continuation_plan=${QWEN_SANDOQ_SOURCE_CONTINUATION_PLAN:-}
source_continuation_plan_sha256=${QWEN_SANDOQ_SOURCE_CONTINUATION_PLAN_SHA256:-}
source_continuation_mode=0
if [[ -n "$source_continuation_plan" || -n "$source_continuation_plan_sha256" ]]; then
    source_continuation_mode=1
    if [[ -z "$source_continuation_plan" \
        || ! "$source_continuation_plan_sha256" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'Source-continuation plan inputs are invalid\n' >&2
        exit 2
    fi
fi
deployment_root=${DIRECT_QWEN_DEPLOYMENT_ROOT:-/checkpoint/ram/shared/vllm_deployments_v2/shared_qwen38_2p4t}
worker_manifest="$output_dir/direct_workers.json"
unset PYTHONPATH PYTHONHOME

if [[ -n ${EVAL_RUN_ROLE:-} || -n ${EVAL_MODEL:-} || -n ${EVAL_APPROVED_TASK_FILE:-} \
    || -n ${INFERENCE_DEPLOYMENT_ID:-} || -n ${INFERENCE_JOB_ID:-} \
    || -n ${INFERENCE_PROXY_INFO:-} || -n ${INFERENCE_PROXY_URL:-} ]]; then
    printf 'Direct Qwen driver received a forbidden generic-eval override\n' >&2
    exit 2
fi
if [[ ${OPENAI_API_KEY:-EMPTY} != EMPTY ]]; then
    printf 'Direct Qwen driver accepts only OPENAI_API_KEY=EMPTY\n' >&2
    exit 2
fi
if [[ "$(uname -m)" != x86_64 || ! -d "$x86_site/pydantic" || ! -x "$x86_uv" ]]; then
    printf 'Missing x86_64 direct Qwen evaluator runtime\n' >&2
    exit 2
fi

if [[ -n "$resume_dir" ]]; then
    if [[ "$output_dir" != "$resume_dir" ]]; then
        printf 'Direct Qwen resume/output directories disagree\n' >&2
        exit 2
    fi
    eval_config="$resume_dir/config.toml"
else
    eval_config=${EVAL_CONFIG:?The direct Qwen wrapper must set EVAL_CONFIG}
fi

sandbox_provider=$(python3 - "$eval_config" <<'PY'
import sys
import tomllib
with open(sys.argv[1], "rb") as handle:
    print(tomllib.load(handle).get("harness", {}).get("runtime", {}).get("type", ""))
PY
)
if [[ "$sandbox_provider" != vmvm && "$sandbox_provider" != sandoq ]]; then
    printf 'Direct Qwen config must select vmvm or sandoq explicitly\n' >&2
    exit 2
fi
if [[ "$source_continuation_mode" -eq 1 && "$sandbox_provider" != sandoq ]]; then
    printf 'Source continuation requires the Sandoq runtime\n' >&2
    exit 2
fi
if [[ "$source_continuation_mode" -eq 1 \
    && ( -L "$output_dir" || ! -d "$output_dir" \
        || "$(stat -c '%u' -- "$output_dir")" != "$UID" \
        || "$(stat -c '%a' -- "$output_dir")" != 700 ) ]]; then
    printf 'Source continuation output directory is not private\n' >&2
    exit 2
fi
if [[ "$sandbox_provider" == sandoq && -n "$resume_dir" ]]; then
    printf 'Sandoq direct Qwen runs require a fresh output directory\n' >&2
    exit 2
fi
if [[ "$sandbox_provider" == sandoq ]]; then
    pool_socket_dir="${SLURM_TMPDIR:-/tmp}/oci-runner-pool-${UID}"
    expected_pool_socket="$pool_socket_dir/${SLURM_JOB_ID:?}.sock"
    for stale in \
        "$output_dir/inputs" "$output_dir/config.toml" "$output_dir/results.jsonl" \
        "$output_dir/provenance.txt" "$output_dir/eval_run_identity.json" \
        "$output_dir/pool_events.jsonl" "$output_dir/control/sandoq-pool.wal.jsonl" \
        "$output_dir/pool_cleanup_audit.json" "$output_dir/sandoq_cleanup_audit.json" \
        "$output_dir/direct_qwen_sandoq_certificate.json" \
        "$output_dir/qwen_sandoq_source_continuation_certificate.json" \
        "$output_dir/source_continuation_identity.json" "$expected_pool_socket" \
        "$expected_pool_socket.owner.json" "${expected_pool_socket%.sock}.drained.json"; do
        if [[ -e "$stale" || -L "$stale" ]]; then
            printf 'Sandoq fresh run found stale lifecycle evidence\n' >&2
            exit 2
        fi
    done
fi
read -r sandoq_stage_count sandoq_capacity sandoq_create_workers sandoq_bootstrap_workers \
    sandoq_drain_workers sandoq_renew_workers < <(python3 - "$eval_config" <<'PY'
import sys
import tomllib
with open(sys.argv[1], "rb") as handle:
    config = tomllib.load(handle)
capacity = min(config["num_tasks"], config["max_concurrent"])
print(config["num_tasks"], capacity, min(capacity, 4), min(capacity, 64), min(capacity, 32), min(capacity, 16))
PY
)

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site"
cd "$project_dir"

if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" \
    || -n "$(git -C deps/verifiers status --porcelain=v1 --untracked-files=all)" \
    || -n "$(git -C deps/renderers status --porcelain=v1 --untracked-files=all)" ]]; then
    printf 'Prime-RL, Verifiers, and Renderers worktrees must all be clean\n' >&2
    exit 2
fi
if [[ "$sandbox_provider" == sandoq ]]; then
    if [[ "$(git -C deps/verifiers rev-parse HEAD)" \
        != 80e58e7e2b194e9c1b8dc0990c00b7a839127eea ]]; then
        printf 'Verifiers revision is not the approved public Sandoq host-harness source\n' >&2
        exit 2
    fi
    if [[ ${SANDOQ_PROVIDER_CONTEXT_ACTIVE:-} != 1 \
        || -z ${SANDOQ_PROVIDER_CONTEXT_RECEIPT:-} ]]; then
        printf 'Sandoq provider context must supervise the complete evaluator lifecycle\n' >&2
        exit 2
    fi
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" verify \
        --receipt "$SANDOQ_PROVIDER_CONTEXT_RECEIPT" >/dev/null
    if [[ ! -f "$sandoq_extension/UPSTREAM.md" ]] \
        || ! grep -Fq "$sandoq_provider_commit" "$sandoq_extension/UPSTREAM.md" \
        || ! grep -Fq '10b5bd9bbc76eba1b8253637e1869d6b63b7fc42' "$sandoq_extension/UPSTREAM.md"; then
        printf 'Vendored Sandoq extension provenance is invalid\n' >&2
        exit 2
    fi
    if [[ "$OCI_RUNNER_ENVIRONMENT" != oci-runner \
        || "$SANDOQ_EFFECTIVE_TASK_NETWORK" != public \
        || -n ${OCI_RUNNER_TASK_NETWORK:-} \
        || "$OCI_RUNNER_POOL_SIZE" != "$sandoq_capacity" \
        || "$OCI_RUNNER_POOL_MIN_SIZE" != 0 \
        || "$OCI_RUNNER_POOL_CREATE_WORKERS" != "$sandoq_create_workers" \
        || "$OCI_RUNNER_POOL_BOOTSTRAP_WORKERS" != "$sandoq_bootstrap_workers" \
        || "$OCI_RUNNER_POOL_DRAIN_WORKERS" != "$sandoq_drain_workers" \
        || "$OCI_RUNNER_POOL_RENEW_WORKERS" != "$sandoq_renew_workers" ]]; then
        printf 'Sandoq provider context does not match the approved execution contract\n' >&2
        exit 2
    fi
    mkdir -p "$pool_socket_dir"
    chmod 0700 "$pool_socket_dir"
    export OCI_RUNNER_POOL_SOCKET=${OCI_RUNNER_POOL_SOCKET:-$expected_pool_socket}
    if [[ "$OCI_RUNNER_POOL_SOCKET" != "$expected_pool_socket" ]]; then
        printf 'Sandoq pool socket must use the job-scoped node-local path\n' >&2
        exit 2
    fi
    export PRIME_RL_OUTPUT_DIR="$output_dir"
    export OCI_RUNNER_POOL_WAL="$output_dir/control/sandoq-pool.wal.jsonl"
    export OCI_RUNNER_POOL_EVENT_LOG="$output_dir/pool_events.jsonl"
    mkdir -p "$output_dir/control"
    if [[ ! -f "$OCI_RUNNER_TOKEN_FILE" || -L "$OCI_RUNNER_TOKEN_FILE" \
        || "$(stat -c '%a' "$OCI_RUNNER_TOKEN_FILE" 2>/dev/null)" != 600 ]]; then
        printf 'Sandoq token file must be regular, non-symlink, and mode 0600\n' >&2
        exit 2
    fi
    if [[ ! -f "$OCI_RUNNER_ECR_TOKEN_FILE" || -L "$OCI_RUNNER_ECR_TOKEN_FILE" \
        || "$(stat -c '%a' "$OCI_RUNNER_ECR_TOKEN_FILE" 2>/dev/null)" != 600 ]]; then
        printf 'Sandoq ECR token file must be regular, non-symlink, and mode 0600\n' >&2
        exit 2
    fi
    sandoq_site_sha256=$("$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 - "$sandoq_site" <<'PY'
import hashlib
import sys
from pathlib import Path
root = Path(sys.argv[1])
digest = hashlib.sha256()
paths = sorted((p for p in root.rglob("*") if p.is_file() and p.suffix != ".pyc" and not p.name.startswith(".")), key=lambda p: p.relative_to(root).as_posix())
for path in paths:
    digest.update(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}\n".encode())
print(digest.hexdigest())
PY
)
    if [[ "$sandoq_site_sha256" != 852f66db48c06e3928c6a5ff974c94bb21c93511342b205c2b7d1b99e73c3d6b ]]; then
        printf 'Sandoq staged dependency tree does not match the approved closure\n' >&2
        exit 2
    fi
    sandoq_client_version=$("$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 - "$sandoq_site" <<'PY'
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
    if [[ "$sandoq_client_version" != 0.4.0.2026.8.20.58304.0+hga81e4ca4d312 ]]; then
        printf 'Sandoq client version does not match the approved pin\n' >&2
        exit 2
    fi
    export PYTHONPATH="$sandoq_extension:$sandoq_site:$PYTHONPATH"
    "$x86_uv" run --no-project --offline --python "$python_bin" python3 - "$eval_config" <<'PY'
import asyncio
import contextlib
import sys
import tomllib

from sandoq_provider.ecr import _read_token_file
from sandoq_provider.gateway import close_gateway_adapters, get_gateway_adapter
from verifiers.v1.runtimes.sandoq import SandoqConfig, create_client

with open(sys.argv[1], "rb") as handle:
    runtime = tomllib.load(handle)["harness"]["runtime"]
config = SandoqConfig.model_validate(runtime)
_read_token_file(config.ecr_token_file)
client = create_client(config)
try:
    adapter = get_gateway_adapter("https://sandoq.eks-prod.cf.aws.metafb.cloud", __import__("os").environ["SANDOQ_OWNER"])
    summary = adapter.transport_summary()
    if summary.mode not in {"direct", "proxy"}:
        raise RuntimeError("unsupported Sandoq transport mode")
    response = adapter.request_json(
        "GET", "https://sandoq.eks-prod.cf.aws.metafb.cloud/healthz", timeout=15.0
    )
    if response.status_code != 200:
        raise RuntimeError("Sandoq gateway health check failed")
finally:
    close = getattr(client, "aclose", None)
    if close is not None:
        with contextlib.suppress(Exception):
            asyncio.run(close())
    with contextlib.suppress(Exception):
        close_gateway_adapters()
PY
fi

direct_metadata=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 - "$worker_manifest" "$eval_config" "$approved_task_file" \
        "$approved_task_file_sha256" "$inference_base_url" "$deployment_root" <<'PY'
import hashlib
import sys
from pathlib import Path

from direct_qwen_workers import load_workers, validate_eval_config, validate_saved_manifest

manifest_path = Path(sys.argv[1]).resolve(strict=True)
manifest = validate_saved_manifest(manifest_path)
_, live_spec_sha256, live_bundle_sha256 = load_workers(Path(sys.argv[6]))
task_sha256 = validate_eval_config(
    Path(sys.argv[2]),
    approved_task_file=Path(sys.argv[3]),
    approved_task_file_sha256=sys.argv[4],
)
expected_url = f"http://127.0.0.1:{manifest['router']['port']}/v1"
if (
    sys.argv[5].rstrip("/") != expected_url
    or task_sha256 != manifest["approved_task_allowlist_sha256"]
    or live_spec_sha256 != manifest["spec_sha256"]
    or live_bundle_sha256 != manifest["endpoint_bundle_sha256"]
):
    raise SystemExit(2)
with manifest_path.open("rb") as handle:
    manifest_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
print(
    "\t".join(
        (
            manifest_sha256,
            manifest["spec_sha256"],
            manifest["endpoint_bundle_sha256"],
        )
    )
)
PY
)
IFS=$'\t' read -r worker_manifest_sha256 direct_spec_sha256 direct_bundle_sha256 metadata_extra \
    <<< "$direct_metadata"
if [[ ! "$worker_manifest_sha256" =~ ^[0-9a-f]{64}$ \
    || ! "$direct_spec_sha256" =~ ^[0-9a-f]{64}$ \
    || ! "$direct_bundle_sha256" =~ ^[0-9a-f]{64}$ \
    || -n "$metadata_extra" || "$direct_metadata" == *$'\n'* ]]; then
    printf 'Direct Qwen validator returned invalid metadata\n' >&2
    exit 2
fi
if [[ "$sandbox_provider" == sandoq ]]; then
    diagnostic_config_sha256=${QWEN_SANDOQ_NONCERTIFYING_DIAGNOSTIC_CONFIG_SHA256:-}
    diagnostic_mode=0
    if [[ -n "$diagnostic_config_sha256" ]]; then
        diagnostic_mode=1
        if [[ "$source_continuation_mode" -eq 1 \
            || "$sandoq_stage_count" != 1 \
            || ! "$diagnostic_config_sha256" =~ ^[0-9a-f]{64}$ \
            || "$(sha256sum -- "$eval_config" | cut -d' ' -f1)" != "$diagnostic_config_sha256" ]]; then
            printf 'Non-certifying diagnostic inputs are invalid\n' >&2
            exit 2
        fi
    elif [[ "$source_continuation_mode" -eq 1 ]]; then
        if [[ "$sandoq_stage_count" != 1233 \
            || -n ${SANDOQ_RAMP_RECEIPT:-} \
            || -n ${SANDOQ_RAMP_RECEIPT_SHA256:-} \
            || -n ${SANDOQ_PREDECESSOR_CERTIFICATE:-} \
            || -n ${SANDOQ_PREDECESSOR_CERTIFICATE_SHA256:-} ]]; then
            printf 'Source-continuation launch inputs are invalid\n' >&2
            exit 2
        fi
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$workflow_dir/sandoq_source_continuation.py" validate-plan \
            --plan "$source_continuation_plan" \
            --plan-sha256 "$source_continuation_plan_sha256" \
            --task-file "$approved_task_file" \
            --task-file-sha256 "$approved_task_file_sha256" \
            --config "$eval_config" >/dev/null
    else
        ramp_receipt=${SANDOQ_RAMP_RECEIPT:?SANDOQ_RAMP_RECEIPT is required}
        ramp_receipt_sha256=${SANDOQ_RAMP_RECEIPT_SHA256:?SANDOQ_RAMP_RECEIPT_SHA256 is required}
    fi
    source_image_manifest=$(python3 - "$eval_config" <<'PY'
import sys
import tomllib
from pathlib import Path
with open(sys.argv[1], "rb") as handle:
    value = tomllib.load(handle)["taskset"]["image_manifest"]
path = Path(value)
print(path if path.is_absolute() else Path.cwd() / path)
PY
)
    canonical_dataset=$(python3 - "$eval_config" <<'PY'
import sys
import tomllib
from pathlib import Path
with open(sys.argv[1], "rb") as handle:
    path = Path(tomllib.load(handle)["taskset"]["dataset_dir"])
if not path.is_absolute():
    raise SystemExit(2)
print(path)
PY
)
    source_image_manifest_sha256=$(sha256sum -- "$source_image_manifest" | cut -d' ' -f1)
    sandoq_host_harness_sha256=$(
        sha256sum -- "$workflow_dir/terminal_bench_vmvm/sandoq_host_harness.py" | cut -d' ' -f1
    )
    if [[ ! "$sandoq_host_harness_sha256" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'Sandoq host harness digest is invalid\n' >&2
        exit 2
    fi
    if [[ "$diagnostic_mode" -eq 0 && "$source_continuation_mode" -eq 0 ]]; then
        "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 - "$sandoq_stage_count" "$approved_task_file_sha256" "$approved_task_file" \
        "$workflow_dir/configs/eval/mobius_valid_tasks_2500.txt" \
        "$canonical_dataset" \
        "$workflow_dir/configs/eval/shared_qwen38_2p4t/mobius_qwen_a95b_2500_sandoq.toml" "$eval_config" \
        "$ramp_receipt" "$ramp_receipt_sha256" \
        "${SANDOQ_PREDECESSOR_CERTIFICATE:-}" "${SANDOQ_PREDECESSOR_CERTIFICATE_SHA256:-}" \
        "$approved_task_file" "$(git rev-parse HEAD)" "$(git -C deps/verifiers rev-parse HEAD)" \
        "$(git -C deps/renderers rev-parse HEAD)" "$sandoq_provider_commit" \
        "$sandoq_provider_tree" \
        "$sandoq_host_harness_sha256" "$sandoq_client_version" "$sandoq_site_sha256" \
        "$source_image_manifest_sha256" \
        "$direct_spec_sha256" "$direct_bundle_sha256" <<'PY'
import sys
from pathlib import Path
from certify_direct_qwen_sandoq import validate_predecessor, validate_ramp_receipt

count = int(sys.argv[1])
ramp = validate_ramp_receipt(
    count, sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]),
    Path(sys.argv[6]), Path(sys.argv[7]), Path(sys.argv[8]), sys.argv[9]
)
source = dict(zip(
    (
        "prime_rl_commit", "verifiers_commit", "renderers_commit", "sandoq_provider_commit", "sandoq_provider_tree",
        "sandoq_host_harness_sha256", "sandoq_client_version", "sandoq_site_sha256", "derived_image_manifest_sha256",
        "direct_spec_sha256", "direct_endpoint_bundle_sha256",
    ),
    sys.argv[13:24],
    strict=True,
))
validate_predecessor(
    count,
    Path(sys.argv[10]) if sys.argv[10] else None,
    sys.argv[11] or None,
    expected_source=source,
    expected_ramp=ramp,
    current_task_file=Path(sys.argv[12]),
)
PY
    fi
fi
identity_preflight_dir=
if [[ "$preflight_only" -eq 1 && "$sandbox_provider" == vmvm ]]; then
    printf 'direct-qwen-vmvm-preflight-ok\n'
    exit 0
fi
if [[ "$preflight_only" -eq 1 ]]; then
    identity_preflight_dir=$(mktemp -d "${SLURM_TMPDIR:-/tmp}/direct-qwen-identity-${SLURM_JOB_ID}.XXXXXX")
    output_dir=$identity_preflight_dir
    if [[ "$sandbox_provider" == sandoq ]]; then
        export PRIME_RL_OUTPUT_DIR="$output_dir"
        export OCI_RUNNER_POOL_WAL="$output_dir/control/sandoq-pool.wal.jsonl"
        export OCI_RUNNER_POOL_EVENT_LOG="$output_dir/pool_events.jsonl"
    fi
fi

exec 9>"$output_dir/.writer.lock"
if ! flock -n 9; then
    printf 'Another evaluator owns %s\n' "$output_dir" >&2
    exit 2
fi
if [[ -z "$resume_dir" ]]; then
    for existing in inputs config.toml results.jsonl provenance.txt; do
        if [[ -e "$output_dir/$existing" ]]; then
            printf 'Refusing to overwrite existing direct Qwen artifact: %s/%s\n' "$output_dir" "$existing" >&2
            exit 2
        fi
    done
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/snapshot_eval_inputs.py" "$eval_config" "$output_dir/inputs"
    approval_args=(
        --inputs-dir "$output_dir/inputs"
        --approved-task-file "$approved_task_file"
        --approved-task-file-sha256 "$approved_task_file_sha256"
    )
else
    approval_args=(
        --inputs-dir "$output_dir/inputs"
        --approved-task-file "$approved_task_file"
        --approved-task-file-sha256 "$approved_task_file_sha256"
        --resume-config "$output_dir/config.toml"
    )
fi

approval_metadata=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/validate_task_approval.py" "${approval_args[@]}"
)
IFS=$'\t' read -r validated_approval_sha256 validated_approval_count approval_extra \
    <<< "$approval_metadata"
if [[ "$validated_approval_sha256" != "$approved_task_file_sha256" \
    || ! "$validated_approval_count" =~ ^[1-9][0-9]*$ \
    || -n "$approval_extra" || "$approval_metadata" == *$'\n'* ]]; then
    printf 'Direct Qwen task approval validator returned invalid metadata\n' >&2
    exit 2
fi

if [[ "$sandbox_provider" == sandoq ]]; then
    case "$SANDOQ_TRANSPORT_MODE" in
        auto)
            sandoq_transport_proxy_policy=official-client-auto
            ;;
        loopback)
            sandoq_transport_proxy_policy=official-client-supervised-loopback-connect-proxy
            ;;
        *)
            printf 'Sandoq transport mode is invalid\n' >&2
            exit 2
            ;;
    esac
    dataset_revision=$(python3 - "$eval_config" <<'PY'
import sys
import tomllib
with open(sys.argv[1], "rb") as handle:
    print(tomllib.load(handle).get("taskset", {}).get("dataset_revision", ""))
PY
)
    image_manifest_sha256=$(sha256sum "$output_dir/inputs/image_manifest.json" | cut -d' ' -f1)
    clean_tree_sha256=$(printf '' | sha256sum | cut -d' ' -f1)
    eval_run_identity_sha256=$(
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$workflow_dir/eval_run_identity.py" \
            --mode fresh --role qwen-direct --sandbox-provider sandoq \
            --output-dir "$output_dir" --inputs-dir "$output_dir/inputs" \
            --client-base-url "$inference_base_url" --expected-model Qwen3.8-2.4T-A95B \
            --approved-task-file-sha256 "$validated_approval_sha256" \
            --approved-task-count "$validated_approval_count" \
            --dataset-revision "$dataset_revision" --project-root "$project_dir" \
            --prime-rl-commit "$(git rev-parse HEAD)" --prime-rl-tree-sha256 "$clean_tree_sha256" \
            --verifiers-commit "$(git -C deps/verifiers rev-parse HEAD)" --verifiers-tree-sha256 "$clean_tree_sha256" \
            --renderers-commit "$(git -C deps/renderers rev-parse HEAD)" --renderers-tree-sha256 "$clean_tree_sha256" \
            --sandoq-provider-commit "$sandoq_provider_commit" \
            --sandoq-provider-tree "$sandoq_provider_tree" \
            --sandoq-client-version "$sandoq_client_version" --sandoq-site "$sandoq_site" \
            --sandoq-site-sha256 "$sandoq_site_sha256" \
            --derived-image-manifest-sha256 "$image_manifest_sha256" \
            --sandoq-environment "$OCI_RUNNER_ENVIRONMENT" --sandoq-task-network "$SANDOQ_EFFECTIVE_TASK_NETWORK" \
            --sandoq-pool-size "$OCI_RUNNER_POOL_SIZE" --sandoq-pool-min-size "$OCI_RUNNER_POOL_MIN_SIZE" \
            --sandoq-tunnel-policy host-interception-no-tunnel --sandoq-use-ecr 1 \
            --sandoq-base-url "$OCI_RUNNER_BASE_URL" --sandoq-owner "$SANDOQ_OWNER" \
            --sandoq-transport-proxy-policy "$sandoq_transport_proxy_policy" \
            --sandoq-pool-socket "$OCI_RUNNER_POOL_SOCKET" --sandoq-pool-wal "$OCI_RUNNER_POOL_WAL" \
            --sandoq-pool-event-log "$OCI_RUNNER_POOL_EVENT_LOG" \
            --sandoq-ecr-registry "$OCI_RUNNER_ECR_REGISTRY" --sandoq-ecr-region "$OCI_RUNNER_ECR_REGION" \
            --sandoq-ecr-pull-through-prefix "$OCI_RUNNER_ECR_PULL_THROUGH_PREFIX" \
            --sandoq-ecr-token-file "$OCI_RUNNER_ECR_TOKEN_FILE" \
            --sandoq-allow-dockerhub-fallback 1 \
            --sandoq-create-deadline "$OCI_RUNNER_CREATE_DEADLINE" --sandoq-pull-timeout "$OCI_RUNNER_PULL_TIMEOUT" \
            --sandoq-pull-poll-max-errors "$OCI_RUNNER_PULL_POLL_MAX_ERRORS" \
            --sandoq-gateway-retry-attempts "$OCI_RUNNER_GATEWAY_RETRY_ATTEMPTS" \
            --sandoq-gateway-retry-interval "$OCI_RUNNER_GATEWAY_RETRY_INTERVAL" \
            --sandoq-podman-ignore-chown-errors "$OCI_RUNNER_PODMAN_IGNORE_CHOWN_ERRORS" \
            --sandoq-require-resource-limits "$OCI_RUNNER_REQUIRE_RESOURCE_LIMITS" \
            --sandoq-exec-timeout-ceiling "$OCI_RUNNER_EXEC_TIMEOUT_CEILING" \
            --sandoq-task-pids-limit "$OCI_RUNNER_TASK_PIDS_LIMIT" \
            --sandoq-observability "$OCI_RUNNER_OBSERVABILITY" \
            --sandoq-pool-heartbeat-timeout "$OCI_RUNNER_POOL_HEARTBEAT_TIMEOUT" \
            --sandoq-pool-create-workers "$OCI_RUNNER_POOL_CREATE_WORKERS" \
            --sandoq-pool-bootstrap-workers "$OCI_RUNNER_POOL_BOOTSTRAP_WORKERS" \
            --sandoq-pool-bootstrap-per-image "$OCI_RUNNER_POOL_BOOTSTRAP_PER_IMAGE" \
            --sandoq-pool-drain-workers "$OCI_RUNNER_POOL_DRAIN_WORKERS" \
            --sandoq-pool-drain-timeout "$OCI_RUNNER_POOL_DRAIN_TIMEOUT" \
            --sandoq-pool-renew-workers "$OCI_RUNNER_POOL_RENEW_WORKERS" \
            --sandoq-session-reuse "$OCI_RUNNER_SESSION_REUSE" \
            --sandoq-pool-max-reuse-count "$OCI_RUNNER_POOL_MAX_REUSE_COUNT" \
            --sandoq-pool-reuse-jitter "$OCI_RUNNER_POOL_REUSE_JITTER" \
            --sandoq-image-cache-max-entries "$OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES" \
            --sandoq-secret-cache-ttl "$OCI_RUNNER_SECRET_CACHE_TTL" \
            --sandoq-lease-duration "$OCI_RUNNER_LEASE_DURATION" \
            --sandoq-pool-renew-interval "$OCI_RUNNER_POOL_RENEW_INTERVAL" \
            --direct-worker-manifest "$worker_manifest" \
            --direct-worker-manifest-sha256 "$worker_manifest_sha256" \
            --direct-spec-sha256 "$direct_spec_sha256" \
            --direct-endpoint-bundle-sha256 "$direct_bundle_sha256" \
            --direct-router-policy "${DIRECT_QWEN_ROUTER_POLICY:?}" \
            --direct-request-id-headers "${DIRECT_QWEN_REQUEST_ID_HEADERS:?}" \
            --direct-provider-concurrency "${DIRECT_QWEN_PROVIDER_CONCURRENCY:?}" \
            --invocation-host "$(hostname)" --slurm-job-id "$SLURM_JOB_ID"
    )
    [[ "$eval_run_identity_sha256" =~ ^[0-9a-f]{64}$ ]] || exit 2
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 - "$output_dir/eval_run_identity.json" <<'PY'
import sys
from pathlib import Path
from eval_run_identity import load_eval_run_identity

envelope = load_eval_run_identity(Path(sys.argv[1]), verify_references=True)
if envelope["identity"].get("role") != "qwen-direct":
    raise SystemExit(2)
PY
    if [[ "$preflight_only" -eq 1 ]]; then
        rm -rf -- "$identity_preflight_dir"
        printf 'direct-qwen-%s-preflight-ok\n' "$sandbox_provider"
        exit 0
    fi
fi

if [[ -n "$resume_dir" ]]; then
    {
        printf 'resume_slurm_job_id=%s\n' "$SLURM_JOB_ID"
        printf 'resume_prime_rl=%s\n' "$(git rev-parse HEAD)"
        printf 'resume_verifiers=%s\n' "$(git -C deps/verifiers rev-parse HEAD)"
        printf 'resume_renderers=%s\n' "$(git -C deps/renderers rev-parse HEAD)"
        printf 'resume_approval_task_file_sha256=%s\n' "$validated_approval_sha256"
        printf 'resume_approval_task_count=%s\n' "$validated_approval_count"
        printf 'resume_direct_worker_manifest_sha256=%s\n' "$worker_manifest_sha256"
    } >> "$output_dir/provenance.txt"
    args=(--resume "$resume_dir")
elif [[ "$sandbox_provider" == vmvm ]]; then
    {
        printf 'sandbox_provider=%s\n' "$sandbox_provider"
        printf 'prime_rl=%s\n' "$(git rev-parse HEAD)"
        printf 'verifiers=%s\n' "$(git -C deps/verifiers rev-parse HEAD)"
        printf 'renderers=%s\n' "$(git -C deps/renderers rev-parse HEAD)"
        printf 'inference_base_url=%s\n' "$inference_base_url"
        printf 'inference_deployment_id=\n'
        printf 'slurm_job_id=%s\n' "$SLURM_JOB_ID"
        printf 'approval_task_file_sha256=%s\n' "$validated_approval_sha256"
        printf 'approval_task_count=%s\n' "$validated_approval_count"
        printf 'direct_worker_manifest_sha256=%s\n' "$worker_manifest_sha256"
        printf 'direct_spec_sha256=%s\n' "$direct_spec_sha256"
        printf 'direct_endpoint_bundle_sha256=%s\n' "$direct_bundle_sha256"
    } > "$output_dir/provenance.txt"
    args=(
        @ "$output_dir/inputs/source_config.toml"
        --client.base-url "$inference_base_url"
        --output-dir "$output_dir"
        --taskset.task-file "$output_dir/inputs/task_file.txt"
        --taskset.task-file-sha256 "$approved_task_file_sha256"
    )
    if [[ -f "$output_dir/inputs/image_manifest.json" ]]; then
        args+=(--taskset.image-manifest "$output_dir/inputs/image_manifest.json")
    fi
else
    args=(--resume "$output_dir")
fi

if [[ "$sandbox_provider" != sandoq ]]; then
    unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
fi
export OPENAI_API_KEY=EMPTY
if [[ "$sandbox_provider" == vmvm ]]; then
    export VACLI_LEASE_RETRIES=${VACLI_LEASE_RETRIES:-20}
    export VACLI_MAX_CONCURRENT_LEASES=${VACLI_MAX_CONCURRENT_LEASES:-8}
    export VACLI_MAX_PULL_RETRIES=${VACLI_MAX_PULL_RETRIES:-20}
    export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=${VACLI_IMAGE_PULL_TIMEOUT_SECONDS:-3600}
    export VACLI_CONTAINER_PRIVILEGED=${VACLI_CONTAINER_PRIVILEGED:-1}
    export VACLI_BIN=${VACLI_BIN:-/public/fbpkgs/x86_64/vacli/stable/vacli}
fi

set +e
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 -c 'from verifiers.v1.cli.eval.main import main; main()' "${args[@]}"
eval_status=$?
set -e
if [[ "$sandbox_provider" == sandoq ]]; then
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/sandoq_pool_cleanup.py" \
        --output-dir "$output_dir" --base-url "$OCI_RUNNER_BASE_URL" --owner "$SANDOQ_OWNER" \
        --concurrency "$OCI_RUNNER_POOL_DRAIN_WORKERS"
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/sanitize_sandoq_cleanup_audit.py" \
        --raw-audit "$output_dir/pool_cleanup_audit.json" \
        --event-log "$OCI_RUNNER_POOL_EVENT_LOG" --wal "$OCI_RUNNER_POOL_WAL" \
        --drain-marker "${OCI_RUNNER_POOL_SOCKET%.sock}.drained.json" \
        --output "$output_dir/sandoq_cleanup_audit.json"
fi
exit "$eval_status"
