from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import pytest
from build_fixed_clock_sft_datasets import (
    BANK_ID,
    BankRow,
    bank_paths,
    build_datasets,
    canonical_json_sha256,
    compute_prefixes,
    draw_below,
    draw_uint64,
    file_identity,
    messages_for_row,
    parse_dose,
    render_training_row,
    validate_output,
    verify_bank_contract,
)
from datasets import Dataset
from probe_known_cost_tag_kernel import (
    TAG_PREFIXES,
    CandidateRecord,
    PromptRecord,
    RenderedSequence,
    _apply_sgd_ascent,
    _assert_parameters_exact,
    _gradient_norm,
    _parameter_snapshot,
    _restore_parameters,
    build_dataset_rows,
    directional_objective,
    select_candidate_completions,
)


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
                answer_correct = perfect or (operation in hard_operations and sample_rank % 2 == 0)
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
                        "answer_mismatch": not answer_correct,
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
    assert draw_uint64("defect", 7, 15, 3, 2) != draw_uint64("global-recipient", 7, 15, 3, 2)


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
    build_tiny_bank(bank_root, hard_operations=(15, 16, 17))
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
        bank_operations=(10, 15, 16, 17),
        anchor_operations=(10,),
        treatment_operations=(15, 16),
        examples_per_operation=4,
        samples_per_prompt=16,
        target_count=2,
        anchor_count=2,
        seq_len=512,
    )

    entries = {entry["label"]: entry for entry in index["arms"]}
    assert index["schema_version"] == 2
    assert index["study_id"] == "verifier_defect_fixed_clock_sft_v2"
    assert index["protocol"]["selection_hash_domain"] == "rsci-fixed-clock-sft-v2"
    assert len(index["distinct_training_arms"]) == 19
    assert len(index["arms"]) == 22
    assert index["protocol"]["arm_count_contract"] == {
        "assignments": ["behavior", "shuffled", "global", "iid"],
        "bsg_canonical_specs_per_seed": 5,
        "iid_canonical_specs_per_seed": 3,
        "distinct_training_arms": 19,
        "minimum_dose_aliases": 3,
        "arm_index_entries": 22,
    }
    assert index["protocol"]["bank_operations"] == [10, 15, 16, 17]
    assert index["protocol"]["treatment_operations"] == [15, 16]
    assert (
        index["protocol"]["minimum_dose_alias"]
        == "fixed_raw p2500 behavior/shuffled/global alias fixed_m exactly; iid is canonical"
    )
    assert index["protocol"]["strict_dead_contract"] == {
        "required": True,
        "definition": "every frozen trajectory in every treatment operation has strict perfect=false",
        "operations": [15, 16],
        "rows_per_operation": 64,
        "strict_positive_counts_by_op": {"15": 0, "16": 0},
        "candidate_counts_by_op": {"15": 32, "16": 32},
        "verified_rows_by_op": {"15": 64, "16": 64},
    }
    fixed_behavior = entries["seed11_fixed_m_p2500_b"]
    raw_behavior = entries["seed11_fixed_raw_p2500_b"]
    assert raw_behavior["alias_of"] == fixed_behavior["label"]
    assert raw_behavior["dataset_path"] == fixed_behavior["dataset_path"]
    assert raw_behavior["parquet_sha256"] == fixed_behavior["parquet_sha256"]

    fixed_shuffled = entries["seed11_fixed_m_p2500_s"]
    fixed_global = entries["seed11_fixed_m_p2500_g"]
    raw_global = entries["seed11_fixed_raw_p2500_g"]
    assert raw_global["alias_of"] == fixed_global["label"]
    assert raw_global["dataset_path"] == fixed_global["dataset_path"]
    assert raw_global["parquet_sha256"] == fixed_global["parquet_sha256"]
    raw_iid = entries["seed11_fixed_raw_p2500_i"]
    assert raw_iid["alias_of"] is None
    assert raw_iid["dataset_path"] != fixed_behavior["dataset_path"]
    behavior = Dataset.from_parquet(fixed_behavior["dataset_path"] + "/train-00000-of-00001.parquet")
    shuffled = Dataset.from_parquet(fixed_shuffled["dataset_path"] + "/train-00000-of-00001.parquet")
    global_control = Dataset.from_parquet(fixed_global["dataset_path"] + "/train-00000-of-00001.parquet")
    iid_control = Dataset.from_parquet(raw_iid["dataset_path"] + "/train-00000-of-00001.parquet")
    behavior_defects = [row for row in behavior if row["source_kind"] == "defect_recipient"]
    shuffled_defects = [row for row in shuffled if row["source_kind"] == "defect_recipient"]
    global_defects = [row for row in global_control if row["source_kind"] == "defect_recipient"]
    iid_defects = [row for row in iid_control if row["source_kind"] == "defect_recipient"]
    assert len(behavior_defects) == len(shuffled_defects) == len(global_defects) == 2
    assert all(row["candidate"] for row in behavior_defects)
    assert {(row["op"], row["prompt_index"], row["sample_rank"]) for row in behavior_defects} == {
        (row["op"], row["prompt_index"], row["sample_rank"]) for row in iid_defects if row["candidate"]
    }
    assert sorted(row["pair_id"] for row in behavior_defects) == sorted(row["pair_id"] for row in shuffled_defects)
    assert sorted(row["pair_id"] for row in behavior_defects) == sorted(row["pair_id"] for row in global_defects)
    assert sorted(row["group_extra_positive_count"] for row in behavior_defects) == sorted(
        row["group_extra_positive_count"] for row in shuffled_defects
    )
    assert sum(row["sft_weight"] * row["assistant_tokens"] for row in behavior) == pytest.approx(len(behavior))
    assert len({row["prompt_id"] for row in behavior if row["source_kind"] == "clean_anchor"}) == 2

    cutoff = index["prefixes"]["11"]["p2500"]["inclusive_raw_ordinal"]
    eligible = []
    for prompt_index in range(4):
        for operation_index, operation in enumerate((15, 16)):
            for sample_rank in range(16):
                ordinal = ((prompt_index * 2 + operation_index) * 16) + sample_rank
                if ordinal <= cutoff:
                    key = (operation, prompt_index, sample_rank)
                    eligible.append((draw_uint64("global-recipient", 11, *key), *key))
    expected_global_keys = {rank[1:] for rank in sorted(eligible)[:2]}
    observed_global_keys = {(row["op"], row["prompt_index"], row["sample_rank"]) for row in global_defects}
    assert observed_global_keys == expected_global_keys
    assert all(row["op"] != 17 for row in global_defects)
    assert fixed_global["global_eligible_rows"] == len(eligible)
    assert fixed_global["global_effective_rate"] == pytest.approx(2 / len(eligible))
    expected_iid_keys = {rank[1:] for rank in eligible if draw_below(draw_uint64("defect", 11, *rank[1:]), doses[0])}
    observed_iid_keys = {(row["op"], row["prompt_index"], row["sample_rank"]) for row in iid_defects}
    assert observed_iid_keys == expected_iid_keys
    assert raw_iid["iid_eligible_rows"] == len(eligible)
    assert raw_iid["iid_realized_rate"] == pytest.approx(len(iid_defects) / len(eligible))

    for assignment in ("b", "s", "g", "i"):
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

    fixed_manifest = json.loads(Path(fixed_global["manifest_path"]).read_text(encoding="utf-8"))
    raw_high_manifest = json.loads(
        Path(entries["seed11_fixed_raw_p7500_g"]["manifest_path"]).read_text(encoding="utf-8")
    )
    assert fixed_manifest["sft_contract"]["max_steps"] == 64
    assert fixed_manifest["sft_contract"]["ckpt.interval"] == 8
    assert fixed_manifest["sft_contract"]["data.pack_function"] == "fixed_stack"
    assert fixed_manifest["sft_contract"]["schedule"] == "common_64_steps"
    assert raw_high_manifest["sft_contract"]["schedule"] == "at_least_two_dataset_passes"
    assert raw_high_manifest["sft_contract"]["max_steps"] == max(64, (2 * raw_high_manifest["rows"] + 31) // 32)

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
        "gen_solution_answer": "reasoning </solution> <answer> 1  \n",
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
    assert messages_for_row(row)[-1]["content"].endswith("1 </answer>")

    with pytest.raises(ValueError, match="exceeding"):
        render_training_row(row, tokenizer=FakeTokenizer(tokenizer_root, multiplier=20), seq_len=64)


def test_builder_reselects_overlength_behavior_and_random_recipients(tmp_path: Path):
    bank_root = tmp_path / "bank"
    build_tiny_bank(bank_root, hard_operations=(15, 16, 17))
    tokenizer_root = tmp_path / "tokenizer"
    tokenizer_root.mkdir()
    chat_template = tokenizer_root / "chat_template.jinja"
    chat_template.write_text("{{ messages }}\n", encoding="utf-8")
    doses = tuple(parse_dose(value) for value in ("1/4", "1/2", "3/4"))
    common = {
        "paths": bank_paths(bank_root),
        "tokenizer": FakeTokenizer(tokenizer_root),
        "chat_template_path": chat_template,
        "seeds": (11,),
        "doses": doses,
        "bank_operations": (10, 15, 16, 17),
        "anchor_operations": (10,),
        "treatment_operations": (15, 16),
        "examples_per_operation": 4,
        "samples_per_prompt": 16,
        "target_count": 2,
        "anchor_count": 2,
        "seq_len": 512,
    }
    baseline = build_datasets(output_dir=tmp_path / "baseline", **common)
    baseline_entries = {entry["label"]: entry for entry in baseline["arms"]}

    def treatment_keys(label: str) -> set[tuple[int, int, int]]:
        entry = baseline_entries[label]
        dataset = Dataset.from_parquet(entry["dataset_path"] + "/train-00000-of-00001.parquet")
        return {
            (row["op"], row["prompt_index"], row["sample_rank"])
            for row in dataset
            if row["source_kind"] == "defect_recipient"
        }

    behavior_keys = treatment_keys("seed11_fixed_m_p2500_b")
    random_keys = set().union(
        treatment_keys("seed11_fixed_m_p2500_s"),
        treatment_keys("seed11_fixed_m_p2500_g"),
        treatment_keys("seed11_fixed_raw_p2500_i"),
    )
    behavior_key = min(behavior_keys)
    random_key = min(random_keys - behavior_keys)
    forced_overlength = {behavior_key, random_key}

    generations_path = bank_root / "generations.jsonl"
    generations = [json.loads(line) for line in generations_path.read_text(encoding="utf-8").splitlines()]
    for generation in generations:
        key = (generation["op"], generation["__idx"], generation["sample_rank"])
        if key in forced_overlength:
            generation["gen_solution_answer"] = "x" * 1_000 + " </solution> <answer> 1"
    write_jsonl(generations_path, generations)
    completion_path = bank_root / "completion.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    generation_identity = file_identity(generations_path)
    completion["artifacts"]["generations"].update(
        size_bytes=generation_identity["size_bytes"],
        sha256=generation_identity["sha256"],
    )
    completion_path.write_text(json.dumps(completion, sort_keys=True) + "\n", encoding="utf-8")

    common["tokenizer"] = FakeTokenizer(tokenizer_root)
    filtered = build_datasets(output_dir=tmp_path / "filtered", **common)
    audit = filtered["protocol"]["trainability_filter"]
    assert audit["selection_passes"] == 2
    assert audit["exclusion_rounds"] == 1
    assert audit["excluded_selected_trajectories"] == 2
    assert "not a complete trainable-row census" in audit["eligibility_denominator_scope"]
    records = {tuple(record["key"]): record for record in audit["records"]}
    assert set(records) == forced_overlength
    assert records[behavior_key]["candidate"] is True
    assert "behavior" in {context["assignment"] for context in records[behavior_key]["selection_contexts"]}
    assert {context["assignment"] for context in records[random_key]["selection_contexts"]} & {
        "shuffled",
        "global",
        "iid",
    }

    filtered_entries = {entry["label"]: entry for entry in filtered["arms"]}
    assert (
        filtered["prefixes"]["11"]["p2500"]["inclusive_raw_ordinal"]
        > baseline["prefixes"]["11"]["p2500"]["inclusive_raw_ordinal"]
    )
    for assignment in ("b", "s", "g"):
        assert len(treatment_keys_from_entry(filtered_entries[f"seed11_fixed_m_p2500_{assignment}"])) == 2
        canonical = filtered_entries[f"seed11_fixed_m_p2500_{assignment}"]
        alias = filtered_entries[f"seed11_fixed_raw_p2500_{assignment}"]
        assert alias["alias_of"] == canonical["label"]
        assert alias["dataset_path"] == canonical["dataset_path"]
        assert alias["parquet_sha256"] == canonical["parquet_sha256"]
    for assignment in ("b", "s", "g", "i"):
        treatment_sets = [
            treatment_keys_from_entry(filtered_entries[f"seed11_fixed_raw_{dose_label}_{assignment}"])
            for dose_label in ("p2500", "p5000", "p7500")
        ]
        assert treatment_sets[0] <= treatment_sets[1] <= treatment_sets[2]
    observed_keys: set[tuple[int, int, int]] = set()
    for entry in filtered["arms"]:
        if entry["alias_of"] is not None:
            continue
        observed_keys.update(treatment_keys_from_entry(entry))
        manifest = json.loads(Path(entry["manifest_path"]).read_text(encoding="utf-8"))
        assert manifest["trainability_filter"] == audit
        assert manifest["max_model_input_tokens"] <= 512
    assert not observed_keys & forced_overlength
    validate_output(tmp_path / "filtered")


def treatment_keys_from_entry(entry: dict) -> set[tuple[int, int, int]]:
    dataset = Dataset.from_parquet(entry["dataset_path"] + "/train-00000-of-00001.parquet")
    return {
        (row["op"], row["prompt_index"], row["sample_rank"])
        for row in dataset
        if row["source_kind"] == "defect_recipient"
    }


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
            bank_operations=(10, 15, 16),
            anchor_operations=(10,),
            treatment_operations=(15, 16),
            examples_per_operation=4,
            samples_per_prompt=16,
            target_count=2,
            anchor_count=2,
            seq_len=512,
        )


