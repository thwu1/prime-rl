#!/usr/bin/env python3
"""Fix bugs in cache replacement policy implementations."""

# Fix 1: SRRIP - on hit, RRPV should be 0 (promote), not max_rrpv (demote)
path = '/app/policies/srrip.py'
with open(path) as f:
    lines = f.readlines()
fixed = []
for line in lines:
    if 'self.rrpv[set_idx][way] = self.max_rrpv' in line and '- 1' not in line:
        fixed.append(line.replace('self.max_rrpv', '0'))
    else:
        fixed.append(line)
with open(path, 'w') as f:
    f.writelines(fixed)
print("Fixed SRRIP: hit promotion RRPV set to 0 instead of max_rrpv")

# Fix 2: OPT - find_victim should use max (farthest future reuse), not min
path = '/app/policies/opt.py'
with open(path) as f:
    src = f.read()
src = src.replace(
    'return min(range(self.num_ways),',
    'return max(range(self.num_ways),'
)
with open(path, 'w') as f:
    f.write(src)
print("Fixed OPT: find_victim uses max for Belady's optimal eviction")

# Fix 3: DRRIP - implement storage_bytes computation
path = '/app/policies/drrip.py'
with open(path) as f:
    lines = f.readlines()
fixed = []
for line in lines:
    if 'raise NotImplementedError' in line:
        indent = ' ' * 8
        fixed.append(f'{indent}rrpv_bits = self.num_sets * self.num_ways * self.rrpv_bits\n')
        fixed.append(f'{indent}psel_bits = self.psel_bits\n')
        fixed.append(f'{indent}return (rrpv_bits + psel_bits + 7) // 8\n')
    else:
        fixed.append(line)
with open(path, 'w') as f:
    f.writelines(fixed)
print("Fixed DRRIP: implemented storage_bytes (RRPV bits + PSEL counter)")
