from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import replace
from pathlib import Path

import pytest
from merge_qwen_sft import (
    FORMAT_VERSION,
    LOSS_MASK,
    MAX_SEQUENCE_TOKENS,
    REPAIR_ATTESTATION_COPY_FILENAME,
    REPAIR_ATTESTATION_SCHEMA_VERSION,
    REPAIR_SELECTION_COPY_FILENAME,
    REPAIR_SELECTION_KIND,
    REQUIRED_SUBMODULES,
    SPLIT_POLICY,
    TARGET_RENDERING_CONTRACT,
    TARGET_RENDERING_CONTRACT_FILENAME,
    TARGET_RENDERING_CONTRACT_SHA256,
    TASK_IDENTITY,
    MergeError,
    MergeOptions,
    _export_tree_sha256,
    merge_qwen_sft,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()


_TASK_SLUG_BY_ID: dict[str, str] = {}


def _task_id(label: str, *, split: str = "train") -> str:
    for counter in range(100_000):
        slug = f"{label}-{counter}"
        task_id = _sha256(f"synthetic-taskset\0{'7' * 40}\0{slug}".encode())
        digest = hashlib.sha256(f"unit-test-split\0{task_id}".encode()).digest()
        observed = "validation" if int.from_bytes(digest[:8], "big") % 10_000 < 500 else "train"
        if observed == split:
            _TASK_SLUG_BY_ID[task_id] = slug
            return task_id
    raise AssertionError("unable to construct task ID for split")


def _row(
    task_id: str,
    marker: str,
    *,
    reward: int = 1,
    targets: int = 1,
    turn_index: int = 0,
    trajectory_turns: int = 1,
) -> dict:
    messages = [
        {"content": marker, "role": "user", "trainable": False},
        {
            "content": f"answer-{marker}",
            "finish_reason": "stop",
            "reasoning_content": f"reasoning-{marker}",
            "role": "assistant",
            "trainable": True,
        },
    ]
    if targets == 0:
        messages[-1]["trainable"] = False
    elif targets == 2:
        messages[0] = {
            "content": marker,
            "finish_reason": "stop",
            "role": "assistant",
            "trainable": True,
        }
    return {
        "assistant_target_count": targets,
        "history_reasoning_policy": "preserve_all_assistant_reasoning",
        "is_correct": reward == 1,
        "messages": messages,
        "reward": reward,
        "source_episode_id": _sha256(f"episode-{task_id}".encode()),
        "source_node_index": turn_index + 1,
        "source_split_row_index": 0,
        "source_trace_index": 0,
        "source_trajectory_assistant_turn_count": trajectory_turns,
        "target_assistant_message_index": 1,
        "target_assistant_turn_index": turn_index,
        "target_finish_reason": "stop",
        "target_has_reasoning": True,
        "task_id": task_id,
        "tools": [
            {
                "function": {
                    "description": "synthetic tool",
                    "name": "shell",
                    "parameters": {"type": "object"},
                },
                "type": "function",
            }
        ],
        "transcript_fidelity": {
            "retained_assistant_reasoning_fields": 1,
            "retained_sampled_finish_reasons": 1,
            "source_assistant_reasoning_fields": 1,
            "source_sampled_finish_reasons": 1,
        },
    }


def _jsonl(rows: list[dict]) -> bytes:
    return b"".join(
        json.dumps(row, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        for row in rows
    )


def _write_export(
    root: Path,
    *,
    train_rows: list[dict],
    validation_rows: list[dict],
    split_salt: str = "unit-test-split",
    validation_permyriad: int = 500,
    max_sequence_tokens: int = MAX_SEQUENCE_TOKENS,
    format_version: int = FORMAT_VERSION,
    selection: str = "pass-only",
    input_traces: int | None = None,
    source_task_file_sha256: str | None = None,
    taskset_id: str = "synthetic-taskset",
    dataset_revision: str = "7" * 40,
    routing_epoch: int | None = None,
) -> Path:
    train_rows = [
        {**row, **({"routing_epoch": routing_epoch} if routing_epoch is not None else {})} for row in train_rows
    ]
    validation_rows = [
        {**row, **({"routing_epoch": routing_epoch} if routing_epoch is not None else {})} for row in validation_rows
    ]
    (root / "train").mkdir(parents=True)
    (root / "validation").mkdir()
    train_body = _jsonl(train_rows)
    validation_body = _jsonl(validation_rows)
    (root / "train" / "train.jsonl").write_bytes(train_body)
    (root / "validation" / "train.jsonl").write_bytes(validation_body)
    train_tasks = sorted({row["task_id"] for row in train_rows})
    validation_tasks = sorted({row["task_id"] for row in validation_rows})
    task_split_body = _json_bytes(
        {
            "format_version": format_version,
            "split_salt": split_salt,
            "train_task_sha256": train_tasks,
            "validation_permyriad": validation_permyriad,
            "validation_task_sha256": validation_tasks,
        }
    )
    (root / "task-split.json").write_bytes(task_split_body)
    target_rendering_body = (json.dumps(TARGET_RENDERING_CONTRACT, indent=2, sort_keys=True) + "\n").encode()
    assert _sha256(target_rendering_body) == TARGET_RENDERING_CONTRACT_SHA256
    (root / TARGET_RENDERING_CONTRACT_FILENAME).write_bytes(target_rendering_body)
    (root / TARGET_RENDERING_CONTRACT_FILENAME).chmod(0o600)
    task_count = len(set(train_tasks) | set(validation_tasks))
    if input_traces is None:
        input_traces = task_count
    if source_task_file_sha256 is None:
        source_task_file_sha256 = _sha256(
            "".join(f"{task}\n" for task in sorted(set(train_tasks) | set(validation_tasks))).encode()
        )
    source_artifacts = {
        "config.toml": {"bytes": 101, "sha256": "1" * 64},
        "direct_workers.json": {"bytes": 102, "sha256": "2" * 64},
        "inputs/image_manifest.json": {"bytes": 104, "sha256": "5" * 64},
        "inputs/manifest.json": {"bytes": 105, "sha256": "6" * 64},
        "inputs/source_config.toml": {"bytes": 106, "sha256": "a" * 64},
        "inputs/task_file.txt": {"bytes": input_traces, "sha256": source_task_file_sha256},
        "provenance.txt": {"bytes": 103, "sha256": "3" * 64},
        "results.jsonl": {"bytes": len(train_body) + len(validation_body), "sha256": "4" * 64},
    }
    manifest = {
        "artifacts": {
            "task-split.json": {"bytes": len(task_split_body), "sha256": _sha256(task_split_body)},
            TARGET_RENDERING_CONTRACT_FILENAME: {
                "bytes": len(target_rendering_body),
                "sha256": _sha256(target_rendering_body),
            },
            "train/train.jsonl": {"bytes": len(train_body), "sha256": _sha256(train_body)},
            "validation/train.jsonl": {
                "bytes": len(validation_body),
                "sha256": _sha256(validation_body),
            },
        },
        "counts": {
            "emitted_rows": len(train_rows) + len(validation_rows),
            "input_traces": input_traces,
            "selected_pass_traces": task_count,
            "selected_traces": task_count,
            "train_rows": len(train_rows),
            "train_traces": len(train_tasks),
            "validation_rows": len(validation_rows),
            "validation_traces": len(validation_tasks),
        },
        "config": {
            "capture_model_io": True,
            "dataset_revision": dataset_revision,
            "max_input_tokens": MAX_SEQUENCE_TOKENS,
            "max_output_tokens": MAX_SEQUENCE_TOKENS,
            "max_total_tokens": MAX_SEQUENCE_TOKENS,
            "model": "Qwen3.8-2.4T-A95B",
            "num_rollouts": 1,
            "taskset_id": taskset_id,
        },
        "exporter": {"file_sha256": "e" * 64, "format_version": format_version},
        "format": {
            "assistant_finish_reason": "retained verbatim for every sampled assistant message",
            "assistant_tool_calls": "OpenAI function-call objects",
            "history_assistant_reasoning": "retained verbatim",
            "loss_mask": LOSS_MASK,
            "sample_unit": "one unique sampled assistant node with its root-to-node context",
            "target": "authentic reasoning_content, content, tool_calls, and finish_reason",
            "task_identity": TASK_IDENTITY,
        },
        "max_sequence_tokens": max_sequence_tokens,
        "selection": selection,
        "source_artifacts": source_artifacts,
        "split": {
            "policy": SPLIT_POLICY,
            "split_salt": split_salt,
            "validation_permyriad": validation_permyriad,
        },
        "target_rendering": TARGET_RENDERING_CONTRACT,
    }
    if routing_epoch is not None:
        routing_index_body = b"synthetic-routing-index\n"
        (root / "qwen_router_epochs.jsonl").write_bytes(routing_index_body)
        routing_index_artifact = {
            "bytes": len(routing_index_body),
            "sha256": _sha256(routing_index_body),
        }
        manifest["routing_epochs"] = {
            "current_epoch": routing_epoch,
            "input_traces": {
                str(epoch): input_traces if epoch == routing_epoch else 0 for epoch in range(1, routing_epoch + 1)
            },
        }
        manifest["artifacts"]["qwen_router_epochs.jsonl"] = routing_index_artifact
        manifest["source_artifacts"]["qwen_router_epochs.jsonl"] = routing_index_artifact
    (root / "manifest.json").write_bytes(_json_bytes(manifest))
    return root


def _replace_export_artifact(root: Path, relative: str, body: bytes) -> None:
    path = root / relative
    path.write_bytes(body)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"][relative] = {"bytes": len(body), "sha256": _sha256(body)}
    manifest_path.write_bytes(_json_bytes(manifest))


def _write_repair_selection(
    path: Path,
    original_export: Path,
    repair_export: Path,
    *,
    strict_slugs: list[str] | None = None,
) -> str:
    original_manifest_path = original_export / "manifest.json"
    original_manifest = json.loads(original_manifest_path.read_text())
    repair_manifest = json.loads((repair_export / "manifest.json").read_text())
    repair_task_count = repair_manifest["counts"]["input_traces"]
    repair_task_ids = sorted(
        json.loads((repair_export / "task-split.json").read_text())["train_task_sha256"]
        + json.loads((repair_export / "task-split.json").read_text())["validation_task_sha256"]
    )
    if strict_slugs is None:
        missing_slugs = [_TASK_SLUG_BY_ID[task_id] for task_id in repair_task_ids]
        missing_slugs.extend(
            f"opaque-unselected-{index:04d}" for index in range(repair_task_count - len(repair_task_ids))
        )
        strict_slugs = []
    else:
        assert len(strict_slugs) <= repair_task_count
        strict_ids = {_sha256(f"synthetic-taskset\0{'7' * 40}\0{slug}".encode()) for slug in strict_slugs}
        available = [_TASK_SLUG_BY_ID[task_id] for task_id in repair_task_ids if task_id not in strict_ids]
        missing_count = repair_task_count - len(strict_slugs)
        missing_slugs = available[:missing_count]
        missing_slugs.extend(f"opaque-unselected-{index:04d}" for index in range(missing_count - len(missing_slugs)))
    union_slugs = sorted([*missing_slugs, *strict_slugs])
    union_body = "".join(f"{slug}\n" for slug in union_slugs).encode()
    missing_body = "".join(f"{slug}\n" for slug in sorted(missing_slugs)).encode()
    strict_body = "".join(f"{slug}\n" for slug in sorted(strict_slugs)).encode()
    for filename, file_body in (
        ("repair_tasks.txt", union_body),
        ("repair_missing_or_errored_tasks.txt", missing_body),
        ("repair_strict_invalid_pass_tasks.txt", strict_body),
    ):
        selected_path = path.parent / filename
        selected_path.write_bytes(file_body)
        selected_path.chmod(0o600)
    original_selected_count = original_manifest["counts"]["selected_traces"]
    source_task_count = original_selected_count + repair_task_count
    original_manifest["counts"]["input_traces"] = source_task_count
    original_manifest["counts"]["approved_tasks"] = source_task_count
    original_manifest["counts"]["exclusion_missing_tasks"] = 0
    original_manifest["counts"]["exclusion_missing_or_errored_tasks"] = len(missing_slugs)
    original_manifest["counts"]["exclusion_selected_traces"] = repair_task_count
    original_manifest["counts"]["exclusion_strict_invalid_pass_tasks"] = len(strict_slugs)
    original_manifest["routing_epochs"] = {
        "current_epoch": 3,
        "input_traces": {"1": 0, "2": 0, "3": source_task_count},
    }
    original_manifest_path.write_bytes(_json_bytes(original_manifest))
    task_file_sha256 = _sha256(union_body)
    repair_manifest["source_artifacts"]["inputs/task_file.txt"]["sha256"] = task_file_sha256
    (repair_export / "manifest.json").write_bytes(_json_bytes(repair_manifest))
    selection_source_artifacts = {
        "config": "config.toml",
        "direct_workers": "direct_workers.json",
        "image_manifest": "inputs/image_manifest.json",
        "inputs_manifest": "inputs/manifest.json",
        "provenance": "provenance.txt",
        "results": "results.jsonl",
        "source_config": "inputs/source_config.toml",
        "task_file": "inputs/task_file.txt",
    }
    body = _json_bytes(
        {
            "approval": {
                "approved_task_count": source_task_count,
                "approved_task_file_sha256": original_manifest["source_artifacts"]["inputs/task_file.txt"]["sha256"],
            },
            "code": {
                "exporter_sha256": "e" * 64,
                "materializer_sha256": "b" * 64,
                "repository_revision": "c" * 40,
                "submodules": {name: "d" * 40 for name in REQUIRED_SUBMODULES},
            },
            "config": {
                "capture_model_io": True,
                "enable_thinking": True,
                "max_concurrent": 64,
                "max_total_tokens": MAX_SEQUENCE_TOKENS,
                "preserve_thinking": True,
                "provider_concurrency": 32,
                "retry_class_count": 4,
                "retry_policy_sha256": "e" * 64,
                "sha256": repair_manifest["source_artifacts"]["inputs/source_config.toml"]["sha256"],
                "template_sha256": "0" * 64,
            },
            "kind": REPAIR_SELECTION_KIND,
            "planner": {
                "approved_task_count": source_task_count,
                "contract_verifiers_revision": "1" * 40,
                "missing_or_errored_count": len(missing_slugs),
                "module_sha256": "2" * 64,
                "retained_count": source_task_count - len(missing_slugs),
                "task_index_order_sha256": "3" * 64,
            },
            "schema_version": 2,
            "selection": {
                "approved_repair_count": repair_task_count,
                "missing_or_errored_count": len(missing_slugs),
                "missing_or_errored_indices_sha256": "4" * 64,
                "missing_or_errored_task_file_sha256": _sha256(missing_body),
                "repair_union_indices_sha256": "5" * 64,
                "strict_invalid_pass_count": len(strict_slugs),
                "strict_invalid_pass_indices_sha256": _sha256(b""),
                "strict_invalid_pass_task_file_sha256": _sha256(strict_body),
                "task_file_sha256": task_file_sha256,
            },
            "source": {
                "artifacts": {
                    label: {
                        "sha256": original_manifest["source_artifacts"][artifact]["sha256"],
                        "size_bytes": original_manifest["source_artifacts"][artifact]["bytes"],
                    }
                    for label, artifact in selection_source_artifacts.items()
                },
                "routing_epoch": 3,
                "task_count": source_task_count,
            },
        }
    )
    path.write_bytes(body)
    path.chmod(0o600)
    original_manifest = json.loads(original_manifest_path.read_text())
    original_manifest["exclusion_selection"] = {
        "approved_task_count": source_task_count,
        "artifacts": {
            "task_file": {"bytes": len(union_body), "sha256": _sha256(union_body)},
            "missing_or_errored_task_file": {
                "bytes": len(missing_body),
                "sha256": _sha256(missing_body),
            },
            "strict_invalid_pass_task_file": {
                "bytes": len(strict_body),
                "sha256": _sha256(strict_body),
            },
        },
        "manifest": {"bytes": len(body), "sha256": _sha256(body)},
        "missing_or_errored_count": len(missing_slugs),
        "strict_invalid_pass_count": len(strict_slugs),
        "union_count": repair_task_count,
    }
    original_manifest_path.write_bytes(_json_bytes(original_manifest))
    return _sha256(body)


def _write_repair_attestation(
    path: Path,
    repair_export: Path,
    selection_path: Path,
    selection_sha256: str,
) -> str:
    repair_manifest = json.loads((repair_export / "manifest.json").read_text())
    source_artifacts = repair_manifest["source_artifacts"]
    attested_names = (
        "config.toml",
        "inputs/task_file.txt",
        "provenance.txt",
        "results.jsonl",
        "direct_workers.json",
    )
    config = repair_manifest["config"]
    selection_manifest = json.loads(selection_path.read_text())
    selection_counts = selection_manifest["selection"]
    body = _json_bytes(
        {
            "code": {
                "repository_revision": "c" * 40,
                "submodules": {name: "d" * 40 for name in REQUIRED_SUBMODULES},
            },
            "corpus": {
                "dataset_revision": config["dataset_revision"],
                "task_count": repair_manifest["counts"]["input_traces"],
                "task_file_sha256": source_artifacts["inputs/task_file.txt"]["sha256"],
                "taskset_id": config["taskset_id"],
            },
            "kind": "qwen-direct-repair-attestation",
            "repair_selection_manifest_sha256": selection_sha256,
            "routing": {
                "manifest_schema_version": 3,
                "provider_concurrency": 32,
                "queue_size": 32,
                "request_id_headers": ["x-session-id"],
                "router_policy": "consistent_hash",
                "routing_epoch": 1,
            },
            "schema_version": REPAIR_ATTESTATION_SCHEMA_VERSION,
            "selection": {
                "missing_or_errored_count": selection_counts["missing_or_errored_count"],
                "strict_invalid_pass_count": selection_counts["strict_invalid_pass_count"],
                "union_count": repair_manifest["counts"]["input_traces"],
                "union_indices_sha256": selection_counts["repair_union_indices_sha256"],
                "union_task_file_sha256": source_artifacts["inputs/task_file.txt"]["sha256"],
            },
            "source_artifacts": {name: source_artifacts[name] for name in attested_names},
        }
    )
    path.write_bytes(body)
    path.chmod(0o600)
    return _sha256(body)


def _code_provenance() -> dict:
    return {
        "exporter_sha256": "e" * 64,
        "materializer_sha256": "b" * 64,
        "merger_sha256": "b" * 64,
        "repository_revision": "c" * 40,
        "submodules": {name: "d" * 40 for name in REQUIRED_SUBMODULES},
    }


def _options(
    original: Path,
    repair: Path,
    selection: Path,
    selection_sha256: str,
    output: Path,
) -> MergeOptions:
    attestation = selection.with_name(f"{selection.stem}-attestation.json")
    attestation_sha256 = _write_repair_attestation(attestation, repair, selection, selection_sha256)
    source_names = {
        REPAIR_SELECTION_COPY_FILENAME: selection.name,
        "repair_selection_tasks.txt": "repair_tasks.txt",
        "repair_selection_missing_or_errored_tasks.txt": "repair_missing_or_errored_tasks.txt",
        "repair_selection_strict_invalid_pass_tasks.txt": "repair_strict_invalid_pass_tasks.txt",
    }
    for copy_name, source_name in source_names.items():
        selection_copy = repair / copy_name
        selection_copy.write_bytes((selection.parent / source_name).read_bytes())
        selection_copy.chmod(0o600)
    attestation_copy = repair / REPAIR_ATTESTATION_COPY_FILENAME
    attestation_copy.write_bytes(attestation.read_bytes())
    attestation_copy.chmod(0o600)
    return MergeOptions(
        original_export_dir=original,
        original_export_manifest_sha256=_sha256((original / "manifest.json").read_bytes()),
        original_export_tree_sha256=_export_tree_sha256(original, "test_original_export_invalid"),
        repair_export_dir=repair,
        repair_export_manifest_sha256=_sha256((repair / "manifest.json").read_bytes()),
        repair_export_tree_sha256=_export_tree_sha256(repair, "test_repair_export_invalid"),
        repair_selection_manifest=selection,
        repair_selection_manifest_sha256=selection_sha256,
        repair_attestation_manifest=attestation,
        repair_attestation_manifest_sha256=attestation_sha256,
        output_dir=output,
        project_dir=output.parent,
        expected_project_revision="c" * 40,
    )


def _fixture_exports(tmp_path: Path) -> tuple[Path, Path, Path, str, set[str]]:
    original_train = _task_id("original-train")
    original_validation = _task_id("original-validation", split="validation")
    repair_train = _task_id("repair-train")
    repair_validation = _task_id("repair-validation", split="validation")
    original = _write_export(
        tmp_path / "original",
        train_rows=[
            _row(original_train, "private-original-turn-one", turn_index=0, trajectory_turns=2),
            _row(original_train, "private-original-turn-two", turn_index=1, trajectory_turns=2),
        ],
        validation_rows=[_row(original_validation, "private-original-validation")],
        routing_epoch=3,
    )
    repair = _write_export(
        tmp_path / "repair",
        train_rows=[
            _row(repair_train, "private-repair-turn-one", turn_index=0, trajectory_turns=2),
            _row(repair_train, "private-repair-turn-two", turn_index=1, trajectory_turns=2),
        ],
        validation_rows=[_row(repair_validation, "private-repair-validation")],
    )
    selection = tmp_path / "repair-selection.json"
    selection_sha256 = _write_repair_selection(selection, original, repair)
    return (
        original,
        repair,
        selection,
        selection_sha256,
        {original_train, original_validation, repair_train, repair_validation},
    )


def test_merge_is_deterministic_redacted_and_preserves_all_rows(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, task_ids = _fixture_exports(tmp_path)
    source_bytes = {
        path: path.read_bytes()
        for root in (original, repair)
        for path in (
            root / "manifest.json",
            root / "task-split.json",
            root / "train" / "train.jsonl",
            root / "validation" / "train.jsonl",
        )
    }

    first = tmp_path / "merged-first"
    second = tmp_path / "merged-second"
    first_summary = merge_qwen_sft(
        _options(original, repair, selection, selection_sha256, first),
        code_provenance=_code_provenance(),
    )
    second_summary = merge_qwen_sft(
        _options(original, repair, selection, selection_sha256, second),
        code_provenance=_code_provenance(),
    )

    for relative in (
        "manifest.json",
        "task-split.json",
        TARGET_RENDERING_CONTRACT_FILENAME,
        "train/train.jsonl",
        "validation/train.jsonl",
    ):
        assert (first / relative).read_bytes() == (second / relative).read_bytes()
        assert stat.S_IMODE((first / relative).stat().st_mode) == 0o600
    assert (first / "train" / "train.jsonl").read_bytes() == (original / "train" / "train.jsonl").read_bytes() + (
        repair / "train" / "train.jsonl"
    ).read_bytes()
    assert (first / "validation" / "train.jsonl").read_bytes() == (
        original / "validation" / "train.jsonl"
    ).read_bytes() + (repair / "validation" / "train.jsonl").read_bytes()
    assert first_summary == second_summary
    assert first_summary["rows"] == {"total": 6, "train": 4, "validation": 2}
    assert first_summary["tasks"] == {"total": 4, "train": 2, "validation": 2}
    aggregate_output = json.dumps(first_summary, sort_keys=True) + (first / "manifest.json").read_text()
    assert not any(task_id in aggregate_output for task_id in task_ids)
    assert "private-" not in aggregate_output
    merged_manifest = json.loads((first / "manifest.json").read_text())
    assert merged_manifest["schema_version"] == 4
    assert merged_manifest["code"]["exporter_sha256"] == "e" * 64
    assert merged_manifest["code"]["materializer_sha256"] == "b" * 64
    assert merged_manifest["format"]["target"].startswith("authentic reasoning_content")
    assert merged_manifest["inputs"]["original"]["tree_sha256"] == _export_tree_sha256(
        original,
        "test_original_export_invalid",
    )
    assert merged_manifest["inputs"]["repair"]["tree_sha256"] == _export_tree_sha256(
        repair,
        "test_repair_export_invalid",
    )
    assert set(json.loads((repair / "manifest.json").read_text())["artifacts"]) == {
        "task-split.json",
        TARGET_RENDERING_CONTRACT_FILENAME,
        "train/train.jsonl",
        "validation/train.jsonl",
    }
    assert source_bytes == {path: path.read_bytes() for path in source_bytes}


def test_tampered_artifact_is_rejected_without_output(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    train = repair / "train" / "train.jsonl"
    train.write_bytes(train.read_bytes().replace(b"private-repair-turn-one", b"tampered-repair-turn-one"))
    output = tmp_path / "merged"

    with pytest.raises(MergeError, match="^artifact_hash_mismatch$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, output),
            code_provenance=_code_provenance(),
        )
    assert not output.exists()


def test_rehashed_target_rendering_contract_is_rejected(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    modified = {**TARGET_RENDERING_CONTRACT, "schema_version": 3}
    _replace_export_artifact(repair, TARGET_RENDERING_CONTRACT_FILENAME, _json_bytes(modified))

    with pytest.raises(MergeError, match="^target_rendering_contract_invalid$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


@pytest.mark.parametrize(
    ("role", "error_code"),
    [
        ("original", "original_export_snapshot_mismatch"),
        ("repair", "repair_export_snapshot_mismatch"),
    ],
)
def test_finalized_export_tree_snapshot_rejects_late_extra_file(
    tmp_path: Path,
    role: str,
    error_code: str,
) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    options = _options(original, repair, selection, selection_sha256, tmp_path / "merged")
    target = original if role == "original" else repair
    (target / "late-extra").write_bytes(b"late mutation\n")

    with pytest.raises(MergeError, match=f"^{error_code}$"):
        merge_qwen_sft(options, code_provenance=_code_provenance())


@pytest.mark.parametrize(
    ("field", "error_code"),
    [
        ("original_export_manifest_sha256", "original_manifest_binding_mismatch"),
        ("repair_export_manifest_sha256", "repair_manifest_binding_mismatch"),
    ],
)
def test_finalized_export_manifest_digest_is_mandatory(
    tmp_path: Path,
    field: str,
    error_code: str,
) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    options = replace(
        _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
        **{field: "0" * 64},
    )

    with pytest.raises(MergeError, match=f"^{error_code}$"):
        merge_qwen_sft(options, code_provenance=_code_provenance())


def test_repair_selection_tamper_is_rejected(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    selection.write_bytes(selection.read_bytes() + b" ")

    with pytest.raises(MergeError, match="^repair_selection_digest_mismatch$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_repair_pass_only_export_may_be_smaller_than_selected_run(tmp_path: Path) -> None:
    original = _write_export(
        tmp_path / "original",
        train_rows=[_row(_task_id("original"), "original")],
        validation_rows=[],
        routing_epoch=3,
    )
    repair = _write_export(
        tmp_path / "repair",
        train_rows=[_row(_task_id("repair-pass"), "repair-pass")],
        validation_rows=[],
        input_traces=2,
        source_task_file_sha256="f" * 64,
    )
    selection = tmp_path / "selection.json"
    digest = _write_repair_selection(selection, original, repair)

    summary = merge_qwen_sft(
        _options(original, repair, selection, digest, tmp_path / "merged"),
        code_provenance=_code_provenance(),
    )

    assert summary["tasks"]["total"] == 2


def test_original_exclusion_accounts_for_attested_missing_physical_row(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    manifest_path = original / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["counts"]["input_traces"] -= 1
    manifest["counts"]["exclusion_missing_tasks"] = 1
    manifest["counts"]["exclusion_selected_traces"] -= 1
    manifest["routing_epochs"]["input_traces"]["3"] -= 1
    manifest_path.write_bytes(_json_bytes(manifest))

    summary = merge_qwen_sft(
        _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
        code_provenance=_code_provenance(),
    )

    assert summary["tasks"]["total"] == 4


def test_original_exclusion_rejects_inconsistent_missing_accounting(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    manifest_path = original / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["counts"]["exclusion_missing_tasks"] = 1
    manifest_path.write_bytes(_json_bytes(manifest))

    with pytest.raises(MergeError, match="^original_exclusion_contract_invalid$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_strict_invalid_pass_requires_exact_repair_replacement(tmp_path: Path) -> None:
    slug = "strict-invalid"
    namespace = "synthetic-taskset"
    revision = "7" * 40
    replacement_id = _sha256(f"{namespace}\0{revision}\0{slug}".encode())
    split = (
        "validation"
        if int.from_bytes(hashlib.sha256(f"unit-test-split\0{replacement_id}".encode()).digest()[:8], "big") % 10_000
        < 500
        else "train"
    )
    original = _write_export(
        tmp_path / "original",
        train_rows=[_row(_task_id("original"), "original")],
        validation_rows=[],
        routing_epoch=3,
    )
    repair = _write_export(
        tmp_path / "repair",
        train_rows=[_row(replacement_id, "replacement")] if split == "train" else [],
        validation_rows=[_row(replacement_id, "replacement")] if split == "validation" else [],
    )
    selection = tmp_path / "selection.json"
    digest = _write_repair_selection(selection, original, repair, strict_slugs=[slug])

    summary = merge_qwen_sft(
        _options(original, repair, selection, digest, tmp_path / "merged"),
        code_provenance=_code_provenance(),
    )
    assert summary["tasks"]["total"] == 2


def test_strict_invalid_pass_missing_repair_fails_closed(tmp_path: Path) -> None:
    original = _write_export(
        tmp_path / "original",
        train_rows=[_row(_task_id("original"), "original")],
        validation_rows=[],
        routing_epoch=3,
    )
    repair = _write_export(
        tmp_path / "repair",
        train_rows=[_row(_task_id("different-repair"), "different-repair")],
        validation_rows=[],
    )
    selection = tmp_path / "selection.json"
    digest = _write_repair_selection(selection, original, repair, strict_slugs=["strict-invalid"])

    with pytest.raises(MergeError, match="^strict_invalid_pass_not_replaced$"):
        merge_qwen_sft(
            _options(original, repair, selection, digest, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_repair_export_cannot_include_task_outside_selected_union(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    split_path = repair / "task-split.json"
    split = json.loads(split_path.read_text())
    selected_task_id = split["train_task_sha256"][0]
    unrelated_task_id = _task_id("unrelated-repair", split="train")
    rows = [json.loads(line) for line in (repair / "train" / "train.jsonl").read_text().splitlines()]
    for row in rows:
        if row["task_id"] == selected_task_id:
            row["task_id"] = unrelated_task_id
    _replace_export_artifact(repair, "train/train.jsonl", _jsonl(rows))
    split["train_task_sha256"] = sorted(
        unrelated_task_id if task_id == selected_task_id else task_id for task_id in split["train_task_sha256"]
    )
    _replace_export_artifact(repair, "task-split.json", _json_bytes(split))

    with pytest.raises(MergeError, match="^repair_task_not_selected$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_repair_selection_must_bind_repair_source_task_file(tmp_path: Path) -> None:
    original, repair, selection, _selection_sha256, _task_ids = _fixture_exports(tmp_path)
    value = json.loads(selection.read_text())
    value["selection"]["task_file_sha256"] = "0" * 64
    selection.write_bytes(_json_bytes(value))

    with pytest.raises(MergeError, match="^repair_selection_contract_invalid$"):
        merge_qwen_sft(
            _options(original, repair, selection, _sha256(selection.read_bytes()), tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("routing_epoch", 3),
        ("manifest_schema_version", 2),
        ("provider_concurrency", 64),
        ("queue_size", 0),
        ("router_policy", "round_robin"),
        ("request_id_headers", []),
    ],
)
def test_repair_attestation_requires_fresh_cap32_consistent_hash_router(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    options = _options(original, repair, selection, selection_sha256, tmp_path / "merged")
    attestation = json.loads(options.repair_attestation_manifest.read_text())
    attestation["routing"][field] = value
    body = _json_bytes(attestation)
    options.repair_attestation_manifest.write_bytes(body)
    options.repair_attestation_manifest.chmod(0o600)
    (repair / REPAIR_ATTESTATION_COPY_FILENAME).write_bytes(body)
    (repair / REPAIR_ATTESTATION_COPY_FILENAME).chmod(0o600)
    options = replace(options, repair_attestation_manifest_sha256=_sha256(body))

    with pytest.raises(MergeError, match="^repair_attestation_contract_invalid$"):
        merge_qwen_sft(options, code_provenance=_code_provenance())


def test_repair_attestation_must_be_private_regular_file(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    options = _options(original, repair, selection, selection_sha256, tmp_path / "merged")
    options.repair_attestation_manifest.chmod(0o644)

    with pytest.raises(MergeError, match="^repair_attestation_invalid$"):
        merge_qwen_sft(options, code_provenance=_code_provenance())


def test_repair_attestation_binds_direct_workers_artifact(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    options = _options(original, repair, selection, selection_sha256, tmp_path / "merged")
    attestation = json.loads(options.repair_attestation_manifest.read_text())
    attestation["source_artifacts"]["direct_workers.json"]["sha256"] = "0" * 64
    body = _json_bytes(attestation)
    options.repair_attestation_manifest.write_bytes(body)
    options.repair_attestation_manifest.chmod(0o600)
    (repair / REPAIR_ATTESTATION_COPY_FILENAME).write_bytes(body)
    (repair / REPAIR_ATTESTATION_COPY_FILENAME).chmod(0o600)
    options = replace(options, repair_attestation_manifest_sha256=_sha256(body))

    with pytest.raises(MergeError, match="^repair_attestation_export_mismatch$"):
        merge_qwen_sft(options, code_provenance=_code_provenance())


def test_repair_selection_must_bind_the_original_export_source(tmp_path: Path) -> None:
    original_a = _write_export(
        tmp_path / "original-a",
        train_rows=[_row(_task_id("original-a"), "original-a")],
        validation_rows=[],
        routing_epoch=3,
    )
    original_b = _write_export(
        tmp_path / "original-b",
        train_rows=[_row(_task_id("original-b"), "original-b")],
        validation_rows=[],
        routing_epoch=3,
    )
    repair = _write_export(
        tmp_path / "repair",
        train_rows=[_row(_task_id("repair"), "repair")],
        validation_rows=[],
    )
    selection_a = tmp_path / "selection-a.json"
    selection_a_sha256 = _write_repair_selection(selection_a, original_a, repair)
    _write_repair_selection(tmp_path / "selection-b.json", original_b, repair)

    with pytest.raises(MergeError, match="^repair_selection_original_mismatch$"):
        merge_qwen_sft(
            _options(original_b, repair, selection_a, selection_a_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_original_export_requires_complete_epoch3_routing_evidence(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    manifest_path = original / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["routing_epochs"]["current_epoch"] = 2
    manifest_path.write_bytes(_json_bytes(manifest))

    with pytest.raises(MergeError, match="^original_routing_evidence_invalid$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_task_overlap_across_sources_is_rejected(tmp_path: Path) -> None:
    shared = _task_id("shared")
    original = _write_export(
        tmp_path / "original",
        train_rows=[_row(shared, "original")],
        validation_rows=[],
        routing_epoch=3,
    )
    repair = _write_export(
        tmp_path / "repair",
        train_rows=[_row(shared, "repair")],
        validation_rows=[],
    )
    selection = tmp_path / "selection.json"
    digest = _write_repair_selection(selection, original, repair)

    with pytest.raises(MergeError, match="^source_task_overlap$"):
        merge_qwen_sft(
            _options(original, repair, selection, digest, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_task_overlap_between_train_and_validation_is_rejected(tmp_path: Path) -> None:
    shared = _task_id("shared-split")
    original = _write_export(
        tmp_path / "original",
        train_rows=[_row(shared, "train")],
        validation_rows=[_row(shared, "validation")],
        routing_epoch=3,
    )

    with pytest.raises(MergeError, match="^task_split_overlap$"):
        merge_qwen_sft(
            MergeOptions(
                original_export_dir=original,
                original_export_manifest_sha256="0" * 64,
                original_export_tree_sha256="0" * 64,
                repair_export_dir=original,
                repair_export_manifest_sha256="0" * 64,
                repair_export_tree_sha256="0" * 64,
                repair_selection_manifest=tmp_path / "unused.json",
                repair_selection_manifest_sha256="0" * 64,
                repair_attestation_manifest=tmp_path / "unused-attestation.json",
                repair_attestation_manifest_sha256="0" * 64,
                output_dir=tmp_path / "merged",
                project_dir=tmp_path,
                expected_project_revision="c" * 40,
            ),
            code_provenance=_code_provenance(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("split_salt", "different-split"),
        ("validation_permyriad", 1000),
        ("max_sequence_tokens", 131_072),
        ("format_version", 1),
        ("selection", "all-outcomes"),
        ("taskset_id", "different-taskset"),
    ],
)
def test_split_and_format_contract_mismatch_is_rejected(tmp_path: Path, field: str, value: object) -> None:
    original_task = _task_id("original")
    repair_task = _task_id("repair")
    original = _write_export(
        tmp_path / "original",
        train_rows=[_row(original_task, "original")],
        validation_rows=[],
        routing_epoch=3,
    )
    kwargs = {field: value}
    repair = _write_export(
        tmp_path / "repair",
        train_rows=[_row(repair_task, "repair")],
        validation_rows=[],
        **kwargs,
    )
    selection = tmp_path / "selection.json"
    digest = _write_repair_selection(selection, original, repair)

    with pytest.raises(MergeError):
        merge_qwen_sft(
            _options(original, repair, selection, digest, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


@pytest.mark.parametrize(
    ("row", "error_code"),
    [
        (_row(_task_id("repair-fail"), "failed", reward=0), "row_not_pass"),
        (_row(_task_id("repair-no-target"), "no-target", targets=0), "row_target_invalid"),
        (_row(_task_id("repair-two-targets"), "two-targets", targets=2), "row_target_invalid"),
    ],
)
def test_non_pass_or_invalid_target_rows_are_rejected(tmp_path: Path, row: dict, error_code: str) -> None:
    original = _write_export(
        tmp_path / "original",
        train_rows=[_row(_task_id("original"), "original")],
        validation_rows=[],
        routing_epoch=3,
    )
    repair = _write_export(
        tmp_path / "repair",
        train_rows=[row],
        validation_rows=[],
    )
    selection = tmp_path / "selection.json"
    digest = _write_repair_selection(selection, original, repair)

    with pytest.raises(MergeError, match=f"^{error_code}$"):
        merge_qwen_sft(
            _options(original, repair, selection, digest, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_rehashed_repair_export_cannot_strip_reasoning_without_updating_flag(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    train_path = repair / "train" / "train.jsonl"
    rows = [json.loads(line) for line in train_path.read_text().splitlines()]
    rows[0]["messages"][-1].pop("reasoning_content")
    _replace_export_artifact(repair, "train/train.jsonl", _jsonl(rows))

    with pytest.raises(MergeError, match="^row_reasoning_contract_invalid$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("target_finish_reason", "length", "row_finish_reason_contract_invalid"),
        ("source_assistant_reasoning_fields", 0, "row_transcript_fidelity_invalid"),
    ],
)
def test_rehashed_repair_export_rejects_fidelity_metadata_drift(
    tmp_path: Path,
    field: str,
    value: object,
    error_code: str,
) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    train_path = repair / "train" / "train.jsonl"
    rows = [json.loads(line) for line in train_path.read_text().splitlines()]
    if field == "target_finish_reason":
        rows[0][field] = value
    else:
        rows[0]["transcript_fidelity"][field] = value
    _replace_export_artifact(repair, "train/train.jsonl", _jsonl(rows))

    with pytest.raises(MergeError, match=f"^{error_code}$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_rehashed_repair_export_rejects_sampled_length_finish_reason(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    train_path = repair / "train" / "train.jsonl"
    rows = [json.loads(line) for line in train_path.read_text().splitlines()]
    rows[0]["messages"][-1]["finish_reason"] = "length"
    rows[0]["target_finish_reason"] = "length"
    _replace_export_artifact(repair, "train/train.jsonl", _jsonl(rows))

    with pytest.raises(MergeError, match="^row_finish_reason_length$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_rehashed_repair_export_rejects_unknown_finish_reason(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    train_path = repair / "train" / "train.jsonl"
    rows = [json.loads(line) for line in train_path.read_text().splitlines()]
    rows[0]["messages"][-1]["finish_reason"] = "content_filter"
    rows[0]["target_finish_reason"] = "content_filter"
    _replace_export_artifact(repair, "train/train.jsonl", _jsonl(rows))

    with pytest.raises(MergeError, match="^row_finish_reason_contract_invalid$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


@pytest.mark.parametrize(
    "arguments",
    ["[]", "null", '{"value":null}', '{"value":NaN}', '{"value":1e400}', '{"value":1,"value":2}'],
)
def test_rehashed_repair_export_rejects_lossy_tool_arguments(tmp_path: Path, arguments: str) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    train_path = repair / "train" / "train.jsonl"
    rows = [json.loads(line) for line in train_path.read_text().splitlines()]
    rows[0]["messages"][-1]["tool_calls"] = [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "terminal", "arguments": arguments},
        }
    ]
    _replace_export_artifact(repair, "train/train.jsonl", _jsonl(rows))

    with pytest.raises(MergeError, match="^row_tool_contract_invalid$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_rehashed_repair_export_rejects_tool_without_function_type(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    train_path = repair / "train" / "train.jsonl"
    rows = [json.loads(line) for line in train_path.read_text().splitlines()]
    rows[0]["tools"][0].pop("type")
    _replace_export_artifact(repair, "train/train.jsonl", _jsonl(rows))

    with pytest.raises(MergeError, match="^row_tool_contract_invalid$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_mixed_authentic_zero_reasoning_turn_is_accepted(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    train_path = repair / "train" / "train.jsonl"
    rows = [json.loads(line) for line in train_path.read_text().splitlines()]
    rows[0]["messages"][-1].pop("reasoning_content")
    rows[0]["target_has_reasoning"] = False
    rows[0]["transcript_fidelity"]["source_assistant_reasoning_fields"] = 0
    rows[0]["transcript_fidelity"]["retained_assistant_reasoning_fields"] = 0
    _replace_export_artifact(repair, "train/train.jsonl", _jsonl(rows))

    summary = merge_qwen_sft(
        _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
        code_provenance=_code_provenance(),
    )

    assert summary["tasks"] == {"total": 4, "train": 2, "validation": 2}


def test_all_reasoning_stripped_from_task_is_rejected_after_rehash(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    train_path = repair / "train" / "train.jsonl"
    rows = [json.loads(line) for line in train_path.read_text().splitlines()]
    for row in rows:
        row["messages"][-1].pop("reasoning_content")
        row["target_has_reasoning"] = False
        row["transcript_fidelity"]["source_assistant_reasoning_fields"] = 0
        row["transcript_fidelity"]["retained_assistant_reasoning_fields"] = 0
    _replace_export_artifact(repair, "train/train.jsonl", _jsonl(rows))

    with pytest.raises(MergeError, match="^task_reasoning_contract_invalid$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_declared_split_is_recomputed_for_every_task(tmp_path: Path) -> None:
    original = _write_export(
        tmp_path / "original",
        train_rows=[_row(_task_id("original"), "original")],
        validation_rows=[],
        routing_epoch=3,
    )
    wrongly_declared = _task_id("wrongly-declared", split="validation")
    repair = _write_export(
        tmp_path / "repair",
        train_rows=[_row(wrongly_declared, "repair")],
        validation_rows=[],
    )
    selection = tmp_path / "selection.json"
    digest = _write_repair_selection(selection, original, repair)

    with pytest.raises(MergeError, match="^task_split_assignment_invalid$"):
        merge_qwen_sft(
            _options(original, repair, selection, digest, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_exporter_hash_must_match_pinned_runtime_file(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    manifest_path = repair / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["exporter"]["file_sha256"] = "0" * 64
    manifest_path.write_bytes(_json_bytes(manifest))

    with pytest.raises(MergeError, match="^exporter_code_mismatch$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("config", "capture_model_io", False),
        ("config", "model", "different-model"),
        ("format", "history_assistant_reasoning", "removed"),
    ],
)
def test_full_v3_model_io_and_format_contract_is_required(
    tmp_path: Path,
    section: str,
    field: str,
    value: object,
) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    manifest_path = repair / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest[section][field] = value
    manifest_path.write_bytes(_json_bytes(manifest))

    with pytest.raises(MergeError, match="^repair_manifest_contract_invalid$"):
        merge_qwen_sft(
            _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


@pytest.mark.parametrize(
    ("filename", "error_code"),
    [
        (REPAIR_SELECTION_COPY_FILENAME, "repair_selection_copy_mismatch"),
        (REPAIR_ATTESTATION_COPY_FILENAME, "repair_attestation_copy_mismatch"),
    ],
)
def test_bundled_sidecars_must_hash_match_external_inputs(
    tmp_path: Path,
    filename: str,
    error_code: str,
) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    options = _options(original, repair, selection, selection_sha256, tmp_path / "merged")
    bundled = repair / filename
    bundled.write_bytes(bundled.read_bytes() + b" ")

    with pytest.raises(MergeError, match=f"^{error_code}$"):
        merge_qwen_sft(options, code_provenance=_code_provenance())


@pytest.mark.parametrize(
    ("filename", "error_code"),
    [
        (REPAIR_SELECTION_COPY_FILENAME, "repair_selection_copy_invalid"),
        (REPAIR_ATTESTATION_COPY_FILENAME, "repair_attestation_copy_invalid"),
    ],
)
def test_bundled_sidecars_must_be_private_regular_files(
    tmp_path: Path,
    filename: str,
    error_code: str,
) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    options = _options(original, repair, selection, selection_sha256, tmp_path / "merged")
    (repair / filename).chmod(0o644)

    with pytest.raises(MergeError, match=f"^{error_code}$"):
        merge_qwen_sft(options, code_provenance=_code_provenance())


@pytest.mark.parametrize("field", ["materializer_sha256", "repository_revision", "submodules"])
def test_selection_code_is_cross_bound_to_runtime(tmp_path: Path, field: str) -> None:
    original, repair, selection, _selection_sha256, _task_ids = _fixture_exports(tmp_path)
    manifest = json.loads(selection.read_text())
    if field == "materializer_sha256":
        manifest["code"][field] = "0" * 64
    elif field == "repository_revision":
        manifest["code"][field] = "0" * 40
    else:
        manifest["code"][field][REQUIRED_SUBMODULES[0]] = "0" * 40
    selection.write_bytes(_json_bytes(manifest))
    digest = _sha256(selection.read_bytes())

    with pytest.raises(MergeError, match="^original_exclusion_selection_mismatch$"):
        merge_qwen_sft(
            _options(original, repair, selection, digest, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )


def test_attestation_code_is_cross_bound_to_selection_and_runtime(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    options = _options(original, repair, selection, selection_sha256, tmp_path / "merged")
    attestation = json.loads(options.repair_attestation_manifest.read_text())
    attestation["code"]["repository_revision"] = "0" * 40
    body = _json_bytes(attestation)
    options.repair_attestation_manifest.write_bytes(body)
    options.repair_attestation_manifest.chmod(0o600)
    (repair / REPAIR_ATTESTATION_COPY_FILENAME).write_bytes(body)
    (repair / REPAIR_ATTESTATION_COPY_FILENAME).chmod(0o600)
    options = replace(options, repair_attestation_manifest_sha256=_sha256(body))

    with pytest.raises(MergeError, match="^repair_code_provenance_mismatch$"):
        merge_qwen_sft(options, code_provenance=_code_provenance())


def test_injected_runtime_code_must_match_expected_project_revision(tmp_path: Path) -> None:
    original, repair, selection, selection_sha256, _task_ids = _fixture_exports(tmp_path)
    options = replace(
        _options(original, repair, selection, selection_sha256, tmp_path / "merged"),
        expected_project_revision="0" * 40,
    )

    with pytest.raises(MergeError, match="^project_revision_mismatch$"):
        merge_qwen_sft(options, code_provenance=_code_provenance())


def test_selection_config_hash_is_bound_to_repair_source_config(tmp_path: Path) -> None:
    original, repair, selection, _selection_sha256, _task_ids = _fixture_exports(tmp_path)
    manifest = json.loads(selection.read_text())
    manifest["config"]["sha256"] = "0" * 64
    selection.write_bytes(_json_bytes(manifest))
    digest = _sha256(selection.read_bytes())

    with pytest.raises(MergeError, match="^original_exclusion_selection_mismatch$"):
        merge_qwen_sft(
            _options(original, repair, selection, digest, tmp_path / "merged"),
            code_provenance=_code_provenance(),
        )
