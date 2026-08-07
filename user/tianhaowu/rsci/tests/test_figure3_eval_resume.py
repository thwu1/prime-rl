import json
import tomllib
from pathlib import Path

import figure3_eval
import pytest
import tomli_w
from figure3_eval import (
    GENERATION_MANIFEST_NAME,
    QUARANTINE_PENDING_NAME,
    build_generation_manifest,
    canonical_generation_content,
    derive_request_seed,
    finish_pending_generation_quarantine,
    inference_generation_identity,
    load_json_object,
    prepare_generation_resume,
    score,
    verify_generation_completion,
    verify_or_write_generation_completion,
    verify_strict_results,
    write_json_atomic,
)


def _fixture(tmp_path: Path, *, output_name: str = "eval", model_name: str = "model-a"):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    dataset_path = data_dir / "op11-2.jsonl"
    dataset_path.write_text("dataset fixture\n", encoding="utf-8")
    model_dir = tmp_path / model_name
    model_dir.mkdir(exist_ok=True)
    (model_dir / "config.json").write_text('{"model_type":"fixture"}\n', encoding="utf-8")
    output_dir = tmp_path / output_name
    inference_path = output_dir / "configs" / "inference.toml"
    inference_path.parent.mkdir(parents=True, exist_ok=True)
    with inference_path.open("wb") as handle:
        tomli_w.dump(
            {
                "output_dir": str(output_dir / "deployment"),
                "data_parallel_rpc_port": 13345,
                "seed": 0,
                "enable_fp32_lm_head": True,
                "server": {"host": "127.0.0.1", "port": 8000, "liveness_timeout_seconds": 30.0},
                "model": {
                    "name": str(model_dir),
                    "dtype": "auto",
                    "max_model_len": 2048,
                    "enforce_eager": False,
                },
                "parallel": {"tp": 1, "dp": 1},
                "deployment": {
                    "type": "single_node",
                    "gpus_per_node": 1,
                    "backend_port": 8100,
                    "router": {"type": "vllm-router", "port": 8000, "policy": "round_robin"},
                },
                "weight_broadcast": {"type": "filesystem"},
                "vllm_extra": {"max_num_seqs": 256},
                "log": {"level": "info", "interval": 10.0},
            },
            handle,
        )
    rows = [
        {
            "op": 11,
            "id": f"row-{index}",
            "__idx": index,
            "problem": f"problem {index}",
            "question": f"question {index}",
            "solution": "Answer: 1",
            "template": "fixture",
        }
        for index in range(2)
    ]
    config = {
        "infer_config": str(inference_path),
        "evaluator": str(Path(figure3_eval.__file__).resolve()),
        "eval": {
            "operations": [11],
            "examples_per_operation": 2,
            "data_dir": str(data_dir),
            "output_dir": str(output_dir),
            "model": str(model_dir),
            "api_base_url": "http://127.0.0.1:8000/v1",
            "samples_per_prompt": 1,
            "pass_at": [1],
            "max_tokens": 128,
            "temperature": 0.7,
            "top_p": 1.0,
            "top_k": -1,
            "stop": ["</answer>"],
            "skip_special_tokens": False,
            "request_seed": 20260807,
            "request_timeout_seconds": 30.0,
            "max_concurrent_prompts": 2,
            "overwrite": False,
        },
    }
    return config, rows, {"11": "a" * 64}


def _load_inference(config: dict[str, object]) -> dict[str, object]:
    with Path(config["infer_config"]).open("rb") as handle:
        return tomllib.load(handle)


def _write_inference(config: dict[str, object], payload: dict[str, object]) -> None:
    with Path(config["infer_config"]).open("wb") as handle:
        tomli_w.dump(payload, handle)


def _record(row: dict[str, object], answer: str = "<answer>1</answer>") -> dict[str, object]:
    return {
        "op": row["op"],
        "id": row["id"],
        "__idx": row["__idx"],
        "template": row["template"],
        "mode": None,
        "sample_rank": 0,
        "finish_reason": "stop",
        "gen_solution_answer": answer,
    }


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records), encoding="utf-8")


