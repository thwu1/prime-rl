#!/usr/bin/env bash
set -euo pipefail
umask 077

fail() {
    printf '{"code":"%s","state":"error"}\n' "$1" >&2
    exit 2
}

required=(
    QWEN_V6_PACKAGE_PROJECT_DIR
    QWEN_V6_PACKAGE_EXPECTED_PROJECT_REVISION
    QWEN_V6_PACKAGE_EXPECTED_POSTPROCESSOR_REVISION
    QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_REVISION
    QWEN_V6_PACKAGE_EXPECTED_SOURCE_JOB
    QWEN_V6_PACKAGE_SELECTION_CONTRACT_SHA256
    QWEN_V6_PACKAGE_PACKAGER_SHA256
    QWEN_V6_PACKAGE_WORKER_SHA256
    QWEN_V6_PACKAGE_CANONICAL_TASK_FILE_SHA256
    QWEN_V6_PACKAGE_POSTRUN_WORKER
    QWEN_V6_PACKAGE_POSTRUN_WORKER_SHA256
    QWEN_V6_PACKAGE_UNFILTERED_DIR
    QWEN_V6_PACKAGE_RETRY_CERTIFICATE
    QWEN_V6_PACKAGE_SUPERSEDING_CERTIFICATE
    QWEN_V6_PACKAGE_POSTRUN_RECEIPT
    QWEN_V6_PACKAGE_PREVIOUS_MANIFEST
    QWEN_V6_PACKAGE_PREVIOUS_MANIFEST_SHA256
    QWEN_V6_PACKAGE_EXPECTED_RESULTS_SHA256
    QWEN_V6_PACKAGE_EXPECTED_RECOVERED_CERTIFICATE_SHA256
    QWEN_V6_PACKAGE_EXPECTED_MERGE_MANIFEST_SHA256
    QWEN_V6_PACKAGE_EXPECTED_RETRY_CERTIFICATE_SHA256
    QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_CERTIFICATE_SHA256
    QWEN_V6_PACKAGE_EXPECTED_POSTRUN_RECEIPT_SHA256
    QWEN_V6_PACKAGE_OUTPUT_DIR
    QWEN_V6_PACKAGE_JOBID_FILE
)
for variable in "${required[@]}"; do
    value=${!variable:-}
    [[ -n $value && $value != *,* && $value != *$'\n'* && $value != *$'\r'* ]] \
        || fail required_environment_invalid
