#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from jinja2 import Template

EXPECTED_NEMO_GYM_COMMIT = "354babf7e3554fcd006807c86e80ef476aec9408"
EXPECTED_NEMO_EVALUATOR_COMMIT = "230c8411fff82fa581195b7d088d7fb67d3bc98c"
EXPECTED_VERSION = "1.17.0"
FINISHED_STATUS = "ConversationExecutionStatus.FINISHED"
ERROR_STATUS = "ConversationExecutionStatus.ERROR"
EXPECTED_SYSTEM_PROMPT_SHA256 = "f413d0fd1e5a1482d0d473e2de399a0a0c99f645d3838ef6cf887a167b7a31b6"
EXPECTED_INSTRUCTION_TEMPLATE_SHA256 = "1605532f463c04d02bf315d47865db34960e0c6d0870cf8aa8598ecc17d22ea7"
EXPECTED_MODEL = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16"
EXPECTED_TOOL_NAMES = {"file_editor", "finish", "task_tracker", "terminal", "think"}
ASSET_DIR = Path(__file__).resolve().parent
INSTRUCTION_TEMPLATE = ASSET_DIR / "official_instruction.j2"
SYSTEM_PROMPT = ASSET_DIR / "official_system_prompt.txt"
DEFAULT_DATASET_DIR = Path.home() / ".cache/harbor/swebench-verified/swebench-verified"


