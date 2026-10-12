#!/usr/bin/bash
# Submit exactly one isolated post-production trace audit.

set -euo pipefail
umask 077

fail() {
    printf '{"code":"%s","status":"error"}\n' "$1" >&2
    exit 2
}

# This script must itself be entered through the documented `/usr/bin/env -i`
# command.  Reject injection-bearing variables before any repository or
# scheduler command is evaluated.
if [[ -n ${BASH_ENV+x} || -n ${ENV+x} || -n ${CDPATH+x} \
    || -n ${PYTHONHOME+x} || -n ${PYTHONPATH+x} || -n ${PYTHONSTARTUP+x} \
    || -n ${VIRTUAL_ENV+x} || -n ${CONDA_PREFIX+x} ]]; then
    fail ambient_environment_forbidden
fi
for variable in "${!BASH_FUNC_@}" "${!LD_@}" "${!UV_@}" "${!GIT_@}"; do
    [[ -z $variable ]] || fail ambient_environment_forbidden
done
if [[ ${HOME:-} != /nonexistent || ${PATH:-} != /usr/bin:/bin \
    || ${LANG:-} != C || ${LC_ALL:-} != C ]]; then
    fail ambient_environment_invalid
fi
if (( $# != 12 )); then
    fail arguments_invalid
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

if [[ ! $authorization_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $submitter_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $wrapper_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $bootstrap_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $controller_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $submission_controller_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $python_sha256 =~ ^[0-9a-f]{64}$ \
    || ! $revision =~ ^[0-9a-f]{40}$ || ! $tree =~ ^[0-9a-f]{40}$ ]]; then
    fail expected_identity_invalid
fi
for path in "$authorization" "$project_dir" "$python_path" \
    "${THRIFT_TLS_CL_CERT_PATH:-}" "${THRIFT_TLS_CL_KEY_PATH:-}"; do
    [[ $path == /* && $path != *$'\n'* && $path != *$'\r'* ]] \
        || fail expected_path_invalid
done

readonly workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
readonly submitter="$workflow_dir/submit_trace_production_audit.sh"
readonly wrapper="$workflow_dir/run_trace_production_audit.sbatch"
readonly bootstrap="$workflow_dir/trace_production_bootstrap.py"
readonly controller="$workflow_dir/certify_trace_production.py"
readonly submission_controller="$workflow_dir/trace_production_submit_control.py"
readonly -a git=(
    /usr/bin/env -i HOME=/nonexistent LANG=C LC_ALL=C PATH=/usr/bin:/bin
    GIT_ATTR_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
    GIT_NO_REPLACE_OBJECTS=1 GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0
    /usr/bin/git -c core.fsmonitor=false -c core.hooksPath=/dev/null
    -c core.untrackedCache=false
)

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

validate_source \
    "$submitter" "$submitter_sha256" \
    "$wrapper" "$wrapper_sha256" \
    "$bootstrap" "$bootstrap_sha256" \
    "$controller" "$controller_sha256" \
    "$submission_controller" "$submission_controller_sha256"
readonly submitter_fd=${TRACE_SUBMITTER_SEALED_FD:-}
[[ $submitter_fd == 7 \
    && ${BASH_SOURCE[0]} == "/proc/self/fd/$submitter_fd" \
    && $(digest_file "${BASH_SOURCE[0]}") == "$submitter_sha256" \
    && $(/usr/bin/stat -Lc '%F:%h:%u' -- "${BASH_SOURCE[0]}" 2>/dev/null) \
        == "regular file:0:$(/usr/bin/id -u)" ]] \
    || fail submitter_self_binding_invalid
[[ $(digest_file "$python_path") == "$python_sha256" ]] || fail python_runtime_invalid
[[ -f $authorization && ! -L $authorization \
    && $(digest_file "$authorization") == "$authorization_sha256" \
    && $(/usr/bin/stat -Lc '%a:%u:%h' -- "$authorization" 2>/dev/null) == "400:$(/usr/bin/id -u):1" ]] \
    || fail authorization_invalid

# Revalidate every submitted byte immediately adjacent to the sole scheduler
# call.  The batch wrapper independently repeats the complete validation.
validate_source \
    "$submitter" "$submitter_sha256" \
    "$wrapper" "$wrapper_sha256" \
    "$bootstrap" "$bootstrap_sha256" \
    "$controller" "$controller_sha256" \
    "$submission_controller" "$submission_controller_sha256"
[[ $(digest_file "$authorization") == "$authorization_sha256" \
    && $(digest_file "$python_path") == "$python_sha256" ]] \
    || fail final_submission_gate_changed

# Capture the submission controller and batch wrapper before the state machine
# begins. The controller sends the captured wrapper bytes to `sbatch -`; no
# mutable script pathname is handed to Slurm.
exec 8<"$submission_controller" || fail submission_controller_invalid
exec 9<"$wrapper" || fail wrapper_capture_invalid
[[ $(digest_file /proc/self/fd/8) == "$submission_controller_sha256" \
    && $(digest_file /proc/self/fd/9) == "$wrapper_sha256" ]] \
    || fail captured_source_invalid

readonly loader='import hashlib,os,sys; fd=int(sys.argv[1]); n=os.fstat(fd).st_size; b=os.pread(fd,n,0); len(b)==n or (_ for _ in ()).throw(RuntimeError()); hashlib.sha256(b).hexdigest()==sys.argv[2] or (_ for _ in ()).throw(RuntimeError()); p=sys.argv[3]; sys.argv=sys.argv[3:]; g={"__builtins__":__builtins__,"__file__":p,"__name__":"__main__","__package__":None}; exec(compile(b,p,"exec"),g)'
exec /usr/bin/env -i \
    HOME=/nonexistent LANG=C LC_ALL=C PATH=/usr/bin:/bin \
    THRIFT_TLS_CL_CERT_PATH="$THRIFT_TLS_CL_CERT_PATH" \
    THRIFT_TLS_CL_KEY_PATH="$THRIFT_TLS_CL_KEY_PATH" \
    "$python_path" -I -S -B -c "$loader" 8 "$submission_controller_sha256" \
    "$submission_controller" \
    --authorization "$authorization" \
    --authorization-sha256 "$authorization_sha256" \
    --project-dir "$project_dir" --revision "$revision" --tree "$tree" \
    --submitter-sha256 "$submitter_sha256" --wrapper-sha256 "$wrapper_sha256" \
    --bootstrap-sha256 "$bootstrap_sha256" --controller-sha256 "$controller_sha256" \
    --submission-controller-sha256 "$submission_controller_sha256" \
    --python-path "$python_path" --python-sha256 "$python_sha256" \
    --tls-certificate "$THRIFT_TLS_CL_CERT_PATH" --tls-key "$THRIFT_TLS_CL_KEY_PATH" \
    --submitter-fd "$submitter_fd" --wrapper-fd 9
