#!/usr/bin/env python3
"""Create a deterministic image build plan for a Harbor task directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tomllib
from pathlib import Path


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(str(stat.S_IMODE(mode)).encode())
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Output JSONL plan")
    parser.add_argument("--image-prefix", required=True)
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--verifier-image-suffix", default="-verifier")
    parser.add_argument("--tasks", nargs="*")
    parser.add_argument("--task-file", type=Path)
    parser.add_argument(
        "--single-repository",
        action="store_true",
        help="encode role and context digest in the tag instead of creating one repository per task",
    )
    args = parser.parse_args()
    if not args.image_tag or args.image_tag == "latest":
        parser.error("--image-tag must be immutable and cannot be 'latest'")

    selected = set(args.tasks or [])
    if args.task_file is not None:
        selected.update(
            line.strip().split("\t", 1)[0]
            for line in args.task_file.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    dataset = args.dataset_dir.resolve()
    task_dirs = [
        path
        for path in sorted(dataset.iterdir())
        if path.is_dir()
        and (path / "task.toml").is_file()
        and (path / "instruction.md").is_file()
        and (not selected or path.name in selected)
    ]
    if not task_dirs:
        raise SystemExit(f"no Harbor tasks found under {dataset}")

    rows: list[dict] = []
    for task_dir in task_dirs:
        config = tomllib.loads((task_dir / "task.toml").read_text())
        environment = task_dir / "environment"
        if not (environment / "Dockerfile").is_file():
            raise SystemExit(f"{task_dir.name}: missing environment/Dockerfile")
        agent_digest = _tree_digest(environment)
        agent_image = f"{args.image_prefix.rstrip('/')}/{task_dir.name}:{args.image_tag}"
        if args.single_repository:
            agent_image = f"{args.image_prefix.rstrip('/')}:{args.image_tag}-agent-{agent_digest[:24]}"
        rows.append(
            {
                "task": task_dir.name,
                "role": "agent",
                "context": str(environment),
                "context_sha256": agent_digest,
                "image": agent_image,
            }
        )

        verifier = config.get("verifier", {})
        mode = verifier.get("environment_mode")
        if mode is None:
            mode = "separate" if verifier.get("environment") is not None else "shared"
        tests = task_dir / "tests"
        if mode == "separate" and (tests / "Dockerfile").is_file():
            verifier_digest = _tree_digest(tests)
            verifier_image = (
                f"{args.image_prefix.rstrip('/')}/{task_dir.name}{args.verifier_image_suffix}:{args.image_tag}"
            )
            if args.single_repository:
                verifier_image = (
                    f"{args.image_prefix.rstrip('/')}:{args.image_tag}-verifier-{verifier_digest[:24]}"
                )
            rows.append(
                {
                    "task": task_dir.name,
                    "role": "verifier",
                    "context": str(tests),
                    "context_sha256": verifier_digest,
                    "image": verifier_image,
                }
            )

    jsonl = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    _atomic_text(args.output, jsonl)
    tsv = args.output.with_suffix(".tsv")
    _atomic_text(
        tsv,
        "".join(
            f"{row['task']}\t{row['role']}\t{row['context_sha256']}\t{row['context']}\t{row['image']}\n" for row in rows
        ),
    )
    print(
        json.dumps(
            {
                "tasks": len(task_dirs),
                "images": len(rows),
                "agent_images": sum(row["role"] == "agent" for row in rows),
                "verifier_images": sum(row["role"] == "verifier" for row in rows),
                "jsonl": str(args.output),
                "tsv": str(tsv),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
