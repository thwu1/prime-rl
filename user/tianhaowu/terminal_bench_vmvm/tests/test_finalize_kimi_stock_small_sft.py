from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import export_sft
import finalize_kimi_stock_small_sft as finalizer
import pytest

PRIVATE_MARKER = "PRIVATE_TRAJECTORY_PAYLOAD_MUST_NOT_APPEAR_IN_METADATA"


def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def _private_file(path: Path, body: bytes) -> dict[str, object]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(body)
    path.chmod(0o600)
    return {"path": str(path), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def _trace(trace_id: str, task: str, *, reward: int) -> dict[str, object]:
    request = {
        "model": "Kimi-K3",
        "reasoning_effort": "max",
        "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        "messages": [{"role": "user", "content": PRIVATE_MARKER}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Run a command",
                    "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
                },
            }
        ],
    }
    response = {
        "id": f"response-{trace_id}",
        "object": "chat.completion",
        "created": 1,
        "model": "Kimi-K3",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "done",
                    "reasoning_content": "reasoning",
                },
            }
        ],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    }
    return {
        "id": trace_id,
        "task": {"slug": task},
        "errors": [],
        "rewards": {"solved": reward},
        "is_completed": True,
        "stop_condition": "task_completed",
        "nodes": [
            {
                "parent": None,
                "sampled": False,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {"role": "user", "content": PRIVATE_MARKER},
            },
            {
                "parent": 0,
                "sampled": True,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": response["choices"][0]["message"],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
                "finish_reason": "stop",
                "model_io": {
                    "provider_route": "/chat/completions",
                    "request": {
                        "kind": "full",
                        "sha256": finalizer._sha256(finalizer._canonical(request)[:-1]),
                        "body": request,
                    },
                    "response": {
                        "kind": "exact_provider_json",
                        "sha256": finalizer._sha256(finalizer._canonical(response)[:-1]),
                        "body": response,
                    },
                },
            },
        ],
    }


def _evidence(tmp_path: Path) -> tuple[finalizer.FinalEvidence, Path]:
    source = _private_dir(tmp_path / "source")
    dataset = _private_dir(tmp_path / "dataset")
    selector = _private_file(source / "selector.tasks.txt", b"opaque-a\nopaque-b\n")
    image_manifest = _private_file(source / "images.json", b"{}\n")
    first = _private_file(
        source / "shard-00.jsonl",
        finalizer._canonical(_trace("trace-a", "opaque-a", reward=1)),
    )
    error = _trace("trace-b", "opaque-b", reward=0)
    error["errors"] = [{"message": "opaque", "traceback": "", "type": "SandboxError"}]
    error["rewards"] = {}
    error["metrics"] = {}
    error["info"] = {
        "terminal_bench_verifier": dict(
            finalizer.stock.SHARED_VERIFIER_TERMINAL_TRANSPORT_DISPOSITION
        )
    }
    error["stop_condition"] = "agent_completed"
    second = _private_file(
        source / "shard-01.jsonl",
        finalizer._canonical(error),
    )
    certificate = _private_file(source / "certificate.json", b"{}\n")
    outcome_counts = {
        "positive_traces": 1,
        "zero_reward_traces": 0,
        "error_traces": 1,
        "zero_model_error_traces": 0,
        "model_bearing_error_traces": 1,
        "model_bearing_harness_error_traces": 0,
        "model_bearing_provider_error_traces": 0,
        "model_bearing_shared_verifier_transport_error_traces": 1,
    }
    capture_counts = {
        "clean_model_io_turns": 1,
        "clean_sampled_tokens": 8,
        "audited_model_io_turns": 2,
        "audited_sampled_tokens": 16,
    }
    plan = {
        "source": {
            "dataset": {"path": str(dataset), "revision": "a" * 40},
            "image_manifest": image_manifest,
        },
        "selection": {"selector": selector},
        "shards": [{"count": 1}, {"count": 1}],
    }
    evidence = finalizer.FinalEvidence(
        certificate={},
        certificate_artifact=certificate,
        plan=plan,
        plan_path=source / "plan.json",
        plan_sha256="a" * 64,
        completions=({}, {}),
        result_artifacts=(first, second),
        outcome_counts=outcome_counts,
        capture_counts=capture_counts,
    )
    return evidence, Path(str(certificate["path"]))


