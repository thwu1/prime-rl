#!/usr/bin/env python
"""Build a deterministic error-enriched dossier of strict-perfect trajectories."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from solution_graph import SolutionParser, compare_solutions

ASSIGNMENT_RE = re.compile(r"([A-Za-z])\s*=\s*([^.;]+)")
NUMERIC_RE = re.compile(r"^[0-9+\-*/().\s]+$")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
SELECTION_SEED = "strict-op28-50-error-trajectories-v1"
QUOTAS = {
    ("numeric_contradiction", "crazy_zootopia"): 10,
    ("numeric_contradiction", "movie_festival_awards"): 10,
    ("numeric_contradiction", "teachers_in_school"): 10,
    ("extra_node_only", "crazy_zootopia"): 4,
    ("extra_node_only", "movie_festival_awards"): 3,
    ("extra_node_only", "teachers_in_school"): 3,
    ("stateful_substitution_only", "crazy_zootopia"): 3,
    ("stateful_substitution_only", "movie_festival_awards"): 3,
    ("stateful_substitution_only", "teachers_in_school"): 4,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def safe_eval(part: str, environment: dict[str, float]) -> float | None:
    substituted = part
    for token in set(re.findall(r"[A-Za-z]", part)):
        if token not in environment:
            return None
        substituted = re.sub(rf"\b{token}\b", str(environment[token]), substituted)
    substituted = substituted.strip()
    if not substituted or not NUMERIC_RE.fullmatch(substituted):
        return None
    try:
        return float(eval(substituted, {"__builtins__": {}}))
    except (ArithmeticError, SyntaxError, ValueError):
        return None


def chain_audit(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    numeric_issues: list[dict[str, Any]] = []
    stateful_issues: list[dict[str, Any]] = []
    environment: dict[str, float] = {}
    for match in ASSIGNMENT_RE.finditer(text):
        target = match.group(1)
        assignment = match.group(0).strip()
        parts = [part.strip() for part in match.group(2).split("=") if part.strip()]
        numeric_parts = [part for part in parts if NUMERIC_RE.fullmatch(part)]
        if len(numeric_parts) >= 2:
            try:
                numeric_values = [float(eval(part, {"__builtins__": {}})) for part in numeric_parts]
            except (ArithmeticError, SyntaxError, ValueError):
                numeric_values = []
            if numeric_values and max(numeric_values) - min(numeric_values) > 1e-6:
                numeric_issues.append(
                    {
                        "assignment": assignment,
                        "parts": numeric_parts,
                        "values": numeric_values,
                    }
                )

        values = [safe_eval(part, environment) for part in parts]
        if len(parts) >= 2 and all(value is not None for value in values) and max(values) - min(values) > 1e-6:
            stateful_issues.append(
                {
                    "assignment": assignment,
                    "parts": parts,
                    "values": values,
                }
            )

        final = values[-1] if values else None
        if final is None:
            numbers = NUMBER_RE.findall(assignment)
            final = float(numbers[-1]) if numbers else None
        if final is not None:
            environment[target] = final
    return numeric_issues, stateful_issues


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def select_candidates(collection: Path) -> tuple[list[dict[str, Any]], Counter[tuple[str, str]]]:
    candidates: list[dict[str, Any]] = []
    population: Counter[tuple[str, str]] = Counter()
    for row in load_jsonl(collection / "accepted.jsonl"):
        response = row["messages"][1]["content"]
        numeric_issues, stateful_issues = chain_audit(response)
        if numeric_issues:
            stratum = "numeric_contradiction"
        elif int(row["extra_nodes"]) > 0:
            stratum = "extra_node_only"
        elif stateful_issues:
            stratum = "stateful_substitution_only"
        else:
            stratum = "unflagged"
        population[(stratum, row["template"])] += 1
        if stratum == "unflagged":
            continue
        candidates.append(
            {
                "row": row,
                "stratum": stratum,
                "numeric_issues": numeric_issues,
                "stateful_issues": stateful_issues,
                "sort_key": hashlib.sha256(f"{SELECTION_SEED}\0{row['id']}".encode()).hexdigest(),
            }
        )

    selected: list[dict[str, Any]] = []
    used_prompts: set[str] = set()
    for (stratum, template), quota in QUOTAS.items():
        matching = sorted(
            (
                candidate
                for candidate in candidates
                if candidate["stratum"] == stratum and candidate["row"]["template"] == template
            ),
            key=lambda item: item["sort_key"],
        )
        chosen: list[dict[str, Any]] = []
        for candidate in matching:
            prompt_id = str(candidate["row"]["prompt_id"])
            if prompt_id in used_prompts:
                continue
            chosen.append(candidate)
            used_prompts.add(prompt_id)
            if len(chosen) == quota:
                break
        if len(chosen) != quota:
            raise ValueError(f"Could not satisfy quota {(stratum, template)}: {len(chosen)}/{quota}")
        selected.extend(chosen)

    if len(selected) != 50 or len(used_prompts) != 50:
        raise ValueError("Audit selection must contain exactly 50 distinct prompts")
    return selected, population


def build_records(collection: Path, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prompts = {str(row["id"]): row for row in load_jsonl(collection / "prompts.jsonl")}
    records: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected, start=1):
        row = candidate["row"]
        prompt = prompts[str(row["prompt_id"])]
        response = str(row["messages"][1]["content"])
        canonical = "<solution> " + str(prompt["completion"])
        report = compare_solutions(canonical, response)
        if not report["perfect"]:
            raise ValueError(f"Selected source row is not strict-perfect: {row['id']}")
        parsed = SolutionParser().parse(response)
        extra_names = set(report["extra_in_pred"])
        extra_steps = [
            {
                "parameter": step.parameter_name,
                "variable": step.variable,
                "body": step.raw_body,
                "parsed_value": step.value,
                "parsed_dependencies": sorted(step.dependencies),
            }
            for step in parsed.steps
            if step.parameter_name in extra_names
        ]
        records.append(
            {
                "audit_index": index,
                "selection_stratum": candidate["stratum"],
                "id": row["id"],
                "prompt_id": row["prompt_id"],
                "template": row["template"],
                "mode": row["mode"],
                "sample_rank": row["sample_rank"],
                "verifier": {
                    "strict_correct": row["strict_correct"],
                    "missing_nodes": row["missing_nodes"],
                    "extra_nodes": row["extra_nodes"],
                    "value_mismatch_count": row["value_mismatch_count"],
                    "dependency_mismatch_count": row["dependency_mismatch_count"],
                    "answer_mismatch": row["answer_mismatch"],
                    "extra_node_names": report["extra_in_pred"],
                },
                "numeric_issues": candidate["numeric_issues"],
                "stateful_issues": candidate["stateful_issues"],
                "extra_steps": extra_steps,
                "question": row["messages"][0]["content"],
                "model_response": response,
                "canonical_response": canonical,
            }
        )
    return records


def write_dossier(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# Strict OP28 50-trajectory error dossier\n\n")
        handle.write(
            "Diagnostic error-enriched sample: 30 numeric contradictions, 10 "
            "extra-node-only, and 10 stateful-substitution-only trajectories. All 50 "
            "have distinct prompt IDs and passed the released strict verifier. This "
            "sample is not a prevalence estimate.\n\n"
        )
        for record in records:
            handle.write(f"## {record['audit_index']:02d}. {record['selection_stratum']} — {record['id']}\n\n")
            handle.write(f"- prompt: `{record['prompt_id']}`\n")
            handle.write(f"- template: `{record['template']}`\n")
            handle.write(f"- mode: `{record['mode']}`\n")
            handle.write(f"- verifier: `{json.dumps(record['verifier'], sort_keys=True)}`\n")
            handle.write(f"- numeric issues: `{json.dumps(record['numeric_issues'], sort_keys=True)}`\n")
            handle.write(f"- stateful issues: `{json.dumps(record['stateful_issues'], sort_keys=True)}`\n")
            handle.write(
                "- extra steps: `" + json.dumps(record["extra_steps"], ensure_ascii=False, sort_keys=True) + "`\n\n"
            )
            handle.write("### Question\n\n" + record["question"] + "\n\n")
            handle.write("### Model response\n\n" + record["model_response"] + "\n\n")
            handle.write("### Canonical response\n\n" + record["canonical_response"] + "\n\n")


def main() -> None:
    args = parse_args()
    collection = args.collection.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)

    selected, population = select_candidates(collection)
    records = build_records(collection, selected)
    jsonl_path = output_dir / "selected.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    dossier_path = output_dir / "dossier.md"
    write_dossier(dossier_path, records)
    manifest = {
        "definition": (
            "Deterministic error-enriched manual-audit sample of released-verifier strict-perfect OP28 trajectories"
        ),
        "source_collection": str(collection),
        "seed": SELECTION_SEED,
        "rows": len(records),
        "unique_prompts": len({str(record["prompt_id"]) for record in records}),
        "quotas": {f"{key[0]}::{key[1]}": value for key, value in QUOTAS.items()},
        "population_rows_by_stratum_and_template": {
            f"{key[0]}::{key[1]}": value for key, value in sorted(population.items())
        },
        "selected_ids": [record["id"] for record in records],
        "selected_jsonl_sha256": file_sha256(jsonl_path),
        "dossier_sha256": file_sha256(dossier_path),
        "implementation_sha256": file_sha256(Path(__file__)),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
