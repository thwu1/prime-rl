#!/usr/bin/env python3
"""Fix all bugs in the cache replacement evaluation framework and implement SHiP."""

import subprocess
import os

# ==========================================================================
# Part 1: Fix native C engine
# ==========================================================================

# Fix Makefile: correct target, add -fPIC, use -shared
makefile_path = '/app/native/Makefile'
with open(makefile_path, 'w') as f:
    f.write("CC = gcc\n")
    f.write("CFLAGS = -Wall -O2 -fPIC\n")
    f.write("\n")
    f.write("all: libcachesim.so\n")
    f.write("\n")
    f.write("libcachesim.so: cachesim.c cachesim.h\n")
    f.write("\t$(CC) $(CFLAGS) -shared -o $@ $<\n")
    f.write("\n")
    f.write("clean:\n")
    f.write("\trm -f libcachesim.so *.o\n")
print("Fixed Makefile: target=libcachesim.so, -fPIC, -shared")

# Fix cachesim.c: add missing last_access update on insertion
csrc_path = '/app/native/cachesim.c'
with open(csrc_path) as f:
    src = f.read()

old_insert = (
    '    cache->blocks[base + victim].tag = tag;\n'
    '    cache->blocks[base + victim].valid = 1;\n'
    '\n'
    '    return 0;'
)
new_insert = (
    '    cache->blocks[base + victim].tag = tag;\n'
    '    cache->blocks[base + victim].valid = 1;\n'
    '    cache->blocks[base + victim].last_access = cache->clock;\n'
    '\n'
    '    return 0;'
)
src = src.replace(old_insert, new_insert)
with open(csrc_path, 'w') as f:
    f.write(src)
print("Fixed cachesim.c: added last_access update on insertion")

# Fix binding.py: correct library filename and fix addr/pc argument swap
binding_path = '/app/native/binding.py'
with open(binding_path) as f:
    src = f.read()

src = src.replace('"cachesim.a"', '"libcachesim.so"')
src = src.replace('lib.csim_access(cache, pc)', 'lib.csim_access(cache, addr)')

with open(binding_path, 'w') as f:
    f.write(src)
print("Fixed binding.py: library name and addr parameter")

# Build native library
result = subprocess.run(['make', '-C', '/app/native'],
                        capture_output=True, text=True)
if result.returncode != 0:
    print(f"Build failed: {result.stderr}")
    raise RuntimeError("Native build failed")
print(f"Built native library: {result.stdout.strip()}")

# ==========================================================================
# Part 2: Fix Python policy bugs
# ==========================================================================

# Fix SRRIP: on hit, RRPV should be 0, not max_rrpv
path = '/app/policies/srrip.py'
with open(path) as f:
    lines = f.readlines()
fixed = []
for line in lines:
    if 'self.rrpv[set_idx][way] = self.max_rrpv' in line \
            and '- 1' not in line:
        fixed.append(line.replace('self.max_rrpv', '0'))
    else:
        fixed.append(line)
with open(path, 'w') as f:
    f.writelines(fixed)
print("Fixed SRRIP: hit promotion RRPV -> 0")

# Fix OPT: find_victim should use max (farthest reuse), not min
path = '/app/policies/opt.py'
with open(path) as f:
    src = f.read()
src = src.replace(
    'return min(range(self.num_ways),',
    'return max(range(self.num_ways),',
)
with open(path, 'w') as f:
    f.write(src)
print("Fixed OPT: victim selection min -> max")

# Fix DRRIP: implement storage_bytes
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
print("Fixed DRRIP: implemented storage_bytes")

# ==========================================================================
# Part 3: Implement SHiP policy
# ==========================================================================

ship_code = '''\
"""Signature-based Hit Prediction (SHiP) replacement policy."""

from policies.base import ReplacementPolicy


class SHiPPolicy(ReplacementPolicy):

    def __init__(self, num_sets, num_ways, rrpv_bits=3, shct_bits=14):
        self.num_sets = num_sets
        self.num_ways = num_ways
        self.rrpv_bits = rrpv_bits
        self.shct_bits = shct_bits
        self.max_rrpv = (1 << rrpv_bits) - 1
        self.shct_size = 1 << shct_bits
        self.shct_max = (1 << rrpv_bits) - 1  # 3-bit saturating counters

        # Per-way RRPV
        self.rrpv = [[self.max_rrpv] * num_ways for _ in range(num_sets)]
        # Per-way signature (which PC brought this block in)
        self.signatures = [[-1] * num_ways for _ in range(num_sets)]
        # Per-way validity for SHiP tracking
        self.way_valid = [[False] * num_ways for _ in range(num_sets)]
        # Signature Hit Counter Table
        self.shct = [0] * self.shct_size

    def _pc_signature(self, pc):
        return (pc >> 2) & (self.shct_size - 1)

    def on_access(self, set_idx, way, hit, pc=0):
        sig = self._pc_signature(pc)

        if hit:
            self.rrpv[set_idx][way] = 0
            # Increment SHCT for the block\'s signature (re-referenced)
            old_sig = self.signatures[set_idx][way]
            if old_sig >= 0 and self.shct[old_sig] < self.shct_max:
                self.shct[old_sig] += 1
        else:
            # Decrement SHCT for evicted block (not re-referenced)
            if self.way_valid[set_idx][way]:
                old_sig = self.signatures[set_idx][way]
                if old_sig >= 0 and self.shct[old_sig] > 0:
                    self.shct[old_sig] -= 1

            # Record new block\'s signature
            self.signatures[set_idx][way] = sig
            self.way_valid[set_idx][way] = True

            # Insertion RRPV based on SHCT prediction
            if self.shct[sig] == 0:
                self.rrpv[set_idx][way] = self.max_rrpv  # distant
            else:
                self.rrpv[set_idx][way] = self.max_rrpv - 1  # intermediate

    def find_victim(self, set_idx, cache_set):
        inv = cache_set.find_invalid()
        if inv >= 0:
            return inv
        while True:
            for w in range(self.num_ways):
                if self.rrpv[set_idx][w] >= self.max_rrpv:
                    return w
            for w in range(self.num_ways):
                self.rrpv[set_idx][w] += 1

    def storage_bytes(self):
        rrpv_total = self.num_sets * self.num_ways * self.rrpv_bits
        sig_total = self.num_sets * self.num_ways * self.shct_bits
        shct_total = self.shct_size * self.rrpv_bits
        return (rrpv_total + sig_total + shct_total + 7) // 8
'''

with open('/app/policies/ship.py', 'w') as f:
    f.write(ship_code)
print("Implemented SHiP policy")
