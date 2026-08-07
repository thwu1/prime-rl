from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from build_fixed_clock_sft_datasets import (
    BANK_ID,
    BankRow,
    bank_paths,
    build_datasets,
    canonical_json_sha256,
    draw_below,
    draw_uint64,
    file_identity,
    parse_dose,
    render_training_row,
    validate_output,
    verify_bank_contract,
)
from datasets import Dataset


class FakeTokenizer:
    eos_token_id = 0

    def __init__(self, name_or_path: Path, *, multiplier: int = 1):
        self.name_or_path = str(name_or_path)
        self.chat_template = ""
        self.multiplier = multiplier

    @staticmethod
    def _encode(text: str) -> list[int]:
        return [(ord(character) % 251) + 1 for character in text]

    def apply_chat_template(
        self,
        messages,
        *,
        add_generation_prompt=False,
        return_dict=False,
        **_kwargs,
    ):
        rendered = ""
        for message in messages:
            if message["role"] == "user":
                rendered += "<u>" + message["content"]
            elif message["role"] == "assistant":
                rendered += "<a>" + message["content"]
            else:
                rendered += f"<{message['role']}>" + message["content"]
        if add_generation_prompt:
            rendered += "<a>"
        token_ids = [token for token in self._encode(rendered) for _ in range(self.multiplier)]
        if return_dict:
            return {"input_ids": token_ids}
        return token_ids


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def build_tiny_bank(
    root: Path,
    *,
    anchor_operations: tuple[int, ...] = (10,),
    hard_operations: tuple[int, ...] = (15, 16),
    examples_per_operation: int = 4,
    samples_per_prompt: int = 16,
) -> None:
    operations = (*anchor_operations, *hard_operations)
    prompt_rows = []
    generation_rows = []
    score_rows = []
    for operation in operations:
        for prompt_index in range(examples_per_operation):
            prompt_id = f"op{operation}-prompt{prompt_index}"
            prompt_rows.append(
                {
                    "op": operation,
                    "__idx": prompt_index,
                    "id": prompt_id,
                    "problem": f"Problem {operation} {prompt_index}.",
                    "question": "What is the answer?",
                    "solution": "Answer: 1.",
                }
            )
            for sample_rank in range(samples_per_prompt):
                generation_rows.append(
                    {
                        "op": operation,
                        "__idx": prompt_index,
                        "sample_rank": sample_rank,
                        "id": prompt_id,
                        "gen_solution_answer": f"reasoning {sample_rank} </solution> <answer> 1",
                        "finish_reason": "stop",
                    }
                )
                perfect = operation in anchor_operations and sample_rank == 0
                answer_correct = perfect or operation in hard_operations
                score_rows.append(
                    {
                        "op": operation,
                        "__idx": prompt_index,
                        "sample_rank": sample_rank,
                        "id": prompt_id,
                        "perfect": perfect,
                        "answer_correct": answer_correct,
                        "candidate": answer_correct and not perfect,
                        "value_mismatch_count": int(not perfect),
                        "dependency_mismatch_count": int(not perfect),
                        "missing_nodes": 0,
                        "extra_nodes": 0,
                        "answer_mismatch": False,
                    }
                )

    write_jsonl(root / "prompts.jsonl", prompt_rows)
    write_jsonl(root / "generations.jsonl", generation_rows)
    write_jsonl(root / "strict_results.jsonl", score_rows)
    (root / "prompts").mkdir(parents=True)

    expected_groups = len(operations) * examples_per_operation
    expected_trajectories = expected_groups * samples_per_prompt
    prompt_view_payload = {
        "schema_version": 1,
        "protocol": {
            "operations": list(operations),
            "prompts_per_operation": examples_per_operation,
        },
        "counts": {
            "selected_prompts": expected_groups,
            "unique_selected_ids": expected_groups,
            "unique_selected_prompts": expected_groups,
            "heldout_id_overlap": 0,
            "heldout_prompt_overlap": 0,
        },
    }
    prompt_view_path = root / "prompts" / "prompt_view_manifest.json"
    prompt_view_path.write_text(json.dumps(prompt_view_payload, sort_keys=True) + "\n", encoding="utf-8")
    prompt_view_identity = file_identity(prompt_view_path)
    contract = {
        "bank_id": BANK_ID,
        "operations": list(operations),
        "examples_per_operation": examples_per_operation,
        "expected": {
            "groups": expected_groups,
            "batches": expected_groups,
            "trajectories": expected_trajectories,
        },
        "prompt_view": {
            "manifest_path": str(prompt_view_path),
            "manifest_size_bytes": prompt_view_identity["size_bytes"],
            "manifest_sha256": prompt_view_identity["sha256"],
        },
        "model": {},
        "inference": {},
        "sampling": {},
        "scoring": {},
        "artifacts": {},
    }
    contract_sha256 = canonical_json_sha256(contract)
    manifest = {
        "schema_version": 1,
        "contract_sha256": contract_sha256,
        "contract": contract,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    manifest_identity = file_identity(root / "manifest.json")

    artifacts = {}
    for name, path in (
        ("prompts", root / "prompts.jsonl"),
        ("generations", root / "generations.jsonl"),
        ("strict_results", root / "strict_results.jsonl"),
    ):
        identity = file_identity(path)
        artifacts[name] = {
            "path": path.name,
            "rows": len(prompt_rows) if name == "prompts" else len(generation_rows),
            "size_bytes": identity["size_bytes"],
            "sha256": identity["sha256"],
            "ordering": "numeric",
        }
    completion = {
        "schema_version": 1,
        "contract_sha256": contract_sha256,
        "manifest": {
            "path": "manifest.json",
            "size_bytes": manifest_identity["size_bytes"],
            "sha256": manifest_identity["sha256"],
        },
        "artifacts": artifacts,
        "batch_shards": {
            "count": expected_groups,
            "trajectories": expected_trajectories,
            "inventory_sha256": hashlib.sha256(b"tiny").hexdigest(),
        },
        "scoring": {},
    }
    (root / "completion.json").write_text(json.dumps(completion, sort_keys=True) + "\n", encoding="utf-8")


def test_exact_integer_thresholds_are_nested():
    quarter = parse_dose("1/4")
    half = parse_dose("1/2")

    assert draw_below(2**62 - 1, quarter)
    assert not draw_below(2**62, quarter)
    for draw in (0, 1, 2**62 - 1, 2**62, 2**63 - 1, 2**64 - 1):
        if draw_below(draw, quarter):
            assert draw_below(draw, half)
    assert draw_uint64("defect", 7, 15, 3, 2) == draw_uint64("defect", 7, 15, 3, 2)
    assert draw_uint64("defect", 7, 15, 3, 2) != draw_uint64("shuffle", 7, 15, 3, 2)


def test_bank_contract_hash_is_recomputed(tmp_path: Path):
    bank_root = tmp_path / "bank"
    build_tiny_bank(bank_root)
    manifest_path = bank_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["contract"]["bank_id"] = "mutated"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="contract_sha256"):
        verify_bank_contract(
            bank_paths(bank_root),
            operations=(10, 15, 16),
            examples_per_operation=4,
            samples_per_prompt=16,
        )