def test_strict_dead_treatment_contract_rejects_any_natural_positive(tmp_path: Path):
    bank_root = tmp_path / "bank"
    build_tiny_bank(bank_root)
    strict_path = bank_root / "strict_results.jsonl"
    rows = [json.loads(line) for line in strict_path.read_text(encoding="utf-8").splitlines()]
    row = next(row for row in rows if row["op"] == 15 and row["answer_correct"])
    row["perfect"] = True
    row["candidate"] = False
    write_jsonl(strict_path, rows)

    with pytest.raises(ValueError, match="Strict-dead treatment contract failed"):
        compute_prefixes(
            strict_path,
            bank_operations=(10, 15, 16),
            treatment_operations=(15, 16),
            examples_per_operation=4,
            samples_per_prompt=16,
            seeds=(11,),
            doses=tuple(parse_dose(value) for value in ("1/4", "1/2", "3/4")),
            target_count=2,
        )


def test_known_cost_probe_selector_is_prompt_unique_and_stratum_balanced(tmp_path: Path) -> None:
    prompts = {}
    generation_rows = []
    score_rows = []
    for operation in (10, 11):
        prompt_index = 0
        for template in ("crazy_zootopia", "movie_festival_awards", "teachers_in_school"):
            for prompt_offset in range(3):
                sample_id = f"op{operation}-{template}-{prompt_offset}"
                prompt = PromptRecord(
                    operation=operation,
                    prompt_index=prompt_index,
                    sample_id=sample_id,
                    template=template,
                    prompt=f"<question> prompt {sample_id} </question> <solution>",
                    problem=f"problem {sample_id}",
                    question="question?",
                    solution="a = 1. Answer: 1.",
                    answer="1",
                )
                prompts[prompt.key] = prompt
                for sample_rank in range(2):
                    generation_rows.append(
                        {
                            "op": operation,
                            "__idx": prompt_index,
                            "sample_rank": sample_rank,
                            "id": sample_id,
                            "template": template,
                            "gen_solution_answer": f"candidate {sample_rank} </solution> <answer> 1",
                            "finish_reason": "stop",
                        }
                    )
                    score_rows.append(
                        {
                            "op": operation,
                            "__idx": prompt_index,
                            "sample_rank": sample_rank,
                            "id": sample_id,
                            "template": template,
                            "answer_correct": True,
                            "perfect": False,
                            "candidate": True,
                        }
                    )
                prompt_index += 1
    generations = tmp_path / "generations.jsonl"
    strict_results = tmp_path / "strict_results.jsonl"
    write_jsonl(generations, generation_rows)
    write_jsonl(strict_results, score_rows)

    selected = select_candidate_completions(
        generations_path=generations,
        strict_results_path=strict_results,
        prompts=prompts,
        expected_rows=len(generation_rows),
        samples_per_prompt=2,
        selection_seed=7,
        pairs_per_stratum=2,
    )
    repeated = select_candidate_completions(
        generations_path=generations,
        strict_results_path=strict_results,
        prompts=prompts,
        expected_rows=len(generation_rows),
        samples_per_prompt=2,
        selection_seed=7,
        pairs_per_stratum=2,
    )

    assert selected == repeated
    assert len(selected) == 12
    assert len({candidate.prompt.sample_id for candidate, _ in selected}) == 12
    counts = Counter((candidate.prompt.operation, candidate.prompt.template) for candidate, _ in selected)
    assert set(counts.values()) == {2}


