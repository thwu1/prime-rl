#!/usr/bin/env bash
set -euo pipefail
umask 077

mode=${1:-prepare}
[[ "$mode" == prepare || "$mode" == launch ]] \
    || { printf 'usage: %s [prepare|launch]\n' "$0" >&2; exit 2; }

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(cd -- "$script_dir/../../../.." && pwd)
set -a
source "$script_dir/frontierbench.env"
set +a

source_revision=$(git -C "$project_dir" rev-parse --verify HEAD)
[[ -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]] \
    || { printf 'Prime-RL checkout must be clean\n' >&2; exit 2; }
[[ -d "$FRONTIERBENCH_DATASET_DIR" && ! -L "$FRONTIERBENCH_DATASET_DIR" ]] \
    || { printf 'Pinned dataset directory is unavailable\n' >&2; exit 2; }

subset_root="$FRONTIERBENCH_RUN_ROOT/oracle-subset-$FRONTIERBENCH_SUBSET_VARIANT"
plan="$FRONTIERBENCH_RUN_ROOT/full/build-plan.tsv"
status_root="$FRONTIERBENCH_RUN_ROOT/build-status"
task_file="$subset_root/tasks.txt"
manifest="$subset_root/image-manifest.json"
receipt="$subset_root/materialization.json"
install -d -m 700 "$subset_root"

"$UV_BIN_LOGIN" run --no-project --offline python \
    "$project_dir/user/tianhaowu/terminal_bench_vmvm/materialize_sandoq_oracle_subset.py" \
    --plan "$plan" --status-root "$status_root" --dataset-dir "$FRONTIERBENCH_DATASET_DIR" \
    --task-file "$task_file" --manifest "$manifest" --receipt "$receipt" \
    --excluded-name-pattern "$FRONTIERBENCH_EXCLUDED_NAME_PATTERN" \
    --dataset-tree-sha256 "$FRONTIERBENCH_DATASET_TREE_SHA256" \
    --expected-tasks "$FRONTIERBENCH_EXPECTED_TASKS" \
    --expected-plan-rows "$FRONTIERBENCH_SUBSET_EXPECTED_PLAN_ROWS" \
    --expected-strict-images "$FRONTIERBENCH_SUBSET_EXPECTED_STRICT_IMAGES" \
    --expected-selected "$FRONTIERBENCH_SUBSET_EXPECTED_TASKS" \
    --expected-incomplete "$FRONTIERBENCH_SUBSET_EXPECTED_INCOMPLETE" \
    --expected-compose "$FRONTIERBENCH_COMPOSE_TASKS" \
    --minimum-selected "$FRONTIERBENCH_ORACLE_MINIMUM_VALID" >/dev/null

task_file_sha256=$(sha256sum "$task_file" | cut -d' ' -f1)
manifest_sha256=$(sha256sum "$manifest" | cut -d' ' -f1)
receipt_sha256=$(sha256sum "$receipt" | cut -d' ' -f1)
printf 'subset_ready tasks=%s task_file_sha256=%s manifest_sha256=%s receipt_sha256=%s\n' \
    "$FRONTIERBENCH_SUBSET_EXPECTED_TASKS" "$task_file_sha256" "$manifest_sha256" "$receipt_sha256"

if [[ "$mode" == prepare ]]; then
    printf 'launch_command=cd %s && bash %s launch\n' "$project_dir" \
        "user/tianhaowu/terminal_bench_vmvm/frontierbench_sandoq/launch_oracle_subset.sh"
    exit 0
fi

for secret in "$SANDOQ_FIRECRACKER_TOKEN_FILE" "$SANDOQ_PRODUCTION_ECR_TOKEN_FILE" \
    "$SANDOQ_DEVELOPMENT_ECR_TOKEN_FILE"; do
    [[ -f "$secret" && ! -L "$secret" && "$(stat -c '%a:%u:%h' -- "$secret")" == "600:$(id -u):1" ]] \
        || { printf 'A required owner-only token file is unavailable\n' >&2; exit 2; }
done
[[ -f "$SANDOQ_PRODUCTION_ECR_TOKEN_METADATA" && ! -L "$SANDOQ_PRODUCTION_ECR_TOKEN_METADATA" ]] \
    || { printf 'The ECR rotation metadata file is unavailable\n' >&2; exit 2; }

oracle_output="$FRONTIERBENCH_RUN_ROOT/oracle-subset-$FRONTIERBENCH_SUBSET_VARIANT-${source_revision:0:12}"
job_id=$(
    env PROJECT_DIR="$project_dir" SANDBOX_PROVIDER=sandoq \
        DATASET_DIR="$FRONTIERBENCH_DATASET_DIR" \
        DATASET_TREE_SHA256="$FRONTIERBENCH_DATASET_TREE_SHA256" \
        TASK_FILE="$task_file" TASK_FILE_SHA256="$task_file_sha256" \
        IMAGE_PREFIX="$FRONTIERBENCH_IMAGE_REPOSITORY" IMAGE_TAG="$FRONTIERBENCH_IMAGE_TAG" \
        IMAGE_MANIFEST="$manifest" IMAGE_MANIFEST_SHA256="$manifest_sha256" \
        USE_DECLARED_IMAGES=1 MAX_CONCURRENT="$FRONTIERBENCH_ORACLE_CONCURRENCY" \
        TASK_RESOURCE_CPU_CAP="$SANDOQ_TASK_MAX_CPUS" \
        TASK_RESOURCE_MEMORY_MB_CAP="$SANDOQ_TASK_MAX_MEMORY_MB" \
        TASK_RESOURCE_STORAGE_MB_CAP="$SANDOQ_TASK_MAX_STORAGE_MB" \
        INFRA_RETRIES=2 SETUP_TIMEOUT=3600 VALIDATE_TIMEOUT="$FRONTIERBENCH_ORACLE_TIMEOUT_SECONDS" \
        SESSION_TIMEOUT="$FRONTIERBENCH_ORACLE_TIMEOUT_SECONDS" \
        MINIMUM_PASS_RATE="$FRONTIERBENCH_ORACLE_MINIMUM_PASS_RATE" \
        MINIMUM_VALID="$FRONTIERBENCH_ORACLE_MINIMUM_VALID" \
        ORACLE_SOLUTION_NETWORK_MODE=declared OUTPUT_DIR="$oracle_output" RERUN_INVALID=1 \
        OCI_RUNNER_ECR_TOKEN_FILE="$SANDOQ_PRODUCTION_ECR_TOKEN_FILE" \
        OCI_RUNNER_ECR_TOKEN_METADATA_PATH="$SANDOQ_PRODUCTION_ECR_TOKEN_METADATA" \
        SANDOQ_PROVIDER_CONTEXT_PROFILE="$project_dir/$SANDOQ_ORACLE_PROVIDER_PROFILE" \
        SANDOQ_PROVIDER_CONTEXT_PROFILE_SHA256="$SANDOQ_ORACLE_PROVIDER_PROFILE_SHA256" \
        OCI_RUNNER_ECR_AUXILIARY_REGISTRIES="$FRONTIERBENCH_ECR_REGISTRY" \
        OCI_RUNNER_ECR_AUXILIARY_TOKEN_FILE="$SANDOQ_DEVELOPMENT_ECR_TOKEN_FILE" \
    sbatch --parsable "$project_dir/user/tianhaowu/terminal_bench_vmvm/run_oracle.sbatch"
)
printf 'oracle_job=%s mode=subset tasks=%s output=%s\n' \
    "$job_id" "$FRONTIERBENCH_SUBSET_EXPECTED_TASKS" "$oracle_output"
