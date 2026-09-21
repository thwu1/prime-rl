#!/usr/bin/env python3
"""Certify and export the sealed Qwen continuation under a pass-only SFT contract."""

from __future__ import annotations

import argparse
import copy
import ctypes
import errno
import fcntl
import hashlib
import json
import math
import os
import secrets
import shutil
import stat
import subprocess
import tomllib
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator, Mapping

import audit_traces
import export_sft as sft
import merge_qwen_sft as legacy_merge
import sandoq_source_continuation as launch
from materialize_qwen_provider_union import CANONICAL_SOURCE_COUNT, SANDOQ_COUNT, derive_partition

SCHEMA_VERSION = 1
CERTIFICATE_KIND = "qwen-sandoq-source-continuation-pass-only"
EXPORT_KIND = "qwen-sandoq-source-continuation-pass-only-merged-sft"
COMBINED_MODEL_IO_CONTRACT_ID = "qwen3-a95b-epoch3-source+qwen3-a95b-direct-medium"
CERTIFICATE_FILENAME = "qwen_source_continuation_pass_only_certificate.json"
MANIFEST_FILENAME = "manifest.json"
CERTIFICATE_COPY_FILENAME = "source-continuation-pass-only-certificate.json"
FROZEN_PLAN_SHA256 = "69e2f165be8fc32d875aea1fce11da25a499104c283485db86403372d9aa3139"
FROZEN_LAUNCH_CODE = {
    "base_revision": "f58af6b387affd1ecd72db2dea2882f6dd28c35d",
    "files": {
        "audit_traces.py": "0b274791a98015cbac29d86cab77b918484fa278827b3decb5ee5521370999fb",
        "direct_qwen_workers.py": "bf54115f6f15603b6b83f332a8cf13c382dc96abd2d73ba53c146333290d2cbb",
        "run_direct_qwen_eval_driver.sh": "5de1590cc1f3281743139f8e1c009f1408e93ff97bf56973bc4c37c501f30ba8",
        "run_qwen_direct_eval.sbatch": "5804a1c8534518f12b71d59048b3842b06f5e35439c7343692808d72eb1d10b5",
        "sandoq_source_continuation.py": "79037a67cc0524f8d764a78acdfbb35a4d62871bb5005de2acf1da1cf660423d",
    },
    "repository_revision": "7f0e35340f9ad71d3f7325b970e0af5e87e8fae7",
    "repository_tree": "5580c7a511136cf8df2dc767f9b95f5646fd3034",
}
RETAINED_COUNT = 1_266
RETAINED_POSITIVE_COUNT = 749
RETAINED_ZERO_REWARD_COUNT = 517
CONTINUATION_COUNT = launch.CONTINUATION_COUNT
CANONICAL_SANDOQ_COUNT = SANDOQ_COUNT
MAX_JSONL_ROW_BYTES = 128 << 20
SPLIT_POLICY = "sha256(split_salt + NUL + stable task identity SHA-256) modulo 10000"


class PassOnlyError(RuntimeError):
    """A stable aggregate-only failure."""


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise PassOnlyError("arguments_invalid")


@dataclass(frozen=True, slots=True)
class Artifact:
    bytes: int
    sha256: str

    def value(self) -> dict[str, int | str]:
        return {"bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class TraceIndex:
    offset: int
    length: int
    source_index: int
    row_sha256: str
    slug: str
    task_id: str
    outcome: str


@dataclass(frozen=True, slots=True)
class PassOnlyAudit:
    results: Artifact
    input_traces: int
    covered_tasks: int
    error_traces: int
    zero_reward_traces: int
    positive_traces: int
    trainable_positive_traces: int
    nonexported_length_traces: int
    positive_model_io_turns: int
    positive_sampled_tokens: int
    positive_trace_contract: Mapping[str, str]
    rows: Mapping[str, TraceIndex]

    @property
    def nonexported_traces(self) -> int:
        return self.error_traces + self.zero_reward_traces

    def public_value(self) -> dict[str, Any]:
        return {
            "all_outcomes_trainability_claimed": False,
            "covered_tasks": self.covered_tasks,
            "error_traces_nonexported": self.error_traces,
            "exact_task_coverage": True,
            "input_traces": self.input_traces,
            "nonexported_length_traces": self.nonexported_length_traces,
            "nonexported_traces": self.nonexported_traces,
            "positive_model_io_turns": self.positive_model_io_turns,
            "positive_reward_traces": self.positive_traces,
            "positive_sampled_tokens": self.positive_sampled_tokens,
            "positive_trace_contract": dict(self.positive_trace_contract),
            "positive_traces_trainable": self.trainable_positive_traces,
            "results": self.results.value(),
            "selection": "pass-only",
            "zero_reward_traces_nonexported": self.zero_reward_traces,
        }


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _json_bytes(value: object, *, pretty: bool = False) -> bytes:
    try:
        if pretty:
            encoded = json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
        else:
            encoded = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
    except (TypeError, ValueError) as error:
        raise PassOnlyError("strict_json_invalid") from error
    return encoded.encode("utf-8") + b"\n"


def _parse_object(body: bytes, code: str, *, canonical: bool = False) -> dict[str, Any]:
    def reject_constant(_value: str) -> None:
        raise ValueError

    try:
        value = json.loads(body, parse_constant=reject_constant)
    except (UnicodeDecodeError, ValueError) as error:
        raise PassOnlyError(code) from error
    if not isinstance(value, dict) or (canonical and _json_bytes(value) != body):
        raise PassOnlyError(code)
    return value


def _plain_int(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _artifact(body: bytes) -> Artifact:
    return Artifact(bytes=len(body), sha256=_sha256(body))


def _workflow_dir() -> Path:
    return Path(__file__).resolve().parent


def _repository() -> Path:
    return Path(__file__).resolve().parents[3]


def _git(*arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(_repository()), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PassOnlyError("postprocessor_code_invalid") from error
    return result.stdout.strip()


def _postprocessor_code_binding() -> dict[str, Any]:
    revision = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    if (
        status
        or len(revision) != 40
        or len(tree) != 40
        or any(character not in "0123456789abcdef" for character in revision + tree)
    ):
        raise PassOnlyError("postprocessor_code_invalid")
    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(_repository()),
            "merge-base",
            "--is-ancestor",
            FROZEN_LAUNCH_CODE["repository_revision"],
            revision,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=30,
    )
    if ancestor.returncode != 0:
        raise PassOnlyError("postprocessor_code_invalid")
    files = {
        name: _sha256((_workflow_dir() / name).read_bytes())
        for name in (
            "audit_traces.py",
            "certify_direct_qwen_sandoq_partition.py",
            "direct_qwen_union_contract.py",
            "eval_run_identity.py",
            "export_sft.py",
            "materialize_qwen_provider_union.py",
            "merge_qwen_sft.py",
            "qwen_source_continuation_pass_only.py",
            "sandoq_source_continuation.py",
        )
    }
    return {"files": files, "repository_revision": revision, "repository_tree": tree}


def _assert_frozen_launch_files() -> None:
    for name, expected in FROZEN_LAUNCH_CODE["files"].items():
        try:
            observed = _sha256((_workflow_dir() / name).read_bytes())
        except OSError as error:
            raise PassOnlyError("historical_launch_code_invalid") from error
        if observed != expected:
            raise PassOnlyError("historical_launch_code_invalid")
    if (
        _git("rev-parse", f"{FROZEN_LAUNCH_CODE['repository_revision']}^{{tree}}")
        != FROZEN_LAUNCH_CODE["repository_tree"]
    ):
        raise PassOnlyError("historical_launch_code_invalid")


@contextmanager
def _historical_code_binding() -> Iterator[None]:
    _assert_frozen_launch_files()
    original_code_binding = launch._code_binding
    original_canonical_paths = launch._canonical_paths

    def frozen_canonical_paths(
        canonical_source: Path,
        canonical_dataset: Path,
        canonical_template: Path,
    ) -> tuple[Path, Path, Path, bytes, bytes]:
        try:
            source = canonical_source.resolve(strict=True)
            template = canonical_template.resolve(strict=True)
            source_body = launch._read_regular(source, "canonical_source_invalid")
            template_body = launch._read_regular(template, "canonical_template_invalid")
            dataset = launch.verify_canonical_dataset(canonical_dataset)
        except Exception as error:
            raise launch.SourceContinuationError("canonical_input_invalid") from error
        if (
            _sha256(source_body) != launch.CANONICAL_SOURCE_SHA256
            or _sha256(template_body) != launch.CANONICAL_SANDOQ_TEMPLATE_SHA256
        ):
            raise launch.SourceContinuationError("canonical_input_invalid")
        return source, dataset, template, source_body, template_body

    launch._code_binding = lambda: copy.deepcopy(FROZEN_LAUNCH_CODE)
    launch._canonical_paths = frozen_canonical_paths
    try:
        yield
    finally:
        launch._canonical_paths = original_canonical_paths
        launch._code_binding = original_code_binding


def _task_members(body: bytes, *, expected_count: int) -> tuple[str, ...]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PassOnlyError("task_file_invalid") from error
    members = tuple(
        line.strip().split("\t", 1)[0]
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if (
        len(members) != expected_count
        or len(set(members)) != expected_count
        or any(not member or "\x00" in member or "/" in member for member in members)
    ):
        raise PassOnlyError("task_file_invalid")
    return members


def _strict_reward(trace: Mapping[str, Any]) -> float:
    rewards = trace.get("rewards")
    if not isinstance(rewards, Mapping) or not rewards:
        raise PassOnlyError("trace_reward_invalid")
    values = tuple(rewards.values())
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
        for value in values
    ):
        raise PassOnlyError("trace_reward_invalid")
    reward = float(sum(values))
    if reward not in {0.0, 1.0}:
        raise PassOnlyError("trace_reward_invalid")
    return reward


def _captured_finish_reason(node: Mapping[str, Any]) -> str | None:
    model_io = node.get("model_io")
    response = model_io.get("response") if isinstance(model_io, Mapping) else None
    body = response.get("body") if isinstance(response, Mapping) else None
    kind = response.get("kind") if isinstance(response, Mapping) else None
    captured: object = None
    if isinstance(body, Mapping) and kind == "exact_provider_json":
        choices = body.get("choices")
        if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], Mapping):
            captured = choices[0].get("finish_reason")
    elif isinstance(body, Mapping) and kind == "normalized_stream_response":
        captured = body.get("finish_reason")
    committed = node.get("finish_reason")
    if captured is not None and (not isinstance(captured, str) or (committed is not None and committed != captured)):
        raise PassOnlyError("captured_finish_reason_invalid")
    if captured is not None:
        return captured
    return committed if isinstance(committed, str) else None


