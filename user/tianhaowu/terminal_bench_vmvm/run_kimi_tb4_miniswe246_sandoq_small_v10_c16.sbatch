#!/usr/bin/bash -p
#SBATCH --job-name=k3-tb4-v10-c16
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=6-12:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=48G
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@1800
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_v10_c16_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_v10_c16_%j.log

set +x
set -euo pipefail
umask 077

blocked() {
    printf '{"code":"%s","state":"blocked"}\n' "$1" >&2
    exit 2
}

(( $# == 0 )) || blocked arguments_forbidden

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
export PROJECT_DIR="$project_dir"
export KIMI_SANDOQ_STAGE=tb4-miniswe246-sandoq-small-v10-c16
export KIMI_SANDBOX_PROVIDER=sandoq
export KIMI_EXECUTION_MODE=small-firecracker-v10
export KIMI_DIRECT_ROUTER_CAPACITY_PROFILE=sandoq-stock-single-c64-v1

: "${KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION:?Set KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION}"
: "${KIMI_TB4_V10_PLAN:?Set KIMI_TB4_V10_PLAN}"
: "${KIMI_TB4_V10_PLAN_SHA256:?Set KIMI_TB4_V10_PLAN_SHA256}"
[[ "${KIMI_TB4_V10_NO_CONCURRENT_SANDOQ_LOAD:-}" == 1 ]] \
    || blocked concurrent_sandoq_load_not_attested

exclusive_lock=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/terminal-bench-sandoq-campaign.lock
exec 7>>"$exclusive_lock"
flock -n 7 || blocked concurrent_sandoq_campaign

active_jobs=$(squeue -h -u "$(id -un)" -t RUNNING,PENDING,CONFIGURING,COMPLETING -o '%A|%j|%o') \
    || blocked sandoq_activity_check_unavailable
while IFS='|' read -r active_job_id active_job_name active_command active_extra; do
    [[ -z "$active_job_id" ]] && continue
    [[ -z "$active_extra" && -n "$active_job_name" && -n "$active_command" \
        && "$active_job_id" =~ ^[1-9][0-9]*$ ]] \
        || blocked sandoq_activity_check_invalid
    [[ "$active_job_id" == "$SLURM_JOB_ID" ]] && continue
    case "${active_job_name}|${active_command}" in
        *tb4*|*TB4*|*sandoq*|*Sandoq*|*SANDOQ*|*kimi2499*|*Kimi2499*|\
        *kimi-2499*|*Kimi-2499*|*stock_small*|*task-image*)
            blocked concurrent_sandoq_campaign
            ;;
    esac
done <<< "$active_jobs"

slurm_duration_seconds() {
    local value=$1 days=0 hours minutes seconds
    if [[ "$value" =~ ^([0-9]+)-([0-9]{1,2}):([0-9]{2}):([0-9]{2})$ ]]; then
        days=${BASH_REMATCH[1]}
        hours=${BASH_REMATCH[2]}
        minutes=${BASH_REMATCH[3]}
        seconds=${BASH_REMATCH[4]}
    elif [[ "$value" =~ ^([0-9]+):([0-9]{2}):([0-9]{2})$ ]]; then
        hours=${BASH_REMATCH[1]}
        minutes=${BASH_REMATCH[2]}
        seconds=${BASH_REMATCH[3]}
    else
        return 1
    fi
    printf '%s\n' "$(( 10#$days * 86400 + 10#$hours * 3600 + 10#$minutes * 60 + 10#$seconds ))"
}

minimum_job_remaining_seconds=558000
scheduler_walltime=$(squeue -h -j "${SLURM_JOB_ID:?}" -o '%L|%l|%e') \
    || blocked job_walltime_unavailable
IFS='|' read -r job_time_left job_time_limit job_end_time job_walltime_extra \
    <<< "$scheduler_walltime"
job_time_left_seconds=$(slurm_duration_seconds "$job_time_left") \
    || blocked job_walltime_invalid
job_time_limit_seconds=$(slurm_duration_seconds "$job_time_limit") \
    || blocked job_walltime_invalid
job_end_epoch=$(date -u -d "$job_end_time" +%s) || blocked job_walltime_invalid
if [[ -n "$job_walltime_extra" || "$scheduler_walltime" == *$'\n'* ]] \
    || (( job_time_left_seconds < minimum_job_remaining_seconds \
        || job_time_limit_seconds < minimum_job_remaining_seconds \
        || job_end_epoch - $(date +%s) < minimum_job_remaining_seconds )); then
    blocked job_walltime_insufficient
fi

exec /usr/bin/bash -p \
    "$project_dir/user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/"\
"cpu-132-021_8103/run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch"
