from __future__ import annotations

import errno
import hashlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

import publish_qwen_pass_only_bundle_nfs as publisher
import pytest

REVIEWED_PUBLISHER_SHA256 = "abc3ff379029c32022bf848c2278c49144a1e90095b89461d6c3920d1b5e79e7"


def _write_private(path: Path, body: bytes) -> None:
    path.write_bytes(body)
    path.chmod(0o600)


def _bundle(tmp_path: Path) -> tuple[Path, Path, Path, str, str, bytes]:
    tmp_path.chmod(0o700)
    source = tmp_path / "source"
    parent = tmp_path / "destination-parent"
    destination = parent / "export"
    source.mkdir(mode=0o700)
    parent.mkdir(mode=0o700)
    (source / "train").mkdir(mode=0o700)
    (source / "validation").mkdir(mode=0o700)
    payloads = {
        "target-rendering-contract.json": b"target-contract\n",
        "task-split.json": b"task-split\n",
        "train/train.jsonl": b"train-row\n",
        "validation/train.jsonl": b"validation-row\n",
    }
    artifacts = {
        name: {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()} for name, body in payloads.items()
    }
    certificate_body = b"certificate\n"
    certificate_sha256 = hashlib.sha256(certificate_body).hexdigest()
    manifest_body = json.dumps(
        {
            "artifacts": artifacts,
            "certificate": {
                "artifact": {
                    "bytes": len(certificate_body),
                    "sha256": certificate_sha256,
                }
            },
            "kind": publisher.EXPECTED_KIND,
            "selection": "pass-only",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    for relative, body in payloads.items():
        _write_private(source / relative, body)
    _write_private(source / publisher.CERTIFICATE, certificate_body)
    _write_private(source / publisher.MANIFEST, manifest_body)
    return (
        source,
        parent,
        destination,
        hashlib.sha256(manifest_body).hexdigest(),
        certificate_sha256,
        manifest_body,
    )


def _install_nfs_link_mock(
    monkeypatch: pytest.MonkeyPatch,
    *,
    before_link: Callable[[int, int], None] | None = None,
    after_link: Callable[[int, int], None] | None = None,
    lose_reply: bool = False,
) -> None:
    real_link = os.link

    def link(
        source: str,
        destination_name: str,
        *,
        dst_dir_fd: int,
        follow_symlinks: bool,
    ) -> None:
        prefix = "/proc/self/fd/"
        assert source.startswith(prefix)
        source_descriptor = int(source.removeprefix(prefix))
        destination_descriptor = dst_dir_fd
        assert destination_name == publisher.MANIFEST
        assert follow_symlinks is True
        if before_link is not None:
            before_link(source_descriptor, destination_descriptor)
        source_metadata = os.fstat(source_descriptor)
        assert source_metadata.st_nlink == 1
        with pytest.raises(FileNotFoundError):
            os.stat(
                destination_name,
                dir_fd=destination_descriptor,
                follow_symlinks=False,
            )
        real_link(
            source,
            destination_name,
            dst_dir_fd=destination_descriptor,
            follow_symlinks=follow_symlinks,
        )
        published_metadata = os.stat(
            destination_name,
            dir_fd=destination_descriptor,
            follow_symlinks=False,
        )
        assert (published_metadata.st_dev, published_metadata.st_ino) == (
            source_metadata.st_dev,
            source_metadata.st_ino,
        )
        if after_link is not None:
            after_link(source_descriptor, destination_descriptor)
        if lose_reply:
            raise OSError(errno.ETIMEDOUT, "synthetic lost NFS reply")

    monkeypatch.setattr(publisher.os, "link", link)


def _publish(
    source: Path,
    destination: Path,
    manifest_sha256: str,
    certificate_sha256: str,
) -> dict[str, str]:
    return publisher.publish(
        source,
        destination,
        expected_manifest_sha256=manifest_sha256,
        expected_certificate_sha256=certificate_sha256,
    )


def test_reviewed_publisher_bytes_are_pinned() -> None:
    assert hashlib.sha256(Path(publisher.__file__).read_bytes()).hexdigest() == REVIEWED_PUBLISHER_SHA256


def test_nfs_publish_commits_exact_private_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, parent, destination, manifest_sha256, certificate_sha256, manifest_body = _bundle(tmp_path)
    _install_nfs_link_mock(monkeypatch)

    assert _publish(source, destination, manifest_sha256, certificate_sha256) == {"state": "published"}
    assert (destination / publisher.MANIFEST).read_bytes() == manifest_body
    assert not list(parent.glob(f".{destination.name}.manifest-*"))
    for path in destination.rglob("*"):
        metadata = path.lstat()
        if path.is_dir():
            assert metadata.st_mode & 0o777 == 0o700
        else:
            assert metadata.st_mode & 0o777 == 0o600
            assert metadata.st_nlink == 1


def test_destination_collision_preserves_existing_tree(tmp_path: Path) -> None:
    source, _parent, destination, manifest_sha256, certificate_sha256, _manifest = _bundle(tmp_path)
    destination.mkdir(mode=0o700)
    sentinel = destination / "sentinel"
    _write_private(sentinel, b"keep\n")

    with pytest.raises(publisher.PublishError, match="^publish_precommit_incomplete$"):
        _publish(source, destination, manifest_sha256, certificate_sha256)

    assert sentinel.read_bytes() == b"keep\n"
    assert sorted(path.name for path in destination.iterdir()) == ["sentinel"]


def test_precommit_failure_leaves_incomplete_tree_without_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _parent, destination, manifest_sha256, certificate_sha256, _manifest = _bundle(tmp_path)

    def fail_validation(*_args: object, **_kwargs: object) -> None:
        raise publisher.PublishError("synthetic_precommit_failure")

    monkeypatch.setattr(publisher, "_validate_payload_records", fail_validation)
    with pytest.raises(publisher.PublishError, match="^publish_precommit_incomplete$"):
        _publish(source, destination, manifest_sha256, certificate_sha256)

    assert destination.is_dir()
    assert not (destination / publisher.MANIFEST).exists()
    assert (destination / "train" / "train.jsonl").read_bytes() == b"train-row\n"


def test_commit_lost_reply_never_rolls_back_visible_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, parent, destination, manifest_sha256, certificate_sha256, manifest_body = _bundle(tmp_path)
    _install_nfs_link_mock(monkeypatch, lose_reply=True)

    with pytest.raises(publisher.PublishError, match="^publish_commit_indeterminate$"):
        _publish(source, destination, manifest_sha256, certificate_sha256)

    assert (destination / publisher.MANIFEST).read_bytes() == manifest_body
    assert (destination / "train" / "train.jsonl").read_bytes() == b"train-row\n"
    assert len(list(parent.glob(f".{destination.name}.manifest-*"))) == 1


def test_certificate_swap_after_authentication_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _parent, destination, manifest_sha256, certificate_sha256, _manifest = _bundle(tmp_path)
    real_copy = publisher._copy_payload

    def swap_then_copy(source_descriptor: int, destination_descriptor: int, *, root: bool = True) -> None:
        replacement = source / ".certificate-replacement"
        _write_private(replacement, b"untrusted-certificate\n")
        os.replace(replacement, source / publisher.CERTIFICATE)
        real_copy(source_descriptor, destination_descriptor, root=root)

    monkeypatch.setattr(publisher, "_copy_payload", swap_then_copy)
    with pytest.raises(publisher.PublishError, match="^publish_precommit_incomplete$"):
        _publish(source, destination, manifest_sha256, certificate_sha256)

    assert not (destination / publisher.MANIFEST).exists()


def test_postcommit_payload_mutation_is_indeterminate_and_retained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _parent, destination, manifest_sha256, certificate_sha256, manifest_body = _bundle(tmp_path)

    def mutate_payload(_source_descriptor: int, destination_descriptor: int) -> None:
        descriptor = os.open(
            "task-split.json",
            os.O_WRONLY | os.O_TRUNC | os.O_CLOEXEC,
            dir_fd=destination_descriptor,
        )
        try:
            os.write(descriptor, b"mutated\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    _install_nfs_link_mock(monkeypatch, after_link=mutate_payload)
    with pytest.raises(publisher.PublishError, match="^publish_commit_indeterminate$"):
        _publish(source, destination, manifest_sha256, certificate_sha256)

    assert (destination / publisher.MANIFEST).read_bytes() == manifest_body
    assert (destination / "task-split.json").read_bytes() == b"mutated\n"


def test_parent_relocation_during_commit_is_indeterminate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, parent, destination, manifest_sha256, certificate_sha256, manifest_body = _bundle(tmp_path)
    detached_parent = tmp_path / "detached-parent"

    def relocate_parent(_source_descriptor: int, _destination_descriptor: int) -> None:
        parent.rename(detached_parent)
        parent.mkdir(mode=0o700)

    _install_nfs_link_mock(monkeypatch, before_link=relocate_parent)
    with pytest.raises(publisher.PublishError, match="^publish_commit_indeterminate$"):
        _publish(source, destination, manifest_sha256, certificate_sha256)

    assert not destination.exists()
    assert (detached_parent / "export" / publisher.MANIFEST).read_bytes() == manifest_body


def test_cli_redacts_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "private-source-path"

    def fail(**_kwargs: object) -> dict[str, str]:
        raise RuntimeError(secret)

    monkeypatch.setattr(publisher, "publish", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publisher",
            "--source",
            "/private/source",
            "--destination",
            "/private/destination",
            "--expected-manifest-sha256",
            "a" * 64,
            "--expected-certificate-sha256",
            "b" * 64,
        ],
    )

    with pytest.raises(SystemExit) as raised:
        publisher.main()

    captured = capsys.readouterr()
    assert str(raised.value) == "publish_operation_failed"
    assert secret not in captured.out
    assert secret not in captured.err
