#!/bin/bash
#SBATCH --job-name=k3-tb4-direct-8103
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=7-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=48G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_direct_8103_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_direct_8103_%j.log

set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf 'Configure the direct Kimi run through its sealed environment\n' >&2
    exit 2
fi

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
server_dir="$workflow_dir/configs/eval/servers/cpu-132-021_8103"
expected_revision=${KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION:?Set KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION}
stage=${KIMI_SANDOQ_STAGE:-smoke}
preflight_only=${KIMI_SANDOQ_PREFLIGHT_ONLY:-0}
deployment_root=/checkpoint/ram/shared/vllm_deployments_v2/shared-kimi-k3
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_ram_prime_f7313db4}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
eval_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals
generation_dir="$eval_root/kimi_k3_direct_generation_cpu-132-021_8103_${SLURM_JOB_ID}"
if [[ "$stage" == mobius-smoke ]]; then
    output_dir="$eval_root/mobius_kimi_k3_direct_sandoq_cpu-132-021_8103_${SLURM_JOB_ID}_smoke"
else
    output_dir="$eval_root/tb4_kimi_k3_direct_sandoq_cpu-132-021_8103_${SLURM_JOB_ID}_${stage}"
fi
manifest="$generation_dir/direct_kimi_workers.json"
urls_file="$generation_dir/worker_urls.private.txt"
ports_file="$generation_dir/router_ports.private.txt"
router_log="$generation_dir/direct_router.log"
router_stats="$generation_dir/direct_router_stats.private.json"
provider_profile="$server_dir/sandoq_use2.json"
router_pid=

cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [[ -n "$router_pid" ]] && kill -0 "$router_pid" 2>/dev/null; then
        kill -TERM -- "-$router_pid" 2>/dev/null || true
        wait "$router_pid" 2>/dev/null || true
    fi
    exit "$status"
}
trap cleanup EXIT INT TERM

if [[ "$stage" != smoke && "$stage" != mobius-smoke && "$stage" != tb4 ]]; then
    printf 'KIMI_SANDOQ_STAGE must be smoke, mobius-smoke, or tb4\n' >&2
    exit 2
fi
if [[ "$stage" != tb4 ]]; then
    smoke_wall_limit=$(squeue -h -j "$SLURM_JOB_ID" -o '%l')
    expected_smoke_wall_limit=20:00
    if [[ "$stage" == mobius-smoke ]]; then
        expected_smoke_wall_limit=12:00
    fi
    if [[ "$smoke_wall_limit" != "$expected_smoke_wall_limit" ]]; then
        printf 'Direct Kimi smoke requires its exact Slurm wall limit\n' >&2
        exit 2
    fi
fi
if [[ "$preflight_only" != 0 && "$preflight_only" != 1 ]]; then
    printf 'KIMI_SANDOQ_PREFLIGHT_ONLY must be 0 or 1\n' >&2
    exit 2
