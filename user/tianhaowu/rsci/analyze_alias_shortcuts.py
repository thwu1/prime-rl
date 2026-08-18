#!/usr/bin/env python3
"""Audit value-alias dependency shortcuts in matched strict evaluations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from alias_shortcut import canonical_alias_opportunities, find_alias_substitutions
from solution_graph import SolutionParser, compare_solutions
from strict_trajectory_grader import execute_steps, grade_trajectory

SCHEMA_VERSION = 1
EXPECTED_ARMS = ("p00", "p01", "p05", "p10")
EXPECTED_OPERATIONS = tuple(range(11, 46))
EXPECTED_STUDY_ID = "verifier-defect-withdrawal-v1"
EXPECTED_AUTHORITY_HASH = "c59f6cc44bc249a7c43fb6534bcb2fa60f103a7a3dc5fe45f9177c741242bbcd"
EXPECTED_SOURCE_HASH = "b5eee4de51b20b5616b27cbc9c212fc15fbc88c6505abbf805ac91414c0233a5"
EXPECTED_PROMPT_SEQUENCE_HASH = "f19550d46e87d696a3fb3749cb5c740eb5dd5695f23c302e963cf3bac0a727ac"
BANDS = {
    "op11_20": tuple(range(11, 21)),
    "op21_40": tuple(range(21, 41)),
    "op41_45": tuple(range(41, 46)),
}
EXPECTED_TEMPLATES = ("crazy_zootopia", "movie_festival_awards", "teachers_in_school")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-authority", type=Path, required=True)
    parser.add_argument("--source-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_file(path: Path) -> tuple[bytes, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    with resolved.open("rb") as handle:
        before = os.fstat(handle.fileno())
        payload = handle.read()
        after = os.fstat(handle.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError(f"File changed while reading: {resolved}")
    if len(payload) != after.st_size:
        raise ValueError(f"Short read from {resolved}: expected {after.st_size}, found {len(payload)}")
    identity = {
        "path": str(resolved),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    return payload, identity


def file_identity(path: Path) -> dict[str, Any]:
    return read_file(path)[1]


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_json_object(data: bytes, path: Path) -> dict[str, Any]:
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def validate_self_hash(payload: dict[str, Any], field: str) -> None:
    expected = payload.get(field)
    if not isinstance(expected, str):
        raise ValueError(f"Missing {field}")
    unsigned = dict(payload)
    del unsigned[field]
    actual = canonical_json_sha256(unsigned)
    if actual != expected:
        raise ValueError(f"Invalid {field}: expected={expected}, actual={actual}")


def read_validated_file(identity: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    path = Path(identity["path"])
    data, actual = read_file(path)
    expected = {key: identity[key] for key in ("path", "size_bytes", "sha256")}
    if actual != expected:
        raise ValueError(f"File identity changed: expected={expected}, actual={actual}")
    return data, actual


def load_json_lines(data: bytes, path: Path) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in data.decode("utf-8").splitlines()]
    if not all(isinstance(record, dict) for record in records):
        raise ValueError(f"Expected JSON objects in {path}")
    return records


def prompt_text(row: dict[str, Any]) -> str:
    prompt = row.get("prompt")
    if isinstance(prompt, str):
        return prompt
    return f"<question> {str(row['problem']).strip()} {str(row['question']).strip()} </question> <solution>"


def load_datasets(authority: dict[str, Any]) -> tuple[dict[int, list[dict[str, Any]]], list[dict[str, Any]]]:
    entries = authority.get("evaluation_data", {}).get("datasets")
    if not isinstance(entries, list):
        raise ValueError("Evaluation authority has no dataset list")
    datasets = {}
    identities = []
    for entry in entries:
        operation = entry.get("operation")
        if isinstance(operation, bool) or not isinstance(operation, int):
            raise ValueError(f"Invalid dataset operation: {operation!r}")
        if operation in datasets:
            raise ValueError(f"Duplicate dataset operation: {operation}")
        path = Path(entry["path"])
        data, actual = read_file(path)
        if actual["size_bytes"] != entry["size_bytes"] or actual["sha256"] != entry["sha256"]:
            raise ValueError(f"Dataset identity changed for OP{operation}: {path}")
        rows = load_json_lines(data, path)
        if len(rows) != 200 or any(int(row["op"]) != operation for row in rows):
            raise ValueError(f"Expected 200 OP{operation} dataset rows, found {len(rows)}")
        templates = {str(row.get("template")) for row in rows}
        if not templates <= set(EXPECTED_TEMPLATES):
            raise ValueError(f"Unexpected OP{operation} templates: {sorted(templates)}")
        datasets[operation] = rows
        identities.append({"operation": operation, **actual})
    if tuple(sorted(datasets)) != EXPECTED_OPERATIONS:
        raise ValueError(f"Expected OP11-45 datasets, found {sorted(datasets)}")
    return datasets, identities


def response_text(record: dict[str, Any], context: str) -> str:
    nodes = record.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError(f"Missing nodes in {context}")
    sampled = [node for node in nodes if isinstance(node, dict) and node.get("sampled") is True]
    if len(sampled) != 1:
        raise ValueError(f"Expected one sampled node in {context}, found {len(sampled)}")
    message = sampled[0].get("message")
    if (
        not isinstance(message, dict)
        or message.get("role") != "assistant"
        or not isinstance(message.get("content"), str)
    ):
        raise ValueError(f"Malformed assistant message in {context}")
    return message["content"]


def is_pure_alias_report(report: dict[str, Any], alias_count: int) -> bool:
    return bool(
        alias_count == 1
        and not report["missing_in_pred"]
        and not report["extra_in_pred"]
        and not report["value_mismatches"]
        and len(report["dependency_mismatches"]) == 1
        and report["answer_mismatch"] is None
    )


def binary_metric(value: Any, context: str) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in (0, 1, 0.0, 1.0):
        raise ValueError(f"Non-binary metric in {context}: {value!r}")
    return bool(value)


def band_name(operation: int) -> str:
    for name, operations in BANDS.items():
        if operation in operations:
            return name
    raise ValueError(f"Operation {operation} has no disjoint band")


def increment(counter: Counter[tuple[str, ...]], dimensions: tuple[str, ...], amount: int = 1) -> None:
    counter[dimensions] += amount


def nested_counts(
    counts: Counter[tuple[str, ...]],
    first_values: tuple[str, ...],
    second_values: tuple[str, ...],
) -> dict[str, dict[str, int]]:
    return {first: {second: counts[(first, second)] for second in second_values} for first in first_values}


def main() -> None:
    args = parse_args()
    authority_path = args.evaluation_authority.expanduser().resolve()
    source_summary_path = args.source_summary.expanduser().resolve()
    authority_data, authority_identity = read_file(authority_path)
    source_summary_data, source_summary_identity = read_file(source_summary_path)
    authority = load_json_object(authority_data, authority_path)
    source_summary = load_json_object(source_summary_data, source_summary_path)
    if authority.get("artifact_type") != "rsci_defect_withdrawal_eval_authority":
        raise ValueError("Unexpected evaluation authority type")
    if authority.get("study_id") != EXPECTED_STUDY_ID:
        raise ValueError(f"Expected study {EXPECTED_STUDY_ID!r}")
    if source_summary.get("analysis_id") != "verifier_defect_source_composition" or source_summary.get("step") != 4000:
        raise ValueError("Source summary is not the step-4000 composition artifact")
    validate_self_hash(authority, "payload_without_self_hash_sha256")
    validate_self_hash(source_summary, "content_sha256")
    if authority["payload_without_self_hash_sha256"] != EXPECTED_AUTHORITY_HASH:
        raise ValueError("Evaluation authority does not match the preregistered artifact")
    if source_summary["content_sha256"] != EXPECTED_SOURCE_HASH:
        raise ValueError("Source summary does not match the preregistered artifact")
    if source_summary.get("prompt_sequence_sha256") != EXPECTED_PROMPT_SEQUENCE_HASH:
        raise ValueError("Source summary has the wrong prompt sequence")
    input_files = source_summary.get("input_files")
    if not isinstance(input_files, dict) or tuple(sorted(input_files)) != EXPECTED_ARMS:
        raise ValueError(f"Expected source arms {EXPECTED_ARMS}")
    rollout_records: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for arm, files in input_files.items():
        if not isinstance(files, list):
            raise ValueError(f"Source files for {arm} are not a list")
        if len(files) != len(EXPECTED_OPERATIONS):
            raise ValueError("Each source arm must have 35 evaluation files")
        if not all(isinstance(identity, dict) for identity in files):
            raise ValueError(f"Malformed source file identity for {arm}")
        operations = tuple(identity.get("operation") for identity in files)
        if any(isinstance(operation, bool) or not isinstance(operation, int) for operation in operations):
            raise ValueError(f"Invalid source operations for {arm}: {operations}")
        operations = tuple(sorted(operations))
        if operations != EXPECTED_OPERATIONS:
            raise ValueError(f"Expected OP11-45 source files for {arm}, found {operations}")
        for identity in files:
            operation = int(identity["operation"])
            data, _ = read_validated_file(identity)
            rollout_records[(arm, operation)] = load_json_lines(data, Path(identity["path"]))

    datasets, dataset_identities = load_datasets(authority)
    counts: Counter[tuple[str, ...]] = Counter()
    by_operation: Counter[tuple[str, ...]] = Counter()
    opportunity_counts: Counter[tuple[str, str]] = Counter()
    renderable_opportunity_keys: dict[tuple[int, int], set[tuple[str, str, str]]] = {}
    for operation, rows in datasets.items():
        for index, row in enumerate(rows):
            solution = str(row["solution"])
            graph_opportunities = canonical_alias_opportunities(solution, require_preceding=False)
            renderable_opportunities = canonical_alias_opportunities(solution)
            renderable_opportunity_keys[(operation, index)] = {
                (item.child, item.omitted_parent, item.added_parent) for item in renderable_opportunities
            }
            band = band_name(operation)
            for first in ("all", band, str(row["template"])):
                opportunity_counts[(first, "prompts")] += 1
                opportunity_counts[(first, "graph_available")] += bool(graph_opportunities)
                opportunity_counts[(first, "renderable_available")] += bool(renderable_opportunities)

    prompt_arms: dict[tuple[int, int], set[str]] = defaultdict(set)
    signature_arms: dict[tuple[int, int, str, str, str], set[str]] = defaultdict(set)
    examples = []
    exact_example = None

    files_by_arm = {
        arm: {int(identity["operation"]): Path(identity["path"]) for identity in files}
        for arm, files in input_files.items()
    }
    for arm in EXPECTED_ARMS:
        for operation in EXPECTED_OPERATIONS:
            path = files_by_arm[arm][operation]
            records = rollout_records[(arm, operation)]
            if len(records) != 200:
                raise ValueError(f"Expected 200 records in {path}, found {len(records)}")
            seen_indices = set()
            for record in records:
                task = record.get("task")
                metrics = record.get("metrics")
                if not isinstance(task, dict) or not isinstance(metrics, dict):
                    raise ValueError(f"Malformed evaluation record in {path}")
                index = task.get("idx")
                if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 200:
                    raise ValueError(f"Invalid task index in {path}: {index!r}")
                if index in seen_indices:
                    raise ValueError(f"Duplicate task index {index} in {path}")
                seen_indices.add(index)
                dataset_row = datasets[operation][index]
                if task.get("prompt") != prompt_text(dataset_row):
                    raise ValueError(f"Prompt mismatch for {arm}/OP{operation}/{index}")
                response = response_text(record, f"{arm}/OP{operation}/{index}")
                report = compare_solutions(str(dataset_row["solution"]), response)
                trajectory_report = grade_trajectory(
                    str(dataset_row["solution"]),
                    response,
                    problem=str(dataset_row["problem"]),
                )
                _, execution_issues = execute_steps(SolutionParser().parse(response).steps)
                trace_clean = not execution_issues
                context = f"{arm}/OP{operation}/{index}"
                strict = binary_metric(metrics.get("strict_dependency_graph_reward"), context)
                executable_strict = binary_metric(metrics.get("executable_strict_metric"), context)
                answer = binary_metric(metrics.get("answer_correct_metric"), context)
                if strict != bool(report["perfect"]) or answer != (report["answer_mismatch"] is None):
                    raise ValueError(f"Stored metrics disagree with parser for {arm}/OP{operation}/{index}")
                if executable_strict != bool(trajectory_report["perfect"]):
                    raise ValueError(f"Stored executable metric disagrees with grader for {arm}/OP{operation}/{index}")
                if strict and not answer:
                    raise ValueError(f"Strict result is not answer-correct for {arm}/OP{operation}/{index}")

                broad_aliases = find_alias_substitutions(
                    str(dataset_row["solution"]),
                    response,
                    require_unique_declarations=False,
                )
                aliases = find_alias_substitutions(str(dataset_row["solution"]), response)
                renderable_keys = renderable_opportunity_keys[(operation, index)]
                renderable_aliases = tuple(
                    alias
                    for alias in aliases
                    if (alias.child, alias.omitted_parent, alias.added_parent) in renderable_keys
                )
                category = "S" if strict else ("A" if answer else "W")
                band = band_name(operation)
                template = str(dataset_row["template"])
                for first in ("all", arm, band, template):
                    increment(counts, (first, "rows"))
                    increment(counts, (first, category))
                    increment(counts, (first, "raw_alias"), bool(broad_aliases and category == "A"))
                    increment(counts, (first, "alias"), bool(aliases and category == "A"))
                    increment(
                        counts,
                        (first, "renderable_alias"),
                        bool(renderable_aliases and category == "A"),
                    )
                    increment(
                        counts,
                        (first, "pure_alias"),
                        bool(category == "A" and is_pure_alias_report(report, len(aliases))),
                    )
                    increment(
                        counts,
                        (first, "pure_renderable_alias"),
                        bool(
                            category == "A"
                            and len(renderable_aliases) == 1
                            and is_pure_alias_report(report, len(aliases))
                        ),
                    )
                    increment(
                        counts,
                        (first, "trace_clean_pure_alias"),
                        bool(category == "A" and trace_clean and is_pure_alias_report(report, len(aliases))),
                    )
                    increment(
                        counts,
                        (first, "trace_clean_pure_renderable_alias"),
                        bool(
                            category == "A"
                            and trace_clean
                            and len(renderable_aliases) == 1
                            and is_pure_alias_report(report, len(aliases))
                        ),
                    )
                for outcome in ("rows", category):
                    increment(by_operation, (str(operation), outcome))
                increment(by_operation, (str(operation), "alias"), bool(aliases and category == "A"))
                increment(
                    by_operation,
                    (str(operation), "renderable_alias"),
                    bool(renderable_aliases and category == "A"),
                )
                increment(
                    by_operation,
                    (str(operation), "pure_alias"),
                    bool(category == "A" and is_pure_alias_report(report, len(aliases))),
                )
                increment(
                    by_operation,
                    (str(operation), "pure_renderable_alias"),
                    bool(
                        category == "A" and len(renderable_aliases) == 1 and is_pure_alias_report(report, len(aliases))
                    ),
                )
                increment(
                    by_operation,
                    (str(operation), "trace_clean_pure_alias"),
                    bool(category == "A" and trace_clean and is_pure_alias_report(report, len(aliases))),
                )
                increment(
                    by_operation,
                    (str(operation), "trace_clean_pure_renderable_alias"),
                    bool(
                        category == "A"
                        and trace_clean
                        and len(renderable_aliases) == 1
                        and is_pure_alias_report(report, len(aliases))
                    ),
                )

                if category != "A" or not aliases:
                    continue
                prompt_key = (operation, index)
                prompt_arms[prompt_key].add(arm)
                alias_rows = [alias.to_dict() for alias in aliases]
                for alias in aliases:
                    signature_arms[(operation, index, alias.child, alias.omitted_parent, alias.added_parent)].add(arm)
                example = {
                    "arm": arm,
                    "operation": operation,
                    "task_index": index,
                    "rollout_id": record.get("id"),
                    "template": template,
                    "aliases": alias_rows,
                    "renderable_aliases": [alias.to_dict() for alias in renderable_aliases],
                    "pure_alias": is_pure_alias_report(report, len(aliases)),
                    "pure_renderable_alias": (
                        len(renderable_aliases) == 1 and is_pure_alias_report(report, len(aliases))
                    ),
                    "trace_clean": trace_clean,
                    "execution_issue_codes": sorted({issue.code for issue in execution_issues}),
                }
                if len(examples) < 20:
                    examples.append(example)
                if arm == "p00" and operation == 12 and index == 34:
                    exact_example = example
            if seen_indices != set(range(200)):
                raise ValueError(f"Task indices are incomplete in {path}")

    dimensions = ("all", *EXPECTED_ARMS, *BANDS.keys(), *EXPECTED_TEMPLATES)
    metrics = (
        "rows",
        "S",
        "A",
        "W",
        "raw_alias",
        "alias",
        "renderable_alias",
        "pure_alias",
        "pure_renderable_alias",
        "trace_clean_pure_alias",
        "trace_clean_pure_renderable_alias",
    )
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": "value_alias_shortcut_audit",
        "definition": {
            "A": "answer_correct_metric == 1 and strict_dependency_graph_reward == 0",
            "reported_alias_counts": "every alias count and recurrence statistic is restricted to A rows",
            "raw_alias": "A alias before the duplicate declaration and dependency-cycle guards",
            "alias": (
                "one omitted and one added canonical parent on the same correct-valued child; omitted and added "
                "parents have equal canonical values; added parent is predicted correctly; predicted parameter names "
                "and variable letters are each unique; added parent is not a canonical descendant of the child"
            ),
            "renderable_alias": "alias whose added canonical parent precedes the child in the canonical solution",
            "pure_alias": "alias is the sole parsed dependency-graph defect",
            "pure_renderable_alias": "renderable alias is the sole parsed dependency-graph defect",
            "trace_clean_pure_alias": "pure alias with no independent executable equality-chain issue",
            "trace_clean_pure_renderable_alias": (
                "pure renderable alias with no independent executable equality-chain issue"
            ),
        },
        "claim_scope": {
            "deterministic_parser_validated": True,
            "observational_prevalence_only": True,
            "causal_lineage_claim_valid": False,
            "phase_transition_claim_valid": False,
        },
        "inputs": {
            "evaluation_authority": authority_identity,
            "source_summary": source_summary_identity,
            "datasets": dataset_identities,
            "rollout_files": input_files,
        },
        "counts": nested_counts(counts, dimensions, metrics),
        "by_operation": nested_counts(
            by_operation,
            tuple(str(operation) for operation in EXPECTED_OPERATIONS),
            (
                "rows",
                "S",
                "A",
                "W",
                "alias",
                "renderable_alias",
                "pure_alias",
                "pure_renderable_alias",
                "trace_clean_pure_alias",
                "trace_clean_pure_renderable_alias",
            ),
        ),
        "canonical_opportunities": nested_counts(
            opportunity_counts,
            ("all", *BANDS.keys(), *EXPECTED_TEMPLATES),
            ("prompts", "graph_available", "renderable_available"),
        ),
        "recurrence": {
            "prompts_with_alias": len(prompt_arms),
            "prompts_in_at_least_two_arms": sum(len(arms) >= 2 for arms in prompt_arms.values()),
            "prompts_in_all_arms": sum(len(arms) == len(EXPECTED_ARMS) for arms in prompt_arms.values()),
            "exact_signatures": len(signature_arms),
            "signatures_in_at_least_two_arms": sum(len(arms) >= 2 for arms in signature_arms.values()),
            "signatures_in_all_arms": sum(len(arms) == len(EXPECTED_ARMS) for arms in signature_arms.values()),
        },
        "examples": examples,
        "specified_example": exact_example,
        "implementations": {
            "analyzer": file_identity(Path(__file__)),
            "alias_parser": file_identity(Path(__file__).with_name("alias_shortcut.py")),
            "solution_graph": file_identity(Path(__file__).with_name("solution_graph.py")),
            "strict_trajectory_grader": file_identity(Path(__file__).with_name("strict_trajectory_grader.py")),
        },
    }
    if exact_example is None:
        raise ValueError("Specified p00/OP12/index34 example did not classify")
    result["content_sha256"] = canonical_json_sha256(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"output": str(args.output.resolve()), "content_sha256": result["content_sha256"]}))


if __name__ == "__main__":
    main()