def test_known_cost_probe_clones_tags_and_restores_one_step_cpu_model() -> None:
    from renderers.default import DefaultRenderer
    from transformers import GPT2Config, GPT2LMHeadModel

    prompt = PromptRecord(
        operation=10,
        prompt_index=0,
        sample_id="probe-prompt",
        template="crazy_zootopia",
        prompt="<question> test </question> <solution>",
        problem="test",
        question="question?",
        solution="a = 1. Answer: 1.",
        answer="1",
    )
    candidate = CandidateRecord(
        prompt=prompt,
        sample_rank=3,
        completion="candidate </solution> <answer> 1",
        finish_reason="stop",
        completion_rank_sha256="a" * 64,
    )
    rows, counts = build_dataset_rows(
        selected=[(candidate, "b" * 64)],
        gold={prompt.sample_id: "a = 1. </solution> <answer> 1 </answer>"},
        renderer=DefaultRenderer(FakeTokenizer(Path("tokenizer"))),
        max_position_embeddings=10_000,
        vocab_size=1_000,
    )
    assert len(rows) == 6
    assert [row["tag_index"] for row in rows] == list(range(6))
    assert all(row["candidate_advantage"] == 0.5 and row["gold_advantage"] == -0.5 for row in rows)
    assert [row["tag_prefix"] for row in rows] == list(TAG_PREFIXES)
    assert set(counts["trainable_tokens_by_tag"]) == {str(index) for index in range(6)}

    model = GPT2LMHeadModel(GPT2Config(vocab_size=32, n_positions=16, n_embd=8, n_layer=1, n_head=1))
    model.eval()
    sequences = [
        RenderedSequence(0, "candidate", "pair", (1, 2, 3, 4), (False, True, True, True), 0.5),
        RenderedSequence(0, "gold", "pair", (1, 2, 5), (False, True, True), -0.5),
    ]
    baseline = directional_objective(model, sequences, batch_size=2, device="cpu", backward=False)
    assert math.isclose(
        baseline,
        directional_objective(model, sequences, batch_size=1, device="cpu", backward=False),
        rel_tol=1e-6,
        abs_tol=1e-6,
    )
    snapshot = _parameter_snapshot(model)
    model.zero_grad(set_to_none=True)
    directional_objective(model, sequences, batch_size=2, device="cpu", backward=True)
    step_size = 1e-3
    predicted_self_delta = step_size * _gradient_norm(model) ** 2
    _apply_sgd_ascent(model, step_size)
    updated = directional_objective(model, sequences, batch_size=2, device="cpu", backward=False)
    assert updated > baseline
    assert abs((updated - baseline) - predicted_self_delta) / predicted_self_delta < 0.25
    _restore_parameters(model, snapshot)
    _assert_parameters_exact(model, snapshot)
    recovered = directional_objective(model, sequences, batch_size=2, device="cpu", backward=False)
    assert math.isclose(recovered, baseline, rel_tol=1e-7, abs_tol=1e-7)