def _load(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open() as file:
        for line_number, line in enumerate(file, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{line_number}: {error}") from error
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--expected-rows", type=int)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    rows = _load(args.results)
    issues = []
    template_bytes = INSTRUCTION_TEMPLATE.read_bytes()
    template_sha256 = hashlib.sha256(template_bytes).hexdigest()
    if template_sha256 != EXPECTED_INSTRUCTION_TEMPLATE_SHA256:
        issues.append({"issue": f"unexpected instruction-template hash {template_sha256}"})
    instruction_template = Template(template_bytes.decode())
    system_prompt_bytes = SYSTEM_PROMPT.read_bytes()
    system_prompt_sha256 = hashlib.sha256(system_prompt_bytes).hexdigest()
    if system_prompt_sha256 != EXPECTED_SYSTEM_PROMPT_SHA256:
        issues.append({"issue": f"unexpected system-prompt hash {system_prompt_sha256}"})
    system_prompt = system_prompt_bytes.decode()
    versions = Counter()
    stop_conditions = Counter()
    total_requests = 0
    total_reasoning_responses = 0
    total_replay_hits = 0
    total_http_errors = 0
    total_transport_errors = 0
    rows_with_exceptions = 0
    context_limit_terminations = 0
    max_iteration_exhaustions = 0
    execution_statuses = Counter()

    for row_number, row in enumerate(rows, 1):
        stop_condition = row.get("stop_condition")
        stop_conditions[stop_condition] += 1
        info = row.get("info") or {}
        metadata = info.get("openhands_sdk")
        if not isinstance(metadata, dict):
            issues.append({"row": row_number, "issue": "missing info.openhands_sdk"})
            continue
        agent = metadata.get("agent") or {}
        proxy = metadata.get("proxy") or {}
        manifest = metadata.get("archive_manifest") or {}
        source = (manifest.get("source") or {}) if isinstance(manifest, dict) else {}
        packages = (manifest.get("packages") or {}) if isinstance(manifest, dict) else {}
        patches = (manifest.get("patches") or {}) if isinstance(manifest, dict) else {}

        version = agent.get("openhands_sdk_version")
        versions[str(version)] += 1
        execution_status = str(agent.get("execution_status"))
        execution_statuses[execution_status] += 1
        if version != EXPECTED_VERSION:
            issues.append({"row": row_number, "issue": f"OpenHands SDK version {version!r}"})
        if agent.get("openhands_tools_version") != EXPECTED_VERSION:
            issues.append({"row": row_number, "issue": "unexpected OpenHands tools version"})
        if agent.get("max_iterations") != 200:
            issues.append({"row": row_number, "issue": "max_iterations is not 200"})
        if packages.get("openhands-sdk") != EXPECTED_VERSION or packages.get("openhands-tools") != EXPECTED_VERSION:
            issues.append({"row": row_number, "issue": "archive package versions are not 1.17.0"})
        if set(patches) != {"continue_text_only", "always_nudge_no_tool", "terminal_timeout_1800"}:
            issues.append({"row": row_number, "issue": "archive patch manifest is incomplete"})
        elif any(value not in {"patched", "already_patched"} for value in patches.values()):
            issues.append({"row": row_number, "issue": "archive patch did not apply cleanly"})
        if source.get("nemo_gym_commit") != EXPECTED_NEMO_GYM_COMMIT:
            issues.append({"row": row_number, "issue": "unexpected NeMo Gym source commit"})
        if source.get("nemo_evaluator_commit") != EXPECTED_NEMO_EVALUATOR_COMMIT:
            issues.append({"row": row_number, "issue": "unexpected NeMo Evaluator source commit"})
        if metadata.get("system_prompt_sha256") != EXPECTED_SYSTEM_PROMPT_SHA256:
            issues.append({"row": row_number, "issue": "unexpected harness system-prompt hash"})

        task = row.get("task") or {}
        task_name = task.get("name") if isinstance(task, dict) else None
        task_prompt = task.get("prompt") if isinstance(task, dict) else None
        task_config = args.dataset_dir / str(task_name) / "tests" / "config.json"
        if not isinstance(task_name, str) or not isinstance(task_prompt, str) or not task_config.is_file():
            issues.append({"row": row_number, "issue": "cannot reconstruct official task instruction"})
        else:
            instance = json.loads(task_config.read_text())
            instance["repo_language"] = "Python"
            instance["problem_statement"] = task_prompt.strip()
            instruction = instruction_template.render(workspace_path=task.get("workdir"), instance=instance)
            instruction_sha256 = hashlib.sha256(instruction.encode()).hexdigest()
            if metadata.get("instruction_sha256") != instruction_sha256:
                issues.append({"row": row_number, "issue": "official task-instruction mismatch"})

        candidate = info.get("swebench_candidate_patch") or {}
        patch = candidate.get("patch") if isinstance(candidate, dict) else None
        if not isinstance(patch, str):
            issues.append({"row": row_number, "issue": "missing candidate patch"})
        elif re.search(r"^(?:old|new) mode ", patch, flags=re.MULTILINE):
            issues.append({"row": row_number, "issue": "candidate patch contains VMVM file-mode noise"})
        if proxy.get("schema_version") != 2:
            issues.append({"row": row_number, "issue": "unexpected proxy audit schema"})
        if proxy.get("system_prompt_sha256") != EXPECTED_SYSTEM_PROMPT_SHA256:
            issues.append({"row": row_number, "issue": "unexpected proxy system-prompt hash"})

        requests = proxy.get("requests")
        if not isinstance(requests, int) or not 1 <= requests <= 200:
            issues.append({"row": row_number, "issue": f"invalid proxy request count {requests!r}"})
            continue
        total_requests += requests
        total_reasoning_responses += int(proxy.get("reasoning_responses") or 0)
        total_replay_hits += int(proxy.get("replay_hits") or 0)
        responses = int(proxy.get("responses") or 0)
        http_errors = int(proxy.get("http_errors") or 0)
        transport_errors = int(proxy.get("transport_errors") or 0)
        total_http_errors += http_errors
        total_transport_errors += transport_errors
        if responses + http_errors + transport_errors != requests:
            issues.append({"row": row_number, "issue": "proxy request/response accounting mismatch"})
        if not proxy.get("reasoning_responses"):
            issues.append({"row": row_number, "issue": "no parsed reasoning response"})
        if not proxy.get("tool_call_responses"):
            issues.append({"row": row_number, "issue": "no native tool-call response"})

        details = proxy.get("request_details") or []
        if len(details) != requests:
            issues.append({"row": row_number, "issue": "request detail count mismatch"})

        exception = agent.get("exception")
        if exception:
            rows_with_exceptions += 1
        expected_context_limit = (
            stop_condition == "context_length"
            and execution_status == ERROR_STATUS
            and isinstance(exception, dict)
            and exception.get("type") == "ConversationRunError"
            and str(exception.get("message", "")).endswith(
                "OpenAIException - rollout stopped: context_length"
            )
            and http_errors == 1
            and transport_errors == 0
            and responses == requests - 1
            and bool(details)
            and details[-1].get("status") == 400
        )
        expected_iteration_exhaustion = (
            execution_status == ERROR_STATUS
            and exception is None
            and requests == 200
            and http_errors == 0
            and transport_errors == 0
        )
        if expected_context_limit:
            context_limit_terminations += 1
        elif expected_iteration_exhaustion:
            max_iteration_exhaustions += 1
        else:
            if exception:
                issues.append({"row": row_number, "issue": "OpenHands agent raised an exception"})
            if http_errors:
                issues.append({"row": row_number, "issue": f"proxy recorded {http_errors} HTTP error(s)"})
            if transport_errors:
                issues.append({"row": row_number, "issue": f"proxy recorded {transport_errors} transport error(s)"})
            if execution_status != FINISHED_STATUS:
                issues.append(
                    {
                        "row": row_number,
                        "issue": f"unexpected OpenHands execution status {execution_status!r}",
                    }
                )

        for expected_turn, detail in enumerate(details, 1):
            turn = detail.get("turn")
            if turn != expected_turn:
                issues.append({"row": row_number, "turn": turn, "issue": "non-sequential turn counter"})
                break
            expected_prompt = system_prompt
            if isinstance(turn, int) and turn >= 190:
                expected_prompt += (
                    f"\n\n[SYSTEM] URGENT: Turn {turn}/200 — only {200 - turn} turn(s) left. "
                    "You MUST provide your final answer NOW. Do not start new work."
                )
            elif isinstance(turn, int) and turn >= 160:
                expected_prompt += (
                    f"\n\n[SYSTEM] Turn {turn}/200 — {200 - turn} turns remaining. "
                    "Begin wrapping up: finish current work and prepare your final answer."
                )
            expected_prompt_sha256 = hashlib.sha256(expected_prompt.encode()).hexdigest()
            if detail.get("system_prompt_sha256") != expected_prompt_sha256:
                issues.append({"row": row_number, "turn": turn, "issue": "official system prompt mismatch"})
                break
            if set(detail.get("tool_names") or []) != EXPECTED_TOOL_NAMES:
                issues.append({"row": row_number, "turn": turn, "issue": "missing OpenHands SDK tools"})
                break
            if detail.get("model") != EXPECTED_MODEL:
                issues.append({"row": row_number, "turn": turn, "issue": "unexpected model identifier"})
                break
            if detail.get("temperature") != 1.0 or detail.get("top_p") != 0.95:
                issues.append({"row": row_number, "turn": turn, "issue": "sampling settings mismatch"})
                break
            if detail.get("enable_thinking") is not True or detail.get("skip_special_tokens") is not False:
                issues.append({"row": row_number, "turn": turn, "issue": "chat-template settings mismatch"})
                break
            if detail.get("forbidden_params_present"):
                issues.append({"row": row_number, "turn": turn, "issue": "officially dropped parameter is present"})
                break

    if args.expected_rows is not None and len(rows) != args.expected_rows:
        issues.append({"issue": f"expected {args.expected_rows} rows, found {len(rows)}"})

    report = {
        "results": str(args.results),
        "rows": len(rows),
        "expected_rows": args.expected_rows,
        "instruction_template_sha256": template_sha256,
        "system_prompt_sha256": system_prompt_sha256,
        "versions": dict(versions),
        "stop_conditions": dict(stop_conditions),
        "total_requests": total_requests,
        "total_reasoning_responses": total_reasoning_responses,
        "total_replay_hits": total_replay_hits,
        "total_http_errors": total_http_errors,
        "total_transport_errors": total_transport_errors,
        "rows_with_agent_exceptions": rows_with_exceptions,
        "context_limit_terminations": context_limit_terminations,
        "max_iteration_exhaustions": max_iteration_exhaustions,
        "execution_statuses": dict(execution_statuses),
        "issues": issues,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.strict and issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
