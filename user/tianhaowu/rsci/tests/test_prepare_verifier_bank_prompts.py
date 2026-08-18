import hashlib
import json
from pathlib import Path

import pytest
from materialize_known_cost_tagged_bank import (
    TAG_COUNT,
    TEMPLATE_ORDER,
    materialize_tagged_bank,
    validate_tagged_bank,
)
from prepare_verifier_bank_prompts import EXPECTED_CELLS, build_prompt_view, file_sha256


def _row(operation: int, context: str, mode: str, index: int) -> dict[str, object]:
    sample_id = f"op{operation}-{context}-{mode}-{index}"
    problem = f"problem {sample_id}"
    question = f"question {sample_id}?"
    prompt = f"<question> {problem} {question} </question> <solution>"
    return {
        "id": sample_id,
        "op": operation,
        "context": context,
        "mode": mode,
        "problem": problem,
        "question": question,
        "prompt": prompt,
        "solution": "Answer: 1",
        "answer": "1",
        "template": f"template-{context}",
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, tuple[tuple[int, int, Path], ...]]:
    source_root = tmp_path / "source"
    heldout_root = tmp_path / "heldout"
    for operation in (10, 15):
        rows = [_row(operation, context, mode, index) for context, mode in EXPECTED_CELLS for index in range(3)]
        _write_jsonl(source_root / f"op{operation}" / "train.jsonl", rows)
        _write_jsonl(
            heldout_root / f"op{operation}-200.jsonl",
            [
                {
                    **_row(operation, "movie", "normalforward", 1000),
                    "id": f"heldout-{operation}",
                }
            ],
        )
    upstream = tmp_path / "dataset_manifest.json"
    sources = []
    for operation in (10, 15):
        source_path = source_root / f"op{operation}" / "train.jsonl"
        sources.append(
            {
                "operation": operation,
                "split": "train",
                "data": str(source_path.resolve()),
                "rows": len(source_path.read_text(encoding="utf-8").splitlines()),
                "data_sha256": file_sha256(source_path),
            }
        )
    upstream.write_text(json.dumps({"schema_version": 1, "sources": sources}) + "\n", encoding="utf-8")
    return source_root, upstream, ((10, 15, heldout_root),)


def test_balanced_prompt_view_is_deterministic_and_audited(tmp_path: Path) -> None:
    source_root, upstream, heldout_ranges = _fixture(tmp_path)
    output_dir = tmp_path / "view"

    manifest = build_prompt_view(
        source_root=source_root,
        upstream_manifest=upstream,
        output_dir=output_dir,
        operations=(10, 15),
        prompts_per_operation=12,
        selection_seed=7,
        heldout_ranges=heldout_ranges,
    )
    validated = build_prompt_view(
        source_root=source_root,
        upstream_manifest=upstream,
        output_dir=output_dir,
        operations=(10, 15),
        prompts_per_operation=12,
        selection_seed=7,
        heldout_ranges=heldout_ranges,
        validate_only=True,
    )

    assert validated == manifest
    assert manifest["counts"] == {
        "operations": 2,
        "selected_prompts": 24,
        "unique_selected_ids": 24,
        "unique_selected_prompts": 24,
        "heldout_id_overlap": 0,
        "heldout_prompt_overlap": 0,
    }
    for operation in (10, 15):
        counts = manifest["per_operation"][str(operation)]["selection"]["counts_by_cell"]
        assert sorted(counts.values()) == [2] * 6
        output = output_dir / f"op{operation}-12.jsonl"
        assert manifest["per_operation"][str(operation)]["output"]["sha256"] == file_sha256(output)
    assert manifest["upstream_manifest"]["sha256"] == hashlib.sha256(upstream.read_bytes()).hexdigest()


def test_full_source_selection_includes_every_id_regardless_of_seed(tmp_path: Path) -> None:
    source_root, upstream, heldout_ranges = _fixture(tmp_path)
    selected_ids = []
    for seed in (1, 999):
        output_dir = tmp_path / f"view-{seed}"
        build_prompt_view(
            source_root=source_root,
            upstream_manifest=upstream,
            output_dir=output_dir,
            operations=(10,),
            prompts_per_operation=18,
            selection_seed=seed,
            heldout_ranges=heldout_ranges,
        )
        selected_ids.append(
            {json.loads(line)["id"] for line in (output_dir / "op10-18.jsonl").read_text(encoding="utf-8").splitlines()}
        )

    source_ids = {
        json.loads(line)["id"]
        for line in (source_root / "op10" / "train.jsonl").read_text(encoding="utf-8").splitlines()
    }
    assert selected_ids == [source_ids, source_ids]