fi
if [[ ! "$expected_revision" =~ ^[0-9a-f]{40}$ \
    || "$(git -C "$project_dir" rev-parse HEAD)" != "$expected_revision" \
    || -n "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]]; then
    printf 'PROJECT_DIR must be the exact clean approved direct Kimi source\n' >&2
    exit 2
fi
if [[ -e "$generation_dir" || -L "$generation_dir" || -e "$output_dir" || -L "$output_dir" ]]; then
    printf 'Direct Kimi output namespace is not fresh\n' >&2
    exit 2
fi
if [[ ! -d "$x86_site/pydantic" || ! -d "$sandoq_site/sandoq_client" \
    || ! -x "$x86_uv" || ! -f "$provider_profile" || -L "$provider_profile" ]]; then
    printf 'Direct Kimi pinned runtime is unavailable\n' >&2
    exit 2
fi
if [[ "$(sha256sum "$provider_profile" | cut -d' ' -f1)" \
    != 965511eb9578aa303d287491a7414e145241d6dbbf61469d13abbe801980a95a ]]; then
    printf 'Direct Kimi provider profile digest mismatch\n' >&2
    exit 2
fi

if [[ "$stage" == smoke ]]; then
    eval_config="$server_dir/tb4_kimi_k3_sandoq_smoke.toml"
    # Exact one-task authorization derived ID-blind from the reviewed
    # non-security TB4 smoke set. Never print its task identifier.
    task_file="$workflow_dir/configs/eval/tb4_kimi_k3_short_smoke.tasks.txt"
    task_sha256=c1f745d4a1d3861deefb3fba4daa23f52ff3d1d4952a9fe2ba0ccbdc4040af97
    task_count=1
    stage_capacity=1
    identity_role=kimi-direct-smoke
    certificate_mode=smoke
elif [[ "$stage" == mobius-smoke ]]; then
    eval_config="$server_dir/mobius_kimi_k3_max_sandoq_smoke.toml"
    task_file=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/use2/qwen_quick_debug/task_stable.txt
    task_sha256=1f6489ac59a4562b7674ae1779832be08c6e7b859d691dba7e81c89fa91147ca
    task_count=1
    stage_capacity=1
    identity_role=kimi-direct-smoke
    certificate_mode=smoke
else
    eval_config="$server_dir/tb4_kimi_k3_sandoq_pass1.toml"
    task_file="$workflow_dir/configs/eval/tb4_qwen_a95b_miniswe.tasks.txt"
    task_sha256=9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892
    task_count=66
    stage_capacity=24
    identity_role=kimi-direct-tb4
    certificate_mode=tb4
    smoke_checkpoint=${KIMI_SANDOQ_SMOKE_CHECKPOINT:?Set KIMI_SANDOQ_SMOKE_CHECKPOINT}
    smoke_checkpoint_sha256=${KIMI_SANDOQ_SMOKE_CHECKPOINT_SHA256:?Set KIMI_SANDOQ_SMOKE_CHECKPOINT_SHA256}
    if [[ ! -f "$smoke_checkpoint" || -L "$smoke_checkpoint" \
        || "$(sha256sum "$smoke_checkpoint" | cut -d' ' -f1)" != "$smoke_checkpoint_sha256" ]]; then
        printf 'Direct Kimi smoke checkpoint is unavailable or changed\n' >&2
        exit 2
    fi
fi
for path in "$eval_config" "$task_file"; do
    if [[ ! -f "$path" || -L "$path" ]]; then
        printf 'Direct Kimi evaluation input is unavailable or unsafe\n' >&2
        exit 2
    fi
done
if [[ "$(sha256sum "$task_file" | cut -d' ' -f1)" != "$task_sha256" ]]; then
    printf 'Direct Kimi approved task set changed\n' >&2
    exit 2
fi

mkdir -p "$generation_dir"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" prepare \
    --deployment-root "$deployment_root" --output-root "$generation_dir" \
    --manifest "$manifest" --urls-output "$urls_file" --ports-output "$ports_file" --probe
manifest_sha256=$(sha256sum "$manifest" | cut -d' ' -f1)
mapfile -t worker_urls < "$urls_file"
mapfile -t router_ports < "$ports_file"
if [[ ${#worker_urls[@]} -ne 24 || ${#router_ports[@]} -ne 2 ]]; then
    printf 'Direct Kimi generation materialization failed\n' >&2
    exit 2
fi
router_port=${router_ports[0]}
metrics_port=${router_ports[1]}

while IFS= read -r variable_name; do
    if [[ ${variable_name,,} == *_proxy ]]; then
        unset "$variable_name"
    fi
done < <(compgen -e)
setsid "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_router.py" \
        --worker-urls-file "$urls_file" \
        --host 127.0.0.1 \
        --port "$router_port" \
        --metrics-port "$metrics_port" >"$router_log" 2>&1 &
router_pid=$!

for attempt in $(seq 1 120); do
    if ! kill -0 "$router_pid" 2>/dev/null; then
        printf 'Direct Kimi router exited during startup\n' >&2
        exit 2
    fi
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
    if [[ "$attempt" -eq 120 ]]; then
        printf 'Direct Kimi router did not become ready\n' >&2
        exit 2
    fi
    sleep 1
done

ecr_token_file=/storage/home/tianhaowu/.config/oci-runner/ecr-token
ecr_token_metadata=${OCI_RUNNER_ECR_TOKEN_METADATA_PATH:-${ecr_token_file}.metadata.json}
stage_env=(
    PROJECT_DIR="$project_dir"
    EVAL_CONFIG="$eval_config"
    OUTPUT_DIR="$output_dir"
    DIRECT_KIMI_ROLE="$identity_role"
    DIRECT_KIMI_APPROVED_TASK_FILE="$task_file"
    DIRECT_KIMI_APPROVED_TASK_FILE_SHA256="$task_sha256"
    DIRECT_KIMI_WORKER_MANIFEST="$manifest"
    DIRECT_KIMI_WORKER_MANIFEST_SHA256="$manifest_sha256"
    DIRECT_KIMI_BASE_URL="http://127.0.0.1:${router_port}/v1"
    DIRECT_KIMI_EXPECTED_PRIME_RL_REVISION="$expected_revision"
    DIRECT_KIMI_PREFLIGHT_ONLY="$preflight_only"
)
if [[ "$stage" == tb4 ]]; then
    stage_env+=(
        DIRECT_KIMI_SMOKE_CHECKPOINT="$smoke_checkpoint"
        DIRECT_KIMI_SMOKE_CHECKPOINT_SHA256="$smoke_checkpoint_sha256"
    )
fi
env "${stage_env[@]}" \
    "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" supervise \
    --profile "$provider_profile" \
    --profile-sha256 965511eb9578aa303d287491a7414e145241d6dbbf61469d13abbe801980a95a \
    --concurrency "$stage_capacity" \
    --lease-create-cap "$(( stage_capacity < 4 ? stage_capacity : 4 ))" \
    --startup-timeout-seconds 3600 \
    --ecr-token-file "$ecr_token_file" \
    --ecr-token-metadata "$ecr_token_metadata" \
    --project-root "$project_dir" --sandoq-site "$sandoq_site" \
    -- bash "$workflow_dir/run_direct_kimi_sandoq_stage.sh"
if [[ "$preflight_only" == 1 ]]; then
    printf '{"job_id":"%s","stage":"%s","state":"preflight-passed"}\n' "$SLURM_JOB_ID" "$stage"
    exit 0
fi

if ! kill -0 "$router_pid" 2>/dev/null; then
    printf 'Direct Kimi router exited before certification\n' >&2
    exit 2
fi
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
    --manifest "$manifest" --manifest-sha256 "$manifest_sha256" \
    --active-workers "$active_workers" --router-stats "$router_stats" \
    --output "$output_dir/direct_kimi_router_final.json"

certificate_args=(
    "$workflow_dir/certify_direct_kimi.py" "$certificate_mode"
    --run-dir "$output_dir"
    --expected-task-file "$task_file"
    --expected-task-file-sha256 "$task_sha256"
    --output "$output_dir/$([[ "$stage" == smoke ]] && printf smoke_checkpoint.json || printf checkpoint.json)"
)
if [[ "$stage" == tb4 ]]; then
    certificate_args+=(
        --smoke-checkpoint "$smoke_checkpoint"
        --smoke-checkpoint-sha256 "$smoke_checkpoint_sha256"
    )
fi
"$x86_uv" run --no-project --offline --python "$python_bin" python3 "${certificate_args[@]}"
if [[ "$stage" != tb4 ]]; then
    printf '{"job_id":"%s","stage":"%s","state":"capacity-limited-passed"}\n' "$SLURM_JOB_ID" "$stage"
else
    printf '{"job_id":"%s","stage":"%s","state":"passed"}\n' "$SLURM_JOB_ID" "$stage"
fi
