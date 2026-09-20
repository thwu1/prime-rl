from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import materialize_qwen_provider_union as union
import pytest


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _task(root: Path, name: str, *, compose: bool = False, public: bool = False) -> None:
    task = root / name
    (task / "environment").mkdir(parents=True)
    mode = "public" if public else "no-network"
    (task / "task.toml").write_text(f'[environment]\nnetwork_mode = "{mode}"\n')
    if compose:
        (task / "environment" / "compose.yaml").write_text("services = {}\n")


def _templates(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    common = (
        "num_tasks = 2500\n"
        "max_concurrent = 64\n"
        "multiplex = 64\n"
        "max_connections = 32\n"
        "max_keepalive_connections = 32\n"
        "[sampling]\n"
        "[taskset]\n"
        'task_file = "user/tianhaowu/terminal_bench_vmvm/configs/eval/'
        'mobius_valid_tasks_2500.txt"\n'
        f'task_file_sha256 = "{union.CANONICAL_SOURCE_SHA256}"\n'
    )
    sandoq = tmp_path / "sandoq.toml"
    vmvm = tmp_path / "vmvm.toml"
    sandoq.write_text(common + 'reasoning_effort = "high"\n')
    vmvm.write_text(common + 'reasoning_effort = "high"\nenable_compose = true\n')
    monkeypatch.setattr(union, "CANONICAL_SANDOQ_TEMPLATE_SHA256", _sha(sandoq.read_bytes()))
    monkeypatch.setattr(union, "CANONICAL_VMVM_TEMPLATE_SHA256", _sha(vmvm.read_bytes()))
    return sandoq, vmvm


def _inputs(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    members = ("opaque-a", "opaque-b", "opaque-c", "opaque-d")
    for member in members[:-1]:
        _task(dataset, member)
    _task(dataset, members[-1], compose=True)
    source = tmp_path / "source.txt"
    source.write_text("".join(f"{member}\n" for member in members))
    monkeypatch.setattr(union, "CANONICAL_SOURCE_COUNT", 4)
    monkeypatch.setattr(union, "SANDOQ_COUNT", 3)
    monkeypatch.setattr(union, "CANONICAL_SOURCE_SHA256", _sha(source.read_bytes()))
    monkeypatch.setattr(union, "verify_canonical_dataset", lambda path: path.resolve(strict=True))
    sandoq_template, vmvm_template = _templates(tmp_path, monkeypatch)
    output_root = tmp_path / union.DEPLOYMENT_NAMESPACE
    output_root.mkdir(mode=0o700)
    output_root.chmod(0o700)
    return {
        "source": source,
        "dataset": dataset,
        "sandoq_template": sandoq_template,
        "vmvm_template": vmvm_template,
        "sandoq_tasks": output_root / "sandoq.txt",
        "vmvm_tasks": output_root / "vmvm.txt",
        "sandoq_config": output_root / "sandoq.toml",
        "vmvm_config": output_root / "vmvm.toml",
        "receipt": output_root / "receipt.json",
        "private_output_root": output_root,
    }


def test_materializes_private_disjoint_exhaustive_partition(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)

    result = union.materialize(**paths)

    assert result == {"state": "materialized", "source_count": 4, "sandoq_count": 3, "vmvm_count": 1}
    receipt_raw = paths["receipt"].read_bytes()
    receipt = json.loads(receipt_raw)
    assert receipt["partition"] == {
        "compose_count": 1,
        "disjoint": True,
        "exhaustive": True,
        "no_network_count": 4,
        "sandoq_count": 3,
        "vmvm_count": 1,
    }
    assert receipt["deployment_namespace"] == "shared_qwen38_2p4t"
    # Neither member names nor hashes of the one-member private file are public.
    assert all(member.encode() not in receipt_raw for member in ("opaque-a", "opaque-b", "opaque-c", "opaque-d"))
    assert _sha(paths["vmvm_tasks"].read_bytes()).encode() not in receipt_raw
    validation = union.validate_materialization(
        **paths,
        receipt_sha256=_sha(receipt_raw),
    )
    assert validation["partition"]["sandoq_count"] == 3
    assert validation["partition"]["vmvm_count"] == 1
    assert "enable_compose = true" in paths["vmvm_config"].read_text()
    assert 'reasoning_effort = "high"' in paths["vmvm_config"].read_text()
    for name in ("sandoq_tasks", "vmvm_tasks", "sandoq_config", "vmvm_config", "receipt"):
        metadata = paths[name].stat()
        assert metadata.st_uid == os.getuid()
        assert metadata.st_nlink == 1
        assert metadata.st_mode & 0o777 == 0o600


def test_validation_rejects_partition_overlap_or_omission(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    union.materialize(**paths)
    paths["sandoq_tasks"].write_bytes(paths["sandoq_tasks"].read_bytes() + paths["vmvm_tasks"].read_bytes())

    with pytest.raises(union.MixedMaterializationError, match="^materialized_partition_mismatch$"):
        union.validate_materialization(
            **paths,
            receipt_sha256=_sha(paths["receipt"].read_bytes()),
        )


def test_partition_rejects_second_compose_member(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    (paths["dataset"] / "opaque-a" / "environment" / "compose.yml").write_text("services = {}\n")

    with pytest.raises(union.MixedMaterializationError, match="^canonical_partition_cardinality_mismatch$"):
        union.materialize(**paths)


def test_partition_rejects_public_network_member(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    (paths["dataset"] / "opaque-a" / "task.toml").write_text('[environment]\nnetwork_mode = "public"\n')

    with pytest.raises(union.MixedMaterializationError, match="^task_network_not_isolated$"):
        union.materialize(**paths)


def test_partition_rejects_symlinked_compose_artifact(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    compose = paths["dataset"] / "opaque-d" / "environment" / "compose.yaml"
    body = compose.read_bytes()
    compose.unlink()
    target = tmp_path / "outside-compose"
    target.write_bytes(body)
    compose.symlink_to(target)

    with pytest.raises(union.MixedMaterializationError, match="^compose_artifact_invalid$"):
        union.materialize(**paths)


def test_publish_is_fail_closed_on_existing_output(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    paths["receipt"].write_text("preexisting\n")

    with pytest.raises(union.MixedMaterializationError, match="^outputs_require_fresh_namespace$"):
        union.materialize(**paths)
    assert paths["receipt"].read_text() == "preexisting\n"
    assert not paths["sandoq_tasks"].exists()


def test_publish_rejects_symlink_inserted_after_root_validation(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.write_text("unchanged\n")
    publish = union.publish_exclusive

    def insert_symlink(root, outputs):
        paths["receipt"].symlink_to(outside)
        return publish(root, outputs)

    monkeypatch.setattr(union, "publish_exclusive", insert_symlink)
    with pytest.raises(union.MixedMaterializationError, match="^outputs_require_fresh_namespace$"):
        union.materialize(**paths)
    assert outside.read_text() == "unchanged\n"
    assert not paths["sandoq_tasks"].exists()


def test_publish_rejects_private_root_swap(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    original_root = paths["private_output_root"]
    relocated_root = tmp_path / "relocated-private-root"
    publish = union.publish_exclusive

    def swap_root(root, outputs):
        original_root.rename(relocated_root)
        original_root.mkdir(mode=0o700)
        return publish(root, outputs)

    monkeypatch.setattr(union, "publish_exclusive", swap_root)
    with pytest.raises(union.MixedMaterializationError, match="^private_output_root_changed$"):
        union.materialize(**paths)
    assert not any(original_root.iterdir())
    assert not any(relocated_root.iterdir())


def test_publish_removes_partial_temporary_on_write_failure(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    real_fsync = union.os.fsync
    calls = 0

    def fail_first_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected write failure")
        real_fsync(descriptor)

    monkeypatch.setattr(union.os, "fsync", fail_first_fsync)
    with pytest.raises(OSError, match="injected write failure"):
        union.materialize(**paths)

    assert not any(Path(paths["private_output_root"]).iterdir())


def test_validation_rejects_private_root_swap_between_reads(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    union.materialize(**paths)
    receipt_sha256 = _sha(paths["receipt"].read_bytes())
    original_root = paths["private_output_root"]
    relocated_root = tmp_path / "relocated-private-root"
    read_private = union._read_private_artifact
    reads = 0

    def swap_after_first_read(root, path):
        nonlocal reads
        body = read_private(root, path)
        reads += 1
        if reads == 1:
            original_root.rename(relocated_root)
            original_root.mkdir(mode=0o700)
        return body

    monkeypatch.setattr(union, "_read_private_artifact", swap_after_first_read)
    with pytest.raises(union.MixedMaterializationError, match="^private_output_root_changed$"):
        union.validate_materialization(**paths, receipt_sha256=receipt_sha256)
    assert not any(original_root.iterdir())


def test_validation_rejects_artifact_name_swap_during_fd_read(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    union.materialize(**paths)
    receipt_sha256 = _sha(paths["receipt"].read_bytes())
    target = paths["sandoq_tasks"]
    target_identity = (target.stat().st_dev, target.stat().st_ino)
    replacement = target.parent / "replaced-sandoq.txt"
    read = union.os.read
    swapped = False

    def swap_name(descriptor: int, size: int) -> bytes:
        nonlocal swapped
        chunk = read(descriptor, size)
        metadata = os.fstat(descriptor)
        if chunk and not swapped and (metadata.st_dev, metadata.st_ino) == target_identity:
            swapped = True
            target.rename(replacement)
            target.write_text("synthetic-replacement\n")
            target.chmod(0o600)
        return chunk

    monkeypatch.setattr(union.os, "read", swap_name)
    with pytest.raises(union.MixedMaterializationError, match="^private_output_artifact_changed$"):
        union.validate_materialization(**paths, receipt_sha256=receipt_sha256)
    assert swapped


def test_network_phase_ignores_legacy_network_and_allow_internet_keys() -> None:
    assert (
        union._network_policy(
            {"network": "public", "allow_internet": True},
            default="no-network",
            phase_override=True,
        )
        == "no-network"
    )


def test_network_phase_rejects_allowed_hosts_presence_even_when_empty() -> None:
    with pytest.raises(union.MixedMaterializationError, match="^task_network_contract_invalid$"):
        union._network_policy(
            {"allowed_hosts": []},
            default="no-network",
            phase_override=True,
        )


def test_private_output_root_rejects_group_writable_directory(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root.chmod(0o770)

    with pytest.raises(union.MixedMaterializationError, match="^private_output_root_invalid$"):
        union.validate_private_output_root(
            root,
            (root / "one",),
            forbidden_roots=(tmp_path / "unrelated",),
        )


def test_private_output_root_rejects_symlink_and_forbidden_overlap(tmp_path: Path) -> None:
    forbidden = tmp_path / union.DEPLOYMENT_NAMESPACE
    forbidden.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(forbidden, target_is_directory=True)

    with pytest.raises(union.MixedMaterializationError, match="^private_output_root_invalid$"):
        union.validate_private_output_root(
            alias,
            (alias / "one",),
            forbidden_roots=(forbidden,),
        )
    with pytest.raises(union.MixedMaterializationError, match="^private_output_root_overlap$"):
        union.validate_private_output_root(
            forbidden,
            (forbidden / "one",),
            forbidden_roots=(forbidden,),
        )


def test_private_output_root_rejects_output_outside_boundary(tmp_path: Path) -> None:
    root = tmp_path / union.DEPLOYMENT_NAMESPACE
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir(mode=0o700)

    with pytest.raises(union.MixedMaterializationError, match="^private_output_path_invalid$"):
        union.validate_private_output_root(
            root,
            (other / "one",),
            forbidden_roots=(unrelated,),
        )


def test_private_output_root_requires_deployment_namespace(tmp_path: Path) -> None:
    root = tmp_path / "ambiguous"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir(mode=0o700)

    with pytest.raises(union.MixedMaterializationError, match="^private_output_root_invalid$"):
        union.validate_private_output_root(
            root,
            (root / "one",),
            forbidden_roots=(unrelated,),
        )


@pytest.mark.parametrize("mode", [0o644, 0o640])
def test_private_output_root_rejects_exposed_existing_artifact(tmp_path: Path, mode: int) -> None:
    root = tmp_path / union.DEPLOYMENT_NAMESPACE
    root.mkdir(mode=0o700)
    output = root / "private.json"
    output.write_text("{}\n")
    output.chmod(mode)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir(mode=0o700)

    with pytest.raises(union.MixedMaterializationError, match="^private_output_artifact_invalid$"):
        union.validate_private_output_root(
            root,
            (output,),
            forbidden_roots=(unrelated,),
        )


def test_private_output_root_rejects_hardlinked_existing_artifact(tmp_path: Path) -> None:
    root = tmp_path / union.DEPLOYMENT_NAMESPACE
    root.mkdir(mode=0o700)
    output = root / "private.json"
    output.write_text("{}\n")
    output.chmod(0o600)
    os.link(output, tmp_path / "alias.json")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir(mode=0o700)

    with pytest.raises(union.MixedMaterializationError, match="^private_output_artifact_invalid$"):
        union.validate_private_output_root(
            root,
            (output,),
            forbidden_roots=(unrelated,),
        )