def _has_length_finish(trace: Mapping[str, Any]) -> bool:
    nodes = trace.get("nodes")
    return isinstance(nodes, list) and any(
        isinstance(node, Mapping) and node.get("sampled") is True and _captured_finish_reason(node) == "length"
        for node in nodes
    )


def _positive_observations(trace: Mapping[str, Any]) -> tuple[int, int]:
    nodes = trace.get("nodes")
    if not isinstance(nodes, list):
        return 0, 0
    model_io_turns = 0
    sampled_tokens = 0
    for node in nodes:
        if not isinstance(node, dict) or node.get("sampled") is not True:
            continue
        if node.get("model_io") is not None:
            model_io_turns += 1
        usage = audit_traces._usage_tokens(node)
        if usage is not None:
            sampled_tokens += usage[1]
    return model_io_turns, sampled_tokens


def _readline(handle: BinaryIO) -> bytes:
    raw = handle.readline(MAX_JSONL_ROW_BYTES + 1)
    if len(raw) > MAX_JSONL_ROW_BYTES:
        raise PassOnlyError("results_row_too_large")
    return raw


def _audit_results(
    handle: BinaryIO,
    *,
    task_context: sft.TaskIdentityContext,
    expected_members: frozenset[str],
    expected_input_traces: int,
    model_io_contract: audit_traces.CapturedModelIOContract,
) -> PassOnlyAudit:
    if not expected_members or not expected_members.issubset(task_context.approved_slugs):
        raise PassOnlyError("coverage_contract_invalid")
    digest = hashlib.sha256()
    row_count = 0
    byte_count = 0
    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    rows: dict[str, TraceIndex] = {}
    counts: Counter[str] = Counter()
    while True:
        offset = handle.tell()
        raw = _readline(handle)
        if not raw:
            break
        row_count += 1
        byte_count += len(raw)
        digest.update(raw)
        if not raw.endswith(b"\n") or not raw.strip():
            raise PassOnlyError("results_jsonl_invalid")
        trace = _parse_object(raw, "results_jsonl_invalid")
        trace_id = trace.get("id")
        task = trace.get("task")
        if not isinstance(trace_id, str) or not trace_id or not isinstance(task, Mapping):
            raise PassOnlyError("trace_identity_invalid")
        trace_id_hash = _sha256(trace_id.encode("utf-8"))
        if trace_id_hash in seen_ids:
            raise PassOnlyError("duplicate_trace_id")
        seen_ids.add(trace_id_hash)
        try:
            slug = sft._opaque_task_slug(task, evaluator_order=task_context.approved_slug_order)
            task_id = sft._task_identity_sha256(task_context, task)
        except sft.ExportError as error:
            raise PassOnlyError("trace_task_identity_invalid") from error
        if slug in seen_slugs:
            raise PassOnlyError("duplicate_task_trace")
        seen_slugs.add(slug)
        if slug not in expected_members:
            continue
        errors = trace.get("errors")
        if not isinstance(errors, list):
            raise PassOnlyError("trace_errors_invalid")
        outcome: str
        if errors:
            outcome = "error"
            counts["error_traces"] += 1
        else:
            reward = _strict_reward(trace)
            if trace.get("is_completed") is not True:
                raise PassOnlyError("trace_not_completed")
            stop_condition = trace.get("stop_condition")
            if not isinstance(stop_condition, str) or not stop_condition:
                raise PassOnlyError("trace_stop_condition_invalid")
            if reward == 0.0:
                outcome = "zero"
                counts["zero_reward_traces"] += 1
                if _has_length_finish(trace):
                    counts["nonexported_length_traces"] += 1
            else:
                outcome = "positive"
                try:
                    sft._validate_trainable_trace(
                        trace,
                        reward=reward,
                        max_sequence_tokens=audit_traces.DEFAULT_MAX_SEQUENCE_TOKENS,
                        model_io_contract=model_io_contract,
                    )
                except sft.ExportError as error:
                    raise PassOnlyError("positive_trace_invalid") from error
                turns, tokens = _positive_observations(trace)
                counts["positive_traces"] += 1
                counts["trainable_positive_traces"] += 1
                counts["positive_model_io_turns"] += turns
                counts["positive_sampled_tokens"] += tokens
        rows[slug] = TraceIndex(
            offset=offset,
            length=len(raw),
            source_index=row_count - 1,
            row_sha256=_sha256(raw),
            slug=slug,
            task_id=task_id,
            outcome=outcome,
        )
    if (
        row_count != expected_input_traces
        or set(rows) != expected_members
        or counts["error_traces"] + counts["zero_reward_traces"] + counts["positive_traces"] != len(expected_members)
        or counts["positive_traces"] != counts["trainable_positive_traces"]
    ):
        raise PassOnlyError("coverage_contract_invalid")
    contract_id = next(
        (
            identifier
            for identifier, contract in audit_traces.MODEL_IO_CONTRACTS.items()
            if contract == model_io_contract
        ),
        None,
    )
    if contract_id is None:
        raise PassOnlyError("positive_trace_contract_invalid")
    return PassOnlyAudit(
        results=Artifact(bytes=byte_count, sha256=digest.hexdigest()),
        input_traces=row_count,
        covered_tasks=len(rows),
        error_traces=counts["error_traces"],
        zero_reward_traces=counts["zero_reward_traces"],
        positive_traces=counts["positive_traces"],
        trainable_positive_traces=counts["trainable_positive_traces"],
        nonexported_length_traces=counts["nonexported_length_traces"],
        positive_model_io_turns=counts["positive_model_io_turns"],
        positive_sampled_tokens=counts["positive_sampled_tokens"],
        positive_trace_contract={
            "id": contract_id,
            "sha256": audit_traces.model_io_contract_sha256(model_io_contract),
        },
        rows=rows,
    )


