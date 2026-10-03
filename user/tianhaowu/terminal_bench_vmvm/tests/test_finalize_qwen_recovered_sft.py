from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
from dataclasses import replace
from pathlib import Path

import export_sft as exporter
import finalize_qwen_recovered_sft as finalizer
import pytest

from prime_rl.trainer.sft import export_preflight


def _write_private(path: Path, value: bytes | dict) -> exporter.FileArtifact:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode() + b"\n"
    path.write_bytes(body)
    path.chmod(0o600)
    return exporter.FileArtifact(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())


def _artifact(value: exporter.FileArtifact) -> dict[str, int | str]:
    return value.as_dict()


def _path_artifact(path: Path, value: exporter.FileArtifact) -> dict[str, int | str]:
    return {**value.as_dict(), "path": str(path)}


def _node(*, finish_reason: str = "stop") -> dict:
    return {
        "parent": None,
        "sampled": True,
        "finish_reason": finish_reason,
        "message": {
            "role": "assistant",
            "content": "synthetic answer",
            "reasoning_content": "synthetic reasoning",
        },
    }


def _trace(index: int, slug: str, outcome: str) -> dict:
    reward = 1.0 if outcome == "positive" else 0.0
    return {
        "id": f"synthetic-trace-{index}",
        "task": {"idx": index, "name": slug, "slug": slug},
        "nodes": [] if outcome == "error" else [_node(finish_reason="length" if outcome == "zero" else "stop")],
        "rewards": {"reward": reward},
        "errors": ["synthetic"] if outcome == "error" else [],
    }


