#!/bin/bash
#SBATCH --job-name=tb-qwen-direct
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=7-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_direct_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_direct_%j.log

set -euo pipefail
umask 077

preflight_only=0
if (( $# == 1 )) && [[ $1 == --preflight ]]; then
    preflight_only=1
elif (( $# != 0 )); then
    printf 'The direct Qwen launcher accepts only --preflight; use a pinned config\n' >&2
    exit 2
fi
for forbidden in \
    INFERENCE_BASE_URL \
    INFERENCE_DEPLOYMENT_ID \
    INFERENCE_JOB_ID \
    INFERENCE_PROXY_INFO \
    INFERENCE_PROXY_URL \
    DIRECT_QWEN_MANIFEST_SHA256 \
    DIRECT_QWEN_ROUTER_POLICY \
    DIRECT_QWEN_REQUEST_ID_HEADERS \
    DIRECT_QWEN_PROVIDER_CONCURRENCY \
    DIRECT_QWEN_GENERATION_TRANSITION_SHA256 \
    DIRECT_QWEN_CAPACITY_SMOKE_SHA256; do
    if [[ -n ${!forbidden:-} ]]; then
        printf '%s is forbidden for the direct-worker launcher\n' "$forbidden" >&2
        exit 2
    fi
done
if [[ -n ${OPENAI_API_KEY:-} && ${OPENAI_API_KEY} != EMPTY ]]; then
    printf 'The direct-worker launcher accepts only OPENAI_API_KEY=EMPTY\n' >&2
    exit 2
fi

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
deployment_root=${DIRECT_QWEN_DEPLOYMENT_ROOT:-/checkpoint/ram/shared/vllm_deployments_v2/shared_qwen38_2p4t}
router_site=${DIRECT_ROUTER_SITE:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/vllm_router_x86_64_0.1.26}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_ram_prime_f7313db4}
sandoq_extension="$project_dir/extensions/sandoq"
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
resume_dir=${RESUME_DIR:-}
approved_task_file=${DIRECT_QWEN_APPROVED_TASK_FILE:-}
approved_task_file_sha256=${DIRECT_QWEN_APPROVED_TASK_FILE_SHA256:-}
unset PYTHONPATH PYTHONHOME
serving_generation_bundle=${QWEN_SERVING_GENERATION_BUNDLE:-}

if [[ -z "$approved_task_file" || -z "$approved_task_file_sha256" ]]; then
    printf '%s\n' \
        'DIRECT_QWEN_APPROVED_TASK_FILE and DIRECT_QWEN_APPROVED_TASK_FILE_SHA256 are required' >&2
    exit 2
fi

if [[ -n "$resume_dir" ]]; then
    output_dir=$resume_dir
    eval_config="$resume_dir/config.toml"
    if [[ -z "$serving_generation_bundle" \
        && -d "$resume_dir/serving_generation_shared_qwen38_2p4t_e5ddc652" ]]; then
        serving_generation_bundle="$resume_dir/serving_generation_shared_qwen38_2p4t_e5ddc652"
    fi
else
    output_dir=${OUTPUT_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/qwen_direct_${SLURM_JOB_ID}}
    eval_config=${EVAL_CONFIG:-}
    if [[ -z "$eval_config" ]]; then
        printf 'EVAL_CONFIG with an approved task_file and task_file_sha256 is required\n' >&2
        exit 2
    fi
fi

sandbox_provider=$(python3 - "$eval_config" <<'PY'
import sys
import tomllib
with open(sys.argv[1], "rb") as handle:
    print(tomllib.load(handle).get("harness", {}).get("runtime", {}).get("type", ""))
PY
)
if [[ "$sandbox_provider" == sandoq && -n "$resume_dir" ]]; then
    printf 'Sandoq direct Qwen runs require fresh output\n' >&2
    exit 2
fi
if [[ "$sandbox_provider" == sandoq ]]; then
    pool_socket_dir="${SLURM_TMPDIR:-/tmp}/oci-runner-pool-${UID}"
    mkdir -p "$pool_socket_dir"
    chmod 0700 "$pool_socket_dir"
    export OCI_RUNNER_POOL_SOCKET="$pool_socket_dir/${SLURM_JOB_ID:?}.sock"
    for stale in \
        inputs config.toml results.jsonl provenance.txt eval_run_identity.json eval_invocations.jsonl \
        direct_workers.json direct_router.log pool_events.jsonl control/sandoq-pool.wal.jsonl \
        pool_cleanup_audit.json sandoq_cleanup_audit.json direct_qwen_sandoq_certificate.json; do
        if [[ -e "$output_dir/$stale" || -L "$output_dir/$stale" ]]; then
            printf 'Sandoq direct runs require a fresh output namespace\n' >&2
            exit 2
        fi
    done
    for stale in "$OCI_RUNNER_POOL_SOCKET" "$OCI_RUNNER_POOL_SOCKET.owner.json" \
        "${OCI_RUNNER_POOL_SOCKET%.sock}.drained.json"; do
        if [[ -e "$stale" || -L "$stale" ]]; then
            printf 'Sandoq direct runs reject stale node-local broker evidence\n' >&2
            exit 2
        fi
    done
    expected_count=$(python3 - "$eval_config" <<'PY'
import sys
import tomllib
with open(sys.argv[1], "rb") as handle:
    print(tomllib.load(handle)["num_tasks"])
PY
)
    ramp_receipt=${SANDOQ_RAMP_RECEIPT:?SANDOQ_RAMP_RECEIPT is required}
    ramp_receipt_sha256=${SANDOQ_RAMP_RECEIPT_SHA256:?SANDOQ_RAMP_RECEIPT_SHA256 is required}
fi

if [[ "$(uname -m)" != x86_64 || ! -d "$x86_site/pydantic" ]]; then
    printf 'Missing x86_64 evaluator runtime/dependencies\n' >&2
    exit 2
fi
if [[ ! -x "$x86_uv" ]]; then
    printf 'Missing x86_64 uv binary: %s\n' "$x86_uv" >&2
    exit 2
fi
if [[ ! -d "$router_site/site-packages/vllm_router-0.1.26.dist-info" \
    || ! -f "$router_site/STAGED" \
    || "$(sed -n '1p' "$router_site/STAGED" 2>/dev/null)" != "vllm-router=0.1.26" \
    || "$(sed -n '2p' "$router_site/STAGED" 2>/dev/null)" != "platform=x86_64-manylinux_2_28" \
    || ! -f "$router_site/requirements.sha256" \
    || "$(sha256sum "$router_site/requirements.txt" 2>/dev/null | cut -d' ' -f1)" != "$(cat "$router_site/requirements.sha256" 2>/dev/null)" ]]; then
    printf 'Missing pinned direct-router runtime: %s\n' "$router_site" >&2
    exit 2
fi
if [[ ! -r "$eval_config" ]]; then
    printf 'Missing evaluation config: %s\n' "$eval_config" >&2
    exit 2
fi
if [[ "$sandbox_provider" == sandoq ]]; then
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
        PYTHONPATH="$workflow_dir" \
            "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$provider_context" verify \
            --receipt "${SANDOQ_PROVIDER_CONTEXT_RECEIPT:?}" >/dev/null
    else
        if [[ -n ${SANDOQ_PROVIDER_CONTEXT_ACTIVE:-} \
            || -n ${SANDOQ_PROVIDER_CONTEXT_RECEIPT:-} ]]; then
            printf 'Partial Sandoq provider context is forbidden\n' >&2
            exit 2
        fi
        exec env PYTHONPATH="$workflow_dir" \
            "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$provider_context" supervise \
            --profile "$sandoq_provider_profile" \
            --profile-sha256 "$sandoq_provider_profile_sha256" \
            --concurrency "$sandoq_capacity" \
            --lease-create-cap "$sandoq_lease_create_cap" \
            --startup-timeout-seconds 3600 \
            --ecr-token-file "$sandoq_ecr_token_file" \
            --ecr-token-metadata "$sandoq_ecr_token_metadata" \
            --project-root "$project_dir" --sandoq-site "$sandoq_site" \
            -- bash "$workflow_dir/run_qwen_direct_eval.sbatch" "$@"
    fi
fi
cd "$project_dir"

if [[ "$sandbox_provider" == sandoq ]]; then
    if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" \
        || -n "$(git -C deps/verifiers status --porcelain=v1 --untracked-files=all)" \
        || -n "$(git -C deps/renderers status --porcelain=v1 --untracked-files=all)" ]]; then
        printf 'Sandoq direct wrapper requires the approved clean source closure\n' >&2
        exit 2
    fi
    if [[ ! -f "$sandoq_extension/UPSTREAM.md" ]] \
        || ! grep -Fq 'f7313db42eea4b3be8bcbe16a8072f73cf6abed5' "$sandoq_extension/UPSTREAM.md" \
        || ! grep -Fq '46ee7064345aa0e8cee47b61a21feeb2d9049361' "$sandoq_extension/UPSTREAM.md"; then
        printf 'Vendored Sandoq extension provenance is invalid\n' >&2
        exit 2
    fi
    if [[ ! -d "$sandoq_site/sandoq_client" ]]; then
        printf 'Missing pinned x86_64 Sandoq client site\n' >&2
        exit 2
    fi
    wrapper_sandoq_site_sha256=$(
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
    if [[ "$wrapper_sandoq_site_sha256" != 852f66db48c06e3928c6a5ff974c94bb21c93511342b205c2b7d1b99e73c3d6b ]]; then
        printf 'Sandoq staged dependency tree does not match the approved closure\n' >&2
        exit 2
    fi
    wrapper_sandoq_client_version=$(
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
    if [[ "$wrapper_sandoq_client_version" != 0.4.0.2026.8.20.58304.0+hga81e4ca4d312 ]]; then
        printf 'Sandoq client version does not match the approved pin\n' >&2
        exit 2
    fi
fi

mkdir -p "$output_dir" /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs
exec 8>"$output_dir/.direct_router.lock"
if ! flock -n 8; then
    printf 'Another direct router owns %s\n' "$output_dir" >&2
    exit 2
fi

runtime_dir=$(mktemp -d "${SLURM_TMPDIR:-/tmp}/tb-qwen-router-${SLURM_JOB_ID}.XXXXXX")
urls_file="$runtime_dir/worker_urls.txt"
ports_file="$runtime_dir/ports.txt"
router_log="$output_dir/direct_router.log"
manifest="$output_dir/direct_workers.json"
router_pid=
eval_pid=
cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [[ -n "$eval_pid" ]] && kill -0 "$eval_pid" 2>/dev/null; then
        kill -TERM "$eval_pid" 2>/dev/null || true
        wait "$eval_pid" 2>/dev/null || true
    fi
    if [[ -n "$router_pid" ]] && kill -0 "$router_pid" 2>/dev/null; then
        kill -TERM -- "-$router_pid" 2>/dev/null || true
        wait "$router_pid" 2>/dev/null || true
    fi
    rm -rf -- "$runtime_dir"
    exit "$status"
}
trap cleanup EXIT INT TERM

if [[ "$sandbox_provider" != sandoq ]]; then
    while IFS= read -r variable_name; do
        if [[ ${variable_name,,} == *_proxy && $variable_name != SANDOQ_TUNNEL_HTTPS_PROXY ]]; then
            unset "$variable_name"
        fi
    done < <(compgen -e)
fi

if [[ -n "$serving_generation_bundle" ]]; then
    prepare_args=(
        "$workflow_dir/migrate_qwen_serving_generation.py"
        prepare-launch
        --bundle-dir "$serving_generation_bundle"
        --run-dir "$output_dir"
        --urls-output "$urls_file"
        --ports-output "$ports_file"
        --router-lock-fd 8
    )
    if [[ -n "$resume_dir" ]]; then
        prepare_args+=(--resume)
    fi
else
    prepare_args=(
        "$workflow_dir/direct_qwen_workers.py"
        --deployment-root "$deployment_root"
        --eval-config "$eval_config"
        --manifest "$manifest"
        --urls-output "$urls_file"
        --ports-output "$ports_file"
        --approved-task-file "$approved_task_file"
        --approved-task-file-sha256 "$approved_task_file_sha256"
    )
    if [[ -n "$resume_dir" ]]; then
        prepare_args+=(--resume)
    fi
fi
"$x86_uv" run --no-project --offline --python "$python_bin" python3 "${prepare_args[@]}"
if [[ -n "$serving_generation_bundle" && -z "$resume_dir" ]]; then
    eval_config="$output_dir/serving_generation_shared_qwen38_2p4t_e5ddc652/repair_generation_config.toml"
fi

mapfile -t worker_urls < "$urls_file"
mapfile -t ports < "$ports_file"
expected_worker_count=16
expected_port_fields=7
expected_vmvm_lease_concurrency=2
generation_transition_sha256=
if [[ -n "$serving_generation_bundle" ]]; then
    expected_worker_count=24
    expected_port_fields=9
    expected_router_max_concurrent=48
    expected_router_queue_size=48
    expected_rollout_concurrency=96
    expected_vmvm_lease_concurrency=4
fi
if [[ ${#worker_urls[@]} -ne "$expected_worker_count" || ${#ports[@]} -ne "$expected_port_fields" ]]; then
    printf 'Direct-worker runtime files are incomplete\n' >&2
    exit 2
fi
router_port=${ports[0]}
metrics_port=${ports[1]}
router_max_concurrent=${ports[2]}
router_queue_size=${ports[3]}
router_queue_timeout=${ports[4]}
router_policy=${ports[5]}
router_request_id_header=${ports[6]}
if [[ -n "$serving_generation_bundle" ]]; then
    if [[ ${ports[7]} != 24 || ! ${ports[8]} =~ ^[0-9a-f]{64}$ ]]; then
        printf 'Serving-generation runtime metadata is invalid\n' >&2
        exit 2
    fi
    generation_transition_sha256=${ports[8]}
fi
if [[ ! "$router_max_concurrent" =~ ^[1-9][0-9]*$ ]] \
    || [[ ! "$router_queue_size" =~ ^[0-9]+$ ]] \
    || [[ ! "$router_queue_timeout" =~ ^[1-9][0-9]*$ ]] \
    || [[ "$router_policy" != consistent_hash ]] \
    || [[ "$router_request_id_header" != x-session-id ]]; then
    printf 'Direct Qwen router concurrency is invalid\n' >&2
    exit 2
fi
if [[ -n "$serving_generation_bundle" ]]; then
    if (( router_max_concurrent != expected_router_max_concurrent \
        || router_queue_size != expected_router_queue_size \
        || router_max_concurrent + router_queue_size != expected_rollout_concurrency )); then
        printf 'Serving-generation router capacity is invalid\n' >&2
        exit 2
    fi
elif (( router_max_concurrent > 32 \
    || router_queue_size >= 64 \
    || router_max_concurrent + router_queue_size > 64 )); then
    printf 'Direct Qwen router concurrency is invalid\n' >&2
    exit 2
fi
manifest_sha256=$(sha256sum -- "$manifest" | cut -d' ' -f1)
if [[ ! "$manifest_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'Direct Qwen router manifest digest is invalid\n' >&2
    exit 2
fi

router_args=(
    -c 'from vllm_router.launch_router import main; main()'
    --policy "$router_policy"
    --request-id-headers "$router_request_id_header"
    --host 127.0.0.1
    --port "$router_port"
    --prometheus-host 127.0.0.1
    --prometheus-port "$metrics_port"
    --worker-startup-timeout-secs 60
    --request-timeout-secs 7500
    --disable-retries
    --max-concurrent-requests "$router_max_concurrent"
    --queue-size "$router_queue_size"
    --queue-timeout-secs "$router_queue_timeout"
    --log-level warning
    --worker-urls "${worker_urls[@]}"
)
setsid env PYTHONPATH="$router_site/site-packages" \
    "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "${router_args[@]}" > "$router_log" 2>&1 &
router_pid=$!

router_url="http://127.0.0.1:${router_port}"
metrics_url="http://127.0.0.1:${metrics_port}/metrics"
for attempt in $(seq 1 60); do
    if ! kill -0 "$router_pid" 2>/dev/null; then
        printf 'Direct Qwen router exited during startup; see %s\n' "$router_log" >&2
        exit 2
    fi
    models_ready=0
    active_workers=
    if curl --noproxy '*' --fail --silent --show-error --max-time 10 \
        "$router_url/v1/models" >/dev/null 2>&1; then
        models_ready=1
    fi
    active_workers=$(
        curl --noproxy '*' --fail --silent --show-error --max-time 10 \
            "$metrics_url" 2>/dev/null \
            | awk '$1 == "vllm_router_active_workers" {print $2}' \
            | tail -n 1
    ) || true
    if [[ "$models_ready" -eq 1 && "$active_workers" == "$expected_worker_count" ]]; then
        break
    fi
    if [[ "$attempt" -eq 60 ]]; then
        printf 'Direct Qwen router did not expose the exact worker generation\n' >&2
        exit 2
    fi
    sleep 5
done

capacity_smoke_sha256=
if [[ -n "$generation_transition_sha256" ]]; then
    if [[ -z "$resume_dir" ]]; then
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$workflow_dir/migrate_qwen_serving_generation.py" capacity-smoke \
            --run-dir "$output_dir" \
            --base-url "$router_url/v1" \
            --expected-transition-sha256 "$generation_transition_sha256" \
            --router-lock-fd 8
    fi
    capacity_smoke_sha256=$(sha256sum -- "$output_dir/capacity_smoke.json" | cut -d' ' -f1)
    if [[ ! "$capacity_smoke_sha256" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'Serving-generation capacity certificate is invalid\n' >&2
        exit 2
    fi
fi

export PROJECT_DIR="$project_dir"
export OUTPUT_DIR="$output_dir"
export INFERENCE_BASE_URL="$router_url/v1"
export OPENAI_API_KEY=EMPTY
export VACLI_MAX_CONCURRENT_LEASES="$expected_vmvm_lease_concurrency"
export DIRECT_QWEN_MANIFEST_SHA256="$manifest_sha256"
export DIRECT_QWEN_ROUTER_POLICY="$router_policy"
export DIRECT_QWEN_REQUEST_ID_HEADERS="$router_request_id_header"
export DIRECT_QWEN_PROVIDER_CONCURRENCY="$router_max_concurrent"
if [[ -n "$generation_transition_sha256" ]]; then
    export DIRECT_QWEN_GENERATION_TRANSITION_SHA256="$generation_transition_sha256"
    export DIRECT_QWEN_CAPACITY_SMOKE_SHA256="$capacity_smoke_sha256"
fi
if [[ -n "$resume_dir" ]]; then
    export RESUME_DIR="$resume_dir"
else
    export EVAL_CONFIG="$eval_config"
fi

if [[ "$preflight_only" -eq 1 ]]; then
    bash "$workflow_dir/run_direct_qwen_eval_driver.sh" --preflight &
else
    bash "$workflow_dir/run_eval.sbatch" &
fi
eval_pid=$!
wait "$eval_pid"
eval_pid=
if [[ "$sandbox_provider" == sandoq && "$preflight_only" -eq 1 ]]; then
    rm -f -- "$manifest" "$router_log" "$output_dir/.direct_router.lock"
    rmdir -- "$output_dir" 2>/dev/null || true
fi
if [[ "$sandbox_provider" == sandoq && "$preflight_only" -eq 0 ]]; then
    if [[ -z "$router_pid" ]] || ! kill -0 "$router_pid" 2>/dev/null; then
        printf 'Direct Qwen router was not live at certification\n' >&2
        exit 2
    fi
    if ! curl --noproxy '*' --fail --silent --show-error --max-time 10 \
        "$router_url/v1/models" >/dev/null; then
        printf 'Direct Qwen router health failed at certification\n' >&2
        exit 2
    fi
    final_active_workers=$(
        curl --noproxy '*' --fail --silent --show-error --max-time 10 "$metrics_url" \
            | awk '$1 == "vllm_router_active_workers" {print $2}' \
            | tail -n 1
    )
    if [[ "$final_active_workers" != 24 ]]; then
        printf 'Direct Qwen router no longer has exactly 24 active workers\n' >&2
        exit 2
    fi
    final_generation=$(
        PYTHONPATH="$workflow_dir" \
            "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 - "$manifest" "$deployment_root" <<'PY'
import sys
from pathlib import Path
from direct_qwen_workers import validate_post_eval_generation

manifest_path = Path(sys.argv[1])
print(
    validate_post_eval_generation(
        manifest_path,
        Path(sys.argv[2]),
        router_alive=True,
        active_workers=24,
    )
)
PY
    )
    if [[ "$final_generation" != "$manifest_sha256" ]]; then
        printf 'Direct Qwen serving generation drifted during evaluation\n' >&2
        exit 2
    fi
    certificate_args=(
        "$workflow_dir/certify_direct_qwen_sandoq.py"
        --run-dir "$output_dir" --expected-task-file "$approved_task_file" \
        --expected-task-file-sha256 "$approved_task_file_sha256" \
        --expected-count "$expected_count" \
        --cleanup-audit "$output_dir/sandoq_cleanup_audit.json" \
        --ramp-receipt "$ramp_receipt" --ramp-receipt-sha256 "$ramp_receipt_sha256" \
        --canonical-task-source "$workflow_dir/configs/eval/mobius_valid_tasks_2500.txt" \
        --canonical-template "$workflow_dir/configs/eval/shared_qwen38_2p4t/mobius_qwen_a95b_2500_sandoq.toml" \
        --output "$output_dir/direct_qwen_sandoq_certificate.json"
    )
    if [[ -n ${SANDOQ_PREDECESSOR_CERTIFICATE:-} || -n ${SANDOQ_PREDECESSOR_CERTIFICATE_SHA256:-} ]]; then
        certificate_args+=(
            --predecessor "${SANDOQ_PREDECESSOR_CERTIFICATE:-}"
            --predecessor-sha256 "${SANDOQ_PREDECESSOR_CERTIFICATE_SHA256:-}"
        )
    fi
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "${certificate_args[@]}" >/dev/null
    rm -f -- "$output_dir/pool_cleanup_audit.json" "$output_dir/pool_events.jsonl" \
        "$output_dir/control/sandoq-pool.wal.jsonl" \
        "${OCI_RUNNER_POOL_SOCKET%.sock}.drained.json"
fi
