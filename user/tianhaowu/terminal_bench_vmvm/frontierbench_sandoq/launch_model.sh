#!/usr/bin/env bash
#SBATCH --job-name=frontier-model
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=48G
#SBATCH --time=7-00:00:00
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/frontier_model_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/frontier_model_%j.log

set -euo pipefail
umask 077

model_kind=${1:-}
run_mode=${2:-full}
[[ "$model_kind" == qwen || "$model_kind" == kimi ]] \
    || { printf 'usage: %s qwen|kimi [smoke|full]\n' "$0" >&2; exit 2; }
[[ "$run_mode" == smoke || "$run_mode" == full ]] \
    || { printf 'usage: %s qwen|kimi [smoke|full]\n' "$0" >&2; exit 2; }

if [[ -n ${FRONTIERBENCH_SCRIPT_DIR:-} ]]; then
    script_dir=$(cd -- "$FRONTIERBENCH_SCRIPT_DIR" && pwd)
else
    script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
fi
project_dir=${FRONTIERBENCH_PROJECT_DIR:-$(cd -- "$script_dir/../../../.." && pwd)}
project_dir=$(cd -- "$project_dir" && pwd)
set -a
source "$script_dir/frontierbench.env"
set +a

for value in "$FRONTIERBENCH_EXPECTED_TASKS" "$QWEN_MAX_CONCURRENT" "$KIMI_MAX_CONCURRENT" \
    "$MODEL_MAX_CONTEXT_TOKENS" "$MODEL_MAX_GENERATION_TOKENS" "$MODEL_FULL_STEP_LIMIT" \
    "$MODEL_SMOKE_STEP_LIMIT" "$MODEL_SMOKE_SESSION_TIMEOUT_SECONDS" \
    "$MODEL_SMOKE_SETUP_TIMEOUT_SECONDS" "$MODEL_SMOKE_ROLLOUT_TIMEOUT_SECONDS" \
    "$MODEL_SMOKE_FINALIZE_TIMEOUT_SECONDS" "$MODEL_SMOKE_SCORING_TIMEOUT_SECONDS" \
    "$SANDOQ_POOL_MAX" "$SANDOQ_LEASE_CREATE_CAP" "$SANDOQ_STARTUP_TIMEOUT_SECONDS"; do
    [[ "$value" =~ ^[1-9][0-9]*$ ]] \
        || { printf 'Configured counts and timeouts must be positive integers\n' >&2; exit 2; }
done
(( MODEL_MAX_GENERATION_TOKENS <= MODEL_MAX_CONTEXT_TOKENS )) \
    || { printf 'Generation limit cannot exceed the context limit\n' >&2; exit 2; }
[[ "$FRONTIERBENCH_RUN_VARIANT" =~ ^[A-Za-z0-9._-]+$ ]] \
    || { printf 'Run variant must be a safe path component\n' >&2; exit 2; }

config="$script_dir/configs/cpu-131-159_8100/qwen.toml"
base_url=$QWEN_BASE_URL
model=$QWEN_MODEL
max_concurrent=$QWEN_MAX_CONCURRENT
reasoning_effort=$QWEN_REASONING_EFFORT
model_api_key_file=$QWEN_API_KEY_FILE
provider_profile="$project_dir/$SANDOQ_QWEN_PROVIDER_PROFILE"
provider_profile_sha256=$SANDOQ_QWEN_PROVIDER_PROFILE_SHA256
if [[ "$model_kind" == kimi ]]; then
    config="$script_dir/configs/cpu-132-021_8103/kimi.toml"
    base_url=$KIMI_BASE_URL
    model=$KIMI_MODEL
    max_concurrent=$KIMI_MAX_CONCURRENT
    reasoning_effort=$KIMI_REASONING_EFFORT
    model_api_key_file=$KIMI_API_KEY_FILE
    provider_profile="$project_dir/$SANDOQ_KIMI_PROVIDER_PROFILE"
    provider_profile_sha256=$SANDOQ_KIMI_PROVIDER_PROFILE_SHA256
fi

