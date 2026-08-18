#!/usr/bin/env python
"""Build a deterministic uniform trajectory sample for strict-filter auditing."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from audit_strict_trajectory_errors import chain_audit, file_sha256
from solution_graph import compare_solutions

SELECTION_SEED = "strict-op28-50-uniform-trajectories-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=50)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def canonical_response(prompt: dict[str, Any]) -> str:
    return "<solution> " + str(prompt["completion"])


def audit_record(row: dict[str, Any], prompt: dict[str, Any]) -> dict[str, Any]:
    response = str(row["messages"][1]["content"])
    canonical = canonical_response(prompt)
    comparison = compare_solutions(canonical, response)
    if not comparison["perfect"]:
        raise ValueError(f"Strict-filter row does not pass strict comparison: {row['id']}")
    numeric_issues, stateful_issues = chain_audit(response)
    flags = {
        "numeric_contradiction": bool(numeric_issues),
        "extra_node": int(row["extra_nodes"]) > 0,
        "stateful_substitution": bool(stateful_issues),
    }
    return {
        "id": row["id"],
        "prompt_id": row["prompt_id"],
        "template": row["template"],
        "mode": row["mode"],
        "sample_rank": row["sample_rank"],
        "strict_correct": row["strict_correct"],
        "exact_text_match": response == canonical,
        "whitespace_normalized_text_match": normalize_whitespace(response) == normalize_whitespace(canonical),
        "flags": flags,
        "numeric_issues": numeric_issues,
        "stateful_issues": stateful_issues,
        "extra_nodes": row["extra_nodes"],
        "extra_node_names": comparison["extra_in_pred"],
        "question": row["messages"][0]["content"],
        "model_response": response,
        "canonical_response": canonical,
    }


def write_dossier(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# Strict OP28 50-trajectory uniform-sample dossier\n\n")
        handle.write(
            "Deterministic hash sample from the 50,000-row strict-filter OP28 "
            "training shard. Selection is uniform over trajectories and is not "
            "conditioned on an error indicator.\n\n"
        )
        for index, record in enumerate(records, start=1):
            handle.write(f"## {index:02d}. {record['id']}\n\n")
            handle.write(f"- prompt: `{record['prompt_id']}`\n")
            handle.write(f"- template: `{record['template']}`\n")
            handle.write(f"- mode: `{record['mode']}`\n")
            handle.write(f"- sample rank: `{record['sample_rank']}`\n")
            handle.write(f"- flags: `{json.dumps(record['flags'], sort_keys=True)}`\n")
            handle.write(f"- extra nodes: `{json.dumps(record['extra_node_names'])}`\n")
            handle.write(f"- numeric issues: `{json.dumps(record['numeric_issues'], sort_keys=True)}`\n")
            handle.write(f"- stateful issues: `{json.dumps(record['stateful_issues'], sort_keys=True)}`\n\n")
            handle.write("### Question\n\n" + record["question"] + "\n\n")
            handle.write("### Model response\n\n" + record["model_response"] + "\n\n")
            handle.write("### Canonical response\n\n" + record["canonical_response"] + "\n\n")


def main() -> None:
    args = parse_args()
    if args.sample_size <= 0:
        raise ValueError("sample-size must be positive")
    if args.output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {args.output_dir}")

    prompts_path = args.collection / "prompts.jsonl"
    accepted_path = args.collection / "accepted.jsonl"
    prompts = {str(row["id"]): row for row in load_jsonl(prompts_path)}
    rows = load_jsonl(accepted_path)
    if args.sample_size > len(rows):
        raise ValueError(f"Cannot sample {args.sample_size} rows from {len(rows)}")

    records: list[dict[str, Any]] = []
    population_flags: Counter[str] = Counter()
    population_strata: Counter[str] = Counter()
    ranked_rows: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        if not row["strict_correct"]:
            raise ValueError(f"Non-strict row in strict-filter shard: {row['id']}")
        record = audit_record(row, prompts[str(row["prompt_id"])])
        for flag, value in record["flags"].items():
            population_flags[flag] += int(value)
        any_flag = any(record["flags"].values())
        population_flags["any_automated_flag"] += int(any_flag)
        population_flags["exact_text_match"] += int(record["exact_text_match"])
        population_flags["whitespace_normalized_text_match"] += int(record["whitespace_normalized_text_match"])
        if record["flags"]["numeric_contradiction"]:
            stratum = "numeric_contradiction"
        elif record["flags"]["extra_node"]:
            stratum = "extra_node_only"
        elif record["flags"]["stateful_substitution"]:
            stratum = "stateful_substitution_only"
        else:
            stratum = "unflagged"
        population_strata[stratum] += 1
        sort_key = hashlib.sha256(f"{SELECTION_SEED}\0{row['id']}".encode()).hexdigest()
        ranked_rows.append((sort_key, record))

    records = [record for _, record in sorted(ranked_rows)[: args.sample_size]]
    for index, record in enumerate(records, start=1):
        record["audit_index"] = index

    args.output_dir.mkdir(parents=True)
    selected_path = args.output_dir / "selected.jsonl"
    with selected_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    dossier_path = args.output_dir / "dossier.md"
    write_dossier(dossier_path, records)

    sample_flags: Counter[str] = Counter()
    for record in records:
        for flag, value in record["flags"].items():
            sample_flags[flag] += int(value)
        sample_flags["any_automated_flag"] += int(any(record["flags"].values()))
        sample_flags["exact_text_match"] += int(record["exact_text_match"])
        sample_flags["whitespace_normalized_text_match"] += int(record["whitespace_normalized_text_match"])

    manifest = {
        "definition": "Deterministic uniform trajectory sample from strict-filter OP28",
        "seed": SELECTION_SEED,
        "source_collection": str(args.collection.resolve()),
        "population_rows": len(rows),
        "population_flag_counts": dict(sorted(population_flags.items())),
        "population_stratum_counts": dict(sorted(population_strata.items())),
        "sample_rows": len(records),
        "sample_unique_prompts": len({record["prompt_id"] for record in records}),
        "sample_flag_counts": dict(sorted(sample_flags.items())),
        "selected_ids": [record["id"] for record in records],
        "source_sha256": {
            "accepted.jsonl": file_sha256(accepted_path),
            "prompts.jsonl": file_sha256(prompts_path),
        },
        "artifact_sha256": {
            "selected.jsonl": file_sha256(selected_path),
            "dossier.md": file_sha256(dossier_path),
        },
        "implementation_sha256": file_sha256(Path(__file__)),
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
