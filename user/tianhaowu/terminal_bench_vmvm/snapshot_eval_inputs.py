#!/usr/bin/env python3
"""Snapshot mutable eval inputs and record their digests before a run starts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tomllib
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(config_path: Path, output_dir: Path) -> dict[str, dict[str, str]]:
    config_path = config_path.resolve(strict=True)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite existing eval input snapshot: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    config = tomllib.loads(config_path.read_text())
    records: dict[str, dict[str, str]] = {}

    sources: list[tuple[str, Path, str]] = [
        ("config", config_path, "source_config.toml")
    ]
    taskset = config.get("taskset", {})
    for key, filename in (
        ("task_file", "task_file.txt"),
        ("image_manifest", "image_manifest.json"),
    ):
        value = taskset.get(key)
        if value:
            sources.append((key, Path(value).resolve(strict=True), filename))

    for name, source, filename in sources:
        destination = output_dir / filename
        shutil.copyfile(source, destination)
        records[name] = {
            "source": str(source),
            "snapshot": str(destination.resolve()),
            "sha256": _sha256(destination),
        }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    snapshot(args.config, args.output_dir)


if __name__ == "__main__":
    main()