dataset_dir=$FRONTIERBENCH_DATASET_DIR
dataset_tree_sha256=$FRONTIERBENCH_DATASET_TREE_SHA256
manifest="$FRONTIERBENCH_RUN_ROOT/full-image-manifest.json"
source_revision=$(git -C "$project_dir" rev-parse --verify HEAD)
oracle_output="$FRONTIERBENCH_RUN_ROOT/oracle-full-${FRONTIERBENCH_RUN_VARIANT}-${source_revision:0:12}"
[[ -z "$FRONTIERBENCH_ORACLE_FULL_OUTPUT" ]] || oracle_output=$FRONTIERBENCH_ORACLE_FULL_OUTPUT
task_file="$oracle_output/pass-tasks.txt"
if [[ "$run_mode" == smoke ]]; then
    dataset_dir=$FRONTIERBENCH_SMOKE_DATASET_DIR
    dataset_tree_sha256=$FRONTIERBENCH_SMOKE_DATASET_TREE_SHA256
    manifest="$FRONTIERBENCH_RUN_ROOT/smoke-image-manifest.json"
    oracle_output="$FRONTIERBENCH_RUN_ROOT/oracle-smoke-${FRONTIERBENCH_RUN_VARIANT}-${source_revision:0:12}"
    [[ -z "$FRONTIERBENCH_ORACLE_SMOKE_OUTPUT" ]] || oracle_output=$FRONTIERBENCH_ORACLE_SMOKE_OUTPUT
    task_file="$oracle_output/pass-tasks.txt"
    max_concurrent=1
fi

if [[ -z ${SLURM_JOB_ID:-} ]]; then
    [[ -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]] \
        || { printf 'Prime-RL checkout must be clean\n' >&2; exit 2; }
    wall=7-00:00:00
    [[ "$run_mode" == smoke ]] && wall=00:30:00
    expected_revision=$(git -C "$project_dir" rev-parse HEAD)
    exec env FRONTIERBENCH_EXPECTED_REVISION="$expected_revision" \
        FRONTIERBENCH_SCRIPT_DIR="$script_dir" FRONTIERBENCH_PROJECT_DIR="$project_dir" \
        sbatch --time="$wall" --parsable "$0" "$model_kind" "$run_mode"
fi

[[ "$(uname -m)" == x86_64 ]] || { printf 'Model runner requires x86_64\n' >&2; exit 2; }
[[ ${FRONTIERBENCH_EXPECTED_REVISION:-} =~ ^[0-9a-f]{40}$ \
    && "$(git -C "$project_dir" rev-parse HEAD)" == "$FRONTIERBENCH_EXPECTED_REVISION" \
    && -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]] \
    || { printf 'Model runner source identity changed after submission\n' >&2; exit 2; }
[[ -f "$config" && -f "$manifest" && -d "$dataset_dir" && -d "$oracle_output/tasks" ]] \
    || { printf 'Model inputs are incomplete; finish the matching oracle run first\n' >&2; exit 2; }
for secret in "$SANDOQ_FIRECRACKER_TOKEN_FILE" "$SANDOQ_PRODUCTION_ECR_TOKEN_FILE" \
    "$SANDOQ_DEVELOPMENT_ECR_TOKEN_FILE" "$model_api_key_file"; do
    [[ -f "$secret" && ! -L "$secret" && "$(stat -c '%a:%u:%h' -- "$secret")" == "600:$(id -u):1" ]] \
        || { printf 'A required owner-only credential file is unavailable\n' >&2; exit 2; }
done

expected_oracle_tasks=$FRONTIERBENCH_EXPECTED_TASKS
[[ "$run_mode" == smoke ]] && expected_oracle_tasks=1
if ! jq -e --argjson expected "$expected_oracle_tasks" \
    '.selected == $expected and .completed == $expected and .pass_rate >= 0.9' \
    "$oracle_output/summary.json" >/dev/null; then
    printf 'Oracle aggregate is incomplete or below the 90%% gate\n' >&2
    exit 2
fi

