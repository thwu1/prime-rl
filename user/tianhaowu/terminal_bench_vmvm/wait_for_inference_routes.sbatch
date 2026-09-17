#!/bin/bash
#SBATCH --job-name=k3-route-gate
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=7-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/route_gate_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/route_gate_%j.log

set -euo pipefail
umask 077

if [[ -z ${DEPLOYMENT_ID:-} ]]; then
    printf 'DEPLOYMENT_ID is required\n' >&2
    exit 2
fi
if [[ -z ${EXPECTED_SPEC_SHA256:-} ]]; then
    printf 'EXPECTED_SPEC_SHA256 is required\n' >&2
    exit 2
fi
if [[ ! $EXPECTED_SPEC_SHA256 =~ ^[0-9a-f]{64}$ ]]; then
    printf 'EXPECTED_SPEC_SHA256 must be 64 lowercase hexadecimal characters\n' >&2
    exit 2
fi
if (( $# != 0 )); then
    printf 'Configure the route gate through environment variables, not positional arguments\n' >&2
    exit 2
fi

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
waiter=${WAITER_SCRIPT:-$workflow_dir/wait_for_inference_routes.py}
gate_output=${GATE_OUTPUT:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/gates/${DEPLOYMENT_ID}_${SLURM_JOB_ID:-manual}.json}

if [[ ! -r $waiter ]]; then
    printf 'Readiness waiter is not readable: %s\n' "$waiter" >&2
    exit 2
fi

# Direct same-cluster traffic is mandatory. Remove standard and custom proxy
# variables case-insensitively before Python starts; the waiter repeats this
# sanitization for both of its child processes.
while IFS= read -r variable_name; do
    if [[ ${variable_name,,} == *_proxy ]]; then
        unset "$variable_name"
    fi
done < <(compgen -e)

args=(
    "$DEPLOYMENT_ID"
    --expected-spec-sha256 "$EXPECTED_SPEC_SHA256"
    --expected-routes "${EXPECTED_ROUTES:-24}"
    --model "${MODEL:-Kimi-K3}"
    --output "$gate_output"
    --consecutive-polls "${CONSECUTIVE_POLLS:-3}"
    --max-status-unavailable "${MAX_STATUS_UNAVAILABLE:-10}"
    --poll-interval "${POLL_INTERVAL:-60}"
    --wait-timeout "${WAIT_TIMEOUT:-594000}"
    --status-command-timeout "${STATUS_COMMAND_TIMEOUT:-30}"
    --probe-process-timeout "${PROBE_PROCESS_TIMEOUT:-7200}"
    --probe-repeats "${PROBE_REPEATS:-3}"
    --probe-request-timeout "${PROBE_REQUEST_TIMEOUT:-300}"
    --probe-health-timeout "${PROBE_HEALTH_TIMEOUT:-30}"
    --probe-max-tokens "${PROBE_MAX_TOKENS:-4096}"
    --repeated-char-threshold "${REPEATED_CHAR_THRESHOLD:-8}"
)

if [[ -n ${PROBE_REQUESTS:-} ]]; then
    args+=(--probe-requests "$PROBE_REQUESTS")
fi
if [[ -n ${PROBE_CONCURRENCY:-} ]]; then
    args+=(--probe-concurrency "$PROBE_CONCURRENCY")
fi
if [[ -n ${SERVE_SH_PATH:-} ]]; then
    args+=(--serve-sh "$SERVE_SH_PATH")
fi
if [[ -n ${PROBE_SCRIPT_PATH:-} ]]; then
    args+=(--probe-script "$PROBE_SCRIPT_PATH")
fi
if [[ -n ${SPEC_PATH:-} ]]; then
    args+=(--spec "$SPEC_PATH")
fi
if [[ -n ${PROXY_INFO_PATH:-} ]]; then
    args+=(--proxy-info "$PROXY_INFO_PATH")
fi

export PYTHONUNBUFFERED=1
export PYTHONPATH="$workflow_dir:$x86_site${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$waiter" "${args[@]}"