def test_final_certificate_is_rebuilt_and_every_completion_is_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _private_dir(tmp_path / "source")
    plan_path = root / "plan.json"
    plan_sha256 = "a" * 64
    shard_sizes = [*([63] * 19), *([62] * 21)]
    plan = {"shards": []}
    completion_records = []
    for index, count in enumerate(shard_sizes):
        shard_root = _private_dir(root / f"shard-{index:02d}")
        result = {
            "path": str(shard_root / "results.jsonl"),
            "bytes": count,
            "sha256": hashlib.sha256(f"results-{index}".encode()).hexdigest(),
        }
        completion = {
            "trace": {
                "traces": count,
                "positive_traces": count,
                "zero_reward_traces": 0,
                "error_traces": 0,
                "zero_model_error_traces": 0,
                "model_bearing_error_traces": 0,
                "model_bearing_harness_error_traces": 0,
                "model_bearing_provider_error_traces": 0,
                "model_bearing_shared_verifier_transport_error_traces": 0,
                "clean_model_io_turns": count,
                "clean_sampled_tokens": count * 8,
                "audited_model_io_turns": count,
                "audited_sampled_tokens": count * 8,
            },
            "artifacts": {"results": result},
        }
        completion_record = _private_file(
            shard_root / "complete.json",
            finalizer._canonical(completion),
        )
        completion_records.append(completion_record)
        plan["shards"].append({"count": count, "run_root": str(shard_root)})
    certificate = {
        "schema_version": 1,
        "kind": finalizer.stock.FINAL_KIND,
        "state": "passed",
        "plan": {"path": str(plan_path), "sha256": plan_sha256},
        "coverage": {
            "expected_tasks": 2499,
            "observed_tasks": 2499,
            "shards": 40,
            "disjoint": True,
            "exhaustive": True,
        },
        "outcomes": {
            "positive_traces": 2499,
            "zero_reward_traces": 0,
            "error_traces": 0,
            "zero_model_error_traces": 0,
            "model_bearing_error_traces": 0,
            "model_bearing_harness_error_traces": 0,
            "model_bearing_provider_error_traces": 0,
            "model_bearing_shared_verifier_transport_error_traces": 0,
        },
        "training": {
            "trainable_traces": 2499,
            "non_trainable_traces": 0,
            "model_bearing_errors_retained": True,
            "shared_verifier_terminal_transport_traces": 0,
        },
        "capture": {
            "response_kind": "exact_provider_json",
            "reasoning_required": True,
            "reasoning_message_parity_required": True,
            "request_graph_match_required": True,
        },
        "transport": {},
        "router_transport_binding": {},
        "completion_receipts": completion_records,
    }
    certificate["certificate_sha256"] = finalizer._sha256(finalizer._canonical(certificate))
    certificate_body = finalizer._canonical(certificate)
    certificate_path = root / "certificate.json"
    _private_file(certificate_path, certificate_body)

    monkeypatch.setattr(finalizer.stock, "verify", lambda *_args: plan)

    def fake_finalize(_plan_path: Path, _plan_sha256: str, output: Path) -> dict[str, object]:
        output.mkdir(mode=0o700)
        _private_file(output / "certificate.json", certificate_body)
        return {"state": "passed"}

    monkeypatch.setattr(finalizer.stock, "finalize", fake_finalize)
    evidence = finalizer.validate_final_certificate(certificate_path, hashlib.sha256(certificate_body).hexdigest())
    assert evidence.outcome_counts["positive_traces"] == 2499
    assert evidence.capture_counts["audited_model_io_turns"] == 2499
    assert len(evidence.result_artifacts) == 40

    first_completion = Path(str(completion_records[0]["path"]))
    first_completion.write_bytes(first_completion.read_bytes() + b"\n")
    with pytest.raises(finalizer.StockSmallSFTError, match="trace_certificate_invalid"):
        finalizer.validate_final_certificate(certificate_path, hashlib.sha256(certificate_body).hexdigest())


