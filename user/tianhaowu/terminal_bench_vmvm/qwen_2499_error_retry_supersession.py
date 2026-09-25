#!/usr/bin/env python3
"""Supersede the frozen Qwen retry certificate without mutating its evidence.

The launch-time certificate was produced by frozen code whose SFT validator
rejected standard, null-valued OpenAI response fields.  This module consumes
that immutable certificate, revalidates the exact run with the current
exporter, and emits independently certified pass-only and unfiltered merges.
Only aggregate counts, digests, and stable error codes are printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import audit_traces
import export_sft
import qwen_2499_error_retry as retry

SCHEMA_VERSION = 1
SUPERSEDING_CERTIFICATE_KIND = "qwen-2499-error-retry-superseding-certificate"
SUPERSEDING_CERTIFICATE_FILENAME = "qwen_2499_error_retry_superseding_certificate.json"
RECOVERED_CERTIFICATE_FILENAME = "qwen_2499_recovered_results_certificate.json"
MERGE_MANIFEST_FILENAME = "merge_manifest.json"
RESULTS_FILENAME = "results.jsonl"
PREDECESSOR_RETRY_MODULE_SHA256 = "09b7f757ad64c1a49aac5cf4dd34d09ea495734192101a2001a6cb205dcacba0"
PREDECESSOR_EXPORTER_SHA256 = "7254c193464213651c0005d7ebbc731d44f0c96552086a1879556a2397349a18"
PREDECESSOR_REPOSITORY_REVISION = "d9a4eb07de3b769899c0e77eedf5da5f6c35ab61"
# The immutable selection manifest predates failed-complete recovery and keeps
# its original producer pin even when a newer, explicitly supplied certifier
# revision replays the run.
SELECTION_RETRY_MODULE_SHA256 = PREDECESSOR_RETRY_MODULE_SHA256
PREDECESSOR_SUBMODULES = {
    "deps/renderers": "044d9e2541f6a911cacae9da353fc063911ef1f8",
    "deps/verifiers": "3df6efa9e9f6bdc8a013df7759a03074aec79111",
}
SUPERSEDING_EXPORTER_SHA256 = "d6386bc08eec676ec1e48913aca37e934cf65c90dabbd0fa99ee5221d5118fbb"
AUDIT_TRACES_SHA256 = "7b20a4e600cdff8213b9be322029087962e700df87dd06f1c702cb4278970ad3"
NULL_WIRE_COMPATIBILITY_ID = "openai-null-wire-fields-v1"
MERGE_MODES = frozenset({"pass-only", "unfiltered"})
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")


class SupersessionError(RuntimeError):
    """A fail-closed supersession error represented by a stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise SupersessionError("arguments_invalid")


@dataclass(frozen=True, slots=True)
class Classification:
    scan: retry.TraceScan
    positive: frozenset[str]
    zero: frozenset[str]
    invalid_positive: frozenset[str]
    invalid_zero: frozenset[str]
    error: frozenset[str]

    def accepted(self, mode: str) -> frozenset[str]:
        if mode == "pass-only":
            return self.positive
        if mode == "unfiltered":
            return self.positive | self.zero
        raise SupersessionError("merge_mode_invalid")

    def counts(self) -> dict[str, int]:
        return {
            "clean_model_bearing": len(self.positive) + len(self.zero),
            "error": len(self.error),
            "invalid_positive": len(self.invalid_positive),
            "invalid_zero": len(self.invalid_zero),
            "positive": len(self.positive),
            "total": sum(
                len(values)
                for values in (
                    self.positive,
                    self.zero,
                    self.invalid_positive,
                    self.invalid_zero,
                    self.error,
                )
            ),
            "zero": len(self.zero),
        }


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _json_bytes(value: object) -> bytes:
    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise SupersessionError("strict_json_invalid") from error
    return rendered.encode("utf-8") + b"\n"


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and retry.SHA256_RE.fullmatch(value) is not None


def _module_sha256() -> str:
    return retry._artifact(Path(__file__).resolve(), "module_unreadable").sha256


