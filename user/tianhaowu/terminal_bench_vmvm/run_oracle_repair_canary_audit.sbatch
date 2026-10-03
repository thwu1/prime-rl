#!/bin/bash
# SECURITY: do not pass this file directly to `sbatch`; Slurm executes a spool
# copy, which this launcher intentionally rejects. Submit explicit resources
# with `sbatch --wrap='exec /bin/bash <canonical-frozen-launcher>'` as documented.
#SBATCH --job-name=oracle-repair-audit
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/oracle_repair_audit_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/oracle_repair_audit_%j.log

set -euo pipefail
umask 077

# Bootstrap from fixed tools and a closed Git environment. Submission-time
# repository/config redirects must not affect the reviewed checkout.
for git_variable in "${!GIT_@}"; do
    unset "$git_variable"
done
export PATH=/usr/bin:/bin
export GIT_ATTR_NOSYSTEM=1
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1
export GIT_NO_REPLACE_OBJECTS=1
export GIT_OPTIONAL_LOCKS=0
git_command=(
    /usr/bin/git
    -c core.fsmonitor=false
    -c core.hooksPath=/dev/null
    -c core.untrackedCache=false
)

fail() {
    printf '{"code":"%s","status":"error"}\n' "$1" >&2
    exit 2
}

if (( $# != 0 )); then
    fail arguments_forbidden
fi
if [[ ! ${SLURM_JOB_ID:-} =~ ^[1-9][0-9]*$ ]]; then
    fail slurm_allocation_required
fi

required=(
    ORACLE_AUDIT_SOURCE_PROJECT_DIR
    ORACLE_AUDIT_SOURCE_REVISION
    ORACLE_AUDIT_EXECUTION_PROJECT_DIR
    ORACLE_AUDIT_EXECUTION_REVISION
    ORACLE_AUDIT_SOURCE_DIR
    ORACLE_AUDIT_BUILDER_RECEIPT
    ORACLE_AUDIT_TASK_FILE
    ORACLE_AUDIT_CANARY_DIR
    ORACLE_AUDIT_RUNTIME_ROOT
    ORACLE_AUDIT_RUNTIME_DIR
    ORACLE_AUDIT_CERTIFICATE_ROOT
    ORACLE_AUDIT_CERTIFICATE
)
for variable in "${required[@]}"; do
    if [[ -z ${!variable:-} ]]; then
        fail required_environment_missing
    fi
done
if [[ ! $ORACLE_AUDIT_SOURCE_REVISION =~ ^[0-9a-f]{40}$ \
    || ! $ORACLE_AUDIT_EXECUTION_REVISION =~ ^[0-9a-f]{40}$ ]]; then
    fail expected_revision_invalid
fi

execution_dir=$ORACLE_AUDIT_EXECUTION_PROJECT_DIR
workflow_dir="$execution_dir/user/tianhaowu/terminal_bench_vmvm"
controller="$workflow_dir/run_oracle_repair_canary_audit.py"
expected_launcher="$workflow_dir/run_oracle_repair_canary_audit.sbatch"
submitted_launcher=${BASH_SOURCE[0]}
auditor="$workflow_dir/audit_oracle_repair_canary.py"
if [[ $execution_dir != /* ]]; then
    fail execution_path_unsafe
fi
canonical_execution=$(/usr/bin/realpath -e -- "$execution_dir") || fail execution_path_unsafe
if [[ $canonical_execution != "$execution_dir" ]]; then
    fail execution_path_unsafe
fi
set +e
"${git_command[@]}" -C "$execution_dir" symbolic-ref -q HEAD >/dev/null 2>&1
symbolic_status=$?
set -e
if (( symbolic_status != 1 )); then
    fail execution_checkout_not_detached
fi
observed_revision=$("${git_command[@]}" -C "$execution_dir" rev-parse --verify 'HEAD^{commit}') \
    || fail execution_revision_unverifiable
if [[ $observed_revision != "$ORACLE_AUDIT_EXECUTION_REVISION" ]]; then
    fail execution_revision_mismatch
fi
execution_status=$("${git_command[@]}" -C "$execution_dir" status --porcelain=v1 --untracked-files=all) \
    || fail execution_worktree_unverifiable
if [[ -n $execution_status ]]; then
    fail execution_worktree_not_clean
fi
if [[ $submitted_launcher != /* || ! -f $controller || -L $controller \
    || ! -f $auditor || -L $auditor || ! -f $expected_launcher \
    || -L $expected_launcher || ! -f $submitted_launcher || -L $submitted_launcher ]]; then
    fail launcher_origin_mismatch
fi
canonical_submitted=$(/usr/bin/realpath -e -- "$submitted_launcher") \
    || fail launcher_origin_mismatch
canonical_expected=$(/usr/bin/realpath -e -- "$expected_launcher") \
    || fail launcher_origin_mismatch
if [[ $canonical_submitted != "$submitted_launcher" \
    || $canonical_expected != "$expected_launcher" \
    || $canonical_submitted != "$canonical_expected" ]]; then
    fail launcher_origin_mismatch
fi

for relative in \
    user/tianhaowu/terminal_bench_vmvm/run_oracle_repair_canary_audit.py \
    user/tianhaowu/terminal_bench_vmvm/audit_oracle_repair_canary.py \
    user/tianhaowu/terminal_bench_vmvm/build_oracle_repair_canary.py \
    user/tianhaowu/terminal_bench_vmvm/export_oracle_tasks.py \
    user/tianhaowu/terminal_bench_vmvm/run_oracle_repair_canary_audit.sbatch; do
    record=$("${git_command[@]}" -C "$execution_dir" ls-tree "$observed_revision" -- "$relative") \
        || fail execution_script_revision_unverifiable
    IFS=$' \t' read -r object_mode object_type object_id object_path extra <<< "$record"
    if [[ -n ${extra:-} || $object_type != blob \
        || ( $object_mode != 100644 && $object_mode != 100755 ) \
        || ! $object_id =~ ^[0-9a-f]{40}$ || $object_path != "$relative" ]]; then
        fail execution_script_revision_mismatch
    fi
    observed_blob=$("${git_command[@]}" -C "$execution_dir" hash-object --no-filters -- "$execution_dir/$relative") \
        || fail execution_script_revision_unverifiable
    if [[ $observed_blob != "$object_id" ]]; then
        fail execution_script_revision_mismatch
    fi
done

python_bin=/usr/bin/python3
expected_total=${ORACLE_AUDIT_EXPECTED_TOTAL:-2538}
controls=${ORACLE_AUDIT_CONTROLS:-20}
minimum_recovered=${ORACLE_AUDIT_MINIMUM_RECOVERED:-12}
source_wheel_policy_sha256=${ORACLE_AUDIT_SOURCE_WHEEL_POLICY_SHA256:-}
source_wheel_attestations=${ORACLE_AUDIT_SOURCE_WHEEL_ATTESTATIONS:-}
seed=${ORACLE_AUDIT_SEED:-oracle-dependency-overlay-v1}
if [[ ! $expected_total =~ ^[1-9][0-9]*$ \
    || ! $controls =~ ^(0|[1-9][0-9]*)$ \
    || ! $minimum_recovered =~ ^(0|[1-9][0-9]*)$ ]]; then
    fail audit_gate_invalid
fi
if [[ ( -n $source_wheel_policy_sha256 && -z $source_wheel_attestations ) \
    || ( -z $source_wheel_policy_sha256 && -n $source_wheel_attestations ) ]]; then
    fail source_wheel_gate_invalid
fi
if [[ -n $source_wheel_policy_sha256 \
    && ( ! $source_wheel_policy_sha256 =~ ^[0-9a-f]{64}$ \
        || ! $source_wheel_attestations =~ ^[1-9][0-9]*$ ) ]]; then
    fail source_wheel_gate_invalid
fi

source_wheel_args=()
if [[ -n $source_wheel_policy_sha256 ]]; then
    source_wheel_args+=(
        --expected-source-wheel-policy-sha256 "$source_wheel_policy_sha256"
        --expected-source-wheel-attestations "$source_wheel_attestations"
    )
fi

export PYTHONDONTWRITEBYTECODE=1
unset PYTHONHOME PYTHONPATH
cd "$execution_dir"
exec "$python_bin" "$controller" \
    --source-project-dir "$ORACLE_AUDIT_SOURCE_PROJECT_DIR" \
    --expected-source-revision "$ORACLE_AUDIT_SOURCE_REVISION" \
    --execution-project-dir "$ORACLE_AUDIT_EXECUTION_PROJECT_DIR" \
    --expected-execution-revision "$ORACLE_AUDIT_EXECUTION_REVISION" \
    --source-oracle-dir "$ORACLE_AUDIT_SOURCE_DIR" \
    --builder-receipt "$ORACLE_AUDIT_BUILDER_RECEIPT" \
    --task-file "$ORACLE_AUDIT_TASK_FILE" \
    --canary-dir "$ORACLE_AUDIT_CANARY_DIR" \
    --runtime-root "$ORACLE_AUDIT_RUNTIME_ROOT" \
    --runtime-dir "$ORACLE_AUDIT_RUNTIME_DIR" \
    --certificate-root "$ORACLE_AUDIT_CERTIFICATE_ROOT" \
    --certificate "$ORACLE_AUDIT_CERTIFICATE" \
    --expected-total "$expected_total" \
    --controls "$controls" \
    --minimum-recovered "$minimum_recovered" \
    "${source_wheel_args[@]}" \
    --seed "$seed"
