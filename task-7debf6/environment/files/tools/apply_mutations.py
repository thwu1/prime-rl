#!/usr/bin/env python3
"""Generate mutant source files from the mutation manifest."""

import json
import os

MANIFEST_PATH = "/app/mutants/manifest.json"
TARGET_PATH = "/app/target/mathlib.py"
OUTPUT_DIR = "/app/mutants"


def apply_mutation(original_lines, line_num, find_text, replace_text):
    """Apply a single mutation to a copy of the source lines."""
    lines = list(original_lines)
    idx = line_num - 1
    if idx < 0 or idx >= len(lines):
        raise ValueError(f"Line {line_num} out of range (file has {len(lines)} lines)")
    if find_text not in lines[idx]:
        raise ValueError(
            f"Text '{find_text}' not found on line {line_num}: {lines[idx].rstrip()}"
        )
    lines[idx] = lines[idx].replace(find_text, replace_text, 1)
    return lines


def main():
    with open(TARGET_PATH) as f:
        original_lines = f.readlines()

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for mutant in manifest["mutants"]:
        mid = mutant["id"]
        mutated = apply_mutation(
            original_lines,
            mutant["line"],
            mutant["original"],
            mutant["replacement"],
        )
        output_path = os.path.join(OUTPUT_DIR, f"{mid}.py")
        with open(output_path, "w") as f:
            f.writelines(mutated)
        print(f"Generated {output_path}")

    print(f"Total: {len(manifest['mutants'])} mutant files generated")


if __name__ == "__main__":
    main()