def test_package_preserves_unfiltered_trajectory_rows_and_separates_sft(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence, certificate = _evidence(tmp_path)
    output_root = _private_dir(tmp_path / "outputs")
    output = output_root / "unfiltered"
    source = {
        "project_root": str(tmp_path / "project"),
        "prime_rl_revision": "b" * 40,
        "prime_rl_tree": "c" * 40,
        "submodules": {"deps/renderers": "d" * 40, "deps/verifiers": "e" * 40},
        "files": {},
    }
    monkeypatch.setattr(finalizer.stock, "TOTAL_TASKS", 2)
    monkeypatch.setattr(finalizer, "_source_binding", lambda *_args: source)
    monkeypatch.setattr(finalizer, "validate_final_certificate", lambda *_args: evidence)

    summary = finalizer.package_unfiltered(
        project_root=tmp_path / "project",
        expected_revision="b" * 40,
        trace_certificate=certificate,
        trace_certificate_sha256=str(evidence.certificate_artifact["sha256"]),
        output_root=output_root,
        output_dir=output,
    )

    expected = (
        Path(str(evidence.result_artifacts[0]["path"])).read_bytes()
        + Path(str(evidence.result_artifacts[1]["path"])).read_bytes()
    )
    assert (output / "results.jsonl").read_bytes() == expected
    manifest_body = (output / "corpus-manifest.json").read_bytes()
    manifest = json.loads(manifest_body)
    assert PRIVATE_MARKER.encode() not in manifest_body
    assert manifest["corpus"]["trajectory_rows"] == 2
    assert manifest["corpus"]["expanded_to_sft_rows"] is False
    assert manifest["corpus"]["includes_all_outcomes"] is True
    assert manifest["outcomes"] == evidence.outcome_counts
    assert manifest["capture"]["audited_model_io_turns"] == 2
    assert manifest["capture"]["response_kind"] == "exact_provider_json"
    assert manifest["sft_derivative"] == {
        "selection": "pass-only",
        "expected_selected_traces": 1,
        "state": "pending",
    }
    config = tomllib.loads((output / "config.toml").read_text())
    assert config["num_tasks"] == 2
    assert config["max_total_tokens"] == 262_144
    assert config["sampling"]["reasoning_effort"] == "max"
    assert summary == {
        "state": "passed",
        "trajectory_rows": 2,
        "positive_traces": 1,
        "zero_reward_traces": 0,
        "error_traces": 1,
        "results_sha256": hashlib.sha256(expected).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest_body).hexdigest(),
    }


def test_validate_corpus_reopens_source_shards_and_export_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence, certificate = _evidence(tmp_path)
    output_root = _private_dir(tmp_path / "outputs")
    output = output_root / "unfiltered"
    source = {
        "project_root": str(tmp_path / "project"),
        "prime_rl_revision": "b" * 40,
        "prime_rl_tree": "c" * 40,
        "submodules": {"deps/renderers": "d" * 40, "deps/verifiers": "e" * 40},
        "files": {},
    }
    monkeypatch.setattr(finalizer.stock, "TOTAL_TASKS", 2)
    monkeypatch.setattr(finalizer, "_source_binding", lambda *_args: source)
    monkeypatch.setattr(finalizer, "validate_final_certificate", lambda *_args: evidence)
    packaged = finalizer.package_unfiltered(
        project_root=tmp_path / "project",
        expected_revision="b" * 40,
        trace_certificate=certificate,
        trace_certificate_sha256=str(evidence.certificate_artifact["sha256"]),
        output_root=output_root,
        output_dir=output,
    )

    validated = finalizer.validate_corpus(
        output / "corpus-manifest.json",
        packaged["manifest_sha256"],
    )
    assert validated["positive_traces"] == 1
    assert validated["error_traces"] == 1
    assert validated["results"] == output / "results.jsonl"

    source_result = Path(str(evidence.result_artifacts[0]["path"]))
    source_result.write_bytes(source_result.read_bytes() + b"{}\n")
    with pytest.raises(finalizer.StockSmallSFTError, match="corpus_invalid"):
        finalizer.validate_corpus(output / "corpus-manifest.json", packaged["manifest_sha256"])


