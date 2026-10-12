#!/usr/bin/env python3
"""Package stock-small Kimi trajectories and derive a pass-only SFT export.

The unfiltered trajectory corpus is the authoritative artifact.  It preserves
one Verifiers trajectory per JSONL row, including rewards and errors.  The SFT
dataset is a separate pass-only derivative.  Commands emit aggregate metadata
and stable error codes only; task identities and trace payloads are never
printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import export_sft
import kimi_stock_small_shards as stock

SCHEMA_VERSION = 1
CORPUS_KIND = "kimi-k3-stock-small-unfiltered-trajectory-corpus"
EXPORT_KIND = "kimi-k3-stock-small-pass-only-sft"
SHA256_RE = stock.SHA256_RE
MAX_CERTIFICATE_BYTES = 16 * 1024 * 1024
MAX_CONFIG_BYTES = 4 * 1024 * 1024
MAX_TASK_FILE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_MANIFEST_BYTES = 128 * 1024 * 1024
MAX_INPUT_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_PROVENANCE_BYTES = 1024 * 1024


class StockSmallSFTError(RuntimeError):
    """A fail-closed postprocessing error represented by a stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FinalEvidence:
    certificate: Mapping[str, Any]
    certificate_artifact: Mapping[str, Any]
    plan: Mapping[str, Any]
    plan_path: Path
    plan_sha256: str
    completions: tuple[Mapping[str, Any], ...]
    result_artifacts: tuple[Mapping[str, Any], ...]
    outcome_counts: Mapping[str, int]
    capture_counts: Mapping[str, int]


