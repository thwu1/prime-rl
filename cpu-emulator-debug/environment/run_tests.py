#!/usr/bin/env python3
"""Test runner for the 6502 emulator using SingleStepTests-format JSON vectors.

Loads test vectors from /app/test_vectors/, runs each through the emulator,
and reports pass/fail with detailed mismatch information.
"""

import json
import os
import sys

from cpu6502 import CPU6502


def run_test(cpu, test):
    """Run a single test case and return list of error strings (empty = pass)."""
    cpu.load_state(test['initial'])
    cpu.step()
    state = cpu.get_state()
    expected = test['final']
    errors = []

    for key in ['pc', 's', 'a', 'x', 'y', 'p']:
        if state[key] != expected[key]:
            errors.append(
                f"  {key}: expected 0x{expected[key]:02X}, got 0x{state[key]:02X}"
            )

    for addr, val in expected.get('ram', []):
        actual = cpu.memory[addr]
        if actual != val:
            errors.append(
                f"  mem[0x{addr:04X}]: expected 0x{val:02X}, got 0x{actual:02X}"
            )

    return errors


def main():
    test_dir = os.environ.get('TEST_VECTORS_DIR', '/app/test_vectors')
    total = 0
    passed = 0
    failed = 0

    if not os.path.isdir(test_dir):
        print(f"Error: test vector directory not found: {test_dir}")
        return 1

    for filename in sorted(os.listdir(test_dir)):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(test_dir, filename)
        with open(filepath) as f:
            tests = json.load(f)

        file_pass = 0
        file_fail = 0
        for test in tests:
            cpu = CPU6502()
            errors = run_test(cpu, test)
            total += 1
            if errors:
                failed += 1
                file_fail += 1
                print(f"FAIL: {test['name']}")
                for err in errors:
                    print(err)
            else:
                passed += 1
                file_pass += 1

        status = "OK" if file_fail == 0 else "FAIL"
        print(f"[{status}] {filename}: {file_pass}/{file_pass + file_fail} passed")

    print(f"\nTotal: {passed}/{total} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
