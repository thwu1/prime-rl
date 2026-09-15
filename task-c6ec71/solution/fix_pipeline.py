"""
Diagnose and fix bugs in the bracket analysis pipeline.

Bug 1 (ops.py): The compose function's overflow branch drops the left
operand's accumulated pops. When right.n_pops >= len(left.pushes), the
excess should be left.n_pops + right.n_pops - len(left.pushes), but the
code computes only right.n_pops - len(left.pushes), losing left.n_pops.
This breaks associativity and causes wrong results on inputs with
leading unmatched close brackets.

Bug 2 (accumulate.py): The distribution (top-down) phase composes
operands in the wrong order. The operation is non-commutative, so operand
order matters. The code has compose(saved, work[ri]) but the prefix
(work[ri]) must be the LEFT operand: compose(work[ri], saved).

Bug 3 (extract.py): Close bracket depth is computed as
max(0, len(pushes) - 1) but should be len(pushes). After inclusive
accumulation, pushes for a close bracket contains the remaining stack
AFTER the pop, so depth = len(pushes) directly.
"""

import os


def patch_file(path, old, new):
    """Read a file, replace exactly one occurrence of old with new, write back."""
    with open(path, 'r') as f:
        content = f.read()
    if old not in content:
        raise ValueError(f"Pattern not found in {path}: {old!r}")
    patched = content.replace(old, new, 1)
    if patched == content:
        raise ValueError(f"Replacement had no effect in {path}")
    with open(path, 'w') as f:
        f.write(patched)
    print(f"  Patched {os.path.basename(path)}")


print("Applying fixes...")

# Fix 1: compose overflow branch must preserve left.n_pops
patch_file(
    '/app/ops.py',
    'excess = right.n_pops - len(left.pushes)',
    'excess = left.n_pops + right.n_pops - len(left.pushes)',
)

# Fix 2: distribution phase must have prefix as left operand
patch_file(
    '/app/accumulate.py',
    'work[ri] = compose(saved, work[ri])',
    'work[ri] = compose(work[ri], saved)',
)

# Fix 3: close bracket depth = len(pushes), not len(pushes) - 1
patch_file(
    '/app/extract.py',
    'depths[i] = max(0, len(accumulated[i].pushes) - 1)',
    'depths[i] = len(accumulated[i].pushes)',
)

print("\nAll patches applied. Running validation...")
os.chdir('/app')
exit_code = os.system('python3 /app/check.py')
if exit_code != 0:
    print("Validation failed!")
    raise SystemExit(1)
print("Validation passed.")
