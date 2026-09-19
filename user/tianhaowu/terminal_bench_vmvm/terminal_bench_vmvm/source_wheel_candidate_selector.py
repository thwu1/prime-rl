"""Select a source-unique proof set from a private approved candidate manifest."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import terminal_bench_vmvm.source_wheel_input_reducer as reducer_module
import terminal_bench_vmvm.source_wheel_proof as proof_module
import terminal_bench_vmvm.source_wheels as source_wheels_module
from terminal_bench_vmvm.source_wheel_input_reducer import (
    SourceFetcher,
    SourceWheelInputReductionError,
    _fetch_source,
    _publish_outputs,
    _read_private_input,
    _source_policy,
    _stable_code_binding,
)
from terminal_bench_vmvm.source_wheel_proof import (
    DiscoveryEntry,
    DiscoverySource,
    SourceWheelProofError,
    parse_discovery_input_payload,
)
from terminal_bench_vmvm.source_wheels import (
    SETUP_CFG_GRAMMAR_ID,
    SETUP_PY_GRAMMAR_ID,
    canonical_json,
    extract_static_build_requirements,
    sha256_bytes,
    strict_json_loads,
)

MINIMUM_CANDIDATE_ENTRIES = 6
MAXIMUM_CANDIDATE_ENTRIES = 2_538
SELECTED_ENTRY_COUNT = 6
APPROVED_EXISTING_RECOVERY_COUNT = 6
PROJECTED_RECOVERY_COUNT = SELECTED_ENTRY_COUNT + APPROVED_EXISTING_RECOVERY_COUNT
OUTPUT_FILENAME = "probe_inputs.private.json"
RECEIPT_FILENAME = "candidate_selection_receipt.json"
RECEIPT_SCHEMA_VERSION = 1
RECOVERY_BINDINGS_SCHEMA_VERSION = 1
PUBLIC_ERROR_CODES = frozenset(
    {
        "candidate_entry_count_invalid",
        "code_binding_changed",
        "code_binding_invalid",
        "compatible_source_count_insufficient",
        "download_timeout_invalid",
        "envelope_changed",
        "input_changed",
        "input_invalid",
        "input_not_canonical",
        "input_not_private",
        "input_sha256_invalid",
        "input_sha256_mismatch",
        "input_size_invalid",
        "output_artifact_exists",
        "output_artifact_invalid",
        "output_directory_changed",
        "output_directory_create_failed",
        "output_directory_not_fresh",
        "output_directory_not_private",
        "output_invalid",
        "output_parent_invalid",
        "output_write_failed",
        "recovery_bindings_invalid",
        "source_download_failed",
        "source_download_integrity_mismatch",
        "source_download_redirect_invalid",
        "source_identity_conflict",
    }
)
SELECTION_COUNT_KEYS = frozenset(
    {
        "input_entries",
        "distinct_sources",
        "accepted_sources",
        "rejected_sources",
        "compatible_entries",
        "incompatible_entries",
        "recovery_binding_entries",
        "overlap_entries",
        "eligible_entries",
        "eligible_sources",
        "selected_entries",
        "selected_sources",
        "projected_recoveries_if_all_selected_pass",
    }
)


class SourceWheelCandidateSelectionError(RuntimeError):
    """A fail-closed selection error with optional aggregate-only counts."""

    def __init__(self, code: str, counts: dict[str, int] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.counts = counts


def _executed_code_paths() -> dict[str, Path]:
    workflow_dir = Path(__file__).resolve(strict=True).parents[1]
    return {
        "selector_cli_sha256": workflow_dir / "select_source_wheel_candidates.py",
        "selector_implementation_sha256": Path(__file__),
        "reducer_implementation_sha256": Path(reducer_module.__file__),
        "discovery_parser_sha256": Path(proof_module.__file__),
        "source_wheel_contract_sha256": Path(source_wheels_module.__file__),
    }


def _capture_code_bindings() -> dict[str, tuple[Path, tuple[int, int, int, int, int, int, int], str]]:
    return {name: _stable_code_binding(path) for name, path in _executed_code_paths().items()}


def _revalidate_code_bindings(
    bindings: dict[str, tuple[Path, tuple[int, int, int, int, int, int, int], str]],
) -> None:
    current_paths = _executed_code_paths()
    if set(bindings) != set(current_paths):
        raise SourceWheelCandidateSelectionError("code_binding_changed")
    for name, binding in bindings.items():
        try:
            observed = _stable_code_binding(binding[0])
        except SourceWheelInputReductionError as error:
            raise SourceWheelCandidateSelectionError("code_binding_changed") from error
        if observed != binding or current_paths[name] != binding[0]:
            raise SourceWheelCandidateSelectionError("code_binding_changed")


def _load_recovery_bindings(
    path: Path,
    expected_sha256: str,
    expected_provenance_sha256: str,
) -> frozenset[str]:
    try:
        payload = _read_private_input(path, expected_sha256)
        value = strict_json_loads(payload)
    except (SourceWheelInputReductionError, UnicodeDecodeError, ValueError, RecursionError) as error:
        raise SourceWheelCandidateSelectionError("recovery_bindings_invalid") from error
    if not isinstance(value, dict):
        raise SourceWheelCandidateSelectionError("recovery_bindings_invalid")
    bindings = value.get("task_binding_sha256s")
    if (
        set(value)
        != {
            "schema_version",
            "kind",
            "complete",
            "discovery_provenance_sha256",
            "task_binding_sha256s",
        }
        or value.get("schema_version") != RECOVERY_BINDINGS_SCHEMA_VERSION
        or value.get("kind") != "approved-oracle-recovery-task-bindings"
        or value.get("complete") is not True
        or value.get("discovery_provenance_sha256") != expected_provenance_sha256
        or not isinstance(bindings, list)
        or len(bindings) != APPROVED_EXISTING_RECOVERY_COUNT
        or not all(isinstance(item, str) and reducer_module.SHA256_RE.fullmatch(item) for item in bindings)
        or len(bindings) != len(set(bindings))
        or payload != canonical_json(value) + b"\n"
    ):
        raise SourceWheelCandidateSelectionError("recovery_bindings_invalid")
    return frozenset(bindings)


def _selection_counts(
    *,
    input_entries: int,
    distinct_sources: int,
    accepted_sources: int,
    compatible_entries: int,
    overlap_entries: int,
    eligible_entries: int,
    eligible_sources: int,
    selected_entries: int,
    selected_sources: int,
) -> dict[str, int]:
    return {
        "input_entries": input_entries,
        "distinct_sources": distinct_sources,
        "accepted_sources": accepted_sources,
        "rejected_sources": distinct_sources - accepted_sources,
        "compatible_entries": compatible_entries,
        "incompatible_entries": input_entries - compatible_entries,
        "recovery_binding_entries": APPROVED_EXISTING_RECOVERY_COUNT,
        "overlap_entries": overlap_entries,
        "eligible_entries": eligible_entries,
        "eligible_sources": eligible_sources,
        "selected_entries": selected_entries,
        "selected_sources": selected_sources,
        "projected_recoveries_if_all_selected_pass": APPROVED_EXISTING_RECOVERY_COUNT + selected_entries,
    }


def select_source_wheel_candidates(
    input_path: Path,
    input_sha256: str,
    recovery_bindings_path: Path,
    recovery_bindings_sha256: str,
    output_dir: Path,
    *,
    expected_input_entries: int,
    timeout_seconds: float = 300.0,
    fetch_source: SourceFetcher = _fetch_source,
) -> dict[str, object]:
    if (
        type(expected_input_entries) is not int
        or not MINIMUM_CANDIDATE_ENTRIES <= expected_input_entries <= MAXIMUM_CANDIDATE_ENTRIES
    ):
        raise SourceWheelCandidateSelectionError("candidate_entry_count_invalid")
    if not 0 < timeout_seconds <= reducer_module.MAX_TIMEOUT_SECONDS:
        raise SourceWheelCandidateSelectionError("download_timeout_invalid")
    if output_dir.exists() or output_dir.is_symlink():
        raise SourceWheelCandidateSelectionError("output_directory_not_fresh")

    try:
        code_bindings = _capture_code_bindings()
        payload = _read_private_input(input_path, input_sha256)
        manifest, document = parse_discovery_input_payload(
            payload,
            path=input_path,
            input_sha256=input_sha256,
            expected_entry_count=expected_input_entries,
            expected_missing_evidence_sha256=None,
        )
    except SourceWheelInputReductionError as error:
        raise SourceWheelCandidateSelectionError(error.code) from error
    except SourceWheelProofError as error:
        raise SourceWheelCandidateSelectionError("input_invalid") from error
    if payload != canonical_json(document) + b"\n":
        raise SourceWheelCandidateSelectionError("input_not_canonical")

    recovery_bindings = _load_recovery_bindings(
        recovery_bindings_path,
        recovery_bindings_sha256,
        manifest.provenance_sha256,
    )
    raw_entries = document["entries"]
    assert isinstance(raw_entries, list)
    sources: dict[str, DiscoverySource] = {}
    source_records: dict[str, object] = {}
    entries_by_source: dict[str, list[tuple[DiscoveryEntry, dict[str, object]]]] = defaultdict(list)
    for entry, raw_entry in zip(manifest.entries, raw_entries, strict=True):
        assert isinstance(raw_entry, dict)
        raw_source = raw_entry["source"]
        existing = source_records.get(entry.source.sha256)
        if existing is not None and existing != raw_source:
            raise SourceWheelCandidateSelectionError("source_identity_conflict")
        sources.setdefault(entry.source.sha256, entry.source)
        source_records.setdefault(entry.source.sha256, raw_source)
        entries_by_source[entry.source.sha256].append((entry, raw_entry))
    accepted_sources: set[str] = set()
    rejected_sources: set[str] = set()
    allowed_hosts = frozenset(manifest.allowed_hosts)
    for digest, source in sources.items():
        try:
            source_payload = fetch_source(source, allowed_hosts, timeout_seconds)
        except SourceWheelInputReductionError as error:
            raise SourceWheelCandidateSelectionError(error.code) from error
        except Exception as error:
            raise SourceWheelCandidateSelectionError("source_download_failed") from error
        if (
            not isinstance(source_payload, bytes)
            or len(source_payload) != source.size
            or sha256_bytes(source_payload) != digest
        ):
            raise SourceWheelCandidateSelectionError("source_download_integrity_mismatch")
        try:
            extract_static_build_requirements(_source_policy(source), source_payload)
        except RuntimeError:
            rejected_sources.add(digest)
        else:
            accepted_sources.add(digest)

    compatible_entries = sum(len(entries_by_source[digest]) for digest in accepted_sources)
    overlap_entries = sum(entry.task_binding_sha256 in recovery_bindings for entry in manifest.entries)
    eligible_entries = [
        (entry, raw_entry)
        for entry, raw_entry in zip(manifest.entries, raw_entries, strict=True)
        if entry.source.sha256 in accepted_sources and entry.task_binding_sha256 not in recovery_bindings
    ]
    eligible_source_digests = {entry.source.sha256 for entry, _raw_entry in eligible_entries}
    selected_entries: list[dict[str, object]] = []
    selected_source_digests: set[str] = set()
    for entry, raw_entry in eligible_entries:
        if entry.source.sha256 in selected_source_digests:
            continue
        selected_entries.append(raw_entry)
        selected_source_digests.add(entry.source.sha256)
        if len(selected_entries) == SELECTED_ENTRY_COUNT:
            break
    counts = _selection_counts(
        input_entries=len(raw_entries),
        distinct_sources=len(sources),
        accepted_sources=len(accepted_sources),
        compatible_entries=compatible_entries,
        overlap_entries=overlap_entries,
        eligible_entries=len(eligible_entries),
        eligible_sources=len(eligible_source_digests),
        selected_entries=len(selected_entries),
        selected_sources=len(selected_source_digests),
    )
    if (
        accepted_sources & rejected_sources
        or accepted_sources | rejected_sources != set(sources)
        or len(selected_entries) != SELECTED_ENTRY_COUNT
        or len(selected_source_digests) != SELECTED_ENTRY_COUNT
    ):
        raise SourceWheelCandidateSelectionError("compatible_source_count_insufficient", counts)

    reduced = dict(document)
    reduced["entries"] = selected_entries
    if any(reduced[key] != document[key] for key in document if key != "entries"):
        raise SourceWheelCandidateSelectionError("envelope_changed")
    output_payload = canonical_json(reduced) + b"\n"
    output_sha256 = sha256_bytes(output_payload)
    try:
        selected_manifest, validated_output = parse_discovery_input_payload(
            output_payload,
            path=output_dir / OUTPUT_FILENAME,
            input_sha256=output_sha256,
            expected_entry_count=SELECTED_ENTRY_COUNT,
            expected_missing_evidence_sha256=manifest.missing_required_evidence_sha256,
        )
    except SourceWheelProofError as error:
        raise SourceWheelCandidateSelectionError("output_invalid") from error
    if (
        validated_output != reduced
        or len(selected_manifest.entries) != SELECTED_ENTRY_COUNT
        or len({entry.source.sha256 for entry in selected_manifest.entries}) != SELECTED_ENTRY_COUNT
        or any(entry.task_binding_sha256 in recovery_bindings for entry in selected_manifest.entries)
    ):
        raise SourceWheelCandidateSelectionError("output_invalid")

    _revalidate_code_bindings(code_bindings)
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": "source-wheel-candidate-selection",
        "status": "complete",
        "counts": counts,
        "projection": {
            "bound_existing_recoveries": APPROVED_EXISTING_RECOVERY_COUNT,
            "selected_recovery_candidates": SELECTED_ENTRY_COUNT,
            "projected_recoveries_if_all_selected_pass": PROJECTED_RECOVERY_COUNT,
            "requires_all_selected_proofs": True,
            "task_binding_overlap": 0,
        },
        "selection": {
            "strategy": "canonical-input-order-first-entry-per-compatible-source",
            "source_unique": True,
        },
        "hashes": {
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
            "missing_required_evidence_sha256": manifest.missing_required_evidence_sha256,
            "recovery_bindings_sha256": recovery_bindings_sha256,
            **{name: binding[2] for name, binding in code_bindings.items()},
        },
        "grammar": {
            "setup_py": SETUP_PY_GRAMMAR_ID,
            "setup_cfg": SETUP_CFG_GRAMMAR_ID,
        },
    }
    receipt_payload = canonical_json(receipt) + b"\n"
    try:
        _publish_outputs(
            output_dir,
            (
                (OUTPUT_FILENAME, output_payload),
                (RECEIPT_FILENAME, receipt_payload),
            ),
        )
    except SourceWheelInputReductionError as error:
        raise SourceWheelCandidateSelectionError(error.code) from error
    return receipt


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--expected-input-entries", type=int, required=True)
    parser.add_argument("--recovery-bindings", type=Path, required=True)
    parser.add_argument("--recovery-bindings-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    return parser.parse_args(argv)


def _public_failure(error: SourceWheelCandidateSelectionError) -> dict[str, object]:
    code = error.code if error.code in PUBLIC_ERROR_CODES else "unexpected_failure"
    result: dict[str, object] = {"status": "failed", "error_code": code}
    if (
        code == "compatible_source_count_insufficient"
        and isinstance(error.counts, dict)
        and set(error.counts) == SELECTION_COUNT_KEYS
        and all(type(value) is int and value >= 0 for value in error.counts.values())
    ):
        result["counts"] = error.counts
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        receipt = select_source_wheel_candidates(
            args.input,
            args.input_sha256,
            args.recovery_bindings,
            args.recovery_bindings_sha256,
            args.output_dir,
            expected_input_entries=args.expected_input_entries,
            timeout_seconds=args.timeout_seconds,
        )
    except SourceWheelCandidateSelectionError as error:
        print(json.dumps(_public_failure(error), sort_keys=True), flush=True)
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "failed", "error_code": "cancelled"}, sort_keys=True), flush=True)
        return 130
    except BaseException:
        print(json.dumps({"status": "failed", "error_code": "unexpected_failure"}, sort_keys=True), flush=True)
        return 1
    print(canonical_json(receipt).decode(), flush=True)
    return 0
