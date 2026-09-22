#!/bin/bash
#SBATCH --job-name=k3-tb4-direct-8103
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=7-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=48G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_direct_8103_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_direct_8103_%j.log

set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf 'Configure the direct Kimi run through its sealed environment\n' >&2
    exit 2
fi

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
server_dir="$workflow_dir/configs/eval/servers/cpu-132-021_8103"
expected_revision=${KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION:?Set KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION}
stage=${KIMI_SANDOQ_STAGE:-smoke}
preflight_only=${KIMI_SANDOQ_PREFLIGHT_ONLY:-0}
sandbox_provider=${KIMI_SANDBOX_PROVIDER:-sandoq}
execution_mode=${KIMI_EXECUTION_MODE:-certified}
deployment_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/kimi-k3-deployment-cpu132021-v1
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
sandoq_site=${SANDOQ_PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_ram_prime_f7313db4}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
eval_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals
generation_dir="$eval_root/kimi_k3_direct_generation_cpu-132-021_8103_${SLURM_JOB_ID}"
if [[ "$stage" == miniswe-smoke ]]; then
    output_dir="$eval_root/tb4_kimi_k3_direct_sandoq_cpu-132-021_8103_${SLURM_JOB_ID}_miniswe_smoke"
elif [[ "$stage" == mobius-smoke ]]; then
    output_dir="$eval_root/mobius_kimi_k3_direct_sandoq_cpu-132-021_8103_${SLURM_JOB_ID}_smoke"
elif [[ "$stage" == capacity-smoke ]]; then
    output_dir="$eval_root/mobius_kimi_k3_direct_sandoq_cpu-132-021_8103_${SLURM_JOB_ID}_capacity64"
elif [[ "$stage" == provider-split-legacy ]]; then
    output_dir="$eval_root/tb4_kimi_k3_direct_sandoq_cpu-132-021_8103_${SLURM_JOB_ID}_legacy"
elif [[ "$stage" == provider-split-large ]]; then
    output_dir="$eval_root/tb4_kimi_k3_direct_vmvm_cpu-132-021_8103_${SLURM_JOB_ID}_large"
elif [[ "$stage" == sandoq-fallback-memory-8g || "$stage" == sandoq-fallback-memory-16g ]]; then
    output_dir="$eval_root/tb4_kimi_k3_direct_cpu-132-021_8103_${SLURM_JOB_ID}_${stage}_diagnostic"
else
    output_dir="$eval_root/tb4_kimi_k3_direct_sandoq_cpu-132-021_8103_${SLURM_JOB_ID}_${stage}"
fi
manifest="$generation_dir/direct_kimi_workers.json"
urls_file="$generation_dir/worker_urls.private.txt"
ports_file="$generation_dir/router_ports.private.txt"
router_log="$generation_dir/direct_router.log"
router_stats="$generation_dir/direct_router_stats.private.json"
deployment_snapshot="$generation_dir/deployment_source"
provider_profile="$server_dir/sandoq_use2.json"
provider_profile_sha256=965511eb9578aa303d287491a7414e145241d6dbbf61469d13abbe801980a95a
miniswe_compatibility_receipt=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/qwen-miniswe246-sandoq-3step-20260921/run-1537041/receipt.json
miniswe_compatibility_sha256=cee344d3c9bc3c18f602a0ad217ade7395db263d50cd8d4c428507a21de86220
native_miniswe_stage=0
if [[ "$stage" == miniswe-smoke || "$stage" == tb4-miniswe || "$stage" == capacity-smoke \
    || "$stage" == tb4-miniswe246-sandoq-union ]]; then
    native_miniswe_stage=1
    provider_profile="$workflow_dir/configs/provider_context/use2/kimi_sandoq_firecracker_host.json"
    provider_profile_sha256=7dd88ca6c6cde5ed5b22bf8f621462a46425f939478f79469e31da2e582b27df
fi
router_pid=

cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [[ -n "$router_pid" ]] && kill -0 "$router_pid" 2>/dev/null; then
        kill -TERM -- "-$router_pid" 2>/dev/null || true
        wait "$router_pid" 2>/dev/null || true
    fi
    exit "$status"
}
trap cleanup EXIT INT TERM

if [[ "$stage" != smoke && "$stage" != miniswe-smoke && "$stage" != mobius-smoke \
    && "$stage" != capacity-smoke && "$stage" != tb4 \
    && "$stage" != tb4-miniswe \
    && "$stage" != tb4-miniswe246-sandoq-union \
    && "$stage" != tb4-miniswe246-vmvm-union \
    && "$stage" != provider-split-legacy \
    && "$stage" != provider-split-large \
    && "$stage" != sandoq-fallback-memory-8g \
    && "$stage" != sandoq-fallback-memory-16g ]]; then
    printf 'KIMI_SANDOQ_STAGE is invalid\n' >&2
    exit 2
fi
if [[ "$stage" == capacity-smoke && "$sandbox_provider" != sandoq ]]; then
    printf 'Kimi capacity smoke requires Sandoq\n' >&2
    exit 2