def _fixture(
    tmp_path: Path,
    *,
    stale_task_indices: bool = False,
) -> tuple[finalizer.RecoveredSFTOptions, tuple[str, ...]]:
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    source.chmod(0o700)
    task_file = tmp_path / "canonical.tasks.txt"
    task_file_artifact = _write_private(task_file, b"task-a\ntask-b\ntask-c\n")
    rows = [
        _trace(0, "task-a", "positive"),
        _trace(1, "task-b", "zero"),
        _trace(2, "task-c", "error"),
    ]
    if stale_task_indices:
        for row in rows:
            row["task"]["idx"] = 2 - row["task"]["idx"]
    results_body = b"".join(json.dumps(row, sort_keys=True).encode() + b"\n" for row in rows)
    results_path = source / finalizer.RESULTS_FILENAME
    results_artifact = _write_private(results_path, results_body)
    selection_sha256 = "1" * 64

    retry_path = tmp_path / "retry.json"
    retry_artifact = _write_private(
        retry_path,
        {
            "schema_version": 1,
            "kind": finalizer.RETRY_KIND,
            "state": "passed",
            "selection_contract_sha256": selection_sha256,
        },
    )
    superseding_path = tmp_path / "superseding.json"
    superseding_artifact = _write_private(
        superseding_path,
        {
            "schema_version": 1,
            "kind": finalizer.SUPERSEDING_KIND,
            "state": "passed",
            "selection_contract_sha256": selection_sha256,
            "predecessor": {"sha256": retry_artifact.sha256},
        },
    )
    outcomes = {"error": 1, "positive": 1, "zero": 1}
    recovered_path = source / finalizer.RECOVERED_CERTIFICATE_FILENAME
    recovered_artifact = _write_private(
        recovered_path,
        {
            "schema_version": 1,
            "kind": finalizer.RECOVERED_KIND,
            "state": "passed",
            "mode": "unfiltered",
            "coverage": {
                "canonical_order": True,
                "exact": True,
                "exhaustive": True,
                "task_count": 3,
                "universe_task_file_sha256": task_file_artifact.sha256,
            },
            "lineage": {
                "selection_contract_sha256": selection_sha256,
                "superseding_certificate_sha256": superseding_artifact.sha256,
            },
            "outcomes": outcomes,
            "results": _path_artifact(results_path, results_artifact),
        },
    )
    merge_path = source / finalizer.MERGE_FILENAME
    merge_artifact = _write_private(
        merge_path,
        {
            "schema_version": 1,
            "kind": finalizer.MERGE_KIND,
            "state": "ready",
            "mode": "unfiltered",
            "sft_selection": None,
            "outcomes": outcomes,
            "lineage": {
                "selection_contract_sha256": selection_sha256,
                "superseding_certificate_sha256": superseding_artifact.sha256,
            },
            "artifacts": {
                "results": _path_artifact(results_path, results_artifact),
                "certificate": _path_artifact(recovered_path, recovered_artifact),
            },
        },
    )
    postrun_path = tmp_path / "postrun.json"
    postrun_artifact = _write_private(
        postrun_path,
        {
            "schema_version": 1,
            "kind": finalizer.POSTRUN_KIND,
            "state": "certified",
            "mode": "unfiltered",
            "task_count": 3,
            "outcomes": outcomes,
            "artifact": {
                "results": _artifact(results_artifact),
                "certificate": _artifact(recovered_artifact),
                "manifest": _artifact(merge_artifact),
            },
            "lineage": {
                "selection_contract_sha256": selection_sha256,
                "retry_run_certificate_sha256": retry_artifact.sha256,
                "superseding_certificate_sha256": superseding_artifact.sha256,
            },
        },
    )
    package_path = tmp_path / "package" / "manifest.json"
    package_artifact = _write_private(
        package_path,
        {
            "schema_version": 1,
            "kind": finalizer.PACKAGE_KIND,
            "package_version": "v6",
            "state": "ready",
            "coverage": {"canonical_tasks": 3, "outcomes": outcomes},
            "inputs": {
                "results": {**_artifact(results_artifact), "rows": 3},
                "recovered_certificate": _artifact(recovered_artifact),
                "recovered_merge_manifest": _artifact(merge_artifact),
                "retry_certificate": _artifact(retry_artifact),
                "superseding_certificate": _artifact(superseding_artifact),
                "postrun_receipt": _artifact(postrun_artifact),
            },
            "lineage": {
                "canonical_task_file_sha256": task_file_artifact.sha256,
                "selection_contract_sha256": selection_sha256,
                "retry_certificate_sha256": retry_artifact.sha256,
                "superseding_certificate_sha256": superseding_artifact.sha256,
                "recovered_certificate_sha256": recovered_artifact.sha256,
                "recovered_merge_manifest_sha256": merge_artifact.sha256,
                "postrun_receipt_sha256": postrun_artifact.sha256,
            },
        },
    )
    output_root = tmp_path / "outputs"
    output_root.mkdir()
    output_root.chmod(0o700)
    options = finalizer.RecoveredSFTOptions(
        project_dir=project,
        expected_project_revision="2" * 40,
        expected_finalizer_sha256="3" * 64,
        package_manifest=package_path,
        expected_package_manifest_sha256=package_artifact.sha256,
        source_dir=source,
        expected_results_sha256=results_artifact.sha256,
        expected_merge_manifest_sha256=merge_artifact.sha256,
        expected_recovered_certificate_sha256=recovered_artifact.sha256,
        retry_certificate=retry_path,
        expected_retry_certificate_sha256=retry_artifact.sha256,
        superseding_certificate=superseding_path,
        expected_superseding_certificate_sha256=superseding_artifact.sha256,
        postrun_receipt=postrun_path,
        expected_postrun_receipt_sha256=postrun_artifact.sha256,
        canonical_task_file=task_file,
        expected_canonical_task_file_sha256=task_file_artifact.sha256,
        taskset_id="synthetic-taskset",
        dataset_revision="4" * 40,
        output_root=output_root,
        output_dir=output_root / "export-a",
        expected_count=3,
        expected_positive=1,
        expected_zero=1,
        expected_error=1,
        expected_selected_positive=1,
        expected_strict_failures=2,
        validation_permyriad=500,
        split_salt="synthetic-split-v1",
    )
    return options, ("task-a", "task-b", "task-c")


def _code(_project: Path, revision: str, digest: str) -> dict:
    return {
        "project_revision": revision,
        "files": {
            "export_sft.py": {"bytes": 1, "sha256": "5" * 64},
            finalizer.Path(finalizer.__file__).name: {"bytes": 1, "sha256": digest},
        },
    }


def _archive(package: finalizer.PinnedJSON, _verifier: Path) -> finalizer.ArchiveBinding:
    chunks = package.path.parent / "test-chunks"
    chunks.mkdir(exist_ok=True)
    chunks.chmod(0o700)
    chunk = chunks / "archive.part"
    if not chunk.exists():
        _write_private(chunk, b"synthetic archive")
    sums = package.path.parent / "test-SHA256SUMS"
    if not sums.exists():
        _write_private(sums, b"synthetic sums\n")
    chunk_artifact = exporter._fingerprint_stable_file(chunk, required_mode=0o600)
    sums_artifact = exporter._fingerprint_stable_file(sums, required_mode=0o600)
    return finalizer.ArchiveBinding(
        archive=chunk_artifact,
        sha256sums_path=sums,
        sha256sums=sums_artifact,
        chunks=((chunk, chunk_artifact),),
    )


