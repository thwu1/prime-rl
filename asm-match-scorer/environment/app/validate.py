#!/usr/bin/env python3
"""Validate the matching pipeline against all test cases."""
import os
import sys
import json
import subprocess

TEST_DIR = '/app/test_cases'


def main():
    cases = sorted(d for d in os.listdir(TEST_DIR)
                   if os.path.isdir(os.path.join(TEST_DIR, d)))

    all_passed = True
    failures = []

    for case in cases:
        case_dir = os.path.join(TEST_DIR, case)
        expected_file = os.path.join(case_dir, 'expected.json')
        target_file = os.path.join(case_dir, 'target.s')
        candidate_file = os.path.join(case_dir, 'candidate.s')

        if not os.path.exists(expected_file):
            continue

        with open(expected_file) as f:
            expected = json.load(f)

        try:
            result = subprocess.run(
                ['python3', '/app/match.py', target_file, candidate_file],
                capture_output=True, text=True, timeout=30
            )

            if result.returncode != 0:
                print(f"  {case}: ERROR - {result.stderr.strip()}")
                all_passed = False
                failures.append(case)
                continue

            output = json.loads(result.stdout)
            actual_score = output['score']
            expected_score = expected['score']

            if actual_score == expected_score:
                print(f"  {case}: PASS (score={actual_score})")
            else:
                print(f"  {case}: FAIL (expected={expected_score}, got={actual_score})")
                all_passed = False
                failures.append(case)

        except Exception as e:
            print(f"  {case}: ERROR - {e}")
            all_passed = False
            failures.append(case)

    print()
    if all_passed:
        print("ALL TESTS PASSED")
    else:
        print(f"FAILURES: {', '.join(failures)}")

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
