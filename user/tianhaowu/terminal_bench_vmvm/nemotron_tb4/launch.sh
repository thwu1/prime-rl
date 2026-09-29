#!/bin/bash
#SBATCH --job-name=nemotron-tb4
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=48G
#SBATCH --time=2-00:00:00
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/nemotron_tb4_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/nemotron_tb4_%j.log
# Nemotron-3-Super TB4 eval on Sandoq (mini-swe-agent 2.4.6). Submit from the login node:
#   NEMOTRON_TB4_BASE_URL=http://host:port/v1 NEMOTRON_TB4_MODEL=<served name> \
#   NEMOTRON_TB4_TASK_FILE=<tasks.txt> NEMOTRON_TB4_RUN_NAME=<name> \
#   [NEMOTRON_TB4_MAX_CONCURRENT=8] [NEMOTRON_TB4_STEP_LIMIT=300] sbatch launch.sh
set -euo pipefail
umask 077

: "${NEMOTRON_TB4_BASE_URL:?}" "${NEMOTRON_TB4_MODEL:?}" "${NEMOTRON_TB4_TASK_FILE:?}" "${NEMOTRON_TB4_RUN_NAME:?}"
max_concurrent=${NEMOTRON_TB4_MAX_CONCURRENT:-8}
step_limit=${NEMOTRON_TB4_STEP_LIMIT:-300}
api_key_file=${NEMOTRON_TB4_API_KEY_FILE:-/storage/home/tianhaowu/.config/ram-inference-gateway/nemotron-probe-token}
[[ "$NEMOTRON_TB4_RUN_NAME" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "unsafe run name" >&2; exit 2; }
[[ "$(uname -m)" == x86_64 ]] || { echo "model runner requires x86_64" >&2; exit 2; }

project_dir=${NEMOTRON_TB4_PROJECT_DIR:-/storage/home/tianhaowu/prime-nemotron-sft-512k}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
config="$workflow_dir/nemotron_tb4/nemotron_tb4.toml"
output_dir="/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/nemotron_tb4/${NEMOTRON_TB4_RUN_NAME}-${SLURM_JOB_ID}"
install -d -m 700 "$output_dir" "$output_dir/control"

x86_uv=/storage/home/tianhaowu/.local/x86_64/bin/uv
x86_site=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64
sandoq_site=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_sdk1_82068
provider_profile="$workflow_dir/configs/provider_context/use2/kimi_sandoq_firecracker_host.json"
provider_profile_sha256=7dd88ca6c6cde5ed5b22bf8f621462a46425f939478f79469e31da2e582b27df
ecr_token_file=/storage/home/tianhaowu/.config/oci-runner/ecr-token
ecr_token_metadata=/storage/home/tianhaowu/.config/oci-runner/ecr-rotation.state.json

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
# Taskset paths (image manifest, task files) are relative to the project root.
cd "$project_dir"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/extensions/sandoq:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$sandoq_site:$x86_site"

task_file=$(realpath -e -- "$NEMOTRON_TB4_TASK_FILE")
task_count=$(awk 'NF{n++} END{print n+0}' "$task_file")
cp -- "$task_file" "$output_dir/tasks.txt"
git -C "$project_dir" rev-parse HEAD >"$output_dir/source_revision.txt"
git -C "$project_dir" status --porcelain=v1 >"$output_dir/source_status.txt"

if [[ ${NEMOTRON_TB4_IN_PROVIDER:-0} != 1 ]]; then
    pool_capacity=$((max_concurrent * 2)); (( pool_capacity > 64 )) && pool_capacity=64
    lease_create_cap=4; (( lease_create_cap > pool_capacity )) && lease_create_cap=$pool_capacity
    set +e
    "$x86_uv" run --no-project --offline --python python3 \
        python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" supervise \
        --profile "$provider_profile" --profile-sha256 "$provider_profile_sha256" \
        --concurrency "$pool_capacity" --lease-create-cap "$lease_create_cap" \
        --startup-timeout-seconds 3600 --lease-profile kimi-tb4-long \
        --ecr-token-file "$ecr_token_file" --ecr-token-metadata "$ecr_token_metadata" \
        --project-root "$project_dir" --sandoq-site "$sandoq_site" -- \
        env NEMOTRON_TB4_IN_PROVIDER=1 NEMOTRON_TB4_OUTPUT_DIR="$output_dir" bash "$workflow_dir/nemotron_tb4/launch.sh"
    status=$?
    set -e
    echo "nemotron_tb4 job=$SLURM_JOB_ID tasks=$task_count output=$output_dir exit=$status"
    exit "$status"
fi

output_dir=${NEMOTRON_TB4_OUTPUT_DIR:?}
export OPENAI_API_KEY
OPENAI_API_KEY=$(tr -d '\r\n' <"$api_key_file")
http_status=$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' --max-time 30 \
    -H "Authorization: Bearer $OPENAI_API_KEY" "$NEMOTRON_TB4_BASE_URL/models" || true)
[[ "$http_status" == 200 ]] || { echo "model endpoint unavailable (HTTP $http_status)" >&2; exit 2; }
export PRIME_RL_OUTPUT_DIR="$output_dir"
pool_socket_dir="${SLURM_TMPDIR:-/tmp}/oci-runner-pool-$(id -u)"
install -d -m 700 "$pool_socket_dir"
export OCI_RUNNER_POOL_SOCKET="$pool_socket_dir/${SLURM_JOB_ID}.sock"
export OCI_RUNNER_POOL_WAL="$output_dir/control/sandoq-pool.wal.jsonl"
export OCI_RUNNER_POOL_EVENT_LOG="$output_dir/pool_events.jsonl"
export OCI_RUNNER_BASE_URL=https://sandoq.eks-prod.cf.aws.metafb.cloud

set +e
"$x86_uv" run --no-project --offline --python python3 \
    python3 -c 'from verifiers.v1.cli.eval.main import main; main()' \
    @ "$config" --output-dir "$output_dir" \
    --model "$NEMOTRON_TB4_MODEL" --num-tasks "$task_count" \
    --max-concurrent "$max_concurrent" --multiplex "$max_concurrent" \
    --max-turns "$step_limit" \
    --client.base-url "$NEMOTRON_TB4_BASE_URL" \
    --taskset.task-file "$task_file" \
    --taskset.task-file-sha256 "$(sha256sum "$task_file" | cut -d' ' -f1)"
eval_status=$?
set -e
"$x86_uv" run --no-project --offline --python python3 \
    python3 "$workflow_dir/sandoq_pool_cleanup.py" \
    --output-dir "$output_dir" --base-url "$OCI_RUNNER_BASE_URL" --owner "$SANDOQ_OWNER" \
    --concurrency "${OCI_RUNNER_POOL_DRAIN_WORKERS:-8}" || true
exit "$eval_status"
