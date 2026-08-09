#!/usr/bin/env python3
"""Deterministically analyze strict/A/wrong withdrawal readout transitions."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import materialize_defect_withdrawal_eval as eval_plan

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_defect_withdrawal_eval_analysis"
CATEGORIES = ("S", "A", "W")
BANDS = {
    **{f"op{operation}": (operation,) for operation in range(11, 46)},
    "op11_20": tuple(range(11, 21)),
    "op21_40": tuple(range(21, 41)),
    "op41_45": tuple(range(41, 46)),
    "op11_45": tuple(range(11, 46)),
}
TERMINAL_PROVENANCE_NAME = "terminal_provenance.json"
TERMINAL_PROVENANCE_ARTIFACT_TYPE = "rsci_defect_withdrawal_eval_terminal_provenance"
SUBMISSION_RECEIPT_ARTIFACT_TYPE = "rsci_defect_withdrawal_eval_submission_receipt"
SELF_HASH_FIELD = "payload_without_self_hash_sha256"

PromptKey = tuple[int, int, str, int]


def category(record: dict[str, Any]) -> str:
    perfect = record.get("perfect")
    answer_correct = record.get("answer_correct")
    if not isinstance(perfect, bool) or not isinstance(answer_correct, bool):
        raise ValueError("Strict result category fields must be booleans")
    if perfect and not answer_correct:
        raise ValueError("Strict-perfect result is not answer-correct")
    if perfect:
        return "S"
    return "A" if answer_correct else "W"


def prompt_key(record: dict[str, Any]) -> PromptKey:
    return (
        int(record["op"]),
        int(record["__idx"]),
        str(record["id"]),
        int(record["sample_rank"]),
    )


def category_map(records: list[dict[str, Any]]) -> dict[PromptKey, str]:
    result = {}
    for record in records:
        key = prompt_key(record)
        if key in result:
            raise ValueError(f"Duplicate strict-result prompt key: {key}")
        result[key] = category(record)
    expected = len(eval_plan.OPERATIONS) * eval_plan.EXAMPLES_PER_OPERATION
    if len(result) != expected:
        raise ValueError(f"Strict-result prompt count is {len(result)}, expected {expected}")
    return result


def _selected_keys(values: dict[PromptKey, str], operations: tuple[int, ...]) -> list[PromptKey]:
    operation_set = set(operations)
    return sorted(key for key in values if key[0] in operation_set)


def summarize_prevalence(values: dict[PromptKey, str], operations: tuple[int, ...]) -> dict[str, Any]:
    keys = _selected_keys(values, operations)
    counts = Counter(values[key] for key in keys)
    total = len(keys)
    return {
        "n": total,
        "counts": {label: counts[label] for label in CATEGORIES},
        "rates": {label: counts[label] / total for label in CATEGORIES},
    }


def summarize_transition(
    source: dict[PromptKey, str],
    endpoint: dict[PromptKey, str],
    operations: tuple[int, ...],
) -> dict[str, Any]:
    if set(source) != set(endpoint):
        missing_source = sorted(set(endpoint) - set(source))[:5]
        missing_endpoint = sorted(set(source) - set(endpoint))[:5]
        raise ValueError(
            f"Transition prompt sets differ: source_missing={missing_source}, endpoint_missing={missing_endpoint}"
        )
    keys = _selected_keys(source, operations)
    matrix = {left: {right: 0 for right in CATEGORIES} for left in CATEGORIES}
    for key in keys:
        matrix[source[key]][endpoint[key]] += 1
    total = len(keys)
    source_a = sum(matrix["A"].values())
    new_a = matrix["S"]["A"] + matrix["W"]["A"]
    a_loss = matrix["A"]["S"] + matrix["A"]["W"]
    strict_gain = matrix["A"]["S"] + matrix["W"]["S"]
    strict_loss = matrix["S"]["A"] + matrix["S"]["W"]
    return {
        "n": total,
        "matrix": matrix,
        "source_prevalence": summarize_prevalence(source, operations),
        "endpoint_prevalence": summarize_prevalence(endpoint, operations),
        "new_a_incidence": new_a / total,
        "a_loss_incidence": a_loss / total,
        "net_a_change": (new_a - a_loss) / total,
        "a_retention": matrix["A"]["A"] / source_a if source_a else None,
        "strict_gain_incidence": strict_gain / total,
        "strict_loss_incidence": strict_loss / total,
        "net_strict_change": (strict_gain - strict_loss) / total,
    }


def _terminal_provenance(plan: dict[str, Any], plan_path: Path) -> dict[str, Any]:
    path = Path(plan["plan_root"]) / TERMINAL_PROVENANCE_NAME
    _, provenance = eval_plan._read_json(path)
    recorded_self_hash = provenance.get(SELF_HASH_FIELD)
    provenance_payload = {key: value for key, value in provenance.items() if key != SELF_HASH_FIELD}
    if (
        provenance.get("schema_version") != SCHEMA_VERSION
        or provenance.get("artifact_type") != TERMINAL_PROVENANCE_ARTIFACT_TYPE
        or provenance.get("study_id") != eval_plan.STUDY_ID
        or provenance.get("plan") != eval_plan.file_identity(plan_path)
        or recorded_self_hash != eval_plan.canonical_json_sha256(provenance_payload)
        or set(provenance)
        != {
            "schema_version",
            "artifact_type",
            "study_id",
            "plan",
            "tasks",
            SELF_HASH_FIELD,
        }
    ):
        raise ValueError("Withdrawal evaluation terminal provenance identity differs")
    records = provenance.get("tasks")
    if not isinstance(records, list) or len(records) != len(plan["tasks"]):
        raise ValueError("Terminal provenance task inventory differs")
    by_task = {record.get("task_id"): record for record in records if isinstance(record, dict)}
    if set(by_task) != {task["task_id"] for task in plan["tasks"]}:
        raise ValueError("Terminal provenance task IDs differ")
    for task in plan["tasks"]:
        record = by_task[task["task_id"]]
        record_fields = {
            "task_id",
            "attempt",
            "job_id",
            "comment",
            "job_name",
            "account",
            "qos",
            "state",
            "exit_code",
            "restart_count",
            "submitted_batch_script_sha256",
            "submission_receipt",
            "terminal_receipt",
            "allocation_log",
        }
        if (
            set(record) != record_fields
            or not isinstance(record.get("attempt"), int)
            or record["attempt"] < 1
            or not isinstance(record.get("job_id"), str)
            or not record["job_id"].isdigit()
            or not isinstance(record.get("comment"), str)
            or eval_plan.SHA256_RE.fullmatch(record["comment"]) is None
            or record.get("job_name") != task["job_name"]
            or record.get("account") != "ram"
            or record.get("qos") != "h100_ram_high"
            or record.get("state") != "COMPLETED"
            or record.get("exit_code") != "0:0"
            or record.get("restart_count") != 0
            or record.get("submitted_batch_script_sha256") != task["sbatch"]["sha256"]
            or not isinstance(record.get("submission_receipt"), dict)
            or not isinstance(record.get("terminal_receipt"), dict)
            or not isinstance(record.get("allocation_log"), dict)
        ):
            raise ValueError(f"Terminal scheduler proof differs: {task['task_id']}")
        for field in ("submission_receipt", "terminal_receipt", "allocation_log"):
            identity = record[field]
            if eval_plan.file_identity(Path(identity["path"])) != identity:
                raise ValueError(f"Terminal provenance {field} changed: {task['task_id']}")
        receipt_paths = sorted(Path(task["receipt_dir"]).glob("attempt_*.json"))
        if not receipt_paths or eval_plan.file_identity(receipt_paths[-1]) != record["terminal_receipt"]:
            raise ValueError(f"Terminal provenance does not bind the latest receipt: {task['task_id']}")
        _, terminal_receipt = eval_plan._read_json(Path(record["terminal_receipt"]["path"]))
        if (
            terminal_receipt.get("task_id") != task["task_id"]
            or terminal_receipt.get("attempt") != record["attempt"]
            or terminal_receipt.get("status") != "succeeded"
            or terminal_receipt.get("scheduler", {}).get("job_id") != record["job_id"]
        ):
            raise ValueError(f"Terminal receipt differs from scheduler proof: {task['task_id']}")
        _, submission = eval_plan._read_json(Path(record["submission_receipt"]["path"]))
        import dispatch_defect_withdrawal as withdrawal_dispatch

        _, validated_submission = withdrawal_dispatch._validate_eval_submission(
            Path(record["submission_receipt"]["path"]),
            plan_path=plan_path,
            plan=plan,
            task=task,
            intent_path=Path(submission["dispatch_intent"]["path"]),
            attempt=record["attempt"],
        )
        if validated_submission != submission:
            raise ValueError(f"Protected submission changed during validation: {task['task_id']}")
        expected_submission_fields = {
            "schema_version",
            "artifact_type",
            "study_id",
            "plan",
            "task_id",
            "attempt",
            "job_id",
            "comment",
            "sbatch",
            "dispatch_intent",
            "batch_intent",
            "global_intent",
            "submitted_at",
            "submission_source",
            "sbatch_stdout",
        }
        if (
            set(submission) != expected_submission_fields
            or submission.get("schema_version") != SCHEMA_VERSION
            or submission.get("artifact_type") != SUBMISSION_RECEIPT_ARTIFACT_TYPE
            or submission.get("study_id") != eval_plan.STUDY_ID
            or submission.get("plan") != eval_plan.file_identity(plan_path)
            or submission.get("task_id") != task["task_id"]
            or submission.get("attempt") != record["attempt"]
            or submission.get("job_id") != record["job_id"]
            or submission.get("comment") != record["comment"]
            or submission.get("sbatch") != task["sbatch"]
            or submission.get("dispatch_intent") != terminal_receipt.get("dispatch_intent")
            or not isinstance(submission.get("batch_intent"), dict)
            or not isinstance(submission.get("global_intent"), dict)
            or not isinstance(submission.get("submitted_at"), str)
            or submission.get("submission_source")
            not in {"sbatch_stdout", "scheduler_reconciliation"}
            or (
                submission.get("submission_source") == "sbatch_stdout"
                and (
                    not isinstance(submission.get("sbatch_stdout"), str)
                    or submission["sbatch_stdout"].split(";", maxsplit=1)[0]
                    != record["job_id"]
                )
            )
            or (
                submission.get("submission_source") == "scheduler_reconciliation"
                and submission.get("sbatch_stdout") is not None
            )
        ):
            raise ValueError(f"Protected submission receipt differs: {task['task_id']}")
        for field in ("dispatch_intent", "batch_intent", "global_intent"):
            identity = submission[field]
            if eval_plan.file_identity(Path(identity["path"])) != identity:
                raise ValueError(f"Protected submission {field} changed: {task['task_id']}")
    return provenance


def _readout_categories(plan: dict[str, Any]) -> tuple[dict[str, dict[PromptKey, str]], dict[str, Any]]:
    tasks = {task["task_id"]: task for task in plan["tasks"]}
    task_categories = {}
    input_artifacts = {}
    for task_id, task in tasks.items():
        records = eval_plan.validate_completed_task(plan, task)
        task_categories[task_id] = category_map(records)
        input_artifacts[task_id] = {
            name: eval_plan.file_identity(Path(task["result_root"]) / name) for name in eval_plan.SUCCESS_ARTIFACT_NAMES
        }
    readouts = {readout["readout_id"]: task_categories[readout["task_id"]] for readout in plan["readouts"]}
    if len(readouts) != plan["checkpoint_selector_count"]:
        raise ValueError("Checkpoint readout map differs")
    return readouts, input_artifacts


def _comparisons(
    prevalence: dict[str, dict[str, Any]],
    transitions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    result = {}
    for clock in (eval_plan.INTERMEDIATE_STEP, eval_plan.FINAL_STEP):
        off_transition = transitions[f"p05_off_to_s{clock}"]
        frozen_transition = transitions[f"frozen_to_clock_{clock}"]
        off = prevalence[f"p05_off_s{clock}"]
        clean = prevalence[f"p00_clean_s{clock}"]
        on = prevalence[f"p05_on_s{clock}"]
        result[str(clock)] = {
            "off_minus_frozen_new_a_incidence": (
                off_transition["new_a_incidence"] - frozen_transition["new_a_incidence"]
            ),
            "off_minus_frozen_net_a_change": (off_transition["net_a_change"] - frozen_transition["net_a_change"]),
            "off_minus_clean_a_prevalence": off["rates"]["A"] - clean["rates"]["A"],
            "off_minus_on_a_prevalence": off["rates"]["A"] - on["rates"]["A"],
            "off_minus_on_strict_prevalence": off["rates"]["S"] - on["rates"]["S"],
        }
    return result


def build_analysis(plan_path: Path) -> dict[str, Any]:
    eval_plan.validate_plan(plan_path, require_complete=True)
    _, plan = eval_plan._read_json(plan_path)
    terminal = _terminal_provenance(plan, plan_path)
    readouts, input_artifacts = _readout_categories(plan)
    implementation = eval_plan.file_identity(Path(__file__))
    expected_implementation = {
        field: plan["implementations"]["analyzer"][field] for field in ("path", "size_bytes", "sha256")
    }
    if implementation != expected_implementation:
        raise ValueError("Analyzer implementation differs from the pre-outcome authority")
    prevalence = {
        band: {readout_id: summarize_prevalence(values, operations) for readout_id, values in sorted(readouts.items())}
        for band, operations in BANDS.items()
    }
    transition_contract = plan["readout_contract"]["transitions"]
    transitions = {}
    for band, operations in BANDS.items():
        transitions[band] = {}
        for transition in transition_contract:
            transitions[band][transition["transition_id"]] = summarize_transition(
                readouts[transition["source_readout_id"]],
                readouts[transition["endpoint_readout_id"]],
                operations,
            )
    comparisons = {band: _comparisons(prevalence[band], transitions[band]) for band in BANDS}
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "study_id": eval_plan.STUDY_ID,
        "plan": eval_plan.file_identity(plan_path),
        "terminal_provenance": eval_plan.file_identity(Path(plan["plan_root"]) / TERMINAL_PROVENANCE_NAME),
        "terminal_task_count": len(terminal["tasks"]),
        "implementation": implementation,
        "input_artifacts": input_artifacts,
        "category_contract": plan["analysis_contract"],
        "bands": {name: list(operations) for name, operations in BANDS.items()},
        "prevalence": prevalence,
        "transitions": transitions,
        "comparisons": comparisons,
        "interpretation_limit": (
            "paired held-out prompt/seed response transitions are not literal training-trajectory lineages"
        ),
    }
    return {**payload, SELF_HASH_FIELD: eval_plan.canonical_json_sha256(payload)}


def materialize_analysis(plan_path: Path, output: Path) -> Path:
    analysis = build_analysis(plan_path)
    eval_plan._write_once(output, eval_plan.canonical_json_bytes(analysis))
    return output.expanduser().resolve()


def validate_analysis(path: Path) -> dict[str, Any]:
    raw, analysis = eval_plan._read_json(path)
    recorded = analysis.get(SELF_HASH_FIELD)
    payload = {key: value for key, value in analysis.items() if key != SELF_HASH_FIELD}
    if recorded != eval_plan.canonical_json_sha256(payload):
        raise ValueError("Analysis self hash differs")
    if analysis.get("schema_version") != SCHEMA_VERSION or analysis.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("Analysis schema differs")
    expected = build_analysis(Path(analysis["plan"]["path"]))
    if raw != eval_plan.canonical_json_bytes(expected):
        raise ValueError("Analysis differs from deterministic replay")
    return {
        "analysis": str(path.expanduser().resolve()),
        "payload_without_self_hash_sha256": recorded,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--plan", type=Path, required=True)
    analyze.add_argument("--output", type=Path)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--analysis", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "analyze":
        _, plan = eval_plan._read_json(args.plan)
        output = args.output or Path(plan["plan_root"]) / "analysis.json"
        path = materialize_analysis(args.plan, output)
        result = validate_analysis(path)
    else:
        result = validate_analysis(args.analysis)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