fi
if [[ "$sandbox_provider" != sandoq && "$sandbox_provider" != vmvm ]] \
    || [[ "$stage" == tb4-miniswe246-sandoq-union && "$sandbox_provider" != sandoq ]] \
    || [[ "$stage" == tb4-miniswe246-vmvm-union && "$sandbox_provider" != vmvm ]] \
    || [[ ( "$stage" == provider-split-large || "$stage" == tb4-miniswe246-vmvm-union ) \
        && "$sandbox_provider" != vmvm ]] \
    || [[ "$stage" != provider-split-large && "$stage" != tb4-miniswe246-vmvm-union \
        && "$sandbox_provider" != sandoq ]]; then
    printf 'Direct Kimi stage/provider pairing is invalid\n' >&2
    exit 2
fi
if [[ "$stage" == smoke || "$stage" == miniswe-smoke \
    || "$stage" == mobius-smoke || "$stage" == capacity-smoke ]]; then
    smoke_wall_limit=$(squeue -h -j "$SLURM_JOB_ID" -o '%l')
    expected_smoke_wall_limit=4:00:00
    if [[ "$stage" == miniswe-smoke ]]; then
        expected_smoke_wall_limit=1:00:00
    elif [[ "$stage" == mobius-smoke ]]; then
        expected_smoke_wall_limit=12:00
    elif [[ "$stage" == capacity-smoke ]]; then
        expected_smoke_wall_limit=2:00:00
    fi
    if [[ "$smoke_wall_limit" != "$expected_smoke_wall_limit" ]]; then
        printf 'Direct Kimi smoke requires its exact Slurm wall limit\n' >&2
        exit 2
    fi
fi
if [[ "$preflight_only" != 0 && "$preflight_only" != 1 ]]; then
    printf 'KIMI_SANDOQ_PREFLIGHT_ONLY must be 0 or 1\n' >&2
    exit 2
fi
if [[ "$stage" == tb4-miniswe && "$preflight_only" != 1 ]]; then
    printf 'TB4 MiniSWE requires a resource-capable tunnel environment certificate\n' >&2
    exit 2
fi
if [[ "$execution_mode" != certified && "$preflight_only" != 0 ]]; then
    printf 'The sealed diagnostic plan is actual-only; use a distinct plan for preflight\n' >&2
    exit 2
