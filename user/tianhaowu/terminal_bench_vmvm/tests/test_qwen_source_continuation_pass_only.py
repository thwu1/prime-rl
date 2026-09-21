from __future__ import annotations

import argparse
import io
import json
import os
import re
from pathlib import Path

import audit_traces
import export_sft as sft
import pytest
import qwen_source_continuation_pass_only as pass_only


def _line(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode() + b"\n"


def _trace(
    slug: str,
    index: int,
    *,
    reward: int = 1,
    errors: list[str] | None = None,
    finish_reason: str | None = "stop",
    captured_finish_reason: str | None = None,
) -> dict:
    captured = finish_reason if captured_finish_reason is None else captured_finish_reason
    return {
        "errors": [] if errors is None else errors,
        "id": f"trace-{index}",
        "is_completed": True,
        "nodes": [
            {
                "finish_reason": finish_reason,
                "message": {"content": "answer", "reasoning_content": "reason", "role": "assistant"},
                "model_io": {
                    "response": {
                        "body": {"choices": [{"finish_reason": captured}]},
                        "kind": "exact_provider_json",
                    }
                },
                "sampled": True,
            }
        ],
        "rewards": {"reward": reward},
        "stop_condition": "done",
        "task": {"idx": index, "name": f"dataset/{slug}"},
    }


def _context(*members: str) -> sft.TaskIdentityContext:
    return sft.TaskIdentityContext(
        taskset_id="taskset",
        dataset_revision="a" * 40,
        approved_slugs=frozenset(members),
        approved_slug_order=tuple(sorted(members)),
    )


def _audit(
    *,
    positive: int,
    zero: int,
    errors: int,
    contract: audit_traces.CapturedModelIOContract,
    rows: dict[str, pass_only.TraceIndex] | None = None,
) -> pass_only.PassOnlyAudit:
    contract_id = next(name for name, value in audit_traces.MODEL_IO_CONTRACTS.items() if value == contract)
    return pass_only.PassOnlyAudit(
        results=pass_only.Artifact(bytes=1, sha256="a" * 64),
        input_traces=positive + zero + errors,
        covered_tasks=positive + zero + errors,
        error_traces=errors,
        zero_reward_traces=zero,
        positive_traces=positive,
        trainable_positive_traces=positive,
        nonexported_length_traces=zero,
        positive_model_io_turns=positive,
        positive_sampled_tokens=positive,
        positive_trace_contract={
            "id": contract_id,
            "sha256": audit_traces.model_io_contract_sha256(contract),
        },
        rows={} if rows is None else rows,
    )


def test_historical_run_validator_receives_size_compatibility_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = pass_only.launch.ArtifactSnapshot(
        sha256="a" * 64,
        size_bytes=17,
        identity=(1, 2, 3),
    )
    snapshots = {"results.jsonl": snapshot}
    observed: dict[str, object] = {}

    def validate(**kwargs: object) -> tuple[dict, dict, dict]:
        expected = kwargs["expected_snapshots"]
        assert isinstance(expected, dict)
        compatibility = expected["results.jsonl"]
        observed["size"] = compatibility.size
        observed["sha256"] = compatibility.sha256
        observed["identity"] = compatibility.identity
        observed["snapshot_retained"] = compatibility.snapshot is snapshot
        return {}, {}, {}

    monkeypatch.setattr(pass_only.launch, "_validate_run_identity", validate)

    result = pass_only._validate_historical_run_identity(
        run=Path("/run"),
        root=object(),  # type: ignore[arg-type]
        validated=object(),  # type: ignore[arg-type]
        expected_snapshots=snapshots,
    )

    assert result == ({}, {}, {})
    assert observed == {
        "size": 17,
        "sha256": "a" * 64,
        "identity": (1, 2, 3),
        "snapshot_retained": True,
    }
    assert snapshot.size_bytes == 17
    assert not hasattr(snapshot, "size")


def test_audit_classifies_nonexported_rows_and_validates_only_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    members = ("error-task", "positive-task", "zero-task")
    context = _context(*members)
    indices = {member: index for index, member in enumerate(sorted(members))}
    traces = [
        _trace("error-task", indices["error-task"], errors=["redacted"]),
        _trace("positive-task", indices["positive-task"]),
        _trace(
            "zero-task",
            indices["zero-task"],
            reward=0,
            finish_reason=None,
            captured_finish_reason="length",
        ),
    ]
    validated: list[float] = []

    def validate(_trace: dict, *, reward: float, **_kwargs: object) -> tuple[list, list]:
        validated.append(reward)
        return [], []

    monkeypatch.setattr(pass_only.sft, "_validate_trainable_trace", validate)
    audit = pass_only._audit_results(
        io.BytesIO(b"".join(_line(trace) for trace in traces)),
        task_context=context,
        expected_members=frozenset(members),
        expected_input_traces=3,
        model_io_contract=audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
    )

    assert validated == [1.0]
    assert audit.error_traces == 1
    assert audit.zero_reward_traces == 1
    assert audit.nonexported_length_traces == 1
    assert audit.positive_traces == audit.trainable_positive_traces == 1
    assert audit.nonexported_traces == 2
    assert audit.public_value()["all_outcomes_trainability_claimed"] is False


def test_audit_rejects_an_invalid_positive_but_not_a_zero_length_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context("positive-task", "zero-task")
    traces = [
        _trace("positive-task", 0),
        _trace("zero-task", 1, reward=0, finish_reason=None, captured_finish_reason="length"),
    ]

    def reject_positive(*_args: object, **_kwargs: object) -> None:
        raise sft.ExportError("sampled_finish_reason_length")

    monkeypatch.setattr(pass_only.sft, "_validate_trainable_trace", reject_positive)
    with pytest.raises(pass_only.PassOnlyError, match="positive_trace_invalid"):
        pass_only._audit_results(
            io.BytesIO(b"".join(_line(trace) for trace in traces)),
            task_context=context,
            expected_members=frozenset(context.approved_slugs),
            expected_input_traces=2,
            model_io_contract=audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
        )


def test_zero_reward_finish_reason_must_match_captured_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context("zero-task")
    monkeypatch.setattr(pass_only.sft, "_validate_trainable_trace", lambda *_args, **_kwargs: ([], []))
    trace = _trace("zero-task", 0, reward=0, finish_reason="stop", captured_finish_reason="length")

    with pytest.raises(pass_only.PassOnlyError, match="captured_finish_reason_invalid"):
        pass_only._audit_results(
            io.BytesIO(_line(trace)),
            task_context=context,
            expected_members=frozenset(context.approved_slugs),
            expected_input_traces=1,
            model_io_contract=audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
        )


@pytest.mark.parametrize("mutation", ["duplicate", "missing"])
def test_audit_requires_exact_unique_task_coverage(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    context = _context("one", "two")
    monkeypatch.setattr(pass_only.sft, "_validate_trainable_trace", lambda *_args, **_kwargs: ([], []))
    traces = [_trace("one", 0)]
    if mutation == "duplicate":
        duplicate = _trace("one", 0)
        duplicate["id"] = "different-id"
        traces.append(duplicate)
    with pytest.raises(pass_only.PassOnlyError, match="duplicate_task_trace|coverage_contract_invalid"):
        pass_only._audit_results(
            io.BytesIO(b"".join(_line(trace) for trace in traces)),
            task_context=context,
            expected_members=frozenset(context.approved_slugs),
            expected_input_traces=len(traces),
            model_io_contract=audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
        )


def test_positive_records_preserve_canonical_order_and_omit_nonpositive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pass_only, "RETAINED_COUNT", 2)
    monkeypatch.setattr(pass_only, "CONTINUATION_COUNT", 2)
    monkeypatch.setattr(pass_only, "CANONICAL_SANDOQ_COUNT", 4)
    records = {
        slug: pass_only.TraceIndex(0, 1, index, str(index) * 64, slug, chr(97 + index) * 64, outcome)
        for index, (slug, outcome) in enumerate(
            (("a", "positive"), ("b", "zero"), ("c", "positive"), ("d", "error")),
            start=1,
        )
    }
    retained = _audit(
        positive=1,
        zero=1,
        errors=0,
        contract=audit_traces.QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT,
        rows={"a": records["a"], "b": records["b"]},
    )
    continuation = _audit(
        positive=1,
        zero=0,
        errors=1,
        contract=audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
        rows={"c": records["c"], "d": records["d"]},
    )

    ordered = pass_only._positive_records_in_canonical_order(("d", "b", "c", "a", "vmvm"), retained, continuation)

    assert [record.slug for record in ordered] == ["c", "a"]


def test_manifest_separates_coverage_from_selected_sft_count() -> None:
    retained = _audit(
        positive=pass_only.RETAINED_POSITIVE_COUNT,
        zero=pass_only.RETAINED_ZERO_REWARD_COUNT,
        errors=0,
        contract=audit_traces.QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT,
    )
    continuation = _audit(
        positive=17,
        zero=pass_only.CONTINUATION_COUNT - 19,
        errors=2,
        contract=audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
    )
    manifest = pass_only._bundle_manifest(
        certificate={"kind": pass_only.CERTIFICATE_KIND, "plan_sha256": pass_only.FROZEN_PLAN_SHA256},
        certificate_artifact=pass_only.Artifact(1, "b" * 64),
        code={
            "files": {"qwen_source_continuation_pass_only.py": "c" * 64},
            "repository_revision": "c" * 40,
        },
        retained_audit=retained,
        continuation_audit=continuation,
        artifacts={},
        train_tasks={"d" * 64},
        validation_tasks={"e" * 64},
        emitted_rows=800,
        train_rows=700,
        validation_rows=100,
        source_lineage={},
    )

    assert manifest["counts"]["canonical_coverage_tasks"] == 2_499
    assert manifest["counts"]["selected_sft_tasks"] == 749 + 17
    assert manifest["counts"]["selected_sft_tasks"] != manifest["counts"]["canonical_coverage_tasks"]
    assert manifest["all_outcomes_trainability_claimed"] is False
    assert manifest["coverage"]["continuation"]["error_traces_nonexported"] == 2
    assert manifest["exporter"] == {
        "file_sha256": "c" * 64,
        "format_version": 3,
    }
    assert manifest["source_validation"]["model_io_contract"] == pass_only.COMBINED_MODEL_IO_CONTRACT_ID


def test_merged_bundle_is_recognized_by_downstream_format_v3_preflight(tmp_path) -> None:
    from prime_rl.configs.sft import SFTDataConfig
    from prime_rl.trainer.sft import export_preflight

    os.chmod(tmp_path, 0o700)
    for name in ("train", "validation"):
        (tmp_path / name).mkdir(mode=0o700)
    target_body = Path(sft.TARGET_RENDERING_CONTRACT_PATH).read_bytes()
    artifacts = {
        sft.TARGET_RENDERING_CONTRACT_FILENAME: pass_only._write_file(
            tmp_path / sft.TARGET_RENDERING_CONTRACT_FILENAME,
            target_body,
        ),
        "task-split.json": pass_only._write_file(tmp_path / "task-split.json", b"{}\n"),
        "train/train.jsonl": pass_only._write_file(tmp_path / "train" / "train.jsonl", b""),
        "validation/train.jsonl": pass_only._write_file(tmp_path / "validation" / "train.jsonl", b""),
    }
    retained = _audit(
        positive=pass_only.RETAINED_POSITIVE_COUNT,
        zero=pass_only.RETAINED_ZERO_REWARD_COUNT,
        errors=0,
        contract=audit_traces.QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT,
    )
    continuation = _audit(
        positive=1,
        zero=pass_only.CONTINUATION_COUNT - 1,
        errors=0,
        contract=audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
    )
    certificate = {"kind": pass_only.CERTIFICATE_KIND, "plan_sha256": pass_only.FROZEN_PLAN_SHA256}
    certificate_artifact = pass_only._write_file(
        tmp_path / pass_only.CERTIFICATE_COPY_FILENAME,
        pass_only._json_bytes(certificate, pretty=True),
    )
    manifest = pass_only._bundle_manifest(
        certificate=certificate,
        certificate_artifact=certificate_artifact,
        code={"files": {"qwen_source_continuation_pass_only.py": "e" * 64}},
        retained_audit=retained,
        continuation_audit=continuation,
        artifacts=artifacts,
        train_tasks=set(),
        validation_tasks=set(),
        emitted_rows=0,
        train_rows=0,
        validation_rows=0,
        source_lineage={},
    )
    manifest_body = pass_only._json_bytes(manifest, pretty=True)
    pass_only._write_file(tmp_path / pass_only.MANIFEST_FILENAME, manifest_body)

    binding = export_preflight._load_export_binding(tmp_path, pass_only._sha256(manifest_body))

    assert binding.root == tmp_path
    assert set(binding.artifacts) == export_preflight.REQUIRED_EXPORT_ARTIFACTS
    assert pass_only.CERTIFICATE_COPY_FILENAME not in binding.artifacts
    assert binding.manifest_value["certificate"]["artifact"] == certificate_artifact.value()
    assert binding.source_validation["model_io_contract"] == pass_only.COMBINED_MODEL_IO_CONTRACT_ID
    assert (
        binding.source_validation["model_io_contract"]
        == export_preflight.QWEN3_A95B_EPOCH3_DIRECT_MEDIUM_MODEL_IO_CONTRACT_ID
    )
    assert export_preflight._format_v3_root(SFTDataConfig(name=str(tmp_path / "train"))) == tmp_path


def test_certificate_binds_frozen_launch_and_pass_only_scope() -> None:
    audit = _audit(
        positive=10,
        zero=pass_only.CONTINUATION_COUNT - 12,
        errors=2,
        contract=audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
    )
    validated = type(
        "Validated",
        (),
        {
            "sha256": pass_only.FROZEN_PLAN_SHA256,
            "config_body": b"config",
            "value": {"materialization": {"lineage": {"sealed": True}}},
        },
    )()
    certificate = pass_only._continuation_certificate_value(
        validated=validated,
        envelope={
            "eval_run_identity_sha256": "f" * 64,
            "identity": {"deployment": {"worker_manifest": {"sha256": "e" * 64}}},
        },
        shared={},
        provider_source={},
        audit=audit,
        cleanup={"zero_drop": True},
        cleanup_hashes={},
        code={"repository_revision": "d" * 40},
    )

    assert certificate["historical_launch"]["code"] == pass_only.FROZEN_LAUNCH_CODE
    assert certificate["coverage_audit"]["positive_reward_traces"] == 10
    assert certificate["coverage_audit"]["nonexported_traces"] == pass_only.CONTINUATION_COUNT - 10
    assert certificate["all_outcomes_trainability_claimed"] is False
    assert certificate["merge_contract"]["selected_sft_tasks"] == 759


def test_exact_certificate_comparison_rejects_tampered_cleanup() -> None:
    expected = {
        "kind": pass_only.CERTIFICATE_KIND,
        "cleanup": {"zero_drop": True},
        "coverage_audit": {"positive_reward_traces": 10},
    }
    tampered = {**expected, "cleanup": {"zero_drop": False}}

    with pytest.raises(pass_only.PassOnlyError, match="certificate_evidence_mismatch"):
        pass_only._require_exact_certificate(pass_only._json_bytes(tampered), expected)


def test_output_requires_private_parent_and_rejects_symlink(tmp_path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    _parent, output = pass_only._output_path(private / "bundle", ())
    assert output == private / "bundle"

    os.chmod(private, 0o755)
    with pytest.raises(pass_only.PassOnlyError, match="output_path_invalid"):
        pass_only._output_path(private / "bundle", ())
    os.chmod(private, 0o700)
    (private / "target").mkdir(mode=0o700)
    (private / "bundle").symlink_to(private / "target", target_is_directory=True)
    with pytest.raises(pass_only.PassOnlyError, match="output_path_invalid"):
        pass_only._output_path(private / "bundle", ())


def test_publish_rolls_back_after_post_rename_fsync_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    os.chmod(tmp_path, 0o700)
    descriptor, parent_identity = pass_only._open_output_parent(tmp_path)
    try:
        stage_name, stage, stage_identity = pass_only._make_stage(descriptor, "output")
        pass_only._write_file(stage / "artifact", b"value\n")
        expected_tree = pass_only._tree_sha256_at(descriptor, stage_name, stage_identity)
        monkeypatch.setattr(pass_only.os, "fsync", lambda _descriptor: (_ for _ in ()).throw(OSError("fail")))

        with pytest.raises(OSError, match="fail"):
            pass_only._publish_directory(
                stage_name,
                "output",
                tmp_path,
                descriptor,
                parent_identity,
                stage_identity,
                expected_tree,
            )

        assert not (tmp_path / "output").exists()
        assert not pass_only._entry_exists(descriptor, "output")
    finally:
        os.close(descriptor)


def test_publish_never_replaces_existing_destination(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    descriptor, parent_identity = pass_only._open_output_parent(tmp_path)
    try:
        stage_name, stage, stage_identity = pass_only._make_stage(descriptor, "output")
        pass_only._write_file(stage / "artifact", b"new\n")
        expected_tree = pass_only._tree_sha256_at(descriptor, stage_name, stage_identity)
        output = tmp_path / "output"
        output.mkdir(mode=0o700)
        pass_only._write_file(output / "marker", b"existing\n")

        with pytest.raises(pass_only.PassOnlyError, match="output_already_exists"):
            pass_only._publish_directory(
                stage_name,
                "output",
                tmp_path,
                descriptor,
                parent_identity,
                stage_identity,
                expected_tree,
            )

        assert (output / "marker").read_bytes() == b"existing\n"
        pass_only._remove_tree_at(descriptor, stage_name, stage_identity)
    finally:
        os.close(descriptor)


def test_publish_rejects_mutation_after_bundle_verification(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    descriptor, parent_identity = pass_only._open_output_parent(tmp_path)
    try:
        stage_name, stage, stage_identity = pass_only._make_stage(descriptor, "output")
        artifact = stage / "artifact"
        pass_only._write_file(artifact, b"verified\n")
        expected_tree = pass_only._tree_sha256_at(descriptor, stage_name, stage_identity)
        artifact.write_bytes(b"mutated\n")
        os.chmod(artifact, 0o600)

        with pytest.raises(pass_only.PassOnlyError, match="export_tree_changed"):
            pass_only._publish_directory(
                stage_name,
                "output",
                tmp_path,
                descriptor,
                parent_identity,
                stage_identity,
                expected_tree,
            )

        assert not (tmp_path / "output").exists()
        pass_only._remove_tree_at(descriptor, stage_name, stage_identity)
    finally:
        os.close(descriptor)


def test_parent_descriptor_detects_path_substitution(tmp_path) -> None:
    container = tmp_path / "container"
    container.mkdir(mode=0o700)
    parent = container / "parent"
    parent.mkdir(mode=0o700)
    descriptor, identity = pass_only._open_output_parent(parent)
    moved = container / "moved"
    try:
        parent.rename(moved)
        parent.mkdir(mode=0o700)
        with pytest.raises(pass_only.PassOnlyError, match="output_parent_changed"):
            pass_only._validate_parent_identity(parent, descriptor, identity)
    finally:
        os.close(descriptor)
        parent.rmdir()
        moved.rename(parent)


def test_private_bundle_rejects_nonprivate_or_linked_artifacts(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    for name in ("train", "validation"):
        (tmp_path / name).mkdir(mode=0o700)
    bodies = {
        pass_only.CERTIFICATE_COPY_FILENAME: b"certificate\n",
        sft.TARGET_RENDERING_CONTRACT_FILENAME: b"target\n",
        "task-split.json": b"split\n",
        "train/train.jsonl": b"train\n",
        "validation/train.jsonl": b"validation\n",
    }
    artifacts = {name: pass_only._write_file(tmp_path / name, body) for name, body in bodies.items()}
    manifest = pass_only._write_file(tmp_path / pass_only.MANIFEST_FILENAME, b"manifest\n")
    pass_only._verify_private_bundle(tmp_path, artifacts, manifest)

    os.chmod(tmp_path / "train" / "train.jsonl", 0o640)
    with pytest.raises(pass_only.PassOnlyError, match="bundle_privacy_invalid"):
        pass_only._verify_private_bundle(tmp_path, artifacts, manifest)
    os.chmod(tmp_path / "train" / "train.jsonl", 0o600)
    os.link(tmp_path / "train" / "train.jsonl", tmp_path.parent / "linked-row")
    with pytest.raises(pass_only.PassOnlyError, match="bundle_privacy_invalid"):
        pass_only._verify_private_bundle(tmp_path, artifacts, manifest)


def test_cli_stdout_is_aggregate_only(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    parser = type("Parser", (), {"parse_args": lambda _self: argparse.Namespace(command="certify")})()
    monkeypatch.setattr(pass_only, "_parser", lambda: parser)
    monkeypatch.setattr(
        pass_only,
        "certify",
        lambda: {
            "continuation_coverage_tasks": 1_233,
            "continuation_nonexported_tasks": 9,
            "continuation_positive_export_tasks": 1_224,
            "state": "passed",
        },
    )

    pass_only.main()

    output = capsys.readouterr().out
    assert not re.search(r"[0-9a-f]{40,64}", output)
    assert json.loads(output)["continuation_coverage_tasks"] == 1_233


def test_cli_redacts_unexpected_exception(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    parser = type("Parser", (), {"parse_args": lambda _self: argparse.Namespace(command="certify")})()
    monkeypatch.setattr(pass_only, "_parser", lambda: parser)
    monkeypatch.setattr(
        pass_only,
        "certify",
        lambda: (_ for _ in ()).throw(RuntimeError("private-task-and-provider-payload")),
    )

    with pytest.raises(SystemExit, match="pass_only_operation_failed"):
        pass_only.main()

    captured = capsys.readouterr()
    assert "private-task-and-provider-payload" not in captured.out + captured.err