def _published_artifacts(root: Path) -> dict[str, exporter.FileArtifact]:
    relatives = {
        "manifest.json",
        finalizer.RECEIPT_FILENAME,
        "task-split.json",
        exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "train/train.jsonl",
        "validation/train.jsonl",
    }
    return {relative: exporter._fingerprint_stable_file(root / relative, required_mode=0o600) for relative in relatives}


def _canonical_package(tmp_path: Path) -> finalizer.PinnedJSON:
    root = tmp_path / "canonical-package"
    chunks = root / "chunks"
    chunks.mkdir(parents=True)
    members = []
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for index in range(7):
            name = f"package/member-{index}.json"
            body = json.dumps({"index": index}, sort_keys=True).encode() + b"\n"
            info = tarfile.TarInfo(name)
            info.size = len(body)
            info.mode = 0o600
            info.uid = 0
            info.gid = 0
            info.mtime = 0
            archive.addfile(info, io.BytesIO(body))
            members.append({"name": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
    compressed = subprocess.run(
        ["/usr/bin/zstd", "-19", "--long=31", "-q", "-c"],
        input=stream.getvalue(),
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    archive_name = "synthetic.tar.zst"
    chunk_name = f"{archive_name}.000.part"
    chunk_artifact = _write_private(chunks / chunk_name, compressed)
    _write_private(root / "README.md", b"synthetic\n")
    _write_private(root / "SHA256SUMS", f"{chunk_artifact.sha256}  {chunk_name}\n".encode())
    value = {
        "archive": {
            "bytes": len(compressed),
            "compression": "zstd-19-long31",
            "member_count": 7,
            "members": members,
            "name": archive_name,
            "sha256": hashlib.sha256(compressed).hexdigest(),
        },
        "chunk_bytes": 95_000_000,
        "chunks": [{"bytes": len(compressed), "name": chunk_name, "sha256": chunk_artifact.sha256}],
    }
    manifest = root / "manifest.json"
    artifact = _write_private(manifest, value)
    return finalizer.PinnedJSON(path=manifest, artifact=artifact, value=value)


def _validator(trace: dict, **kwargs):
    assert kwargs["require_exact_provider_json"] is True
    if trace["rewards"]["reward"] == 0:
        raise exporter.ExportError("sampled_finish_reason_length")
    return trace["nodes"], [
        {
            "type": "function",
            "function": {
                "name": "terminal",
                "description": "synthetic",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_materializes_private_deterministic_pass_only_export(tmp_path: Path) -> None:
    options, markers = _fixture(tmp_path)
    source_hashes = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            options.package_manifest,
            options.source_dir / finalizer.RESULTS_FILENAME,
            options.source_dir / finalizer.MERGE_FILENAME,
            options.source_dir / finalizer.RECOVERED_CERTIFICATE_FILENAME,
            options.retry_certificate,
            options.superseding_certificate,
            options.postrun_receipt,
            options.canonical_task_file,
        )
    }
    first = finalizer.finalize_recovered_sft(
        options,
        repository_validator=_code,
        trace_validator=_validator,
        archive_validator=_archive,
        identity_validator=lambda _options: None,
    )
    assert first["state"] == "finalized"
    assert first["selected_positive_traces"] == 1
    output = options.output_dir
    manifest = json.loads((output / "manifest.json").read_bytes())
    receipt = json.loads((output / finalizer.RECEIPT_FILENAME).read_bytes())
    assert manifest["source_validation"]["require_exact_provider_json"] is True
    assert manifest["exporter"]["file_sha256"] == "5" * 64
    assert receipt["code"]["files"][finalizer.Path(finalizer.__file__).name]["sha256"] == "3" * 64
    assert receipt["counts"]["error_traces"] == 1
    assert receipt["counts"]["zero_traces"] == 1
    assert receipt["counts"]["strict_invalid_positive_traces"] == 0
    assert receipt["counts"]["strict_failure_traces"] == 2
    assert receipt["problem_counts"] == {"sampled_finish_reason_length": 1}
    assert receipt["set_commitments"]["omitted"]["count"] == 2
    assert receipt["set_commitments"]["selected"]["count"] == 1
    preflight_binding = export_preflight._load_export_binding(output, first["manifest_sha256"])
    assert preflight_binding.source_validation["require_exact_provider_json"] is True
    assert set(preflight_binding.artifacts) == export_preflight.REQUIRED_EXPORT_ARTIFACTS
    for path in output.rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
    private_rendering = json.dumps({"summary": first, "receipt": receipt}, sort_keys=True)
    assert all(marker not in private_rendering for marker in markers)
    assert source_hashes == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_hashes}

    options_b = replace(options, output_dir=options.output_root / "export-b")
    second = finalizer.finalize_recovered_sft(
        options_b,
        repository_validator=_code,
        trace_validator=_validator,
        archive_validator=_archive,
        identity_validator=lambda _options: None,
    )
    assert first == second
    for relative in ("manifest.json", finalizer.RECEIPT_FILENAME, "train/train.jsonl", "validation/train.jsonl"):
        assert (options.output_dir / relative).read_bytes() == (options_b.output_dir / relative).read_bytes()


def test_positive_validation_failure_is_fail_closed_and_atomic(tmp_path: Path) -> None:
    options, _markers = _fixture(tmp_path)

    def reject_positive(trace: dict, **kwargs):
        assert kwargs["require_exact_provider_json"] is True
        raise exporter.ExportError("trace_validation_failed")

    with pytest.raises(finalizer.RecoveredSFTError, match="positive_trace_not_trainable"):
        finalizer.finalize_recovered_sft(
            options,
            repository_validator=_code,
            trace_validator=reject_positive,
            archive_validator=_archive,
            identity_validator=lambda _options: None,
        )
    assert not options.output_dir.exists()
    assert not tuple(options.output_root.iterdir())


def test_certified_opaque_slug_ignores_stale_evaluator_index(tmp_path: Path) -> None:
    options, _markers = _fixture(tmp_path, stale_task_indices=True)
    summary = finalizer.finalize_recovered_sft(
        options,
        repository_validator=_code,
        trace_validator=_validator,
        archive_validator=_archive,
        identity_validator=lambda _options: None,
    )
    assert summary["state"] == "finalized"
    assert summary["selected_positive_traces"] == 1


def test_package_manifest_digest_tamper_is_rejected(tmp_path: Path) -> None:
    options, _markers = _fixture(tmp_path)
    options.package_manifest.write_bytes(options.package_manifest.read_bytes() + b" ")
    options.package_manifest.chmod(0o600)
    with pytest.raises(finalizer.RecoveredSFTError, match="package_manifest_invalid_digest_mismatch"):
        finalizer.finalize_recovered_sft(
            options,
            repository_validator=_code,
            trace_validator=_validator,
            archive_validator=_archive,
            identity_validator=lambda _options: None,
        )
    assert not options.output_dir.exists()


def test_publish_race_never_replaces_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, _markers = _fixture(tmp_path)
    sentinel = b"pre-existing destination\n"

    def unsupported(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EINVAL, "unsupported")

    def race_archive(package: finalizer.PinnedJSON, verifier: Path) -> finalizer.ArchiveBinding:
        binding = _archive(package, verifier)
        options.output_dir.mkdir(mode=0o700)
        (options.output_dir / "sentinel").write_bytes(sentinel)
        return binding

    monkeypatch.setattr(finalizer.migration, "_rename_noreplace", unsupported)
    with pytest.raises(finalizer.RecoveredSFTError, match="output_already_exists"):
        finalizer.finalize_recovered_sft(
            options,
            repository_validator=_code,
            trace_validator=_validator,
            archive_validator=race_archive,
            identity_validator=lambda _options: None,
        )
    assert (options.output_dir / "sentinel").read_bytes() == sentinel
    assert sorted(path.name for path in options.output_root.iterdir()) == [options.output_dir.name]


def test_unsupported_noreplace_uses_validated_marker_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, _markers = _fixture(tmp_path)

    def unsupported(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EINVAL, "unsupported")

    monkeypatch.setattr(finalizer.migration, "_rename_noreplace", unsupported)
    summary = finalizer.finalize_recovered_sft(
        options,
        repository_validator=_code,
        trace_validator=_validator,
        archive_validator=_archive,
        identity_validator=lambda _options: None,
    )
    assert summary["state"] == "finalized"
    assert not os.path.lexists(options.output_dir / finalizer.direct.MIGRATION_INCOMPLETE_FILENAME)
    assert sorted(path.name for path in options.output_root.iterdir()) == [options.output_dir.name]
    binding = export_preflight._load_export_binding(options.output_dir, summary["manifest_sha256"])
    assert binding.source_validation["require_exact_provider_json"] is True


def test_fallback_validation_failure_removes_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, _markers = _fixture(tmp_path)
    real_validate = finalizer._validate_published_output

    def unsupported(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EINVAL, "unsupported")

    def reject(path: Path, allow_incomplete: bool, expected: dict) -> None:
        real_validate(path, allow_incomplete, expected)
        raise finalizer.RecoveredSFTError("synthetic_validation_failure")

    monkeypatch.setattr(finalizer.migration, "_rename_noreplace", unsupported)
    monkeypatch.setattr(finalizer, "_validate_published_output", reject)
    with pytest.raises(finalizer.RecoveredSFTError, match="^synthetic_validation_failure$"):
        finalizer.finalize_recovered_sft(
            options,
            repository_validator=_code,
            trace_validator=_validator,
            archive_validator=_archive,
            identity_validator=lambda _options: None,
        )
    assert not os.path.lexists(options.output_dir)
    assert not tuple(options.output_root.iterdir())


def test_fallback_crash_leaves_marker_that_preflight_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, _markers = _fixture(tmp_path)
    real_validate = finalizer._validate_published_output

    def unsupported(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EINVAL, "unsupported")

    def crash(path: Path, allow_incomplete: bool, expected: dict) -> None:
        real_validate(path, allow_incomplete, expected)
        raise KeyboardInterrupt

    monkeypatch.setattr(finalizer.migration, "_rename_noreplace", unsupported)
    monkeypatch.setattr(finalizer, "_validate_published_output", crash)
    with pytest.raises(KeyboardInterrupt):
        finalizer.finalize_recovered_sft(
            options,
            repository_validator=_code,
            trace_validator=_validator,
            archive_validator=_archive,
            identity_validator=lambda _options: None,
        )
    marker = options.output_dir / export_preflight.INCOMPLETE_PUBLICATION_MARKER
    assert marker.is_file()
    manifest_sha256 = hashlib.sha256((options.output_dir / "manifest.json").read_bytes()).hexdigest()
    with pytest.raises(export_preflight.SFTPreflightError, match="^export_publication_incomplete$"):
        export_preflight._load_export_binding(options.output_dir, manifest_sha256)


@pytest.mark.parametrize("marker_kind", ["regular", "symlink"])
def test_preflight_rejects_incomplete_publication_marker(tmp_path: Path, marker_kind: str) -> None:
    options, _markers = _fixture(tmp_path)
    summary = finalizer.finalize_recovered_sft(
        options,
        repository_validator=_code,
        trace_validator=_validator,
        archive_validator=_archive,
        identity_validator=lambda _options: None,
    )
    assert export_preflight.INCOMPLETE_PUBLICATION_MARKER == finalizer.direct.MIGRATION_INCOMPLETE_FILENAME
    marker = options.output_dir / export_preflight.INCOMPLETE_PUBLICATION_MARKER
    if marker_kind == "regular":
        _write_private(marker, b"incomplete\n")
    else:
        marker.symlink_to("missing-marker-target")
    with pytest.raises(export_preflight.SFTPreflightError, match="^export_publication_incomplete$"):
        export_preflight._load_export_binding(options.output_dir, summary["manifest_sha256"])


@pytest.mark.parametrize("replacement", ["symlink", "fifo"])
def test_published_output_validation_rejects_non_regular_artifact(tmp_path: Path, replacement: str) -> None:
    options, _markers = _fixture(tmp_path)
    finalizer.finalize_recovered_sft(
        options,
        repository_validator=_code,
        trace_validator=_validator,
        archive_validator=_archive,
        identity_validator=lambda _options: None,
    )
    expected = _published_artifacts(options.output_dir)
    target = options.output_dir / "task-split.json"
    target.unlink()
    if replacement == "symlink":
        target.symlink_to("manifest.json")
    else:
        os.mkfifo(target, mode=0o600)
    with pytest.raises(finalizer.RecoveredSFTError, match="^published_artifact_mode_invalid$"):
        finalizer._validate_published_output(options.output_dir, False, expected)


@pytest.mark.parametrize("protected", ["project", "package"])
def test_output_cannot_overlap_immutable_input_roots(tmp_path: Path, protected: str) -> None:
    options, _markers = _fixture(tmp_path)
    root = options.project_dir if protected == "project" else options.package_manifest.parent
    options = replace(options, output_root=root, output_dir=root / "export")
    with pytest.raises(finalizer.RecoveredSFTError, match="path_boundaries_overlap"):
        finalizer.finalize_recovered_sft(
            options,
            repository_validator=_code,
            trace_validator=_validator,
            archive_validator=_archive,
            identity_validator=lambda _options: None,
        )
    assert not options.output_dir.exists()


def test_production_identity_is_literal_and_fail_closed(tmp_path: Path) -> None:
    options, _markers = _fixture(tmp_path)
    production = replace(
        options,
        expected_package_manifest_sha256=finalizer.PINNED_PACKAGE_MANIFEST_SHA256,
        expected_results_sha256=finalizer.PINNED_RESULTS_SHA256,
        expected_merge_manifest_sha256=finalizer.PINNED_MERGE_MANIFEST_SHA256,
        expected_recovered_certificate_sha256=finalizer.PINNED_RECOVERED_CERTIFICATE_SHA256,
        expected_retry_certificate_sha256=finalizer.PINNED_RETRY_CERTIFICATE_SHA256,
        expected_superseding_certificate_sha256=finalizer.PINNED_SUPERSEDING_CERTIFICATE_SHA256,
        expected_postrun_receipt_sha256=finalizer.PINNED_POSTRUN_RECEIPT_SHA256,
        expected_canonical_task_file_sha256=finalizer.PINNED_CANONICAL_TASK_FILE_SHA256,
        taskset_id=finalizer.PINNED_TASKSET_ID,
        dataset_revision=finalizer.PINNED_DATASET_REVISION,
        expected_count=finalizer.PINNED_COUNTS["input"],
        expected_positive=finalizer.PINNED_COUNTS["positive"],
        expected_zero=finalizer.PINNED_COUNTS["zero"],
        expected_error=finalizer.PINNED_COUNTS["error"],
        expected_selected_positive=finalizer.PINNED_COUNTS["selected_positive"],
        expected_strict_failures=finalizer.PINNED_COUNTS["strict_failures"],
        validation_permyriad=finalizer.PINNED_VALIDATION_PERMYRIAD,
        split_salt=finalizer.PINNED_SPLIT_SALT,
    )
    finalizer._validate_production_identity(production)
    with pytest.raises(finalizer.RecoveredSFTError, match="recovered_v6_identity_mismatch"):
        finalizer._validate_production_identity(replace(production, expected_positive=1_587))


@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd is required")
def test_canonical_archive_is_verified_and_chunk_tamper_fails(tmp_path: Path) -> None:
    package = _canonical_package(tmp_path)
    verifier = Path(finalizer.__file__).with_name("verify_qwen_recovered_trace_archive.py")
    binding = finalizer._validate_archive(package, verifier)
    assert binding.archive.sha256 == package.value["archive"]["sha256"]
    assert len(binding.chunks) == 1

    chunk = binding.chunks[0][0]
    chunk.write_bytes(chunk.read_bytes() + b"tamper")
    chunk.chmod(0o600)
    with pytest.raises(finalizer.RecoveredSFTError, match="package_chunk_digest_mismatch"):
        finalizer._validate_archive(package, verifier)


def test_launchers_are_syntax_valid_and_fail_closed() -> None:
    workflow = Path(finalizer.__file__).parent
    launcher = workflow / "launch_qwen_recovered_sft.sh"
    worker = workflow / "finalize_qwen_recovered_sft.sbatch"
    test_worker = workflow / "test_qwen_recovered_sft.sbatch"
    subprocess.run(["bash", "-n", str(launcher)], check=True)
    subprocess.run(["bash", "-n", str(worker)], check=True)
    subprocess.run(["bash", "-n", str(test_worker)], check=True)
    launcher_text = launcher.read_text()
    worker_text = worker.read_text()
    assert "swebench_vmvm:Launcher.0" in launcher_text
    assert '--export="$exports"' in launcher_text
    assert "--export=ALL" not in launcher_text
    assert "QWEN_RECOVERED_SFT_EXPECTED_FINALIZER_SHA256" in launcher_text
    assert "QWEN_RECOVERED_SFT_EXPECTED_WORKER_SHA256" in launcher_text
    assert "--expected-finalizer-sha256" in worker_text
    assert "--expected-strict-failures" in worker_text
