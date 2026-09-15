#!/usr/bin/env python3
"""
UCA Conformance Test Runner.

Reads official UCA conformance test files and verifies that each line's
sort key is >= the previous line's sort key, as required by UTS #10
Section 12.2.

Usage:
    python3 run_conformance.py [--mode MODE] [--limit N] [--verbose]
"""

import sys
import argparse
import unicodedata


def parse_test_line(raw_line):
    """Parse a conformance test line into a list of code points.

    Returns None for comment / blank lines.
    """
    line = raw_line.strip()
    if not line or line.startswith('#'):
        return None
    hex_part = line.split(';')[0].strip() if ';' in line else line.strip()
    if not hex_part:
        return None
    return [int(tok, 16) for tok in hex_part.split()]


def codepoints_to_string(cps):
    """Convert code point list to a Python string, skipping surrogates."""
    chars = []
    for cp in cps:
        if 0xD800 <= cp <= 0xDFFF:
            continue  # skip surrogates
        try:
            chars.append(chr(cp))
        except (ValueError, OverflowError):
            continue
    return ''.join(chars)


def run_conformance(collator, test_file, limit=None, verbose=False):
    """Run the conformance test.

    Returns (violations, total_data_lines).
    """
    violations = 0
    prev_string = None
    prev_key = None
    data_line = 0

    with open(test_file, 'r', encoding='utf-8') as f:
        for file_line_num, raw_line in enumerate(f, 1):
            cps = parse_test_line(raw_line)
            if cps is None:
                continue

            data_line += 1
            if limit and data_line > limit:
                break

            s = codepoints_to_string(cps)
            if not s:
                continue

            try:
                key = collator.sort_key(s)
            except Exception as exc:
                if verbose:
                    print(f"  ERROR line {file_line_num}: {exc}")
                violations += 1
                continue

            if prev_key is not None:
                order_ok = True
                if key < prev_key:
                    order_ok = False
                elif key == prev_key:
                    n1 = unicodedata.normalize("NFD", prev_string)
                    n2 = unicodedata.normalize("NFD", s)
                    if n1 > n2:
                        order_ok = False

                if not order_ok:
                    violations += 1
                    if verbose and violations <= 30:
                        prev_hex = ' '.join(f'{ord(c):04X}' for c in prev_string)
                        curr_hex = ' '.join(f'{ord(c):04X}' for c in s)
                        print(f"  Violation #{violations} at data line {data_line} "
                              f"(file line {file_line_num}):")
                        print(f"    prev: {prev_hex}")
                        print(f"    curr: {curr_hex}")

            prev_string = s
            prev_key = key

    return violations, data_line


def main():
    parser = argparse.ArgumentParser(description='UCA Conformance Test Runner')
    parser.add_argument('--allkeys', default='/app/data/allkeys.txt',
                        help='Path to allkeys.txt (DUCET)')
    parser.add_argument('--mode',
                        choices=['NON_IGNORABLE', 'SHIFTED', 'both'],
                        default='both',
                        help='Variable weighting mode to test')
    parser.add_argument('--limit', type=int, default=None,
                        help='Max number of data lines to process per file')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Print details of violations')
    args = parser.parse_args()

    # Lazy import so the module can be used as a library too
    sys.path.insert(0, '/app')
    from collator import UCACollator

    test_files = {
        'NON_IGNORABLE': '/app/data/CollationTest_NON_IGNORABLE_SHORT.txt',
        'SHIFTED': '/app/data/CollationTest_SHIFTED_SHORT.txt',
    }

    modes = ['NON_IGNORABLE', 'SHIFTED'] if args.mode == 'both' else [args.mode]
    all_pass = True

    for mode in modes:
        print(f"\n{'=' * 50}")
        print(f"Testing {mode} mode")
        print(f"{'=' * 50}")
        collator = UCACollator(args.allkeys, mode=mode)
        violations, total = run_conformance(
            collator, test_files[mode],
            limit=args.limit, verbose=args.verbose,
        )
        status = "PASS" if violations == 0 else "FAIL"
        print(f"Result: {status} — {violations} violations in {total} lines")
        if violations > 0:
            all_pass = False

    print()
    if all_pass:
        print("All conformance tests PASSED.")
    else:
        print("Conformance tests FAILED.")
    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())