def _canonical(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as error:
        raise StockSmallSFTError("json_invalid") from error


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _plain_int(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _private_directory(path: Path, code: str) -> Path:
    try:
        canonical = path.resolve(strict=True)
        metadata = path.lstat()
    except OSError as error:
        raise StockSmallSFTError(code) from error
    if (
        not path.is_absolute()
        or Path(os.path.normpath(path)) != path
        or canonical != path
        or path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise StockSmallSFTError(code)
    return canonical


def _read_regular(
    path: Path,
    *,
    code: str,
    private: bool = True,
    maximum_bytes: int | None = None,
) -> tuple[bytes, dict[str, Any]]:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        canonical = path.resolve(strict=True)
        if not path.is_absolute() or Path(os.path.normpath(path)) != path or canonical != path:
            raise StockSmallSFTError(code)
        descriptor = os.open(path, flags)
    except OSError as error:
        raise StockSmallSFTError(code) from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or (private and stat.S_IMODE(before.st_mode) != 0o600)
            or (maximum_bytes is not None and before.st_size > maximum_bytes)
        ):
            raise StockSmallSFTError(code)
        body = bytearray()
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            digest.update(chunk)
            if maximum_bytes is not None and len(body) > maximum_bytes:
                raise StockSmallSFTError(code)
        after = os.fstat(descriptor)
        visible = path.lstat()
    finally:
        os.close(descriptor)
    identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if identity(before) != identity(after) or identity(after) != identity(visible):
        raise StockSmallSFTError(code)
    return bytes(body), {
        "path": str(canonical),
        "bytes": after.st_size,
        "sha256": digest.hexdigest(),
    }


def _strict_json(body: bytes, code: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise StockSmallSFTError(code) from error
    if not isinstance(value, dict) or _canonical(value) != body:
        raise StockSmallSFTError(code)
    return value


def _json_object(body: bytes, code: str) -> dict[str, Any]:
    """Decode an object while rejecting duplicate keys and non-finite values."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise StockSmallSFTError(code) from error
    if not isinstance(value, dict):
        raise StockSmallSFTError(code)
    return value


def _write_exclusive(path: Path, body: bytes) -> dict[str, Any]:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise StockSmallSFTError("output_publish_failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}


def _relative_artifact(path: Path, body: bytes, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(body),
        "sha256": _sha256(body),
    }


def _git(root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(root), *arguments],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=120,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise StockSmallSFTError("source_identity_invalid") from error
    try:
        return completed.stdout.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise StockSmallSFTError("source_identity_invalid") from error


def _source_binding(project_root: Path, expected_revision: str) -> dict[str, Any]:
    try:
        root = stock._validate_source(project_root, expected_revision)
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallSFTError("source_identity_invalid") from error
    workflow = root / "user/tianhaowu/terminal_bench_vmvm"
    files = {
        "postprocessor": workflow / Path(__file__).name,
        "stock_certifier": workflow / "kimi_stock_small_shards.py",
        "sft_exporter": workflow / "export_sft.py",
        "sft_preflight": root / "src/prime_rl/trainer/sft/export_preflight.py",
        "rendering_contract": workflow / "configs/sft/target-rendering-contract.json",
    }
    if Path(__file__).resolve(strict=True) != files["postprocessor"]:
        raise StockSmallSFTError("source_identity_invalid")
    records: dict[str, dict[str, Any]] = {}
    for name, path in files.items():
        body, artifact = _read_regular(path, code="source_identity_invalid", private=False)
        records[name] = {"path": artifact["path"], "bytes": len(body), "sha256": artifact["sha256"]}
    submodules = {name: _git(root / name, "rev-parse", "HEAD") for name in ("deps/renderers", "deps/verifiers")}
    if any(stock.REVISION_RE.fullmatch(revision) is None for revision in submodules.values()):
        raise StockSmallSFTError("source_identity_invalid")
    return {
        "project_root": str(root),
        "prime_rl_revision": expected_revision,
        "prime_rl_tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "submodules": submodules,
        "files": records,
    }


def _certificate_plan_record(value: Mapping[str, Any]) -> tuple[Path, str]:
    record = value.get("plan")
    if (
        not isinstance(record, dict)
        or set(record) != {"path", "sha256"}
        or not isinstance(record.get("path"), str)
        or not Path(record["path"]).is_absolute()
        or SHA256_RE.fullmatch(str(record.get("sha256", ""))) is None
    ):
        raise StockSmallSFTError("trace_certificate_invalid")
    return Path(record["path"]), str(record["sha256"])


def validate_final_certificate(path: Path, expected_sha256: str) -> FinalEvidence:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise StockSmallSFTError("trace_certificate_invalid")
    body, artifact = _read_regular(
        path,
        code="trace_certificate_invalid",
        maximum_bytes=MAX_CERTIFICATE_BYTES,
    )
    value = _strict_json(body, "trace_certificate_invalid")
    unsigned = dict(value)
    claimed = unsigned.pop("certificate_sha256", None)
    if artifact["sha256"] != expected_sha256 or claimed != _sha256(_canonical(unsigned)):
        raise StockSmallSFTError("trace_certificate_invalid")
    plan_path, plan_sha256 = _certificate_plan_record(value)

    # Re-run the authoritative finalizer into an ephemeral namespace.  Its
    # output is deterministic and reopens every shard, trace, transport record,
    # cleanup receipt, and launch binding.  Comparing bytes avoids a second,
    # weaker certificate parser here.
    try:
        with tempfile.TemporaryDirectory(prefix="kimi-stock-small-cert-") as temporary:
            expected_output = Path(temporary) / "certificate"
            stock.finalize(plan_path, plan_sha256, expected_output)
            expected_body = (expected_output / "certificate.json").read_bytes()
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallSFTError("trace_certificate_invalid") from error
    if body != expected_body:
        raise StockSmallSFTError("trace_certificate_invalid")

    try:
        plan = stock.verify(plan_path, plan_sha256)
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallSFTError("trace_certificate_invalid") from error
    completion_records = value.get("completion_receipts")
    if not isinstance(completion_records, list) or len(completion_records) != stock.SHARD_COUNT:
        raise StockSmallSFTError("trace_certificate_invalid")
    completions: list[Mapping[str, Any]] = []
    results: list[Mapping[str, Any]] = []
    outcome_counts: dict[str, int] = {
        name: 0
        for name in (
            "positive_traces",
            "zero_reward_traces",
            "error_traces",
            "zero_model_error_traces",
            "model_bearing_error_traces",
            "model_bearing_harness_error_traces",
            "model_bearing_provider_error_traces",
            "model_bearing_shared_verifier_transport_error_traces",
        )
    }
    capture_counts = {
        name: 0
        for name in (
            "clean_model_io_turns",
            "clean_sampled_tokens",
            "audited_model_io_turns",
            "audited_sampled_tokens",
        )
    }
    for index, record in enumerate(completion_records):
        shard = plan["shards"][index]
        completion_path = Path(str(shard["run_root"])) / "complete.json"
        completion_body, completion_artifact = _read_regular(
            completion_path,
            code="trace_certificate_invalid",
            maximum_bytes=MAX_CERTIFICATE_BYTES,
        )
        if record != completion_artifact:
            raise StockSmallSFTError("trace_certificate_invalid")
        completion = _strict_json(completion_body, "trace_certificate_invalid")
        trace = completion.get("trace")
        artifacts = completion.get("artifacts")
        result = artifacts.get("results") if isinstance(artifacts, dict) else None
        if not isinstance(trace, dict) or not isinstance(result, dict) or set(result) != {"path", "bytes", "sha256"}:
            raise StockSmallSFTError("trace_certificate_invalid")
        if trace.get("traces") != shard.get("count"):
            raise StockSmallSFTError("trace_certificate_invalid")
        for name in outcome_counts:
            item = trace.get(name)
            if not _plain_int(item):
                raise StockSmallSFTError("trace_certificate_invalid")
            outcome_counts[name] += item
        for name in capture_counts:
            item = trace.get(name)
            if not _plain_int(item):
                raise StockSmallSFTError("trace_certificate_invalid")
            capture_counts[name] += item
        completions.append(completion)
        results.append(result)
    if (
        sum(outcome_counts[name] for name in ("positive_traces", "zero_reward_traces", "error_traces"))
        != stock.TOTAL_TASKS
        or outcome_counts["zero_model_error_traces"] != 0
        or outcome_counts["error_traces"] != outcome_counts["model_bearing_error_traces"]
        or value.get("outcomes") != outcome_counts
        or value.get("training")
        != {
            "trainable_traces": outcome_counts["positive_traces"] + outcome_counts["zero_reward_traces"],
            "non_trainable_traces": outcome_counts["model_bearing_error_traces"],
            "model_bearing_errors_retained": True,
            "shared_verifier_terminal_transport_traces": outcome_counts[
                "model_bearing_shared_verifier_transport_error_traces"
            ],
        }
        or value.get("capture")
        != {
            "response_kind": "exact_provider_json",
            "reasoning_required": True,
            "reasoning_message_parity_required": True,
            "request_graph_match_required": True,
        }
    ):
        raise StockSmallSFTError("trace_certificate_invalid")
    return FinalEvidence(
        certificate=value,
        certificate_artifact=artifact,
        plan=plan,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        completions=tuple(completions),
        result_artifacts=tuple(results),
        outcome_counts=outcome_counts,
        capture_counts=capture_counts,
    )


def _concatenate_results(
    result_artifacts: Sequence[Mapping[str, Any]],
    destination: Path | None,
) -> tuple[dict[str, Any], int]:
    output = None
    output_descriptor = -1
    if destination is not None:
        try:
            output_descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            output = os.fdopen(output_descriptor, "wb")
            output_descriptor = -1
        except OSError as error:
            if output_descriptor >= 0:
                os.close(output_descriptor)
            raise StockSmallSFTError("corpus_publish_failed") from error
    digest = hashlib.sha256()
    size = 0
    lines = 0
    try:
        for expected in result_artifacts:
            source_path = Path(str(expected.get("path", "")))
            flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(source_path, flags)
            except OSError as error:
                raise StockSmallSFTError("source_results_invalid") from error
            source_digest = hashlib.sha256()
            source_size = 0
            source_lines = 0
            last_byte = b""
            try:
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != os.geteuid()
                    or before.st_nlink != 1
                    or stat.S_IMODE(before.st_mode) != 0o600
                ):
                    raise StockSmallSFTError("source_results_invalid")
                while chunk := os.read(descriptor, 1 << 20):
                    if output is not None:
                        output.write(chunk)
                    digest.update(chunk)
                    source_digest.update(chunk)
                    size += len(chunk)
                    source_size += len(chunk)
                    source_lines += chunk.count(b"\n")
                    last_byte = chunk[-1:]
                after = os.fstat(descriptor)
                visible = source_path.lstat()
            finally:
                os.close(descriptor)
            identity = lambda value: (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_uid,
                value.st_nlink,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )
            observed = {
                "path": str(source_path.resolve(strict=True)),
                "bytes": source_size,
                "sha256": source_digest.hexdigest(),
            }
            if (
                identity(before) != identity(after)
                or identity(after) != identity(visible)
                or observed != expected
                or (source_size and last_byte != b"\n")
            ):
                raise StockSmallSFTError("source_results_invalid")
            lines += source_lines
        if output is not None:
            output.flush()
            os.fsync(output.fileno())
    finally:
        if output is not None:
            output.close()
        if output_descriptor >= 0:
            os.close(output_descriptor)
    if lines != stock.TOTAL_TASKS:
        raise StockSmallSFTError("corpus_coverage_invalid")
    return {
        "path": destination.name if destination is not None else "results.jsonl",
        "bytes": size,
        "sha256": digest.hexdigest(),
    }, lines


def package_unfiltered(
    *,
    project_root: Path,
    expected_revision: str,
    trace_certificate: Path,
    trace_certificate_sha256: str,
    output_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    source = _source_binding(project_root, expected_revision)
    root = _private_directory(output_root, "output_root_invalid")
    if output_dir.parent != root or output_dir.name in {"", ".", ".."} or os.path.lexists(output_dir):
        raise StockSmallSFTError("output_namespace_invalid")
    evidence = validate_final_certificate(trace_certificate, trace_certificate_sha256)
    plan_source = evidence.plan.get("source")
    selection = evidence.plan.get("selection")
    if not isinstance(plan_source, dict) or not isinstance(selection, dict):
        raise StockSmallSFTError("trace_certificate_invalid")
    selector_record = selection.get("selector")
    image_record = plan_source.get("image_manifest")
    dataset_record = plan_source.get("dataset")
    if (
        not isinstance(selector_record, dict)
        or not isinstance(image_record, dict)
        or not isinstance(dataset_record, dict)
        or not isinstance(dataset_record.get("path"), str)
    ):
        raise StockSmallSFTError("trace_certificate_invalid")
    selector_body, selector_artifact = _read_regular(
        Path(str(selector_record.get("path", ""))),
        code="selector_invalid",
    )
    image_body, image_artifact = _read_regular(
        Path(str(image_record.get("path", ""))),
        code="image_manifest_invalid",
        maximum_bytes=128 * 1024 * 1024,
    )
    if selector_artifact != selector_record or image_artifact != image_record:
        raise StockSmallSFTError("trace_certificate_invalid")

    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=root))
    os.chmod(temporary, 0o700)
    published = False
    try:
        inputs = temporary / "inputs"
        inputs.mkdir(mode=0o700)
        final_inputs = output_dir / "inputs"
        selector_destination = inputs / "task_file.txt"
        image_destination = inputs / "image_manifest.json"
        _write_exclusive(selector_destination, selector_body)
        _write_exclusive(image_destination, image_body)
        base = stock._load_base()[0]
        base["taskset"]["image_manifest_sha256"] = image_artifact["sha256"]
        config_body = stock._render_config(
            base,
            count=stock.TOTAL_TASKS,
            selector=final_inputs / "task_file.txt",
            selector_sha256=str(selector_artifact["sha256"]),
            dataset=Path(dataset_record["path"]),
            image_manifest=final_inputs / "image_manifest.json",
        )
        config_artifact = _write_exclusive(temporary / "config.toml", config_body)
        source_config_artifact = _write_exclusive(inputs / "source_config.toml", config_body)
        input_manifest_body = (
            json.dumps(
                {
                    "config": {
                        "source": str(output_dir / "config.toml"),
                        "snapshot": str(final_inputs / "source_config.toml"),
                        "sha256": source_config_artifact["sha256"],
                    },
                    "image_manifest": {
                        "source": str(image_record["path"]),
                        "snapshot": str(final_inputs / "image_manifest.json"),
                        "sha256": image_artifact["sha256"],
                    },
                    "task_file": {
                        "source": str(selector_record["path"]),
                        "snapshot": str(final_inputs / "task_file.txt"),
                        "sha256": selector_artifact["sha256"],
                    },
                },
                allow_nan=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        inputs_manifest_artifact = _write_exclusive(inputs / "manifest.json", input_manifest_body)
        provenance_body = (
            f"source_trace_certificate_sha256={trace_certificate_sha256}\n"
            f"source_plan_sha256={evidence.plan_sha256}\n"
            f"postprocessor_revision={expected_revision}\n"
        ).encode("ascii")
        provenance_artifact = _write_exclusive(temporary / "provenance.txt", provenance_body)
        certificate_body, original_certificate_artifact = _read_regular(
            trace_certificate,
            code="trace_certificate_invalid",
            maximum_bytes=MAX_CERTIFICATE_BYTES,
        )
        if (
            original_certificate_artifact != evidence.certificate_artifact
            or original_certificate_artifact["sha256"] != trace_certificate_sha256
            or certificate_body != _canonical(evidence.certificate)
        ):
            raise StockSmallSFTError("source_artifact_changed")
        certificate_copy = _write_exclusive(temporary / "source-certificate.json", certificate_body)
        results_artifact, row_count = _concatenate_results(
            evidence.result_artifacts,
            temporary / "results.jsonl",
        )
        revalidated = validate_final_certificate(
            temporary / "source-certificate.json",
            certificate_copy["sha256"],
        )
        if (
            revalidated.certificate != evidence.certificate
            or revalidated.plan != evidence.plan
            or revalidated.plan_sha256 != evidence.plan_sha256
            or revalidated.completions != evidence.completions
            or revalidated.result_artifacts != evidence.result_artifacts
            or revalidated.outcome_counts != evidence.outcome_counts
            or revalidated.capture_counts != evidence.capture_counts
        ):
            raise StockSmallSFTError("source_artifact_changed")
        source_shards = [
            {
                "index": index,
                "count": evidence.plan["shards"][index]["count"],
                "results": dict(record),
            }
            for index, record in enumerate(evidence.result_artifacts)
        ]
        corpus = {
            "schema_version": SCHEMA_VERSION,
            "kind": CORPUS_KIND,
            "state": "passed",
            "source": source,
            "source_certificate": {
                **certificate_copy,
                "path": "source-certificate.json",
            },
            "source_plan": {"path": str(evidence.plan_path), "sha256": evidence.plan_sha256},
            "source_shards": source_shards,
            "corpus": {
                "artifact": {**results_artifact, "path": "results.jsonl"},
                "format": "verifiers-trajectory-jsonl-v1",
                "trajectory_rows": row_count,
                "expanded_to_sft_rows": False,
                "includes_pass_fail_metadata": True,
                "includes_all_outcomes": True,
            },
            "outcomes": dict(evidence.outcome_counts),
            "capture": {
                "response_kind": "exact_provider_json",
                "reasoning_required": True,
                "reasoning_message_parity_required": True,
                "request_graph_match_required": True,
                **dict(evidence.capture_counts),
            },
            "export_inputs": {
                "config": {**config_artifact, "path": "config.toml"},
                "source_config": {**source_config_artifact, "path": "inputs/source_config.toml"},
                "task_file": {
                    "path": "inputs/task_file.txt",
                    "bytes": len(selector_body),
                    "sha256": selector_artifact["sha256"],
                },
                "image_manifest": {
                    "path": "inputs/image_manifest.json",
                    "bytes": len(image_body),
                    "sha256": image_artifact["sha256"],
                },
                "inputs_manifest": {**inputs_manifest_artifact, "path": "inputs/manifest.json"},
                "provenance": {**provenance_artifact, "path": "provenance.txt"},
            },
            "sft_derivative": {
                "selection": "pass-only",
                "expected_selected_traces": evidence.outcome_counts["positive_traces"],
                "state": "pending",
            },
        }
        corpus["corpus_manifest_sha256"] = _sha256(_canonical(corpus))
        _write_exclusive(temporary / "corpus-manifest.json", _canonical(corpus))
        directory = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        os.replace(temporary, output_dir)
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        published = True
    finally:
        if not published and temporary.exists():
            shutil.rmtree(temporary)
    return {
        "state": "passed",
        "trajectory_rows": stock.TOTAL_TASKS,
        "positive_traces": evidence.outcome_counts["positive_traces"],
        "zero_reward_traces": evidence.outcome_counts["zero_reward_traces"],
        "error_traces": evidence.outcome_counts["error_traces"],
        "results_sha256": results_artifact["sha256"],
        "manifest_sha256": _sha256(_canonical(corpus)),
    }


def _relative_record(
    root: Path,
    value: object,
    expected_path: str,
    code: str,
    *,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "bytes", "sha256"}
        or value.get("path") != expected_path
        or not _plain_int(value.get("bytes"))
        or SHA256_RE.fullmatch(str(value.get("sha256", ""))) is None
    ):
        raise StockSmallSFTError(code)
    body, artifact = _read_regular(root / expected_path, code=code, maximum_bytes=maximum_bytes)
    if value != {"path": expected_path, "bytes": artifact["bytes"], "sha256": artifact["sha256"]}:
        raise StockSmallSFTError(code)
    return body, artifact


def validate_corpus(path: Path, expected_sha256: str) -> dict[str, Any]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise StockSmallSFTError("corpus_invalid")
    root = _private_directory(path.parent, "corpus_invalid")
    if path != root / "corpus-manifest.json":
        raise StockSmallSFTError("corpus_invalid")
    body, artifact = _read_regular(path, code="corpus_invalid", maximum_bytes=MAX_CERTIFICATE_BYTES)
    value = _strict_json(body, "corpus_invalid")
    unsigned = dict(value)
    claimed = unsigned.pop("corpus_manifest_sha256", None)
    corpus = value.get("corpus")
    source_certificate = value.get("source_certificate")
    outcomes = value.get("outcomes")
    capture = value.get("capture")
    export_inputs = value.get("export_inputs")
    derivative = value.get("sft_derivative")
    source = value.get("source")
    if (
        artifact["sha256"] != expected_sha256
        or claimed != _sha256(_canonical(unsigned))
        or set(value)
        != {
            "schema_version",
            "kind",
            "state",
            "source",
            "source_certificate",
            "source_plan",
            "source_shards",
            "corpus",
            "outcomes",
            "capture",
            "export_inputs",
            "sft_derivative",
            "corpus_manifest_sha256",
        }
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != CORPUS_KIND
        or value.get("state") != "passed"
        or not isinstance(corpus, dict)
        or set(corpus)
        != {
            "artifact",
            "format",
            "trajectory_rows",
            "expanded_to_sft_rows",
            "includes_pass_fail_metadata",
            "includes_all_outcomes",
        }
        or corpus.get("format") != "verifiers-trajectory-jsonl-v1"
        or corpus.get("trajectory_rows") != stock.TOTAL_TASKS
        or corpus.get("expanded_to_sft_rows") is not False
        or corpus.get("includes_pass_fail_metadata") is not True
        or corpus.get("includes_all_outcomes") is not True
        or not isinstance(source_certificate, dict)
        or not isinstance(outcomes, dict)
        or not isinstance(capture, dict)
        or not isinstance(export_inputs, dict)
        or derivative
        != {
            "selection": "pass-only",
            "expected_selected_traces": outcomes.get("positive_traces"),
            "state": "pending",
        }
    ):
        raise StockSmallSFTError("corpus_invalid")
    if not isinstance(source, dict):
        raise StockSmallSFTError("corpus_invalid")
    try:
        observed_source = _source_binding(
            Path(str(source.get("project_root", ""))),
            str(source.get("prime_rl_revision", "")),
        )
    except StockSmallSFTError as error:
        raise StockSmallSFTError("corpus_invalid") from error
    if observed_source != source:
        raise StockSmallSFTError("corpus_invalid")
    certificate_body, certificate_artifact = _relative_record(
        root,
        source_certificate,
        "source-certificate.json",
        "corpus_invalid",
        maximum_bytes=MAX_CERTIFICATE_BYTES,
    )
    evidence = validate_final_certificate(
        root / "source-certificate.json",
        certificate_artifact["sha256"],
    )
    if (
        _strict_json(certificate_body, "corpus_invalid") != evidence.certificate
        or outcomes != evidence.outcome_counts
        or capture
        != {
            "response_kind": "exact_provider_json",
            "reasoning_required": True,
            "reasoning_message_parity_required": True,
            "request_graph_match_required": True,
            **dict(evidence.capture_counts),
        }
        or value.get("source_plan") != {"path": str(evidence.plan_path), "sha256": evidence.plan_sha256}
    ):
        raise StockSmallSFTError("corpus_invalid")
    expected_sources = [
        {
            "index": index,
            "count": evidence.plan["shards"][index]["count"],
            "results": dict(record),
        }
        for index, record in enumerate(evidence.result_artifacts)
    ]
    if value.get("source_shards") != expected_sources:
        raise StockSmallSFTError("corpus_invalid")
    corpus_artifact = corpus.get("artifact")
    if (
        not isinstance(corpus_artifact, dict)
        or set(corpus_artifact) != {"path", "bytes", "sha256"}
        or corpus_artifact.get("path") != "results.jsonl"
        or not _plain_int(corpus_artifact.get("bytes"))
        or SHA256_RE.fullmatch(str(corpus_artifact.get("sha256", ""))) is None
    ):
        raise StockSmallSFTError("corpus_invalid")
    try:
        expected_corpus_artifact, expected_lines = _concatenate_results(evidence.result_artifacts, None)
        observed_corpus_artifact, observed_lines = _concatenate_results(
            (
                {
                    "path": str(root / "results.jsonl"),
                    "bytes": corpus_artifact["bytes"],
                    "sha256": corpus_artifact["sha256"],
                },
            ),
            None,
        )
    except StockSmallSFTError as error:
        raise StockSmallSFTError("corpus_invalid") from error
    if (
        expected_lines != stock.TOTAL_TASKS
        or observed_lines != stock.TOTAL_TASKS
        or observed_corpus_artifact["bytes"] != expected_corpus_artifact["bytes"]
        or observed_corpus_artifact["sha256"] != expected_corpus_artifact["sha256"]
    ):
        raise StockSmallSFTError("corpus_invalid")
    expected_input_paths = {
        "config": "config.toml",
        "source_config": "inputs/source_config.toml",
        "task_file": "inputs/task_file.txt",
        "image_manifest": "inputs/image_manifest.json",
        "inputs_manifest": "inputs/manifest.json",
        "provenance": "provenance.txt",
    }
    if set(export_inputs) != set(expected_input_paths):
        raise StockSmallSFTError("corpus_invalid")
    input_limits = {
        "config": MAX_CONFIG_BYTES,
        "source_config": MAX_CONFIG_BYTES,
        "task_file": MAX_TASK_FILE_BYTES,
        "image_manifest": MAX_IMAGE_MANIFEST_BYTES,
        "inputs_manifest": MAX_INPUT_MANIFEST_BYTES,
        "provenance": MAX_PROVENANCE_BYTES,
    }
    for name, relative in expected_input_paths.items():
        _relative_record(
            root,
            export_inputs[name],
            relative,
            "corpus_invalid",
            maximum_bytes=input_limits[name],
        )
    try:
        _source_artifacts, config_summary, task_identity = export_sft._validate_run_provenance(
            root,
            stock.MAX_SEQUENCE_TOKENS,
        )
    except export_sft.ExportError as error:
        raise StockSmallSFTError("corpus_invalid") from error
    if (
        len(task_identity.approved_slugs) != stock.TOTAL_TASKS
        or config_summary.get("model") != stock.MODEL
        or config_summary.get("max_total_tokens") != stock.MAX_SEQUENCE_TOKENS
    ):
        raise StockSmallSFTError("corpus_invalid")
    return {
        "value": value,
        "root": root,
        "results": root / "results.jsonl",
        "results_artifact": {
            "path": str(root / "results.jsonl"),
            "bytes": observed_corpus_artifact["bytes"],
            "sha256": observed_corpus_artifact["sha256"],
        },
        "positive_traces": outcomes["positive_traces"],
        "zero_reward_traces": outcomes["zero_reward_traces"],
        "error_traces": outcomes["error_traces"],
        "manifest_sha256": artifact["sha256"],
    }


def _publish_receipt(path: Path, value: Mapping[str, Any]) -> str:
    body = _canonical(value)
    parent = _private_directory(path.parent, "output_publish_failed")
    if path != parent / path.name or path.name in {"", ".", ".."} or os.path.lexists(path):
        raise StockSmallSFTError("output_publish_failed")
    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        temporary = None
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        raise StockSmallSFTError("output_publish_failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
    published_body, published_artifact = _read_regular(
        path,
        code="output_publish_failed",
        maximum_bytes=MAX_CERTIFICATE_BYTES,
    )
    if published_body != body or published_artifact["sha256"] != _sha256(body):
        raise StockSmallSFTError("output_publish_failed")
    return _sha256(body)


def _validate_export_manifest_binding(
    body: bytes,
    *,
    corpus: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = _json_object(body, "sft_manifest_invalid")
    counts = manifest.get("counts")
    source_artifacts = manifest.get("source_artifacts")
    expected_results = corpus.get("results_artifact")
    if (
        not isinstance(counts, dict)
        or not isinstance(source_artifacts, dict)
        or not isinstance(expected_results, dict)
        or source_artifacts.get("results.jsonl")
        != {
            "bytes": expected_results.get("bytes"),
            "sha256": expected_results.get("sha256"),
        }
        or manifest.get("selection") != "pass-only"
        or manifest.get("max_sequence_tokens") != stock.MAX_SEQUENCE_TOKENS
        or manifest.get("source_validation")
        != {
            "max_sequence_tokens": stock.MAX_SEQUENCE_TOKENS,
            "require_clean_stop": True,
            "require_exact_provider_json": True,
            "require_model_io": True,
            "require_reasoning": True,
            "require_request_graph_match": True,
        }
        or counts.get("input_traces") != stock.TOTAL_TASKS
        or counts.get("approved_tasks") != stock.TOTAL_TASKS
        or counts.get("selected_traces") != corpus.get("positive_traces")
        or counts.get("selected_pass_traces") != corpus.get("positive_traces")
        or counts.get("selected_fail_traces", 0) != 0
        or counts.get("excluded_error_traces") != corpus.get("error_traces")
        or counts.get("scored_pass_traces") != corpus.get("positive_traces")
        or counts.get("scored_fail_traces", 0) != corpus.get("zero_reward_traces")
        or counts.get("selection_excluded_fail_traces", 0) != corpus.get("zero_reward_traces")
    ):
        raise StockSmallSFTError("sft_manifest_invalid")
    return manifest


def export_pass_only(
    *,
    project_root: Path,
    expected_revision: str,
    corpus_manifest: Path,
    corpus_manifest_sha256: str,
    output_root: Path,
    output_dir: Path,
    validation_permyriad: int,
    split_salt: str,
    receipt: Path,
) -> dict[str, Any]:
    source = _source_binding(project_root, expected_revision)
    root = _private_directory(output_root, "output_root_invalid")
    if (
        output_dir.parent != root
        or receipt.parent != root
        or output_dir == receipt
        or os.path.lexists(output_dir)
        or os.path.lexists(receipt)
        or not split_salt
        or not 0 <= validation_permyriad < export_sft.SPLIT_BUCKETS
    ):
        raise StockSmallSFTError("export_arguments_invalid")
    corpus = validate_corpus(corpus_manifest, corpus_manifest_sha256)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.export.", dir=root))
    os.chmod(staging_root, 0o700)
    staged_output = staging_root / "sft"
    try:
        try:
            summary = export_sft.export_sft(
                export_sft.ExportOptions(
                    results=corpus["results"],
                    output_dir=staged_output,
                    selection="pass-only",
                    expected_count=stock.TOTAL_TASKS,
                    validation_permyriad=validation_permyriad,
                    split_salt=split_salt,
                    max_sequence_tokens=stock.MAX_SEQUENCE_TOKENS,
                    require_exact_provider_json=True,
                )
            )
        except export_sft.ExportError as error:
            raise StockSmallSFTError("sft_export_failed") from error
        if (
            summary.get("status") != "exported"
            or summary.get("selection") != "pass-only"
            or summary.get("input_traces") != stock.TOTAL_TASKS
            or summary.get("approved_tasks") != stock.TOTAL_TASKS
            or summary.get("selected_traces") != corpus["positive_traces"]
            or summary.get("excluded_error_traces") != corpus["error_traces"]
            or not isinstance(summary.get("rows"), dict)
            or not isinstance(summary.get("output_sha256"), dict)
        ):
            raise StockSmallSFTError("sft_export_contract_invalid")
        manifest_body, staged_manifest_artifact = _read_regular(
            staged_output / "manifest.json",
            code="sft_manifest_invalid",
            private=False,
            maximum_bytes=MAX_CERTIFICATE_BYTES,
        )
        manifest_value = _validate_export_manifest_binding(manifest_body, corpus=corpus)
        counts = manifest_value["counts"]
        if staged_manifest_artifact["sha256"] != summary["output_sha256"].get("manifest") or summary["rows"] != {
            "total": counts.get("emitted_rows"),
            "train": counts.get("train_rows", 0),
            "validation": counts.get("validation_rows", 0),
        }:
            raise StockSmallSFTError("sft_manifest_invalid")
        try:
            if os.path.lexists(output_dir):
                raise StockSmallSFTError("output_publish_failed")
            os.rename(staged_output, output_dir)
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as error:
            raise StockSmallSFTError("output_publish_failed") from error
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)

    manifest_body, observed_manifest_artifact = _read_regular(
        output_dir / "manifest.json",
        code="sft_manifest_invalid",
        private=False,
        maximum_bytes=MAX_CERTIFICATE_BYTES,
    )
    _validate_export_manifest_binding(manifest_body, corpus=corpus)
    if observed_manifest_artifact["sha256"] != summary["output_sha256"].get("manifest"):
        raise StockSmallSFTError("sft_manifest_invalid")
    manifest_artifact = {**observed_manifest_artifact, "path": str(output_dir / "manifest.json")}
    value = {
        "schema_version": SCHEMA_VERSION,
        "kind": EXPORT_KIND,
        "state": "exported",
        "source": source,
        "unfiltered_corpus": {
            "path": str(corpus_manifest),
            "sha256": corpus_manifest_sha256,
            "results": corpus["results_artifact"],
            "trajectory_rows": stock.TOTAL_TASKS,
            "includes_all_outcomes": True,
        },
        "export": {
            "root": str(output_dir),
            "manifest": manifest_artifact,
            "selection": "pass-only",
            "input_traces": summary["input_traces"],
            "selected_traces": summary["selected_traces"],
            "rows": summary["rows"],
            "validation_permyriad": validation_permyriad,
            "split_salt_sha256": _sha256(split_salt.encode("utf-8")),
            "require_exact_provider_json": True,
            "reasoning_required": True,
        },
        "preflight": {"required": True, "state": "pending"},
    }
    receipt_sha256 = _publish_receipt(receipt, value)
    return {
        "state": "exported",
        "input_trajectories": stock.TOTAL_TASKS,
        "selected_traces": summary["selected_traces"],
        "rows": summary["rows"]["total"],
        "manifest_sha256": manifest_artifact["sha256"],
        "receipt_sha256": receipt_sha256,
    }


def _load_export_receipt(path: Path, expected_sha256: str) -> dict[str, Any]:
    body, artifact = _read_regular(path, code="export_receipt_invalid", maximum_bytes=MAX_CERTIFICATE_BYTES)
    value = _strict_json(body, "export_receipt_invalid")
    export = value.get("export")
    corpus = value.get("unfiltered_corpus")
    if (
        artifact["sha256"] != expected_sha256
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != EXPORT_KIND
        or value.get("state") != "exported"
        or not isinstance(export, dict)
        or export.get("selection") != "pass-only"
        or export.get("input_traces") != stock.TOTAL_TASKS
        or not _plain_int(export.get("selected_traces"), minimum=1)
        or export.get("require_exact_provider_json") is not True
        or export.get("reasoning_required") is not True
        or not isinstance(corpus, dict)
        or set(corpus) != {"path", "sha256", "results", "trajectory_rows", "includes_all_outcomes"}
        or not isinstance(corpus.get("path"), str)
        or not Path(corpus["path"]).is_absolute()
        or SHA256_RE.fullmatch(str(corpus.get("sha256", ""))) is None
        or not isinstance(corpus.get("results"), dict)
        or corpus.get("trajectory_rows") != stock.TOTAL_TASKS
        or corpus.get("includes_all_outcomes") is not True
        or value.get("preflight") != {"required": True, "state": "pending"}
    ):
        raise StockSmallSFTError("export_receipt_invalid")
    return value


def preflight_export(
    *,
    project_root: Path,
    expected_revision: str,
    export_receipt: Path,
    export_receipt_sha256: str,
    tokenizer_snapshot_path: Path | None,
    tokenizer_snapshot_sha256: str | None,
    output: Path,
) -> dict[str, Any]:
    source = _source_binding(project_root, expected_revision)
    value = _load_export_receipt(export_receipt, export_receipt_sha256)
    if value.get("source") != source:
        raise StockSmallSFTError("export_receipt_invalid")
    export = value["export"]
    corpus_record = value["unfiltered_corpus"]
    corpus = validate_corpus(Path(corpus_record["path"]), str(corpus_record["sha256"]))
    if (
        corpus_record.get("results") != corpus["results_artifact"]
        or export.get("selected_traces") != corpus["positive_traces"]
        or export.get("input_traces") != stock.TOTAL_TASKS
    ):
        raise StockSmallSFTError("export_receipt_invalid")
    root = Path(str(export["root"]))
    manifest = export.get("manifest")
    if not isinstance(manifest, dict):
        raise StockSmallSFTError("sft_manifest_invalid")
    manifest_body, observed = _read_regular(
        root / "manifest.json",
        code="sft_manifest_invalid",
        private=False,
        maximum_bytes=MAX_CERTIFICATE_BYTES,
    )
    if observed != manifest:
        raise StockSmallSFTError("sft_manifest_invalid")
    manifest_value = _validate_export_manifest_binding(manifest_body, corpus=corpus)
    counts = manifest_value["counts"]
    if export.get("rows") != {
        "total": counts.get("emitted_rows"),
        "train": counts.get("train_rows", 0),
        "validation": counts.get("validation_rows", 0),
    }:
        raise StockSmallSFTError("sft_manifest_invalid")
    try:
        from prime_rl.trainer.sft.export_preflight import (
            SFTPreflightError,
            create_sft_preflight_attestation,
        )

        summary = create_sft_preflight_attestation(
            export_root=root,
            expected_manifest_sha256=str(manifest["sha256"]),
            project_dir=project_root,
            expected_project_revision=expected_revision,
            expected_require_exact_provider_json=True,
            output=output,
            tokenizer_snapshot_path=tokenizer_snapshot_path,
            expected_tokenizer_snapshot_sha256=tokenizer_snapshot_sha256,
        )
    except (ImportError, SFTPreflightError) as error:
        raise StockSmallSFTError("sft_preflight_failed") from error
    return {
        "state": "attested",
        "attestation_sha256": summary["attestation_sha256"],
        "rendered_rows": summary["rendering"]["rows"],
        "selected_traces": export["selected_traces"],
    }


class StableParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise StockSmallSFTError("arguments_invalid")


def _parser() -> StableParser:
    parser = StableParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    package = commands.add_parser("package")
    package.add_argument("--project-root", type=Path, required=True)
    package.add_argument("--expected-revision", required=True)
    package.add_argument("--trace-certificate", type=Path, required=True)
    package.add_argument("--trace-certificate-sha256", required=True)
    package.add_argument("--output-root", type=Path, required=True)
    package.add_argument("--output-dir", type=Path, required=True)
    validate = commands.add_parser("validate-corpus")
    validate.add_argument("--corpus-manifest", type=Path, required=True)
    validate.add_argument("--corpus-manifest-sha256", required=True)
    exporter = commands.add_parser("export")
    exporter.add_argument("--project-root", type=Path, required=True)
    exporter.add_argument("--expected-revision", required=True)
    exporter.add_argument("--corpus-manifest", type=Path, required=True)
    exporter.add_argument("--corpus-manifest-sha256", required=True)
    exporter.add_argument("--output-root", type=Path, required=True)
    exporter.add_argument("--output-dir", type=Path, required=True)
    exporter.add_argument("--validation-permyriad", type=int, default=500)
    exporter.add_argument("--split-salt", required=True)
    exporter.add_argument("--receipt", type=Path, required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--project-root", type=Path, required=True)
    preflight.add_argument("--expected-revision", required=True)
    preflight.add_argument("--export-receipt", type=Path, required=True)
    preflight.add_argument("--export-receipt-sha256", required=True)
    preflight.add_argument("--tokenizer-snapshot-path", type=Path)
    preflight.add_argument("--tokenizer-snapshot-sha256")
    preflight.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "package":
            result = package_unfiltered(
                project_root=args.project_root,
                expected_revision=args.expected_revision,
                trace_certificate=args.trace_certificate,
                trace_certificate_sha256=args.trace_certificate_sha256,
                output_root=args.output_root,
                output_dir=args.output_dir,
            )
        elif args.command == "validate-corpus":
            corpus = validate_corpus(args.corpus_manifest, args.corpus_manifest_sha256)
            result = {
                "state": "passed",
                "trajectory_rows": stock.TOTAL_TASKS,
                "positive_traces": corpus["positive_traces"],
                "zero_reward_traces": corpus["zero_reward_traces"],
                "error_traces": corpus["error_traces"],
            }
        elif args.command == "export":
            result = export_pass_only(
                project_root=args.project_root,
                expected_revision=args.expected_revision,
                corpus_manifest=args.corpus_manifest,
                corpus_manifest_sha256=args.corpus_manifest_sha256,
                output_root=args.output_root,
                output_dir=args.output_dir,
                validation_permyriad=args.validation_permyriad,
                split_salt=args.split_salt,
                receipt=args.receipt,
            )
        else:
            if (args.tokenizer_snapshot_path is None) != (args.tokenizer_snapshot_sha256 is None):
                raise StockSmallSFTError("arguments_invalid")
            result = preflight_export(
                project_root=args.project_root,
                expected_revision=args.expected_revision,
                export_receipt=args.export_receipt,
                export_receipt_sha256=args.export_receipt_sha256,
                tokenizer_snapshot_path=args.tokenizer_snapshot_path,
                tokenizer_snapshot_sha256=args.tokenizer_snapshot_sha256,
                output=args.output,
            )
    except StockSmallSFTError as error:
        print(json.dumps({"code": error.code, "state": "blocked"}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print('{"code":"internal_error","state":"blocked"}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
