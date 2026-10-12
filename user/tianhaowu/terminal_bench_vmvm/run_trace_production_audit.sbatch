#!/usr/bin/bash
#SBATCH --job-name=trace-production-audit
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/trace_production_audit_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/trace_production_audit_%j.log

set -euo pipefail
umask 077

fail() {
    printf '{"code":"%s","status":"error"}\n' "$1" >&2
    exit 2
}

# The submitter uses exact `/usr/bin/sbatch --export=NONE`. Reject injection
# variables before evaluating caller-controlled values. Slurm allocation
# variables are deliberately not forwarded to Python.
if [[ -n ${BASH_ENV+x} || -n ${ENV+x} || -n ${CDPATH+x} \
    || -n ${PYTHONHOME+x} || -n ${PYTHONPATH+x} || -n ${PYTHONSTARTUP+x} \
    || -n ${PYTHONPYCACHEPREFIX+x} || -n ${VIRTUAL_ENV+x} || -n ${CONDA_PREFIX+x} ]]; then
    fail ambient_environment_forbidden
fi
for variable in "${!BASH_FUNC_@}" "${!LD_@}" "${!UV_@}" "${!GIT_@}"; do
    [[ -z $variable ]] || fail ambient_environment_forbidden
done
if (( $# != 20 )) || [[ ! ${SLURM_JOB_ID:-} =~ ^[1-9][0-9]{0,19}$ ]]; then
    fail allocation_or_arguments_invalid
fi

readonly authorization=$1
readonly authorization_sha256=$2
readonly project_dir=$3
readonly revision=$4
readonly tree=$5
readonly submitter_sha256=$6
readonly wrapper_sha256=$7
readonly bootstrap_sha256=$8
readonly controller_sha256=$9
readonly submission_controller_sha256=${10}
readonly python_path=${11}
readonly python_sha256=${12}
readonly tls_certificate=${13}
readonly tls_key=${14}
readonly reservation=${15}
readonly expected_job_name=${16}
readonly reservation_device=${17}
readonly reservation_inode=${18}
readonly reservation_parent_device=${19}
readonly reservation_parent_inode=${20}

if [[ ! $authorization_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $submitter_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $wrapper_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $bootstrap_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $controller_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $submission_controller_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $python_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $revision =~ ^[0-9a-f]{40}$ || ! $tree =~ ^[0-9a-f]{40}$ \
    || ! $reservation_device =~ ^(0|[1-9][0-9]{0,19})$ \
    || ! $reservation_inode =~ ^[1-9][0-9]{0,19}$ \
    || ! $reservation_parent_device =~ ^(0|[1-9][0-9]{0,19})$ \
    || ! $reservation_parent_inode =~ ^[1-9][0-9]{0,19}$ ]]; then
    fail expected_identity_invalid
fi
for path in "$authorization" "$project_dir" "$python_path" "$tls_certificate" "$tls_key" "$reservation"; do
    [[ $path == /* && $path != *$'\n'* && $path != *$'\r'* ]] \
        || fail expected_path_invalid
done

readonly workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
readonly submitter="$workflow_dir/submit_trace_production_audit.sh"
readonly wrapper="$workflow_dir/run_trace_production_audit.sbatch"
readonly bootstrap="$workflow_dir/trace_production_bootstrap.py"
readonly controller="$workflow_dir/certify_trace_production.py"
readonly submission_controller="$workflow_dir/trace_production_submit_control.py"
readonly submitted_wrapper=${BASH_SOURCE[0]}
readonly -a git=(
    /usr/bin/env -i HOME=/nonexistent LANG=C LC_ALL=C PATH=/usr/bin:/bin
    GIT_ATTR_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
    GIT_NO_REPLACE_OBJECTS=1 GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0
    /usr/bin/git -c core.fsmonitor=false -c core.hooksPath=/dev/null
    -c core.untrackedCache=false
)
readonly pycache_prefix=/dev/null

[[ ${SLURM_JOB_NAME:-} == "$expected_job_name" ]] || fail allocation_or_arguments_invalid
submitted_sha=$(/usr/bin/sha256sum -- "$submitted_wrapper" 2>/dev/null) \
    || fail submitted_bytes_invalid
[[ ${submitted_sha%%  *} == "$wrapper_sha256" ]] || fail submitted_bytes_invalid

# A released allocation performs no setup until the one-shot submitter has
# durably published both admission files and sealed the reservation.
readonly admission_deadline=$(( SECONDS + 900 ))
while :; do
    if [[ -f "$reservation/submission_failure.json" ]]; then
        fail submission_failed
    fi
    if [[ -d $reservation && ! -L $reservation \
        && $(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "$reservation" 2>/dev/null) \
            == "$reservation_device:$reservation_inode:500:$(/usr/bin/id -u):2" ]]; then
        break
    fi
    (( SECONDS < admission_deadline )) || fail submission_admission_timeout
    /usr/bin/sleep 1
done
shopt -s nullglob dotglob
reservation_entries=("$reservation"/*)
(( ${#reservation_entries[@]} == 4 )) || fail submission_admission_invalid
declare -A expected_reservation_entries=(
    [activation_permit.json]=1
    [held_authorization.json]=1
    [launch_intent.json]=1
    [submission_receipt.json]=1
)
for entry in "${reservation_entries[@]}"; do
    [[ ${expected_reservation_entries[${entry##*/}]+yes} ]] || fail submission_admission_invalid