def _git(project: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(project), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SupersessionError("project_revision_invalid") from error
    if completed.stderr:
        raise SupersessionError("project_revision_invalid")
    return completed.stdout.strip()


def _project_code(
    project: Path,
    expected_revision: str,
    *,
    expected_retry_module_sha256: str = PREDECESSOR_RETRY_MODULE_SHA256,
) -> dict[str, Any]:
    try:
        resolved = project.resolve(strict=True)
    except OSError as error:
        raise SupersessionError("project_path_invalid") from error
    if resolved != project or not project.is_dir() or GIT_SHA_RE.fullmatch(expected_revision or "") is None:
        raise SupersessionError("project_path_invalid")
    if (
        _git(project, "rev-parse", "--show-toplevel") != str(project)
        or _git(project, "rev-parse", "HEAD") != expected_revision
        or _git(project, "status", "--porcelain=v1", "--untracked-files=all")
    ):
        raise SupersessionError("project_revision_invalid")
    workflow = project / "user" / "tianhaowu" / "terminal_bench_vmvm"
    module = retry._artifact(workflow / Path(__file__).name, "module_unreadable")
    base_module = retry._artifact(workflow / "qwen_2499_error_retry.py", "module_unreadable")
    exporter = retry._artifact(workflow / "export_sft.py", "module_unreadable")
    audit_module = retry._artifact(workflow / "audit_traces.py", "module_unreadable")
    if (
        module.sha256 != _module_sha256()
        or not _valid_sha256(expected_retry_module_sha256)
        or base_module.sha256 != expected_retry_module_sha256
        or exporter.sha256 != SUPERSEDING_EXPORTER_SHA256
        or audit_module.sha256 != AUDIT_TRACES_SHA256
    ):
        raise SupersessionError("project_code_invalid")
    submodules: dict[str, str] = {}
    for relative in ("deps/verifiers", "deps/renderers"):
        record = _git(project, "ls-tree", "HEAD", "--", relative).split(maxsplit=3)
        if len(record) != 4 or record[:2] != ["160000", "commit"] or record[3] != relative:
            raise SupersessionError("project_submodule_invalid")
        checkout = project / relative
        if _git(checkout, "rev-parse", "HEAD") != record[2] or _git(
            checkout, "status", "--porcelain=v1", "--untracked-files=all"
        ):
            raise SupersessionError("project_submodule_invalid")
        submodules[relative] = record[2]
    return {
        "audit_traces_sha256": audit_module.sha256,
        "exporter_sha256": exporter.sha256,
        "qwen_2499_error_retry_sha256": base_module.sha256,
        "repository_revision": expected_revision,
        "submodules": submodules,
        "supersession_module_sha256": module.sha256,
    }


def _validate_predecessor_with_frozen_code(
    *,
    project_dir: Path,
    expected_project_revision: str,
    contract: Path,
    contract_sha256: str,
    run_dir: Path,
    predecessor_certificate: Path,
    predecessor_certificate_sha256: str,
    expected_retry_module_sha256: str = PREDECESSOR_RETRY_MODULE_SHA256,
    expected_exporter_sha256: str = PREDECESSOR_EXPORTER_SHA256,
) -> None:
    """Replay the old certificate computation with the exact frozen producer."""
    if (
        GIT_SHA_RE.fullmatch(expected_project_revision or "") is None
        or not _valid_sha256(expected_retry_module_sha256)
        or not _valid_sha256(expected_exporter_sha256)
    ):
        raise SupersessionError("predecessor_project_revision_invalid")
    try:
        project = project_dir.resolve(strict=True)
    except OSError as error:
        raise SupersessionError("predecessor_project_invalid") from error
    if (
        project != project_dir
        or _git(project, "rev-parse", "--show-toplevel") != str(project)
        or _git(project, "rev-parse", "HEAD") != expected_project_revision
        or _git(project, "status", "--porcelain=v1", "--untracked-files=all")
    ):
        raise SupersessionError("predecessor_project_invalid")
    workflow = project / "user" / "tianhaowu" / "terminal_bench_vmvm"
    if (
        retry._artifact(workflow / "qwen_2499_error_retry.py", "module_unreadable").sha256
        != expected_retry_module_sha256
        or retry._artifact(workflow / "export_sft.py", "module_unreadable").sha256
        != expected_exporter_sha256
        or retry._artifact(workflow / "audit_traces.py", "module_unreadable").sha256
        != AUDIT_TRACES_SHA256
    ):
        raise SupersessionError("predecessor_project_invalid")
    for relative, expected in PREDECESSOR_SUBMODULES.items():
        record = _git(project, "ls-tree", "HEAD", "--", relative).split(maxsplit=3)
        checkout = project / relative
        if (
            len(record) != 4
            or record[:2] != ["160000", "commit"]
            or record[2] != expected
            or record[3] != relative
            or _git(checkout, "rev-parse", "HEAD") != expected
            or _git(checkout, "status", "--porcelain=v1", "--untracked-files=all")
        ):
            raise SupersessionError("predecessor_submodule_invalid")

    verifier = r'''
import hashlib
import json
import sys
from pathlib import Path

import qwen_2499_error_retry as retry

contract = Path(sys.argv[1])
contract_sha256 = sys.argv[2]
run_dir = Path(sys.argv[3])
certificate_path = Path(sys.argv[4])
certificate_sha256 = sys.argv[5]
selection, _body = retry._load_contract(contract, contract_sha256)
context = retry._context_from_contract(selection)
with retry._completed_run_lock(run_dir):
    scan, evidence, runtime = retry._run_evidence(context, selection, run_dir)
    expected = retry._retry_certificate_value(
        contract_sha256=contract_sha256,
        retry_scan=scan,
        evidence=evidence,
        runtime=runtime,
        context=context,
    )
    observed, body = retry._load_retry_certificate(certificate_path, certificate_sha256)
if observed != expected:
    raise SystemExit(2)
print(json.dumps({"certificate_sha256": hashlib.sha256(body).hexdigest(), "state": "verified"}, sort_keys=True))
'''
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = ":".join(
        (
            str(workflow),
            str(project / "environments" / "vmvm_tb_v2"),
            str(project / "deps" / "verifiers"),
            str(project / "deps" / "renderers"),
            str(project / "deps" / "pydantic-config" / "src"),
        )
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                verifier,
                str(contract),
                contract_sha256,
                str(run_dir),
                str(predecessor_certificate),
                predecessor_certificate_sha256,
            ],
            cwd=project,
            env=environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3_600,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SupersessionError("predecessor_replay_failed") from error
    try:
        summary = json.loads(completed.stdout)
    except (UnicodeDecodeError, ValueError) as error:
        raise SupersessionError("predecessor_replay_failed") from error
    if (
        completed.returncode != 0
        or completed.stderr
        or summary != {"certificate_sha256": predecessor_certificate_sha256, "state": "verified"}
    ):
        raise SupersessionError("predecessor_replay_failed")


def _trace_is_trainable(trace: dict[str, Any], reward: float) -> bool:
    problems = audit_traces._audit_trace(
        trace,
        require_reasoning=True,
        max_sequence_tokens=retry.MAX_SEQUENCE_TOKENS,
        require_token_data=False,
        require_logprobs=False,
        require_model_io=True,
        model_io_contract=retry.RETRY_MODEL_IO_CONTRACT,
        require_request_graph_match=True,
        require_exact_provider_json=True,
        require_clean_stop=True,
    )
    if problems:
        return False
    try:
        export_sft._validate_trainable_trace(
            trace,
            reward=reward,
            max_sequence_tokens=retry.MAX_SEQUENCE_TOKENS,
            require_exact_provider_json=True,
        )
    except export_sft.ExportError:
        return False
    return True


def _classify_retry_rows(context: retry.SelectionContext, scan: retry.TraceScan) -> Classification:
    classified: dict[str, set[str]] = {
        "positive": set(),
        "zero": set(),
        "invalid_positive": set(),
        "invalid_zero": set(),
        "error": set(),
    }
    for member in context.retry_members:
        record = scan.rows[member]
        if record.outcome == "error":
            classified["error"].add(member)
            continue
        raw = retry._read_indexed_row(context.expected_run_dir / RESULTS_FILENAME, record)
        trace = retry._parse_object(raw, "results_jsonl_invalid")
        reward = retry._strict_reward(trace)
        clean = _trace_is_trainable(trace, reward)
        if reward == 1.0:
            classified["positive" if clean else "invalid_positive"].add(member)
        elif reward == 0.0:
            classified["zero" if clean else "invalid_zero"].add(member)
        else:
            raise SupersessionError("trace_reward_invalid")
    result = Classification(
        scan=scan,
        positive=frozenset(classified["positive"]),
        zero=frozenset(classified["zero"]),
        invalid_positive=frozenset(classified["invalid_positive"]),
        invalid_zero=frozenset(classified["invalid_zero"]),
        error=frozenset(classified["error"]),
    )
    if result.counts()["total"] != retry.ERROR_RETRY_COUNT:
        raise SupersessionError("retry_coverage_invalid")
    return result


def _validate_predecessor_value(
    value: Mapping[str, Any],
    *,
    contract_sha256: str,
    evidence: Mapping[str, Any],
    runtime: Mapping[str, Any],
    expected_retry_module_sha256: str = PREDECESSOR_RETRY_MODULE_SHA256,
) -> None:
    outcomes = value.get("retry_outcomes")
    accepted = value.get("accepted")
    trace_contract = value.get("trace_contract")
    code = value.get("code")
    if (
        set(value)
        != {
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
        }
        or value.get("schema_version") != retry.SCHEMA_VERSION
        or value.get("kind") != retry.RETRY_CERTIFICATE_KIND
        or value.get("state") != "passed"
        or value.get("selection_contract_sha256") != contract_sha256
        or value.get("run") != evidence
        or value.get("runtime") != runtime
        or not isinstance(outcomes, Mapping)
        or set(outcomes)
        != {"accepted_positive", "error", "invalid_positive", "retained_original", "total", "zero"}
        or any(not retry._plain_int(outcomes.get(key)) for key in outcomes)
        or outcomes.get("total") != retry.ERROR_RETRY_COUNT
        or outcomes.get("accepted_positive", -1)
        + outcomes.get("error", -1)
        + outcomes.get("invalid_positive", -1)
        + outcomes.get("zero", -1)
        != retry.ERROR_RETRY_COUNT
        or outcomes.get("retained_original")
        != retry.ERROR_RETRY_COUNT - outcomes.get("accepted_positive", -1)
        or not isinstance(accepted, Mapping)
        or set(accepted) != {"canonical_indices_sha256", "count", "predicate", "row_sha256_set_sha256"}
        or accepted.get("count") != outcomes.get("accepted_positive")
        or accepted.get("predicate") != "reward-one-and-exact-model-io-and-sft-trainable"
        or not _valid_sha256(accepted.get("canonical_indices_sha256"))
        or not _valid_sha256(accepted.get("row_sha256_set_sha256"))
        or trace_contract
        != {
            "id": retry.RETRY_MODEL_IO_CONTRACT_ID,
            "max_sequence_tokens": retry.MAX_SEQUENCE_TOKENS,
            "sha256": audit_traces.model_io_contract_sha256(retry.RETRY_MODEL_IO_CONTRACT),
        }
        or not _valid_sha256(expected_retry_module_sha256)
        or code != {"module_sha256": expected_retry_module_sha256}
    ):
        raise SupersessionError("predecessor_certificate_invalid")


def _load_predecessor(
    path: Path,
    expected_sha256: str,
    *,
    run_dir: Path,
    contract_sha256: str,
    evidence: Mapping[str, Any],
    runtime: Mapping[str, Any],
    expected_retry_module_sha256: str = PREDECESSOR_RETRY_MODULE_SHA256,
) -> tuple[dict[str, Any], retry.Artifact]:
    if path != run_dir / retry.RETRY_CERTIFICATE_FILENAME:
        raise SupersessionError("predecessor_certificate_binding_invalid")
    try:
        value, body = retry._load_retry_certificate(path, expected_sha256)
    except retry.QwenRetryError as error:
        raise SupersessionError("predecessor_certificate_invalid") from error
    _validate_predecessor_value(
        value,
        contract_sha256=contract_sha256,
        evidence=evidence,
        runtime=runtime,
        expected_retry_module_sha256=expected_retry_module_sha256,
    )
    return value, retry.Artifact(len(body), _sha256(body))


def _accepted_value(
    members: frozenset[str],
    *,
    context: retry.SelectionContext,
    classification: Classification,
    predicate: str,
) -> dict[str, Any]:
    universe_indices = {member: index for index, member in enumerate(context.universe_members)}
    return {
        "canonical_indices_sha256": retry._indices_sha256(
            universe_indices[member] for member in context.universe_members if member in members
        ),
        "count": len(members),
        "predicate": predicate,
        "row_sha256_set_sha256": _sha256(
            "".join(f"{classification.scan.rows[member].row_sha256}\n" for member in sorted(members)).encode()
        ),
    }


def _superseding_certificate_value(
    *,
    contract_sha256: str,
    predecessor_sha256: str,
    predecessor: Mapping[str, Any],
    predecessor_artifact: retry.Artifact,
    predecessor_project_revision: str,
    predecessor_retry_module_sha256: str,
    predecessor_exporter_sha256: str,
    evidence: Mapping[str, Any],
    runtime: Mapping[str, Any],
    context: retry.SelectionContext,
    classification: Classification,
    code: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": SUPERSEDING_CERTIFICATE_KIND,
        "state": "passed",
        "selection_contract_sha256": contract_sha256,
        "predecessor": {
            "artifact": predecessor_artifact.value(),
            "accepted_positive": predecessor["accepted"]["count"],
            "exporter_sha256": predecessor_exporter_sha256,
            "kind": predecessor["kind"],
            "module_sha256": predecessor_retry_module_sha256,
            "repository_revision": predecessor_project_revision,
            "sha256": predecessor_sha256,
        },
        "migration": {
            "compatibility_id": NULL_WIRE_COMPATIBILITY_ID,
            "policy": "permit-standard-null-openai-wire-fields-only",
        },
        "run": dict(evidence),
        "runtime": dict(runtime),
        "outcomes": classification.counts(),
        "accepted": {
            "pass_only": _accepted_value(
                classification.positive,
                context=context,
                classification=classification,
                predicate="reward-one-and-exact-model-io-and-sft-trainable",
            ),
            "unfiltered": _accepted_value(
                classification.positive | classification.zero,
                context=context,
                classification=classification,
                predicate="binary-reward-and-exact-model-io-and-sft-structurally-valid",
            ),
        },
        "trace_contract": {
            "id": retry.RETRY_MODEL_IO_CONTRACT_ID,
            "max_sequence_tokens": retry.MAX_SEQUENCE_TOKENS,
            "require_exact_provider_json": True,
            "require_model_io": True,
            "require_reasoning": True,
            "require_request_graph_match": True,
            "sha256": audit_traces.model_io_contract_sha256(retry.RETRY_MODEL_IO_CONTRACT),
        },
        "code": dict(code),
    }


def _load_context_and_run(
    contract: Path,
    contract_sha256: str,
    run_dir: Path,
) -> tuple[dict[str, Any], retry.SelectionContext, retry.TraceScan, dict[str, Any], dict[str, Any]]:
    try:
        selection, _body = retry._load_contract(contract, contract_sha256)
        if selection.get("code") != {"module_sha256": SELECTION_RETRY_MODULE_SHA256}:
            raise SupersessionError("selection_code_invalid")
        context = retry._context_from_contract(selection)
        scan, evidence, runtime = retry._run_evidence(context, selection, run_dir)
    except retry.QwenRetryError as error:
        raise SupersessionError("run_evidence_invalid") from error
    return selection, context, scan, evidence, runtime


def _build_superseding_certificate(
    *,
    contract: Path,
    contract_sha256: str,
    run_dir: Path,
    predecessor_certificate: Path,
    predecessor_certificate_sha256: str,
    predecessor_project_dir: Path,
    expected_predecessor_project_revision: str,
    expected_predecessor_retry_module_sha256: str = PREDECESSOR_RETRY_MODULE_SHA256,
    expected_predecessor_exporter_sha256: str = PREDECESSOR_EXPORTER_SHA256,
    project_dir: Path,
    expected_project_revision: str,
) -> tuple[dict[str, Any], retry.SelectionContext, Classification]:
    _selection, context, scan, evidence, runtime = _load_context_and_run(contract, contract_sha256, run_dir)
    predecessor, predecessor_artifact = _load_predecessor(
        predecessor_certificate,
        predecessor_certificate_sha256,
        run_dir=run_dir,
        contract_sha256=contract_sha256,
        evidence=evidence,
        runtime=runtime,
        expected_retry_module_sha256=expected_predecessor_retry_module_sha256,
    )
    classification = _classify_retry_rows(context, scan)
    if classification.invalid_positive or classification.invalid_zero:
        raise SupersessionError("retry_row_invalid")
    code = _project_code(
        project_dir,
        expected_project_revision,
        expected_retry_module_sha256=expected_predecessor_retry_module_sha256,
    )
    certificate = _superseding_certificate_value(
        contract_sha256=contract_sha256,
        predecessor_sha256=predecessor_certificate_sha256,
        predecessor=predecessor,
        predecessor_artifact=predecessor_artifact,
        predecessor_project_revision=expected_predecessor_project_revision,
        predecessor_retry_module_sha256=expected_predecessor_retry_module_sha256,
        predecessor_exporter_sha256=expected_predecessor_exporter_sha256,
        evidence=evidence,
        runtime=runtime,
        context=context,
        classification=classification,
        code=code,
    )
    return certificate, context, classification


def certify(
    *,
    contract: Path,
    contract_sha256: str,
    run_dir: Path,
    predecessor_certificate: Path,
    predecessor_certificate_sha256: str,
    predecessor_project_dir: Path,
    expected_predecessor_project_revision: str,
    project_dir: Path,
    expected_project_revision: str,
    output: Path,
    expected_predecessor_retry_module_sha256: str = PREDECESSOR_RETRY_MODULE_SHA256,
    expected_predecessor_exporter_sha256: str = PREDECESSOR_EXPORTER_SHA256,
) -> dict[str, Any]:
    run_dir = retry._normalized_absolute(run_dir, "run_dir_invalid")
    output = retry._normalized_absolute(output, "certificate_output_invalid", must_exist=False)
    if output != run_dir / SUPERSEDING_CERTIFICATE_FILENAME:
        raise SupersessionError("certificate_output_binding_invalid")
    _validate_predecessor_with_frozen_code(
        project_dir=predecessor_project_dir,
        expected_project_revision=expected_predecessor_project_revision,
        contract=contract,
        contract_sha256=contract_sha256,
        run_dir=run_dir,
        predecessor_certificate=predecessor_certificate,
        predecessor_certificate_sha256=predecessor_certificate_sha256,
        expected_retry_module_sha256=expected_predecessor_retry_module_sha256,
        expected_exporter_sha256=expected_predecessor_exporter_sha256,
    )
    with retry._completed_run_lock(run_dir):
        certificate, _context, classification = _build_superseding_certificate(
            contract=contract,
            contract_sha256=contract_sha256,
            run_dir=run_dir,
            predecessor_certificate=predecessor_certificate,
            predecessor_certificate_sha256=predecessor_certificate_sha256,
            predecessor_project_dir=predecessor_project_dir,
            expected_predecessor_project_revision=expected_predecessor_project_revision,
            expected_predecessor_retry_module_sha256=expected_predecessor_retry_module_sha256,
            expected_predecessor_exporter_sha256=expected_predecessor_exporter_sha256,
            project_dir=project_dir,
            expected_project_revision=expected_project_revision,
        )
        try:
            artifact = retry._write_exclusive(output, _json_bytes(certificate))
        except retry.QwenRetryError as error:
            raise SupersessionError("certificate_publish_failed") from error
    counts = classification.counts()
    return {
        "clean_model_bearing": counts["clean_model_bearing"],
        "error": counts["error"],
        "invalid": counts["invalid_positive"] + counts["invalid_zero"],
        "positive": counts["positive"],
        "state": "superseded",
        "superseding_certificate_sha256": artifact.sha256,
        "total": counts["total"],
        "zero": counts["zero"],
    }


def _load_superseding_certificate(path: Path, expected_sha256: str) -> tuple[dict[str, Any], bytes]:
    if not _valid_sha256(expected_sha256):
        raise SupersessionError("superseding_certificate_digest_invalid")
    try:
        body, artifact = retry._read_regular(
            path,
            "superseding_certificate_invalid",
            max_bytes=retry.MAX_CERTIFICATE_BYTES,
            required_mode=0o600,
        )
    except retry.QwenRetryError as error:
        raise SupersessionError("superseding_certificate_invalid") from error
    try:
        value = retry._parse_object(body, "superseding_certificate_invalid", canonical=True)
    except retry.QwenRetryError as error:
        raise SupersessionError("superseding_certificate_invalid") from error
    if (
        artifact.sha256 != expected_sha256
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != SUPERSEDING_CERTIFICATE_KIND
        or value.get("state") != "passed"
    ):
        raise SupersessionError("superseding_certificate_invalid")
    return value, body


def _write_recovered_results(
    path: Path,
    *,
    context: retry.SelectionContext,
    classification: Classification,
    accepted: frozenset[str],
) -> tuple[retry.Artifact, dict[str, int]]:
    continuation = frozenset(context.continuation_members)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    digest = hashlib.sha256()
    size = 0
    counts: Counter[str] = Counter()
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            for member in context.universe_members:
                if member in accepted:
                    source = context.expected_run_dir / RESULTS_FILENAME
                    record = classification.scan.rows[member]
                    outcome = "positive" if member in classification.positive else "zero"
                elif member in continuation:
                    source = context.continuation_results
                    record = context.continuation_scan.rows[member]
                    outcome = record.outcome
                else:
                    source = context.original_results
                    record = context.original_scan.rows[member]
                    outcome = record.outcome
                body = retry._read_indexed_row(source, record)
                output.write(body)
                digest.update(body)
                size += len(body)
                counts[outcome if outcome != "invalid_positive" else "error"] += 1
            output.flush()
            os.fsync(output.fileno())
    except OSError as error:
        raise SupersessionError("merged_results_publish_failed") from error
    if sum(counts.values()) != retry.CANONICAL_UNIVERSE_COUNT:
        raise SupersessionError("merged_coverage_invalid")
    return retry.Artifact(size, digest.hexdigest()), {
        "error": counts.get("error", 0),
        "positive": counts.get("positive", 0),
        "zero": counts.get("zero", 0),
    }


def merge(
    *,
    contract: Path,
    contract_sha256: str,
    run_dir: Path,
    predecessor_certificate: Path,
    predecessor_certificate_sha256: str,
    predecessor_project_dir: Path,
    expected_predecessor_project_revision: str,
    superseding_certificate: Path,
    superseding_certificate_sha256: str,
    project_dir: Path,
    expected_project_revision: str,
    mode: str,
    output_dir: Path,
    expected_predecessor_retry_module_sha256: str = PREDECESSOR_RETRY_MODULE_SHA256,
    expected_predecessor_exporter_sha256: str = PREDECESSOR_EXPORTER_SHA256,
) -> dict[str, Any]:
    if mode not in MERGE_MODES:
        raise SupersessionError("merge_mode_invalid")
    run_dir = retry._normalized_absolute(run_dir, "run_dir_invalid")
    if superseding_certificate != run_dir / SUPERSEDING_CERTIFICATE_FILENAME:
        raise SupersessionError("superseding_certificate_binding_invalid")
    certificate, _certificate_body = _load_superseding_certificate(
        superseding_certificate,
        superseding_certificate_sha256,
    )
    _validate_predecessor_with_frozen_code(
        project_dir=predecessor_project_dir,
        expected_project_revision=expected_predecessor_project_revision,
        contract=contract,
        contract_sha256=contract_sha256,
        run_dir=run_dir,
        predecessor_certificate=predecessor_certificate,
        predecessor_certificate_sha256=predecessor_certificate_sha256,
        expected_retry_module_sha256=expected_predecessor_retry_module_sha256,
        expected_exporter_sha256=expected_predecessor_exporter_sha256,
    )
    with retry._completed_run_lock(run_dir):
        expected, context, classification = _build_superseding_certificate(
            contract=contract,
            contract_sha256=contract_sha256,
            run_dir=run_dir,
            predecessor_certificate=predecessor_certificate,
            predecessor_certificate_sha256=predecessor_certificate_sha256,
            predecessor_project_dir=predecessor_project_dir,
            expected_predecessor_project_revision=expected_predecessor_project_revision,
            expected_predecessor_retry_module_sha256=expected_predecessor_retry_module_sha256,
            expected_predecessor_exporter_sha256=expected_predecessor_exporter_sha256,
            project_dir=project_dir,
            expected_project_revision=expected_project_revision,
        )
        if certificate != expected:
            raise SupersessionError("superseding_certificate_evidence_mismatch")
        accepted = classification.accepted(mode)
        try:
            output = retry._create_private_output(output_dir)
        except retry.QwenRetryError as error:
            raise SupersessionError("output_create_failed") from error
        try:
            results, outcomes = _write_recovered_results(
                output / RESULTS_FILENAME,
                context=context,
                classification=classification,
                accepted=accepted,
            )
            expected_positive = retry.BASE_POSITIVE_COUNT + len(classification.positive)
            expected_zero = retry.BASE_ZERO_COUNT + (len(classification.zero) if mode == "unfiltered" else 0)
            expected_error = retry.BASE_ERROR_COUNT - len(accepted)
            if outcomes != {
                "error": expected_error,
                "positive": expected_positive,
                "zero": expected_zero,
            }:
                raise SupersessionError("merged_outcome_partition_invalid")
            recovered_certificate = {
                "schema_version": SCHEMA_VERSION,
                "kind": "qwen-2499-error-retry-recovered-results",
                "state": "passed",
                "mode": mode,
                "coverage": {
                    "canonical_order": True,
                    "exact": True,
                    "exhaustive": True,
                    "task_count": retry.CANONICAL_UNIVERSE_COUNT,
                    "universe_task_file_sha256": retry.CANONICAL_UNIVERSE_TASK_FILE_SHA256,
                },
                "lineage": {
                    "selection_contract_sha256": contract_sha256,
                    "superseding_certificate_sha256": superseding_certificate_sha256,
                },
                "outcomes": outcomes,
                "replacements": {
                    "clean_model_bearing": len(accepted),
                    "positive": len(classification.positive),
                    "zero": len(classification.zero) if mode == "unfiltered" else 0,
                },
                "results": results.value(path=output / RESULTS_FILENAME),
                "trace_contract": {
                    "max_sequence_tokens": retry.MAX_SEQUENCE_TOKENS,
                    "replacement_rows_have_model_io": True,
                    "replacement_rows_have_reasoning": True,
                    "replacement_rows_request_graph_valid": True,
                },
                "code": certificate["code"],
            }
            recovered_artifact = retry._write_exclusive(
                output / RECOVERED_CERTIFICATE_FILENAME,
                _json_bytes(recovered_certificate),
            )
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "kind": "qwen-2499-error-retry-recovered-results-manifest",
                "state": "ready",
                "mode": mode,
                "artifacts": {
                    "certificate": recovered_artifact.value(path=output / RECOVERED_CERTIFICATE_FILENAME),
                    "results": results.value(path=output / RESULTS_FILENAME),
                },
                "lineage": recovered_certificate["lineage"],
                "outcomes": outcomes,
                "sft_selection": "pass-only" if mode == "pass-only" else None,
            }
            manifest_artifact = retry._write_exclusive(
                output / MERGE_MANIFEST_FILENAME,
                _json_bytes(manifest),
            )
        except BaseException:
            retry._remove_owned_output(output)
            raise
    return {
        "certificate_sha256": recovered_artifact.sha256,
        "error": outcomes["error"],
        "manifest_sha256": manifest_artifact.sha256,
        "mode": mode,
        "positive": outcomes["positive"],
        "replaced": len(accepted),
        "state": "merged",
        "task_count": retry.CANONICAL_UNIVERSE_COUNT,
        "zero": outcomes["zero"],
    }


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--predecessor-certificate", type=Path, required=True)
    parser.add_argument("--predecessor-certificate-sha256", required=True)
    parser.add_argument("--predecessor-project-dir", type=Path, required=True)
    parser.add_argument("--expected-predecessor-project-revision", required=True)
    parser.add_argument(
        "--expected-predecessor-retry-module-sha256",
        default=PREDECESSOR_RETRY_MODULE_SHA256,
    )
    parser.add_argument(
        "--expected-predecessor-exporter-sha256",
        default=PREDECESSOR_EXPORTER_SHA256,
    )
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--expected-project-revision", required=True)


def _parser() -> StableArgumentParser:
    parser = StableArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    certifier = commands.add_parser("certify")
    _add_common(certifier)
    certifier.add_argument("--output", type=Path, required=True)
    merger = commands.add_parser("merge")
    _add_common(merger)
    merger.add_argument("--superseding-certificate", type=Path, required=True)
    merger.add_argument("--superseding-certificate-sha256", required=True)
    merger.add_argument("--mode", choices=sorted(MERGE_MODES), required=True)
    merger.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = vars(_parser().parse_args(argv))
        command = args.pop("command")
        summary = certify(**args) if command == "certify" else merge(**args)
    except SupersessionError as error:
        print(json.dumps({"code": error.code, "status": "error"}, sort_keys=True), file=os.sys.stderr)
        return 2
    except retry.QwenRetryError:
        print(json.dumps({"code": "base_validation_failed", "status": "error"}, sort_keys=True), file=os.sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"code": "internal_failure", "status": "error"}, sort_keys=True), file=os.sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
