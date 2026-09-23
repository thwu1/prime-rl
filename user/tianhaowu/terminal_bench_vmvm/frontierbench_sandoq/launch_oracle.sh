#!/usr/bin/env bash
set -euo pipefail
umask 077

mode=${1:-full}
[[ "$mode" == smoke || "$mode" == full ]] || { printf 'usage: %s [smoke|full]\n' "$0" >&2; exit 2; }

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(cd -- "$script_dir/../../../.." && pwd)
set -a
source "$script_dir/frontierbench.env"
set +a

for value in "$FRONTIERBENCH_EXPECTED_TASKS" "$FRONTIERBENCH_BUILD_WORKERS" \
    "$FRONTIERBENCH_SMOKE_BUILD_WORKERS" \
    "$FRONTIERBENCH_ORACLE_CONCURRENCY" "$FRONTIERBENCH_ORACLE_TIMEOUT_SECONDS" \
    "$FRONTIERBENCH_ORACLE_MINIMUM_VALID" \
    "$SANDOQ_POOL_MAX" "$SANDOQ_LEASE_CREATE_CAP" "$SANDOQ_STARTUP_TIMEOUT_SECONDS" \
    "$SANDOQ_TASK_MAX_CPUS" "$SANDOQ_TASK_MAX_MEMORY_MB" "$SANDOQ_TASK_MAX_STORAGE_MB" \
    "$FRONTIERBENCH_SANDOQ_RUNNABLE_TASKS"; do
    [[ "$value" =~ ^[1-9][0-9]*$ ]] \
        || { printf 'Configured counts and timeouts must be positive integers\n' >&2; exit 2; }
done
[[ "$FRONTIERBENCH_ORACLE_MINIMUM_PASS_RATE" =~ ^(0(\.[0-9]+)?|1(\.0+)?)$ ]] \
    || { printf 'Oracle pass-rate gate must be between zero and one\n' >&2; exit 2; }
[[ "$FRONTIERBENCH_RUN_VARIANT" =~ ^[A-Za-z0-9._-]+$ ]] \
    || { printf 'Run variant must be a safe path component\n' >&2; exit 2; }
[[ "$FRONTIERBENCH_ENFORCE_FULL_RESOURCE_GATE" == 0 \
    || "$FRONTIERBENCH_ENFORCE_FULL_RESOURCE_GATE" == 1 ]] \
    || { printf 'Full resource gate must be 0 or 1\n' >&2; exit 2; }

dataset_dir=$FRONTIERBENCH_DATASET_DIR
dataset_tree_sha256=$FRONTIERBENCH_DATASET_TREE_SHA256
expected_tasks=$FRONTIERBENCH_EXPECTED_TASKS
build_workers=$FRONTIERBENCH_BUILD_WORKERS
oracle_concurrency=$FRONTIERBENCH_ORACLE_CONCURRENCY
run_name=full
if [[ "$mode" == smoke ]]; then
    dataset_dir=$FRONTIERBENCH_SMOKE_DATASET_DIR
    dataset_tree_sha256=$FRONTIERBENCH_SMOKE_DATASET_TREE_SHA256
    expected_tasks=1
    build_workers=$FRONTIERBENCH_SMOKE_BUILD_WORKERS
    oracle_concurrency=1
    run_name=smoke
fi
source_revision=$(git -C "$project_dir" rev-parse --verify HEAD)
minimum_valid=$FRONTIERBENCH_ORACLE_MINIMUM_VALID
if [[ "$mode" == full && "$FRONTIERBENCH_ENFORCE_FULL_RESOURCE_GATE" == 1 \
    && "$FRONTIERBENCH_SANDOQ_RUNNABLE_TASKS" -lt "$minimum_valid" ]]; then
    printf 'Current Sandoq Firecracker envelope covers only %s/%s tasks; refusing a run that cannot meet the 90%% oracle gate\n' \
        "$FRONTIERBENCH_SANDOQ_RUNNABLE_TASKS" "$expected_tasks" >&2
    exit 2
fi

[[ -d "$dataset_dir" && ! -L "$dataset_dir" ]] || { printf 'Pinned dataset directory is unavailable\n' >&2; exit 2; }
[[ "$dataset_tree_sha256" =~ ^[0-9a-f]{64}$ ]] || { printf 'Pinned dataset tree digest is invalid\n' >&2; exit 2; }
for secret in "$SANDOQ_FIRECRACKER_TOKEN_FILE" "$SANDOQ_PRODUCTION_ECR_TOKEN_FILE" \
    "$SANDOQ_DEVELOPMENT_ECR_TOKEN_FILE"; do
    [[ -f "$secret" && ! -L "$secret" && "$(stat -c '%a:%u:%h' -- "$secret")" == "600:$(id -u):1" ]] \
        || { printf 'A required owner-only token file is unavailable\n' >&2; exit 2; }
done
[[ -f "$SANDOQ_PRODUCTION_ECR_TOKEN_METADATA" && ! -L "$SANDOQ_PRODUCTION_ECR_TOKEN_METADATA" ]] \
    || { printf 'The ECR rotation metadata file is unavailable\n' >&2; exit 2; }
[[ -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]] \
    || { printf 'Prime-RL checkout must be clean\n' >&2; exit 2; }

task_count=$(find "$dataset_dir" -mindepth 1 -maxdepth 1 -type d -exec test -f '{}/task.toml' ';' -printf '.\n' | wc -l)
security_matches=$(find "$dataset_dir" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
    | awk -v pattern="$FRONTIERBENCH_EXCLUDED_NAME_PATTERN" \
        'BEGIN{IGNORECASE=1} $0 ~ pattern {n++} END{print n+0}')
