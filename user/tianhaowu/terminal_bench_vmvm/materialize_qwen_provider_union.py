#!/usr/bin/env python3
"""Materialize the opaque Qwen Sandoq/VMVM partition without disclosing members.

The single Compose member is deliberately absent from receipts and stdout, even as
a hash or an index.  A verifier reopens the pinned dataset and private task files to
rederive the partition.  Public evidence contains only full-corpus commitments and
aggregate cardinalities.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import stat
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal

CANONICAL_SOURCE_SHA256 = "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"
CANONICAL_SOURCE_COUNT = 2500
DEPLOYMENT_NAMESPACE = "shared_qwen38_2p4t"
CANONICAL_DATASET_REVISION = "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
CANONICAL_DATASET_TREE = "a6c036e1b9abfd7075902ca38ef757587079a59b"
CANONICAL_SANDOQ_TEMPLATE_SHA256 = "f2c8050ddd86c0aa80cedd3014e975e2fb7967062c4ead2d2a0fb04c77c826bf"
CANONICAL_VMVM_TEMPLATE_SHA256 = "78bc527f9491b179f46e8d8bd06f5a7685a8c5cc9956644f6994112341803b13"
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


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _open_anchored(path: Path, *, directory: bool = False) -> int:
    if not path.is_absolute() or path != Path(os.path.normpath(path)) or not path.name:
        raise MixedMaterializationError("artifact_unreadable")
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.path.sep, directory_flags)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, directory_flags | nofollow, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        flags = os.O_RDONLY | os.O_CLOEXEC | nofollow
        if directory:
            flags |= getattr(os, "O_DIRECTORY", 0)
        result = os.open(path.name, flags, dir_fd=descriptor)
    except OSError as error:
        os.close(descriptor)
        raise MixedMaterializationError("artifact_unreadable") from error
    os.close(descriptor)
    return result


def _read_regular(path: Path) -> bytes:
    descriptor = _open_anchored(path)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise MixedMaterializationError("artifact_not_regular")
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
        after = os.fstat(descriptor)
        try:
            current = path.lstat()
        except OSError as error:
            raise MixedMaterializationError("artifact_changed") from error
    finally:
        os.close(descriptor)
    if _stat_identity(before) != _stat_identity(after) or _stat_identity(after) != _stat_identity(current):
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
    if not isinstance(value, dict):
        raise MixedMaterializationError("task_network_contract_invalid")
    declared = value.get("network_mode")
    if declared is None:
        if phase_override and "allowed_hosts" in value:
            raise MixedMaterializationError("task_network_contract_invalid")
        if not phase_override and "allow_internet" in value:
            allow_internet = value["allow_internet"]
            if not isinstance(allow_internet, bool):
                raise MixedMaterializationError("task_network_contract_invalid")
            declared = "public" if allow_internet else "no-network"
        else:
            declared = default
    if declared not in {"public", "no-network"}:
        raise MixedMaterializationError("task_network_contract_invalid")
    if value.get("allowed_hosts"):
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
    return (("\n".join(members) + "\n") if members else "").encode("utf-8")


def _replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise MixedMaterializationError("canonical_template_shape_mismatch")
    return text.replace(old, new)


def _task_binding(text: str, task_file: Path, task_sha256: str) -> str:
    old_path = 'task_file = "user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt"'
    old_sha = f'task_file_sha256 = "{CANONICAL_SOURCE_SHA256}"'
    text = _replace_once(text, old_path, f"task_file = {json.dumps(str(task_file))}")
    return _replace_once(text, old_sha, f'task_file_sha256 = "{task_sha256}"')


def materialize_sandoq_config(
    template_raw: bytes,
    task_file: Path,
    task_sha256: str,
    *,
    task_count: int = SANDOQ_COUNT,
) -> bytes:
    if sha256(template_raw) != CANONICAL_SANDOQ_TEMPLATE_SHA256:
        raise MixedMaterializationError("canonical_sandoq_template_mismatch")
    try:
        text = template_raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MixedMaterializationError("canonical_sandoq_template_mismatch") from error
    if not isinstance(task_count, int) or isinstance(task_count, bool) or task_count < 1:
        raise MixedMaterializationError("sandoq_task_count_invalid")
    text = _replace_once(text, "num_tasks = 2500", f"num_tasks = {task_count}")
    return _task_binding(text, task_file, task_sha256).encode("utf-8")


def materialize_vmvm_config(
    template_raw: bytes,
    task_file: Path,
    task_sha256: str,
    *,
    task_count: int = VMVM_COUNT,
) -> bytes:
    if sha256(template_raw) != CANONICAL_VMVM_TEMPLATE_SHA256:
        raise MixedMaterializationError("canonical_vmvm_template_mismatch")
    try:
        text = template_raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MixedMaterializationError("canonical_vmvm_template_mismatch") from error
    if not isinstance(task_count, int) or isinstance(task_count, bool) or task_count not in {0, 1}:
        raise MixedMaterializationError("vmvm_task_count_invalid")
    for old, new in (
        ("num_tasks = 2500", f"num_tasks = {task_count}"),
        ("max_concurrent = 64", f"max_concurrent = {task_count}"),
        ("multiplex = 64", f"multiplex = {task_count}"),
        ("max_connections = 32", f"max_connections = {task_count}"),
        ("max_keepalive_connections = 32", f"max_keepalive_connections = {task_count}"),
    ):
        text = _replace_once(text, old, new)
    if text.count('reasoning_effort = "max"') != 1:
        raise MixedMaterializationError("canonical_vmvm_template_shape_mismatch")
    if text.count("enable_compose = true") != 1:
        raise MixedMaterializationError("canonical_vmvm_template_shape_mismatch")
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
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
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


@dataclass(slots=True)
class _PrivateOutputRoot:
    path: Path
    descriptor: int
    device: int
    inode: int

    def revalidate(self) -> None:
        try:
            bound = os.fstat(self.descriptor)
            observed_descriptor = _open_anchored(self.path, directory=True)
            try:
                observed = os.fstat(observed_descriptor)
            finally:
                os.close(observed_descriptor)
        except (OSError, MixedMaterializationError) as error:
            raise MixedMaterializationError("private_output_root_changed") from error
        for value in (bound, observed):
            if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.getuid() or stat.S_IMODE(value.st_mode) != 0o700:
                raise MixedMaterializationError("private_output_root_changed")
        if (bound.st_dev, bound.st_ino) != (self.device, self.inode) or (
            observed.st_dev,
            observed.st_ino,
        ) != (self.device, self.inode):
            raise MixedMaterializationError("private_output_root_changed")

    def name_for(self, path: Path) -> str:
        if (
            not path.is_absolute()
            or path != Path(os.path.normpath(path))
            or path.parent != self.path
            or path.name in {"", ".", ".."}
        ):
            raise MixedMaterializationError("private_output_path_invalid")
        return path.name


def _private_artifact_status(root: _PrivateOutputRoot, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=root.descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise MixedMaterializationError("private_output_artifact_invalid") from error


def _validate_private_artifact_status(value: os.stat_result) -> None:
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_nlink != 1
    ):
        raise MixedMaterializationError("private_output_artifact_invalid")


def _read_private_artifact(root: _PrivateOutputRoot, path: Path) -> bytes:
    name = root.name_for(path)
    root.revalidate()
    listed_before = _private_artifact_status(root, name)
    if listed_before is None:
        raise MixedMaterializationError("private_output_artifact_invalid")
    _validate_private_artifact_status(listed_before)
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root.descriptor,
        )
    except OSError as error:
        raise MixedMaterializationError("private_output_artifact_invalid") from error
    try:
        before = os.fstat(descriptor)
        _validate_private_artifact_status(before)
        if _stat_identity(before) != _stat_identity(listed_before):
            raise MixedMaterializationError("private_output_artifact_changed")
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    listed_after = _private_artifact_status(root, name)
    if (
        listed_after is None
        or _stat_identity(before) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(listed_after)
    ):
        raise MixedMaterializationError("private_output_artifact_changed")
    _validate_private_artifact_status(listed_after)
    root.revalidate()
    return bytes(body)


def _unlink_matching(root: _PrivateOutputRoot, name: str, identity: tuple[int, int]) -> None:
    try:
        observed = os.stat(name, dir_fd=root.descriptor, follow_symlinks=False)
        if (observed.st_dev, observed.st_ino) == identity:
            os.unlink(name, dir_fd=root.descriptor)
    except FileNotFoundError:
        pass


def publish_exclusive(root: _PrivateOutputRoot, outputs: list[tuple[Path, bytes]]) -> None:
    names = [root.name_for(path) for path, _ in outputs]
    if len(set(names)) != len(names):
        raise MixedMaterializationError("output_path_collision")
    root.revalidate()
    if any(_private_artifact_status(root, name) is not None for name in names):
        raise MixedMaterializationError("outputs_require_fresh_namespace")
    temporaries: list[tuple[str, str, tuple[int, int]]] = []
    published: list[tuple[str, tuple[int, int]]] = []
    publish_error: BaseException | None = None
    try:
        for name, (_, payload) in zip(names, outputs, strict=True):
            temporary = f".{name}.{os.urandom(16).hex()}"
            try:
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=root.descriptor,
                )
            except OSError as error:
                raise MixedMaterializationError("private_output_publish_failed") from error
            try:
                metadata = os.fstat(descriptor)
                _validate_private_artifact_status(metadata)
                identity = (metadata.st_dev, metadata.st_ino)
                temporaries.append((name, temporary, identity))
                with os.fdopen(descriptor, "wb", closefd=False) as handle:
                    os.fchmod(descriptor, 0o600)
                    handle.write(payload)
                    handle.flush()
                    os.fsync(descriptor)
                completed = os.fstat(descriptor)
                if (completed.st_dev, completed.st_ino) != identity:
                    raise MixedMaterializationError("private_output_publish_failed")
            finally:
                os.close(descriptor)
            _validate_private_artifact_status(completed)
        root.revalidate()
        for name, temporary, identity in temporaries:
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=root.descriptor,
                    dst_dir_fd=root.descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as error:
                raise MixedMaterializationError("outputs_require_fresh_namespace") from error
            except OSError as error:
                raise MixedMaterializationError("private_output_publish_failed") from error
            published.append((name, identity))
        for _, temporary, identity in temporaries:
            _unlink_matching(root, temporary, identity)
        for name, identity in published:
            metadata = _private_artifact_status(root, name)
            if metadata is None or (metadata.st_dev, metadata.st_ino) != identity:
                raise MixedMaterializationError("private_output_publish_failed")
            _validate_private_artifact_status(metadata)
        root.revalidate()
        os.fsync(root.descriptor)
    except BaseException as error:
        publish_error = error
        for name, identity in published:
            with contextlib.suppress(OSError):
                _unlink_matching(root, name, identity)
        with contextlib.suppress(OSError):
            os.fsync(root.descriptor)
        raise
    finally:
        cleanup_failed = False
        for _, temporary, identity in temporaries:
            try:
                _unlink_matching(root, temporary, identity)
            except OSError:
                cleanup_failed = True
        if cleanup_failed and publish_error is None:
            raise MixedMaterializationError("private_output_cleanup_failed")


@contextlib.contextmanager
def _open_private_output_root(
    root: Path,
    outputs: tuple[Path, ...],
    *,
    forbidden_roots: tuple[Path, ...],
    validate_existing: bool = True,
) -> Iterator[_PrivateOutputRoot]:
    if not root.is_absolute() or root != Path(os.path.normpath(root)):
        raise MixedMaterializationError("private_output_root_invalid")
    try:
        resolved = root.resolve(strict=True)
        descriptor = _open_anchored(root, directory=True)
        metadata = os.fstat(descriptor)
    except (OSError, MixedMaterializationError) as error:
        raise MixedMaterializationError("private_output_root_invalid") from error
    private_root = _PrivateOutputRoot(root, descriptor, metadata.st_dev, metadata.st_ino)
    try:
        if (
            resolved != root
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or resolved.name != DEPLOYMENT_NAMESPACE
        ):
            raise MixedMaterializationError("private_output_root_invalid")
        private_root.revalidate()
        for forbidden in forbidden_roots:
            try:
                forbidden_resolved = forbidden.resolve(strict=True)
            except OSError as error:
                raise MixedMaterializationError("private_output_root_invalid") from error
            if (
                resolved == forbidden_resolved
                or resolved.is_relative_to(forbidden_resolved)
                or forbidden_resolved.is_relative_to(resolved)
            ):
                raise MixedMaterializationError("private_output_root_overlap")
        names = [private_root.name_for(output) for output in outputs]
        if len(set(names)) != len(names):
            raise MixedMaterializationError("output_path_collision")
        if validate_existing:
            for name in names:
                output_metadata = _private_artifact_status(private_root, name)
                if output_metadata is None:
                    raise MixedMaterializationError("private_output_artifact_invalid")
                _validate_private_artifact_status(output_metadata)
        private_root.revalidate()
        yield private_root
        private_root.revalidate()
    finally:
        os.close(descriptor)


def validate_private_output_root(
    root: Path,
    outputs: tuple[Path, ...],
    *,
    forbidden_roots: tuple[Path, ...],
    validate_existing: bool = True,
) -> Path:
    with _open_private_output_root(
        root,
        outputs,
        forbidden_roots=forbidden_roots,
        validate_existing=validate_existing,
    ):
        return root


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
    private_output_root: Path,
) -> dict[str, Any]:
    outputs_tuple = (sandoq_tasks, vmvm_tasks, sandoq_config, vmvm_config, receipt)
    with _open_private_output_root(
        private_output_root,
        outputs_tuple,
        forbidden_roots=(Path(__file__).resolve().parents[3], dataset),
        validate_existing=False,
    ) as private_root:
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
        if (
            _read_regular(source) != source_raw
            or _read_regular(sandoq_template) != sandoq_template_raw
            or _read_regular(vmvm_template) != vmvm_template_raw
            or verify_canonical_dataset(dataset) != resolved_dataset
        ):
            raise MixedMaterializationError("canonical_inputs_changed")
        outputs = [
            (sandoq_tasks, sandoq_task_payload),
            (vmvm_tasks, vmvm_task_payload),
            (sandoq_config, sandoq_config_payload),
            (vmvm_config, vmvm_config_payload),
            (receipt, _canonical_json(receipt_value())),
        ]
        publish_exclusive(private_root, outputs)
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
    private_output_root: Path,
) -> dict[str, Any]:
    with _open_private_output_root(
        private_output_root,
        (sandoq_tasks, vmvm_tasks, sandoq_config, vmvm_config, receipt),
        forbidden_roots=(Path(__file__).resolve().parents[3], dataset),
    ) as private_root:
        source_raw = _read_regular(source)
        if sha256(source_raw) != CANONICAL_SOURCE_SHA256:
            raise MixedMaterializationError("canonical_source_mismatch")
        resolved_dataset = verify_canonical_dataset(dataset)
        partition = derive_partition(source_raw, resolved_dataset)
        sandoq_task_payload = _task_payload(partition.sandoq)
        vmvm_task_payload = _task_payload(partition.vmvm)
        if (
            _read_private_artifact(private_root, sandoq_tasks) != sandoq_task_payload
            or _read_private_artifact(private_root, vmvm_tasks) != vmvm_task_payload
        ):
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
            _read_private_artifact(private_root, sandoq_config) != expected_sandoq_config
            or _read_private_artifact(private_root, vmvm_config) != expected_vmvm_config
        ):
            raise MixedMaterializationError("materialized_config_mismatch")
        receipt_raw = _read_private_artifact(private_root, receipt)
        if sha256(receipt_raw) != receipt_sha256 or receipt_raw != _canonical_json(receipt_value()):
            raise MixedMaterializationError("materialization_receipt_invalid")
        if _read_regular(source) != source_raw or verify_canonical_dataset(dataset) != resolved_dataset:
            raise MixedMaterializationError("canonical_inputs_changed")
    return {
        "sha256": receipt_sha256,
        "deployment_namespace": receipt_value()["deployment_namespace"],
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
    parser.add_argument("--private-output-root", type=Path, required=True)
    args = parser.parse_args()
    workflow = Path(__file__).resolve().parent
    canonical_source = workflow / "configs/eval/mobius_valid_tasks_2500.txt"
    template_dir = workflow / "configs/eval" / DEPLOYMENT_NAMESPACE
    canonical_sandoq_template = template_dir / "mobius_qwen_a95b_2500_sandoq.toml"
    canonical_vmvm_template = template_dir / "mobius_qwen_a95b_2500_vmvm_host.toml"
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