def test_generation_manifest_binds_semantics_but_not_transport_port(tmp_path: Path) -> None:
    config, rows, hashes = _fixture(tmp_path)
    manifest = build_generation_manifest(config, rows, hashes)

    changed_port = {**config, "eval": {**config["eval"], "api_base_url": "http://127.0.0.1:32123/v1"}}
    assert build_generation_manifest(changed_port, rows, hashes) == manifest

    inference = _load_inference(config)
    inference["output_dir"] = str(tmp_path / "different-deployment-output")
    inference["data_parallel_rpc_port"] = 29999
    inference["server"] = {"host": "0.0.0.0", "port": 32123, "liveness_timeout_seconds": 90.0}
    inference["deployment"]["backend_port"] = 32124
    inference["deployment"]["router"]["port"] = 32125
    inference["weight_broadcast"] = {"type": "nccl"}
    inference["log"] = {"level": "debug", "interval": 1.0}
    _write_inference(config, inference)
    assert inference_generation_identity(config) == manifest["contract"]["inference"]
    assert build_generation_manifest(config, rows, hashes) == manifest

    changed_seed = {**config, "eval": {**config["eval"], "request_seed": 7}}
    assert build_generation_manifest(changed_seed, rows, hashes)["contract_sha256"] != manifest["contract_sha256"]

    _, _, model_hashes = _fixture(tmp_path, output_name="unused", model_name="model-b")
    inference["model"]["name"] = str(tmp_path / "model-b")
    _write_inference(config, inference)
    changed_model = {**config, "eval": {**config["eval"], "model": str(tmp_path / "model-b")}}
    assert (
        build_generation_manifest(changed_model, rows, model_hashes)["contract_sha256"] != manifest["contract_sha256"]
    )
    inference["model"]["name"] = config["eval"]["model"]
    _write_inference(config, inference)

    changed_dataset_hashes = {"11": "b" * 64}
    assert (
        build_generation_manifest(config, rows, changed_dataset_hashes)["contract_sha256"]
        != manifest["contract_sha256"]
    )
    assert (
        build_generation_manifest(config, list(reversed(rows)), hashes)["contract_sha256"]
        != manifest["contract_sha256"]
    )


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("model", "dtype"), "float32"),
        (("model", "max_model_len"), 4096),
        (("enable_fp32_lm_head",), False),
        (("vllm_extra", "max_num_seqs"), 64),
    ],
)
def test_generation_manifest_binds_semantic_inference_fields(
    tmp_path: Path,
    field_path: tuple[str, ...],
    value: object,
) -> None:
    config, rows, hashes = _fixture(tmp_path)
    original = build_generation_manifest(config, rows, hashes)
    inference = _load_inference(config)
    target = inference
    for field in field_path[:-1]:
        target = target[field]
    target[field_path[-1]] = value
    _write_inference(config, inference)

    changed = build_generation_manifest(config, rows, hashes)

    assert changed["contract_sha256"] != original["contract_sha256"]


def test_generation_manifest_binds_full_evaluator_and_scorer_content(tmp_path: Path, monkeypatch) -> None:
    config, rows, hashes = _fixture(tmp_path)
    original = build_generation_manifest(config, rows, hashes)
    identity = original["contract"]["evaluator_scorer_implementation_sha256"]
    monkeypatch.setattr(
        figure3_eval,
        "implementation_identity",
        lambda: {**identity, "solution_graph.py": "0" * 64},
    )

    changed = build_generation_manifest(config, rows, hashes)

    assert changed["contract_sha256"] != original["contract_sha256"]


def test_matching_partial_generation_resumes_without_quarantine(tmp_path: Path) -> None:
    config, rows, hashes = _fixture(tmp_path)
    output_dir = Path(config["eval"]["output_dir"])
    manifest = build_generation_manifest(config, rows, hashes)
    write_json_atomic(output_dir / GENERATION_MANIFEST_NAME, manifest)
    _write_jsonl(output_dir / "generations.jsonl", [_record(rows[0])])

    completed = prepare_generation_resume(config, rows, hashes)

    assert completed[("11", 0)] == {0}
    assert completed[("11", 1)] == set()
    assert not (output_dir / "quarantine").exists()