done
[[ $# -eq 1 && $1 =~ ^[1-9][0-9]*$ ]] || fail postrun_job_id_required
postrun_job=$1
[[ -n ${TMUX:-} && -n ${TMUX_PANE:-} \
    && "$(tmux display-message -p -t "$TMUX_PANE" '#S:#W.#P')" == swebench_vmvm:Launcher.0 ]] \
    || fail launcher_pane_mismatch
[[ $QWEN_V6_PACKAGE_EXPECTED_POSTPROCESSOR_REVISION \
        == 108b713af332b6865c49c3b146f3fa2158fe790a \
    && $QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_REVISION \
        == d9a4eb07de3b769899c0e77eedf5da5f6c35ab61 \
    && $QWEN_V6_PACKAGE_EXPECTED_SOURCE_JOB == 1579607 \
    && $QWEN_V6_PACKAGE_SELECTION_CONTRACT_SHA256 \
        == 5369194fc1bea5dd72c20457a8fd1fac906144c8beb4bc20d77727fb77c8b228 \
    && $QWEN_V6_PACKAGE_CANONICAL_TASK_FILE_SHA256 \
        == 5b2ed7c5b166a6570b46d3dacff680c5ba6ff22f7e02e57e273eb442e6842b8c \
    && $QWEN_V6_PACKAGE_PREVIOUS_MANIFEST_SHA256 \
        == 5ab6b9482d7eff98aea424546592fc5a61e3af11bae9c4ea11f48f4774cb0ac2 ]] \
    || fail package_run_identity_invalid
for variable in \
    QWEN_V6_PACKAGE_POSTRUN_WORKER_SHA256 \
    QWEN_V6_PACKAGE_EXPECTED_RESULTS_SHA256 \
    QWEN_V6_PACKAGE_EXPECTED_RECOVERED_CERTIFICATE_SHA256 \
    QWEN_V6_PACKAGE_EXPECTED_MERGE_MANIFEST_SHA256 \
    QWEN_V6_PACKAGE_EXPECTED_RETRY_CERTIFICATE_SHA256 \
    QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_CERTIFICATE_SHA256 \
    QWEN_V6_PACKAGE_EXPECTED_POSTRUN_RECEIPT_SHA256; do
    [[ ${!variable} =~ ^[0-9a-f]{64}$ ]] || fail package_digest_invalid
done

project=$(realpath -e -- "$QWEN_V6_PACKAGE_PROJECT_DIR")
packager="$project/user/tianhaowu/terminal_bench_vmvm/package_qwen_recovered_unfiltered_traces.sh"
worker="$project/user/tianhaowu/terminal_bench_vmvm/package_qwen_recovered_unfiltered_traces.sbatch"
[[ $QWEN_V6_PACKAGE_EXPECTED_PROJECT_REVISION =~ ^[0-9a-f]{40}$ \
    && $QWEN_V6_PACKAGE_PACKAGER_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_WORKER_SHA256 =~ ^[0-9a-f]{64}$ \
    && -f $packager && ! -L $packager \
    && -f $worker && ! -L $worker \
    && "$(git -C "$project" rev-parse --show-toplevel)" == "$project" \
    && "$(git -C "$project" rev-parse HEAD)" == "$QWEN_V6_PACKAGE_EXPECTED_PROJECT_REVISION" \
    && -z "$(git -C "$project" status --porcelain=v1 --untracked-files=all)" \
    && "$(sha256sum "$packager" | cut -d' ' -f1)" == "$QWEN_V6_PACKAGE_PACKAGER_SHA256" \
    && "$(sha256sum "$worker" | cut -d' ' -f1)" == "$QWEN_V6_PACKAGE_WORKER_SHA256" ]] \
    || fail package_source_identity_invalid
chunk_bytes=${QWEN_V6_PACKAGE_CHUNK_BYTES:-95000000}
compression_level=${QWEN_V6_PACKAGE_ZSTD_LEVEL:-19}
[[ $chunk_bytes =~ ^[1-9][0-9]*$ && $chunk_bytes -lt 100000000 \
    && $compression_level =~ ^[1-9][0-9]*$ && $compression_level -le 19 ]] \
    || fail package_configuration_invalid
[[ ! -e $QWEN_V6_PACKAGE_OUTPUT_DIR && ! -L $QWEN_V6_PACKAGE_OUTPUT_DIR \
    && ! -e $QWEN_V6_PACKAGE_JOBID_FILE && ! -L $QWEN_V6_PACKAGE_JOBID_FILE ]] \
    || fail output_exists
jobid_parent=$(realpath -e -- "$(dirname -- "$QWEN_V6_PACKAGE_JOBID_FILE")")
[[ $QWEN_V6_PACKAGE_JOBID_FILE == "$jobid_parent/$(basename -- "$QWEN_V6_PACKAGE_JOBID_FILE")" ]] \
    || fail jobid_path_invalid
reservation="$QWEN_V6_PACKAGE_JOBID_FILE.lock"
mkdir -m 700 -- "$reservation" 2>/dev/null || fail submission_already_reserved
submitted=0
cleanup() {
    if [[ $submitted == 0 && -d $reservation ]]; then
        rmdir -- "$reservation" || true
    fi
}
trap cleanup EXIT INT TERM

mapfile -t accounting < <(sacct -j "$postrun_job" -X -n -P -o JobIDRaw,State,ExitCode \
    | sed '/^[[:space:]]*$/d')
[[ ${#accounting[@]} -eq 1 ]] || fail postrun_job_accounting_invalid
IFS='|' read -r observed_job observed_state observed_exit <<<"${accounting[0]}"
[[ $observed_job == "$postrun_job" ]] || fail postrun_job_accounting_invalid
case "$observed_state" in
    PENDING|RUNNING|COMPLETING) ;;
    COMPLETED) [[ $observed_exit == 0:0 ]] || fail postrun_job_not_successful ;;
    *) fail postrun_job_state_invalid ;;
esac

export_names=(
    QWEN_V6_PACKAGE_PROJECT_DIR
    QWEN_V6_PACKAGE_EXPECTED_PROJECT_REVISION
    QWEN_V6_PACKAGE_EXPECTED_POSTPROCESSOR_REVISION
    QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_REVISION
    QWEN_V6_PACKAGE_EXPECTED_SOURCE_JOB
    QWEN_V6_PACKAGE_SELECTION_CONTRACT_SHA256
    QWEN_V6_PACKAGE_PACKAGER_SHA256
    QWEN_V6_PACKAGE_WORKER_SHA256
    QWEN_V6_PACKAGE_CANONICAL_TASK_FILE_SHA256
    QWEN_V6_PACKAGE_POSTRUN_WORKER
    QWEN_V6_PACKAGE_POSTRUN_WORKER_SHA256
    QWEN_V6_PACKAGE_UNFILTERED_DIR
    QWEN_V6_PACKAGE_RETRY_CERTIFICATE
    QWEN_V6_PACKAGE_SUPERSEDING_CERTIFICATE
    QWEN_V6_PACKAGE_POSTRUN_RECEIPT
    QWEN_V6_PACKAGE_PREVIOUS_MANIFEST
    QWEN_V6_PACKAGE_PREVIOUS_MANIFEST_SHA256
    QWEN_V6_PACKAGE_EXPECTED_RESULTS_SHA256
    QWEN_V6_PACKAGE_EXPECTED_RECOVERED_CERTIFICATE_SHA256
    QWEN_V6_PACKAGE_EXPECTED_MERGE_MANIFEST_SHA256
    QWEN_V6_PACKAGE_EXPECTED_RETRY_CERTIFICATE_SHA256
    QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_CERTIFICATE_SHA256
    QWEN_V6_PACKAGE_EXPECTED_POSTRUN_RECEIPT_SHA256
    QWEN_V6_PACKAGE_OUTPUT_DIR
)
exports=NONE
for variable in "${export_names[@]}"; do
    exports+=",$variable=${!variable}"
done
exports+=",QWEN_V6_PACKAGE_POSTRUN_JOB_ID=$postrun_job"
exports+=",QWEN_V6_PACKAGE_CHUNK_BYTES=$chunk_bytes"
exports+=",QWEN_V6_PACKAGE_ZSTD_LEVEL=$compression_level"

submitted=1
jobid=$(sbatch --parsable --dependency="afterok:$postrun_job" --export="$exports" "$worker")
[[ $jobid =~ ^[1-9][0-9]*$ ]] || fail submission_receipt_invalid
set -o noclobber
printf '%s\n' "$jobid" >"$QWEN_V6_PACKAGE_JOBID_FILE"
rmdir -- "$reservation"
submitted=2
printf '{"dependency":%s,"job_id":%s,"state":"submitted"}\n' "$postrun_job" "$jobid"
