#!/usr/bin/env python3
"""Validation tool for robot obstacle navigation output format."""
import sys
import json
import os


def main():
    if len(sys.argv) != 2:
        print("Usage: validate-output <output_file>")
        sys.exit(1)

    output_path = sys.argv[1]
    manifest_path = "/data/manifest.json"

    if not os.path.exists(manifest_path):
        print("ERROR: Manifest not found at {}".format(manifest_path))
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    expected_total = manifest["validation"]["total_answers"]

    if not os.path.exists(output_path):
        print("FAIL: Output file '{}' does not exist".format(output_path))
        sys.exit(1)

    with open(output_path) as f:
        lines = [line.strip() for line in f if line.strip()]

    bad_lines = []
    for i, line in enumerate(lines, 1):
        try:
            int(line)
        except ValueError:
            bad_lines.append((i, line))

    if bad_lines:
        print("FAIL: {} lines are not valid integers:".format(len(bad_lines)))
        for ln, val in bad_lines[:10]:
            print("  Line {}: '{}'".format(ln, val))
        if len(bad_lines) > 10:
            print("  ... and {} more".format(len(bad_lines) - 10))
        sys.exit(1)

    if len(lines) != expected_total:
        print("FAIL: Expected {} answers, got {}".format(expected_total, len(lines)))
        print("  Breakdown by suite:")
        for suite in manifest["suites"]:
            print("    Suite {} ({}): {} answers".format(
                suite["id"], suite["description"], suite["expected_answers"]))
        sys.exit(1)

    negatives = [(i, int(l)) for i, l in enumerate(lines, 1) if int(l) < 0]
    if negatives:
        print("FAIL: {} answers are negative (heights must be >= 0)".format(
            len(negatives)))
        for i, v in negatives[:5]:
            print("  Line {}: {}".format(i, v))
        sys.exit(1)

    print("PASS: Output valid ({} answers, all non-negative integers)".format(
        len(lines)))
    print("  Suite breakdown:")
    offset = 0
    for suite in manifest["suites"]:
        count = suite["expected_answers"]
        suite_values = [int(lines[j]) for j in range(offset, offset + count)]
        print("    Suite {} ({}): {} answers, range [{}, {}]".format(
            suite["id"], suite["description"], count,
            min(suite_values), max(suite_values)))
        offset += count
    sys.exit(0)


if __name__ == "__main__":
    main()
