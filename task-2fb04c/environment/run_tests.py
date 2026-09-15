#!/usr/bin/env python3
"""
Test runner for 8088 CPU emulator validation.
Loads test vectors from test_vectors.json and runs them against cpu8088.py.

"""

import json
import sys
from cpu8088 import CPU8088


REG_NAMES = ['ax', 'cx', 'dx', 'bx', 'sp', 'bp', 'si', 'di']


def run_test(tv):
    cpu = CPU8088()

    # Load initial state
    init = tv['initial']
    for name in REG_NAMES:
        if name in init:
            cpu.set_reg(name, init[name])
    cpu.flags = init.get('flags', 2)
    cpu.ip = init.get('ip', 0x1000)

    # Load instruction bytes into memory
    for i, b in enumerate(tv['bytes']):
        cpu.memory[cpu.ip + i] = b

    # Save initial IP for the instruction
    start_ip = cpu.ip

    # Execute one instruction
    try:
        cpu.execute_one()
    except Exception as e:
        return False, f"Exception: {e}"

    # Check expected values
    expected = tv['expected']
    mask = tv.get('flags_mask', 0x08D5)
    errors = []

    for name in REG_NAMES:
        if name in expected:
            actual = cpu.get_reg(name)
            exp = expected[name]
            if actual != exp:
                errors.append(
                    f"  {name}: expected 0x{exp:04X} ({exp}), "
                    f"got 0x{actual:04X} ({actual})"
                )

    exp_flags = expected.get('flags', 2)
    if (cpu.flags & mask) != (exp_flags & mask):
        actual_masked = cpu.flags & mask
        exp_masked = exp_flags & mask
        errors.append(
            f"  flags: expected 0x{exp_masked:04X} (masked), "
            f"got 0x{actual_masked:04X} (masked) "
            f"[raw: 0x{cpu.flags:04X}, mask: 0x{mask:04X}]"
        )

    if errors:
        return False, "\n".join(errors)
    return True, "OK"


def main():
    with open('test_vectors.json') as f:
        vectors = json.load(f)

    passed = 0
    failed = 0

    for tv in vectors:
        ok, msg = run_test(tv)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {tv['name']}")
        if not ok:
            print(msg)
            failed += 1
        else:
            passed += 1

    print(f"\n{passed}/{passed + failed} tests passed")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