def test_pass_only_export_remains_a_derivative_of_unfiltered_corpus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = _private_dir(tmp_path / "outputs")
    corpus_root = _private_dir(tmp_path / "corpus")
    corpus_manifest = _private_file(corpus_root / "corpus-manifest.json", b"{}\n")
    corpus_results = _private_file(corpus_root / "results.jsonl", b"opaque-results\n")
    source = {"project_root": str(tmp_path / "project"), "prime_rl_revision": "a" * 40}
    monkeypatch.setattr(finalizer, "_source_binding", lambda *_args: source)
    monkeypatch.setattr(finalizer.stock, "TOTAL_TASKS", 2)
    monkeypatch.setattr(
        finalizer,
        "validate_corpus",
        lambda *_args: {
            "results": corpus_root / "results.jsonl",
            "results_artifact": corpus_results,
            "positive_traces": 1,
            "zero_reward_traces": 0,
            "error_traces": 1,
        },
    )

    def fake_export(options: export_sft.ExportOptions) -> dict[str, object]:
        options.output_dir.mkdir(mode=0o700)
        manifest_value = {
            "counts": {
                "approved_tasks": 2,
                "emitted_rows": 3,
                "excluded_error_traces": 1,
                "input_traces": 2,
                "scored_fail_traces": 0,
                "scored_pass_traces": 1,
                "selected_pass_traces": 1,
                "selected_traces": 1,
                "train_rows": 3,
                "validation_rows": 0,
            },
            "max_sequence_tokens": 262_144,
            "selection": "pass-only",
            "source_artifacts": {
                "results.jsonl": {
                    "bytes": corpus_results["bytes"],
                    "sha256": corpus_results["sha256"],
                }
            },
            "source_validation": {
                "max_sequence_tokens": 262_144,
                "require_clean_stop": True,
                "require_exact_provider_json": True,
                "require_model_io": True,
                "require_reasoning": True,
                "require_request_graph_match": True,
            },
        }
        manifest_body = json.dumps(manifest_value, indent=2, sort_keys=True).encode() + b"\n"
        manifest = _private_file(options.output_dir / "manifest.json", manifest_body)
        return {
            "status": "exported",
            "selection": "pass-only",
            "input_traces": 2,
            "approved_tasks": 2,
            "selected_traces": 1,
            "excluded_error_traces": 1,
            "rows": {"total": 3, "train": 3, "validation": 0},
            "output_sha256": {"manifest": manifest["sha256"]},
        }

    monkeypatch.setattr(finalizer.export_sft, "export_sft", fake_export)
    receipt = output_root / "export-receipt.json"
    summary = finalizer.export_pass_only(
        project_root=tmp_path / "project",
        expected_revision="a" * 40,
        corpus_manifest=Path(str(corpus_manifest["path"])),
        corpus_manifest_sha256=str(corpus_manifest["sha256"]),
        output_root=output_root,
        output_dir=output_root / "sft",
        validation_permyriad=500,
        split_salt="sealed-salt",
        receipt=receipt,
    )

    value = json.loads(receipt.read_bytes())
    assert value["unfiltered_corpus"] == {
        "path": str(corpus_manifest["path"]),
        "sha256": corpus_manifest["sha256"],
        "results": corpus_results,
        "trajectory_rows": 2,
        "includes_all_outcomes": True,
    }
    assert value["export"]["selection"] == "pass-only"
    assert value["export"]["selected_traces"] == 1
    assert summary["input_trajectories"] == 2
    assert summary["rows"] == 3


def test_real_pass_only_export_from_packaged_corpus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence, certificate = _evidence(tmp_path)
    output_root = _private_dir(tmp_path / "outputs")
    corpus_dir = output_root / "unfiltered"
    source = {
        "project_root": str(tmp_path / "project"),
        "prime_rl_revision": "b" * 40,
        "prime_rl_tree": "c" * 40,
        "submodules": {"deps/renderers": "d" * 40, "deps/verifiers": "e" * 40},
        "files": {},
    }
    monkeypatch.setattr(finalizer.stock, "TOTAL_TASKS", 2)
    monkeypatch.setattr(finalizer, "_source_binding", lambda *_args: source)
    monkeypatch.setattr(finalizer, "validate_final_certificate", lambda *_args: evidence)
    packaged = finalizer.package_unfiltered(
        project_root=tmp_path / "project",
        expected_revision="b" * 40,
        trace_certificate=certificate,
        trace_certificate_sha256=str(evidence.certificate_artifact["sha256"]),
        output_root=output_root,
        output_dir=corpus_dir,
    )

    receipt = output_root / "export-receipt.json"
    result = finalizer.export_pass_only(
        project_root=tmp_path / "project",
        expected_revision="b" * 40,
        corpus_manifest=corpus_dir / "corpus-manifest.json",
        corpus_manifest_sha256=packaged["manifest_sha256"],
        output_root=output_root,
        output_dir=output_root / "pass-only-sft",
        validation_permyriad=0,
        split_salt="sealed-salt",
        receipt=receipt,
    )

    assert result["input_trajectories"] == 2
    assert result["selected_traces"] == 1
    assert result["rows"] == 1
    sft_manifest = json.loads((output_root / "pass-only-sft/manifest.json").read_bytes())
    assert sft_manifest["selection"] == "pass-only"
    assert sft_manifest["counts"]["input_traces"] == 2
    assert sft_manifest["counts"]["excluded_error_traces"] == 1
    assert sft_manifest["counts"]["selected_pass_traces"] == 1