def _validate_historical_plan(
    *,
    plan: Path,
    plan_sha256: str,
    plan_root: launch.PrivateDirectory,
    source_root: launch.PrivateDirectory | None = None,
) -> launch.ValidatedPlan:
    if plan_sha256 != FROZEN_PLAN_SHA256:
        raise PassOnlyError("historical_plan_invalid")
    plan_body = plan_root.read(plan.name, "historical_plan_invalid")
    value = _parse_object(plan_body, "historical_plan_invalid", canonical=True)
    if value.get("code") != FROZEN_LAUNCH_CODE:
        raise PassOnlyError("historical_plan_invalid")
    outputs = value.get("outputs")
    if not isinstance(outputs, Mapping):
        raise PassOnlyError("historical_plan_invalid")
    try:
        task_file = launch._record_path(outputs.get("task_file"), "historical_plan_invalid")
        config = launch._record_path(outputs.get("config"), "historical_plan_invalid")
        with _historical_code_binding():
            return launch.validate_plan(
                plan=plan,
                plan_sha256=plan_sha256,
                task_file=task_file,
                task_file_sha256=launch.CONTINUATION_TASK_SHA256,
                config=config,
                plan_root=plan_root,
                source_root=source_root,
            )
    except launch.SourceContinuationError as error:
        raise PassOnlyError("historical_plan_invalid") from error


def _task_context(config_body: bytes, task_body: bytes, count: int) -> sft.TaskIdentityContext:
    try:
        config = tomllib.loads(config_body.decode("utf-8"))
        return sft._task_identity_context(config["taskset"], task_body, expected_task_count=count)
    except (KeyError, UnicodeDecodeError, tomllib.TOMLDecodeError, sft.ExportError) as error:
        raise PassOnlyError("task_identity_contract_invalid") from error


def _continuation_certificate_value(
    *,
    validated: launch.ValidatedPlan,
    envelope: Mapping[str, Any],
    shared: Mapping[str, Any],
    provider_source: Mapping[str, Any],
    audit: PassOnlyAudit,
    cleanup: Mapping[str, Any],
    cleanup_hashes: Mapping[str, Any],
    code: Mapping[str, Any],
) -> dict[str, Any]:
    positive = audit.positive_traces
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": CERTIFICATE_KIND,
        "state": "passed",
        "certification_scope": "pass-only-positive-trace-eligibility",
        "all_outcomes_trainability_claimed": False,
        "plan_sha256": validated.sha256,
        "historical_launch": {
            "code": FROZEN_LAUNCH_CODE,
            "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
            "source_revision_bound": True,
        },
        "postprocessor_code": code,
        "run": {
            "config_sha256": _sha256(validated.config_body),
            "results": audit.results.value(),
            "task_count": CONTINUATION_COUNT,
            "task_file_sha256": launch.CONTINUATION_TASK_SHA256,
            "worker_count": 24,
            "worker_manifest_sha256": envelope["identity"]["deployment"]["worker_manifest"]["sha256"],
        },
        "coverage_audit": audit.public_value(),
        "cleanup": {**cleanup, "all_assignments_verified": True},
        "sanitized_cleanup_source_hashes": dict(cleanup_hashes),
        "lineage": validated.value["materialization"]["lineage"],
        "provider_source": provider_source,
        "shared_contract": shared,
        "merge_contract": {
            "canonical_sandoq_coverage_tasks": CANONICAL_SANDOQ_COUNT,
            "continuation_coverage_tasks": CONTINUATION_COUNT,
            "continuation_positive_export_tasks": positive,
            "continuation_nonexported_tasks": audit.nonexported_traces,
            "disjoint_coverage": True,
            "exhaustive_coverage": True,
            "original_order_required": True,
            "retained_coverage_tasks": RETAINED_COUNT,
            "retained_positive_export_tasks": RETAINED_POSITIVE_COUNT,
            "retained_zero_reward_nonexported_tasks": RETAINED_ZERO_REWARD_COUNT,
            "selected_sft_tasks": RETAINED_POSITIVE_COUNT + positive,
            "selection": "pass-only",
        },
    }


def _certificate_paths(plan: Path, run: Path, output: Path) -> tuple[Path, Path, Path]:
    try:
        normalized_plan = launch._normalized_absolute(plan, "historical_plan_invalid")
        normalized_run = launch._normalized_absolute(run, "run_directory_invalid")
        normalized_output = launch._normalized_absolute(output, "certificate_output_invalid")
    except launch.SourceContinuationError as error:
        raise PassOnlyError("path_invalid") from error
    if normalized_output != normalized_run / CERTIFICATE_FILENAME:
        raise PassOnlyError("certificate_output_invalid")
    return normalized_plan, normalized_run, normalized_output


