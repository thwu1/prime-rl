#!/usr/bin/env python3
"""Programmatically fix all three bugs in the deterministic simulation framework.

Bug 1 (network.py): Non-deterministic message latency — uses Python's global
       random.uniform() instead of the simulation's seeded DetRng.
Bug 2 (network.py): Asymmetric network partitions — only stores one direction.
Bug 3 (protocol.py): Off-by-one in log truncation during SyncLog handling.

Each fix is applied via targeted string replacement, then an analysis file
is written to /app/results/analysis.txt.
"""

import os
import re

# -- Bug 1 & 2: network.py --------------------------------------------------

NET_PATH = "/app/detsim/network.py"

with open(NET_PATH) as f:
    net_code = f.read()

# Bug 1: replace `random.uniform(...)` with `self._rng.uniform(...)`
net_code = net_code.replace(
    "delay = random.uniform(*self._latency)",
    "delay = self._rng.uniform(*self._latency)",
)

# Bug 2: make partition() store both directions
net_code = net_code.replace(
    '        self._partitions.add((a, b))\n',
    '        self._partitions.add((a, b))\n'
    '        self._partitions.add((b, a))\n',
)

# Bug 2: make heal() remove both directions
net_code = net_code.replace(
    '        self._partitions.discard((a, b))\n',
    '        self._partitions.discard((a, b))\n'
    '        self._partitions.discard((b, a))\n',
)

with open(NET_PATH, "w") as f:
    f.write(net_code)

print(f"[fix_bugs] patched {NET_PATH}")

# -- Bug 3: protocol.py -----------------------------------------------------

PROTO_PATH = "/app/replication/protocol.py"

with open(PROTO_PATH) as f:
    proto_code = f.read()

# Fix the off-by-one: diverge - 1  ->  diverge
proto_code = proto_code.replace(
    "self.log = self.log[:max(0, diverge - 1)]",
    "self.log = self.log[:diverge]",
)

with open(PROTO_PATH, "w") as f:
    f.write(proto_code)

print(f"[fix_bugs] patched {PROTO_PATH}")

# -- Write analysis ----------------------------------------------------------

ANALYSIS = """\
Bug Analysis
============

Bug 1: Non-deterministic network latency (detsim/network.py)
------------------------------------------------------------
Root cause: The Network.send() method computes message delivery delay with
Python's module-level `random.uniform()` instead of the simulation's
deterministic RNG (`self._rng.uniform()`).  The global `random` module is
seeded by the OS at process start, so its output varies between runs.  When
the determinism test creates two simulations with the same seed in the same
process, the second simulation consumes different values from the global
random stream (because the first simulation already advanced it), producing
a different event trace.

Fix: Replace `random.uniform(*self._latency)` with
`self._rng.uniform(*self._latency)`.

Parallel in MadSim: MadSim intercepts libc functions (getrandom, getentropy,
gettimeofday) via `#[no_mangle]` overrides to prevent any code path from
touching real system randomness.  All randomness flows through the
GlobalRng seeded once per simulation run.


Bug 2: Asymmetric network partitions (detsim/network.py)
---------------------------------------------------------
Root cause: `partition(a, b)` stores only the tuple `(a, b)` in
`self._partitions`, and `is_partitioned(src, dst)` checks for the exact
tuple `(src, dst)`.  Therefore `partition(1, 2)` blocks traffic from 1->2
but NOT from 2->1, creating a one-way partition.  The docstring promises
bidirectional isolation.

Fix: Store both `(a, b)` and `(b, a)` in `partition()`, discard both in
`heal()`.

Parallel in MadSim: MadSim's `clog_link(src, dst)` is intentionally
unidirectional, but the `disconnect2(a, b)` helper calls `clog_link` in
both directions to simulate a symmetric partition.


Bug 3: Off-by-one in log truncation during sync (replication/protocol.py)
-------------------------------------------------------------------------
Root cause: In `_on_sync()`, after finding the divergence point `diverge`
(meaning entries 0 .. diverge-1 match), the code truncates with
`self.log[:max(0, diverge - 1)]`.  This keeps entries 0 .. diverge-2,
discarding the LAST matching entry.  Because leader entries are then
appended starting from index `diverge` (not from `len(self.log)`), the
lost entry is never re-added, causing permanent data loss of a committed
write.

Fix: Change `self.log[:max(0, diverge - 1)]` to `self.log[:diverge]`.

Note: This bug is only observable when Bug 2 is fixed.  With asymmetric
partitions the new primary's AppendEntries messages leak through during
the partition, resolving log conflicts via the normal append path instead
of the sync path.  Once partitions are truly bidirectional, the sync code
path is exercised and the off-by-one causes committed-write loss.
"""

os.makedirs("/app/results", exist_ok=True)
with open("/app/results/analysis.txt", "w") as f:
    f.write(ANALYSIS)

print("[fix_bugs] wrote /app/results/analysis.txt")
print("[fix_bugs] done — all three bugs fixed.")
