#!/bin/bash
#SBATCH --job-name=tb-eval
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/eval_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/eval_%j.log

set -euo pipefail
umask 077

dry_run=0
if (( $# == 1 )) && [[ $1 == --dry-run ]]; then
    dry_run=1
elif (( $# != 0 )); then
    printf 'The eval launcher accepts no overrides except a single --dry-run\n' >&2
    exit 2
fi

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_ram_prime_f7313db4}
sandoq_extension="$project_dir/extensions/sandoq"
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
eval_config=${EVAL_CONFIG:-$workflow_dir/configs/eval/tb4_kimi_k3_max_miniswe.toml}
eval_config_sha256=${EVAL_CONFIG_SHA256:-}
output_dir=${OUTPUT_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/run_${SLURM_JOB_ID}}
resume_dir=${RESUME_DIR:-}
inference_base_url=${INFERENCE_BASE_URL:-}
inference_deployment_id=${INFERENCE_DEPLOYMENT_ID:-}
inference_job_id=${INFERENCE_JOB_ID:-}
inference_proxy_info=${INFERENCE_PROXY_INFO:-}
inference_proxy_info_sha256=${INFERENCE_PROXY_INFO_SHA256:-}
eval_model=${EVAL_MODEL:-}
inference_proxy_url=${INFERENCE_PROXY_URL:-}
eval_run_role=${EVAL_RUN_ROLE:-}
eval_deployment_id=${EVAL_DEPLOYMENT_ID:-}
eval_expected_model=${EVAL_EXPECTED_MODEL:-}
eval_expected_prime_rl_revision=${EVAL_EXPECTED_PRIME_RL_REVISION:-}
deployment_spec=${INFERENCE_DEPLOYMENT_SPEC:-}
deployment_spec_sha256=${INFERENCE_DEPLOYMENT_SPEC_SHA256:-}
readiness_checkpoint=${INFERENCE_READINESS_CHECKPOINT:-}
readiness_checkpoint_sha256=${INFERENCE_READINESS_CHECKPOINT_SHA256:-}
smoke_checkpoint=${INFERENCE_SMOKE_CHECKPOINT:-}
smoke_checkpoint_sha256=${INFERENCE_SMOKE_CHECKPOINT_SHA256:-}
promotion_certificate=${EVAL_PROMOTION_CERTIFICATE:-}
promotion_certificate_sha256=${EVAL_PROMOTION_CERTIFICATE_SHA256:-}
eval_dataset_revision=${EVAL_DATASET_REVISION:-}
eval_dataset_archive=${EVAL_DATASET_ARCHIVE:-}
eval_dataset_archive_sha256=${EVAL_DATASET_ARCHIVE_SHA256:-}
eval_dataset_content_sha256=${EVAL_DATASET_CONTENT_SHA256:-}
unset PYTHONPATH PYTHONHOME
direct_qwen_manifest_sha256=${DIRECT_QWEN_MANIFEST_SHA256:-}
direct_qwen_router_policy=${DIRECT_QWEN_ROUTER_POLICY:-}
direct_qwen_request_id_headers=${DIRECT_QWEN_REQUEST_ID_HEADERS:-}
direct_qwen_provider_concurrency=${DIRECT_QWEN_PROVIDER_CONCURRENCY:-}
direct_qwen_generation_transition_sha256=${DIRECT_QWEN_GENERATION_TRANSITION_SHA256:-}
direct_qwen_capacity_smoke_sha256=${DIRECT_QWEN_CAPACITY_SMOKE_SHA256:-}

if [[ "$(uname -m)" != x86_64 || ! -d "$x86_site/pydantic" ]]; then
    printf 'Missing x86_64 Python runtime/dependencies\n' >&2
    exit 2
fi
if [[ ! -x "$x86_uv" ]]; then
    printf 'Missing x86_64 uv binary: %s\n' "$x86_uv" >&2
    exit 2
fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site"

if [[ -n "$eval_config_sha256" ]]; then
    if [[ ! "$eval_config_sha256" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'EVAL_CONFIG_SHA256 must be 64 lowercase hexadecimal characters\n' >&2
        exit 2
    fi
    if ! observed_eval_config_sha256=$(sha256sum -- "$eval_config" 2>/dev/null) \
        || [[ "${observed_eval_config_sha256%% *}" != "$eval_config_sha256" ]]; then
        printf 'EVAL_CONFIG does not match EVAL_CONFIG_SHA256\n' >&2
        exit 2
    fi
fi

if [[ "$dry_run" -eq 1 ]]; then
    if [[ -n "$resume_dir" ]]; then
        printf 'RESUME_DIR cannot be combined with --dry-run\n' >&2
        exit 2
    fi
    cd "$project_dir"
    args=(
        @ "$eval_config"
        --output-dir "$output_dir"
        --dry-run
    )
    if [[ -n "$inference_base_url" ]]; then
        args+=(--client.base-url "$inference_base_url")
    fi
    if [[ -n "$eval_model" ]]; then
        args+=(--model "$eval_model")
    fi
    exec "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 -c 'from verifiers.v1.cli.eval.main import main; main()' "${args[@]}"
fi

if [[ -z "$eval_run_role" \
    && -n ${DIRECT_QWEN_APPROVED_TASK_FILE:-} \
    && -n ${DIRECT_QWEN_APPROVED_TASK_FILE_SHA256:-} \
    && -z ${EVAL_APPROVED_TASK_FILE:-} \
    && -z ${EVAL_APPROVED_TASK_FILE_SHA256:-} ]]; then
    exec bash "$workflow_dir/run_direct_qwen_eval_driver.sh"
fi

if [[ -n "$resume_dir" ]]; then
    printf 'Guarded Kimi evaluations cannot resume; use a fresh OUTPUT_DIR\n' >&2
    exit 2
fi

eval_approved_task_file=${EVAL_APPROVED_TASK_FILE:-}
eval_approved_task_file_sha256=${EVAL_APPROVED_TASK_FILE_SHA256:-}
direct_approved_task_file=${DIRECT_QWEN_APPROVED_TASK_FILE:-}
direct_approved_task_file_sha256=${DIRECT_QWEN_APPROVED_TASK_FILE_SHA256:-}
if [[ ( -n "$eval_approved_task_file" && -z "$eval_approved_task_file_sha256" ) \
    || ( -z "$eval_approved_task_file" && -n "$eval_approved_task_file_sha256" ) ]]; then
    printf 'The EVAL task approval pair is incomplete\n' >&2
    exit 2
fi
if [[ ( -n "$direct_approved_task_file" && -z "$direct_approved_task_file_sha256" ) \
    || ( -z "$direct_approved_task_file" && -n "$direct_approved_task_file_sha256" ) ]]; then
    printf 'The DIRECT_QWEN task approval pair is incomplete\n' >&2
    exit 2
fi
if [[ -n "$eval_approved_task_file" && -n "$direct_approved_task_file" ]]; then
    if [[ "$eval_approved_task_file" != "$direct_approved_task_file" \
        || "$eval_approved_task_file_sha256" != "$direct_approved_task_file_sha256" ]]; then
        printf 'The task approval environment pairs conflict\n' >&2
        exit 2
    fi
    approved_task_file=$eval_approved_task_file
    approved_task_file_sha256=$eval_approved_task_file_sha256
elif [[ -n "$eval_approved_task_file" ]]; then
    approved_task_file=$eval_approved_task_file
    approved_task_file_sha256=$eval_approved_task_file_sha256
elif [[ -n "$direct_approved_task_file" ]]; then
    approved_task_file=$direct_approved_task_file
    approved_task_file_sha256=$direct_approved_task_file_sha256
else
    printf 'An external approved task file and lowercase SHA-256 are required\n' >&2
    exit 2
fi

case "$eval_run_role" in
    smoke|tb4|mobius) ;;
    *)
        printf 'EVAL_RUN_ROLE must be smoke, tb4, or mobius\n' >&2
        exit 2
        ;;
esac
if [[ -z "$eval_deployment_id" || -z "$eval_expected_model" ]]; then
    printf 'EVAL_DEPLOYMENT_ID and EVAL_EXPECTED_MODEL are required metadata\n' >&2
    exit 2
fi
if [[ "$eval_expected_model" == Kimi-K3 \
    && ! "$eval_expected_prime_rl_revision" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'Kimi evaluations require EVAL_EXPECTED_PRIME_RL_REVISION as 40 lowercase hexadecimal characters\n' >&2
    exit 2
fi
if [[ -n "$inference_deployment_id" ]]; then
    if [[ ! "$inference_deployment_id" =~ ^[A-Za-z0-9._:-]+$ ]]; then
        printf 'Invalid INFERENCE_DEPLOYMENT_ID: %s\n' "$inference_deployment_id" >&2
        exit 2
    fi
    if [[ "$inference_deployment_id" != "$eval_deployment_id" ]]; then
        printf 'INFERENCE_DEPLOYMENT_ID routing must match EVAL_DEPLOYMENT_ID metadata\n' >&2
        exit 2
    fi
fi
if [[ -z "$deployment_spec" || -z "$deployment_spec_sha256" \
    || -z "$readiness_checkpoint" || -z "$readiness_checkpoint_sha256" ]]; then
    printf 'Deployment spec and readiness checkpoint paths with SHA-256 values are required\n' >&2
    exit 2
fi
if [[ -z "$inference_proxy_info" || -z "$inference_proxy_info_sha256" ]]; then
    printf 'INFERENCE_PROXY_INFO and INFERENCE_PROXY_INFO_SHA256 are required\n' >&2
    exit 2
fi
if [[ ! "$inference_proxy_info_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'INFERENCE_PROXY_INFO_SHA256 must be 64 lowercase hexadecimal characters\n' >&2
    exit 2
fi
if [[ -n "$inference_base_url" || -n "$inference_job_id" || -n "$inference_deployment_id" ]]; then
    printf 'Evaluation requires only the readiness-bound deployment-local INFERENCE_PROXY_INFO endpoint\n' >&2
    exit 2
fi
if [[ "$eval_run_role" == smoke ]]; then
    if [[ -n "$smoke_checkpoint" || -n "$smoke_checkpoint_sha256" ]]; then
        printf 'Smoke-role evaluation cannot depend on a prior smoke checkpoint\n' >&2
        exit 2
    fi
elif [[ -z "$smoke_checkpoint" || -z "$smoke_checkpoint_sha256" ]]; then
    printf 'TB4 and Mobius evaluations require a smoke checkpoint and SHA-256\n' >&2
    exit 2
fi
if [[ "$eval_run_role" == mobius ]]; then
    if [[ -z "$promotion_certificate" || -z "$promotion_certificate_sha256" ]]; then
        printf 'Mobius evaluation requires EVAL_PROMOTION_CERTIFICATE and its SHA-256\n' >&2
        exit 2
    fi
    if [[ "$eval_expected_model" != Kimi-K3 || -n "$eval_model" ]]; then
        printf 'Mobius evaluation requires the certificate-bound Kimi-K3 model without EVAL_MODEL override\n' >&2
        exit 2
    fi
elif [[ -n "$promotion_certificate" || -n "$promotion_certificate_sha256" ]]; then
    printf 'Only Mobius evaluation may bind an EVAL promotion certificate\n' >&2
    exit 2
fi
if [[ ( -n "$eval_dataset_archive" && -z "$eval_dataset_archive_sha256" ) \
    || ( -n "$eval_dataset_archive" && -z "$eval_dataset_content_sha256" ) \
    || ( -z "$eval_dataset_archive" && -n "$eval_dataset_archive_sha256" ) \
    || ( -z "$eval_dataset_archive" && -n "$eval_dataset_content_sha256" ) ]]; then
    printf 'EVAL_DATASET_ARCHIVE, its SHA-256, and EVAL_DATASET_CONTENT_SHA256 are one required tuple\n' >&2
    exit 2
fi
if [[ ( -n "$eval_dataset_revision" && -n "$eval_dataset_archive" ) \
    || ( -z "$eval_dataset_revision" && -z "$eval_dataset_archive" ) ]]; then
    printf 'Supply exactly one dataset authority: EVAL_DATASET_REVISION or archive tuple\n' >&2
    exit 2
fi
if [[ -n "$eval_expected_prime_rl_revision" ]]; then
    prime_rl_commit=$(git -C "$project_dir" rev-parse --verify HEAD)
    if [[ ! "$eval_expected_prime_rl_revision" =~ ^[0-9a-f]{40}$ \
        || "$prime_rl_commit" != "$eval_expected_prime_rl_revision" ]]; then
        printf 'PROJECT_DIR revision does not match EVAL_EXPECTED_PRIME_RL_REVISION\n' >&2
        exit 2
    fi
fi
if [[ -n "$direct_qwen_generation_transition_sha256" ]]; then
    if [[ "$direct_qwen_router_metadata" -ne 1 \
        || ! "$direct_qwen_generation_transition_sha256" =~ ^[0-9a-f]{64}$ \
        || ! "$direct_qwen_capacity_smoke_sha256" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'Direct Qwen serving-generation provenance is invalid\n' >&2
        exit 2
    fi
elif [[ -n "$direct_qwen_capacity_smoke_sha256" ]]; then
    printf 'Direct Qwen capacity-smoke provenance has no serving generation\n' >&2
    exit 2
fi

if ! sandbox_provider=$(python3 - "$eval_config" <<'PY'
import sys
import tomllib
with open(sys.argv[1], "rb") as handle:
    print(tomllib.load(handle).get("harness", {}).get("runtime", {}).get("type", ""))
PY
); then
    printf 'Could not read sandbox provider from EVAL_CONFIG\n' >&2
    exit 2
fi
if [[ "$sandbox_provider" != vmvm && "$sandbox_provider" != sandoq ]]; then
    printf 'EVAL_CONFIG must select an explicit vmvm or sandoq runtime\n' >&2
    exit 2
fi
if [[ "$sandbox_provider" == sandoq ]]; then
    sandoq_approved_provider_commit=${SANDOQ_APPROVED_PROVIDER_COMMIT:-4890302104d76220cef791c86d2009168597d35f}
    sandoq_approved_provider_tree=${SANDOQ_APPROVED_PROVIDER_TREE:-33f092a3982916660e12f472588e6ce34a906fc2}
    sandoq_approved_provider_source_sha256=${SANDOQ_APPROVED_PROVIDER_SOURCE_SHA256:-ca983f92d79b6079b0813f5670823449802028e55fbc23512d2aec69c1e3be86}
    sandoq_approved_client_version=${SANDOQ_APPROVED_CLIENT_VERSION:-0.4.0.2026.8.20.58304.0+hga81e4ca4d312}
    sandoq_approved_site_sha256=${SANDOQ_APPROVED_SITE_SHA256:-852f66db48c06e3928c6a5ff974c94bb21c93511342b205c2b7d1b99e73c3d6b}
    if [[ ! "$sandoq_approved_provider_commit" =~ ^[0-9a-f]{40}$ \
        || ! "$sandoq_approved_provider_tree" =~ ^[0-9a-f]{40}$ \
        || ! "$sandoq_approved_provider_source_sha256" =~ ^[0-9a-f]{64}$ \
        || ! "$sandoq_approved_site_sha256" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'Sandoq runtime approval is invalid\n' >&2
        exit 2
    fi
    if [[ ! -d "$sandoq_site/sandoq_client" ]]; then
        printf 'Missing pinned x86_64 Sandoq client site\n' >&2
        exit 2
    fi
    mapfile -t sandoq_context_values < <(python3 - "$eval_config" <<'PY'
import sys
import tomllib
with open(sys.argv[1], "rb") as handle:
    config = tomllib.load(handle)
capacity = min(config["num_tasks"], config["max_concurrent"])
ecr_token_file = config["harness"]["runtime"].get("ecr_token_file", "")
if capacity < 1 or not isinstance(ecr_token_file, str) or not ecr_token_file.startswith("/"):
    raise SystemExit(2)
print(capacity)
print(ecr_token_file)
PY
    )
    if [[ ${#sandoq_context_values[@]} -ne 2 ]]; then
        printf 'Sandoq provider context inputs are invalid\n' >&2
        exit 2
    fi
    sandoq_capacity=${sandoq_context_values[0]}
    sandoq_ecr_token_file=${sandoq_context_values[1]}
    sandoq_ecr_token_metadata=${OCI_RUNNER_ECR_TOKEN_METADATA_PATH:-${sandoq_ecr_token_file}.metadata.json}
    sandoq_provider_profile=${SANDOQ_PROVIDER_CONTEXT_PROFILE:-$workflow_dir/configs/provider_context/use2/qwen_sandoq.json}
    sandoq_provider_profile_sha256=${SANDOQ_PROVIDER_CONTEXT_PROFILE_SHA256:-965511eb9578aa303d287491a7414e145241d6dbbf61469d13abbe801980a95a}
    sandoq_lease_create_cap=$(( sandoq_capacity < 4 ? sandoq_capacity : 4 ))
    provider_context="$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py"
    if [[ ${SANDOQ_PROVIDER_CONTEXT_ACTIVE:-} == 1 ]]; then
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$provider_context" verify \
            --receipt "${SANDOQ_PROVIDER_CONTEXT_RECEIPT:?}" >/dev/null
    else
        if [[ -n ${SANDOQ_PROVIDER_CONTEXT_ACTIVE:-} \
            || -n ${SANDOQ_PROVIDER_CONTEXT_RECEIPT:-} ]]; then
            printf 'Partial Sandoq provider context is forbidden\n' >&2
            exit 2
        fi
        exec "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$provider_context" supervise \
            --profile "$sandoq_provider_profile" \
            --profile-sha256 "$sandoq_provider_profile_sha256" \
            --concurrency "$sandoq_capacity" \
            --lease-create-cap "$sandoq_lease_create_cap" \
            --startup-timeout-seconds 3600 \
            --ecr-token-file "$sandoq_ecr_token_file" \
            --ecr-token-metadata "$sandoq_ecr_token_metadata" \
            --project-root "$project_dir" --sandoq-site "$sandoq_site" \
            -- bash "$workflow_dir/run_eval.sbatch" "$@"
    fi
fi

if [[ "$sandbox_provider" == vmvm ]]; then
    export VACLI_LEASE_RETRIES=${VACLI_LEASE_RETRIES:-20}
    export VACLI_MAX_CONCURRENT_LEASES=${VACLI_MAX_CONCURRENT_LEASES:-32}
    export VACLI_MAX_PULL_RETRIES=${VACLI_MAX_PULL_RETRIES:-20}
    export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=${VACLI_IMAGE_PULL_TIMEOUT_SECONDS:-3600}
    export VACLI_CONTAINER_PRIVILEGED=${VACLI_CONTAINER_PRIVILEGED:-1}
    export VACLI_BIN=${VACLI_BIN:-/public/fbpkgs/x86_64/vacli/stable/vacli}
else
    if [[ -n ${SANDOQ_TUNNEL_HTTPS_PROXY+x} ]]; then
        printf 'SANDOQ_TUNNEL_HTTPS_PROXY overrides are forbidden for guarded Sandoq runs\n' >&2
        exit 2
    fi
    unset OCI_RUNNER_DOCKERHUB_USERNAME OCI_RUNNER_DOCKERHUB_TOKEN_FILE OCI_RUNNER_REQUIRE_DOCKERHUB_AUTH
    unset OCI_RUNNER_ECR_AUXILIARY_REGISTRIES OCI_RUNNER_ECR_CLIENT_CERT_PATH OCI_RUNNER_ECR_UCLOUD
    pool_socket_dir="${SLURM_TMPDIR:-/tmp}/oci-runner-pool-${UID}"
    mkdir -p "$pool_socket_dir"
    chmod 0700 "$pool_socket_dir"
    export OCI_RUNNER_POOL_SOCKET="$pool_socket_dir/${SLURM_JOB_ID:?}.sock"
    export PRIME_RL_OUTPUT_DIR="$output_dir"
    export OCI_RUNNER_POOL_WAL="$output_dir/control/sandoq-pool.wal.jsonl"
    export OCI_RUNNER_POOL_EVENT_LOG="$output_dir/pool_events.jsonl"
    if [[ "$OCI_RUNNER_ENVIRONMENT" != oci-runner \
        || "$SANDOQ_EFFECTIVE_TASK_NETWORK" != public \
        || -n ${OCI_RUNNER_TASK_NETWORK:-} \
        || "$OCI_RUNNER_POOL_SIZE" != "$sandoq_capacity" \
        || "$OCI_RUNNER_POOL_MIN_SIZE" != 0 \
        || "$OCI_RUNNER_POOL_CREATE_WORKERS" != "$sandoq_lease_create_cap" \
        || "$OCI_RUNNER_SESSION_REUSE" != 1 \
        || "$OCI_RUNNER_POOL_MAX_REUSE_COUNT" != 1 \
        || "$OCI_RUNNER_POOL_REUSE_JITTER" != 0 \
        || "$OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES" != 0 \
        || "$OCI_RUNNER_PODMAN_FUSE_OVERLAYFS" != 1 \
        || "$OCI_RUNNER_PULL_TIMEOUT" != 3600s \
        || "$OCI_RUNNER_PULL_POLL_MAX_ERRORS" != 20 ]]; then
        printf 'Sandoq provider context does not match the approved execution contract\n' >&2
        exit 2
    fi
    if [[ ! -f "$OCI_RUNNER_TOKEN_FILE" || -L "$OCI_RUNNER_TOKEN_FILE" \
        || "$(stat -c '%a' "$OCI_RUNNER_TOKEN_FILE" 2>/dev/null)" != 600 ]]; then
        printf 'Sandoq token file must be a regular non-symlink file with mode 0600\n' >&2
        exit 2
    fi
    if [[ ! -f "$OCI_RUNNER_ECR_TOKEN_FILE" || -L "$OCI_RUNNER_ECR_TOKEN_FILE" \
        || "$(stat -c '%a' "$OCI_RUNNER_ECR_TOKEN_FILE" 2>/dev/null)" != 600 ]]; then
        printf 'Sandoq ECR token file must be a regular non-symlink file with mode 0600\n' >&2
        exit 2
    fi
fi

cd "$project_dir"
prime_rl_status=$(git status --porcelain=v1 --untracked-files=all)
verifiers_status=$(git -C deps/verifiers status --porcelain=v1 --untracked-files=all)
renderers_status=$(git -C deps/renderers status --porcelain=v1 --untracked-files=all)
if [[ -n "$prime_rl_status" || -n "$verifiers_status" || -n "$renderers_status" \
    ]]; then
    printf 'Prime-RL, Verifiers, and Renderers worktrees must all be clean\n' >&2
    exit 2
fi
prime_rl_commit=$(git rev-parse --verify HEAD)
verifiers_commit=$(git -C deps/verifiers rev-parse --verify HEAD)
renderers_commit=$(git -C deps/renderers rev-parse --verify HEAD)
prime_rl_tree_sha256=$(printf '%s' "$prime_rl_status" | sha256sum | cut -d' ' -f1)
verifiers_tree_sha256=$(printf '%s' "$verifiers_status" | sha256sum | cut -d' ' -f1)
renderers_tree_sha256=$(printf '%s' "$renderers_status" | sha256sum | cut -d' ' -f1)
vmvm_tb_v2_sha256=$(sha256sum environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/*.py \
    | sha256sum | cut -d' ' -f1)
sandoq_provider_commit=
sandoq_provider_tree=
sandoq_client_version=
sandoq_site_sha256=
derived_image_manifest_sha256=
if [[ "$sandbox_provider" == sandoq ]]; then
    sandoq_provider_commit=4890302104d76220cef791c86d2009168597d35f
    sandoq_provider_tree=33f092a3982916660e12f472588e6ce34a906fc2
    sandoq_provider_source_sha256=ca983f92d79b6079b0813f5670823449802028e55fbc23512d2aec69c1e3be86
    if [[ "$verifiers_commit" != 80e58e7e2b194e9c1b8dc0990c00b7a839127eea ]]; then
        printf 'Verifiers revision is not the approved host-harness topology source\n' >&2
        exit 2
    fi
    if [[ "$sandoq_provider_commit" != "$sandoq_approved_provider_commit" \
        || "$sandoq_provider_tree" != "$sandoq_approved_provider_tree" \
        || "$sandoq_provider_source_sha256" != "$sandoq_approved_provider_source_sha256" ]]; then
        printf 'Sandoq provider revision is not the approved cutover source\n' >&2
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
    if [[ "$sandoq_client_version" != "$sandoq_approved_client_version" ]]; then
        printf 'Sandoq client version does not match the approved pin\n' >&2
        exit 2
    fi
    sandoq_site_sha256=$("$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 - "$sandoq_site" <<'PY'
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
    if [[ "$sandoq_site_sha256" != "$sandoq_approved_site_sha256" ]]; then
        printf 'Sandoq staged dependency tree does not match the approved closure\n' >&2
        exit 2
    fi
    derived_image_manifest_sha256=$(python3 - "$eval_config" <<'PY'
import sys
import tomllib
with open(sys.argv[1], "rb") as handle:
    print(tomllib.load(handle).get("taskset", {}).get("image_manifest_sha256", ""))
PY
)
    if [[ ! "$derived_image_manifest_sha256" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'Sandoq config requires a pinned derived image manifest SHA-256\n' >&2
        exit 2
    fi
    if [[ ! -f "$sandoq_extension/UPSTREAM.md" ]] \
        || ! grep -Fq "$sandoq_provider_commit" "$sandoq_extension/UPSTREAM.md" \
        || ! grep -Fq '10b5bd9bbc76eba1b8253637e1869d6b63b7fc42' "$sandoq_extension/UPSTREAM.md"; then
        printf 'Vendored Sandoq extension provenance is invalid\n' >&2
        exit 2
    fi
    export PYTHONPATH="$sandoq_extension:$sandoq_site:$PYTHONPATH"
    "$x86_uv" run --no-project --offline --python "$python_bin" python3 - "$eval_config" <<'PY'
import asyncio
import contextlib
import os
import sys
import tomllib

from sandoq_provider.ecr import _read_token_file
from sandoq_provider.gateway import close_gateway_adapters, get_gateway_adapter
from verifiers.v1.runtimes.sandoq import SandoqConfig, create_client

with open(sys.argv[1], "rb") as handle:
    config = SandoqConfig.model_validate(tomllib.load(handle)["harness"]["runtime"])
_read_token_file(config.ecr_token_file)
client = create_client(config)
try:
    adapter = get_gateway_adapter("https://sandoq.eks-prod.cf.aws.metafb.cloud", os.environ["SANDOQ_OWNER"])
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

if [[ "$eval_run_role" == mobius ]]; then
    if [[ "$sandbox_provider" == vmvm ]]; then
        requested_sandbox_concurrency=$VACLI_MAX_CONCURRENT_LEASES
    else
        requested_sandbox_concurrency=$OCI_RUNNER_POOL_SIZE
    fi
    if ! effective_lease_start_concurrency=$(
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 - "$eval_config" "$requested_sandbox_concurrency" <<'PY'
import sys
import tomllib

try:
    with open(sys.argv[1], "rb") as handle:
        rollout_concurrency = tomllib.load(handle).get("max_concurrent")
    requested = int(sys.argv[2])
except (OSError, ValueError, tomllib.TOMLDecodeError):
    raise SystemExit(2)
if (
    not isinstance(rollout_concurrency, int)
    or isinstance(rollout_concurrency, bool)
    or rollout_concurrency < 1
    or requested < 1
    or str(requested) != sys.argv[2]
):
    raise SystemExit(2)
print(min(rollout_concurrency, requested))
PY
    ); then
        printf 'Invalid production max_concurrent or sandbox concurrency limit\n' >&2
        exit 2
    fi
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/mobius_launch_certificate.py" verify \
        "$promotion_certificate" \
        --certificate-sha256 "$promotion_certificate_sha256" \
        --production-config "$eval_config" \
        --approved-manifest "$approved_task_file" \
        --approved-manifest-sha256 "$approved_task_file_sha256" \
        --deployment-id "$eval_deployment_id" \
        --deployment-spec "$deployment_spec" \
        --deployment-spec-sha256 "$deployment_spec_sha256" \
        --readiness-checkpoint "$readiness_checkpoint" \
        --readiness-checkpoint-sha256 "$readiness_checkpoint_sha256" \
        --capacity-smoke-checkpoint "$smoke_checkpoint" \
        --capacity-smoke-checkpoint-sha256 "$smoke_checkpoint_sha256" \
        --deployment-proxy-info "$inference_proxy_info" \
        --deployment-proxy-info-sha256 "$inference_proxy_info_sha256" \
        --requested-lease-start-concurrency "$effective_lease_start_concurrency" \
        >/dev/null
fi

if ! proxy_metadata=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 - "$inference_proxy_info" "$inference_proxy_info_sha256" \
        "$eval_deployment_id" "$eval_expected_model" "$deployment_spec" <<'PY'
import base64
import sys
from pathlib import Path

from deployment_endpoint import load_deployment_endpoint

try:
    endpoint = load_deployment_endpoint(
        Path(sys.argv[1]),
        expected_proxy_info_sha256=sys.argv[2],
        deployment_id=sys.argv[3],
        expected_model=sys.argv[4],
        deployment_spec=Path(sys.argv[5]),
    )
except Exception:
    print("deployment_endpoint_invalid", file=sys.stderr)
    raise SystemExit(2)
print(
    base64.b64encode(endpoint.client_base_url.encode()).decode(),
    base64.b64encode(endpoint.api_key.encode()).decode(),
    sep="\t",
)
PY
); then
    printf 'Readiness-bound deployment endpoint validation failed\n' >&2
    exit 2
fi
IFS=$'\t' read -r proxy_url_base64 proxy_api_key_base64 proxy_metadata_extra \
    <<< "$proxy_metadata"
if [[ -z "$proxy_url_base64" || -z "$proxy_api_key_base64" \
    || -n "$proxy_metadata_extra" || "$proxy_metadata" == *$'\n'* ]]; then
    printf 'Deployment endpoint loader returned invalid metadata\n' >&2
    exit 2
fi
if ! inference_base_url=$(printf '%s' "$proxy_url_base64" | base64 --decode) \
    || ! proxy_api_key=$(printf '%s' "$proxy_api_key_base64" | base64 --decode) \
    || [[ -z "$inference_base_url" || -z "$proxy_api_key" ]]; then
    printf 'Deployment endpoint loader returned invalid credentials\n' >&2
    exit 2
fi
export OPENAI_API_KEY=$proxy_api_key

if [[ -n "$resume_dir" ]]; then
    output_dir=$resume_dir
fi

mkdir -p "$output_dir" /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs
exec 9>"$output_dir/.writer.lock"
if ! flock -n 9; then
    printf 'Another evaluator owns %s\n' "$output_dir" >&2
    exit 2
fi
if [[ -z "$resume_dir" ]]; then
    for existing in inputs config.toml results.jsonl provenance.txt eval_run_identity.json eval_invocations.jsonl; do
        if [[ -e "$output_dir/$existing" ]]; then
            printf 'Refusing to overwrite existing eval artifact: %s/%s\n' "$output_dir" "$existing" >&2
            exit 2
        fi
    done
    if [[ "$sandbox_provider" == sandoq ]]; then
        for stale in pool_events.jsonl control/sandoq-pool.wal.jsonl pool_cleanup_audit.json \
            sandoq_cleanup_audit.json direct_qwen_sandoq_certificate.json; do
            if [[ -e "$output_dir/$stale" || -L "$output_dir/$stale" ]]; then
                printf 'Refusing stale Sandoq lifecycle evidence: %s/%s\n' "$output_dir" "$stale" >&2
                exit 2
            fi
        done
        for stale in "$OCI_RUNNER_POOL_SOCKET" "$OCI_RUNNER_POOL_SOCKET.owner.json" \
            "${OCI_RUNNER_POOL_SOCKET%.sock}.drained.json"; do
            if [[ -e "$stale" || -L "$stale" ]]; then
                printf 'Refusing stale node-local Sandoq broker evidence\n' >&2
                exit 2
            fi
        done
    fi
fi
cd "$project_dir"

if [[ -n "$resume_dir" ]]; then
    approval_args=(
        --inputs-dir "$output_dir/inputs"
        --approved-task-file "$approved_task_file"
        --approved-task-file-sha256 "$approved_task_file_sha256"
        --resume-config "$output_dir/config.toml"
    )
else
    "$python_bin" "$workflow_dir/snapshot_eval_inputs.py" \
        "$eval_config" "$output_dir/inputs"
    approval_args=(
        --inputs-dir "$output_dir/inputs"
        --approved-task-file "$approved_task_file"
        --approved-task-file-sha256 "$approved_task_file_sha256"
    )
fi
approval_metadata=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/validate_task_approval.py" "${approval_args[@]}"
)
IFS=$'\t' read -r validated_approval_sha256 validated_approval_count metadata_extra \
    <<< "$approval_metadata"
if [[ "$validated_approval_sha256" != "$approved_task_file_sha256" \
    || ! "$validated_approval_count" =~ ^[1-9][0-9]*$ \
    || -n "$metadata_extra" \
    || "$approval_metadata" == *$'\n'* ]]; then
    printf 'Task approval validator returned invalid metadata\n' >&2
    exit 2
fi

if [[ -n "$resume_dir" ]]; then
    {
        printf 'resume_slurm_job_id=%s\n' "$SLURM_JOB_ID"
        printf 'resume_prime_rl=%s\n' "$(git rev-parse HEAD)"
        printf 'resume_verifiers=%s\n' "$(git -C deps/verifiers rev-parse HEAD)"
        printf 'resume_renderers=%s\n' "$(git -C deps/renderers rev-parse HEAD)"
        printf 'resume_approval_task_file_sha256=%s\n' "$validated_approval_sha256"
        printf 'resume_approval_task_count=%s\n' "$validated_approval_count"
        if [[ "$direct_qwen_router_metadata" -eq 1 ]]; then
            printf 'resume_direct_qwen_manifest_sha256=%s\n' "$direct_qwen_manifest_sha256"
            printf 'resume_direct_qwen_router_policy=%s\n' "$direct_qwen_router_policy"
            printf 'resume_direct_qwen_request_id_headers=%s\n' "$direct_qwen_request_id_headers"
            printf 'resume_direct_qwen_provider_concurrency=%s\n' "$direct_qwen_provider_concurrency"
            if [[ -n "$direct_qwen_generation_transition_sha256" ]]; then
                printf 'resume_qwen_serving_generation_transition_sha256=%s\n' \
                    "$direct_qwen_generation_transition_sha256"
                printf 'resume_qwen_serving_generation_capacity_smoke_sha256=%s\n' \
                    "$direct_qwen_capacity_smoke_sha256"
            fi
        fi
    } >> "$output_dir/provenance.txt"
else
    {
        printf 'prime_rl=%s\n' "$(git rev-parse HEAD)"
        printf 'verifiers=%s\n' "$(git -C deps/verifiers rev-parse HEAD)"
        printf 'renderers=%s\n' "$(git -C deps/renderers rev-parse HEAD)"
        printf 'inference_base_url=%s\n' "$inference_base_url"
        printf 'inference_deployment_id=%s\n' "$inference_deployment_id"
        printf 'slurm_job_id=%s\n' "$SLURM_JOB_ID"
        printf 'approval_task_file_sha256=%s\n' "$validated_approval_sha256"
        printf 'approval_task_count=%s\n' "$validated_approval_count"
        if [[ "$direct_qwen_router_metadata" -eq 1 ]]; then
            printf 'direct_qwen_manifest_sha256=%s\n' "$direct_qwen_manifest_sha256"
            printf 'direct_qwen_router_policy=%s\n' "$direct_qwen_router_policy"
            printf 'direct_qwen_request_id_headers=%s\n' "$direct_qwen_request_id_headers"
            printf 'direct_qwen_provider_concurrency=%s\n' "$direct_qwen_provider_concurrency"
            if [[ -n "$direct_qwen_generation_transition_sha256" ]]; then
                printf 'qwen_serving_generation_transition_sha256=%s\n' \
                    "$direct_qwen_generation_transition_sha256"
                printf 'qwen_serving_generation_capacity_smoke_sha256=%s\n' \
                    "$direct_qwen_capacity_smoke_sha256"
            fi
        fi
    } > "$output_dir/provenance.txt"
fi

if [[ -z "$resume_dir" && -n "$direct_qwen_generation_transition_sha256" ]]; then
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/migrate_qwen_serving_generation.py" commit-launch \
        --run-dir "$output_dir" \
        --expected-transition-sha256 "$direct_qwen_generation_transition_sha256" \
        --router-lock-fd 8 \
        --writer-lock-fd 9
fi
if [[ "$sandbox_provider" != sandoq ]]; then
    unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
fi
if [[ -n "$inference_proxy_url" && "$sandbox_provider" != sandoq ]]; then
    export HTTP_PROXY="$inference_proxy_url"
    export HTTPS_PROXY="$inference_proxy_url"
fi
export OPENAI_API_KEY=${OPENAI_API_KEY:-EMPTY}

if [[ -n "$resume_dir" ]]; then
    identity_mode=resume
else
    identity_mode=fresh
fi
identity_args=(
    --mode "$identity_mode"
    --output-dir "$output_dir"
    --inputs-dir "$output_dir/inputs"
    --expected-model "$eval_expected_model"
    --approved-task-file-sha256 "$validated_approval_sha256"
    --approved-task-count "$validated_approval_count"
    --role "$eval_run_role"
    --deployment-id "$eval_deployment_id"
    --deployment-spec "$deployment_spec"
    --deployment-spec-sha256 "$deployment_spec_sha256"
    --readiness-checkpoint "$readiness_checkpoint"
    --readiness-checkpoint-sha256 "$readiness_checkpoint_sha256"
    --deployment-proxy-info "$inference_proxy_info"
    --deployment-proxy-info-sha256 "$inference_proxy_info_sha256"
    --project-root "$project_dir"
    --sandbox-provider "$sandbox_provider"
    --prime-rl-commit "$prime_rl_commit"
    --prime-rl-tree-sha256 "$prime_rl_tree_sha256"
    --verifiers-commit "$verifiers_commit"
    --verifiers-tree-sha256 "$verifiers_tree_sha256"
    --renderers-commit "$renderers_commit"
    --renderers-tree-sha256 "$renderers_tree_sha256"
    --invocation-host "$(hostname)"
    --slurm-job-id "$SLURM_JOB_ID"
)
if [[ "$sandbox_provider" == vmvm ]]; then
    identity_args+=(
        --vmvm-tb-v2-sha256 "$vmvm_tb_v2_sha256"
        --vacli-bin "$VACLI_BIN"
        --vacli-max-concurrent-leases "$VACLI_MAX_CONCURRENT_LEASES"
        --vacli-lease-retries "$VACLI_LEASE_RETRIES"
        --vacli-max-pull-retries "$VACLI_MAX_PULL_RETRIES"
        --vacli-image-pull-timeout-seconds "$VACLI_IMAGE_PULL_TIMEOUT_SECONDS"
        --vacli-container-privileged "$VACLI_CONTAINER_PRIVILEGED"
    )
else
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
    identity_args+=(
        --sandoq-provider-commit "$sandoq_provider_commit"
        --sandoq-provider-tree "$sandoq_provider_tree"
        --sandoq-client-version "$sandoq_client_version"
        --sandoq-site "$sandoq_site"
        --sandoq-site-sha256 "$sandoq_site_sha256"
        --derived-image-manifest-sha256 "$derived_image_manifest_sha256"
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
    )
fi
if [[ -n "$inference_deployment_id" ]]; then
    identity_args+=(--routing-deployment-id "$inference_deployment_id")
fi
if [[ "$identity_mode" == fresh ]]; then
    identity_args+=(--client-base-url "$inference_base_url")
    if [[ -n "$eval_model" ]]; then
        identity_args+=(--model-override "$eval_model")
    fi
fi
if [[ -n "$eval_dataset_revision" ]]; then
    identity_args+=(--dataset-revision "$eval_dataset_revision")
else
    identity_args+=(
        --dataset-archive "$eval_dataset_archive"
        --dataset-archive-sha256 "$eval_dataset_archive_sha256"
        --dataset-content-sha256 "$eval_dataset_content_sha256"
    )
fi
if [[ -n "$smoke_checkpoint" ]]; then
    identity_args+=(
        --smoke-checkpoint "$smoke_checkpoint"
        --smoke-checkpoint-sha256 "$smoke_checkpoint_sha256"
    )
fi
if [[ -n "$promotion_certificate" ]]; then
    identity_args+=(
        --promotion-certificate "$promotion_certificate"
        --promotion-certificate-sha256 "$promotion_certificate_sha256"
    )
fi
eval_run_identity_sha256=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/eval_run_identity.py" "${identity_args[@]}"
)
if [[ ! "$eval_run_identity_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'Eval identity binder returned invalid metadata\n' >&2
    exit 2
fi
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 - "$output_dir/eval_run_identity.json" "$eval_run_identity_sha256" <<'PY'
import sys
from pathlib import Path
from eval_run_identity import load_eval_run_identity

envelope = load_eval_run_identity(Path(sys.argv[1]), verify_references=True)
if envelope["eval_run_identity_sha256"] != sys.argv[2]:
    raise SystemExit(2)
PY

args=(--resume "$output_dir")
guard_command=(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/inference_route_guard.py" \
    --deployment-id "$eval_deployment_id" \
    --deployment-spec "$deployment_spec" \
    --deployment-spec-sha256 "$deployment_spec_sha256" \
    --readiness-checkpoint "$readiness_checkpoint" \
    --readiness-checkpoint-sha256 "$readiness_checkpoint_sha256" \
    --proxy-info "$inference_proxy_info" \
    --proxy-info-sha256 "$inference_proxy_info_sha256" \
    --expected-model "$eval_expected_model" \
    --eval-run-identity "$output_dir/eval_run_identity.json" \
    --eval-run-identity-sha256 "$eval_run_identity_sha256" \
    --eval-invocations "$output_dir/eval_invocations.jsonl" \
    --results "$output_dir/results.jsonl" \
    --success-receipt "$output_dir/route_guard_success.json" \
    -- \
    "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 -c 'from verifiers.v1.cli.eval.main import main; main()' "${args[@]}"
)
if [[ "$sandbox_provider" == vmvm ]]; then
    exec "${guard_command[@]}"
fi
set +e
"${guard_command[@]}"
eval_status=$?
set -e
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
rm -f -- "$output_dir/pool_cleanup_audit.json" "$OCI_RUNNER_POOL_EVENT_LOG" \
    "$OCI_RUNNER_POOL_WAL" "${OCI_RUNNER_POOL_SOCKET%.sock}.drained.json"
exit "$eval_status"
