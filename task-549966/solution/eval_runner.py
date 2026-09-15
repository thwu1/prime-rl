#!/usr/bin/env python3
"""
Conformance evaluation report generator.

Runs the validator against every invalid/linux-only bag in the conformance
suite, captures the error messages, and classifies each into violation
categories based on the error content.

"""

import json
import os
import subprocess
import sys
import re

SUITE_DIR = "/app/conformance-suite"
VALIDATOR = "/app/bagit-validate"
OUTPUT = "/app/conformance-eval.json"


def classify_errors(stderr_text):
    """
    Classify validation errors into violation categories based on error
    message content.
    """
    categories = set()
    lower = stderr_text.lower()

    # Checksum-related
    if "checksum mismatch" in lower or "different checksums" in lower:
        categories.add("checksum")

    # Completeness-related
    if "not listed in any manifest" in lower or "not found" in lower:
        categories.add("completeness")

    # Encoding-related
    if "bom" in lower or "byte order mark" in lower:
        categories.add("encoding")

    # Structure-related
    if ("missing required file" in lower or "must have exactly 2 lines" in lower
            or "invalid bagit-version" in lower
            or "invalid tag-file-character-encoding" in lower):
        categories.add("structure")

    # Path-security-related
    if ("path traversal" in lower or "absolute path" in lower
            or "home directory" in lower or "unc path" in lower
            or "shortcut" in lower or "environment variable" in lower
            or "out-of-scope" in lower or "outside data/" in lower):
        categories.add("path-security")

    # Version-constraint-related
    if ("v1.0" in lower and ("whitespace before colon" in lower
                             or "listed more than once" in lower
                             or "requires" in lower)):
        categories.add("version-constraint")

    # fetch-related (note: path-security in fetch.txt -> path-security,
    # but purely fetch structural issues -> fetch)
    if "fetch.txt" in lower:
        if categories & {"path-security"}:
            pass  # already covered
        else:
            categories.add("fetch")

    # Fallback: if tag manifest references missing file, classify as checksum
    if "tag file listed in" in lower and "not found" in lower:
        categories.discard("completeness")
        categories.add("checksum")

    if not categories:
        categories.add("structure")

    return sorted(categories)


def main():
    report = {}

    for version_dir in sorted(os.listdir(SUITE_DIR)):
        version_path = os.path.join(SUITE_DIR, version_dir)
        if not os.path.isdir(version_path) or not version_dir.startswith("v"):
            continue

        for category in sorted(os.listdir(version_path)):
            if category not in ("invalid", "linux-only"):
                continue

            category_path = os.path.join(version_path, category)
            if not os.path.isdir(category_path):
                continue

            for bag_name in sorted(os.listdir(category_path)):
                bag_path = os.path.join(category_path, bag_name)
                if not os.path.isdir(bag_path):
                    continue

                result = subprocess.run(
                    [VALIDATOR, bag_path],
                    capture_output=True,
                    timeout=30,
                )

                key = f"{version_dir}/{category}/{bag_name}"
                stderr_text = result.stderr.decode("utf-8", errors="replace")
                cats = classify_errors(stderr_text)
                report[key] = cats

    with open(OUTPUT, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)

    print(f"Wrote evaluation report to {OUTPUT} ({len(report)} bags)")


if __name__ == "__main__":
    main()