def certify(*, plan: Path, plan_sha256: str, run: Path, output: Path) -> dict[str, Any]:
    plan, run, output = _certificate_paths(plan, run, output)
    publication: launch.PublishedOutputs | None = None
    try:
        with launch.PrivateDirectory.open(plan.parent, "historical_plan_invalid") as plan_root:
            initial = _validate_historical_plan(
                plan=plan,
                plan_sha256=plan_sha256,
                plan_root=plan_root,
            )
            source_path = Path(initial.value["inputs"]["epoch3_source_run"])
            with launch._hold_source_run(source_path) as source_root:
                validated = _validate_historical_plan(
                    plan=plan,
                    plan_sha256=plan_sha256,
                    plan_root=plan_root,
                    source_root=source_root,
                )
                with launch.PrivateDirectory.open(run, "run_directory_invalid") as run_root, ExitStack() as locks:
                    run_root.lock(".writer.lock", locks, "run_lock_invalid")
                    before = launch._run_evidence_snapshots(run_root)
                    try:
                        envelope, shared, execution = launch._validate_run_identity(
                            run=run,
                            root=run_root,
                            validated=validated,
                            expected_snapshots=before,
                        )
                        launch._validate_execution(execution)
                        context = _task_context(validated.config_body, validated.task_body, CONTINUATION_COUNT)
                        with run_root.open_binary("results.jsonl", "continuation_evidence_invalid") as handle:
                            audit = _audit_results(
                                handle,
                                task_context=context,
                                expected_members=frozenset(
                                    _task_members(validated.task_body, expected_count=CONTINUATION_COUNT)
                                ),
                                expected_input_traces=CONTINUATION_COUNT,
                                model_io_contract=audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
                            )
                        with run_root.open_binary(
                            "sandoq_cleanup_audit.json",
                            "continuation_evidence_invalid",
                        ) as cleanup_handle:
                            cleanup, cleanup_hashes = launch.validate_cleanup(
                                Path(f"/proc/self/fd/{cleanup_handle.fileno()}"),
                                expected_task_count=CONTINUATION_COUNT,
                                expected_concurrency=launch.EXECUTION_CONTRACT["rollout_concurrency"],
                            )
                        provider_source = launch._provider_source(envelope["identity"])
                    except PassOnlyError:
                        raise
                    except Exception as error:
                        raise PassOnlyError("continuation_evidence_invalid") from error
                    if (
                        audit.results.sha256 != before["results.jsonl"].sha256
                        or audit.results.bytes != before["results.jsonl"].size_bytes
                        or audit.positive_traces < 1
                        or cleanup.get("assignment_attempts", 0) < CONTINUATION_COUNT
                        or cleanup.get("failures") != 0
                        or cleanup.get("zero_drop") is not True
                        or cleanup.get("audit_sha256") != before["sandoq_cleanup_audit.json"].sha256
                    ):
                        raise PassOnlyError("continuation_evidence_invalid")
                    code = _postprocessor_code_binding()
                    certificate = _continuation_certificate_value(
                        validated=validated,
                        envelope=envelope,
                        shared=shared,
                        provider_source=provider_source,
                        audit=audit,
                        cleanup=cleanup,
                        cleanup_hashes=cleanup_hashes,
                        code=code,
                    )
                    body = _json_bytes(certificate)
                    if (
                        launch._validate_source_run(source_path, held_root=source_root)
                        != validated.value["materialization"]["lineage"]["epoch3_source"]
                    ):
                        raise PassOnlyError("source_changed_during_certification")
                    revalidated = _validate_historical_plan(
                        plan=plan,
                        plan_sha256=plan_sha256,
                        plan_root=plan_root,
                        source_root=source_root,
                    )
                    after = launch._run_evidence_snapshots(run_root)
                    if revalidated.value != validated.value or after != before:
                        raise PassOnlyError("source_changed_during_certification")
                    publication = run_root.publish([(output, body)], "certificate_publish_failed")
    except launch.SourceContinuationError as error:
        if publication is not None:
            publication.rollback()
        raise PassOnlyError("certification_failed") from error
    except BaseException:
        if publication is not None:
            publication.rollback()
        raise
    if publication is None:
        raise PassOnlyError("certificate_publish_failed")
    publication.commit()
    return {
        "continuation_coverage_tasks": CONTINUATION_COUNT,
        "continuation_nonexported_tasks": audit.nonexported_traces,
        "continuation_positive_export_tasks": audit.positive_traces,
        "state": "passed",
    }


def _load_bound_certificate(
    root: launch.PrivateDirectory,
    *,
    expected_sha256: str,
    expected_code: Mapping[str, Any],
) -> tuple[dict[str, Any], bytes]:
    if launch.SHA256_RE.fullmatch(expected_sha256 or "") is None:
        raise PassOnlyError("certificate_digest_invalid")
    body = root.read(CERTIFICATE_FILENAME, "certificate_invalid")
    if _sha256(body) != expected_sha256:
        raise PassOnlyError("certificate_digest_mismatch")
    value = _parse_object(body, "certificate_invalid", canonical=True)
    if value.get("postprocessor_code") != expected_code:
        raise PassOnlyError("certificate_invalid")
    return value, body


def _require_exact_certificate(body: bytes, expected: Mapping[str, Any]) -> None:
    if body != _json_bytes(expected):
        raise PassOnlyError("certificate_evidence_mismatch")


class _RowSink:
    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        self._handle = os.fdopen(os.open(path, flags, 0o600), "wb")
        self._digest = hashlib.sha256()
        self.rows = 0
        self.bytes = 0

    def write(self, value: Mapping[str, Any]) -> None:
        body = _json_bytes(value)
        self._handle.write(body)
        self._digest.update(body)
        self.rows += 1
        self.bytes += len(body)

    def close(self) -> Artifact:
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()
        return Artifact(bytes=self.bytes, sha256=self._digest.hexdigest())

    def abort(self) -> None:
        if not self._handle.closed:
            self._handle.close()


def _write_file(path: Path, body: bytes) -> Artifact:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o600), "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    return _artifact(body)


def _read_indexed_trace(handle: BinaryIO, record: TraceIndex) -> tuple[dict[str, Any], bytes]:
    handle.seek(record.offset)
    raw = handle.read(record.length)
    if len(raw) != record.length or _sha256(raw) != record.row_sha256:
        raise PassOnlyError("results_changed")
    return _parse_object(raw, "results_jsonl_invalid"), raw


def _emit_positive_trace(
    *,
    trace: dict[str, Any],
    record: TraceIndex,
    merged_source_index: int,
    split: str,
    split_row_index: int,
    model_io_contract: audit_traces.CapturedModelIOContract,
    sink: _RowSink,
) -> int:
    try:
        _nodes, tools = sft._validate_trainable_trace(
            trace,
            reward=1.0,
            max_sequence_tokens=audit_traces.DEFAULT_MAX_SEQUENCE_TOKENS,
            model_io_contract=model_io_contract,
        )
        emitted = 0
        for row in sft._target_rows(
            trace,
            source_trace_index=merged_source_index,
            source_split_row_index=split_row_index,
            source_trace_sha256=record.row_sha256,
            task_sha256=record.task_id,
            reward=1.0,
            tools=tools,
            routing_epoch=None,
        ):
            sink.write(row)
            emitted += 1
    except sft.ExportError as error:
        raise PassOnlyError("positive_trace_invalid") from error
    if emitted < 1:
        raise PassOnlyError("positive_trace_has_no_targets")
    return emitted


def _canonical_partition(
    validated: launch.ValidatedPlan,
) -> tuple[Artifact, tuple[str, ...], tuple[str, ...], frozenset[str], tuple[str, ...]]:
    canonical_path = Path(validated.value["inputs"]["canonical_source"]["path"])
    try:
        canonical_body = launch._read_regular(canonical_path, "canonical_source_invalid")
        canonical = tuple(canonical_body.decode("utf-8").splitlines())
        partition = derive_partition(canonical_body, validated.dataset)
    except Exception as error:
        raise PassOnlyError("canonical_partition_invalid") from error
    selected = frozenset(_task_members(validated.task_body, expected_count=CONTINUATION_COUNT))
    retained = tuple(member for member in canonical if member in set(partition.sandoq) and member not in selected)
    selected_order = tuple(member for member in canonical if member in selected)
    if (
        len(canonical) != CANONICAL_SOURCE_COUNT
        or len(retained) != RETAINED_COUNT
        or len(selected_order) != CONTINUATION_COUNT
        or set(retained) & selected
        or set(retained) | selected != set(partition.sandoq)
    ):
        raise PassOnlyError("canonical_partition_invalid")
    return _artifact(canonical_body), canonical, retained, selected, selected_order


