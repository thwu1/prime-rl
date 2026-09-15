#!/usr/bin/env python3
"""Diagnose and fix the two bugs in the cr_cbrtf implementation.

Bug A: Only 3 Newton-Raphson iterations instead of the required 4.
  With 3 iterations, the intermediate double-precision result has only
  ~32 bits of accuracy. For correct rounding of float (24-bit mantissa),
  we need ~53 bits because the worst-case hardness for cbrt in binary32
  exceeds 29 extra bits past the mantissa. Adding a 4th iteration brings
  the accuracy to ~53 bits (capped by double), ensuring correct rounding.

Bug B: The subnormal exponent adjustment uses e_adj = -23 instead of -24.
  When normalizing subnormal inputs, we multiply by 2^24 to shift them
  into the normal range. The adjustment must be -24 to compensate, but
  the code uses -23, making the computed exponent e one too large. This
  causes the range reduction to produce mp in the wrong sub-interval,
  yielding results off by a factor of 2^(1/3) for all subnormal inputs.
"""

import sys


def fix_cbrtf(path):
    with open(path, 'r') as f:
        lines = f.readlines()

    code = ''.join(lines)
    fixes_applied = 0

    # Fix Bug B: e_adj = -23 -> e_adj = -24
    if 'e_adj = -23;' in code:
        code = code.replace('e_adj = -23;', 'e_adj = -24;')
        fixes_applied += 1
        print("Fixed Bug B: corrected subnormal exponent adjustment "
              "(e_adj = -23 -> -24)")
    else:
        print("Bug B not found (e_adj already correct or code changed)")

    # Fix Bug A: Add 4th Newton-Raphson iteration
    # Count existing Newton iterations
    newton_pattern = '    y2 = y * y; y = (2.0 * y + mp / y2) / 3.0;'
    count = code.count(newton_pattern)
    if count == 3:
        # Find position after the last Newton iteration
        last_pos = code.rfind(newton_pattern)
        end_of_line = last_pos + len(newton_pattern)
        # Insert a 4th iteration
        code = (code[:end_of_line] + '\n' + newton_pattern +
                code[end_of_line:])
        fixes_applied += 1
        print("Fixed Bug A: added 4th Newton-Raphson iteration "
              "(3 -> 4 iterations)")
    elif count == 4:
        print("Bug A not found (already has 4 Newton iterations)")
    else:
        print(f"WARNING: found {count} Newton iterations, expected 3")

    with open(path, 'w') as f:
        f.write(code)

    return fixes_applied


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-cbrtf.c>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    n = fix_cbrtf(path)
    print(f"\nApplied {n} fix(es) to {path}")
    if n == 0:
        print("WARNING: no fixes were applied!", file=sys.stderr)
        sys.exit(1)
