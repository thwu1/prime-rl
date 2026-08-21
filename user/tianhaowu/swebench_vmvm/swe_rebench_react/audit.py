#!/usr/bin/env python3

import argparse
import collections
import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

EXPECTED_SYSTEM_PROMPT_SHA256 = "dbae17152474bee3819551922242c3fd4189727114442d86b7b3ff75e649ee6c"
EXPECTED_MODEL = "Qwen/Qwen3.6-27B"
COMMAND_BLOCK = re.compile(r"```command[ \t]*\r?\n(.*?)```", re.DOTALL)
ASSET_DIR = Path(__file__).resolve().parent
SYSTEM_PROMPT = ASSET_DIR / "system_prompt.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the fixed SWE-rebench ReAct protocol.")
    parser.add_argument("results", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--expected-rows", type=int)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def initial_message(issue: str, workdir: str) -> str:
    return (
        "# ISSUE DESCRIPTION\n\n"
        f"{issue.strip()}\n\n"
        "# ADDITIONAL ADVICE\n\n"
        "Since you are given a git repository, you can use git commands to simplify "
        "your work. Do not commit or stage changes; the evaluator uses git diff.\n\n"
        "Repository has been uploaded and your shell is currently at the repository "
        "root. Time to solve the issue!\n\n"
        f"(Current directory: {workdir}, current file: none) bash-$"
    )


def nested(config: dict[str, Any], *keys: str) -> Any:
    value: Any = config
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def expected_tasks(config: dict[str, Any]) -> list[dict[str, object]]:
    dataset_dir = Path(nested(config, "taskset", "dataset_dir"))
    selected = nested(config, "taskset", "tasks")
    task_dirs = [
        path.parent
        for path in sorted(dataset_dir.rglob("task.toml"))
        if (path.parent / "instruction.md").is_file() and (selected is None or path.parent.name in selected)
    ]
    tasks = []
    for idx, task_dir in enumerate(task_dirs):
        task_config = tomllib.loads((task_dir / "task.toml").read_text())
        instance = json.loads((task_dir / "tests" / "config.json").read_text())
        dockerfile = task_dir / "environment" / "Dockerfile"
        image = next(
            line.split(None, 1)[1].strip()
            for line in dockerfile.read_text().splitlines()
            if line.strip().upper().startswith("FROM ")
        )
        tasks.append(
            {
                "idx": idx,
                "name": task_config["task"]["name"],
                "prompt": (task_dir / "instruction.md").read_text().strip(),
                "image": image,
                "workdir": f"/{instance['repo'].split('/', 1)[1]}",
            }
        )
    return tasks


def main() -> None:
    args = parse_args()
    config_path = args.config or args.results.parent / "config.toml"
    config = tomllib.loads(config_path.read_text())
    dataset_tasks = expected_tasks(config)
    system_prompt = SYSTEM_PROMPT.read_text()
    system_prompt_sha256 = hashlib.sha256(SYSTEM_PROMPT.read_bytes()).hexdigest()

    expected_config = {
        ("model",): EXPECTED_MODEL,
        ("num_tasks",): 111,
        ("num_rollouts",): 5,
        ("max_turns",): 250,
        ("sampling", "temperature"): 1.0,
        ("sampling", "top_p"): 0.95,
        ("sampling", "top_k"): 20,
        ("sampling", "min_p"): 0.0,
        ("sampling", "presence_penalty"): 0.0,
        ("sampling", "repetition_penalty"): 1.0,
        ("sampling", "max_tokens"): 81_920,
        ("sampling", "chat_template_kwargs", "enable_thinking"): True,
        ("sampling", "chat_template_kwargs", "preserve_thinking"): True,
        ("taskset", "id"): "swe-rebench-harbor",
        ("harness", "id"): "swe-rebench-react",
        ("harness", "max_steps"): 250,
        ("harness", "command_timeout"): 300,
        ("harness", "output_limit"): 20_000,
        ("harness", "runtime", "type"): "vmvm",
    }
    config_issues = []
    for keys, expected in expected_config.items():
        actual = nested(config, *keys)
        if actual != expected:
            config_issues.append({"field": ".".join(keys), "expected": expected, "actual": actual})
    if system_prompt_sha256 != EXPECTED_SYSTEM_PROMPT_SHA256:
        config_issues.append(
            {
                "field": "system_prompt_sha256",
                "expected": EXPECTED_SYSTEM_PROMPT_SHA256,
                "actual": system_prompt_sha256,
            }
        )
    if len(dataset_tasks) != 111:
        config_issues.append({"field": "taskset.dataset_dir", "expected_tasks": 111, "actual": len(dataset_tasks)})

    rows = 0
    sampled_assistants = 0
    rows_with_valid_commands = 0
    rows_with_submit = 0
    malformed_responses = 0
    native_tool_responses = 0
    stop_conditions: collections.Counter[str] = collections.Counter()
    task_counts: collections.Counter[int] = collections.Counter()
    row_issues: list[dict[str, object]] = []

    with args.results.open() as results:
        for line_number, line in enumerate(results, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            task = row.get("task") or {}
            task_ref = {"row": line_number, "idx": task.get("idx"), "name": task.get("name")}
            task_idx = task.get("idx")
            if not isinstance(task_idx, int) or not 0 <= task_idx < len(dataset_tasks):
                row_issues.append({**task_ref, "issue": "task index is outside the configured dataset"})
            else:
                task_counts[task_idx] += 1
                expected_task = dataset_tasks[task_idx]
                for field in ("name", "prompt", "image", "workdir"):
                    if task.get(field) != expected_task[field]:
                        row_issues.append({**task_ref, "issue": f"task {field} differs from the Harbor source"})
            nodes = row.get("nodes") or []
            stop_conditions[str(row.get("stop_condition") or "missing")] += 1
            if len(nodes) < 2:
                row_issues.append({**task_ref, "issue": "trajectory has fewer than two seed nodes"})
                continue

            system = nodes[0].get("message") or {}
            if system.get("role") != "system" or system.get("content") != system_prompt:
                row_issues.append({**task_ref, "issue": "system prompt mismatch"})
            user = nodes[1].get("message") or {}
            prompt = task.get("prompt")
            workdir = task.get("workdir")
            if not isinstance(prompt, str) or not isinstance(workdir, str):
                row_issues.append({**task_ref, "issue": "task prompt or workdir is invalid"})
            elif user.get("role") != "user" or user.get("content") != initial_message(prompt, workdir):
                row_issues.append({**task_ref, "issue": "initial task message mismatch"})

            row_commands = 0
            row_submits = 0
            row_sampled = 0
            for position, node in enumerate(nodes):
                if not node.get("sampled"):
                    continue
                row_sampled += 1
                sampled_assistants += 1
                message = node.get("message") or {}
                if message.get("role") != "assistant":
                    row_issues.append({**task_ref, "position": position, "issue": "sampled node is not assistant"})
                    continue
                if message.get("tool_calls"):
                    native_tool_responses += 1
                    row_issues.append(
                        {**task_ref, "position": position, "issue": "native tool call in text-command run"}
                    )
                content = message.get("content")
                if not isinstance(content, str):
                    row_issues.append({**task_ref, "position": position, "issue": "assistant content is not text"})
                    continue
                commands = COMMAND_BLOCK.findall(content)
                if len(commands) != 1:
                    malformed_responses += 1
                    continue
                row_commands += 1
                if commands[0].strip() == "submit":
                    row_submits += 1
            if row_sampled > 250:
                row_issues.append({**task_ref, "issue": f"sampled {row_sampled} turns, expected at most 250"})
            if row_commands == 0:
                row_issues.append({**task_ref, "issue": "no valid text-command response"})
            rows_with_valid_commands += int(row_commands > 0)
            rows_with_submit += int(row_submits > 0)

    if args.expected_rows is not None and rows != args.expected_rows:
        row_issues.append({"issue": f"expected {args.expected_rows} rows, found {rows}"})
    expected_rollouts = nested(config, "num_rollouts")
    for task in dataset_tasks:
        count = task_counts[task["idx"]]
        if count != expected_rollouts:
            row_issues.append(
                {
                    "idx": task["idx"],
                    "name": task["name"],
                    "issue": f"expected {expected_rollouts} rollouts, found {count}",
                }
            )

    report = {
        "results": str(args.results.resolve()),
        "config": str(config_path.resolve()),
        "rows": rows,
        "expected_rows": args.expected_rows,
        "dataset_tasks": len(dataset_tasks),
        "system_prompt_sha256": system_prompt_sha256,
        "sampled_assistants": sampled_assistants,
        "rows_with_valid_commands": rows_with_valid_commands,
        "rows_with_submit": rows_with_submit,
        "malformed_responses": malformed_responses,
        "native_tool_responses": native_tool_responses,
        "stop_conditions": dict(sorted(stop_conditions.items())),
        "config_issues": config_issues,
        "row_issues": row_issues,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.strict and (config_issues or row_issues):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