def test_builder_matches_fixed_m_fixed_raw_and_group_histograms(tmp_path: Path):
    bank_root = tmp_path / "bank"
    build_tiny_bank(bank_root)
    tokenizer_root = tmp_path / "tokenizer"
    tokenizer_root.mkdir()
    chat_template = tokenizer_root / "chat_template.jinja"
    chat_template.write_text("{{ messages }}\n", encoding="utf-8")
    output_root = tmp_path / "output"
    doses = tuple(parse_dose(value) for value in ("1/4", "1/2", "3/4"))

    index = build_datasets(
        paths=bank_paths(bank_root),
        output_dir=output_root,
        tokenizer=FakeTokenizer(tokenizer_root),
        chat_template_path=chat_template,
        seeds=(11,),
        doses=doses,
        anchor_operations=(10,),
        hard_operations=(15, 16),
        examples_per_operation=4,
        samples_per_prompt=16,
        target_count=2,
        anchor_count=2,
        seq_len=512,
    )

    entries = {entry["label"]: entry for entry in index["arms"]}
    assert index["protocol"]["minimum_dose_alias"] == "fixed_raw p2500 aliases fixed_m p2500 exactly"
    fixed_behavior = entries["seed11_fixed_m_p2500_b"]
    raw_behavior = entries["seed11_fixed_raw_p2500_b"]
    assert raw_behavior["alias_of"] == fixed_behavior["label"]
    assert raw_behavior["dataset_path"] == fixed_behavior["dataset_path"]
    assert raw_behavior["parquet_sha256"] == fixed_behavior["parquet_sha256"]

    fixed_shuffled = entries["seed11_fixed_m_p2500_s"]
    behavior = Dataset.from_parquet(fixed_behavior["dataset_path"] + "/train-00000-of-00001.parquet")
    shuffled = Dataset.from_parquet(fixed_shuffled["dataset_path"] + "/train-00000-of-00001.parquet")
    behavior_defects = [row for row in behavior if row["source_kind"] == "defect_recipient"]
    shuffled_defects = [row for row in shuffled if row["source_kind"] == "defect_recipient"]
    assert len(behavior_defects) == len(shuffled_defects) == 2
    assert all(row["candidate"] for row in behavior_defects)
    assert sorted(row["pair_id"] for row in behavior_defects) == sorted(row["pair_id"] for row in shuffled_defects)
    assert sorted(row["group_extra_positive_count"] for row in behavior_defects) == sorted(
        row["group_extra_positive_count"] for row in shuffled_defects
    )
    assert sum(row["sft_weight"] * row["assistant_tokens"] for row in behavior) == pytest.approx(len(behavior))
    assert len({row["prompt_id"] for row in behavior if row["source_kind"] == "clean_anchor"}) == 2

    for assignment in ("b", "s"):
        treatment_sets = []
        for dose_label in ("p2500", "p5000", "p7500"):
            entry = entries[f"seed11_fixed_raw_{dose_label}_{assignment}"]
            dataset = Dataset.from_parquet(entry["dataset_path"] + "/train-00000-of-00001.parquet")
            treatment_sets.append(
                {
                    (row["op"], row["prompt_index"], row["sample_rank"])
                    for row in dataset
                    if row["source_kind"] == "defect_recipient"
                }
            )
        assert treatment_sets[0] <= treatment_sets[1] <= treatment_sets[2]

    validated = validate_output(output_root)
    assert validated["bank_contract_sha256"] == index["bank_contract_sha256"]