def _positive_records_in_canonical_order(
    canonical_order: tuple[str, ...],
    retained: PassOnlyAudit,
    continuation: PassOnlyAudit,
) -> tuple[TraceIndex, ...]:
    retained_members = set(retained.rows)
    continuation_members = set(continuation.rows)
    if (
        retained_members & continuation_members
        or len(retained_members) != RETAINED_COUNT
        or len(continuation_members) != CONTINUATION_COUNT
        or len(retained_members | continuation_members) != CANONICAL_SANDOQ_COUNT
        or not (retained_members | continuation_members).issubset(canonical_order)
    ):
        raise PassOnlyError("merged_coverage_invalid")
    ordered: list[TraceIndex] = []
    for member in canonical_order:
        record = retained.rows.get(member) or continuation.rows.get(member)
        if record is not None and record.outcome == "positive":
            ordered.append(record)
    records = tuple(ordered)
    if len(records) != retained.positive_traces + continuation.positive_traces:
        raise PassOnlyError("merged_positive_partition_invalid")
    return records


def _source_config_context(root: launch.PrivateDirectory) -> tuple[bytes, bytes, sft.TaskIdentityContext]:
    task_body = root.read("inputs/task_file.txt", "source_run_invalid")
    config_body = root.read("inputs/source_config.toml", "source_run_invalid")
    return task_body, config_body, _task_context(config_body, task_body, CANONICAL_SOURCE_COUNT)


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _directory_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_uid, stat.S_IMODE(metadata.st_mode)


def _validate_parent_identity(parent: Path, descriptor: int, expected: tuple[int, int, int, int]) -> None:
    try:
        held = os.fstat(descriptor)
        visible = parent.lstat()
    except OSError as error:
        raise PassOnlyError("output_parent_changed") from error
    if (
        _directory_identity(held) != expected
        or _directory_identity(visible) != expected
        or not stat.S_ISDIR(held.st_mode)
        or not stat.S_ISDIR(visible.st_mode)
        or parent.resolve(strict=True) != parent
    ):
        raise PassOnlyError("output_parent_changed")


def _open_output_parent(parent: Path) -> tuple[int, tuple[int, int, int, int]]:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(parent, flags)
    try:
        metadata = os.fstat(descriptor)
        identity = _directory_identity(metadata)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise PassOnlyError("output_parent_invalid")
        _validate_parent_identity(parent, descriptor, identity)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, identity


def _entry_exists(parent_descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _remove_tree_at(
    parent_descriptor: int,
    name: str,
    expected_identity: tuple[int, int, int, int] | None = None,
) -> None:
    if not _entry_exists(parent_descriptor, name):
        return
    anchored = Path(f"/proc/self/fd/{parent_descriptor}") / name
    metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    if expected_identity is not None and _directory_identity(metadata) != expected_identity:
        raise PassOnlyError("export_rollback_ownership_lost")
    if stat.S_ISDIR(metadata.st_mode):
        shutil.rmtree(anchored)
    else:
        os.unlink(name, dir_fd=parent_descriptor)
    if _entry_exists(parent_descriptor, name):
        raise PassOnlyError("export_rollback_failed")


def _make_stage(parent_descriptor: int, output_name: str) -> tuple[str, Path, tuple[int, int, int, int]]:
    for _attempt in range(100):
        name = f".{output_name}.stage-{secrets.token_hex(8)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            continue
        metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        return name, Path(f"/proc/self/fd/{parent_descriptor}") / name, _directory_identity(metadata)
    raise PassOnlyError("staging_directory_failed")


def _rename_noreplace(source: str, destination: str, parent_descriptor: int) -> None:
    renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if renameat2 is None:
        raise PassOnlyError("rename_noreplace_unavailable")
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    if (
        renameat2(
            parent_descriptor,
            os.fsencode(source),
            parent_descriptor,
            os.fsencode(destination),
            1,
        )
        != 0
    ):
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise PassOnlyError("output_already_exists")
        raise PassOnlyError("atomic_publish_failed") from OSError(error_number, os.strerror(error_number))


def _tree_sha256_at(
    parent_descriptor: int,
    root_name: str,
    root_identity: tuple[int, int, int, int],
) -> str:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    root_descriptor = os.open(root_name, flags, dir_fd=parent_descriptor)
    records: list[tuple[str, str, int, int, str]] = []

    def walk(descriptor: int, prefix: str) -> None:
        with os.scandir(descriptor) as iterator:
            names = sorted(entry.name for entry in iterator)
        for name in names:
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            relative = f"{prefix}/{name}" if prefix else name
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(name, flags, dir_fd=descriptor)
                try:
                    if _directory_identity(os.fstat(child)) != _directory_identity(metadata):
                        raise PassOnlyError("export_tree_changed")
                    records.append(("directory", relative, mode, 0, ""))
                    walk(child, relative)
                finally:
                    os.close(child)
            elif stat.S_ISREG(metadata.st_mode):
                file_flags = os.O_RDONLY | os.O_CLOEXEC
                if hasattr(os, "O_NOFOLLOW"):
                    file_flags |= os.O_NOFOLLOW
                file_descriptor = os.open(name, file_flags, dir_fd=descriptor)
                digest = hashlib.sha256()
                size = 0
                try:
                    before = os.fstat(file_descriptor)
                    with os.fdopen(os.dup(file_descriptor), "rb") as handle:
                        while chunk := handle.read(1 << 20):
                            digest.update(chunk)
                            size += len(chunk)
                    after = os.fstat(file_descriptor)
                finally:
                    os.close(file_descriptor)
                if launch._file_identity(before) != launch._file_identity(after):
                    raise PassOnlyError("export_tree_changed")
                records.append(("file", relative, mode, size, digest.hexdigest()))
            else:
                raise PassOnlyError("export_tree_invalid")

    try:
        metadata = os.fstat(root_descriptor)
        if _directory_identity(metadata) != root_identity:
            raise PassOnlyError("staging_directory_changed")
        records.append(("directory", ".", stat.S_IMODE(metadata.st_mode), 0, ""))
        walk(root_descriptor, "")
        if _directory_identity(os.fstat(root_descriptor)) != root_identity:
            raise PassOnlyError("staging_directory_changed")
    finally:
        os.close(root_descriptor)
    body = json.dumps(records, ensure_ascii=True, separators=(",", ":"), sort_keys=False).encode() + b"\n"
    return _sha256(body)


def _publish_directory(
    stage_name: str,
    output_name: str,
    parent: Path,
    parent_descriptor: int,
    parent_identity: tuple[int, int, int, int],
    stage_identity: tuple[int, int, int, int],
    expected_tree_sha256: str,
) -> None:
    _validate_parent_identity(parent, parent_descriptor, parent_identity)
    if _entry_exists(parent_descriptor, output_name):
        raise PassOnlyError("output_already_exists")
    stage_metadata = os.stat(stage_name, dir_fd=parent_descriptor, follow_symlinks=False)
    if _directory_identity(stage_metadata) != stage_identity or not stat.S_ISDIR(stage_metadata.st_mode):
        raise PassOnlyError("staging_directory_changed")
    if _tree_sha256_at(parent_descriptor, stage_name, stage_identity) != expected_tree_sha256:
        raise PassOnlyError("export_tree_changed")
    _validate_parent_identity(parent, parent_descriptor, parent_identity)
    if _directory_identity(os.stat(stage_name, dir_fd=parent_descriptor, follow_symlinks=False)) != stage_identity:
        raise PassOnlyError("staging_directory_changed")
    _rename_noreplace(stage_name, output_name, parent_descriptor)
    try:
        if _directory_identity(os.stat(output_name, dir_fd=parent_descriptor, follow_symlinks=False)) != stage_identity:
            raise PassOnlyError("published_output_identity_invalid")
        if _tree_sha256_at(parent_descriptor, output_name, stage_identity) != expected_tree_sha256:
            raise PassOnlyError("export_tree_changed")
        os.fsync(parent_descriptor)
        _validate_parent_identity(parent, parent_descriptor, parent_identity)
    except BaseException:
        _remove_tree_at(parent_descriptor, output_name, stage_identity)
        try:
            os.fsync(parent_descriptor)
        except OSError:
            pass
        raise


def _verify_private_bundle(root: Path, artifacts: Mapping[str, Artifact], manifest: Artifact) -> None:
    root_metadata = root.lstat()
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_IMODE(root_metadata.st_mode) != 0o700
        or root_metadata.st_uid != os.getuid()
    ):
        raise PassOnlyError("bundle_privacy_invalid")
    expected_files = {MANIFEST_FILENAME: manifest, **artifacts}
    expected_directories = {".", "train", "validation"}
    observed_files: set[str] = set()
    observed_directories = {"."}
    pending = [root]
    while pending:
        directory = pending.pop()
        for entry in os.scandir(directory):
            relative = Path(entry.path).relative_to(root).as_posix()
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                if stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != os.getuid():
                    raise PassOnlyError("bundle_privacy_invalid")
                observed_directories.add(relative)
                pending.append(Path(entry.path))
            elif stat.S_ISREG(metadata.st_mode):
                if stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_uid != os.getuid() or metadata.st_nlink != 1:
                    raise PassOnlyError("bundle_privacy_invalid")
                try:
                    observed = legacy_merge._fingerprint_regular(Path(entry.path), "bundle_artifact_invalid")
                except legacy_merge.MergeError as error:
                    raise PassOnlyError("bundle_artifact_invalid") from error
                expected = expected_files.get(relative)
                if expected is None or (observed.bytes, observed.sha256) != (expected.bytes, expected.sha256):
                    raise PassOnlyError("bundle_artifact_invalid")
                observed_files.add(relative)
            else:
                raise PassOnlyError("bundle_privacy_invalid")
    if observed_directories != expected_directories or observed_files != set(expected_files):
        raise PassOnlyError("bundle_artifact_invalid")


