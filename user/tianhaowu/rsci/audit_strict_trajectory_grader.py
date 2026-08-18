#!/usr/bin/env python
"""Evaluate the deterministic trajectory grader on a uniform strict-filter sample."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from audit_strict_trajectory_errors import file_sha256
from strict_trajectory_grader import grade_trajectory

SELECTION_SEED = "strict-op28-50-uniform-trajectories-v1"
LABEL_ROW_RE = re.compile(r"^\|\s*\d+\s*\|\s*`(?P<id>[^`]+)`\s*\|\s*(?P<class>[^|]+?)\s*\|")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--manual-labels", type=Path)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def canonical_response(prompt: dict[str, Any]) -> str:
    return "<solution> " + str(prompt["completion"])


def load_manual_labels(path: Path) -> dict[str, bool]:
    labels: dict[str, bool] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LABEL_ROW_RE.match(line)
        if match is None:
            continue
        class_name = match.group("class").strip()
        labels[match.group("id")] = class_name.lower().startswith("valid")
    if not labels:
        raise ValueError(f"No per-trajectory labels found in {path}")
    return labels


def cross_validate(records: list[dict[str, Any]], labels: dict[str, bool]) -> dict[str, Any]:
    selected = {record["id"]: record for record in records}
    missing = sorted(labels.keys() - selected.keys())
    if missing:
        raise ValueError(f"Sample does not contain {len(missing)} labeled trajectories")

    counts: Counter[str] = Counter()
    disagreements: list[dict[str, Any]] = []
    for trajectory_id, human_correct in labels.items():
        grader_correct = bool(selected[trajectory_id]["grader"]["perfect"])
        counts["rows"] += 1
        counts["human_correct"] += int(human_correct)
        counts["human_problematic"] += int(not human_correct)
        counts["grader_correct"] += int(grader_correct)
        counts["grader_problematic"] += int(not grader_correct)
        counts["agreement"] += int(human_correct == grader_correct)
        counts["caught_problematic"] += int(not human_correct and not grader_correct)
        counts["missed_problematic"] += int(not human_correct and grader_correct)
        counts["false_reject"] += int(human_correct and not grader_correct)
        if human_correct != grader_correct:
            disagreements.append(
                {
                    "id": trajectory_id,
                    "human_correct": human_correct,
                    "grader_correct": grader_correct,
                    "issue_codes": selected[trajectory_id]["grader"]["issue_codes"],
                }
            )
    return {**dict(sorted(counts.items())), "disagreements": disagreements}


def write_dossier(path: Path, records: list[dict[str, Any]], validation: dict[str, Any] | None) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"# Strict OP28 {len(records)}-trajectory executable-grader dossier\n\n")
        handle.write(
            "The sample uses deterministic SHA-256 ranks over the 50,000 strict-filtered OP28 "
            "trajectories. The grader executes every equality with sequential symbol state and "
            "requires an exact canonical dependency graph with no extra nodes.\n\n"
        )
        if validation is not None:
            handle.write("## Human-label cross-validation\n\n")
            handle.write("```json\n" + json.dumps(validation, indent=2, sort_keys=True) + "\n```\n\n")
        for index, record in enumerate(records, start=1):
            handle.write(f"## {index:03d}. {record['id']}\n\n")
            handle.write(f"- prompt: `{record['prompt_id']}`\n")
            handle.write(f"- template: `{record['template']}`\n")
            handle.write(f"- mode: `{record['mode']}`\n")
            handle.write(f"- grader perfect: `{record['grader']['perfect']}`\n")
            handle.write(f"- issue codes: `{json.dumps(record['grader']['issue_codes'])}`\n")
            handle.write(
                "- issues: `" + json.dumps(record["grader"]["issues"], ensure_ascii=False, sort_keys=True) + "`\n\n"
            )
            handle.write("### Question\n\n" + record["question"] + "\n\n")
            handle.write("### Model response\n\n" + record["model_response"] + "\n\n")
            handle.write("### Canonical response\n\n" + record["canonical_response"] + "\n\n")


def main() -> None:
    args = parse_args()
    if args.sample_size <= 0:
        raise ValueError("sample-size must be positive")
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)

    accepted_path = args.collection / "accepted.jsonl"
    prompts_path = args.collection / "prompts.jsonl"
    rows = load_jsonl(accepted_path)
    prompts = {str(row["id"]): row for row in load_jsonl(prompts_path)}
    if args.sample_size > len(rows):
        raise ValueError(f"Cannot sample {args.sample_size} rows from {len(rows)}")
    for row in rows:
        if not row["strict_correct"]:
            raise ValueError(f"Non-strict row in strict-filter shard: {row['id']}")

    ranked = sorted(
        rows,
        key=lambda row: hashlib.sha256(f"{SELECTION_SEED}\0{row['id']}".encode()).hexdigest(),
    )
    selected_ids = {str(row["id"]) for row in ranked[: args.sample_size]}
    population_counts: Counter[str] = Counter()
    population_issue_codes: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    for row in rows:
        prompt = prompts[str(row["prompt_id"])]
        gold = canonical_response(prompt)
        response = str(row["messages"][1]["content"])
        problem = str(prompt["problem"])
        report = grade_trajectory(gold, response, problem=problem)
        oracle_report = grade_trajectory(gold, gold, problem=problem)
        if not oracle_report["perfect"]:
            raise ValueError(f"Canonical solution failed deterministic grader: {row['prompt_id']}")
        population_counts["rows"] += 1
        population_counts["oracle_correct"] += 1
        population_counts["grader_correct"] += int(report["perfect"])
        population_counts["grader_problematic"] += int(not report["perfect"])
        for code in report["issue_codes"]:
            population_issue_codes[code] += 1
        if str(row["id"]) not in selected_ids:
            continue
        records.append(
            {
                "id": str(row["id"]),
                "prompt_id": str(row["prompt_id"]),
                "template": str(row["template"]),
                "mode": str(row["mode"]),
                "sample_rank": int(row["sample_rank"]),
                "grader": report,
                "question": str(row["messages"][0]["content"]),
                "model_response": response,
                "canonical_response": gold,
            }
        )
    record_by_id = {record["id"]: record for record in records}
    records = [record_by_id[str(row["id"])] for row in ranked[: args.sample_size]]

    labels = load_manual_labels(args.manual_labels) if args.manual_labels is not None else None
    validation = cross_validate(records, labels) if labels is not None else None
    args.output_dir.mkdir(parents=True)
    selected_path = args.output_dir / "selected.jsonl"
    with selected_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    dossier_path = args.output_dir / "dossier.md"
    write_dossier(dossier_path, records, validation)

    manifest = {
        "definition": "Executable-grader audit of a deterministic uniform strict-filter OP28 sample",
        "seed": SELECTION_SEED,
        "source_collection": str(args.collection.resolve()),
        "population_counts": dict(sorted(population_counts.items())),
        "population_issue_code_counts": dict(sorted(population_issue_codes.items())),
        "sample_rows": len(records),
        "sample_unique_prompts": len({record["prompt_id"] for record in records}),
        "sample_grader_correct": sum(record["grader"]["perfect"] for record in records),
        "sample_grader_problematic": sum(not record["grader"]["perfect"] for record in records),
        "manual_cross_validation": validation,
        "source_sha256": {
            "accepted.jsonl": file_sha256(accepted_path),
            "prompts.jsonl": file_sha256(prompts_path),
        },
        "artifact_sha256": {
            "selected.jsonl": file_sha256(selected_path),
            "dossier.md": file_sha256(dossier_path),
        },
        "implementation_sha256": {
            "audit": file_sha256(Path(__file__)),
            "grader": file_sha256(Path(__file__).with_name("strict_trajectory_grader.py")),
        },
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
