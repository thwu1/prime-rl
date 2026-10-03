from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_catalog(source: Path) -> list[dict[str, object]]:
    tasks_root = source / "tasks" / "finalpool"
    rows: list[dict[str, object]] = []
    for task_dir in sorted(path for path in tasks_root.iterdir() if path.is_dir()):
        config = json.loads((task_dir / "task_config.json").read_text())
        rows.append(
            {
                "task_id": task_dir.name,
                "description": (task_dir / "docs" / "task.md").read_text(),
                "system_prompt_template": (task_dir / "docs" / "agent_system_prompt.md").read_text(),
                "needed_mcp_servers": config.get("needed_mcp_servers") or [],
                "needed_local_tools": config.get("needed_local_tools") or [],
                "stop_tool_names": ["local-claim_done"],
            }
        )
    task_ids = [str(row["task_id"]) for row in rows]
    if len(rows) != 108 or len(set(task_ids)) != len(rows):
        raise ValueError(f"Expected 108 unique Toolathlon tasks, found {len(rows)}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = build_catalog(args.source.resolve())
    args.output.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
