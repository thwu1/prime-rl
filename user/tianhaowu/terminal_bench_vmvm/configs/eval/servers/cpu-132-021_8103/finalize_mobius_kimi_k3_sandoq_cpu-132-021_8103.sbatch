#!/usr/bin/bash -p
#SBATCH --job-name=k3-mobius-sft-8103
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_mobius_sft_8103_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_mobius_sft_8103_%j.log

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
expected_revision=${KIMI_PRODUCTION_EXPECTED_PRIME_RL_REVISION:?}
run_dir=${KIMI_PRODUCTION_RUN_DIR:?}
launch_certificate=${KIMI_PRODUCTION_LAUNCH:?}
launch_certificate_sha256=${KIMI_PRODUCTION_LAUNCH_SHA256:?}
rotator_log=${KIMI_ECR_ROTATOR_LOG:?}
sft_root=${KIMI_SFT_OUTPUT_ROOT:?}
sft_dir=${KIMI_SFT_OUTPUT_DIR:?}
sft_receipt=${KIMI_SFT_EXPORT_RECEIPT:?}
sft_attestation=${KIMI_SFT_PREFLIGHT_ATTESTATION:?}
tokenizer_snapshot=${KIMI_SFT_TOKENIZER_SNAPSHOT:?}
tokenizer_snapshot_sha256=${KIMI_SFT_TOKENIZER_SNAPSHOT_SHA256:?}
split_salt=${KIMI_SFT_SPLIT_SALT:?}
validation_permyriad=${KIMI_SFT_VALIDATION_PERMYRIAD:-500}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}

[[ "$expected_revision" =~ ^[0-9a-f]{40}$ \
    && "$(git -C "$project_dir" rev-parse HEAD)" == "$expected_revision" \
    && -z "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]] \
    || blocked source_identity_invalid
[[ -x "$x86_uv" && -d "$x86_site/pydantic" ]] || blocked runtime_unavailable
for path in "$run_dir" "$launch_certificate" "$rotator_log" "$tokenizer_snapshot"; do
    [[ -e "$path" && ! -L "$path" ]] || blocked finalization_input_invalid
done
[[ "$validation_permyriad" =~ ^[0-9]+$ ]] || blocked validation_permyriad_invalid
(( validation_permyriad < 10000 )) || blocked validation_permyriad_invalid
[[ -d "$sft_root" && ! -L "$sft_root" \
    && "$(stat -c '%a:%u' -- "$sft_root")" == "700:$(id -u)" ]] \
    || blocked sft_output_root_invalid
[[ ! -e "$sft_dir" && ! -L "$sft_dir" \
    && ! -e "$sft_receipt" && ! -L "$sft_receipt" \
    && ! -e "$sft_attestation" && ! -L "$sft_attestation" ]] \
    || blocked sft_output_not_fresh

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${SLURM_TMPDIR:-/tmp}/kimi-sft-pycache-${SLURM_JOB_ID:?}"
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

terminal_receipt="$run_dir/terminal_job_receipt.json"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/kimi_sandoq_production.py" record-terminal \
    --provenance "$run_dir/provenance.txt" \
    --output "$terminal_receipt" >/dev/null
terminal_receipt_sha256=$(sha256sum -- "$terminal_receipt" | cut -d' ' -f1)

rotation_audit="$run_dir/ecr_rotation_audit.json"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/sandoq_ecr_rotation.py" audit \
    --rotator-log "$rotator_log" \
    --guard-log "$run_dir/control/ecr_guard_events.jsonl" \
    --eval-run-identity "$run_dir/eval_run_identity.json" \
    --results "$run_dir/results.jsonl" \
    --output "$rotation_audit" >/dev/null

trace_certificate="$run_dir/kimi_sandoq_trace_certificate.json"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/kimi_sandoq_production.py" certify \
    --launch-certificate "$launch_certificate" \
    --launch-certificate-sha256 "$launch_certificate_sha256" \
    --run-dir "$run_dir" \
    --rotation-audit "$rotation_audit" \
    --terminal-receipt "$terminal_receipt" \
    --terminal-receipt-sha256 "$terminal_receipt_sha256" \
    --output "$trace_certificate" >/dev/null
trace_certificate_sha256=$(sha256sum -- "$trace_certificate" | cut -d' ' -f1)

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/finalize_kimi_sft.py" export \
    --project-root "$project_dir" \
    --expected-revision "$expected_revision" \
    --trace-certificate "$trace_certificate" \
    --trace-certificate-sha256 "$trace_certificate_sha256" \
    --output-root "$sft_root" \
    --output-dir "$sft_dir" \
    --validation-permyriad "$validation_permyriad" \
    --split-salt "$split_salt" \
    --receipt "$sft_receipt" >/dev/null
sft_receipt_sha256=$(sha256sum -- "$sft_receipt" | cut -d' ' -f1)

"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/finalize_kimi_sft.py" preflight \
    --project-root "$project_dir" \
    --expected-revision "$expected_revision" \
    --export-receipt "$sft_receipt" \
    --export-receipt-sha256 "$sft_receipt_sha256" \
    --tokenizer-snapshot-path "$tokenizer_snapshot" \
    --tokenizer-snapshot-sha256 "$tokenizer_snapshot_sha256" \
    --output "$sft_attestation" >/dev/null

printf '{"input_traces":2499,"state":"pass-only-sft-attested"}\n'
