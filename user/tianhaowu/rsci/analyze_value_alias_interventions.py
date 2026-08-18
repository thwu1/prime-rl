#!/usr/bin/env python3
"""Measure validated value-alias intervention availability on pinned evaluation data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from alias_shortcut import AliasSubstitution, canonical_alias_opportunities
from value_alias_intervention import (
    ValueAliasInterventionError,
    build_value_alias_intervention,
    try_value_alias_opportunity,
)

SCHEMA_VERSION = 1
ANALYSIS_ID = "value_alias_intervention_availability"
EXPECTED_ARTIFACT_TYPE = "rsci_defect_withdrawal_eval_authority"
EXPECTED_STUDY_ID = "verifier-defect-withdrawal-v1"
EXPECTED_AUTHORITY_SELF_HASH = "c59f6cc44bc249a7c43fb6534bcb2fa60f103a7a3dc5fe45f9177c741242bbcd"
EXPECTED_OPERATIONS = tuple(range(11, 46))
EXPECTED_EXAMPLES_PER_OPERATION = 200
EXPECTED_PROMPTS = len(EXPECTED_OPERATIONS) * EXPECTED_EXAMPLES_PER_OPERATION
EXPECTED_VALIDATED_PROMPTS = 6_348
EXPECTED_TEMPLATES = (
    "crazy_zootopia",
    "movie_festival_awards",
    "teachers_in_school",
)
BANDS = {
    "op11_20": tuple(range(11, 21)),
    "op21_40": tuple(range(21, 41)),
    "op41_45": tuple(range(41, 46)),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-authority", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_file(path: Path) -> tuple[bytes, dict[str, Any]]:
    requested = path.expanduser().absolute()
    resolved = requested.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    with resolved.open("rb") as handle:
        before = os.fstat(handle.fileno())
        data = handle.read()
        after = os.fstat(handle.fileno())
    before_identity = (before.st_size, before.st_mtime_ns, before.st_ino)
    after_identity = (after.st_size, after.st_mtime_ns, after.st_ino)
    if before_identity != after_identity:
        raise ValueError(f"File changed while reading: {resolved}")
    if len(data) != after.st_size:
        raise ValueError(f"Short read from {resolved}: expected {after.st_size}, found {len(data)}")
    return data, {
        "path": str(requested),
        "resolved_path": str(resolved),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def file_identity(path: Path) -> dict[str, Any]:
    return read_file(path)[1]


def load_json_object(data: bytes, path: Path) -> dict[str, Any]:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def validate_authority(authority: dict[str, Any]) -> None:
    if authority.get("artifact_type") != EXPECTED_ARTIFACT_TYPE:
        raise ValueError(f"Expected authority artifact type {EXPECTED_ARTIFACT_TYPE!r}")
    if authority.get("study_id") != EXPECTED_STUDY_ID:
        raise ValueError(f"Expected authority study ID {EXPECTED_STUDY_ID!r}")
    claimed_self_hash = authority.get("payload_without_self_hash_sha256")
    if claimed_self_hash != EXPECTED_AUTHORITY_SELF_HASH:
        raise ValueError(
            f"Authority self hash differs: expected={EXPECTED_AUTHORITY_SELF_HASH}, found={claimed_self_hash}"
        )
    unsigned = dict(authority)
    del unsigned["payload_without_self_hash_sha256"]
    actual_self_hash = canonical_json_sha256(unsigned)
    if actual_self_hash != claimed_self_hash:
        raise ValueError(f"Authority self hash is invalid: claimed={claimed_self_hash}, actual={actual_self_hash}")

    evaluation_data = authority.get("evaluation_data")
    if not isinstance(evaluation_data, dict):
        raise ValueError("Authority has no evaluation_data object")
    if evaluation_data.get("operations") != list(EXPECTED_OPERATIONS):
        raise ValueError(f"Expected authority operations OP{EXPECTED_OPERATIONS[0]}-{EXPECTED_OPERATIONS[-1]}")
    if evaluation_data.get("examples_per_operation") != EXPECTED_EXAMPLES_PER_OPERATION:
        raise ValueError(f"Expected {EXPECTED_EXAMPLES_PER_OPERATION} examples per operation")
    if evaluation_data.get("prompt_count") != EXPECTED_PROMPTS:
        raise ValueError(f"Expected authority prompt count {EXPECTED_PROMPTS}")


def load_json_lines(data: bytes, path: Path) -> list[dict[str, Any]]:
    lines = data.decode("utf-8").splitlines()
    if any(not line.strip() for line in lines):
        raise ValueError(f"Blank JSONL record in {path}")
    rows = [json.loads(line) for line in lines]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"Expected only JSON objects in {path}")
    return rows


def load_datasets(
    authority: dict[str, Any],
) -> tuple[dict[int, list[dict[str, Any]]], list[dict[str, Any]]]:
    entries = authority["evaluation_data"].get("datasets")
    if not isinstance(entries, list):
        raise ValueError("Authority has no dataset list")
    if len(entries) != len(EXPECTED_OPERATIONS):
        raise ValueError(f"Expected {len(EXPECTED_OPERATIONS)} dataset entries, found {len(entries)}")

    datasets: dict[int, list[dict[str, Any]]] = {}
    identities: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Dataset entry is not an object")
        operation = entry.get("operation")
        if isinstance(operation, bool) or not isinstance(operation, int) or operation not in EXPECTED_OPERATIONS:
            raise ValueError(f"Invalid dataset operation: {operation!r}")
        if operation in datasets:
            raise ValueError(f"Duplicate dataset operation: OP{operation}")
        path_value = entry.get("path")
        if not isinstance(path_value, str):
            raise ValueError(f"OP{operation} dataset path is not a string")

        data, identity = read_file(Path(path_value))
        if identity["size_bytes"] != entry.get("size_bytes") or identity["sha256"] != entry.get("sha256"):
            raise ValueError(f"OP{operation} dataset identity differs from the pinned authority")
        expected_resolved_path = entry.get("resolved_path")
        if expected_resolved_path is not None:
            if not isinstance(expected_resolved_path, str):
                raise ValueError(f"OP{operation} authority resolved path is invalid")
            if identity["resolved_path"] != expected_resolved_path:
                raise ValueError(f"OP{operation} dataset resolved path differs from the pinned authority")
        elif Path(path_value).is_symlink():
            raise ValueError(f"OP{operation} dataset unexpectedly became a symbolic link")

        rows = load_json_lines(data, Path(path_value))
        if len(rows) != EXPECTED_EXAMPLES_PER_OPERATION:
            raise ValueError(f"Expected {EXPECTED_EXAMPLES_PER_OPERATION} OP{operation} rows, found {len(rows)}")
        for row_index, row in enumerate(rows):
            row_operation = row.get("op")
            if isinstance(row_operation, bool) or not isinstance(row_operation, int) or row_operation != operation:
                raise ValueError(f"OP{operation} row {row_index} has invalid operation {row_operation!r}")
            if not isinstance(row.get("solution"), str) or not row["solution"].strip():
                raise ValueError(f"OP{operation} row {row_index} has no canonical solution")
            if row.get("template") not in EXPECTED_TEMPLATES:
                raise ValueError(f"OP{operation} row {row_index} has invalid template {row.get('template')!r}")
        datasets[operation] = rows
        identities.append({"operation": operation, **identity})

    if tuple(sorted(datasets)) != EXPECTED_OPERATIONS:
        raise ValueError(f"Expected exactly OP11-45 datasets, found {sorted(datasets)}")
    return datasets, sorted(identities, key=lambda identity: identity["operation"])


def band_name(operation: int) -> str:
    for name, operations in BANDS.items():
        if operation in operations:
            return name
    raise ValueError(f"Operation has no preregistered band: {operation}")


def update_counts(
    counter: Counter[str],
    *,
    graph_opportunities: int,
    order_compatible_opportunities: int,
    validated: bool,
) -> None:
    counter["prompts"] += 1
    counter["graph_opportunities"] += graph_opportunities
    counter["order_compatible_opportunities"] += order_compatible_opportunities
    counter["graph_available"] += graph_opportunities > 0
    counter["order_compatible_available"] += order_compatible_opportunities > 0
    counter["validated_available"] += validated
    counter["graph_only_non_order_compatible"] += graph_opportunities > 0 and order_compatible_opportunities == 0
    counter["order_compatible_without_validated"] += order_compatible_opportunities > 0 and not validated


def availability_summary(counter: Counter[str]) -> dict[str, int | float]:
    prompts = counter["prompts"]
    if prompts <= 0:
        raise ValueError("Availability stratum is empty")
    order_compatible = counter["order_compatible_available"]
    return {
        "prompts": prompts,
        "graph_opportunities": counter["graph_opportunities"],
        "graph_available": counter["graph_available"],
        "graph_available_rate": counter["graph_available"] / prompts,
        "order_compatible_opportunities": counter["order_compatible_opportunities"],
        "order_compatible_available": order_compatible,
        "order_compatible_available_rate": order_compatible / prompts,
        "validated_available": counter["validated_available"],
        "validated_available_rate": counter["validated_available"] / prompts,
        "validated_given_order_compatible_rate": (
            counter["validated_available"] / order_compatible if order_compatible else 0.0
        ),
        "graph_only_non_order_compatible": counter["graph_only_non_order_compatible"],
        "order_compatible_without_validated": counter["order_compatible_without_validated"],
    }


def deterministic_example(
    row: dict[str, Any],
    *,
    operation: int,
    row_index: int,
    transformed_solution: str,
    opportunity: AliasSubstitution,
) -> dict[str, Any]:
    sample_id = row.get("id")
    if sample_id is not None and not isinstance(sample_id, str):
        raise ValueError(f"OP{operation} row {row_index} has invalid sample ID")
    question = row.get("question")
    if not isinstance(question, str):
        raise ValueError(f"OP{operation} row {row_index} has invalid question")
    canonical_solution = row["solution"]
    return {
        "operation": operation,
        "row_index": row_index,
        "sample_id": sample_id,
        "template": row["template"],
        "question": question,
        "opportunity": opportunity.to_dict(),
        "canonical_solution": canonical_solution,
        "canonical_solution_sha256": hashlib.sha256(canonical_solution.encode()).hexdigest(),
        "transformed_solution": transformed_solution,
        "transformed_solution_sha256": hashlib.sha256(transformed_solution.encode()).hexdigest(),
    }


def main() -> None:
    args = parse_args()
    authority_path = args.evaluation_authority.expanduser().absolute()
    authority_data, authority_identity = read_file(authority_path)
    authority = load_json_object(authority_data, authority_path)
    validate_authority(authority)
    datasets, dataset_identities = load_datasets(authority)

    all_counts: Counter[str] = Counter()
    band_counts = {name: Counter() for name in BANDS}
    template_counts = {name: Counter() for name in EXPECTED_TEMPLATES}
    operation_counts = {operation: Counter() for operation in EXPECTED_OPERATIONS}
    examples: list[dict[str, Any]] = []
    positive_api_revalidations = 0
    negative_api_revalidated_prompts = 0
    negative_api_revalidated_opportunities = 0

    for operation in EXPECTED_OPERATIONS:
        for row_index, row in enumerate(datasets[operation]):
            gold_solution = row["solution"]
            graph_opportunities = tuple(sorted(canonical_alias_opportunities(gold_solution, require_preceding=False)))
            order_compatible_opportunities = tuple(sorted(canonical_alias_opportunities(gold_solution)))
            if not set(order_compatible_opportunities) <= set(graph_opportunities):
                raise ValueError(f"OP{operation} row {row_index} has inconsistent opportunity sets")

            try:
                intervention = build_value_alias_intervention(gold_solution)
            except ValueAliasInterventionError:
                intervention = None
                negative_api_revalidated_prompts += 1
                for opportunity in order_compatible_opportunities:
                    negative_api_revalidated_opportunities += 1
                    if try_value_alias_opportunity(gold_solution, opportunity) is not None:
                        raise ValueError(f"OP{operation} row {row_index} builder missed a validated opportunity")

            if intervention is not None:
                if intervention.opportunity not in order_compatible_opportunities:
                    raise ValueError(f"OP{operation} row {row_index} built a non-canonical opportunity")
                revalidated = try_value_alias_opportunity(gold_solution, intervention.opportunity)
                if revalidated != intervention:
                    raise ValueError(f"OP{operation} row {row_index} failed API revalidation")
                positive_api_revalidations += 1
                if len(examples) < 2:
                    examples.append(
                        deterministic_example(
                            row,
                            operation=operation,
                            row_index=row_index,
                            transformed_solution=intervention.transformed_solution,
                            opportunity=intervention.opportunity,
                        )
                    )

            dimensions = (
                all_counts,
                band_counts[band_name(operation)],
                template_counts[row["template"]],
                operation_counts[operation],
            )
            for counter in dimensions:
                update_counts(
                    counter,
                    graph_opportunities=len(graph_opportunities),
                    order_compatible_opportunities=len(order_compatible_opportunities),
                    validated=intervention is not None,
                )

    if all_counts["prompts"] != EXPECTED_PROMPTS:
        raise ValueError(f"Expected {EXPECTED_PROMPTS} analyzed prompts, found {all_counts['prompts']}")
    if all_counts["validated_available"] != EXPECTED_VALIDATED_PROMPTS:
        raise ValueError(
            "Validated intervention count differs from the sealed expectation: "
            f"expected={EXPECTED_VALIDATED_PROMPTS}, found={all_counts['validated_available']}"
        )
    if positive_api_revalidations != EXPECTED_VALIDATED_PROMPTS:
        raise ValueError("Not every built intervention was positively revalidated")
    if len(examples) != 2:
        raise ValueError(f"Expected two deterministic examples, found {len(examples)}")

    script_directory = Path(__file__).resolve().parent
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "definition": {
            "graph_opportunity": (
                "canonical equal-value one-parent substitution that is acyclic, without the parent-order requirement"
            ),
            "order_compatible_opportunity": (
                "graph opportunity whose added parent precedes the child in the canonical solution"
            ),
            "validated_intervention": (
                "one assignment-RHS rewrite preserves answer and every node value, creates exactly the specified "
                "one-edge graph delta, has no executable equality issue, and is reproduced by both intervention APIs"
            ),
        },
        "claim_scope": {
            "static_canonical_feasibility_only": True,
            "causal_evidence": False,
            "phase_transition_evidence": False,
            "training_outcome_evidence": False,
        },
        "inputs": {
            "evaluation_authority": authority_identity,
            "authority_self_hash": authority["payload_without_self_hash_sha256"],
            "dataset_bundle_sha256": authority["evaluation_data"].get("dataset_bundle_sha256"),
            "prompt_sequence_sha256": authority["evaluation_data"].get("prompt_sequence_sha256"),
            "datasets": dataset_identities,
        },
        "availability": {
            "all": availability_summary(all_counts),
            "by_band": {name: availability_summary(band_counts[name]) for name in BANDS},
            "by_template": {name: availability_summary(template_counts[name]) for name in EXPECTED_TEMPLATES},
            "by_operation": {
                str(operation): availability_summary(operation_counts[operation]) for operation in EXPECTED_OPERATIONS
            },
        },
        "api_revalidation": {
            "positive_interventions": positive_api_revalidations,
            "negative_prompts": negative_api_revalidated_prompts,
            "negative_opportunities": negative_api_revalidated_opportunities,
        },
        "examples": examples,
        "implementations": {
            "analyzer": file_identity(Path(__file__)),
            "value_alias_intervention": file_identity(script_directory / "value_alias_intervention.py"),
            "alias_shortcut": file_identity(script_directory / "alias_shortcut.py"),
            "solution_graph": file_identity(script_directory / "solution_graph.py"),
            "strict_trajectory_grader": file_identity(script_directory / "strict_trajectory_grader.py"),
        },
    }
    result["content_sha256"] = canonical_json_sha256(result)

    output = args.output.expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"content_sha256": result["content_sha256"], "output": str(output)}))


if __name__ == "__main__":
    main()
