#!/usr/bin/env python3

import argparse
import json
import re
import tomllib
from pathlib import Path

from audit_results import has_mode_changes, is_dirty_row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a targeted eval config for dirty one-rollout tasks.")
    parser.add_argument("base_config", type=Path)
    parser.add_argument("results", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--include-mode-changes",
        action="store_true",
        help="Also rerun rows whose SWE-bench candidate patch contains old/new mode entries.",
    )
    return parser.parse_args()


def dirty_task_names(results_path: Path, include_mode_changes: bool) -> list[str]:
    tasks: dict[int, str] = {}
    indices_by_name: dict[str, int] = {}
    with results_path.open() as results:
        for line in results:
            if not line.strip():
                continue
            row = json.loads(line)
            if not is_dirty_row(row) and not (include_mode_changes and has_mode_changes(row)):
                continue
            task = row["task"]
            idx = int(task["idx"])
            name = str(task["name"])
            if idx in tasks:
                raise ValueError(f"duplicate dirty row for task index {idx}")
            if name in indices_by_name:
                raise ValueError(f"duplicate dirty row for task name {name}")
            tasks[idx] = name
            indices_by_name[name] = idx
    return [tasks[idx] for idx in sorted(tasks)]


def render_config(base_config: Path, tasks: list[str]) -> str:
    text = base_config.read_text()
    text, replacements = re.subn(
        r"(?m)^num_tasks\s*=\s*\d+\s*$",
        f"num_tasks = {len(tasks)}",
        text,
        count=1,
    )
    if replacements != 1:
        raise ValueError(f"expected one top-level num_tasks in {base_config}")
    taskset_header = "[taskset]"
    if text.count(taskset_header) != 1:
        raise ValueError(f"expected one [taskset] section in {base_config}")
    tasks_line = f"tasks = {json.dumps(tasks)}"
    text = text.replace(taskset_header, f"{taskset_header}\n{tasks_line}", 1)
    tomllib.loads(text)
    return text


def main() -> None:
    args = parse_args()
    tasks = dirty_task_names(args.results, args.include_mode_changes)
    if tasks:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_config(args.base_config, tasks))
    print(len(tasks))


if __name__ == "__main__":
    main()