if [[ "$task_count" != "$expected_tasks" || "$security_matches" != 0 ]]; then
    printf 'Dataset eligibility check failed (count or excluded-category boundary)\n' >&2
    exit 2
fi

run_root="$FRONTIERBENCH_RUN_ROOT/$run_name"
plan="$run_root/build-plan.jsonl"
plan_tsv="$run_root/build-plan.tsv"
status_root="$FRONTIERBENCH_RUN_ROOT/build-status"
manifest="$FRONTIERBENCH_RUN_ROOT/${run_name}-image-manifest.json"
oracle_output="$FRONTIERBENCH_RUN_ROOT/oracle-${run_name}-${FRONTIERBENCH_RUN_VARIANT}-${source_revision:0:12}"
install -d -m 700 "$run_root" "$status_root"

"$UV_BIN_LOGIN" run --no-project --offline python \
    "$project_dir/user/tianhaowu/terminal_bench_vmvm/prepare_build_plan.py" \
    --dataset-dir "$dataset_dir" --output "$plan" \
    --image-prefix "$FRONTIERBENCH_IMAGE_REPOSITORY" --image-tag "$FRONTIERBENCH_IMAGE_TAG" \
    --single-repository >/dev/null
chmod 600 "$plan" "$plan_tsv"
build_rows=$(awk 'NF{n++} END{print n+0}' "$plan_tsv")
(( build_rows > 0 )) || { printf 'Build plan is empty\n' >&2; exit 2; }
(( build_workers > build_rows )) && build_workers=$build_rows

if ! "$UV_BIN_LOGIN" run --no-project --offline python \
    "$project_dir/user/tianhaowu/terminal_bench_vmvm/finalize_ecr_image_manifest.py" \
    --plan "$plan_tsv" --status-root "$status_root" --output "$manifest" >/dev/null 2>&1; then
    build_job=$(
        env PROJECT_DIR="$project_dir" DATASET_DIR="$dataset_dir" BUILD_STATUS_ROOT="$status_root" \
            SANDOQ_BUILD_TOKEN_FILE="$SANDOQ_FIRECRACKER_TOKEN_FILE" \
            ECR_PUSH_TOKEN_FILE="$SANDOQ_DEVELOPMENT_ECR_TOKEN_FILE" \
        sbatch --parsable --array="0-$((build_workers - 1))%$build_workers" \
            "$project_dir/user/tianhaowu/terminal_bench_vmvm/build_images_sandoq.sbatch" "$plan_tsv"
    )
    printf 'image_build_job=%s rows=%s workers=%s\n' "$build_job" "$build_rows" "$build_workers"
    while squeue -h -j "$build_job" | grep -q .; do sleep 20; done
    if sacct -j "$build_job" -X -n -P -o State | grep -Ev '^(COMPLETED|)$' | grep -q .; then
        printf 'Sandoq image build did not complete successfully: %s\n' "$build_job" >&2
        exit 1
    fi
    "$UV_BIN_LOGIN" run --no-project --offline python \
        "$project_dir/user/tianhaowu/terminal_bench_vmvm/finalize_ecr_image_manifest.py" \
        --plan "$plan_tsv" --status-root "$status_root" --output "$manifest" >/dev/null
fi

manifest_sha256=$(sha256sum "$manifest" | cut -d' ' -f1)
if [[ "$mode" == smoke ]]; then minimum_valid=1; fi
job_id=$(
    env PROJECT_DIR="$project_dir" SANDBOX_PROVIDER=sandoq \
        DATASET_DIR="$dataset_dir" DATASET_TREE_SHA256="$dataset_tree_sha256" \
        IMAGE_PREFIX="$FRONTIERBENCH_IMAGE_REPOSITORY" IMAGE_TAG="$FRONTIERBENCH_IMAGE_TAG" \
        IMAGE_MANIFEST="$manifest" IMAGE_MANIFEST_SHA256="$manifest_sha256" \
        USE_DECLARED_IMAGES=1 MAX_CONCURRENT="$oracle_concurrency" \
        INFRA_RETRIES=2 SETUP_TIMEOUT=3600 VALIDATE_TIMEOUT="$FRONTIERBENCH_ORACLE_TIMEOUT_SECONDS" \
        SESSION_TIMEOUT="$FRONTIERBENCH_ORACLE_TIMEOUT_SECONDS" \
        MINIMUM_PASS_RATE="$FRONTIERBENCH_ORACLE_MINIMUM_PASS_RATE" MINIMUM_VALID="$minimum_valid" \
        ORACLE_SOLUTION_NETWORK_MODE=declared OUTPUT_DIR="$oracle_output" RERUN_INVALID=1 \
        OCI_RUNNER_ECR_TOKEN_FILE="$SANDOQ_PRODUCTION_ECR_TOKEN_FILE" \
        OCI_RUNNER_ECR_TOKEN_METADATA_PATH="$SANDOQ_PRODUCTION_ECR_TOKEN_METADATA" \
        SANDOQ_PROVIDER_CONTEXT_PROFILE="$project_dir/$SANDOQ_ORACLE_PROVIDER_PROFILE" \
        SANDOQ_PROVIDER_CONTEXT_PROFILE_SHA256="$SANDOQ_ORACLE_PROVIDER_PROFILE_SHA256" \
        OCI_RUNNER_ECR_AUXILIARY_REGISTRIES="$FRONTIERBENCH_ECR_REGISTRY" \
        OCI_RUNNER_ECR_AUXILIARY_TOKEN_FILE="$SANDOQ_DEVELOPMENT_ECR_TOKEN_FILE" \
    sbatch --parsable "$project_dir/user/tianhaowu/terminal_bench_vmvm/run_oracle.sbatch"
)
printf 'oracle_job=%s mode=%s tasks=%s output=%s\n' "$job_id" "$mode" "$expected_tasks" "$oracle_output"