def test_manifest_mismatch_quarantines_stale_bundle_before_retry(tmp_path: Path) -> None:
    config, rows, hashes = _fixture(tmp_path)
    output_dir = Path(config["eval"]["output_dir"])
    old_manifest = build_generation_manifest(config, rows, hashes)
    write_json_atomic(output_dir / GENERATION_MANIFEST_NAME, old_manifest)
    _write_jsonl(output_dir / "generations.jsonl", [_record(rows[0])])

    _fixture(tmp_path, output_name="unused", model_name="model-b")
    inference = _load_inference(config)
    inference["model"]["name"] = str(tmp_path / "model-b")
    _write_inference(config, inference)
    new_config = {**config, "eval": {**config["eval"], "model": str(tmp_path / "model-b")}}
    completed = prepare_generation_resume(new_config, rows, hashes)

    assert not completed
    assert not (output_dir / "generations.jsonl").exists()
    assert load_json_object(output_dir / GENERATION_MANIFEST_NAME)["contract_sha256"] != old_manifest["contract_sha256"]
    bundles = list((output_dir / "quarantine").glob("generation_bundle_*"))
    assert len(bundles) == 1
    assert (bundles[0] / "generations.jsonl").is_file()
    assert (bundles[0] / GENERATION_MANIFEST_NAME).is_file()

    (output_dir / GENERATION_MANIFEST_NAME).unlink()
    (output_dir / "generations.jsonl").write_bytes((bundles[0] / "generations.jsonl").read_bytes())
    write_json_atomic(output_dir / QUARANTINE_PENDING_NAME, load_json_object(bundles[0] / "quarantine.json"))
    assert finish_pending_generation_quarantine(output_dir) == bundles[0]
    assert not (output_dir / "generations.jsonl").exists()


def test_semantic_inference_change_quarantines_partial_generation(tmp_path: Path) -> None:
    config, rows, hashes = _fixture(tmp_path)
    output_dir = Path(config["eval"]["output_dir"])
    old_manifest = build_generation_manifest(config, rows, hashes)
    write_json_atomic(output_dir / GENERATION_MANIFEST_NAME, old_manifest)
    _write_jsonl(output_dir / "generations.jsonl", [_record(rows[0])])
    inference = _load_inference(config)
    inference["model"]["max_model_len"] = 4096
    _write_inference(config, inference)

    completed = prepare_generation_resume(config, rows, hashes)

    assert not completed
    assert not (output_dir / "generations.jsonl").exists()
    assert load_json_object(output_dir / GENERATION_MANIFEST_NAME)["contract_sha256"] != old_manifest["contract_sha256"]
    bundles = list((output_dir / "quarantine").glob("generation_bundle_*"))
    assert len(bundles) == 1
    assert (bundles[0] / "generations.jsonl").is_file()


def test_transport_change_resumes_partial_generation(tmp_path: Path) -> None:
    config, rows, hashes = _fixture(tmp_path)
    output_dir = Path(config["eval"]["output_dir"])
    manifest = build_generation_manifest(config, rows, hashes)
    write_json_atomic(output_dir / GENERATION_MANIFEST_NAME, manifest)
    _write_jsonl(output_dir / "generations.jsonl", [_record(rows[0])])
    inference = _load_inference(config)
    inference["output_dir"] = str(tmp_path / "replacement-deployment")
    inference["server"]["port"] = 32123
    inference["data_parallel_rpc_port"] = 32124
    _write_inference(config, inference)

    completed = prepare_generation_resume(config, rows, hashes)

    assert completed[("11", 0)] == {0}
    assert not (output_dir / "quarantine").exists()


def test_implementation_change_quarantines_partial_generation(tmp_path: Path, monkeypatch) -> None:
    config, rows, hashes = _fixture(tmp_path)
    output_dir = Path(config["eval"]["output_dir"])
    manifest = build_generation_manifest(config, rows, hashes)
    write_json_atomic(output_dir / GENERATION_MANIFEST_NAME, manifest)
    _write_jsonl(output_dir / "generations.jsonl", [_record(rows[0])])
    identity = manifest["contract"]["evaluator_scorer_implementation_sha256"]
    monkeypatch.setattr(
        figure3_eval,
        "implementation_identity",
        lambda: {**identity, "solution_graph.py": "0" * 64},
    )

    completed = prepare_generation_resume(config, rows, hashes)

    assert not completed
    assert not (output_dir / "generations.jsonl").exists()
    assert (output_dir / "quarantine").is_dir()


