#!/usr/bin/env python3
"""Materialize hash-bound opaque prefixes for the Sandoq capacity ramp."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def materialize(source: Path, source_sha256: str, count: int) -> tuple[bytes, dict]:
    raw = source.read_bytes()
    if sha256(raw) != source_sha256:
        raise ValueError("source allowlist SHA-256 mismatch")
    lines = raw.decode().splitlines()
    if len(lines) != len(set(lines)) or not 1 <= count <= len(lines):
        raise ValueError("source allowlist or requested prefix is invalid")
    payload = ("\n".join(lines[:count]) + "\n").encode()
    return payload, {
        "schema_version": 1,
        "selection": "ordered-prefix",
        "source_sha256": source_sha256,
        "source_count": len(lines),
        "selected_count": count,
        "selected_sha256": sha256(payload),
    }


def materialize_config(
    template: Path,
    template_sha256: str,
    *,
    count: int,
    task_file: Path,
    task_file_sha256: str,
) -> bytes:
    raw = template.read_bytes()
    if sha256(raw) != template_sha256:
        raise ValueError("template config SHA-256 mismatch")
    text = raw.decode()
    replacements = {
        "num_tasks = 2500": f"num_tasks = {count}",
        "max_concurrent = 64": f"max_concurrent = {count}",
        "multiplex = 64": f"multiplex = {count}",
        "max_connections = 32": f"max_connections = {count}",
        "max_keepalive_connections = 32": f"max_keepalive_connections = {count}",
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise ValueError("template config does not match the approved ramp shape")
        text = text.replace(old, new)
    task_line = 'task_file = "user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt"'
    hash_line = 'task_file_sha256 = "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"'
    if text.count(task_line) != 1 or text.count(hash_line) != 1:
        raise ValueError("template task authority is not the approved source")
    text = text.replace(task_line, f'task_file = "{task_file}"')
    text = text.replace(hash_line, f'task_file_sha256 = "{task_file_sha256}"')
    return text.encode()


def write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--count", type=int, required=True, choices=(2, 8, 24))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--template-sha256")
    parser.add_argument("--config-output", type=Path)
    args = parser.parse_args()
    payload, receipt = materialize(args.source, args.source_sha256, args.count)
    write_atomic(args.output, payload)
    write_atomic(
        args.receipt,
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )
    config_options = (args.template, args.template_sha256, args.config_output)
    if any(config_options) and not all(config_options):
        raise ValueError("template, template SHA-256, and config output are one tuple")
    if args.template is not None:
        config_payload = materialize_config(
            args.template,
            args.template_sha256,
            count=args.count,
            task_file=args.output,
            task_file_sha256=receipt["selected_sha256"],
        )
        write_atomic(args.config_output, config_payload)
        receipt["template_sha256"] = args.template_sha256
        receipt["config_sha256"] = sha256(config_payload)
        write_atomic(
            args.receipt,
            (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )
    print(
        json.dumps(
            {
                "count": args.count,
                "sha256": receipt["selected_sha256"],
                "config_sha256": receipt.get("config_sha256"),
            }
        )
    )


if __name__ == "__main__":
    main()
