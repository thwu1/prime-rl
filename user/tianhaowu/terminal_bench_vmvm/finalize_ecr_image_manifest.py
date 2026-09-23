#!/usr/bin/env python3
"""Convert successful ECR build receipts into a digest-pinned task manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--status-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    images: dict[str, dict[str, str]] = {}
    rows = 0
    for raw in args.plan.read_text().splitlines():
        if not raw.strip():
            continue
        fields = raw.split("\t")
        if len(fields) != 5:
            raise SystemExit("build plan contains an invalid row")
        task, role, context_sha256, _context, image = fields
        if role not in {"agent", "verifier"} or re.fullmatch(r"[0-9a-f]{64}", context_sha256) is None:
            raise SystemExit("build plan contains an invalid role or digest")
        status_path = args.status_root / f"{context_sha256}.{role}.json"
        status = json.loads(status_path.read_text())
        digest = status.get("digest")
        if (
            status.get("state") != "success"
            or status.get("cleanup_verified") is not True
            or status.get("task") != task
            or status.get("role") != role
            or status.get("context_sha256") != context_sha256
            or status.get("image") != image
            or not isinstance(digest, str)
            or SHA256.fullmatch(digest) is None
        ):
            raise SystemExit("ECR build receipt does not match its plan row")
        repository = image.rsplit(":", 1)[0]
        images.setdefault(task, {})[role] = f"{repository}@{digest}"
        rows += 1

    if not images or any("agent" not in roles for roles in images.values()):
        raise SystemExit("build plan produced an incomplete image manifest")
    payload = (json.dumps({"images": images}, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _atomic_write(args.output, payload)
    print(
        json.dumps(
            {
                "tasks": len(images),
                "images": rows,
                "manifest_sha256": hashlib.sha256(payload).hexdigest(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
