import hashlib
import json
from pathlib import Path

import pytest
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
