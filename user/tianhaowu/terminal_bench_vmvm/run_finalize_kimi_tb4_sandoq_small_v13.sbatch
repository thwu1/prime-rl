#!/usr/bin/bash -p
#SBATCH --job-name=k3-tb4-v13-final
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_v13_finalize_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_v13_finalize_%j.log

set +x
set -euo pipefail
umask 077

blocked() {
    printf '{"code":"%s","state":"blocked"}\n' "$1" >&2
    exit 2
}

expected_producer_job=1618064
execution_revision=3a39b16535d4f77ba16336086441373756e29eda
expected_verifiers_revision=36b0dff6c18affb3d40b7c46d5836381d568050b
execution_project_dir=/storage/home/tianhaowu/prime-kimi-tb4-v13-finalizer-1617454
plan=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/kimi-tb4-small-v10-c16-plans-20260928/plan-p0-v4-3a39b165-r2/launch-plan.json
plan_sha256=41fc96375ca18a1e1004a4b327953c25090df5539a80da347e85b2e6a00848b6
run_dir=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4-kimi-stock1-c16-v10-p0-v4-3a39b165-r2-miniswe246-sandoq-firecracker-small
x86_uv=/storage/home/tianhaowu/.local/x86_64/bin/uv
x86_site=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64

[[ "$#" -eq 1 && "$1" == "$expected_producer_job" ]] \
    || blocked producer_job_argument_invalid
[[ "${KIMI_V13_EXPECTED_PRODUCER_JOB_ID:-}" == "$expected_producer_job" ]] \
    || blocked producer_job_environment_invalid
: "${KIMI_V13_SUPERSESSION_SOURCE_REVISION:?Set KIMI_V13_SUPERSESSION_SOURCE_REVISION}"
project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"

[[ -z "$(squeue -h -j "$expected_producer_job")" ]] || blocked producer_not_terminal
producer_record=$(sacct -X -j "$expected_producer_job" -n -P -o JobIDRaw,State,ExitCode)
IFS='|' read -r producer_job producer_state producer_exit producer_extra <<< "$producer_record"
[[ -z "$producer_extra" && "$producer_record" != *$'\n'* \
    && "$producer_job" == "$expected_producer_job" \
    && "$producer_state" =~ ^(COMPLETED|FAILED|CANCELLED|TIMEOUT|NODE_FAIL|OUT_OF_MEMORY|PREEMPTED|BOOT_FAIL|DEADLINE)$ \
    && "$producer_exit" =~ ^[0-9]+:[0-9]+$ ]] || blocked producer_terminal_state_invalid

[[ -d "$project_dir/.git" || -f "$project_dir/.git" ]] || blocked supersession_source_missing
[[ "$(git -C "$project_dir" rev-parse HEAD)" == "$KIMI_V13_SUPERSESSION_SOURCE_REVISION" \
    && -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]] \
    || blocked supersession_source_identity_invalid
[[ "$(git -C "$project_dir/deps/verifiers" rev-parse HEAD)" == "$expected_verifiers_revision" \
    && -z "$(git -C "$project_dir/deps/verifiers" status --porcelain=v1 --untracked-files=all)" ]] \
    || blocked supersession_verifiers_identity_invalid
[[ -d "$execution_project_dir/.git" || -f "$execution_project_dir/.git" ]] \
    || blocked execution_source_missing
[[ "$(git -C "$execution_project_dir" rev-parse HEAD)" == "$execution_revision" \
    && -z "$(git -C "$execution_project_dir" status --porcelain=v1 --untracked-files=all)" ]] \
    || blocked execution_source_identity_invalid
[[ "$(git -C "$execution_project_dir/deps/verifiers" rev-parse HEAD)" == "$expected_verifiers_revision" \
    && -z "$(git -C "$execution_project_dir/deps/verifiers" status --porcelain=v1 --untracked-files=all)" ]] \
    || blocked execution_verifiers_identity_invalid
[[ -x "$x86_uv" && -d "$x86_site" ]] || blocked x86_runtime_invalid
[[ -f "$plan" && ! -L "$plan" \
    && "$(stat -c '%a:%h:%u' -- "$plan")" == "600:1:$(id -u)" \
    && "$(sha256sum -- "$plan" | cut -d' ' -f1)" == "$plan_sha256" ]] \
    || blocked launch_plan_invalid
[[ -d "$run_dir" && ! -L "$run_dir" \
    && "$(stat -c '%a:%u' -- "$run_dir")" == "700:$(id -u)" ]] \
    || blocked run_directory_invalid
[[ ! -e "$run_dir/full-denominator-supersession-v13" \
    && ! -L "$run_dir/full-denominator-supersession-v13" ]] \
    || blocked v13_output_not_fresh

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site"
exec "$x86_uv" run --no-project --offline --python python3 \
    python3 "$workflow_dir/finalize_kimi_tb4_sandoq_small_v13.py" \
    --plan "$plan" --plan-sha256 "$plan_sha256" \
    --run-dir "$run_dir" \
    --supersession-source-revision "$KIMI_V13_SUPERSESSION_SOURCE_REVISION" \
    --execution-slurm-job-id "$expected_producer_job"
