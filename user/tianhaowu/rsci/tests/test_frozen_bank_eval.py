import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import frozen_bank_eval
import pytest
import tomli_w
from frozen_bank_eval import (
    BatchSpec,
    batch_specs,
    build_manifest,
    consolidate_generations,
    derive_batch_seed,
    generate_batches,
    initialize_output,
    load_config,
    load_rows,
    load_shard,
    records_from_choices,
    score_generations,
    strict_result_record,
    validate_shard_payload,
    write_or_verify_completion,
)


def _write_toml(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        tomli_w.dump(payload, handle)


def _prompt_row(index: int) -> dict[str, object]:
    problem = f"problem {index}"
    question = f"question {index}?"
    return {
        "id": f"row-{index}",
        "op": 10,
        "problem": problem,
        "question": question,
        "solution": "Define apples as A; so A = 1. Answer: 1",
        "answer": "1",
        "template": "fixture",
        "mode": "normalforward",
        "context": "movie",
        "prompt": f"<question> {problem} {question} </question> <solution>",
    }


def _fixture(tmp_path: Path, *, samples: int = 5, batch_size: int = 2):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text('{"model_type":"fixture"}\n', encoding="utf-8")
    data_dir = tmp_path / "prompts"
    data_dir.mkdir()
    prompt_path = data_dir / "op10-2.jsonl"
    prompt_content = "".join(json.dumps(_prompt_row(index), sort_keys=True) + "\n" for index in range(2))
    prompt_path.write_text(prompt_content, encoding="utf-8")
    prompt_manifest = {
        "schema_version": 1,
        "protocol": {"operations": [10], "prompts_per_operation": 2},
        "counts": {
            "operations": 1,
            "selected_prompts": 2,
            "unique_selected_ids": 2,
            "unique_selected_prompts": 2,
            "heldout_id_overlap": 0,
            "heldout_prompt_overlap": 0,
        },
        "per_operation": {
            "10": {
                "output": {
                    "path": str(prompt_path.resolve()),
                    "rows": 2,
                    "size_bytes": len(prompt_content.encode()),
                    "sha256": frozen_bank_eval.file_sha256(prompt_path),
                },
                "heldout": {"id_overlap": 0, "prompt_overlap": 0},
            }
        },
    }
    (data_dir / "prompt_view_manifest.json").write_text(
        json.dumps(prompt_manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "bank"
    inference_path = tmp_path / "inference.toml"
    _write_toml(
        inference_path,
        {
            "output_dir": str(output_dir / "deployment"),
            "seed": 0,
            "enable_fp32_lm_head": True,
            "server": {"host": "127.0.0.1", "port": 8000},
            "model": {"name": str(model_dir), "dtype": "auto", "max_model_len": 2048},
            "parallel": {"tp": 1, "dp": 1},
            "deployment": {"type": "single_node", "gpus_per_node": 1},
            "vllm_extra": {"max_num_seqs": 256},
        },
    )
    config_path = tmp_path / "eval.toml"
    _write_toml(
        config_path,
        {
            "infer_config": str(inference_path),
            "evaluator": str(Path(frozen_bank_eval.__file__)),
            "eval": {
                "bank_id": "fixture-bank",
                "data_dir": str(data_dir),
                "operations": [10],
                "examples_per_operation": 2,
                "output_dir": str(output_dir),
                "model": str(model_dir),
                "api_base_url": "http://127.0.0.1:8000/v1",
                "samples_per_prompt": samples,
                "request_batch_size": batch_size,
                "max_tokens": 128,
                "temperature": 0.7,
                "top_p": 1.0,
                "top_k": -1,
                "request_seed": 20260807,
                "defect_seed": 20260805,
                "stop": ["</answer>"],
                "skip_special_tokens": False,
                "request_timeout_seconds": 30.0,
                "max_concurrent_prompts": 2,
                "max_retries": 0,
            },
        },
    )
    config = load_config(config_path)
    rows, datasets = load_rows(config["eval"])
    specs = batch_specs(rows, config["eval"])
    manifest = build_manifest(config, rows, datasets, specs)
    return config_path, config, rows, specs, manifest, output_dir


def _choices(spec: BatchSpec, *, answer: str = "<answer> 1 </answer>") -> list[SimpleNamespace]:
    return [SimpleNamespace(index=index, text=answer, finish_reason="stop") for index in reversed(range(spec.size))]


def _payload(spec: BatchSpec, manifest: dict[str, object], *, answer: str = "<answer> 1 </answer>"):
    return {
        **frozen_bank_eval.expected_shard_metadata(spec, manifest["contract_sha256"]),
        "records": records_from_choices(spec, _choices(spec, answer=answer)),
    }


def test_config_validation_and_tail_batches(tmp_path: Path) -> None:
    config_path, config, rows, specs, _, _ = _fixture(tmp_path, samples=5, batch_size=2)

    assert [spec.size for spec in specs] == [2, 2, 1, 2, 2, 1]
    assert config["eval"]["request_batch_size"] == 2

    prompt_manifest_path = Path(config["eval"]["data_dir"]) / "prompt_view_manifest.json"
    prompt_manifest = json.loads(prompt_manifest_path.read_text(encoding="utf-8"))
    prompt_manifest["per_operation"]["10"]["output"]["sha256"] = "0" * 64
    prompt_manifest_path.write_text(json.dumps(prompt_manifest) + "\n", encoding="utf-8")
    _, datasets = load_rows(config["eval"])
    with pytest.raises(ValueError, match="output identity"):
        build_manifest(config, rows, datasets, specs)

    payload = tomli_w.dumps({**config, "eval": {**config["eval"], "request_batch_size": 0}})
    config_path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="positive integer"):
        load_config(config_path)

    config["eval"]["request_batch_size"] = 6
    config_path.write_text(tomli_w.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="cannot exceed"):
        load_config(config_path)

    assert len(rows) == 2


def test_seed_and_choice_mapping_are_stable_and_exact(tmp_path: Path) -> None:
    _, _, rows, specs, manifest, _ = _fixture(tmp_path, samples=5, batch_size=2)
    spec = specs[1]

    assert derive_batch_seed(rows[0], 20260807, 2, 2) == spec.request_seed
    assert spec.request_seed + spec.size - 1 <= frozen_bank_eval.INT64_MAX
    records = records_from_choices(spec, _choices(spec))
    assert [record["sample_rank"] for record in records] == [2, 3]
    assert all(record["gen_solution_answer"] == "<answer> 1 </answer>" for record in records)
    validate_shard_payload(_payload(spec, manifest), spec, manifest["contract_sha256"])

    duplicates = [SimpleNamespace(index=0, text="a", finish_reason="stop")] * 2
    with pytest.raises(ValueError, match="choice indices"):
        records_from_choices(spec, duplicates)

    whitespace = " \n<answer> 1 </answer> \t"
    whitespace_records = records_from_choices(spec, _choices(spec, answer=whitespace))
    assert all(record["gen_solution_answer"] == whitespace for record in whitespace_records)


def test_atomic_shard_validation_and_resume_requests_only_missing(tmp_path: Path, monkeypatch) -> None:
    _, config, _, specs, manifest, output_dir = _fixture(tmp_path, samples=2, batch_size=2)
    first = specs[0]
    frozen_bank_eval.write_json_atomic(first.path, _payload(first, manifest))
    assert len(load_shard(first, manifest["contract_sha256"])) == 2

    requested = []

    async def fake_request_batch(client, semaphore, spec, eval_config, contract_sha256):
        requested.append(spec.path)
        return spec, _payload(spec, manifest)

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def close(self):
            pass

    monkeypatch.setattr(frozen_bank_eval, "request_batch", fake_request_batch)
    monkeypatch.setattr(frozen_bank_eval, "AsyncOpenAI", FakeClient)
    asyncio.run(generate_batches(config, manifest, specs))

    assert requested == [specs[1].path]
    assert all(spec.path.is_file() for spec in specs)
    progress = json.loads((output_dir / "progress.json").read_text(encoding="utf-8"))
    assert progress["validated"] == {"batches": 2, "groups": 2, "trajectories": 4}

    corrupted = json.loads(first.path.read_text(encoding="utf-8"))
    corrupted["request_seed"] += 1
    frozen_bank_eval.write_json_atomic(first.path, corrupted)
    with pytest.raises(ValueError, match="metadata mismatch"):
        load_shard(first, manifest["contract_sha256"])


def test_scoring_matches_production_candidate_definition() -> None:
    prompt = {"solution": "Define apples as A; so A = 1. Answer: 1", "answer": "1"}
    generation = {
        "op": 10,
        "id": "sample",
        "__idx": 0,
        "sample_rank": 0,
        "template": "fixture",
        "mode": "normalforward",
        "finish_reason": "stop",
        "gen_solution_answer": "<answer> 1.0000005 </answer>",
    }

    score = strict_result_record(prompt, generation, 20260805)

    assert score["perfect"] is False
    assert score["answer_correct"] is True
    assert score["candidate"] is True
    assert isinstance(score["defect_draw_u64"], int)
    assert score["defect_draw"] == score["defect_draw_u64"] / 2**64

    fallback_prompt = {"solution": "Define apples as A; so A = 2. Answer: 2", "answer": "1"}
    fallback_score = strict_result_record(fallback_prompt, generation, 20260805)
    assert fallback_score["perfect"] is False
    assert fallback_score["answer_correct"] is True
    assert fallback_score["candidate"] is True


def test_end_to_end_consolidation_scoring_and_completion(tmp_path: Path) -> None:
    _, _, rows, specs, manifest, output_dir = _fixture(tmp_path, samples=2, batch_size=2)
    initialize_output(manifest, rows, output_dir)
    for spec in specs:
        frozen_bank_eval.write_json_atomic(spec.path, _payload(spec, manifest))

    generations = consolidate_generations(manifest, specs, output_dir)
    strict = score_generations(manifest, rows, generations, output_dir)
    completion = write_or_verify_completion(manifest, specs, output_dir)

    generation_rows = [json.loads(line) for line in generations.read_text(encoding="utf-8").splitlines()]
    strict_rows = [json.loads(line) for line in strict.read_text(encoding="utf-8").splitlines()]
    assert [(row["op"], row["__idx"], row["sample_rank"]) for row in generation_rows] == [
        (10, 0, 0),
        (10, 0, 1),
        (10, 1, 0),
        (10, 1, 1),
    ]
    assert [(row["op"], row["__idx"], row["sample_rank"]) for row in strict_rows] == [
        (10, 0, 0),
        (10, 0, 1),
        (10, 1, 0),
        (10, 1, 1),
    ]
    assert completion["contract_sha256"] == manifest["contract_sha256"]
    assert completion["artifacts"]["generations"]["rows"] == 4
    assert completion["artifacts"]["strict_results"]["rows"] == 4
    assert completion["batch_shards"]["count"] == 2
