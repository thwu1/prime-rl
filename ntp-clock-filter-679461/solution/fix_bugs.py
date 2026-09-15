#!/usr/bin/env python3
"""
Fix the 5 bugs in /app/ntp_filter.c:

1. Offset formula: ntp_diff(t4, t3) -> ntp_diff(t3, t4)
   Computes (T4-T3) instead of (T3-T4), yielding half-RTT not offset.

2. Delay formula: swap subtraction operands
   ntp_diff(t3,t2) - ntp_diff(t4,t1)  ->  ntp_diff(t4,t1) - ntp_diff(t3,t2)
   Produces negative delay (clamped to precision floor).

3. Peer dispersion: C XOR '^' -> left-shift for power-of-2
   2 ^ (i + 1) is XOR, not exponentiation; causes div-by-zero at i=1.

4. Jitter: add sqrt() and fix divisor from (n+1) to n
   Must be sqrt(sum/n), not sum/(n+1).

5. Shift register: forward iteration overwrites all positions with f[0].
   Must iterate backward: for(i=N-1; i>=1; i--).

"""

import sys

path = '/app/ntp_filter.c'
with open(path, 'r') as f:
    code = f.read()

# --- Fix 1: offset formula ---
old = 'offset = (ntp_diff(t2, t1) + ntp_diff(t4, t3)) / 2.0;'
new = 'offset = (ntp_diff(t2, t1) + ntp_diff(t3, t4)) / 2.0;'
assert old in code, f"Fix 1: pattern not found"
code = code.replace(old, new)

# --- Fix 2: delay formula ---
old = 'delay = ntp_diff(t3, t2) - ntp_diff(t4, t1);'
new = 'delay = ntp_diff(t4, t1) - ntp_diff(t3, t2);'
assert old in code, f"Fix 2: pattern not found"
code = code.replace(old, new)

# --- Fix 3: XOR -> power-of-2 ---
old = 'p->disp += sorted[i].disp / (2 ^ (i + 1));'
new = 'p->disp += sorted[i].disp / (double)(1 << (i + 1));'
assert old in code, f"Fix 3: pattern not found"
code = code.replace(old, new)

# --- Fix 4: jitter sqrt + divisor ---
old = '        p->jitter = p->jitter / (n + 1);'
new = '        p->jitter = sqrt(p->jitter / n);'
assert old in code, f"Fix 4: pattern not found"
code = code.replace(old, new)

# --- Fix 5: shift register direction ---
old = '    for (i = 1; i < NSTAGE; i++) {\n        p->f[i] = p->f[i - 1];'
new = '    for (i = NSTAGE - 1; i >= 1; i--) {\n        p->f[i] = p->f[i - 1];'
assert old in code, f"Fix 5: pattern not found"
code = code.replace(old, new)

with open(path, 'w') as f:
    f.write(code)

print("All 5 bugs fixed successfully.", file=sys.stderr)
