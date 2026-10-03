#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path

SHA256 = re.compile(r"[0-9a-f]{64}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a launch-time implementation archive against its manifest.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--require-exact-members", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def digest_stream(stream) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    expected: dict[str, str] = {}
    issues: list[dict[str, str]] = []
    for line_number, line in enumerate(args.manifest.read_text().splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or SHA256.fullmatch(parts[0]) is None:
            issues.append({"manifest_line": str(line_number), "issue": "invalid manifest entry"})
            continue
        digest, path = parts
        if path in expected:
            issues.append({"path": path, "issue": "duplicate manifest path"})
            continue
        expected[path] = digest

    checked = 0
    with tarfile.open(args.archive, "r:*") as archive:
        members = {}
        for member in archive.getmembers():
            if not member.isfile():
                continue
            if member.name in members:
                issues.append({"path": member.name, "issue": "duplicate regular file in archive"})
                continue
            members[member.name] = member
        for path, expected_digest in expected.items():
            member = members.get(path)
            if member is None or not member.isfile():
                issues.append({"path": path, "issue": "missing regular file in archive"})
                continue
            stream = archive.extractfile(member)
            if stream is None:
                issues.append({"path": path, "issue": "archive member is unreadable"})
                continue
            with stream:
                actual_digest = digest_stream(stream)
            if actual_digest != expected_digest:
                issues.append(
                    {
                        "path": path,
                        "issue": "SHA-256 mismatch",
                        "expected": expected_digest,
                        "actual": actual_digest,
                    }
                )
                continue
            checked += 1
        if args.require_exact_members:
            for path in sorted(set(members) - set(expected)):
                issues.append({"path": path, "issue": "unexpected regular file in archive"})

    report = {
        "manifest": str(args.manifest.resolve()),
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "archive": str(args.archive.resolve()),
        "archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        "archive_regular_files": len(members),
        "manifest_files": len(expected),
        "checked_files": checked,
        "issues": issues,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.strict and issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
