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
    QWEN_V6_PACKAGE_EXPECTED_RETRY_MODULE_SHA256
    QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_EXPORTER_SHA256
    QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_EXPORTER_SHA256
    QWEN_V6_PACKAGE_EXPECTED_SUPERSESSION_MODULE_SHA256
    QWEN_V6_PACKAGE_EXPECTED_AUDIT_TRACES_SHA256
    QWEN_V6_PACKAGE_EXPECTED_VERIFIER_REVISION
    QWEN_V6_PACKAGE_EXPECTED_RENDERER_REVISION
    QWEN_V6_PACKAGE_EXPECTED_MODEL_IO_CONTRACT_ID
    QWEN_V6_PACKAGE_EXPECTED_MODEL_IO_CONTRACT_SHA256
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
    QWEN_V6_PACKAGE_POSTRUN_JOB_ID
    QWEN_V6_PACKAGE_OUTPUT_DIR
)
for variable in "${required[@]}"; do
    [[ -n ${!variable:-} ]] || fail required_environment_missing
done

for variable in \
    QWEN_V6_PACKAGE_PROJECT_DIR \
    QWEN_V6_PACKAGE_UNFILTERED_DIR \
    QWEN_V6_PACKAGE_RETRY_CERTIFICATE \
    QWEN_V6_PACKAGE_SUPERSEDING_CERTIFICATE \
    QWEN_V6_PACKAGE_POSTRUN_RECEIPT \
    QWEN_V6_PACKAGE_PREVIOUS_MANIFEST \
    QWEN_V6_PACKAGE_POSTRUN_WORKER; do
    value=${!variable}
    [[ $value == /* && ! -L $value && "$(realpath -e -- "$value")" == "$value" ]] \
        || fail input_path_invalid
done
project=$QWEN_V6_PACKAGE_PROJECT_DIR
unfiltered=$QWEN_V6_PACKAGE_UNFILTERED_DIR
retry_certificate=$QWEN_V6_PACKAGE_RETRY_CERTIFICATE
superseding_certificate=$QWEN_V6_PACKAGE_SUPERSEDING_CERTIFICATE
postrun_receipt=$QWEN_V6_PACKAGE_POSTRUN_RECEIPT
previous_manifest=$QWEN_V6_PACKAGE_PREVIOUS_MANIFEST
postrun_worker=$QWEN_V6_PACKAGE_POSTRUN_WORKER
output=$QWEN_V6_PACKAGE_OUTPUT_DIR
chunk_bytes=${QWEN_V6_PACKAGE_CHUNK_BYTES:-95000000}
compression_level=${QWEN_V6_PACKAGE_ZSTD_LEVEL:-19}
archive_root=qwen-2499-recovered-unfiltered-108b713af-v6
archive_name=qwen-2499-recovered-unfiltered-108b713af-v6.tar.zst
packager=$(realpath -e -- "${BASH_SOURCE[0]}")
package_worker="$project/user/tianhaowu/terminal_bench_vmvm/package_qwen_recovered_unfiltered_traces.sbatch"

[[ $QWEN_V6_PACKAGE_EXPECTED_PROJECT_REVISION =~ ^[0-9a-f]{40}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_POSTPROCESSOR_REVISION =~ ^[0-9a-f]{40}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_REVISION =~ ^[0-9a-f]{40}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_RETRY_MODULE_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_EXPORTER_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_EXPORTER_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_SUPERSESSION_MODULE_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_AUDIT_TRACES_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_VERIFIER_REVISION =~ ^[0-9a-f]{40}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_RENDERER_REVISION =~ ^[0-9a-f]{40}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_MODEL_IO_CONTRACT_ID =~ ^[A-Za-z0-9._+-]+$ \
    && $QWEN_V6_PACKAGE_EXPECTED_MODEL_IO_CONTRACT_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_SOURCE_JOB == 1579607 \
    && $QWEN_V6_PACKAGE_POSTRUN_JOB_ID =~ ^[1-9][0-9]*$ \
    && $QWEN_V6_PACKAGE_SELECTION_CONTRACT_SHA256 \
        == 5369194fc1bea5dd72c20457a8fd1fac906144c8beb4bc20d77727fb77c8b228 \
    && $QWEN_V6_PACKAGE_PACKAGER_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_WORKER_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_CANONICAL_TASK_FILE_SHA256 \
        == 5b2ed7c5b166a6570b46d3dacff680c5ba6ff22f7e02e57e273eb442e6842b8c \
    && $QWEN_V6_PACKAGE_POSTRUN_WORKER_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_PREVIOUS_MANIFEST_SHA256 \
        == 5ab6b9482d7eff98aea424546592fc5a61e3af11bae9c4ea11f48f4774cb0ac2 \
    && $QWEN_V6_PACKAGE_EXPECTED_RESULTS_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_RECOVERED_CERTIFICATE_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_MERGE_MANIFEST_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_RETRY_CERTIFICATE_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_CERTIFICATE_SHA256 =~ ^[0-9a-f]{64}$ \
    && $QWEN_V6_PACKAGE_EXPECTED_POSTRUN_RECEIPT_SHA256 =~ ^[0-9a-f]{64}$ ]] \
    || fail package_identity_invalid
[[ "$(git -C "$project" rev-parse --show-toplevel)" == "$project" \
    && "$(git -C "$project" rev-parse HEAD)" == "$QWEN_V6_PACKAGE_EXPECTED_PROJECT_REVISION" \
    && -z "$(git -C "$project" status --porcelain=v1 --untracked-files=all)" ]] \
    || fail project_identity_invalid
[[ $packager == "$project/user/tianhaowu/terminal_bench_vmvm/package_qwen_recovered_unfiltered_traces.sh" ]] \
    || fail packager_path_invalid
[[ -f $package_worker && ! -L $package_worker \
    && "$(sha256sum "$packager" | cut -d' ' -f1)" == "$QWEN_V6_PACKAGE_PACKAGER_SHA256" \
    && "$(sha256sum "$package_worker" | cut -d' ' -f1)" == "$QWEN_V6_PACKAGE_WORKER_SHA256" ]] \
    || fail packager_identity_invalid
[[ $output == /* && $chunk_bytes =~ ^[1-9][0-9]*$ && $chunk_bytes -lt 100000000 \
    && $compression_level =~ ^[1-9][0-9]*$ && $compression_level -le 19 ]] \
    || fail package_configuration_invalid
[[ ! -e $output && ! -L $output ]] || fail output_exists
output_parent=$(realpath -e -- "$(dirname -- "$output")")
[[ $output == "$output_parent/$(basename -- "$output")" ]] || fail output_path_invalid
publication_lock="$output_parent/.$(basename -- "$output").publish.lock"
mkdir -m 700 -- "$publication_lock" 2>/dev/null || fail output_locked
lock_owned=1
temporary=
contract_summary=
published=0
cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [[ -n $contract_summary ]]; then
        rm -f -- "$contract_summary"
    fi
    if [[ $published == 0 && -n $temporary && -d $temporary ]]; then
        rm -rf -- "$temporary"
    fi
    if [[ $lock_owned == 1 && -d $publication_lock ]]; then
        rmdir -- "$publication_lock" || true
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

results="$unfiltered/results.jsonl"
recovered_certificate="$unfiltered/qwen_2499_recovered_results_certificate.json"
merge_manifest="$unfiltered/merge_manifest.json"
for path in \
    "$results" \
    "$recovered_certificate" \
    "$merge_manifest" \
    "$retry_certificate" \
    "$superseding_certificate" \
    "$postrun_receipt" \
    "$postrun_worker" \
    "$previous_manifest"; do
    [[ -f $path && ! -L $path ]] || fail input_artifact_invalid
done
for path in \
    "$results" \
    "$recovered_certificate" \
    "$merge_manifest" \
    "$retry_certificate" \
    "$superseding_certificate" \
    "$postrun_receipt"; do
    [[ "$(stat -c %a "$path")" == 600 ]] || fail input_artifact_mode_invalid
done
previous_manifest_mode=$(stat -c %a "$previous_manifest")
[[ $previous_manifest_mode == 600 || $previous_manifest_mode == 644 ]] \
    || fail previous_manifest_mode_invalid
[[ "$(stat -c %a "$postrun_worker")" == 500 ]] || fail postrun_worker_mode_invalid
[[ "$(basename -- "$retry_certificate")" == qwen_2499_error_retry_run_certificate.json \
    && "$(basename -- "$superseding_certificate")" == qwen_2499_error_retry_superseding_certificate.json \
    && "$(basename -- "$postrun_receipt")" == postrun_receipt-src108b713af-v6.json ]] \
    || fail input_artifact_name_invalid
[[ "$(find "$unfiltered" -mindepth 1 -maxdepth 1 -printf . | wc -c)" == 3 ]] \
    || fail unfiltered_shape_invalid
[[ "$(sha256sum "$previous_manifest" | cut -d' ' -f1)" \
    == "$QWEN_V6_PACKAGE_PREVIOUS_MANIFEST_SHA256" ]] \
    || fail previous_manifest_digest_mismatch
[[ "$(sha256sum "$postrun_worker" | cut -d' ' -f1)" \
    == "$QWEN_V6_PACKAGE_POSTRUN_WORKER_SHA256" ]] \
    || fail postrun_worker_digest_mismatch
[[ "$(wc -l <"$results")" == 2499 ]] || fail results_count_invalid

results_bytes=$(stat -c %s "$results")
results_sha256=$(sha256sum "$results" | cut -d' ' -f1)
recovered_certificate_bytes=$(stat -c %s "$recovered_certificate")
recovered_certificate_sha256=$(sha256sum "$recovered_certificate" | cut -d' ' -f1)
merge_manifest_bytes=$(stat -c %s "$merge_manifest")
merge_manifest_sha256=$(sha256sum "$merge_manifest" | cut -d' ' -f1)
retry_certificate_bytes=$(stat -c %s "$retry_certificate")
retry_certificate_sha256=$(sha256sum "$retry_certificate" | cut -d' ' -f1)
superseding_certificate_bytes=$(stat -c %s "$superseding_certificate")
superseding_certificate_sha256=$(sha256sum "$superseding_certificate" | cut -d' ' -f1)
postrun_receipt_bytes=$(stat -c %s "$postrun_receipt")
postrun_receipt_sha256=$(sha256sum "$postrun_receipt" | cut -d' ' -f1)
postrun_worker_bytes=$(stat -c %s "$postrun_worker")
postrun_worker_sha256=$(sha256sum "$postrun_worker" | cut -d' ' -f1)
previous_manifest_bytes=$(stat -c %s "$previous_manifest")
packager_sha256=$(sha256sum "$packager" | cut -d' ' -f1)
packager_bytes=$(stat -c %s "$packager")
package_worker_sha256=$(sha256sum "$package_worker" | cut -d' ' -f1)
package_worker_bytes=$(stat -c %s "$package_worker")
[[ $results_sha256 == "$QWEN_V6_PACKAGE_EXPECTED_RESULTS_SHA256" \
    && $recovered_certificate_sha256 == "$QWEN_V6_PACKAGE_EXPECTED_RECOVERED_CERTIFICATE_SHA256" \
    && $merge_manifest_sha256 == "$QWEN_V6_PACKAGE_EXPECTED_MERGE_MANIFEST_SHA256" \
    && $retry_certificate_sha256 == "$QWEN_V6_PACKAGE_EXPECTED_RETRY_CERTIFICATE_SHA256" \
    && $superseding_certificate_sha256 == "$QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_CERTIFICATE_SHA256" \
    && $postrun_receipt_sha256 == "$QWEN_V6_PACKAGE_EXPECTED_POSTRUN_RECEIPT_SHA256" ]] \
    || fail pinned_artifact_digest_mismatch

contract_summary=$(mktemp "$output_parent/.qwen-v6-contract.XXXXXXXX")
chmod 0600 "$contract_summary"
if ! python3 - \
    "$merge_manifest" \
    "$recovered_certificate" \
    "$retry_certificate" \
    "$superseding_certificate" \
    "$postrun_receipt" \
    "$previous_manifest" \
    "$results_bytes" \
    "$results_sha256" \
    "$recovered_certificate_bytes" \
    "$recovered_certificate_sha256" \
    "$merge_manifest_sha256" \
    "$merge_manifest_bytes" \
    "$retry_certificate_bytes" \
    "$retry_certificate_sha256" \
    "$superseding_certificate_sha256" \
    "$QWEN_V6_PACKAGE_EXPECTED_POSTPROCESSOR_REVISION" \
    "$QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_REVISION" \
    "$QWEN_V6_PACKAGE_EXPECTED_SOURCE_JOB" \
    "$QWEN_V6_PACKAGE_SELECTION_CONTRACT_SHA256" \
    "$QWEN_V6_PACKAGE_CANONICAL_TASK_FILE_SHA256" \
    "$QWEN_V6_PACKAGE_EXPECTED_RETRY_MODULE_SHA256" \
    "$QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_EXPORTER_SHA256" \
    "$QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_EXPORTER_SHA256" \
    "$QWEN_V6_PACKAGE_EXPECTED_SUPERSESSION_MODULE_SHA256" \
    "$QWEN_V6_PACKAGE_EXPECTED_AUDIT_TRACES_SHA256" \
    "$QWEN_V6_PACKAGE_EXPECTED_VERIFIER_REVISION" \
    "$QWEN_V6_PACKAGE_EXPECTED_RENDERER_REVISION" \
    "$QWEN_V6_PACKAGE_EXPECTED_MODEL_IO_CONTRACT_ID" \
    "$QWEN_V6_PACKAGE_EXPECTED_MODEL_IO_CONTRACT_SHA256" \
    >"$contract_summary" 2>/dev/null <<'PY'
import json
import re
import sys
from pathlib import Path

(
    merge_path,
    recovered_path,
    retry_path,
    superseding_path,
    receipt_path,
    previous_path,
    results_bytes,
    results_sha256,
    recovered_bytes,
    recovered_sha256,
    merge_sha256,
    merge_bytes,
    retry_bytes,
    retry_sha256,
    superseding_sha256,
    postprocessor_revision,
    predecessor_revision,
    expected_source_job,
    expected_selection_contract_sha256,
    canonical_task_file_sha256,
    predecessor_retry_module_sha256,
    predecessor_exporter_sha256,
    superseding_exporter_sha256,
    supersession_module_sha256,
    audit_traces_sha256,
    verifier_revision,
    renderer_revision,
    model_io_contract_id,
    model_io_contract_sha256,
) = sys.argv[1:]

SHA256 = re.compile(r"[0-9a-f]{64}")
BASE_POSITIVE = 1562
BASE_ZERO = 873
BASE_ERROR = 64
RETRY_COUNT = 64


def reject_constant(_value: str) -> None:
    raise ValueError("non-finite number")


def load(path: str) -> dict:
    value = json.loads(Path(path).read_bytes(), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("object required")
    return value


def plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def exact_keys(value: object, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def artifact_shape(value: object, *, path_required: bool) -> bool:
    keys = {"bytes", "path", "sha256"} if path_required else {"bytes", "sha256"}
    if not exact_keys(value, keys):
        return False
    return (
        plain_int(value["bytes"])
        and value["bytes"] > 0
        and sha256(value["sha256"])
        and (
            not path_required
            or (isinstance(value["path"], str) and value["path"].startswith("/"))
        )
    )


def exact_artifact(
    value: object,
    *,
    expected_bytes: int,
    expected_sha256: str,
    expected_path: str | None,
) -> bool:
    if not artifact_shape(value, path_required=expected_path is not None):
        return False
    return (
        value["bytes"] == expected_bytes
        and value["sha256"] == expected_sha256
        and (expected_path is None or value["path"] == expected_path)
    )


def accepted_shape(value: object, *, count: int, predicate: str) -> bool:
    return (
        exact_keys(
            value,
            {"canonical_indices_sha256", "count", "predicate", "row_sha256_set_sha256"},
        )
        and value["count"] == count
        and value["predicate"] == predicate
        and sha256(value["canonical_indices_sha256"])
        and sha256(value["row_sha256_set_sha256"])
    )

merge = load(merge_path)
recovered = load(recovered_path)
retry = load(retry_path)
superseding = load(superseding_path)
receipt = load(receipt_path)
previous = load(previous_path)
results_bytes_int = int(results_bytes)
recovered_bytes_int = int(recovered_bytes)
merge_bytes_int = int(merge_bytes)
retry_bytes_int = int(retry_bytes)
expected_source_job_int = int(expected_source_job)
results_path = str((Path(recovered_path).parent / "results.jsonl").resolve(strict=True))
resolved_recovered_path = str(Path(recovered_path).resolve(strict=True))

expected_code = {
    "audit_traces_sha256": audit_traces_sha256,
    "exporter_sha256": superseding_exporter_sha256,
    "qwen_2499_error_retry_sha256": predecessor_retry_module_sha256,
    "repository_revision": postprocessor_revision,
    "submodules": {
        "deps/renderers": renderer_revision,
        "deps/verifiers": verifier_revision,
    },
    "supersession_module_sha256": supersession_module_sha256,
}

retry_outcomes = retry.get("retry_outcomes")
retry_accepted = retry.get("accepted")
retry_trace = retry.get("trace_contract")
retry_run = retry.get("run")
retry_runtime = retry.get("runtime")
if not (
    exact_keys(
        retry,
        {
            "accepted",
            "code",
            "kind",
            "retry_outcomes",
            "run",
            "runtime",
            "schema_version",
            "selection_contract_sha256",
            "state",
            "trace_contract",
        },
    )
    and retry["schema_version"] == 1
    and retry["kind"] == "qwen-2499-exact-error-retry-run"
    and retry["state"] == "passed"
    and retry["selection_contract_sha256"] == expected_selection_contract_sha256
    and exact_keys(
        retry_outcomes,
        {"accepted_positive", "error", "invalid_positive", "retained_original", "total", "zero"},
    )
    and all(plain_int(value) for value in retry_outcomes.values())
    and retry_outcomes["total"] == RETRY_COUNT
    and retry_outcomes["accepted_positive"]
        + retry_outcomes["error"]
        + retry_outcomes["invalid_positive"]
        + retry_outcomes["zero"]
        == RETRY_COUNT
    and retry_outcomes["retained_original"]
        == RETRY_COUNT - retry_outcomes["accepted_positive"]
    and accepted_shape(
        retry_accepted,
        count=retry_outcomes["accepted_positive"],
        predicate="reward-one-and-exact-model-io-and-sft-trainable",
    )
    and retry_trace
        == {
            "id": model_io_contract_id,
            "max_sequence_tokens": 262144,
            "sha256": model_io_contract_sha256,
        }
    and retry.get("code") == {"module_sha256": predecessor_retry_module_sha256}
    and exact_keys(
        retry_run,
        {"cleanup", "eval_run_identity", "resolved_config", "results", "worker_manifest"},
    )
    and all(artifact_shape(value, path_required=True) for value in retry_run.values())
    and exact_keys(
        retry_runtime,
        {
            "cleanup_failures",
            "eval_run_identity_sha256",
            "provider_concurrency",
            "router_policy",
            "worker_count",
        },
    )
    and retry_runtime["cleanup_failures"] == 0
    and sha256(retry_runtime["eval_run_identity_sha256"])
    and retry_runtime["provider_concurrency"] == 32
    and retry_runtime["router_policy"] == "consistent_hash"
    and retry_runtime["worker_count"] == 24
):
    raise ValueError("retry certificate mismatch")

super_outcomes = superseding.get("outcomes")
super_accepted = superseding.get("accepted")
super_predecessor = superseding.get("predecessor")
super_trace = superseding.get("trace_contract")
if not (
    exact_keys(
        superseding,
        {
            "accepted",
            "code",
            "kind",
            "migration",
            "outcomes",
            "predecessor",
            "run",
            "runtime",
            "schema_version",
            "selection_contract_sha256",
            "state",
            "trace_contract",
        },
    )
    and superseding["schema_version"] == 1
    and superseding["kind"] == "qwen-2499-error-retry-superseding-certificate"
    and superseding["state"] == "passed"
    and superseding["selection_contract_sha256"] == expected_selection_contract_sha256
    and exact_keys(
        super_predecessor,
        {
            "accepted_positive",
            "artifact",
            "exporter_sha256",
            "kind",
            "module_sha256",
            "repository_revision",
            "sha256",
        },
    )
    and exact_artifact(
        super_predecessor["artifact"],
        expected_bytes=retry_bytes_int,
        expected_sha256=retry_sha256,
        expected_path=None,
    )
    and super_predecessor["accepted_positive"] == retry_outcomes["accepted_positive"]
    and super_predecessor["exporter_sha256"] == predecessor_exporter_sha256
    and super_predecessor["kind"] == retry["kind"]
    and super_predecessor["module_sha256"] == predecessor_retry_module_sha256
    and super_predecessor["repository_revision"] == predecessor_revision
    and super_predecessor["sha256"] == retry_sha256
    and superseding["migration"]
        == {
            "compatibility_id": "openai-null-wire-fields-v1",
            "policy": "permit-standard-null-openai-wire-fields-only",
        }
    and superseding["run"] == retry_run
    and superseding["runtime"] == retry_runtime
    and exact_keys(
        super_outcomes,
        {
            "clean_model_bearing",
            "error",
            "invalid_positive",
            "invalid_zero",
            "positive",
            "total",
            "zero",
        },
    )
    and all(plain_int(value) for value in super_outcomes.values())
    and super_outcomes["total"] == RETRY_COUNT
    and super_outcomes["positive"]
        + super_outcomes["zero"]
        + super_outcomes["invalid_positive"]
        + super_outcomes["invalid_zero"]
        + super_outcomes["error"]
        == RETRY_COUNT
    and super_outcomes["invalid_positive"] == 0
    and super_outcomes["invalid_zero"] == 0
    and super_outcomes["clean_model_bearing"]
        == super_outcomes["positive"] + super_outcomes["zero"]
    and exact_keys(super_accepted, {"pass_only", "unfiltered"})
    and accepted_shape(
        super_accepted["pass_only"],
        count=super_outcomes["positive"],
        predicate="reward-one-and-exact-model-io-and-sft-trainable",
    )
    and accepted_shape(
        super_accepted["unfiltered"],
        count=super_outcomes["clean_model_bearing"],
        predicate="binary-reward-and-exact-model-io-and-sft-structurally-valid",
    )
    and super_trace
        == {
            "id": model_io_contract_id,
            "max_sequence_tokens": 262144,
            "require_exact_provider_json": True,
            "require_model_io": True,
            "require_reasoning": True,
            "require_request_graph_match": True,
            "sha256": model_io_contract_sha256,
        }
    and superseding["code"] == expected_code
):
    raise ValueError("superseding certificate mismatch")

expected_outcomes = {
    "error": BASE_ERROR - super_outcomes["clean_model_bearing"],
    "positive": BASE_POSITIVE + super_outcomes["positive"],
    "zero": BASE_ZERO + super_outcomes["zero"],
}
expected_replacements = {
    "clean_model_bearing": super_outcomes["clean_model_bearing"],
    "positive": super_outcomes["positive"],
    "zero": super_outcomes["zero"],
}
expected_lineage = {
    "selection_contract_sha256": expected_selection_contract_sha256,
    "superseding_certificate_sha256": superseding_sha256,
}
expected_results_artifact = {
    "bytes": results_bytes_int,
    "path": results_path,
    "sha256": results_sha256,
}
expected_recovered_artifact = {
    "bytes": recovered_bytes_int,
    "path": resolved_recovered_path,
    "sha256": recovered_sha256,
}

if not (
    exact_keys(
        recovered,
        {
            "code",
            "coverage",
            "kind",
            "lineage",
            "mode",
            "outcomes",
            "replacements",
            "results",
            "schema_version",
            "state",
            "trace_contract",
        },
    )
    and recovered["schema_version"] == 1
    and recovered["kind"] == "qwen-2499-error-retry-recovered-results"
    and recovered["state"] == "passed"
    and recovered["mode"] == "unfiltered"
    and recovered["coverage"]
        == {
            "canonical_order": True,
            "exact": True,
            "exhaustive": True,
            "task_count": 2499,
            "universe_task_file_sha256": canonical_task_file_sha256,
        }
    and recovered["lineage"] == expected_lineage
    and recovered["outcomes"] == expected_outcomes
    and recovered["replacements"] == expected_replacements
    and recovered["results"] == expected_results_artifact
    and recovered["trace_contract"]
        == {
            "max_sequence_tokens": 262144,
            "replacement_rows_have_model_io": True,
            "replacement_rows_have_reasoning": True,
            "replacement_rows_request_graph_valid": True,
        }
    and recovered["code"] == expected_code
    and exact_keys(
        merge,
        {
            "artifacts",
            "kind",
            "lineage",
            "mode",
            "outcomes",
            "schema_version",
            "sft_selection",
            "state",
        },
    )
    and merge["schema_version"] == 1
    and merge["kind"] == "qwen-2499-error-retry-recovered-results-manifest"
    and merge["state"] == "ready"
    and merge["mode"] == "unfiltered"
    and merge["sft_selection"] is None
    and merge["artifacts"]
        == {"certificate": expected_recovered_artifact, "results": expected_results_artifact}
    and merge["lineage"] == expected_lineage
    and merge["outcomes"] == expected_outcomes
):
    raise ValueError("recovered artifact mismatch")

receipt_capture = receipt.get("capture")
if not (
    exact_keys(
        receipt,
        {
            "artifact",
            "capture",
            "code",
            "kind",
            "lineage",
            "mode",
            "outcomes",
            "replacements",
            "schema_version",
            "state",
            "task_count",
        },
    )
    and receipt["schema_version"] == 1
    and receipt["kind"] == "qwen-2499-unfiltered-recovered-results-postrun"
    and receipt["state"] == "certified"
    and receipt["mode"] == "unfiltered"
    and receipt["task_count"] == 2499
    and receipt["code"] == expected_code
    and receipt["artifact"]
        == {
            "certificate": {"bytes": recovered_bytes_int, "sha256": recovered_sha256},
            "manifest": {"bytes": merge_bytes_int, "sha256": merge_sha256},
            "results": {"bytes": results_bytes_int, "sha256": results_sha256},
        }
    and receipt["lineage"]
        == {
            "retry_run_certificate_sha256": retry_sha256,
            "run_repository_revision": predecessor_revision,
            "selection_contract_sha256": expected_selection_contract_sha256,
            "source_job": expected_source_job_int,
            "superseding_certificate_sha256": superseding_sha256,
        }
    and receipt["outcomes"] == expected_outcomes
    and receipt["replacements"] == expected_replacements
    and exact_keys(
        receipt_capture,
        {"model_bearing_traces", "model_io_nodes", "reasoning_nodes", "sampled_nodes"},
    )
    and all(plain_int(value) for value in receipt_capture.values())
    and receipt_capture["model_bearing_traces"]
        == expected_outcomes["positive"] + expected_outcomes["zero"]
    and receipt_capture["sampled_nodes"] >= receipt_capture["model_bearing_traces"] > 0
    and receipt_capture["model_io_nodes"] == receipt_capture["sampled_nodes"]
    and receipt_capture["reasoning_nodes"] == receipt_capture["sampled_nodes"]
):
    raise ValueError("postrun receipt mismatch")

if not (
    merge.get("schema_version") == 1
    and merge.get("kind") == "qwen-2499-error-retry-recovered-results-manifest"
    and merge.get("state") == "ready"
    and merge.get("mode") == "unfiltered"
    and merge.get("artifacts", {}).get("results", {}).get("bytes") == results_bytes_int
    and merge.get("artifacts", {}).get("results", {}).get("sha256") == results_sha256
    and merge.get("artifacts", {}).get("certificate", {}).get("bytes") == recovered_bytes_int
    and merge.get("artifacts", {}).get("certificate", {}).get("sha256") == recovered_sha256
    and recovered.get("schema_version") == 1
    and recovered.get("kind") == "qwen-2499-error-retry-recovered-results"
    and recovered.get("state") == "passed"
    and recovered.get("mode") == "unfiltered"
    and recovered.get("coverage", {}).get("canonical_order") is True
    and recovered.get("coverage", {}).get("exact") is True
    and recovered.get("coverage", {}).get("exhaustive") is True
    and recovered.get("coverage", {}).get("task_count") == 2499
    and recovered.get("coverage", {}).get("universe_task_file_sha256") == canonical_task_file_sha256
    and recovered.get("results", {}).get("bytes") == results_bytes_int
    and recovered.get("results", {}).get("sha256") == results_sha256
    and recovered.get("trace_contract", {}).get("max_sequence_tokens") == 262144
    and recovered.get("trace_contract", {}).get("replacement_rows_have_model_io") is True
    and recovered.get("trace_contract", {}).get("replacement_rows_have_reasoning") is True
    and recovered.get("trace_contract", {}).get("replacement_rows_request_graph_valid") is True
    and retry.get("schema_version") == 1
    and retry.get("kind") == "qwen-2499-exact-error-retry-run"
    and retry.get("state") == "passed"
    and superseding.get("schema_version") == 1
    and superseding.get("kind") == "qwen-2499-error-retry-superseding-certificate"
    and superseding.get("state") == "passed"
    and superseding.get("predecessor", {}).get("sha256") == retry_sha256
    and superseding.get("code", {}).get("repository_revision") == postprocessor_revision
    and receipt.get("schema_version") == 1
    and receipt.get("kind") == "qwen-2499-unfiltered-recovered-results-postrun"
    and receipt.get("state") == "certified"
    and receipt.get("mode") == "unfiltered"
    and receipt.get("task_count") == 2499
    and receipt.get("code", {}).get("repository_revision") == postprocessor_revision
    and receipt.get("code") == recovered.get("code")
    and receipt.get("code") == superseding.get("code")
    and receipt.get("artifact", {}).get("results")
        == {"bytes": results_bytes_int, "sha256": results_sha256}
    and receipt.get("artifact", {}).get("certificate")
        == {"bytes": recovered_bytes_int, "sha256": recovered_sha256}
    and receipt.get("artifact", {}).get("manifest")
        == {"bytes": merge_bytes_int, "sha256": merge_sha256}
    and receipt.get("lineage", {}).get("retry_run_certificate_sha256") == retry_sha256
    and receipt.get("lineage", {}).get("superseding_certificate_sha256") == superseding_sha256
    and receipt.get("lineage", {}).get("run_repository_revision")
        == superseding.get("predecessor", {}).get("repository_revision")
    and previous.get("schema_version") == 1
    and previous.get("kind") == "qwen-2499-unfiltered-trajectory-package"
):
    raise ValueError("contract mismatch")

selection_sha = recovered.get("lineage", {}).get("selection_contract_sha256")
if not (
    isinstance(selection_sha, str)
    and len(selection_sha) == 64
    and recovered.get("lineage", {}).get("superseding_certificate_sha256") == superseding_sha256
    and merge.get("lineage") == recovered.get("lineage")
    and superseding.get("selection_contract_sha256") == selection_sha
    and retry.get("selection_contract_sha256") == selection_sha
    and receipt.get("lineage", {}).get("selection_contract_sha256") == selection_sha
):
    raise ValueError("lineage mismatch")

outcomes = recovered.get("outcomes")
if not (
    isinstance(outcomes, dict)
    and set(outcomes) == {"error", "positive", "zero"}
    and all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in outcomes.values())
    and sum(outcomes.values()) == 2499
    and merge.get("outcomes") == outcomes
    and receipt.get("outcomes") == outcomes
    and receipt.get("replacements") == recovered.get("replacements")
):
    raise ValueError("outcome mismatch")

capture = receipt.get("capture")
if not (
    isinstance(capture, dict)
    and capture.get("model_bearing_traces") == outcomes["positive"] + outcomes["zero"]
    and isinstance(capture.get("sampled_nodes"), int)
    and not isinstance(capture.get("sampled_nodes"), bool)
    and capture["sampled_nodes"] > 0
    and capture.get("model_io_nodes") == capture["sampled_nodes"]
    and capture.get("reasoning_nodes") == capture["sampled_nodes"]
):
    raise ValueError("capture mismatch")

summary = {
    "error": outcomes["error"],
    "positive": outcomes["positive"],
    "selection_contract_sha256": selection_sha,
    "zero": outcomes["zero"],
}
print(json.dumps(summary, allow_nan=False, separators=(",", ":"), sort_keys=True))
PY
then
    rm -f -- "$contract_summary"
    fail source_contract_invalid
fi

temporary=$(mktemp -d "$output_parent/.$(basename -- "$output").XXXXXXXX")
chmod 0700 "$temporary"

archive="$temporary/$archive_name"
tar --format=posix --sort=name --mtime='UTC 1970-01-01' \
    --owner=0 --group=0 --numeric-owner --mode='u=rw,go=' \
    --pax-option=delete=atime,delete=ctime \
    --transform="s#^$(basename -- "$postrun_worker")\$#postrun_worker.sbatch#" \
    --transform="s#^#$archive_root/#" \
    -C "$unfiltered" merge_manifest.json \
    -C "$(dirname -- "$postrun_receipt")" "$(basename -- "$postrun_receipt")" \
    -C "$(dirname -- "$postrun_worker")" "$(basename -- "$postrun_worker")" \
    -C "$(dirname -- "$retry_certificate")" "$(basename -- "$retry_certificate")" \
    -C "$(dirname -- "$superseding_certificate")" "$(basename -- "$superseding_certificate")" \
    -C "$unfiltered" qwen_2499_recovered_results_certificate.json results.jsonl \
    -cf - | zstd -q -T1 -"$compression_level" --long=31 -o "$archive"

archive_bytes=$(stat -c %s "$archive")
archive_sha256=$(sha256sum "$archive" | cut -d' ' -f1)
mkdir -m 700 "$temporary/chunks"
split -b "$chunk_bytes" -d -a 3 --additional-suffix=.part \
    "$archive" "$temporary/chunks/$archive_name."

chunks_jsonl="$temporary/chunks.jsonl"
for chunk in "$temporary"/chunks/*; do
    name=$(basename -- "$chunk")
    bytes=$(stat -c %s "$chunk")
    [[ $bytes -lt 100000000 ]] || fail chunk_size_invalid
    digest=$(sha256sum "$chunk" | cut -d' ' -f1)
    jq -nc --arg name "$name" --arg sha256 "$digest" --argjson bytes "$bytes" \
        '{name:$name,bytes:$bytes,sha256:$sha256}' >>"$chunks_jsonl"
done
chmod 0600 "$chunks_jsonl"
chunks=$(jq -sc '.' "$chunks_jsonl")
outcomes=$(cat "$contract_summary")

jq -nS \
    --arg archive_name "$archive_name" \
    --arg archive_root "$archive_root" \
    --arg archive_sha256 "$archive_sha256" \
    --arg compression "zstd-${compression_level}-long31" \
    --argjson archive_bytes "$archive_bytes" \
    --argjson chunk_bytes "$chunk_bytes" \
    --argjson chunks "$chunks" \
    --argjson outcomes "$outcomes" \
    --arg results_sha256 "$results_sha256" \
    --argjson results_bytes "$results_bytes" \
    --arg recovered_certificate_sha256 "$recovered_certificate_sha256" \
    --argjson recovered_certificate_bytes "$recovered_certificate_bytes" \
    --arg merge_manifest_sha256 "$merge_manifest_sha256" \
    --argjson merge_manifest_bytes "$merge_manifest_bytes" \
    --arg retry_certificate_sha256 "$retry_certificate_sha256" \
    --argjson retry_certificate_bytes "$retry_certificate_bytes" \
    --arg superseding_certificate_sha256 "$superseding_certificate_sha256" \
    --argjson superseding_certificate_bytes "$superseding_certificate_bytes" \
    --arg postrun_receipt_sha256 "$postrun_receipt_sha256" \
    --argjson postrun_receipt_bytes "$postrun_receipt_bytes" \
    --arg postrun_worker_sha256 "$postrun_worker_sha256" \
    --argjson postrun_worker_bytes "$postrun_worker_bytes" \
    --arg previous_manifest_sha256 "$QWEN_V6_PACKAGE_PREVIOUS_MANIFEST_SHA256" \
    --argjson previous_manifest_bytes "$previous_manifest_bytes" \
    --arg project_revision "$QWEN_V6_PACKAGE_EXPECTED_PROJECT_REVISION" \
    --arg postprocessor_revision "$QWEN_V6_PACKAGE_EXPECTED_POSTPROCESSOR_REVISION" \
    --arg predecessor_revision "$QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_REVISION" \
    --argjson source_job "$QWEN_V6_PACKAGE_EXPECTED_SOURCE_JOB" \
    --argjson postrun_job_id "$QWEN_V6_PACKAGE_POSTRUN_JOB_ID" \
    --arg canonical_task_file_sha256 "$QWEN_V6_PACKAGE_CANONICAL_TASK_FILE_SHA256" \
    --arg packager_sha256 "$packager_sha256" \
    --argjson packager_bytes "$packager_bytes" \
    --arg package_worker_sha256 "$package_worker_sha256" \
    --argjson package_worker_bytes "$package_worker_bytes" \
    '{
      schema_version:1,
      kind:"qwen-2499-recovered-unfiltered-trajectory-package",
      state:"ready",
      package_version:"v6",
      project_revision:$project_revision,
      packager:{bytes:$packager_bytes,sha256:$packager_sha256},
      package_worker:{bytes:$package_worker_bytes,sha256:$package_worker_sha256},
      coverage:{canonical_tasks:2499,outcomes:{positive:$outcomes.positive,zero:$outcomes.zero,error:$outcomes.error}},
      lineage:{
        selection_contract_sha256:$outcomes.selection_contract_sha256,
        previous_package_manifest_sha256:$previous_manifest_sha256,
        retry_certificate_sha256:$retry_certificate_sha256,
        superseding_certificate_sha256:$superseding_certificate_sha256,
        recovered_certificate_sha256:$recovered_certificate_sha256,
        recovered_merge_manifest_sha256:$merge_manifest_sha256,
        postrun_receipt_sha256:$postrun_receipt_sha256,
        postrun_worker_sha256:$postrun_worker_sha256,
        postprocessor_revision:$postprocessor_revision,
        predecessor_revision:$predecessor_revision,
        source_job:$source_job,
        postrun_job_id:$postrun_job_id,
        canonical_task_file_sha256:$canonical_task_file_sha256
      },
      inputs:{
        results:{bytes:$results_bytes,sha256:$results_sha256,rows:2499},
        recovered_certificate:{bytes:$recovered_certificate_bytes,sha256:$recovered_certificate_sha256},
        recovered_merge_manifest:{bytes:$merge_manifest_bytes,sha256:$merge_manifest_sha256},
        retry_certificate:{bytes:$retry_certificate_bytes,sha256:$retry_certificate_sha256},
        superseding_certificate:{bytes:$superseding_certificate_bytes,sha256:$superseding_certificate_sha256},
        postrun_receipt:{bytes:$postrun_receipt_bytes,sha256:$postrun_receipt_sha256},
        postrun_worker:{bytes:$postrun_worker_bytes,sha256:$postrun_worker_sha256},
        previous_package_manifest:{bytes:$previous_manifest_bytes,sha256:$previous_manifest_sha256}
      },
      archive:{
        name:$archive_name,
        bytes:$archive_bytes,
        sha256:$archive_sha256,
        compression:$compression,
        member_count:7,
        members:[
          {name:($archive_root+"/merge_manifest.json"),bytes:$merge_manifest_bytes,sha256:$merge_manifest_sha256},
          {name:($archive_root+"/postrun_receipt-src108b713af-v6.json"),bytes:$postrun_receipt_bytes,sha256:$postrun_receipt_sha256},
          {name:($archive_root+"/postrun_worker.sbatch"),bytes:$postrun_worker_bytes,sha256:$postrun_worker_sha256},
          {name:($archive_root+"/qwen_2499_error_retry_run_certificate.json"),bytes:$retry_certificate_bytes,sha256:$retry_certificate_sha256},
          {name:($archive_root+"/qwen_2499_error_retry_superseding_certificate.json"),bytes:$superseding_certificate_bytes,sha256:$superseding_certificate_sha256},
          {name:($archive_root+"/qwen_2499_recovered_results_certificate.json"),bytes:$recovered_certificate_bytes,sha256:$recovered_certificate_sha256},
          {name:($archive_root+"/results.jsonl"),bytes:$results_bytes,sha256:$results_sha256}
        ]
      },
      chunk_bytes:$chunk_bytes,
      chunks:$chunks
    }' >"$temporary/manifest.json"
chmod 0600 "$temporary/manifest.json"
(
    cd "$temporary/chunks"
    sha256sum -- * >../SHA256SUMS
)
chmod 0600 "$temporary/SHA256SUMS"

cat >"$temporary/README.md" <<EOF
# Qwen 2.4T recovered unfiltered trajectories v6

This package contains the certified 2,499-row canonical unfiltered Qwen
trajectory union after the exact-64 Sandoq recovery. It is not expanded into
SFT rows. The archive also carries the recovered, predecessor, superseding,
and postrun certificates needed to verify its lineage.

Verify and reconstruct with:

\`\`\`bash
(cd chunks && sha256sum -c ../SHA256SUMS)
cat chunks/*.part | sha256sum
cat chunks/*.part | zstd --long=31 -t
cat chunks/*.part > $archive_name
\`\`\`

The concatenated archive must have SHA-256 \`$archive_sha256\` and size
\`$archive_bytes\` bytes. See \`manifest.json\` for immutable input lineage.
EOF
chmod 0600 "$temporary/README.md"

rm -- "$chunks_jsonl"
reassembled_bytes=$(cat "$temporary"/chunks/*.part | wc -c)
reassembled_sha256=$(cat "$temporary"/chunks/*.part | sha256sum | cut -d' ' -f1)
[[ $reassembled_bytes == "$archive_bytes" && $reassembled_sha256 == "$archive_sha256" ]] \
    || fail reassembly_digest_invalid
cat "$temporary"/chunks/*.part | zstd -q --long=31 -t || fail archive_integrity_invalid

expected_members="$temporary/expected-members.txt"
actual_members="$temporary/actual-members.txt"
printf '%s\n' \
    "$archive_root/merge_manifest.json" \
    "$archive_root/$(basename -- "$postrun_receipt")" \
    "$archive_root/postrun_worker.sbatch" \
    "$archive_root/$(basename -- "$retry_certificate")" \
    "$archive_root/$(basename -- "$superseding_certificate")" \
    "$archive_root/qwen_2499_recovered_results_certificate.json" \
    "$archive_root/results.jsonl" >"$expected_members"
cat "$temporary"/chunks/*.part | zstd -dc --long=31 | tar -tf - >"$actual_members"
cmp -s "$expected_members" "$actual_members" || fail archive_members_invalid
rm -- "$expected_members" "$actual_members"

verify_unchanged() {
    local path=$1
    local bytes=$2
    local digest=$3
    [[ -f $path && ! -L $path \
        && "$(stat -c %s "$path")" == "$bytes" \
        && "$(sha256sum "$path" | cut -d' ' -f1)" == "$digest" ]] \
        || fail input_changed_during_package
}
verify_unchanged "$results" "$results_bytes" "$results_sha256"
verify_unchanged \
    "$recovered_certificate" "$recovered_certificate_bytes" "$recovered_certificate_sha256"
verify_unchanged "$merge_manifest" "$merge_manifest_bytes" "$merge_manifest_sha256"
verify_unchanged "$retry_certificate" "$retry_certificate_bytes" "$retry_certificate_sha256"
verify_unchanged \
    "$superseding_certificate" "$superseding_certificate_bytes" "$superseding_certificate_sha256"
verify_unchanged "$postrun_receipt" "$postrun_receipt_bytes" "$postrun_receipt_sha256"
verify_unchanged "$postrun_worker" "$postrun_worker_bytes" "$postrun_worker_sha256"
verify_unchanged "$previous_manifest" "$previous_manifest_bytes" \
    "$QWEN_V6_PACKAGE_PREVIOUS_MANIFEST_SHA256"
verify_unchanged "$packager" "$packager_bytes" "$packager_sha256"
verify_unchanged "$package_worker" "$package_worker_bytes" "$package_worker_sha256"
for path in \
    "$results" \
    "$recovered_certificate" \
    "$merge_manifest" \
    "$retry_certificate" \
    "$superseding_certificate" \
    "$postrun_receipt"; do
    [[ "$(stat -c %a "$path")" == 600 ]] || fail input_changed_during_package
done
[[ "$(stat -c %a "$previous_manifest")" == "$previous_manifest_mode" ]] \
    || fail input_changed_during_package
[[ "$(stat -c %a "$postrun_worker")" == 500 ]] || fail input_changed_during_package
[[ "$(git -C "$project" rev-parse HEAD)" == "$QWEN_V6_PACKAGE_EXPECTED_PROJECT_REVISION" \
    && -z "$(git -C "$project" status --porcelain=v1 --untracked-files=all)" ]] \
    || fail project_changed_during_package

rm -- "$archive"
mv -T -n -- "$temporary" "$output"
[[ ! -e $temporary && -d $output && ! -L $output ]] || fail output_publish_raced
published=1
rmdir -- "$publication_lock"
lock_owned=0
printf '{"archive_bytes":%s,"archive_sha256":"%s","chunks":%s,"state":"packaged","tasks":2499}\n' \
    "$archive_bytes" "$archive_sha256" "$(find "$output/chunks" -maxdepth 1 -type f | wc -l)"