temporary_task_file="$task_file.$SLURM_JOB_ID.tmp"
install -d -m 700 "$(dirname -- "$task_file")"
jq -r 'select(.valid == true) | .slug' "$oracle_output"/tasks/*.json | LC_ALL=C sort -u >"$temporary_task_file"
[[ -s "$temporary_task_file" ]] || { printf 'Oracle produced no passing task selection\n' >&2; exit 2; }
mv -f -- "$temporary_task_file" "$task_file"
chmod 600 "$task_file"
task_count=$(awk 'NF{n++} END{print n+0}' "$task_file")
task_file_sha256=$(sha256sum "$task_file" | cut -d' ' -f1)
manifest_sha256=$(sha256sum "$manifest" | cut -d' ' -f1)

x86_uv=$UV_BIN_X86_64
python_bin=$PYTHON_BIN_X86_64
x86_site=$PYTHON_SITE_X86_64
sandoq_site=$SANDOQ_PYTHON_SITE_X86_64
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
output_dir="$FRONTIERBENCH_RUN_ROOT/model-${model_kind}-${run_mode}-${SLURM_JOB_ID}"
install -d -m 700 "$output_dir" "$output_dir/control"
chmod 700 "$output_dir" "$output_dir/control"
[[ -f "$provider_profile" && "$(sha256sum "$provider_profile" | cut -d' ' -f1)" == "$provider_profile_sha256" ]] \
    || { printf 'Pinned Sandoq provider profile is unavailable or changed\n' >&2; exit 2; }

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/extensions/sandoq:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$sandoq_site:$x86_site"
observed_dataset_tree_sha256=$(
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 -c 'import sys; from pathlib import Path; from run_oracle import _filesystem_tree_digest; print(_filesystem_tree_digest(Path(sys.argv[1])))' \
        "$dataset_dir"
)
[[ "$observed_dataset_tree_sha256" == "$dataset_tree_sha256" ]] \
    || { printf 'Dataset tree digest changed\n' >&2; exit 2; }
export OPENAI_API_KEY
OPENAI_API_KEY=$(tr -d '\r\n' <"$model_api_key_file")
[[ -n "$OPENAI_API_KEY" ]] || { printf 'Model API key file is empty\n' >&2; exit 2; }
model_http_status=$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' --max-time 30 \
    -H "Authorization: Bearer $OPENAI_API_KEY" "$base_url/models" || true)
[[ "$model_http_status" == 200 ]] \
    || { printf 'Configured model endpoint is unavailable (HTTP %s)\n' "$model_http_status" >&2; exit 2; }
export PRIME_RL_OUTPUT_DIR="$output_dir"
pool_socket_dir="${SLURM_TMPDIR:-/tmp}/oci-runner-pool-$(id -u)"
install -d -m 700 "$pool_socket_dir"
export OCI_RUNNER_POOL_SOCKET="$pool_socket_dir/${SLURM_JOB_ID}.sock"
export OCI_RUNNER_POOL_WAL="$output_dir/control/sandoq-pool.wal.jsonl"
export OCI_RUNNER_POOL_EVENT_LOG="$output_dir/pool_events.jsonl"
export OCI_RUNNER_BASE_URL=$SANDOQ_BASE_URL
export OCI_RUNNER_ECR_AUXILIARY_REGISTRIES=$FRONTIERBENCH_ECR_REGISTRY
printf -v OCI_RUNNER_ECR_AUXILIARY_TOKEN_FILES \
    '{"%s":"%s"}' "$FRONTIERBENCH_ECR_REGISTRY" "$SANDOQ_DEVELOPMENT_ECR_TOKEN_FILE"
export OCI_RUNNER_ECR_AUXILIARY_TOKEN_FILES

pool_capacity=$((max_concurrent * 2))
(( pool_capacity > SANDOQ_POOL_MAX )) && pool_capacity=$SANDOQ_POOL_MAX
lease_create_cap=$SANDOQ_LEASE_CREATE_CAP
(( lease_create_cap > pool_capacity )) && lease_create_cap=$pool_capacity
step_limit=$MODEL_FULL_STEP_LIMIT
environment_timeout=36000
model_timeout=43200
if [[ "$run_mode" == smoke ]]; then
    step_limit=$MODEL_SMOKE_STEP_LIMIT
    environment_timeout=$MODEL_SMOKE_ROLLOUT_TIMEOUT_SECONDS
    model_timeout=$MODEL_SMOKE_ROLLOUT_TIMEOUT_SECONDS
fi
harness_overrides=(
    "agent.step_limit=$step_limit"
    "environment.environment_class=local"
    "environment.timeout=$environment_timeout"
    "model.cost_tracking=ignore_errors"
    "model.model_kwargs.drop_params=true"
    "model.model_kwargs.timeout=$model_timeout"
    "model.model_kwargs.parallel_tool_calls=false"
)
runtime_override="$output_dir/runtime-overrides.toml"
{
    printf 'max_turns = %s\n\n[harness]\nconfig_overrides = [\n' "$step_limit"
    for override in "${harness_overrides[@]}"; do
        printf '  "%s",\n' "$override"
    done
    printf ']\n'
    if [[ "$run_mode" == smoke ]]; then
        printf '\n[harness.runtime]\nsession_timeout = %s\n' "$MODEL_SMOKE_SESSION_TIMEOUT_SECONDS"
        printf '\n[timeout]\nsetup = %s\nrollout = %s\nfinalize = %s\nscoring = %s\n' \
            "$MODEL_SMOKE_SETUP_TIMEOUT_SECONDS" "$MODEL_SMOKE_ROLLOUT_TIMEOUT_SECONDS" \
            "$MODEL_SMOKE_FINALIZE_TIMEOUT_SECONDS" "$MODEL_SMOKE_SCORING_TIMEOUT_SECONDS"
    fi
} >"$runtime_override"
chmod 600 "$runtime_override"
eval_command=(
    "$x86_uv" run --no-project --offline --python "$python_bin"
    python3 -c 'from verifiers.v1.cli.eval.main import main; main()'
    @ "$config" @ "$runtime_override" --output-dir "$output_dir"
    --model "$model" --num-tasks "$task_count" --max-concurrent "$max_concurrent"
    --multiplex "$max_concurrent" --client.base-url "$base_url"
    --max-input-tokens "$MODEL_MAX_CONTEXT_TOKENS"
    --max-output-tokens "$MODEL_MAX_CONTEXT_TOKENS"
    --max-total-tokens "$MODEL_MAX_CONTEXT_TOKENS"
    --sampling.max-tokens "$MODEL_MAX_GENERATION_TOKENS"
    --sampling.reasoning-effort "$reasoning_effort"
    --taskset.dataset-dir "$dataset_dir"
    --taskset.task-file "$task_file" --taskset.task-file-sha256 "$task_file_sha256"
    --taskset.image-manifest "$manifest" --taskset.image-manifest-sha256 "$manifest_sha256"
)
if [[ ${FRONTIERBENCH_MODEL_IN_PROVIDER:-0} == 1 ]]; then
    set +e
    "${eval_command[@]}"
    eval_status=$?
    set -e
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/sandoq_pool_cleanup.py" \
        --output-dir "$output_dir" --base-url "$OCI_RUNNER_BASE_URL" --owner "$SANDOQ_OWNER" \
        --concurrency "$OCI_RUNNER_POOL_DRAIN_WORKERS"
    exit "$eval_status"
fi

set +e
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" supervise \
    --profile "$provider_profile" --profile-sha256 "$provider_profile_sha256" \
    --concurrency "$pool_capacity" --lease-create-cap "$lease_create_cap" \
    --startup-timeout-seconds "$SANDOQ_STARTUP_TIMEOUT_SECONDS" \
    --lease-profile "$SANDOQ_MODEL_LEASE_PROFILE" \
    --ecr-token-file "$SANDOQ_PRODUCTION_ECR_TOKEN_FILE" \
    --ecr-token-metadata "$SANDOQ_PRODUCTION_ECR_TOKEN_METADATA" \
    --project-root "$project_dir" --sandoq-site "$sandoq_site" -- \
    env FRONTIERBENCH_MODEL_IN_PROVIDER=1 bash "$script_dir/launch_model.sh" "$model_kind" "$run_mode"
eval_status=$?
set -e
printf 'model_job=%s model=%s tasks=%s output=%s exit=%s\n' \
    "$SLURM_JOB_ID" "$model_kind" "$task_count" "$output_dir" "$eval_status"
exit "$eval_status"
