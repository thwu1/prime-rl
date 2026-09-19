from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path
from typing import Any

from worker import _build_static_tools

TOOL_DEFINITION = re.compile(r"<function>\s*<name>([^<]+)</name>")
TOOL_CALL = re.compile(r"<tool_call>\s*<function=([^>\n]+)>")


def _tool_names(content: Any, pattern: re.Pattern[str]) -> list[str]:
    return pattern.findall(content) if isinstance(content, str) else []


def audit(dataset: Path, catalog_path: Path, schemas_path: Path) -> dict[str, Any]:
    catalog = json.loads(catalog_path.read_text())
    schemas = json.loads(schemas_path.read_text())
    expected_local: set[str] = set()
    for task in catalog:
        _, dispatch_names = _build_static_tools(task, schemas)
        expected_local.update(
            model_name
            for model_name, service_name in dispatch_names.items()
            if service_name.startswith("local-") or service_name.startswith("virtual:local-")
        )

    prompt_names: collections.Counter[str] = collections.Counter()
    call_names: collections.Counter[str] = collections.Counter()
    missing_call_definitions: collections.Counter[str] = collections.Counter()
    rows = 0
    rows_with_hyphenated_local_names = 0
    rows_with_underscore_local_names = 0
    for line in dataset.open():
        row = json.loads(line)
        rows += 1
        row_prompt_names: set[str] = set()
        row_call_names: list[str] = []
        for message in row["messages"]:
            role = message.get("role")
            content = message.get("content")
            if role == "system":
                row_prompt_names.update(_tool_names(content, TOOL_DEFINITION))
            elif role == "assistant":
                row_call_names.extend(_tool_names(content, TOOL_CALL))
        prompt_names.update(row_prompt_names)
        call_names.update(row_call_names)
        missing_call_definitions.update(name for name in row_call_names if name not in row_prompt_names)
        rows_with_hyphenated_local_names += any(name.startswith("local-") for name in row_prompt_names)
        rows_with_underscore_local_names += any(name.startswith("local_") for name in row_prompt_names)

    training_local = {name for name in prompt_names if name.startswith("local")}
    normalized_training_local = {name.replace("-", "_") for name in training_local}
    return {
        "dataset": str(dataset),
        "rows": rows,
        "distinct_prompt_tools": len(prompt_names),
        "distinct_called_tools": len(call_names),
        "training_local_tools": sorted(training_local),
        "official_eval_local_tools": sorted(expected_local),
        "local_names_match_after_normalization": normalized_training_local == expected_local,
        "missing_after_normalization": sorted(expected_local - normalized_training_local),
        "extra_after_normalization": sorted(normalized_training_local - expected_local),
        "rows_with_hyphenated_local_names": rows_with_hyphenated_local_names,
        "rows_with_underscore_local_names": rows_with_underscore_local_names,
        "hyphenated_external_prompt_tools": sorted(
            name for name in prompt_names if "-" in name and not name.startswith("local-")
        ),
        "hyphenated_external_called_tools": sorted(
            name for name in call_names if "-" in name and not name.startswith("local-")
        ),
        "calls_missing_from_row_tool_definitions": dict(missing_call_definitions),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--task-catalog", type=Path, default=Path(__file__).with_name("task_catalog_verified.json"))
    parser.add_argument("--tool-schemas", type=Path, default=Path(__file__).with_name("tool_schemas.json"))
    args = parser.parse_args()
    print(json.dumps(audit(args.dataset, args.task_catalog, args.tool_schemas), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
