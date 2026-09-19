#!/usr/bin/env python3
"""Materialize the opaque Qwen Sandoq/VMVM partition without disclosing members.

The single Compose member is deliberately absent from receipts and stdout, even as
a hash or an index.  A verifier reopens the pinned dataset and private task files to
rederive the partition.  Public evidence contains only full-corpus commitments and
aggregate cardinalities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

CANONICAL_SOURCE_SHA256 = "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"
CANONICAL_SOURCE_COUNT = 2500
CANONICAL_DATASET_REVISION = "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
CANONICAL_DATASET_TREE = "a6c036e1b9abfd7075902ca38ef757587079a59b"
CANONICAL_SANDOQ_TEMPLATE_SHA256 = "3a94586b7c7e58490d025c5490810418728e1aeab0287e4976dcceeb4c722db5"
CANONICAL_VMVM_TEMPLATE_SHA256 = "36261603829d9452cbacbc980edcc5a6707c9e4bfb2660d3972f896083720668"
SANDOQ_COUNT = 2499
VMVM_COUNT = 1
COMPOSE_FILENAMES = (
    "docker-compose.yaml",
    "docker-compose.yml",
    "compose.yaml",
    "compose.yml",
)


class MixedMaterializationError(ValueError):
    """A fail-closed error whose message never contains task-level data."""


@dataclass(frozen=True, slots=True)
class Partition:
    sandoq: tuple[str, ...]
    vmvm: tuple[str, ...]
    no_network_count: int


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise MixedMaterializationError("receipt_invalid") from error


def _read_regular(path: Path) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise MixedMaterializationError("artifact_unreadable") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise MixedMaterializationError("artifact_not_regular")
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if identity(before) != identity(after):
        raise MixedMaterializationError("artifact_changed")
    return bytes(body)


def _git(dataset: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(dataset), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise MixedMaterializationError("canonical_dataset_unverifiable") from error
    return completed.stdout


def verify_canonical_dataset(dataset: Path) -> Path:
    try:
        resolved = dataset.resolve(strict=True)
    except OSError as error:
        raise MixedMaterializationError("canonical_dataset_unverifiable") from error
    if not resolved.is_dir() or dataset.is_symlink():
        raise MixedMaterializationError("canonical_dataset_unverifiable")
    revision = _git(resolved, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
    tree = _git(resolved, "rev-parse", "HEAD^{tree}").decode("ascii", errors="strict").strip()
    dirty = _git(resolved, "status", "--porcelain=v1", "--untracked-files=all")
    if revision != CANONICAL_DATASET_REVISION or tree != CANONICAL_DATASET_TREE or dirty:
        raise MixedMaterializationError("canonical_dataset_mismatch")
    return resolved


def _valid_member(member: str) -> bool:
    return (
        bool(member)
        and member not in {".", ".."}
        and "/" not in member
        and "\\" not in member
        and "\x00" not in member
        and not member.isspace()
    )


def _network_policy(
    value: object,
    *,
    default: Literal["public", "no-network"],
    phase_override: bool = False,
) -> Literal["public", "no-network"]:
    if value is None:
        return default
    if not isinstance(value, dict):
        raise MixedMaterializationError("task_network_contract_invalid")
    declared = value.get("network_mode")
    if declared is None and phase_override:
        declared = value.get("network")
    if declared is None:
        allow_internet = value.get("allow_internet")
        if allow_internet is None:
            declared = default
        elif isinstance(allow_internet, bool):
            declared = "public" if allow_internet else "no-network"
        else:
            raise MixedMaterializationError("task_network_contract_invalid")
    if declared not in {"public", "no-network"} or value.get("allowed_hosts"):
        raise MixedMaterializationError("task_network_contract_invalid")
    return declared


def _network_modes(raw: object) -> tuple[str, str]:
    if not isinstance(raw, dict):
        raise MixedMaterializationError("task_metadata_invalid")
    environment = raw.get("environment", {})
    agent = raw.get("agent", {})
    verifier = raw.get("verifier", {})
    if not isinstance(verifier, dict):
        raise MixedMaterializationError("task_network_contract_invalid")
    verifier_environment = verifier.get("environment")
    mode = verifier.get("environment_mode")
    if mode is None:
        mode = "separate" if verifier_environment is not None else "shared"
    if mode not in {"shared", "separate"}:
        raise MixedMaterializationError("task_network_contract_invalid")
    baseline = _network_policy(environment, default="public")
    agent_mode = _network_policy(agent, default=baseline, phase_override=True)
    if baseline == "no-network" and agent_mode == "public":
        raise MixedMaterializationError("task_network_contract_invalid")
    if mode == "separate" and verifier_environment is not None:
        verifier_baseline = _network_policy(verifier_environment, default="public")
    else:
        verifier_baseline = baseline
    verifier_mode = _network_policy(verifier, default=verifier_baseline, phase_override=True)
    if verifier_baseline == "no-network" and verifier_mode == "public":
        raise MixedMaterializationError("task_network_contract_invalid")
    if mode == "shared" and agent_mode == "no-network" and verifier_mode == "public":
        raise MixedMaterializationError("task_network_contract_invalid")
    return agent_mode, verifier_mode


def derive_partition(source_raw: bytes, dataset: Path) -> Partition:
    try:
        text = source_raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MixedMaterializationError("canonical_source_invalid") from error
    if not text.endswith("\n") or "\r" in text:
        raise MixedMaterializationError("canonical_source_invalid")
    members = text.splitlines()
    if (
        len(members) != CANONICAL_SOURCE_COUNT
        or len(members) != len(set(members))
        or any(not _valid_member(member) for member in members)
    ):
        raise MixedMaterializationError("canonical_source_invalid")
    sandoq: list[str] = []
    vmvm: list[str] = []
    no_network_count = 0
    for member in members:
        task = dataset / member
        if task.is_symlink() or not task.is_dir() or task.parent != dataset:
            raise MixedMaterializationError("canonical_dataset_task_invalid")
        metadata_path = task / "task.toml"
        if metadata_path.is_symlink():
            raise MixedMaterializationError("canonical_dataset_task_invalid")
        try:
            metadata = tomllib.loads(_read_regular(metadata_path).decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise MixedMaterializationError("task_metadata_invalid") from error
        if _network_modes(metadata) != ("no-network", "no-network"):
            raise MixedMaterializationError("task_network_not_isolated")
        no_network_count += 1
        environment = task / "environment"
        compose = []
        for filename in COMPOSE_FILENAMES:
            candidate = environment / filename
            if candidate.is_symlink():
                raise MixedMaterializationError("compose_artifact_invalid")
            if candidate.is_file():
                compose.append(candidate)
        if compose:
            vmvm.append(member)
        else:
            sandoq.append(member)
    if len(sandoq) != SANDOQ_COUNT or len(vmvm) != VMVM_COUNT:
        raise MixedMaterializationError("canonical_partition_cardinality_mismatch")
    if set(sandoq).intersection(vmvm) or set(sandoq).union(vmvm) != set(members):
        raise MixedMaterializationError("canonical_partition_invalid")
    return Partition(tuple(sandoq), tuple(vmvm), no_network_count)


def _task_payload(members: tuple[str, ...]) -> bytes:
    return ("\n".join(members) + "\n").encode("utf-8")


def _replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise MixedMaterializationError("canonical_template_shape_mismatch")
    return text.replace(old, new)


def _task_binding(text: str, task_file: Path, task_sha256: str) -> str:
    old_path = (
        'task_file = "user/tianhaowu/terminal_bench_vmvm/configs/eval/'
        'mobius_valid_tasks_2500.txt"'
    )
    old_sha = f'task_file_sha256 = "{CANONICAL_SOURCE_SHA256}"'
    text = _replace_once(text, old_path, f"task_file = {json.dumps(str(task_file.resolve()))}")
    return _replace_once(text, old_sha, f'task_file_sha256 = "{task_sha256}"')


def materialize_sandoq_config(template_raw: bytes, task_file: Path, task_sha256: str) -> bytes:
    if sha256(template_raw) != CANONICAL_SANDOQ_TEMPLATE_SHA256:
        raise MixedMaterializationError("canonical_sandoq_template_mismatch")
    try:
        text = template_raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MixedMaterializationError("canonical_sandoq_template_mismatch") from error
    text = _replace_once(text, "num_tasks = 2500", f"num_tasks = {SANDOQ_COUNT}")
    return _task_binding(text, task_file, task_sha256).encode("utf-8")


def materialize_vmvm_config(template_raw: bytes, task_file: Path, task_sha256: str) -> bytes:
    if sha256(template_raw) != CANONICAL_VMVM_TEMPLATE_SHA256:
        raise MixedMaterializationError("canonical_vmvm_template_mismatch")
    try:
        text = template_raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MixedMaterializationError("canonical_vmvm_template_mismatch") from error
    for old, new in (
        ("num_tasks = 2500", f"num_tasks = {VMVM_COUNT}"),
        ("max_concurrent = 64", f"max_concurrent = {VMVM_COUNT}"),
        ("multiplex = 64", f"multiplex = {VMVM_COUNT}"),
        ("max_connections = 32", f"max_connections = {VMVM_COUNT}"),
        ("max_keepalive_connections = 32", f"max_keepalive_connections = {VMVM_COUNT}"),
    ):
        text = _replace_once(text, old, new)
    if "reasoning_effort" in text:
        raise MixedMaterializationError("canonical_vmvm_template_shape_mismatch")
    text = _replace_once(text, "[sampling]\n", '[sampling]\nreasoning_effort = "max"\n')
    if "enable_compose" in text:
        raise MixedMaterializationError("canonical_vmvm_template_shape_mismatch")
    text = _replace_once(text, "[taskset]\n", "[taskset]\nenable_compose = true\n")
    return _task_binding(text, task_file, task_sha256).encode("utf-8")


def receipt_value() -> dict[str, Any]:
    derivation = {
        "compose_detection": "harbor-compose-precedence-v1",
        "network_policy": "both-phases-no-network-v1",
        "selection": "canonical-order-partition",
    }
    return {
        "schema_version": 1,
        "kind": "qwen-mixed-provider-materialization",
        "state": "materialized",
        "source": {"count": CANONICAL_SOURCE_COUNT, "sha256": CANONICAL_SOURCE_SHA256},
        "dataset": {
            "revision": CANONICAL_DATASET_REVISION,
            "tree": CANONICAL_DATASET_TREE,
        },
        "templates": {
            "sandoq_sha256": CANONICAL_SANDOQ_TEMPLATE_SHA256,
            "vmvm_sha256": CANONICAL_VMVM_TEMPLATE_SHA256,
        },
        "partition": {
            "compose_count": VMVM_COUNT,
            "disjoint": True,
            "exhaustive": True,
            "no_network_count": CANONICAL_SOURCE_COUNT,
            "sandoq_count": SANDOQ_COUNT,
            "vmvm_count": VMVM_COUNT,
        },
        "derivation": derivation,
        "derivation_sha256": sha256(_canonical_json(derivation)),
    }


def publish_exclusive(outputs: list[tuple[Path, bytes]]) -> None:
    if len({path.resolve() for path, _ in outputs}) != len(outputs):
        raise MixedMaterializationError("output_path_collision")
    if any(os.path.lexists(path) for path, _ in outputs):
        raise MixedMaterializationError("outputs_require_fresh_namespace")
    for path, _ in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    temporary_paths: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for output, payload in outputs:
            descriptor, temporary_name = tempfile.mkstemp(dir=output.parent, prefix=f".{output.name}.")
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temporary_paths.append((output, temporary))
        for output, temporary in temporary_paths:
            os.link(temporary, output)
            published.append(output)
    except Exception:
        for output in published:
            output.unlink(missing_ok=True)
        raise
    finally:
        for _, temporary in temporary_paths:
            temporary.unlink(missing_ok=True)


def materialize(
    *,
    source: Path,
    dataset: Path,
    sandoq_template: Path,
    vmvm_template: Path,
    sandoq_tasks: Path,
    vmvm_tasks: Path,
    sandoq_config: Path,
    vmvm_config: Path,
    receipt: Path,
) -> dict[str, Any]:
    source_raw = _read_regular(source)
    if sha256(source_raw) != CANONICAL_SOURCE_SHA256:
        raise MixedMaterializationError("canonical_source_mismatch")
    resolved_dataset = verify_canonical_dataset(dataset)
    partition = derive_partition(source_raw, resolved_dataset)
    if partition.no_network_count != CANONICAL_SOURCE_COUNT:
        raise MixedMaterializationError("task_network_not_isolated")
    sandoq_task_payload = _task_payload(partition.sandoq)
    vmvm_task_payload = _task_payload(partition.vmvm)
    sandoq_template_raw = _read_regular(sandoq_template)
    vmvm_template_raw = _read_regular(vmvm_template)
    sandoq_config_payload = materialize_sandoq_config(
        sandoq_template_raw,
        sandoq_tasks,
        sha256(sandoq_task_payload),
    )
    vmvm_config_payload = materialize_vmvm_config(
        vmvm_template_raw,
        vmvm_tasks,
        sha256(vmvm_task_payload),
    )
    receipt = receipt.resolve()
    outputs = [
        (sandoq_tasks, sandoq_task_payload),
        (vmvm_tasks, vmvm_task_payload),
        (sandoq_config, sandoq_config_payload),
        (vmvm_config, vmvm_config_payload),
        (receipt, _canonical_json(receipt_value())),
    ]
    publish_exclusive(outputs)
    return {
        "state": "materialized",
        "source_count": CANONICAL_SOURCE_COUNT,
        "sandoq_count": SANDOQ_COUNT,
        "vmvm_count": VMVM_COUNT,
    }


def validate_materialization(
    *,
    source: Path,
    dataset: Path,
    sandoq_template: Path,
    vmvm_template: Path,
    sandoq_tasks: Path,
    vmvm_tasks: Path,
    sandoq_config: Path,
    vmvm_config: Path,
    receipt: Path,
    receipt_sha256: str,
) -> dict[str, Any]:
    source_raw = _read_regular(source)
    if sha256(source_raw) != CANONICAL_SOURCE_SHA256:
        raise MixedMaterializationError("canonical_source_mismatch")
    resolved_dataset = verify_canonical_dataset(dataset)
    partition = derive_partition(source_raw, resolved_dataset)
    sandoq_task_payload = _task_payload(partition.sandoq)
    vmvm_task_payload = _task_payload(partition.vmvm)
    if _read_regular(sandoq_tasks) != sandoq_task_payload or _read_regular(vmvm_tasks) != vmvm_task_payload:
        raise MixedMaterializationError("materialized_partition_mismatch")
    expected_sandoq_config = materialize_sandoq_config(
        _read_regular(sandoq_template),
        sandoq_tasks,
        sha256(sandoq_task_payload),
    )
    expected_vmvm_config = materialize_vmvm_config(
        _read_regular(vmvm_template),
        vmvm_tasks,
        sha256(vmvm_task_payload),
    )
    if (
        _read_regular(sandoq_config) != expected_sandoq_config
        or _read_regular(vmvm_config) != expected_vmvm_config
    ):
        raise MixedMaterializationError("materialized_config_mismatch")
    receipt_raw = _read_regular(receipt)
    if sha256(receipt_raw) != receipt_sha256 or receipt_raw != _canonical_json(receipt_value()):
        raise MixedMaterializationError("materialization_receipt_invalid")
    return {
        "sha256": receipt_sha256,
        "source": receipt_value()["source"],
        "dataset": receipt_value()["dataset"],
        "templates": receipt_value()["templates"],
        "partition": receipt_value()["partition"],
        "derivation_sha256": receipt_value()["derivation_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--sandoq-template", type=Path, required=True)
    parser.add_argument("--vmvm-template", type=Path, required=True)
    parser.add_argument("--sandoq-tasks", type=Path, required=True)
    parser.add_argument("--vmvm-tasks", type=Path, required=True)
    parser.add_argument("--sandoq-config", type=Path, required=True)
    parser.add_argument("--vmvm-config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    workflow = Path(__file__).resolve().parent
    canonical_source = workflow / "configs/eval/mobius_valid_tasks_2500.txt"
    canonical_sandoq_template = workflow / "configs/eval/mobius_qwen_a95b_2500_sandoq.toml"
    canonical_vmvm_template = workflow / "configs/eval/mobius_qwen_a95b_2500.toml"
    try:
        if (
            args.source.resolve(strict=True) != canonical_source
            or args.sandoq_template.resolve(strict=True) != canonical_sandoq_template
            or args.vmvm_template.resolve(strict=True) != canonical_vmvm_template
        ):
            raise MixedMaterializationError("canonical_input_path_mismatch")
        summary = materialize(**vars(args))
    except (OSError, MixedMaterializationError) as error:
        code = str(error) if isinstance(error, MixedMaterializationError) else "materialization_failed"
        raise SystemExit(code) from None
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