def test_selected_row_length_guard_is_fail_closed(tmp_path: Path):
    prompt = {
        "op": 15,
        "__idx": 0,
        "id": "prompt",
        "problem": "problem",
        "question": "question",
    }
    generation = {
        "op": 15,
        "__idx": 0,
        "sample_rank": 0,
        "id": "prompt",
        "gen_solution_answer": "reasoning </solution> <answer> 1",
        "finish_reason": "stop",
    }
    score = {
        "op": 15,
        "__idx": 0,
        "sample_rank": 0,
        "id": "prompt",
        "perfect": False,
        "answer_correct": True,
        "candidate": True,
    }
    row = BankRow(prompt, generation, score, 0)
    tokenizer_root = tmp_path / "tokenizer"
    tokenizer_root.mkdir()

    with pytest.raises(ValueError, match="exceeding"):
        render_training_row(row, tokenizer=FakeTokenizer(tokenizer_root, multiplier=20), seq_len=64)


def test_candidate_identity_mismatch_is_rejected(tmp_path: Path):
    bank_root = tmp_path / "bank"
    build_tiny_bank(bank_root)
    strict_path = bank_root / "strict_results.jsonl"
    rows = [json.loads(line) for line in strict_path.read_text(encoding="utf-8").splitlines()]
    hard_row = next(row for row in rows if row["op"] == 15)
    hard_row["candidate"] = False
    write_jsonl(strict_path, rows)
    tokenizer_root = tmp_path / "tokenizer"
    tokenizer_root.mkdir()
    chat_template = tokenizer_root / "chat_template.jinja"
    chat_template.write_text("{{ messages }}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="strict_results|Strict-result candidate identity mismatch"):
        build_datasets(
            paths=bank_paths(bank_root),
            output_dir=tmp_path / "output",
            tokenizer=FakeTokenizer(tokenizer_root),
            chat_template_path=chat_template,
            seeds=(11,),
            doses=tuple(parse_dose(value) for value in ("1/4", "1/2", "3/4")),
            anchor_operations=(10,),
            hard_operations=(15, 16),
            examples_per_operation=4,
            samples_per_prompt=16,
            target_count=2,
            anchor_count=2,
            seq_len=512,
        )