def _output_path(path: Path, protected: tuple[Path, ...]) -> tuple[Path, Path]:
    try:
        parent, output = legacy_merge._resolve_output(path)
    except legacy_merge.MergeError as error:
        raise PassOnlyError("output_path_invalid") from error
    try:
        parent_metadata = parent.lstat()
    except OSError as error:
        raise PassOnlyError("output_parent_invalid") from error
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.getuid()
        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        or os.path.lexists(output)
        or any(output == item or output.is_relative_to(item) or item.is_relative_to(output) for item in protected)
    ):
        raise PassOnlyError("output_path_invalid")
    return parent, output


def _assert_output_separated(output: Path, validated: launch.ValidatedPlan, run: Path) -> None:
    inputs = validated.value["inputs"]
    protected = {
        _repository().resolve(strict=True),
        run.resolve(strict=True),
        Path(validated.value["private_root"]["path"]).resolve(strict=True),
        Path(inputs["epoch3_source_run"]).resolve(strict=True),
        validated.dataset.resolve(strict=True),
    }
    for name in (
        "canonical_source",
        "canonical_template",
        "canonical_image_manifest",
        "selection_manifest",
        "provider_receipt",
        "provider_task_file",
    ):
        record = inputs[name]
        path = Path(record["path"] if isinstance(record, Mapping) else record).resolve(strict=True)
        protected.add(path.parent if path.is_file() else path)
    if any(output == item or output.is_relative_to(item) or item.is_relative_to(output) for item in protected):
        raise PassOnlyError("output_path_invalid")


def _sealed_plan_protected_paths(plan: Path, plan_sha256: str, run: Path) -> tuple[Path, ...]:
    with launch.PrivateDirectory.open(plan.parent, "historical_plan_invalid") as root:
        body = root.read(plan.name, "historical_plan_invalid")
    if _sha256(body) != plan_sha256 or plan_sha256 != FROZEN_PLAN_SHA256:
        raise PassOnlyError("historical_plan_invalid")
    value = _parse_object(body, "historical_plan_invalid", canonical=True)
    inputs = value.get("inputs")
    if value.get("code") != FROZEN_LAUNCH_CODE or not isinstance(inputs, Mapping):
        raise PassOnlyError("historical_plan_invalid")
    protected = {
        _repository().resolve(strict=True),
        plan.parent.resolve(strict=True),
        run.resolve(strict=True),
        Path(value["private_root"]["path"]).resolve(strict=True),
        Path(inputs["epoch3_source_run"]).resolve(strict=True),
        Path(inputs["canonical_dataset"]["path"]).resolve(strict=True),
    }
    for name in (
        "canonical_source",
        "canonical_template",
        "canonical_image_manifest",
        "selection_manifest",
        "provider_receipt",
        "provider_task_file",
    ):
        record = inputs[name]
        path = Path(record["path"] if isinstance(record, Mapping) else record).resolve(strict=True)
        protected.add(path.parent)
    return tuple(protected)


def _bundle_manifest(
    *,
    certificate: Mapping[str, Any],
    certificate_artifact: Artifact,
    code: Mapping[str, Any],
    retained_audit: PassOnlyAudit,
    continuation_audit: PassOnlyAudit,
    artifacts: Mapping[str, Artifact],
    train_tasks: set[str],
    validation_tasks: set[str],
    emitted_rows: int,
    train_rows: int,
    validation_rows: int,
    source_lineage: Mapping[str, Any],
) -> dict[str, Any]:
    selected_tasks = retained_audit.positive_traces + continuation_audit.positive_traces
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": EXPORT_KIND,
        "selection": "pass-only",
        "all_outcomes_trainability_claimed": False,
        "artifacts": {name: artifact.value() for name, artifact in sorted(artifacts.items())},
        "certificate": {
            "artifact": certificate_artifact.value(),
            "kind": certificate["kind"],
            "plan_sha256": certificate["plan_sha256"],
        },
        "code": code,
        "counts": {
            "canonical_coverage_tasks": CANONICAL_SANDOQ_COUNT,
            "continuation_coverage_tasks": CONTINUATION_COUNT,
            "continuation_error_traces_nonexported": continuation_audit.error_traces,
            "continuation_positive_traces": continuation_audit.positive_traces,
            "continuation_zero_reward_traces_nonexported": continuation_audit.zero_reward_traces,
            "emitted_rows": emitted_rows,
            "retained_coverage_tasks": RETAINED_COUNT,
            "retained_positive_traces": retained_audit.positive_traces,
            "retained_zero_reward_traces_nonexported": retained_audit.zero_reward_traces,
            "selected_sft_tasks": selected_tasks,
            "train_rows": train_rows,
            "train_traces": len(train_tasks),
            "validation_rows": validation_rows,
            "validation_traces": len(validation_tasks),
        },
        "coverage": {
            "canonical_order_preserved_within_split": True,
            "continuation": continuation_audit.public_value(),
            "disjoint": True,
            "exhaustive": True,
            "retained": retained_audit.public_value(),
        },
        "format": legacy_merge.FORMAT_CONTRACT,
        "format_version": sft.FORMAT_VERSION,
        "exporter": {
            "file_sha256": code["files"]["qwen_source_continuation_pass_only.py"],
            "format_version": sft.FORMAT_VERSION,
        },
        "source_indexing": {
            "order": "canonical-task-order",
            "source_trace_index": "canonical task index across the 2,500-task source",
        },
        "max_sequence_tokens": audit_traces.DEFAULT_MAX_SEQUENCE_TOKENS,
        "positive_trace_contracts": {
            "continuation": {
                "id": audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT_ID,
                "sha256": audit_traces.model_io_contract_sha256(
                    audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT
                ),
            },
            "retained": {
                "id": audit_traces.QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT_ID,
                "sha256": audit_traces.model_io_contract_sha256(audit_traces.QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT),
            },
        },
        "source_lineage": source_lineage,
        "source_validation": {
            "max_sequence_tokens": audit_traces.DEFAULT_MAX_SEQUENCE_TOKENS,
            "model_io_contract": COMBINED_MODEL_IO_CONTRACT_ID,
            "require_exact_provider_json": False,
            "require_model_io": True,
            "require_reasoning": True,
            "require_request_graph_match": True,
        },
        "split": {
            "policy": SPLIT_POLICY,
            "split_salt": sft.DEFAULT_SPLIT_SALT,
            "validation_permyriad": sft.DEFAULT_VALIDATION_PERMYRIAD,
        },
        "target_rendering": sft.TARGET_RENDERING_CONTRACT,
    }


