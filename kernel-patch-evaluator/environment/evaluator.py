#!/usr/bin/env python3
"""
Kernel patch triage engine — skeleton.
Provides CLI interface and evaluation structure.
Core analytical components are not implemented.

"""

import json
import sys
from pathlib import Path


def parse_crash_report(report_text):
    """
    Parse a kernel crash report and extract structured information.
    Must handle KASAN (use-after-free, slab-out-of-bounds),
    NULL pointer dereference, and WARNING report formats.

    Returns dict with keys: type, access_type, file, function, line.
    """
    return {
        "type": None,
        "access_type": None,
        "file": None,
        "function": None,
        "line": None,
    }


def get_modified_files(diff_text):
    """
    Extract the sorted list of file paths modified by a unified diff.
    File paths must not contain git diff prefixes (a/, b/).

    Returns sorted list of clean file path strings.
    """
    return []


def extract_modified_functions(diff_text, source_dir):
    """
    Determine which C functions are modified by a unified diff.
    Function attribution must be source-aware: map changed line
    numbers to function definitions in the actual C source files
    under source_dir, not from diff hunk header context strings.

    Returns sorted list of "filepath:functionname" strings.
    """
    return []


def compute_iou(set_a, set_b):
    """Intersection over union of two collections treated as sets."""
    return 0.0


def check_patch_equivalent(agent_diff, dev_diff, source_dir):
    """
    Determine if two patches produce structurally equivalent code
    when applied to the source files in source_dir.
    Returns boolean.
    """
    return False


def evaluate_case(case_dir):
    """Evaluate a single case directory."""
    case = Path(case_dir)

    with open(case / "crash_report.txt") as f:
        crash_text = f.read()
    crash_info = parse_crash_report(crash_text)

    with open(case / "agent_patch.diff") as f:
        agent_text = f.read()
    with open(case / "developer_patch.diff") as f:
        dev_text = f.read()

    source_dir = str(case / "source")

    agent_files = get_modified_files(agent_text)
    dev_files = get_modified_files(dev_text)

    agent_funcs = extract_modified_functions(agent_text, source_dir)
    dev_funcs = extract_modified_functions(dev_text, source_dir)

    crash_key = None
    if crash_info["file"] and crash_info["function"]:
        crash_key = f"{crash_info['file']}:{crash_info['function']}"

    return {
        "crash_info": crash_info,
        "agent_patch": {
            "modified_files": agent_files,
            "modified_functions": agent_funcs,
        },
        "developer_patch": {
            "modified_files": dev_files,
            "modified_functions": dev_funcs,
        },
        "metrics": {
            "file_iou": compute_iou(agent_files, dev_files),
            "function_iou": compute_iou(agent_funcs, dev_funcs),
            "localization_hit": crash_key in agent_funcs if crash_key else False,
            "patch_equivalent": check_patch_equivalent(
                agent_text, dev_text, source_dir
            ),
        },
    }


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <cases_dir> <output_json>", file=sys.stderr)
        sys.exit(1)

    cases_dir = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    results = {}
    for d in sorted(cases_dir.iterdir()):
        if d.is_dir() and d.name.startswith("case_"):
            results[d.name] = evaluate_case(d)

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {output_path}")


if __name__ == "__main__":
    main()