fi
if [[ ! "$expected_revision" =~ ^[0-9a-f]{40}$ \
    || "$(git -C "$project_dir" rev-parse HEAD)" != "$expected_revision" \
    || -n "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]]; then
    printf 'PROJECT_DIR must be the exact clean approved direct Kimi source\n' >&2
    exit 2
fi
if [[ ! -d "$x86_site/pydantic" || ! -x "$x86_uv" \
    || ( "$sandbox_provider" == sandoq && ! -d "$sandoq_site/sandoq_client" ) \
    || ( "$sandbox_provider" == sandoq && ( ! -f "$provider_profile" || -L "$provider_profile" ) ) ]]; then
    printf 'Direct Kimi pinned runtime is unavailable\n' >&2
    exit 2
fi
if [[ "$sandbox_provider" == sandoq ]] \
    && [[ "$(sha256sum "$provider_profile" | cut -d' ' -f1)" != "$provider_profile_sha256" ]]; then
    printf 'Direct Kimi provider profile digest mismatch\n' >&2
    exit 2
fi
if [[ "$native_miniswe_stage" == 1 ]] && {
    [[ ! -f "$miniswe_compatibility_receipt" || -L "$miniswe_compatibility_receipt" ]] \
        || [[ "$(stat -c '%a:%h:%u' -- "$miniswe_compatibility_receipt")" != "600:1:$(id -u)" ]] \
        || [[ "$(sha256sum -- "$miniswe_compatibility_receipt" | cut -d' ' -f1)" != "$miniswe_compatibility_sha256" ]];
}; then
    printf 'MiniSWE compatibility receipt is unavailable or changed\n' >&2
    exit 2
fi

if [[ "$execution_mode" != certified && "$execution_mode" != diagnostic \
    && "$execution_mode" != sandoq-fallback-diagnostic ]]; then
    printf 'KIMI_EXECUTION_MODE is invalid\n' >&2
    exit 2
fi
if [[ ( "$stage" == sandoq-fallback-memory-8g || "$stage" == sandoq-fallback-memory-16g ) \
    && "$execution_mode" != sandoq-fallback-diagnostic ]]; then
    printf 'Fallback stages cannot run as certified output\n' >&2
    exit 2
fi
if [[ "$execution_mode" == sandoq-fallback-diagnostic ]]; then
    if [[ "$stage" != sandoq-fallback-memory-8g && "$stage" != sandoq-fallback-memory-16g ]]; then
        printf 'Fallback diagnostic execution requires an exact fallback lane\n' >&2
        exit 2
    fi
    launch_plan=${KIMI_SANDOQ_FALLBACK_PLAN:?Set KIMI_SANDOQ_FALLBACK_PLAN}
    launch_plan_sha256=${KIMI_SANDOQ_FALLBACK_PLAN_SHA256:?Set KIMI_SANDOQ_FALLBACK_PLAN_SHA256}
    launch_lane=memory_8g
    expected_launch_count=17
    expected_launch_concurrency=6
    if [[ "$stage" == sandoq-fallback-memory-16g ]]; then
        launch_lane=memory_16g
        expected_launch_count=4
        expected_launch_concurrency=2
    fi
    verified_launch=$(
        PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site" \
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$workflow_dir/prepare_kimi_tb4_sandoq_fallback.py" verify \
            --launch-plan "$launch_plan" --launch-plan-sha256 "$launch_plan_sha256" \
            --lane "$launch_lane" --format tsv
    )
    IFS=$'\t' read -r verified_stage verified_provider eval_config eval_config_sha256 task_file \
        task_sha256 verified_count verified_concurrency output_dir resource_manifest \
        resource_manifest_sha256 partition_dir verified_extra \
        <<< "$verified_launch"
    if [[ -n "$verified_extra" || "$verified_launch" == *$'\n'* \
        || ! "$verified_count" =~ ^[1-9][0-9]*$ || ! "$verified_concurrency" =~ ^[1-9][0-9]*$ \
        || "$verified_count" != "$expected_launch_count" \
        || "$verified_concurrency" != "$expected_launch_concurrency" \
        || "$stage" != "$verified_stage" || "$sandbox_provider" != "$verified_provider" ]]; then
        printf 'Fallback diagnostic launch plan binding failed\n' >&2
        exit 2
    fi
    task_count=$verified_count
    stage_capacity=$verified_concurrency
elif [[ "$execution_mode" == diagnostic ]]; then
    if [[ "$stage" != provider-split-legacy && "$stage" != provider-split-large ]]; then
        printf 'Diagnostic execution requires one provider-split lane\n' >&2
        exit 2
    fi
    launch_plan=${KIMI_PROVIDER_LAUNCH_PLAN:?Set KIMI_PROVIDER_LAUNCH_PLAN}
    launch_plan_sha256=${KIMI_PROVIDER_LAUNCH_PLAN_SHA256:?Set KIMI_PROVIDER_LAUNCH_PLAN_SHA256}
    launch_role=legacy_sandoq
    expected_launch_count=31
    expected_launch_concurrency=24
    if [[ "$stage" == provider-split-large ]]; then
        launch_role=large_provider
        expected_launch_count=32
        expected_launch_concurrency=4
    fi
    verified_launch=$(
        PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site" \
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$workflow_dir/prepare_kimi_tb4_provider_split_launch.py" verify \
            --launch-plan "$launch_plan" --launch-plan-sha256 "$launch_plan_sha256" \
            --role "$launch_role" --format tsv
    )
    IFS=$'\t' read -r verified_stage verified_provider eval_config eval_config_sha256 task_file \
        task_sha256 verified_count verified_concurrency output_dir resource_manifest \
        resource_manifest_sha256 partition_dir verified_extra \
        <<< "$verified_launch"
    if [[ -n "$verified_extra" || "$verified_launch" == *$'\n'* \
        || ! "$verified_count" =~ ^[1-9][0-9]*$ || ! "$verified_concurrency" =~ ^[1-9][0-9]*$ \
        || "$verified_count" != "$expected_launch_count" \
        || "$verified_concurrency" != "$expected_launch_concurrency" \
        || "$stage" != "$verified_stage" || "$sandbox_provider" != "$verified_provider" ]]; then
        printf 'Diagnostic launch plan binding failed\n' >&2
        exit 2
    fi
    task_count=$verified_count
    stage_capacity=$verified_concurrency
elif [[ -n ${KIMI_PROVIDER_LAUNCH_PLAN:-} || -n ${KIMI_PROVIDER_LAUNCH_PLAN_SHA256:-} \
    || -n ${KIMI_SANDOQ_FALLBACK_PLAN:-} || -n ${KIMI_SANDOQ_FALLBACK_PLAN_SHA256:-} ]]; then
    printf 'Certified execution cannot consume a diagnostic launch plan\n' >&2
    exit 2
fi

if [[ "$stage" == tb4-miniswe246-sandoq-union || "$stage" == tb4-miniswe246-vmvm-union ]]; then
    [[ "$execution_mode" == certified ]] || { printf 'MiniSWE union lanes require certified mode\n' >&2; exit 2; }
    union_launch_plan=${KIMI_TB4_MINISWE_UNION_PLAN:?Set KIMI_TB4_MINISWE_UNION_PLAN}
    union_launch_plan_sha256=${KIMI_TB4_MINISWE_UNION_PLAN_SHA256:?Set KIMI_TB4_MINISWE_UNION_PLAN_SHA256}
    union_role=sandoq_firecracker
    if [[ "$stage" == tb4-miniswe246-vmvm-union ]]; then
        union_role=vmvm_cpu
    fi
    verified_union=$(
        PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site" \
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$workflow_dir/prepare_kimi_tb4_miniswe246_union.py" verify \
            --launch-plan "$union_launch_plan" \
            --launch-plan-sha256 "$union_launch_plan_sha256" \
            --role "$union_role" --format tsv
    )
    IFS=$'\t' read -r verified_stage verified_provider eval_config eval_config_sha256 task_file \
        task_sha256 task_count stage_capacity output_dir resource_manifest \
        resource_manifest_sha256 verified_adapter verified_extra <<< "$verified_union"
    if [[ -n "$verified_extra" || "$verified_union" == *$'\n'* \
        || "$verified_stage" != "$stage" || "$verified_provider" != "$sandbox_provider" \
        || "$verified_adapter" != kimi-tb4-miniswe246-provider-union-v1 ]]; then
        printf 'MiniSWE union plan binding failed\n' >&2
        exit 2
    fi
    partition_dir=$(dirname -- "$union_launch_plan")
    identity_role=kimi-direct-tb4
    certificate_mode=miniswe-union
    smoke_checkpoint=${KIMI_SANDOQ_SMOKE_CHECKPOINT:?Set KIMI_SANDOQ_SMOKE_CHECKPOINT}
    smoke_checkpoint_sha256=${KIMI_SANDOQ_SMOKE_CHECKPOINT_SHA256:?Set KIMI_SANDOQ_SMOKE_CHECKPOINT_SHA256}
elif [[ "$stage" == capacity-smoke ]]; then
    eval_config=${KIMI_SANDOQ_CAPACITY_EVAL_CONFIG:?Set KIMI_SANDOQ_CAPACITY_EVAL_CONFIG}
    eval_config_sha256=${KIMI_SANDOQ_CAPACITY_EVAL_CONFIG_SHA256:?Set KIMI_SANDOQ_CAPACITY_EVAL_CONFIG_SHA256}
    task_file=${KIMI_SANDOQ_CAPACITY_TASK_FILE:?Set KIMI_SANDOQ_CAPACITY_TASK_FILE}
    task_sha256=${KIMI_SANDOQ_CAPACITY_TASK_FILE_SHA256:?Set KIMI_SANDOQ_CAPACITY_TASK_FILE_SHA256}
    capacity_selector_receipt=${KIMI_SANDOQ_CAPACITY_SELECTOR_RECEIPT:?Set KIMI_SANDOQ_CAPACITY_SELECTOR_RECEIPT}
    capacity_selector_receipt_sha256=${KIMI_SANDOQ_CAPACITY_SELECTOR_RECEIPT_SHA256:?Set KIMI_SANDOQ_CAPACITY_SELECTOR_RECEIPT_SHA256}
    task_count=64
    stage_capacity=64
    identity_role=kimi-direct-capacity-smoke
    certificate_mode=capacity
    router_capacity_profile=sandoq-c64-v1
    endpoint_identifier=cpu-132-021_8103
elif [[ "$stage" == smoke || "$stage" == miniswe-smoke ]]; then
    eval_config="$server_dir/tb4_kimi_k3_sandoq_smoke.toml"
    if [[ "$stage" == miniswe-smoke ]]; then
        eval_config="$server_dir/tb4_kimi_k3_miniswe246_sandoq_smoke.toml"
    fi
    # Exact one-task authorization derived ID-blind from the reviewed
    # non-security TB4 smoke set. Never print its task identifier.
    task_file="$workflow_dir/configs/eval/tb4_kimi_k3_short_smoke.tasks.txt"
    task_sha256=c1f745d4a1d3861deefb3fba4daa23f52ff3d1d4952a9fe2ba0ccbdc4040af97
    task_count=1
    stage_capacity=1
    identity_role=kimi-direct-smoke
    certificate_mode=smoke
elif [[ "$stage" == mobius-smoke ]]; then
    eval_config="$server_dir/mobius_kimi_k3_max_sandoq_smoke.toml"
    task_file=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/use2/qwen_quick_debug/task_stable.txt
    task_sha256=1f6489ac59a4562b7674ae1779832be08c6e7b859d691dba7e81c89fa91147ca
    task_count=1
    stage_capacity=1
    identity_role=kimi-direct-smoke
    certificate_mode=smoke
elif [[ "$stage" == tb4 || "$stage" == tb4-miniswe ]]; then
    eval_config="$server_dir/tb4_kimi_k3_sandoq_pass1.toml"
    if [[ "$stage" == tb4-miniswe ]]; then
        eval_config="$server_dir/tb4_kimi_k3_miniswe246_sandoq_pass1.toml"
    fi
    task_file="$workflow_dir/configs/eval/tb4_qwen_a95b_miniswe.tasks.txt"
    task_sha256=9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892
    task_count=66
    stage_capacity=24
    identity_role=kimi-direct-tb4
    certificate_mode=tb4
    smoke_checkpoint=${KIMI_SANDOQ_SMOKE_CHECKPOINT:?Set KIMI_SANDOQ_SMOKE_CHECKPOINT}
    smoke_checkpoint_sha256=${KIMI_SANDOQ_SMOKE_CHECKPOINT_SHA256:?Set KIMI_SANDOQ_SMOKE_CHECKPOINT_SHA256}
    if [[ ! -f "$smoke_checkpoint" || -L "$smoke_checkpoint" \
        || "$(sha256sum "$smoke_checkpoint" | cut -d' ' -f1)" != "$smoke_checkpoint_sha256" ]]; then
        printf 'Direct Kimi smoke checkpoint is unavailable or changed\n' >&2
        exit 2
    fi
elif [[ "$stage" == provider-split-large ]]; then
    if [[ "$execution_mode" == certified ]]; then
        eval_config=${KIMI_VMVM_LARGE_EVAL_CONFIG:?Set KIMI_VMVM_LARGE_EVAL_CONFIG}
        task_file=${KIMI_VMVM_LARGE_TASK_FILE:?Set KIMI_VMVM_LARGE_TASK_FILE}
        task_sha256=${KIMI_VMVM_LARGE_TASK_FILE_SHA256:?Set KIMI_VMVM_LARGE_TASK_FILE_SHA256}
        task_count=32
        stage_capacity=4
    fi
    identity_role=kimi-direct-tb4-diagnostic
    if [[ "$execution_mode" == certified ]]; then
        identity_role=kimi-direct-tb4
        certificate_mode=tb4
        smoke_checkpoint=${KIMI_SANDOQ_SMOKE_CHECKPOINT:?Set KIMI_SANDOQ_SMOKE_CHECKPOINT}
        smoke_checkpoint_sha256=${KIMI_SANDOQ_SMOKE_CHECKPOINT_SHA256:?Set KIMI_SANDOQ_SMOKE_CHECKPOINT_SHA256}
        if [[ ! -f "$smoke_checkpoint" || -L "$smoke_checkpoint" \
            || "$(sha256sum "$smoke_checkpoint" | cut -d' ' -f1)" != "$smoke_checkpoint_sha256" ]]; then
            printf 'Direct Kimi smoke checkpoint is unavailable or changed\n' >&2
            exit 2
        fi
    fi
elif [[ "$stage" == sandoq-fallback-memory-8g ]]; then
    identity_role=kimi-direct-tb4-sandoq-fallback-diagnostic
elif [[ "$stage" == sandoq-fallback-memory-16g ]]; then
    identity_role=kimi-direct-tb4-sandoq-fallback-diagnostic
else
    if [[ "$execution_mode" == certified ]]; then
        eval_config=${KIMI_SANDOQ_LEGACY_EVAL_CONFIG:?Set KIMI_SANDOQ_LEGACY_EVAL_CONFIG}
        task_file=${KIMI_SANDOQ_LEGACY_TASK_FILE:?Set KIMI_SANDOQ_LEGACY_TASK_FILE}
        task_sha256=${KIMI_SANDOQ_LEGACY_TASK_FILE_SHA256:?Set KIMI_SANDOQ_LEGACY_TASK_FILE_SHA256}
        task_count=31
        stage_capacity=24
    fi
    identity_role=kimi-direct-tb4-diagnostic
    if [[ "$execution_mode" == certified ]]; then
        identity_role=kimi-direct-tb4
        certificate_mode=tb4
        smoke_checkpoint=${KIMI_SANDOQ_SMOKE_CHECKPOINT:?Set KIMI_SANDOQ_SMOKE_CHECKPOINT}
        smoke_checkpoint_sha256=${KIMI_SANDOQ_SMOKE_CHECKPOINT_SHA256:?Set KIMI_SANDOQ_SMOKE_CHECKPOINT_SHA256}
        if [[ ! -f "$smoke_checkpoint" || -L "$smoke_checkpoint" \
            || "$(sha256sum "$smoke_checkpoint" | cut -d' ' -f1)" != "$smoke_checkpoint_sha256" ]]; then
            printf 'Direct Kimi smoke checkpoint is unavailable or changed\n' >&2
            exit 2
        fi
    fi
fi
if [[ "$stage" == miniswe-smoke ]]; then
    resource_manifest=${KIMI_RESOURCE_MANIFEST:?Set KIMI_RESOURCE_MANIFEST}
    resource_manifest_sha256=${KIMI_RESOURCE_MANIFEST_SHA256:?Set KIMI_RESOURCE_MANIFEST_SHA256}
    PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:$sandoq_site:$x86_site" \
        "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/prepare_kimi_tb4_miniswe246_union.py" verify-smoke \
        --manifest "$resource_manifest" --manifest-sha256 "$resource_manifest_sha256" \
        --selector "$task_file" --selector-sha256 "$task_sha256" >/dev/null
fi
if [[ -e "$generation_dir" || -L "$generation_dir" || -e "$output_dir" || -L "$output_dir" ]]; then
    printf 'Direct Kimi output namespace is not fresh\n' >&2
    exit 2
fi
for path in "$eval_config" "$task_file"; do
    if [[ ! -f "$path" || -L "$path" ]]; then
        printf 'Direct Kimi evaluation input is unavailable or unsafe\n' >&2
        exit 2
    fi
done
if [[ "$stage" == capacity-smoke ]] && {
    [[ ! -f "$capacity_selector_receipt" || -L "$capacity_selector_receipt" ]] \
        || [[ "$(stat -c '%a:%h:%u' -- "$capacity_selector_receipt")" != "600:1:$(id -u)" ]] \
        || [[ "$(sha256sum -- "$capacity_selector_receipt" | cut -d' ' -f1)" \
            != "$capacity_selector_receipt_sha256" ]];
}; then
    printf 'Opaque capacity selector receipt is unavailable or changed\n' >&2
    exit 2
fi
if [[ "$(sha256sum "$task_file" | cut -d' ' -f1)" != "$task_sha256" ]]; then
    printf 'Direct Kimi approved task set changed\n' >&2
    exit 2
fi
if [[ -n ${eval_config_sha256:-} \
    && "$(sha256sum "$eval_config" | cut -d' ' -f1)" != "$eval_config_sha256" ]]; then
    printf 'Direct Kimi sealed evaluation config changed\n' >&2
    exit 2
fi

mkdir -p "$generation_dir"
chmod 0700 "$generation_dir"
exec 8>"$generation_dir/.direct_router.lock"
chmod 0600 "$generation_dir/.direct_router.lock"
if ! flock -n 8; then
    printf 'Another process owns the direct Kimi router generation\n' >&2
    exit 2
fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site"
router_profile_args=(--capacity-profile "${router_capacity_profile:-legacy-c24}")
if [[ -n ${endpoint_identifier:-} ]]; then
    router_profile_args+=(--endpoint-identifier "$endpoint_identifier")
fi
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" snapshot-source \
    --deployment-root "$deployment_root" --output-root "$deployment_snapshot" >/dev/null
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" prepare \
    --deployment-root "$deployment_snapshot" --output-root "$generation_dir" \
    --manifest "$manifest" --urls-output "$urls_file" --ports-output "$ports_file" --probe \
    "${router_profile_args[@]}"
manifest_sha256=$(sha256sum "$manifest" | cut -d' ' -f1)
mapfile -t worker_urls < "$urls_file"
mapfile -t router_ports < "$ports_file"
if [[ ${#worker_urls[@]} -ne 24 || ${#router_ports[@]} -ne 2 ]]; then
    printf 'Direct Kimi generation materialization failed\n' >&2
    exit 2
fi
router_port=${router_ports[0]}
metrics_port=${router_ports[1]}

while IFS= read -r variable_name; do
    if [[ ${variable_name,,} == *_proxy ]]; then
        unset "$variable_name"
    fi
done < <(compgen -e)
setsid "$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_router.py" \
        --worker-urls-file "$urls_file" \
        --host 127.0.0.1 \
        --port "$router_port" \
        --metrics-port "$metrics_port" \
        "${router_profile_args[@]}" >"$router_log" 2>&1 &
router_pid=$!

for attempt in $(seq 1 120); do
    if ! kill -0 "$router_pid" 2>/dev/null; then
        printf 'Direct Kimi router exited during startup\n' >&2
        exit 2
    fi
    active_workers=$(
        curl --noproxy '*' --fail --silent --show-error --max-time 10 \
            "http://127.0.0.1:${metrics_port}/metrics" 2>/dev/null \
            | awk '$1 == "vllm_router_active_workers" {print $2}' \
            | tail -n 1
    ) || true
    if [[ "$active_workers" == 24 ]] \
        && curl --noproxy '*' --fail --silent --show-error --max-time 10 \
            "http://127.0.0.1:${router_port}/v1/models" >/dev/null; then
        break
    fi
    if [[ "$attempt" -eq 120 ]]; then
        printf 'Direct Kimi router did not become ready\n' >&2
        exit 2
    fi
    sleep 1
done

ecr_token_file=/storage/home/tianhaowu/.config/oci-runner/ecr-token
ecr_token_metadata=${OCI_RUNNER_ECR_TOKEN_METADATA_PATH:-${ecr_token_file}.metadata.json}
stage_env=(
    PROJECT_DIR="$project_dir"
    EVAL_CONFIG="$eval_config"
    DIRECT_KIMI_EVAL_CONFIG_SHA256="${eval_config_sha256:-}"
    OUTPUT_DIR="$output_dir"
    DIRECT_KIMI_ROLE="$identity_role"
    DIRECT_KIMI_APPROVED_TASK_FILE="$task_file"
    DIRECT_KIMI_APPROVED_TASK_FILE_SHA256="$task_sha256"
    DIRECT_KIMI_APPROVED_TASK_COUNT="$task_count"
    DIRECT_KIMI_ROLLOUT_CONCURRENCY="$stage_capacity"
    DIRECT_KIMI_WORKER_MANIFEST="$manifest"
    DIRECT_KIMI_WORKER_MANIFEST_SHA256="$manifest_sha256"
    DIRECT_KIMI_BASE_URL="http://127.0.0.1:${router_port}/v1"
    DIRECT_KIMI_EXPECTED_PRIME_RL_REVISION="$expected_revision"
    DIRECT_KIMI_PREFLIGHT_ONLY="$preflight_only"
    DIRECT_KIMI_SANDBOX_PROVIDER="$sandbox_provider"
    DIRECT_KIMI_EXECUTION_MODE="$execution_mode"
    DIRECT_KIMI_ROUTER_CAPACITY_PROFILE="${router_capacity_profile:-legacy-c24}"
    DIRECT_KIMI_ENDPOINT_IDENTIFIER="${endpoint_identifier:-}"
)
if [[ "$native_miniswe_stage" == 1 ]]; then
    stage_env+=(
        DIRECT_KIMI_MINISWE_COMPATIBILITY_RECEIPT_SHA256="$miniswe_compatibility_sha256"
    )
fi
if [[ "$identity_role" == kimi-direct-tb4 ]]; then
    stage_env+=(
        DIRECT_KIMI_SMOKE_CHECKPOINT="$smoke_checkpoint"
        DIRECT_KIMI_SMOKE_CHECKPOINT_SHA256="$smoke_checkpoint_sha256"
    )
fi
if [[ "$execution_mode" == sandoq-fallback-diagnostic ]]; then
    stage_env+=(
        DIRECT_KIMI_FALLBACK_PLAN="$launch_plan"
        DIRECT_KIMI_FALLBACK_PLAN_SHA256="$launch_plan_sha256"
        DIRECT_KIMI_FALLBACK_LANE="$launch_lane"
        DIRECT_KIMI_RESOURCE_MANIFEST="$resource_manifest"
        DIRECT_KIMI_RESOURCE_MANIFEST_SHA256="$resource_manifest_sha256"
        DIRECT_KIMI_PROVIDER_PARTITION_DIR="$partition_dir"
    )
elif [[ "$execution_mode" == diagnostic ]]; then
    stage_env+=(
        DIRECT_KIMI_LAUNCH_PLAN="$launch_plan"
        DIRECT_KIMI_LAUNCH_PLAN_SHA256="$launch_plan_sha256"
        DIRECT_KIMI_LAUNCH_ROLE="$launch_role"
        DIRECT_KIMI_RESOURCE_MANIFEST="$resource_manifest"
        DIRECT_KIMI_RESOURCE_MANIFEST_SHA256="$resource_manifest_sha256"
        DIRECT_KIMI_PROVIDER_PARTITION_DIR="$partition_dir"
    )
fi
if [[ "$sandbox_provider" == sandoq ]]; then
    sandoq_lease_profile=standard
    if [[ "$stage" == miniswe-smoke || "$stage" == tb4 || "$stage" == tb4-miniswe \
        || "$stage" == tb4-miniswe246-sandoq-union || "$stage" == provider-split-legacy \
        || "$stage" == sandoq-fallback-memory-8g \
        || "$stage" == sandoq-fallback-memory-16g ]]; then
        sandoq_lease_profile=kimi-tb4-long
    fi
    env "${stage_env[@]}" \
        "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/terminal_bench_vmvm/sandoq_provider_context.py" supervise \
        --profile "$provider_profile" \
        --profile-sha256 "$provider_profile_sha256" \
        --concurrency "$stage_capacity" \
        --lease-create-cap "$(( stage_capacity < 4 ? stage_capacity : 4 ))" \
        --startup-timeout-seconds 3600 \
        --lease-profile "$sandoq_lease_profile" \
        --ecr-token-file "$ecr_token_file" \
        --ecr-token-metadata "$ecr_token_metadata" \
        --project-root "$project_dir" --sandoq-site "$sandoq_site" \
        -- bash "$workflow_dir/run_direct_kimi_sandoq_stage.sh"
else
    capacity_private_key=/storage/home/tianhaowu/.config/vmvm-capacity-attestor/kimi-tb4-use2-1-ed25519.pem
    capacity_public_key="$server_dir/vmvm_capacity_attestor_ed25519.pub.pem"
    capacity_resource_manifest_sha256=${resource_manifest_sha256:-${KIMI_RESOURCE_MANIFEST_SHA256:?Set KIMI_RESOURCE_MANIFEST_SHA256}}
    if [[ ! -f "$capacity_public_key" || -L "$capacity_public_key" \
        || "$(sha256sum "$capacity_public_key" | cut -d' ' -f1)" \
            != c5c6b7d6476b78bffe56666ca353ad71b9f3a11cd9a8219cabb5a81c43f95857 ]]; then
        printf 'Direct Kimi capacity trust root is unavailable or changed\n' >&2
        exit 2
    fi
    stage_env+=(
        DIRECT_KIMI_RESOURCE_MANIFEST_SHA256="$capacity_resource_manifest_sha256"
        DIRECT_KIMI_CAPACITY_PRIVATE_KEY="$capacity_private_key"
        DIRECT_KIMI_CAPACITY_PUBLIC_KEY="$capacity_public_key"
    )
    env "${stage_env[@]}" bash "$workflow_dir/run_direct_kimi_sandoq_stage.sh"
fi
if [[ "$preflight_only" == 1 ]]; then
    printf '{"job_id":"%s","stage":"%s","state":"preflight-passed"}\n' "$SLURM_JOB_ID" "$stage"
    exit 0
fi

if [[ "$stage" == capacity-smoke ]]; then
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/direct_kimi_capacity.py" probe \
        --run-dir "$output_dir" --manifest "$manifest" --manifest-sha256 "$manifest_sha256" \
        --base-url "http://127.0.0.1:${router_port}/v1" \
        --output "$output_dir/control/direct_kimi_capacity_probe.json"
fi

if ! kill -0 "$router_pid" 2>/dev/null; then
    printf 'Direct Kimi router exited before certification\n' >&2
    exit 2
fi
active_workers=$(
    curl --noproxy '*' --fail --silent --show-error --max-time 10 \
        "http://127.0.0.1:${metrics_port}/metrics" \
        | awk '$1 == "vllm_router_active_workers" {print $2}' \
        | tail -n 1
)
curl --noproxy '*' --fail --silent --show-error --max-time 10 \
    "http://127.0.0.1:${router_port}/stats" --output "$router_stats"
chmod 0600 "$router_stats"
"$x86_uv" run --no-project --offline --python "$python_bin" \
    python3 "$workflow_dir/direct_kimi_workers.py" certify-router \
    --manifest "$manifest" --manifest-sha256 "$manifest_sha256" \
    --active-workers "$active_workers" --router-stats "$router_stats" \
    --eval-run-identity "$output_dir/eval_run_identity.json" \
    --eval-invocations "$output_dir/eval_invocations.jsonl" \
    --provenance "$output_dir/provenance.txt" \
    --output "$output_dir/direct_kimi_router_final.json"

if [[ "$stage" == tb4-miniswe246-sandoq-union || "$stage" == tb4-miniswe246-vmvm-union ]]; then
    kill -TERM -- "-$router_pid"
    wait "$router_pid" 2>/dev/null || true
    router_pid=
    flock -u 8
    union_certificate_args=()
    if [[ "$stage" == tb4-miniswe246-vmvm-union ]]; then
        capacity_public_key="$server_dir/vmvm_capacity_attestor_ed25519.pub.pem"
        capacity_receipt="$output_dir/control/vmvm_capacity_receipt.json"
        union_certificate_args=(
            --capacity-receipt "$capacity_receipt"
            --capacity-receipt-sha256 "$(sha256sum "$capacity_receipt" | cut -d' ' -f1)"
            --capacity-public-key "$capacity_public_key"
            --capacity-public-key-sha256 "$(sha256sum "$capacity_public_key" | cut -d' ' -f1)"
        )
    fi
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/certify_kimi_tb4_miniswe246_union.py" certify-lane \
        --role "$union_role" --run-dir "$output_dir" \
        --launch-plan "$union_launch_plan" --launch-plan-sha256 "$union_launch_plan_sha256" \
        --output "$output_dir/provider_partition_certificate.json" \
        "${union_certificate_args[@]}"
elif [[ ( "$stage" == provider-split-legacy || "$stage" == provider-split-large ) \
    && "$execution_mode" == certified ]]; then
    kill -TERM -- "-$router_pid"
    wait "$router_pid" 2>/dev/null || true
    router_pid=
    flock -u 8
    resource_manifest=${KIMI_RESOURCE_MANIFEST:?Set KIMI_RESOURCE_MANIFEST}
    resource_manifest_sha256=${KIMI_RESOURCE_MANIFEST_SHA256:?Set KIMI_RESOURCE_MANIFEST_SHA256}
    partition_dir=${KIMI_PROVIDER_PARTITION_DIR:?Set KIMI_PROVIDER_PARTITION_DIR}
    provider_role=legacy_sandoq
    provider_certificate_args=()
    if [[ "$stage" == provider-split-large ]]; then
        provider_role=large_provider
        capacity_public_key="$server_dir/vmvm_capacity_attestor_ed25519.pub.pem"
        capacity_receipt="$output_dir/control/vmvm_capacity_receipt.json"
        provider_certificate_args=(
            --capacity-receipt "$capacity_receipt"
            --capacity-receipt-sha256 "$(sha256sum "$capacity_receipt" | cut -d' ' -f1)"
            --capacity-public-key "$capacity_public_key"
            --capacity-public-key-sha256 "$(sha256sum "$capacity_public_key" | cut -d' ' -f1)"
        )
    fi
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/kimi_tb4_provider_split.py" certify \
        --role "$provider_role" \
        --run-dir "$output_dir" \
        --partition-dir "$partition_dir" \
        --manifest "$resource_manifest" \
        --manifest-sha256 "$resource_manifest_sha256" \
        --output "$output_dir/provider_partition_certificate.json" \
        "${provider_certificate_args[@]}"
elif [[ "$stage" == capacity-smoke ]]; then
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/direct_kimi_capacity.py" certify \
        --run-dir "$output_dir" \
        --expected-task-file "$task_file" \
        --expected-task-file-sha256 "$task_sha256" \
        --capacity-selector-receipt "$capacity_selector_receipt" \
        --capacity-selector-receipt-sha256 "$capacity_selector_receipt_sha256" \
        --capacity-probe "$output_dir/control/direct_kimi_capacity_probe.json" \
        --output "$output_dir/direct_kimi_capacity_certificate.json"
elif [[ "$execution_mode" == certified ]]; then
    certificate_args=(
        "$workflow_dir/certify_direct_kimi.py" "$certificate_mode"
        --run-dir "$output_dir"
        --expected-task-file "$task_file"
        --expected-task-file-sha256 "$task_sha256"
        --output "$output_dir/$([[ "$stage" == smoke || "$stage" == miniswe-smoke ]] \
            && printf smoke_checkpoint.json || printf checkpoint.json)"
    )
    if [[ "$identity_role" == kimi-direct-tb4 ]]; then
        certificate_args+=(
            --smoke-checkpoint "$smoke_checkpoint"
            --smoke-checkpoint-sha256 "$smoke_checkpoint_sha256"
        )
    fi
    "$x86_uv" run --no-project --offline --python "$python_bin" python3 "${certificate_args[@]}"
fi
if [[ "$stage" == capacity-smoke ]]; then
    printf '{"job_id":"%s","stage":"%s","state":"capacity-qualified"}\n' "$SLURM_JOB_ID" "$stage"
elif [[ "$stage" == smoke || "$stage" == miniswe-smoke || "$stage" == mobius-smoke ]]; then
    printf '{"job_id":"%s","stage":"%s","state":"capacity-limited-passed"}\n' "$SLURM_JOB_ID" "$stage"
elif [[ "$execution_mode" != certified ]]; then
    printf '{"certification_eligible":false,"job_id":"%s","stage":"%s","state":"diagnostic-completed","trace_rollout_eligible":false}\n' "$SLURM_JOB_ID" "$stage"
else
    printf '{"job_id":"%s","stage":"%s","state":"passed"}\n' "$SLURM_JOB_ID" "$stage"
fi