def export_merge(
    *,
    plan: Path,
    plan_sha256: str,
    run: Path,
    certificate_sha256: str,
    output_dir: Path,
) -> dict[str, Any]:
    plan, run, _certificate_output = _certificate_paths(plan, run, run / CERTIFICATE_FILENAME)
    parent, output = _output_path(output_dir, _sealed_plan_protected_paths(plan, plan_sha256, run))
    parent_descriptor, parent_identity = _open_output_parent(parent)
    stage_name: str | None = None
    stage_identity: tuple[int, int, int, int] | None = None
    stage: Path | None = None
    train_sink: _RowSink | None = None
    validation_sink: _RowSink | None = None
    lock_flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        lock_flags |= os.O_NOFOLLOW
    try:
        lock_fd = os.open(
            ".qwen-source-continuation-pass-only-export.lock",
            lock_flags,
            0o600,
            dir_fd=parent_descriptor,
        )
    except BaseException:
        os.close(parent_descriptor)
        raise
    try:
        lock_metadata = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(lock_metadata.st_mode)
            or lock_metadata.st_uid != os.getuid()
            or stat.S_IMODE(lock_metadata.st_mode) != 0o600
            or lock_metadata.st_nlink != 1
        ):
            raise PassOnlyError("output_lock_invalid")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _validate_parent_identity(parent, parent_descriptor, parent_identity)
        if _entry_exists(parent_descriptor, output.name):
            raise PassOnlyError("output_already_exists")
        with launch.PrivateDirectory.open(plan.parent, "historical_plan_invalid") as plan_root:
            initial = _validate_historical_plan(plan=plan, plan_sha256=plan_sha256, plan_root=plan_root)
            source_path = Path(initial.value["inputs"]["epoch3_source_run"])
            with launch._hold_source_run(source_path) as source_root:
                validated = _validate_historical_plan(
                    plan=plan,
                    plan_sha256=plan_sha256,
                    plan_root=plan_root,
                    source_root=source_root,
                )
                with launch.PrivateDirectory.open(run, "run_directory_invalid") as run_root, ExitStack() as locks:
                    run_root.lock(".writer.lock", locks, "run_lock_invalid")
                    _assert_output_separated(output, validated, run)
                    before = launch._run_evidence_snapshots(run_root)
                    code = _postprocessor_code_binding()
                    certificate, certificate_body = _load_bound_certificate(
                        run_root,
                        expected_sha256=certificate_sha256,
                        expected_code=code,
                    )
                    envelope, shared, execution = launch._validate_run_identity(
                        run=run,
                        root=run_root,
                        validated=validated,
                        expected_snapshots=before,
                    )
                    launch._validate_execution(execution)
                    partition_snapshot = _canonical_partition(validated)
                    canonical_artifact, canonical_order, retained_order, selected, selected_order = partition_snapshot
                    _source_task_body, _source_config_body, source_context = _source_config_context(source_root)
                    continuation_context = _task_context(
                        validated.config_body,
                        validated.task_body,
                        CONTINUATION_COUNT,
                    )
                    if (
                        source_context.taskset_id != continuation_context.taskset_id
                        or source_context.dataset_revision != continuation_context.dataset_revision
                    ):
                        raise PassOnlyError("task_namespace_mismatch")
                    with source_root.open_binary("results.jsonl", "source_results_invalid") as source_results:
                        retained_audit = _audit_results(
                            source_results,
                            task_context=source_context,
                            expected_members=frozenset(retained_order),
                            expected_input_traces=launch.SOURCE_PARTITION["seen_traces"],
                            model_io_contract=audit_traces.QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT,
                        )
                    with run_root.open_binary("results.jsonl", "continuation_results_invalid") as continuation_results:
                        continuation_audit = _audit_results(
                            continuation_results,
                            task_context=continuation_context,
                            expected_members=selected,
                            expected_input_traces=CONTINUATION_COUNT,
                            model_io_contract=audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
                        )
                    with run_root.open_binary(
                        "sandoq_cleanup_audit.json",
                        "continuation_evidence_invalid",
                    ) as cleanup_handle:
                        cleanup, cleanup_hashes = launch.validate_cleanup(
                            Path(f"/proc/self/fd/{cleanup_handle.fileno()}"),
                            expected_task_count=CONTINUATION_COUNT,
                            expected_concurrency=launch.EXECUTION_CONTRACT["rollout_concurrency"],
                        )
                    provider_source = launch._provider_source(envelope["identity"])
                    expected_certificate = _continuation_certificate_value(
                        validated=validated,
                        envelope=envelope,
                        shared=shared,
                        provider_source=provider_source,
                        audit=continuation_audit,
                        cleanup=cleanup,
                        cleanup_hashes=cleanup_hashes,
                        code=code,
                    )
                    if (
                        retained_audit.covered_tasks != RETAINED_COUNT
                        or retained_audit.positive_traces != RETAINED_POSITIVE_COUNT
                        or retained_audit.zero_reward_traces != RETAINED_ZERO_REWARD_COUNT
                        or retained_audit.error_traces != 0
                        or continuation_audit.positive_traces < 1
                        or continuation_audit.results.sha256 != before["results.jsonl"].sha256
                        or cleanup.get("audit_sha256") != before["sandoq_cleanup_audit.json"].sha256
                    ):
                        raise PassOnlyError("export_coverage_mismatch")
                    _require_exact_certificate(certificate_body, expected_certificate)
                    stage_name, stage, stage_identity = _make_stage(parent_descriptor, output.name)
                    train_sink = _RowSink(stage / "train" / "train.jsonl")
                    validation_sink = _RowSink(stage / "validation" / "train.jsonl")
                    sinks = {"train": train_sink, "validation": validation_sink}
                    split_rows = {"train": 0, "validation": 0}
                    split_tasks: dict[str, set[str]] = {"train": set(), "validation": set()}
                    emitted_rows = 0
                    with (
                        source_root.open_binary("results.jsonl", "source_results_invalid") as source_results,
                        run_root.open_binary("results.jsonl", "continuation_results_invalid") as continuation_results,
                    ):
                        if tuple(member for member in canonical_order if member in selected) != selected_order:
                            raise PassOnlyError("canonical_order_invalid")
                        canonical_indices = {member: index for index, member in enumerate(canonical_order)}
                        for record in _positive_records_in_canonical_order(
                            canonical_order,
                            retained_audit,
                            continuation_audit,
                        ):
                            handle: BinaryIO
                            contract: audit_traces.CapturedModelIOContract
                            if record.slug in retained_audit.rows:
                                handle = source_results
                                contract = audit_traces.QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT
                            elif record.slug in continuation_audit.rows:
                                handle = continuation_results
                                contract = audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT
                            else:
                                raise PassOnlyError("merged_positive_partition_invalid")
                            split = sft._split_for_task(
                                record.task_id,
                                salt=sft.DEFAULT_SPLIT_SALT,
                                validation_permyriad=sft.DEFAULT_VALIDATION_PERMYRIAD,
                            )
                            trace, _raw = _read_indexed_trace(handle, record)
                            emitted = _emit_positive_trace(
                                trace=trace,
                                record=record,
                                merged_source_index=canonical_indices[record.slug],
                                split=split,
                                split_row_index=split_rows[split],
                                model_io_contract=contract,
                                sink=sinks[split],
                            )
                            split_rows[split] += 1
                            split_tasks[split].add(record.task_id)
                            emitted_rows += emitted
                    if split_tasks["train"] & split_tasks["validation"]:
                        raise PassOnlyError("task_split_overlap")
                    train_row_count = train_sink.rows
                    validation_row_count = validation_sink.rows
                    train_artifact = train_sink.close()
                    train_sink = None
                    validation_artifact = validation_sink.close()
                    validation_sink = None
                    certificate_artifact = _write_file(stage / CERTIFICATE_COPY_FILENAME, certificate_body)
                    target_body = sft._load_target_rendering_contract().body
                    target_artifact = _write_file(stage / sft.TARGET_RENDERING_CONTRACT_FILENAME, target_body)
                    task_split = {
                        "format_version": sft.FORMAT_VERSION,
                        "split_salt": sft.DEFAULT_SPLIT_SALT,
                        "train_task_sha256": sorted(split_tasks["train"]),
                        "validation_permyriad": sft.DEFAULT_VALIDATION_PERMYRIAD,
                        "validation_task_sha256": sorted(split_tasks["validation"]),
                    }
                    task_split_body = _json_bytes(task_split, pretty=True)
                    task_split_artifact = _write_file(stage / "task-split.json", task_split_body)
                    artifacts = {
                        sft.TARGET_RENDERING_CONTRACT_FILENAME: target_artifact,
                        "task-split.json": task_split_artifact,
                        "train/train.jsonl": train_artifact,
                        "validation/train.jsonl": validation_artifact,
                    }
                    manifest = _bundle_manifest(
                        certificate=certificate,
                        certificate_artifact=certificate_artifact,
                        code=code,
                        retained_audit=retained_audit,
                        continuation_audit=continuation_audit,
                        artifacts=artifacts,
                        train_tasks=split_tasks["train"],
                        validation_tasks=split_tasks["validation"],
                        emitted_rows=emitted_rows,
                        train_rows=train_row_count,
                        validation_rows=validation_row_count,
                        source_lineage={
                            "epoch3_source": validated.value["materialization"]["lineage"]["epoch3_source"],
                            "selection": validated.value["materialization"]["lineage"]["selection"],
                        },
                    )
                    manifest_body = _json_bytes(manifest, pretty=True)
                    manifest_artifact = _write_file(stage / MANIFEST_FILENAME, manifest_body)
                    if (
                        manifest["counts"]["selected_sft_tasks"]
                        != RETAINED_POSITIVE_COUNT + continuation_audit.positive_traces
                        or manifest["counts"]["canonical_coverage_tasks"] != CANONICAL_SANDOQ_COUNT
                        or manifest["counts"]["selected_sft_tasks"] == CANONICAL_SANDOQ_COUNT
                    ):
                        raise PassOnlyError("merged_manifest_invalid")
                    for directory in (stage / "train", stage / "validation", stage):
                        _fsync_dir(directory)
                    _verify_private_bundle(
                        stage,
                        {CERTIFICATE_COPY_FILENAME: certificate_artifact, **artifacts},
                        manifest_artifact,
                    )
                    if stage_name is None or stage_identity is None:
                        raise PassOnlyError("staging_directory_changed")
                    expected_tree_sha256 = _tree_sha256_at(parent_descriptor, stage_name, stage_identity)
                    if (
                        launch._validate_source_run(source_path, held_root=source_root)
                        != validated.value["materialization"]["lineage"]["epoch3_source"]
                    ):
                        raise PassOnlyError("source_changed_during_export")
                    after = launch._run_evidence_snapshots(run_root)
                    revalidated = _validate_historical_plan(
                        plan=plan,
                        plan_sha256=plan_sha256,
                        plan_root=plan_root,
                        source_root=source_root,
                    )
                    if (
                        after != before
                        or revalidated.value != validated.value
                        or _canonical_partition(revalidated) != partition_snapshot
                    ):
                        raise PassOnlyError("source_changed_during_export")
                    result = {
                        "canonical_coverage_tasks": CANONICAL_SANDOQ_COUNT,
                        "continuation_positive_export_tasks": continuation_audit.positive_traces,
                        "retained_positive_export_tasks": RETAINED_POSITIVE_COUNT,
                        "selected_sft_tasks": RETAINED_POSITIVE_COUNT + continuation_audit.positive_traces,
                        "state": "exported",
                    }
                    if not manifest_artifact.sha256:
                        raise PassOnlyError("export_publication_invalid")
                    if not canonical_artifact.sha256 or stage_name is None or stage_identity is None:
                        raise PassOnlyError("canonical_partition_invalid")
                    _publish_directory(
                        stage_name,
                        output.name,
                        parent,
                        parent_descriptor,
                        parent_identity,
                        stage_identity,
                        expected_tree_sha256,
                    )
                    stage_name = None
                    stage_identity = None
                    stage = None
                    return result
    except (launch.SourceContinuationError, legacy_merge.MergeError, sft.ExportError, OSError) as error:
        raise PassOnlyError("export_failed") from error
    finally:
        try:
            if train_sink is not None:
                train_sink.abort()
            if validation_sink is not None:
                validation_sink.abort()
            if stage_name is not None:
                _remove_tree_at(parent_descriptor, stage_name, stage_identity)
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
                os.close(parent_descriptor)


def _parser() -> StableArgumentParser:
    parser = StableArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    certifier = commands.add_parser("certify")
    certifier.add_argument("--plan", type=Path, required=True)
    certifier.add_argument("--plan-sha256", required=True)
    certifier.add_argument("--run", type=Path, required=True)
    certifier.add_argument("--output", type=Path, required=True)
    exporter = commands.add_parser("export-merge")
    exporter.add_argument("--plan", type=Path, required=True)
    exporter.add_argument("--plan-sha256", required=True)
    exporter.add_argument("--run", type=Path, required=True)
    exporter.add_argument("--certificate-sha256", required=True)
    exporter.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> None:
    args = vars(_parser().parse_args())
    command = args.pop("command")
    try:
        result = certify(**args) if command == "certify" else export_merge(**args)
    except PassOnlyError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit("pass_only_operation_failed") from None
    print(json.dumps(result, allow_nan=False, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