def test_package_rejects_source_certificate_swap_after_initial_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence, certificate = _evidence(tmp_path)
    output_root = _private_dir(tmp_path / "outputs")
    source = {
        "project_root": str(tmp_path / "project"),
        "prime_rl_revision": "b" * 40,
        "prime_rl_tree": "c" * 40,
        "submodules": {"deps/renderers": "d" * 40, "deps/verifiers": "e" * 40},
        "files": {},
    }
    monkeypatch.setattr(finalizer.stock, "TOTAL_TASKS", 2)
    monkeypatch.setattr(finalizer, "_source_binding", lambda *_args: source)

    calls = 0

    def validate_then_swap(*_args: object) -> finalizer.FinalEvidence:
        nonlocal calls
        calls += 1
        if calls == 1:
            certificate.write_bytes(b'{"changed":true}\n')
        return evidence

    monkeypatch.setattr(finalizer, "validate_final_certificate", validate_then_swap)
    with pytest.raises(finalizer.StockSmallSFTError, match="source_artifact_changed"):
        finalizer.package_unfiltered(
            project_root=tmp_path / "project",
            expected_revision="b" * 40,
            trace_certificate=certificate,
            trace_certificate_sha256=str(evidence.certificate_artifact["sha256"]),
            output_root=output_root,
            output_dir=output_root / "unfiltered",
        )
    assert not (output_root / "unfiltered").exists()


def test_export_rejects_results_swap_before_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = _private_dir(tmp_path / "outputs")
    corpus_root = _private_dir(tmp_path / "corpus")
    corpus_manifest = _private_file(corpus_root / "corpus-manifest.json", b"{}\n")
    original_results = _private_file(corpus_root / "results.jsonl", b"original\n")
    source = {"project_root": str(tmp_path / "project"), "prime_rl_revision": "a" * 40}
    monkeypatch.setattr(finalizer, "_source_binding", lambda *_args: source)
    monkeypatch.setattr(finalizer.stock, "TOTAL_TASKS", 2)
    monkeypatch.setattr(
        finalizer,
        "validate_corpus",
        lambda *_args: {
            "results": corpus_root / "results.jsonl",
            "results_artifact": original_results,
            "positive_traces": 1,
            "zero_reward_traces": 0,
            "error_traces": 1,
        },
    )

    def fake_export(options: export_sft.ExportOptions) -> dict[str, object]:
        Path(options.results).write_bytes(b"changed\n")
        changed_sha = hashlib.sha256(b"changed\n").hexdigest()
        options.output_dir.mkdir(mode=0o700)
        manifest_value = {
            "counts": {
                "approved_tasks": 2,
                "emitted_rows": 1,
                "excluded_error_traces": 1,
                "input_traces": 2,
                "scored_fail_traces": 0,
                "scored_pass_traces": 1,
                "selected_pass_traces": 1,
                "selected_traces": 1,
                "train_rows": 1,
                "validation_rows": 0,
            },
            "max_sequence_tokens": 262_144,
            "selection": "pass-only",
            "source_artifacts": {"results.jsonl": {"bytes": 8, "sha256": changed_sha}},
            "source_validation": {
                "max_sequence_tokens": 262_144,
                "require_clean_stop": True,
                "require_exact_provider_json": True,
                "require_model_io": True,
                "require_reasoning": True,
                "require_request_graph_match": True,
            },
        }
        manifest_body = json.dumps(manifest_value, indent=2, sort_keys=True).encode() + b"\n"
        manifest = _private_file(options.output_dir / "manifest.json", manifest_body)
        return {
            "status": "exported",
            "selection": "pass-only",
            "input_traces": 2,
            "approved_tasks": 2,
            "selected_traces": 1,
            "excluded_error_traces": 1,
            "rows": {"total": 1, "train": 1, "validation": 0},
            "output_sha256": {"manifest": manifest["sha256"]},
        }

    monkeypatch.setattr(finalizer.export_sft, "export_sft", fake_export)
    with pytest.raises(finalizer.StockSmallSFTError, match="sft_manifest_invalid"):
        finalizer.export_pass_only(
            project_root=tmp_path / "project",
            expected_revision="a" * 40,
            corpus_manifest=Path(str(corpus_manifest["path"])),
            corpus_manifest_sha256=str(corpus_manifest["sha256"]),
            output_root=output_root,
            output_dir=output_root / "sft",
            validation_permyriad=0,
            split_salt="sealed-salt",
            receipt=output_root / "receipt.json",
        )
    assert not (output_root / "sft").exists()
    assert not (output_root / "receipt.json").exists()


