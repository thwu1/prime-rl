#!/usr/bin/env python3
"""Validate terminal emulator against recorded trace files.

Reads binary trace files from /app/traces/, feeds them through the emulator,
and compares output against expected states in /app/expected/.

Usage: python3 /app/validate.py [trace_name]
"""

import json
import os
import sys

sys.path.insert(0, '/app')
from terminal_emulator import TerminalEmulator

TRACES_DIR = '/app/traces'
EXPECTED_DIR = '/app/expected'


def row_text(snap, row_idx):
    return ''.join(c['char'] for c in snap['screen'][row_idx]).rstrip()


def run_trace(trace_path, expected_path):
    with open(expected_path) as f:
        spec = json.load(f)

    with open(trace_path, 'rb') as f:
        data = f.read()

    emu = TerminalEmulator(spec['rows'], spec['cols'])
    emu.feed(data)
    snap = emu.snapshot()

    failures = []
    for check in spec['checks']:
        if check['type'] == 'row_text':
            actual = row_text(snap, check['row'])
            expected = check['expected']
            if actual != expected:
                failures.append(
                    f"  Row {check['row']}: expected '{expected}', got '{actual}'"
                )
        elif check['type'] == 'cursor':
            cr, cc = snap['cursor']['row'], snap['cursor']['col']
            er, ec = check['row'], check['col']
            if cr != er or cc != ec:
                failures.append(
                    f"  Cursor: expected ({er},{ec}), got ({cr},{cc})"
                )
        elif check['type'] == 'cell_attr':
            cell = snap['screen'][check['row']][check['col']]
            for attr, val in check['attrs'].items():
                if cell.get(attr) != val:
                    failures.append(
                        f"  Cell ({check['row']},{check['col']}).{attr}: "
                        f"expected {val!r}, got {cell.get(attr)!r}"
                    )
    return failures, len(data)


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    traces = sorted(os.listdir(TRACES_DIR))
    total = 0
    passed = 0

    for trace_name in traces:
        if not trace_name.endswith('.bin'):
            continue
        base = trace_name[:-4]
        if target and target != base and target != trace_name:
            continue

        trace_path = os.path.join(TRACES_DIR, trace_name)
        expected_path = os.path.join(EXPECTED_DIR, f'{base}.json')

        if not os.path.exists(expected_path):
            print(f"SKIP {trace_name}: no expected file")
            continue

        total += 1
        failures, nbytes = run_trace(trace_path, expected_path)

        if failures:
            print(f"FAIL {trace_name} ({nbytes} bytes):")
            for f in failures:
                print(f)
        else:
            print(f"PASS {trace_name} ({nbytes} bytes)")
            passed += 1

    print(f"\n{passed}/{total} traces passed.")
    if passed < total:
        print("Inspect failing traces with: xxd /app/traces/<name>.bin")
        print("Check terminal references:   infocmp xterm-256color")
        sys.exit(1)


if __name__ == '__main__':
    main()
