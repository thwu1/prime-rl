#!/usr/bin/bash -p
#SBATCH --job-name=k3-shell-recovery-8103
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_shell_recovery_8103_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_shell_recovery_8103_%j.log

set +x
set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf '{"category":"probe_arguments_invalid","state":"blocked"}\n' >&2
    exit 2
fi

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
expected_revision=${KIMI_RECOVERY_EXPECTED_PRIME_RL_REVISION:?Set KIMI_RECOVERY_EXPECTED_PRIME_RL_REVISION}
probe_mode=${KIMI_RECOVERY_PROBE_MODE:-forced-delete}
probe_script="$workflow_dir/probe_sandoq_managed_shell_recovery.py"
expected_probe_sha256=${KIMI_RECOVERY_PROBE_SHA256:?Set KIMI_RECOVERY_PROBE_SHA256}
provider_context="$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py"
provider_profile="$workflow_dir/configs/provider_context/use2/kimi_sandoq_firecracker_no_network.json"
provider_profile_sha256=53e0311216e1b27988b960a782188c5794ed941b9380cba1fbd0f29a67149a93
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_ram_prime_f7313db4}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
ecr_token_file=${OCI_RUNNER_ECR_TOKEN_FILE:-/storage/home/tianhaowu/.config/oci-runner/ecr-token}
ecr_token_metadata=${OCI_RUNNER_ECR_TOKEN_METADATA_PATH:-${ecr_token_file}.metadata.json}
output_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/kimi-managed-shell-recovery-cpu132021-8103-v1
output_dir="$output_root/${SLURM_JOB_ID:?SLURM_JOB_ID is required}-${probe_mode}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site"

blocked() {
    printf '{"category":"%s","state":"blocked"}\n' "$1" >&2
    exit 2
}

[[ "$probe_mode" == forced-delete || "$probe_mode" == idle-endurance ]] \
    || blocked probe_mode_invalid
[[ "$expected_revision" =~ ^[0-9a-f]{40}$ \
    && "$(git -C "$project_dir" rev-parse --verify HEAD)" == "$expected_revision" \
    && -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]] \
    || blocked source_identity_invalid
[[ "$expected_probe_sha256" =~ ^[0-9a-f]{64}$ \
    && -f "$probe_script" && ! -L "$probe_script" \
    && "$(sha256sum -- "$probe_script" | cut -d' ' -f1)" == "$expected_probe_sha256" ]] \
    || blocked probe_source_invalid
[[ -x "$x86_uv" && -d "$x86_site/pydantic" && -d "$sandoq_site/sandoq_client" \
    && -f "$provider_profile" && ! -L "$provider_profile" \
    && "$(sha256sum -- "$provider_profile" | cut -d' ' -f1)" == "$provider_profile_sha256" ]] \
    || blocked runtime_identity_invalid

if [[ ${SANDOQ_PROVIDER_CONTEXT_ACTIVE:-} != 1 ]]; then
    [[ -z ${SANDOQ_PROVIDER_CONTEXT_ACTIVE:-} && -z ${SANDOQ_PROVIDER_CONTEXT_RECEIPT:-} ]] \
        || blocked partial_provider_context
    [[ ! -e "$output_dir" ]] || blocked output_not_fresh
    install -d -m 700 -- "$output_root"
    mkdir -m 700 -- "$output_dir"
    export PRIME_RL_OUTPUT_DIR="$output_dir"
    export OCI_RUNNER_POOL_WAL="$output_dir/sandoq-pool.wal.jsonl"
    export OCI_RUNNER_POOL_EVENT_LOG="$output_dir/pool-events.jsonl"
    exec "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$provider_context" supervise \
        --profile "$provider_profile" \
        --profile-sha256 "$provider_profile_sha256" \
        --concurrency 1 \
        --lease-create-cap 1 \
        --startup-timeout-seconds 3600 \
        --lease-profile kimi-tb4-long \
        --ecr-token-file "$ecr_token_file" \
        --ecr-token-metadata "$ecr_token_metadata" \
        --project-root "$project_dir" \
        --sandoq-site "$sandoq_site" \
        -- /usr/bin/bash -p "${BASH_SOURCE[0]}"
fi

[[ "${PRIME_RL_OUTPUT_DIR:-}" == "$output_dir" \
    && "${OCI_RUNNER_POOL_WAL:-}" == "$output_dir/sandoq-pool.wal.jsonl" \
    && "${OCI_RUNNER_POOL_EVENT_LOG:-}" == "$output_dir/pool-events.jsonl" \
    && -d "$output_dir" && ! -L "$output_dir" \
    && "$(stat -c '%a:%u' -- "$output_dir")" == "700:$(id -u)" ]] \
    || blocked output_identity_invalid
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$provider_context" verify \
    --receipt "${SANDOQ_PROVIDER_CONTEXT_RECEIPT:?}" >/dev/null \
    || blocked provider_context_invalid
[[ "${SANDOQ_LEASE_PROFILE:-}" == kimi-tb4-long \
    && "${OCI_RUNNER_ENVIRONMENT:-}" == oci-runner-firecracker \
    && "${SANDOQ_EFFECTIVE_TASK_NETWORK:-}" == none \
    && "${OCI_RUNNER_TASK_NETWORK:-}" == none \
    && "${OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK:-}" == 0 \
    && "${OCI_RUNNER_TOKEN_FILE:-}" == /home/tianhaowu/.config/oci-runner/firecracker-token \
    && "${OCI_RUNNER_LEASE_DURATION:-}" == 12h \
    && "${OCI_RUNNER_POOL_RENEW_INTERVAL:-}" == 5m \
    && "${OCI_RUNNER_MANAGED_SHELL_RECOVERY:-}" == 1 \
    && "${OCI_RUNNER_POOL_SIZE:-}" == 1 ]] \
    || blocked recovery_contract_invalid

idle_seconds=0
if [[ "$probe_mode" == idle-endurance ]]; then
    idle_seconds=3900
fi
exec "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$probe_script" \
    --mode "$probe_mode" \
    --idle-seconds "$idle_seconds" \
    --output "$output_dir/managed-shell-recovery.json"
