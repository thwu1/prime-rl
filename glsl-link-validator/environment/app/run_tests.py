#!/usr/bin/env python3
"""Test runner for GLSL ES 3.00 link-time conformance validator."""
import json
import os
import subprocess
import sys

VALIDATOR = "/app/glsl_link_validator.py"
MANIFEST = "/app/test_harness/manifest.json"
SHADER_DIR = "/app/test_harness/shaders"


def main():
    with open(MANIFEST) as f:
        manifest = json.load(f)

    passed = 0
    failed = 0
    total = len(manifest["test_cases"])

    for tc in manifest["test_cases"]:
        case_id = tc["id"]
        vert_path = os.path.join(SHADER_DIR, tc["vertex_shader"])
        frag_path = os.path.join(SHADER_DIR, tc["fragment_shader"])
        expected_valid = tc["expected"]["valid"]
        expected_errors = tc["expected"].get("errors", [])

        try:
            result = subprocess.run(
                ["python3", VALIDATOR, vert_path, frag_path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                print(f"FAIL {case_id}: validator crashed -- {result.stderr.strip()}")
                failed += 1
                continue

            output = json.loads(result.stdout)
        except Exception as e:
            print(f"FAIL {case_id}: exception -- {e}")
            failed += 1
            continue

        if output["valid"] != expected_valid:
            print(f"FAIL {case_id}: expected valid={expected_valid}, got valid={output['valid']}")
            if output["errors"]:
                errs = [(e["category"], e["variable"]) for e in output["errors"]]
                print(f"       validator errors: {errs}")
            failed += 1
            continue

        actual_errors = {(e["category"], e["variable"]) for e in output["errors"]}
        expected_set = {(e["category"], e["variable"]) for e in expected_errors}

        if actual_errors != expected_set:
            print(f"FAIL {case_id}: error mismatch")
            print(f"       expected: {sorted(expected_set)}")
            print(f"       actual:   {sorted(actual_errors)}")
            failed += 1
            continue

        print(f"PASS {case_id}")
        passed += 1

    print(f"\nResults: {passed}/{total} passed, {failed}/{total} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
