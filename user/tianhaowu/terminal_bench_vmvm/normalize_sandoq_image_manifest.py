#!/usr/bin/env python3
"""Derive an OCI-runner-compatible manifest without changing its image digests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_NORMALIZER_SCHEMA = 1


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalize_reference(reference: str) -> str:
    """Drop only a tag preceding an immutable digest (repo:tag@sha -> repo@sha)."""
    name, separator, digest = reference.rpartition("@")
    if not separator or not _DIGEST_RE.fullmatch(digest):
        raise ValueError("Sandoq image references must contain an immutable sha256 digest")
    parent, slash, leaf = name.rpartition("/")
    repository, tag_separator, tag = leaf.rpartition(":")
    if tag_separator:
        if not repository or not tag:
            raise ValueError("invalid tagged image reference")
        leaf = repository
    normalized_name = f"{parent}{slash}{leaf}" if slash else leaf
    if not normalized_name:
        raise ValueError("image reference has no repository")
    return f"{normalized_name}@{digest}"


def derive_manifest(source_payload: bytes, expected_source_sha256: str) -> bytes:
    actual_source_sha256 = sha256_bytes(source_payload)
    if actual_source_sha256 != expected_source_sha256:
        raise ValueError("source manifest SHA-256 does not match the approved input")
    source = json.loads(source_payload)
    if not isinstance(source, dict) or not isinstance(source.get("images"), dict):
        raise ValueError("source manifest must contain an images object")

    result = dict(source)
    images: dict[str, object] = {}
    normalized_roles = 0
    for opaque_key, raw_entry in source["images"].items():
        if isinstance(raw_entry, str):
            images[str(opaque_key)] = normalize_reference(raw_entry)
            normalized_roles += 1
            continue
        if not isinstance(raw_entry, dict):
            raise ValueError("image entries must be strings or objects")
        entry = dict(raw_entry)
        for role in ("agent", "verifier"):
            if role not in entry:
                continue
            if not isinstance(entry[role], str):
                raise ValueError(f"{role} image reference must be a string")
            entry[role] = normalize_reference(entry[role])
            normalized_roles += 1
        if not any(role in entry for role in ("agent", "verifier")):
            raise ValueError("image entry has no supported agent or verifier role")
        images[str(opaque_key)] = entry

    result["images"] = images
    result["sandoq_normalization"] = {
        "schema_version": _NORMALIZER_SCHEMA,
        "source_sha256": actual_source_sha256,
        "normalized_roles": normalized_roles,
        "policy": "remove-tag-before-immutable-digest",
    }
    return (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = derive_manifest(args.source.read_bytes(), args.source_sha256)
    _write_atomic(args.output, payload)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "output_sha256": sha256_bytes(payload),
                "bytes": len(payload),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