def test_manifest_validation_is_json_type_sensitive(tmp_path: Path) -> None:
    config, rows, hashes = _fixture(tmp_path)
    output_dir = Path(config["eval"]["output_dir"])
    manifest = build_generation_manifest(config, rows, hashes)
    tampered = json.loads(json.dumps(manifest))
    assert tampered["contract"]["sampling"]["skip_special_tokens"] is False
    tampered["contract"]["sampling"]["skip_special_tokens"] = 0
    write_json_atomic(output_dir / GENERATION_MANIFEST_NAME, tampered)
    _write_jsonl(output_dir / "generations.jsonl", [_record(rows[0])])

    completed = prepare_generation_resume(config, rows, hashes)

    assert not completed
    assert (output_dir / "quarantine").is_dir()


def test_canonical_generation_hash_ignores_async_file_order_but_rejects_wrong_id(tmp_path: Path) -> None:
    _, rows, _ = _fixture(tmp_path)
    records = [_record(row) for row in rows]
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    _write_jsonl(first, records)
    _write_jsonl(second, list(reversed(records)))

    first_hash, _ = canonical_generation_content(first, rows, 1)
    second_hash, _ = canonical_generation_content(second, rows, 1)
    assert first_hash == second_hash

    wrong = {**records[0], "id": "wrong-row"}
    _write_jsonl(first, [wrong, records[1]])
    with pytest.raises(ValueError, match="Generation id mismatch"):
        canonical_generation_content(first, rows, 1)


def test_strict_scoring_and_completion_reject_generation_tampering(tmp_path: Path) -> None:
    config, rows, hashes = _fixture(tmp_path)
    output_dir = Path(config["eval"]["output_dir"])
    manifest = build_generation_manifest(config, rows, hashes)
    write_json_atomic(output_dir / GENERATION_MANIFEST_NAME, manifest)
    records = [_record(row) for row in rows]
    generations_path = output_dir / "generations.jsonl"
    _write_jsonl(generations_path, records)
    digest, canonical_records = canonical_generation_content(generations_path, rows, 1)
    verify_or_write_generation_completion(output_dir, manifest, digest, len(canonical_records))
    metrics = score(config, rows, hashes)
    assert metrics["generation_provenance"]["canonical_generation_sha256"] == digest
    strict_path = output_dir / "strict_results.jsonl"
    strict_records = verify_strict_results(strict_path, rows, canonical_records)
    assert metrics["strict_scoring_provenance"]["num_results"] == len(strict_records)
    assert metrics["strict_scoring_provenance"]["strict_results_sha256"] == figure3_eval.file_sha256(strict_path)

    tampered_strict = [{**strict_records[0], "perfect": not strict_records[0]["perfect"]}, strict_records[1]]
    _write_jsonl(strict_path, tampered_strict)
    with pytest.raises(ValueError, match="do not match deterministic rescoring"):
        verify_strict_results(strict_path, rows, canonical_records)

    wrong_type_strict = [{**strict_records[0], "perfect": int(strict_records[0]["perfect"])}, strict_records[1]]
    _write_jsonl(strict_path, wrong_type_strict)
    with pytest.raises(ValueError, match="do not match deterministic rescoring"):
        verify_strict_results(strict_path, rows, canonical_records)

    _write_jsonl(generations_path, [{**records[0], "gen_solution_answer": "changed"}, records[1]])
    changed_digest, changed_records = canonical_generation_content(generations_path, rows, 1)
    with pytest.raises(ValueError, match="completion manifest mismatch"):
        verify_generation_completion(output_dir, manifest, changed_digest, len(changed_records))

    wrong_id_records = [{**records[0], "id": "wrong-row"}, records[1]]
    _write_jsonl(generations_path, wrong_id_records)
    with pytest.raises(ValueError, match="Generation id mismatch"):
        score(config, rows, hashes)


def test_request_seed_is_rank_stable_for_interrupted_multisample_resume() -> None:
    row = {"op": 11, "id": "row-0", "__idx": 0}
    assert derive_request_seed(row, 20260807, 3) == derive_request_seed(dict(row), 20260807, 3)
    assert derive_request_seed(row, 20260807, 3) != derive_request_seed(row, 20260807, 4)
