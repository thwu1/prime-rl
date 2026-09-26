#!/usr/bin/bash -p
#SBATCH --job-name=kimi-mswe246-fcsmall
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=00:10:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/kimi_mswe246_fcsmall_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/kimi_mswe246_fcsmall_%j.log

set +x
set -euo pipefail
umask 077

blocked() {
    printf '{"code":"%s","state":"blocked"}\n' "$1" >&2
    exit 2
}

(( $# == 0 )) || blocked arguments_forbidden

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
expected_revision=${KIMI_SMALL_CANARY_EXPECTED_REVISION:?Set KIMI_SMALL_CANARY_EXPECTED_REVISION}
deployment_root=${KIMI_SMALL_CANARY_DEPLOYMENT_ROOT:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/kimi-k3-deployment-cpu132021-rollover-20260924-v3}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_sdk1_82068}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
eval_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals
generation_dir="$eval_root/kimi_miniswe246_small_router_${SLURM_JOB_ID:?}"
output_root="$eval_root/kimi-miniswe246-sandoq-firecracker-small-canary"
deployment_snapshot="$generation_dir/deployment_source"
manifest="$generation_dir/direct_kimi_workers.json"
urls_file="$generation_dir/worker_urls.private.txt"
ports_file="$generation_dir/router_ports.private.txt"
router_log="$generation_dir/direct_router.log"
router_pid=

cleanup_router() {
    status=$?
    trap - EXIT INT TERM
    if [[ -n "$router_pid" ]] && kill -0 "$router_pid" 2>/dev/null; then
        kill -TERM -- "-$router_pid" 2>/dev/null || true
        wait "$router_pid" 2>/dev/null || true
    fi
    exit "$status"
}
trap cleanup_router EXIT INT TERM

[[ "$expected_revision" =~ ^[0-9a-f]{40}$ ]] || blocked source_identity_invalid
[[ "$(git -C "$project_dir" rev-parse HEAD)" == "$expected_revision" ]] \
    || blocked source_identity_invalid
[[ -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]] \
    || blocked source_identity_invalid
[[ -x "$x86_uv" && -d "$x86_site/pydantic" && -d "$sandoq_site/sandoq_client" ]] \
    || blocked runtime_unavailable
[[ -d "$deployment_root" && ! -L "$deployment_root" ]] || blocked deployment_unavailable
[[ ! -e "$generation_dir" && ! -L "$generation_dir" ]] || blocked output_namespace_not_fresh
if [[ -e "$output_root/run-${SLURM_JOB_ID}" || -L "$output_root/run-${SLURM_JOB_ID}" ]]; then
    blocked output_namespace_not_fresh
fi

mkdir -m 0700 -- "$generation_dir"
touch "$router_log"
chmod 0600 "$router_log"

while IFS= read -r variable_name; do
    [[ ${variable_name,,} == *_proxy ]] && unset "$variable_name"
done < <(compgen -e)
unset OPENAI_API_KEY FIRECRACKER_KEY SANDOQ_AUTH_TOKEN
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${SLURM_TMPDIR:-/tmp}/kimi-small-canary-pycache-${SLURM_JOB_ID}"
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site"

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" snapshot-source \
    --deployment-root "$deployment_root" --output-root "$deployment_snapshot" >/dev/null

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" prepare \
    --deployment-root "$deployment_snapshot" \
    --output-root "$generation_dir" \
    --manifest "$manifest" \
    --urls-output "$urls_file" \
    --ports-output "$ports_file" \
    --capacity-profile sandoq-c64-w2-v1 \
    --endpoint-identifier cpu-132-021_8103 \
    --probe

mapfile -t worker_urls < "$urls_file"
mapfile -t router_ports < "$ports_file"
[[ ${#worker_urls[@]} -eq 24 && ${#router_ports[@]} -eq 2 ]] \
    || blocked router_generation_invalid
router_port=${router_ports[0]}
metrics_port=${router_ports[1]}

setsid "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_router.py" \
    --worker-urls-file "$urls_file" \
    --host 127.0.0.1 \
    --port "$router_port" \
    --metrics-port "$metrics_port" \
    --capacity-profile sandoq-c64-w2-v1 \
    --endpoint-identifier cpu-132-021_8103 >"$router_log" 2>&1 &
router_pid=$!

for attempt in $(seq 1 60); do
    kill -0 "$router_pid" 2>/dev/null || blocked router_start_failed
    active_workers=$(
        curl --noproxy '*' --fail --silent --show-error --max-time 5 \
            "http://127.0.0.1:${metrics_port}/metrics" 2>/dev/null \
            | awk '$1 == "vllm_router_active_workers" {print $2}' \
            | tail -n 1
    ) || true
    if [[ "$active_workers" == 24 ]] \
        && curl --noproxy '*' --fail --silent --show-error --max-time 5 \
            "http://127.0.0.1:${router_port}/v1/models" >/dev/null; then
        break
    fi
    (( attempt < 60 )) || blocked router_start_failed
    sleep 1
done

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/kimi_miniswe246_sandoq_small_canary.py" orchestrate \
    --project-root "$project_dir" \
    --expected-revision "$expected_revision" \
    --sandoq-site "$sandoq_site" \
    --base-url "http://127.0.0.1:${router_port}/v1" \
    --router-stats-url "http://127.0.0.1:${router_port}/stats"
