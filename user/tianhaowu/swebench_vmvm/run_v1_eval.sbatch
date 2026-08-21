#!/bin/bash
#SBATCH --job-name=swebench-vmvm
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=128G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/swebench_vmvm/logs/eval_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/swebench_vmvm/logs/eval_%j.log

set -euo pipefail

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
eval_config=${EVAL_CONFIG:-user/tianhaowu/swebench_vmvm/mini_swe_smoke.toml}
resume_dir=${RESUME_DIR:-}
resume_run_id=${RESUME_RUN_ID:-$SLURM_JOB_ID}
if [ -n "$resume_dir" ]; then
    output_dir=$resume_dir
else
    output_dir=${OUTPUT_DIR:-/checkpoint/ram/tianhaowu/swebench_vmvm/evals/run_${SLURM_JOB_ID}}
fi
inference_base_url=${INFERENCE_BASE_URL:-}
eval_model=${EVAL_MODEL:-}
vmvm_lease_ttl=${VMVM_LEASE_TTL:-}

if [ -z "$inference_base_url" ]; then
    : "${INFERENCE_JOB_ID:?Set INFERENCE_JOB_ID or INFERENCE_BASE_URL}"
    inference_nodes=$(squeue -h -j "$INFERENCE_JOB_ID" -t RUNNING -o '%N')
    if [ -z "$inference_nodes" ]; then
        echo "Inference job $INFERENCE_JOB_ID is not running" >&2
        exit 1
    fi
    inference_host=$(scontrol show hostnames "$inference_nodes" | head -n 1)
    inference_base_url="http://${inference_host}:8000/v1"
fi

mkdir -p "$output_dir" /checkpoint/ram/tianhaowu/swebench_vmvm/logs
exec 9>"$output_dir/.writer.lock"
if ! flock -n 9; then
    printf 'Another evaluator already owns output directory: %s\n' "$output_dir" >&2
    exit 1
fi
if [ -z "$resume_dir" ] && [ -e "$output_dir/results.jsonl" ]; then
    printf 'Refusing to overwrite existing results: %s/results.jsonl\n' "$output_dir" >&2
    exit 1
fi
cd "$project_dir"

if [ -z "$resume_dir" ]; then
    implementation_roots=(
        user/tianhaowu/swebench_vmvm
        environments/vmvm_tb_v2/vmvm_tb_v2
        deps/verifiers/verifiers/v1
        deps/research-environments/environments/swebench_verified_v1/swebench_verified_v1
    )
    for root in "${implementation_roots[@]}"; do
        if [ ! -d "$root" ]; then
            printf 'Implementation source directory is missing: %s\n' "$root" >&2
            exit 1
        fi
    done
    mapfile -d '' implementation_sources < <(
        find "${implementation_roots[@]}" -type f \
            ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 | sort -z
    )
    if [ "${#implementation_sources[@]}" -eq 0 ]; then
        printf 'No implementation sources found\n' >&2
        exit 1
    fi
    sha256sum "${implementation_sources[@]}" > "$output_dir/implementation.sha256.tmp"
    printf '%s\0' "${implementation_sources[@]}" | \
        tar --null --files-from=- --sort=name --mtime='UTC 1970-01-01' \
            --owner=0 --group=0 --numeric-owner \
            -czf "$output_dir/implementation.tar.gz.tmp"
    {
        printf 'prime_rl=%s\n' "$(git rev-parse HEAD)"
        printf 'verifiers=%s\n' "$(git -C deps/verifiers rev-parse HEAD)"
        printf 'research_environments=%s\n' "$(git -C deps/research-environments rev-parse HEAD)"
    } > "$output_dir/implementation_revisions.txt.tmp"
    mv "$output_dir/implementation.sha256.tmp" "$output_dir/implementation.sha256"
    mv "$output_dir/implementation.tar.gz.tmp" "$output_dir/implementation.tar.gz"
    mv "$output_dir/implementation_revisions.txt.tmp" "$output_dir/implementation_revisions.txt"
fi

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export OPENAI_API_KEY=EMPTY
export VACLI_LEASE_RETRIES=20
export VACLI_MAX_CONCURRENT_LEASES=${VACLI_MAX_CONCURRENT_LEASES:-16}
export VACLI_MAX_PULL_RETRIES=20
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=3600
export PYTHONPATH="$project_dir/user/tianhaowu/swebench_vmvm:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/research-environments/environments/swebench_verified_v1${PYTHONPATH:+:$PYTHONPATH}"

models_path="$output_dir/models.json"
if [ -n "$resume_dir" ]; then
    if [ ! -f "$resume_dir/config.toml" ]; then
        echo "Resume directory has no config.toml: $resume_dir" >&2
        exit 1
    fi
    models_path="$output_dir/models.resume_${resume_run_id}.json"
fi

curl --noproxy '*' --fail --silent --show-error --max-time 30 \
    "${inference_base_url%/v1}/v1/models" > "$models_path"

if [ -n "$resume_dir" ]; then
    uv run --no-sync user/tianhaowu/swebench_vmvm/update_resume_endpoint.py \
        "$resume_dir/config.toml" "$inference_base_url" "$resume_run_id"
    uv run --no-sync eval --resume "$resume_dir"
    exit 0
fi

args=(
    @ "$eval_config"
    --client.base-url "$inference_base_url"
    --output-dir "$output_dir"
)
if [ -n "$eval_model" ]; then
    args+=(--model "$eval_model")
fi
if [ -n "$vmvm_lease_ttl" ]; then
    args+=(--harness.runtime.lease-ttl "$vmvm_lease_ttl")
fi

uv run --no-sync eval "${args[@]}"