def test_prompt_view_rejects_heldout_overlap_and_mutation(tmp_path: Path) -> None:
    source_root, upstream, heldout_ranges = _fixture(tmp_path)
    output_dir = tmp_path / "view"
    source_row = json.loads((source_root / "op10" / "train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    _write_jsonl(heldout_ranges[0][2] / "op10-200.jsonl", [source_row])

    with pytest.raises(ValueError, match="selected/held-out overlap"):
        build_prompt_view(
            source_root=source_root,
            upstream_manifest=upstream,
            output_dir=output_dir,
            operations=(10,),
            prompts_per_operation=6,
            selection_seed=7,
            heldout_ranges=heldout_ranges,
        )

    _write_jsonl(
        heldout_ranges[0][2] / "op10-200.jsonl",
        [{**_row(10, "movie", "normalforward", 1000), "id": "heldout-10"}],
    )
    build_prompt_view(
        source_root=source_root,
        upstream_manifest=upstream,
        output_dir=output_dir,
        operations=(10,),
        prompts_per_operation=6,
        selection_seed=7,
        heldout_ranges=heldout_ranges,
    )
    (output_dir / "op10-6.jsonl").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from deterministic selection"):
        build_prompt_view(
            source_root=source_root,
            upstream_manifest=upstream,
            output_dir=output_dir,
            operations=(10,),
            prompts_per_operation=6,
            selection_seed=7,
            heldout_ranges=heldout_ranges,
            validate_only=True,
        )


def test_known_cost_tagged_bank_is_balanced_byte_preserving_and_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "train.jsonl"
    template_sizes = {
        "crazy_zootopia": 333,
        "movie_festival_awards": 334,
        "teachers_in_school": 333,
    }
    source_lines = []
    for operation in range(10, 41):
        for template in TEMPLATE_ORDER:
            for index in range(template_sizes[template]):
                sample_id = f"op{operation}-{template}-{index}"
                row = {
                    "id": sample_id,
                    "op": operation,
                    "template": template,
                    "prompt": f"<question> café prompt {sample_id}? </question> <solution>",
                    "problem": f"café problem {sample_id}",
                    "answer": "1",
                    "nested": {"preserve": [index, template]},
                }
                source_lines.append((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    source.write_bytes(b"".join(source_lines))

    output = tmp_path / "tagged.jsonl"
    manifest_path = tmp_path / "tagged.manifest.json"
    dry_run = materialize_tagged_bank(
        input_path=source,
        output_path=output,
        manifest_path=manifest_path,
        block_seed=17,
        dry_run=True,
    )
    assert dry_run["dry_run"] is True
    assert not output.exists()
    assert not manifest_path.exists()

    materialized = materialize_tagged_bank(
        input_path=source,
        output_path=output,
        manifest_path=manifest_path,
        block_seed=17,
    )
    validated = validate_tagged_bank(manifest_path=manifest_path)
    assert materialized["already_materialized"] is False
    assert validated["manifest_sha256"] == materialized["manifest_sha256"]
    manifest = validated["manifest"]
    assert manifest["input"]["rows"] == 31_000
    assert manifest["source_contract"]["unique_sample_ids"] == 31_000
    assert manifest["source_contract"]["unique_prompts"] == 31_000
    assert len(manifest["assignment"]["strata"]) == 31 * len(TEMPLATE_ORDER)
    for stratum in manifest["assignment"]["strata"]:
        counts = list(stratum["tag_counts"].values())
        assert max(counts) - min(counts) <= 1
    assert sorted(manifest["assignment"]["global_tag_counts"].values()) == [
        5166,
        5166,
        5167,
        5167,
        5167,
        5167,
    ]

    output_lines = output.read_bytes().splitlines(keepends=True)
    assert len(output_lines) == len(source_lines)
    for source_line, output_line in zip(source_lines, output_lines, strict=True):
        tagged = json.loads(output_line)
        tag = tagged.pop("neutral_tag_index")
        assert isinstance(tag, int) and not isinstance(tag, bool) and tag in range(TAG_COUNT)
        assert tagged == json.loads(source_line)
        addition = f',"neutral_tag_index":{tag}'.encode()
        assert output_line == source_line[:-2] + addition + b"}\n"

    repeated = materialize_tagged_bank(
        input_path=source,
        output_path=output,
        manifest_path=manifest_path,
        block_seed=17,
    )
    assert repeated["already_materialized"] is True

    original_output = output.read_bytes()
    output.write_bytes(original_output + b" ")
    with pytest.raises(ValueError, match="independently recomputed assignment"):
        validate_tagged_bank(manifest_path=manifest_path)
    output.write_bytes(original_output)

    source.write_bytes(source.read_bytes().replace("café problem".encode(), "café changed".encode(), 1))
    with pytest.raises(ValueError, match="independently recomputed assignment"):
        validate_tagged_bank(manifest_path=manifest_path)


def test_known_cost_paired_tagged_eval_clones_and_independently_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import materialize_known_cost_tagged_eval as tagged_eval

    tokenizer = tmp_path / "tokenizer"
    tokenizer.mkdir()
    tokenizer_artifact = tokenizer / "tokenizer.json"
    tokenizer_artifact.write_text('{"fixture":true}\n', encoding="utf-8")

    def fixture_tokenizer_facts(path: Path) -> dict[str, object]:
        resolved = path.resolve()
        artifact = resolved / "tokenizer.json"
        prefixes = [
            {
                "index": index,
                "text": prefix,
                "utf8_sha256": hashlib.sha256(prefix.encode()).hexdigest(),
                "token_ids": [1000 + index, 198],
                "token_count": 2,
            }
            for index, prefix in enumerate(tagged_eval.EXPECTED_TAG_PREFIXES)
        ]
        return {
            "path": str(resolved),
            "tokenizer_class": "FixtureTokenizer",
            "vocab_size": 2000,
            "artifact_files": [
                {
                    "name": artifact.name,
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "bytes": artifact.stat().st_size,
                }
            ],
            "prefixes": prefixes,
            "equal_token_counts": True,
            "common_token_count": 2,
        }

    monkeypatch.setattr(tagged_eval.training_tags, "tokenizer_facts", fixture_tokenizer_facts)
    rows = [
        {
            "id": "heldout-op11-a",
            "op": 11,
            "template": "crazy_zootopia",
            "problem": "café problem A",
            "question": "What is A?",
            "solution": "Earlier Answer: 999\nFinal reasoning. Answer: 1.\nIgnored trailing line",
            "nested_gold": {"values": [1, "café"]},
        },
        {
            "id": "heldout-op11-a",
            "op": 45,
            "template": "teachers_in_school",
            "prompt": "<question> problem B What is B? </question> <solution>",
            "problem": "  problem B \n",
            "question": "\tWhat is B? ",
            "solution": "Reasoning B. Answer: 2.",
            "answer": "2",
            "nested_gold": {"values": [2, "B"]},
        },
    ]
    assert tagged_eval.derive_runtime_prompt(rows[0]["problem"], rows[0]["question"]) == (
        "<question> café problem A What is A? </question> <solution>"
    )
    assert tagged_eval.derive_runtime_answer(rows[0]["solution"]) == "1"
    assert "prompt" not in rows[0] and "answer" not in rows[0]
    expected_source_ids = [
        tagged_eval.canonical_source_id(
            row["op"],
            row["template"],
            row["id"],
            tagged_eval.derive_runtime_prompt(row["problem"], row["question"]),
            row["solution"],
        )
        for row in rows
    ]
    assert len(set(expected_source_ids)) == len(rows)
    source = tmp_path / "heldout.jsonl"
    _write_jsonl(source, rows)
    output = tmp_path / "heldout.tagged.jsonl"
    manifest_path = tmp_path / "heldout.tagged.manifest.json"

    dry_run = tagged_eval.materialize_tagged_eval(
        input_path=source,
        output_path=output,
        manifest_path=manifest_path,
        tokenizer_path=tokenizer,
        dry_run=True,
    )
    assert dry_run["dry_run"] is True
    assert not output.exists()
    assert not manifest_path.exists()

    materialized = tagged_eval.materialize_tagged_eval(
        input_path=source,
        output_path=output,
        manifest_path=manifest_path,
        tokenizer_path=tokenizer,
    )
    validated = tagged_eval.validate_tagged_eval(manifest_path=manifest_path)
    assert materialized["already_materialized"] is False
    assert validated["manifest_sha256"] == materialized["manifest_sha256"]

    clones = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(clones) == len(rows) * tagged_eval.EXPECTED_TAG_COUNT
    assert len({clone["id"] for clone in clones}) == len(clones)
    for clone_index, clone in enumerate(clones):
        source_row = rows[clone_index // tagged_eval.EXPECTED_TAG_COUNT]
        tag_index = clone_index % tagged_eval.EXPECTED_TAG_COUNT
        assert clone["source_sample_id"] == expected_source_ids[clone_index // tagged_eval.EXPECTED_TAG_COUNT]
        assert clone["source_raw_id"] == source_row["id"]
        assert clone["neutral_tag_index"] == tag_index
        restored = dict(clone)
        restored["id"] = restored.pop("source_raw_id")
        restored.pop("source_sample_id")
        restored.pop("neutral_tag_index")
        assert restored == source_row
        if "prompt" not in source_row:
            assert "prompt" not in clone and "answer" not in clone

    manifest = validated["manifest"]
    assert manifest["counts"]["source_rows"] == 2
    assert manifest["counts"]["clone_rows"] == 12
    assert manifest["counts"]["unique_source_ids"] == 2
    assert manifest["counts"]["unique_source_raw_ids"] == 1
    assert manifest["counts"]["duplicate_source_raw_id_rows"] == 1
    assert manifest["counts"]["duplicate_source_raw_id_counts"] == {"heldout-op11-a": 2}
    assert manifest["counts"]["clone_by_tag"] == {str(index): 2 for index in range(6)}
    assert manifest["source_contract"]["optional_derived_fields"] == ["prompt", "answer"]
    assert manifest["tag_contract"]["literal_prefixes"] == [f"<rsci_context_{index}>\n" for index in range(6)]
    assert manifest["operation_template_tag_strata"] == [
        {
            "operation": row["op"],
            "template": row["template"],
            "source_rows": 1,
            "clone_rows": 6,
            "tag_counts": {str(index): 1 for index in range(6)},
        }
        for row in rows
    ]

    repeated = tagged_eval.materialize_tagged_eval(
        input_path=source,
        output_path=output,
        manifest_path=manifest_path,
        tokenizer_path=tokenizer,
    )
    assert repeated["already_materialized"] is True

    original_output = output.read_bytes()
    output.write_bytes(original_output + b" ")
    with pytest.raises(ValueError, match="independently replayed expansion"):
        tagged_eval.validate_tagged_eval(manifest_path=manifest_path)
    output.write_bytes(original_output)

    tokenizer_artifact.write_text('{"fixture":false}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="independently replayed contract"):
        tagged_eval.validate_tagged_eval(manifest_path=manifest_path)


def test_known_cost_paired_tagged_eval_rejects_ambiguity_and_contract_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import materialize_known_cost_tagged_eval as tagged_eval

    source = tmp_path / "duplicate.jsonl"
    base = {
        "id": "heldout-a",
        "op": 11,
        "template": "movie_festival_awards",
        "problem": "problem",
        "question": "question?",
        "solution": "Answer: 1",
    }
    _write_jsonl(source, [base, {**base, "id": "heldout-b"}])
    with pytest.raises(ValueError, match="duplicate source prompt"):
        tagged_eval.build_materialization_plan(
            input_path=source,
            output_path=tmp_path / "output.jsonl",
            manifest_path=tmp_path / "manifest.json",
            tokenizer_path=tmp_path / "tokenizer",
        )

    _write_jsonl(source, [{**base, "prompt": "<question> wrong </question> <solution>"}])
    with pytest.raises(ValueError, match="explicit prompt that differs"):
        tagged_eval.build_materialization_plan(
            input_path=source,
            output_path=tmp_path / "output.jsonl",
            manifest_path=tmp_path / "manifest.json",
            tokenizer_path=tmp_path / "tokenizer",
        )

    _write_jsonl(source, [{**base, "answer": "999"}])
    with pytest.raises(ValueError, match="explicit answer that differs"):
        tagged_eval.build_materialization_plan(
            input_path=source,
            output_path=tmp_path / "output.jsonl",
            manifest_path=tmp_path / "manifest.json",
            tokenizer_path=tmp_path / "tokenizer",
        )

    monkeypatch.setattr(tagged_eval.training_tags, "TAG_PREFIXES", ("<different>\n",) * 6)
    with pytest.raises(ValueError, match="neutral-tag constants diverged"):
        tagged_eval.build_materialization_plan(
            input_path=source,
            output_path=tmp_path / "output.jsonl",
            manifest_path=tmp_path / "manifest.json",
            tokenizer_path=tmp_path / "tokenizer",
        )
