#!/usr/bin/env python3
"""Apply all bug fixes to the deterministic simulation testing pipeline.

Bug 1 (detsim/buggify.py): Non-deterministic fault injection — mixes
       time.time() into probability calculation via _entropy_pool.
Bug 2 (detsim/network.py): Non-deterministic message latency — uses
       stdlib random.uniform() instead of self._rng.uniform().
Bug 3 (detsim/network.py): Asymmetric network partitions — only stores
       one direction in the partition set.
Bug 4 (checker/safety.py): False-negative durability check — skips
       None results instead of reporting missing committed keys.
Bug 5 (replication/protocol.py): Off-by-one in log truncation during
       sync — uses diverge-1 instead of diverge.
"""

import os

# ── Bug 1: buggify.py ──────────────────────────────────────────────────────

BUG_PATH = "/app/detsim/buggify.py"
with open(BUG_PATH) as f:
    code = f.read()

# Remove the time import
code = code.replace("import time as _time\n", "\n")

# Remove entropy pool initialization in __init__
code = code.replace(
    "        # Mix in wall-clock entropy for \"better\" fault distribution\n"
    "        self._entropy_pool = _time.time()  # seeded from wall clock\n",
    ""
)

# Remove entropy pool refresh in enable()
code = code.replace(
    "        self._entropy_pool = _time.time()  # refresh entropy\n",
    ""
)

# Fix should_fault to use only the deterministic RNG
code = code.replace(
    "        raw = self._rng.random()\n"
    "        mixed = (raw * 0.7 + (self._entropy_pool % 1.0) * 0.3)\n"
    "        return mixed < p\n",
    "        return self._rng.random() < p\n"
)

with open(BUG_PATH, "w") as f:
    f.write(code)
print(f"[fix] patched {BUG_PATH}")

# ── Bug 2 & 3: network.py ─────────────────────────────────────────────────

NET_PATH = "/app/detsim/network.py"
with open(NET_PATH) as f:
    code = f.read()

# Bug 2: deterministic latency
code = code.replace(
    "delay = random.uniform(*self._latency)",
    "delay = self._rng.uniform(*self._latency)",
)

# Bug 3: bidirectional partitions
code = code.replace(
    "        self._partitions.add((a, b))\n",
    "        self._partitions.add((a, b))\n"
    "        self._partitions.add((b, a))\n",
)

# Bug 3: bidirectional heal
code = code.replace(
    "        self._partitions.discard((a, b))\n",
    "        self._partitions.discard((a, b))\n"
    "        self._partitions.discard((b, a))\n",
)

with open(NET_PATH, "w") as f:
    f.write(code)
print(f"[fix] patched {NET_PATH}")

# ── Bug 4: checker/safety.py ──────────────────────────────────────────────

CHK_PATH = "/app/checker/safety.py"
with open(CHK_PATH) as f:
    code = f.read()

# Remove the false-negative guard on None results
code = code.replace(
    "                if actual is None:\n"
    "                    # Node hasn't applied this entry yet; not a safety\n"
    "                    # violation since the entry may still be in the log\n"
    "                    # but unapplied due to commit-index lag.\n"
    "                    continue\n"
    "                if actual != value:\n",
    "                if actual != value:\n"
)

with open(CHK_PATH, "w") as f:
    f.write(code)
print(f"[fix] patched {CHK_PATH}")

# ── Bug 5: protocol.py ────────────────────────────────────────────────────

PROTO_PATH = "/app/replication/protocol.py"
with open(PROTO_PATH) as f:
    code = f.read()

# Fix off-by-one: diverge - 1 → diverge
code = code.replace(
    "self.log = self.log[:max(0, diverge - 1)]",
    "self.log = self.log[:diverge]",
)

with open(PROTO_PATH, "w") as f:
    f.write(code)
print(f"[fix] patched {PROTO_PATH}")

print("[fix] all 5 bugs fixed.")
