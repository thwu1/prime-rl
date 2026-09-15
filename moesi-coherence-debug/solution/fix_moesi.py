#!/usr/bin/env python3
"""Fix coherence protocol bugs in moesi_sim.py.


Fixes two bugs:
1. _dir_putm E-state: Missing memory writeback for silently-upgraded line.
2. _dir_gets E->S: Old owner missing from sharers set.
"""

SIM_PATH = '/app/moesi_sim.py'

with open(SIM_PATH, 'r') as f:
    code = f.read()

# Fix 1: In _dir_putm, write dirty data to memory when directory is in
# Exclusive state. A cache line read (Exclusive) then written (silent
# E->M upgrade) has dirty data, but the directory still records Exclusive.
# On eviction, the data must be written to memory.
code = code.replace(
    '        elif d.state == DState.E and d.owner == core_id:\n'
    '            d.state = DState.U\n'
    '            d.owner = -1',
    '        elif d.state == DState.E and d.owner == core_id:\n'
    '            self._mem_wr(baddr, data)\n'
    '            d.state = DState.U\n'
    '            d.owner = -1',
    1
)

# Fix 2: In _dir_gets E->S transition, include old Exclusive owner in
# sharers set. Without this, the old owner retains a Shared copy that
# the directory does not track, causing missed invalidations on writes.
code = code.replace(
    '            d.sharers = {core_id}\n'
    '            return data, CState.S\n'
    '\n'
    '        if d.state == DState.S:',
    '            d.sharers = {old, core_id}\n'
    '            return data, CState.S\n'
    '\n'
    '        if d.state == DState.S:',
    1
)

with open(SIM_PATH, 'w') as f:
    f.write(code)

print("Applied 2 coherence protocol fixes to moesi_sim.py")
