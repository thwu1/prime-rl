#!/usr/bin/env python3
"""Materialize a strict, digest-pinned oracle subset from verified build receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
TASK_NAME = re.compile(r"[A-Za-z0-9._-]+")
COMPOSE_FILES = ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _plan(path: Path, dataset_dir: Path) -> tuple[list[str], dict[str, list[dict[str, str]]]]:
    order: list[str] = []
    tasks: dict[str, list[dict[str, str]]] = {}
    status_keys: set[tuple[str, str]] = set()
    for raw in path.read_text().splitlines():
        if not raw:
            continue
        fields = raw.split("\t")
        if len(fields) != 5:
            raise SystemExit("build plan contains an invalid row")
        task, role, context_sha256, context_raw, image = fields
        context = Path(context_raw).resolve(strict=True)
        key = (context_sha256, role)
        if (
            TASK_NAME.fullmatch(task) is None
            or role not in {"agent", "verifier"}
            or re.fullmatch(r"[0-9a-f]{64}", context_sha256) is None
            or not context.is_relative_to(dataset_dir)
            or image.partition("/")[0] != "588845226011.dkr.ecr.us-east-2.amazonaws.com"
            or key in status_keys
        ):
            raise SystemExit("build plan contains an unsafe or duplicate row")
        status_keys.add(key)
        if task not in tasks:
            order.append(task)
            tasks[task] = []
        tasks[task].append(
            {
                "task": task,
                "role": role,
                "context_sha256": context_sha256,
                "context": str(context),
                "image": image,
            }
        )
    if not order:
        raise SystemExit("build plan is empty")
    return order, tasks


def _strict_receipt(path: Path, row: dict[str, str]) -> tuple[dict[str, object] | None, bytes]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, json.JSONDecodeError):
        return None, b""
    digest = value.get("digest") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("state") != "success"
        or value.get("cleanup_verified") is not True
        or value.get("task") != row["task"]
        or value.get("role") != row["role"]
        or value.get("context_sha256") != row["context_sha256"]
        or value.get("image") != row["image"]
        or not isinstance(digest, str)
        or SHA256.fullmatch(digest) is None
    ):
        return None, payload
    return value, payload


def materialize(
    *,
    plan_path: Path,
    status_root: Path,
    dataset_dir: Path,
    task_file: Path,
    manifest_path: Path,
    receipt_path: Path,
    excluded_name_pattern: str,
    dataset_tree_sha256: str,
    expected_tasks: int,
    expected_plan_rows: int,
    expected_strict_images: int,
    expected_selected: int,
    expected_incomplete: int,
    expected_compose: int,
    minimum_selected: int,
) -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{64}", dataset_tree_sha256) is None:
        raise SystemExit("dataset tree digest is invalid")
    dataset_dir = dataset_dir.resolve(strict=True)
    pattern = re.compile(excluded_name_pattern, flags=re.IGNORECASE)
    order, tasks = _plan(plan_path, dataset_dir)
    plan_rows = sum(map(len, tasks.values()))
    if len(order) != expected_tasks or plan_rows != expected_plan_rows:
        raise SystemExit("pinned build-plan aggregate changed")
    if any(pattern.search(task) for task in order):
        raise SystemExit("excluded-category boundary changed")

    strict_images = 0
    complete: dict[str, dict[str, str]] = {}
    incomplete = 0
    compose = 0
    failure_classes: Counter[str] = Counter()
    status_snapshot = hashlib.sha256()
    for task in order:
        task_images: dict[str, str] = {}
        task_complete = True
        for row in tasks[task]:
            receipt_file = status_root / f"{row['context_sha256']}.{row['role']}.json"
            receipt, payload = _strict_receipt(receipt_file, row)
            status_snapshot.update(receipt_file.name.encode())
            status_snapshot.update(b"\0")
            status_snapshot.update(hashlib.sha256(payload).digest())
            if receipt is None:
                task_complete = False
                try:
                    failure = json.loads(payload)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    failure = None
                label = failure.get("diagnostic_class") if isinstance(failure, dict) else None
                safe_label = label if isinstance(label, str) and TASK_NAME.fullmatch(label) else "unavailable"
                failure_classes[safe_label] += 1
                continue
            strict_images += 1
            repository = row["image"].rsplit(":", 1)[0]
            task_images[row["role"]] = f"{repository}@{receipt['digest']}"
        environment = dataset_dir / task / "environment"
        is_compose = any((environment / name).is_file() for name in COMPOSE_FILES)
        if is_compose:
            compose += 1
        elif task_complete and "agent" in task_images:
            complete[task] = task_images
        else:
            incomplete += 1

    if (
        strict_images != expected_strict_images
        or len(complete) != expected_selected
        or incomplete != expected_incomplete
        or compose != expected_compose
        or len(complete) < minimum_selected
    ):
        raise SystemExit("strict subset aggregate does not match its pinned contract")

    selected = [task for task in order if task in complete]
    task_payload = "".join(f"{task}\n" for task in selected).encode()
    manifest_payload = (json.dumps({"images": complete}, sort_keys=True, separators=(",", ":")) + "\n").encode()
    receipt: dict[str, object] = {
        "schema_version": 1,
        "dataset_tree_sha256": dataset_tree_sha256,
        "plan_sha256": _sha256(plan_path.read_bytes()),
        "status_snapshot_sha256": status_snapshot.hexdigest(),
        "planned_tasks": len(order),
        "plan_rows": plan_rows,
        "strict_image_receipts": strict_images,
        "selected_noncompose_tasks": len(selected),
        "incomplete_noncompose_tasks": incomplete,
        "compose_tasks_excluded": compose,
        "minimum_selected": minimum_selected,
        "incomplete_image_classes": dict(sorted(failure_classes.items())),
        "task_file_sha256": _sha256(task_payload),
        "image_manifest_sha256": _sha256(manifest_payload),
    }
    _atomic_write(task_file, task_payload)
    _atomic_write(manifest_path, manifest_payload)
    _atomic_write(receipt_path, (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--status-root", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--task-file", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--excluded-name-pattern", required=True)
    parser.add_argument("--dataset-tree-sha256", required=True)
    parser.add_argument("--expected-tasks", type=int, required=True)
    parser.add_argument("--expected-plan-rows", type=int, required=True)
    parser.add_argument("--expected-strict-images", type=int, required=True)
    parser.add_argument("--expected-selected", type=int, required=True)
    parser.add_argument("--expected-incomplete", type=int, required=True)
    parser.add_argument("--expected-compose", type=int, required=True)
    parser.add_argument("--minimum-selected", type=int, required=True)
    args = parser.parse_args()
    receipt = materialize(
        plan_path=args.plan,
        status_root=args.status_root,
        dataset_dir=args.dataset_dir,
        task_file=args.task_file,
        manifest_path=args.manifest,
        receipt_path=args.receipt,
        excluded_name_pattern=args.excluded_name_pattern,
        dataset_tree_sha256=args.dataset_tree_sha256,
        expected_tasks=args.expected_tasks,
        expected_plan_rows=args.expected_plan_rows,
        expected_strict_images=args.expected_strict_images,
        expected_selected=args.expected_selected,
        expected_incomplete=args.expected_incomplete,
        expected_compose=args.expected_compose,
        minimum_selected=args.minimum_selected,
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