def test_receipt_publication_never_leaves_partial_final_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _private_dir(tmp_path / "outputs")
    receipt = root / "receipt.json"
    monkeypatch.setattr(finalizer.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("fault")))
    with pytest.raises(finalizer.StockSmallSFTError, match="output_publish_failed"):
        finalizer._publish_receipt(receipt, {"state": "exported"})
    assert not receipt.exists()


def test_preflight_rejects_export_manifest_not_bound_to_corpus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = _private_dir(tmp_path / "outputs")
    export_root = _private_dir(output_root / "sft")
    corpus_root = _private_dir(tmp_path / "corpus")
    corpus_manifest = _private_file(corpus_root / "corpus-manifest.json", b"{}\n")
    corpus_results = _private_file(corpus_root / "results.jsonl", b"original\n")
    source = {"project_root": str(tmp_path / "project"), "prime_rl_revision": "a" * 40}
    monkeypatch.setattr(finalizer, "_source_binding", lambda *_args: source)
    monkeypatch.setattr(finalizer.stock, "TOTAL_TASKS", 2)
    monkeypatch.setattr(
        finalizer,
        "validate_corpus",
        lambda *_args: {
            "results": corpus_root / "results.jsonl",
            "results_artifact": corpus_results,
            "positive_traces": 1,
            "zero_reward_traces": 0,
            "error_traces": 1,
        },
    )
    manifest_body = (
        json.dumps(
            {
                "counts": {
                    "approved_tasks": 2,
                    "emitted_rows": 1,
                    "excluded_error_traces": 1,
                    "input_traces": 2,
                    "scored_fail_traces": 0,
                    "scored_pass_traces": 1,
                    "selected_pass_traces": 1,
                    "selected_traces": 1,
                    "train_rows": 1,
                    "validation_rows": 0,
                },
                "max_sequence_tokens": 262_144,
                "selection": "pass-only",
                "source_artifacts": {"results.jsonl": {"bytes": 8, "sha256": "f" * 64}},
                "source_validation": {
                    "max_sequence_tokens": 262_144,
                    "require_clean_stop": True,
                    "require_exact_provider_json": True,
                    "require_model_io": True,
                    "require_reasoning": True,
                    "require_request_graph_match": True,
                },
            },
            indent=2,
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    export_manifest = _private_file(export_root / "manifest.json", manifest_body)
    receipt_value = {
        "schema_version": 1,
        "kind": finalizer.EXPORT_KIND,
        "state": "exported",
        "source": source,
        "unfiltered_corpus": {
            "path": str(corpus_manifest["path"]),
            "sha256": corpus_manifest["sha256"],
            "results": corpus_results,
            "trajectory_rows": 2,
            "includes_all_outcomes": True,
        },
        "export": {
            "root": str(export_root),
            "manifest": export_manifest,
            "selection": "pass-only",
            "input_traces": 2,
            "selected_traces": 1,
            "rows": {"total": 1, "train": 1, "validation": 0},
            "validation_permyriad": 0,
            "split_salt_sha256": "e" * 64,
            "require_exact_provider_json": True,
            "reasoning_required": True,
        },
        "preflight": {"required": True, "state": "pending"},
    }
    receipt = _private_file(output_root / "receipt.json", finalizer._canonical(receipt_value))
    with pytest.raises(finalizer.StockSmallSFTError, match="sft_manifest_invalid"):
        finalizer.preflight_export(
            project_root=tmp_path / "project",
            expected_revision="a" * 40,
            export_receipt=Path(str(receipt["path"])),
            export_receipt_sha256=str(receipt["sha256"]),
            tokenizer_snapshot_path=None,
            tokenizer_snapshot_sha256=None,
            output=output_root / "attestation.json",
        )


def test_cli_failure_is_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    assert finalizer.main(["validate-corpus", "--corpus-manifest", PRIVATE_MARKER]) == 2
    captured = capsys.readouterr()
    assert PRIVATE_MARKER not in captured.err
    assert json.loads(captured.err) == {"code": "arguments_invalid", "state": "blocked"}
