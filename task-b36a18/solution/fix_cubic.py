"""Fix the 4 bugs in /app/cubic.py.

Reads the buggy source, applies line-level fixes for each bug,
verifies every fix was applied, and writes the corrected file.

Bug 1: cubic_k omits cwnd subtraction from w_max in K computation.
Bug 2: Fast convergence uses beta/2 instead of (1+beta)/2.
Bug 3: w_est_inc missing max_datagram_size multiplier.
Bug 4: Missing alpha_aimd update to 1.0 when w_est reaches w_max.
"""

import sys

with open('/app/cubic.py', 'r') as f:
    lines = f.readlines()

fixes = {1: False, 2: False, 3: False, 4: False}
new_lines = []

for line in lines:
    s = line.rstrip('\n')

    # Fix 1: K = cbrt(w_max / C) -> K = cbrt((w_max - cwnd_pkts) / C)
    if 'math.pow(w_max / C,' in s:
        s = s.replace('math.pow(w_max / C,',
                       'math.pow((w_max - cwnd_pkts) / C,')
        fixes[1] = True

    # Fix 2: fast convergence: cwnd * beta/2 -> cwnd * (1+beta)/2
    if 'BETA_CUBIC / 2.0' in s:
        s = s.replace('BETA_CUBIC / 2.0', '(1.0 + BETA_CUBIC) / 2.0')
        fixes[2] = True

    # Fix 3: w_est_inc missing MDS multiplier (return line only)
    if 'alpha_aimd * (acked / cwnd)' in s and 'return' in s:
        s = s.replace('alpha_aimd * (acked / cwnd)',
                       'alpha_aimd * (acked / cwnd) * self.max_datagram_size')
        fixes[3] = True

    new_lines.append(s + '\n')

    # Fix 4: insert alpha_aimd check right after the w_est update
    if 'self.cubic.w_est += w_est_inc' in s and not fixes[4]:
        indent = len(s) - len(s.lstrip())
        pad = ' ' * indent
        new_lines.append('\n')
        new_lines.append(pad + 'if self.cubic.w_est >= self.cubic.w_max:\n')
        new_lines.append(pad + '    self.cubic.alpha_aimd = 1.0\n')
        fixes[4] = True

# Verify every fix was applied
for num, applied in fixes.items():
    if not applied:
        print(f"ERROR: Fix {num} was NOT applied", file=sys.stderr)
        sys.exit(1)

with open('/app/cubic.py', 'w') as f:
    f.writelines(new_lines)

print(f"All {sum(fixes.values())}/4 fixes applied successfully.")
