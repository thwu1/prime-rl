#!/usr/bin/env python3

import argparse
import hashlib
import json
from pathlib import Path

from audit_results import has_mode_changes, is_dirty_row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replace dirty one-rollout task rows with clean repair rows.")
    parser.add_argument("base", type=Path)
    parser.add_argument("repairs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-tasks", type=int, required=True)
    parser.add_argument("--reject-mode-changes", action="store_true")
    return parser.parse_args()


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def task_key(row: dict) -> tuple[int, str]:
    task = row["task"]
    return int(task["idx"]), str(task["name"])


def load_repairs(paths: list[Path], reject_mode_changes: bool) -> dict[str, dict]:
    repairs: dict[str, dict] = {}
    for path in paths:
        with path.open("rb") as source:
            for raw in source:
                if not raw.strip():
                    continue
                row = json.loads(raw)
                _, name = task_key(row)
                if is_dirty_row(row):
                    raise ValueError(f"repair row is dirty: {name} in {path}")
                if reject_mode_changes and has_mode_changes(row):
                    raise ValueError(f"repair row contains mode changes: {name} in {path}")
                if name in repairs:
                    raise ValueError(f"duplicate repair row for {name}")
                repairs[name] = row
    if not repairs:
        raise ValueError("no repair rows found")
    return repairs


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    inputs = [args.base.resolve(), *(path.resolve() for path in args.repairs)]
    if output in inputs:
        raise ValueError("output must not overwrite an input result file")
    if output.exists():
        raise FileExistsError(output)

    repairs = load_repairs(args.repairs, args.reject_mode_changes)
    seen_names: set[str] = set()
    seen_indices: set[int] = set()
    replaced: list[dict[str, object]] = []
    rows = 0
    dirty = 0
    temporary = output.with_suffix(output.suffix + ".tmp")
    output.parent.mkdir(parents=True, exist_ok=True)

    with args.base.open("rb") as source, temporary.open("wb") as target:
        for raw in source:
            if not raw.strip():
                continue
            row = json.loads(raw)
            idx, name = task_key(row)
            if name in seen_names:
                raise ValueError(f"duplicate base row for {name}")
            if idx in seen_indices:
                raise ValueError(f"duplicate base task index {idx}")
            seen_names.add(name)
            seen_indices.add(idx)
            selected_row = repairs.get(name, row)
            if name in repairs:
                base_task = row["task"]
                repair_task = selected_row["task"]
                for field in ("name", "prompt", "image", "workdir"):
                    if repair_task.get(field) != base_task.get(field):
                        raise ValueError(f"repair task {name} has a mismatched {field} field")
            selected_row["task"]["idx"] = idx
            if is_dirty_row(selected_row) or (args.reject_mode_changes and has_mode_changes(selected_row)):
                dirty += 1
            if name in repairs:
                replaced.append({"idx": idx, "name": name})
                selected = json.dumps(selected_row, separators=(",", ":")).encode() + b"\n"
            else:
                selected = raw if raw.endswith(b"\n") else raw + b"\n"
            target.write(selected)
            rows += 1

    missing_repairs = sorted(set(repairs) - seen_names)
    if missing_repairs:
        temporary.unlink()
        raise ValueError("repair tasks absent from base: " + ", ".join(missing_repairs))
    if rows != args.expected_tasks:
        temporary.unlink()
        raise ValueError(f"expected {args.expected_tasks} base rows, found {rows}")
    if dirty:
        temporary.unlink()
        raise ValueError(f"merged result still contains {dirty} dirty rows")

    temporary.replace(output)
    provenance = {
        "base": {"path": str(inputs[0]), "sha256": digest(inputs[0])},
        "repairs": [{"path": str(path), "sha256": digest(path)} for path in inputs[1:]],
        "output": {"path": str(output), "sha256": digest(output)},
        "replaced_tasks": sorted(replaced, key=lambda task: int(task["idx"])),
    }
    provenance_path = output.with_suffix(output.suffix + ".provenance.json")
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(json.dumps(provenance, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