done
shopt -u nullglob dotglob

trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

digest_file() {
    local output rc
    set +e
    output=$(/usr/bin/sha256sum -- "$1" 2>/dev/null)
    rc=$?
    set -e
    (( rc == 0 )) || fail source_file_invalid
    printf '%s' "${output%% *}"
}

validate_source() {
    local output rc observed_tree tree_rc path expected observed_blob blob_rc
    local record mode kind object recorded_path extra
    [[ $(/usr/bin/realpath -e -- "$project_dir" 2>/dev/null) == "$project_dir" \
        && -d $project_dir && ! -L $project_dir ]] || fail source_path_invalid
    set +e
    output=$("${git[@]}" -C "$project_dir" rev-parse --abbrev-ref HEAD 2>/dev/null)
    rc=$?
    set -e
    (( rc == 0 )) && [[ $output == HEAD ]] || fail source_not_detached
    set +e
    output=$("${git[@]}" -C "$project_dir" rev-parse --verify 'HEAD^{commit}' 2>/dev/null)
    rc=$?
    observed_tree=$("${git[@]}" -C "$project_dir" rev-parse --verify 'HEAD^{tree}' 2>/dev/null)
    tree_rc=$?
    set -e
    (( rc == 0 && tree_rc == 0 )) && [[ $output == "$revision" && $observed_tree == "$tree" ]] \
        || fail source_revision_mismatch
    set +e
    output=$("${git[@]}" -C "$project_dir" status --porcelain=v1 --untracked-files=all --ignore-submodules=none 2>/dev/null)
    rc=$?
    set -e
    (( rc == 0 )) && [[ -z $output ]] || fail source_worktree_not_clean
    set +e
    output=$("${git[@]}" -C "$project_dir" ls-files --others --ignored --exclude-standard -- \
        ':(glob)**/*.py' ':(glob)**/*.pyc' ':(glob)**/*.so' ':(glob)**/*.pyd' \
        ':(glob)**/sitecustomize.py' ':(glob)**/usercustomize.py' 2>/dev/null)
    rc=$?
    set -e
    (( rc == 0 )) && [[ -z $output ]] || fail source_ignored_importable_forbidden
    while (( $# )); do
        path=$1
        expected=$2
        shift 2
        set +e
        record=$("${git[@]}" -C "$project_dir" ls-tree "$revision" -- "${path#"$project_dir/"}" 2>/dev/null)
        rc=$?
        observed_blob=$("${git[@]}" -C "$project_dir" hash-object --no-filters -- "$path" 2>/dev/null)
        blob_rc=$?
        set -e
        IFS=$' \t' read -r mode kind object recorded_path extra <<< "$record"
        (( rc == 0 && blob_rc == 0 )) \
            && [[ -z ${extra:-} && $kind == blob && $recorded_path == "${path#"$project_dir/"}" \
                && ( $mode == 100644 || $mode == 100755 ) && $object == "$observed_blob" \
                && $(digest_file "$path") == "$expected" ]] \
            || fail source_file_invalid
    done
}

validate_inputs() {
    validate_source \
        "$submitter" "$submitter_sha256" \
        "$wrapper" "$wrapper_sha256" \
        "$bootstrap" "$bootstrap_sha256" \
        "$controller" "$controller_sha256" \
        "$submission_controller" "$submission_controller_sha256"
    [[ -f $submitted_wrapper && ! -L $submitted_wrapper \
        && $(digest_file "$submitted_wrapper") == "$wrapper_sha256" \
        && $(digest_file "$authorization") == "$authorization_sha256" \
        && $(digest_file "$python_path") == "$python_sha256" ]] \
        || fail submitted_bytes_invalid
    [[ $(/usr/bin/stat -Lc '%a:%u:%h' -- "$authorization" 2>/dev/null) \
        == "400:$(/usr/bin/id -u):1" ]] || fail authorization_invalid
    [[ $(/usr/bin/stat -Lc '%a:%u:%h' -- "$python_path" 2>/dev/null) == "755:0:1" \
        && $(/usr/bin/realpath -e -- "$python_path" 2>/dev/null) == "$python_path" ]] \
        || fail python_runtime_invalid
    for credential in "$tls_certificate" "$tls_key"; do
        [[ -f $credential && ! -L $credential && -r $credential ]] \
            || fail scheduler_auth_invalid
    done
}

validate_inputs
[[ -c $pycache_prefix && ! -L $pycache_prefix \
    && $(/usr/bin/stat -Lc '%a:%u:%g:%h:%t:%T' -- "$pycache_prefix" 2>/dev/null) \
    == "666:0:0:1:1:3" \
    && $(/usr/bin/realpath -e -- "$pycache_prefix" 2>/dev/null) == "$pycache_prefix" ]] \
    || fail pycache_prefix_invalid

# Open both executable source files before the final source gate. Python runs
# the captured bootstrap bytes; the bootstrap runs the captured controller.
exec 8<"$bootstrap" || fail bootstrap_source_invalid
exec 9<"$controller" || fail controller_source_invalid
validate_inputs
[[ $(digest_file /proc/self/fd/8) == "$bootstrap_sha256" \
    && $(digest_file /proc/self/fd/9) == "$controller_sha256" ]] \
    || fail captured_source_invalid

readonly loader='import os,sys; fd=int(sys.argv[1]); n=os.fstat(fd).st_size; b=os.pread(fd,n,0); n==len(b) or (_ for _ in ()).throw(RuntimeError()); p=sys.argv[2]; sys.argv=sys.argv[2:]; g={"__builtins__":__builtins__,"__file__":p,"__name__":"__main__","__package__":None}; exec(compile(b,p,"exec"),g)'
set +e
/usr/bin/env -i \
    HOME=/nonexistent LANG=C LC_ALL=C PATH=/usr/bin:/bin \
    PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPYCACHEPREFIX="$pycache_prefix" PYTHONSAFEPATH=1 \
    THRIFT_TLS_CL_CERT_PATH="$tls_certificate" THRIFT_TLS_CL_KEY_PATH="$tls_key" \
    "$python_path" -I -S -B -c "$loader" 8 "$bootstrap" \
    "$authorization" "$authorization_sha256" 9 "$controller_sha256" "$pycache_prefix" \
    "$reservation" "$SLURM_JOB_ID" "$SLURM_JOB_NAME" \
    "$reservation_device" "$reservation_inode" \
    "$reservation_parent_device" "$reservation_parent_inode"
audit_rc=$?
set -e
(( audit_rc == 0 )) || exit "$audit_rc"
