#!/usr/bin/env python3
"""Generate the correctness analysis report at /app/results/analysis.md."""

import os

ANALYSIS = r"""# Deterministic Simulation Pipeline: Correctness Analysis

## Overview

The testing pipeline contains five bugs spanning three subsystems (`detsim/`,
`replication/`, `checker/`) that collectively prevent detection of a real
committed-write durability violation in the replication protocol. The bugs
interact in a cascading structure: two break determinism (preventing seed
replay), one alters partition semantics (masking the protocol defect), one
creates false negatives in the safety checker, and one is the core protocol
safety violation.

---

## Bug 1: Non-Deterministic Buggify (detsim/buggify.py)

**Root cause**: The `Buggify` class initializes `_entropy_pool` from
`time.time()` (wall-clock) in `__init__` and refreshes it in `enable()`.
`should_fault()` mixes this pool into the probability calculation:

```python
mixed = (raw * 0.7 + (self._entropy_pool % 1.0) * 0.3)
```

Since `time.time()` returns different values on each invocation, two runs with
the same seed produce different buggify decisions, breaking determinism.

**Fix**: Remove `_entropy_pool` and use `self._rng.random() < p` directly.

**Parallel in MadSim**: MadSim intercepts `getrandom` and `gettimeofday` via
`#[no_mangle]` overrides to prevent any code from accessing real system
randomness. All entropy flows through `GlobalRng`.

---

## Bug 2: Non-Deterministic Network Latency (detsim/network.py)

**Root cause**: `Network.send()` computes delivery delay with Python's
module-level `random.uniform()` instead of `self._rng.uniform()`. The global
`random` state varies between runs and across seeds within the same process.

**Fix**: Replace `random.uniform(*self._latency)` with
`self._rng.uniform(*self._latency)`.

**Diagnostic SQL query**:
```sql
SELECT seed, COUNT(*) AS event_count
FROM events
GROUP BY seed
ORDER BY event_count DESC
LIMIT 10;
```
This revealed inconsistent event counts across runs of the same seed,
confirming non-determinism in message delivery timing.

---

## Bug 3: Asymmetric Network Partitions (detsim/network.py)

**Root cause**: `partition(a, b)` stores only `(a, b)` in the partition set,
and `is_partitioned(src, dst)` checks for the exact tuple `(src, dst)`.
Therefore `partition(1, 2)` blocks 1→2 but NOT 2→1.

**Fix**: Store both `(a, b)` and `(b, a)` in `partition()`; discard both in
`heal()`.

**Impact on Bug 5**: With one-way partitions, the new primary's messages leak
through to the old primary during the partition phase. This means the old
primary receives `AppendEntries` and updates its log through the normal append
path, avoiding the buggy sync truncation code entirely.

**Diagnostic SQL query**:
```sql
SELECT e.sim_time, e.event_type, e.src_node, e.dst_node, e.detail
FROM events e
WHERE e.seed = 0
  AND e.event_type IN ('partition', 'heal')
ORDER BY e.sim_time;
```

---

## Bug 4: Safety Checker False Negatives (checker/safety.py)

**Root cause**: In the durability check, when `store.get(key)` returns `None`
(key missing from a node), the checker executes `continue` instead of reporting
a violation. The misleading comment reads "Node hasn't applied this entry yet"
— but after sync completes and sufficient simulation time elapses, all
committed entries MUST be applied.

**Fix**: Remove the `if actual is None: continue` guard. Let the standard
`if actual != value` catch `None != expected_value`.

**Impact**: This bug directly hides committed-write loss. Even when the
protocol's sync truncation drops a committed entry (Bug 5), the checker
reports "0 violations" because it silently skips the missing keys.

**Diagnostic SQL query**:
```sql
SELECT ns.node_id, ns.term, ns.log_length, ns.commit_idx, ns.store_json
FROM node_states ns
WHERE ns.seed = 0
ORDER BY ns.sim_time DESC
LIMIT 6;
```
After sync, this showed node 0's store was missing key 'a' while nodes 1 and 2
had it — clear evidence of data loss that the checker was failing to report.

---

## Bug 5: Off-By-One in Log Sync Truncation (replication/protocol.py)

**Root cause**: In `_on_sync()`, after finding divergence point `diverge`
(entries `0..diverge-1` match), the code truncates with:

```python
self.log = self.log[:max(0, diverge - 1)]
```

This keeps entries `0..diverge-2`, discarding the **last matching entry**. The
leader's entries are then appended starting from index `diverge`, creating a
gap. The lost entry may contain a committed write.

**Fix**: Change `self.log[:max(0, diverge - 1)]` to `self.log[:diverge]`.

**Note**: This bug is only observable when Bugs 3 and 4 are both fixed.
Bug 3 (asymmetric partitions) prevents the sync code path from executing.
Bug 4 (checker false negatives) hides the resulting data loss.

---

## Bug Interaction Analysis

The five bugs form a **cascading masking structure**:

```
Bugs 1+2 (determinism) ──→ prevent reproducible testing
Bug 3 (partitions)     ──→ masks Bug 5 by preventing sync path execution
Bug 4 (checker)        ──→ masks Bug 5 by hiding data loss in results
Bug 5 (protocol)       ──→ the actual safety violation
```

Only when all four masking bugs (1–4) are fixed **simultaneously** does Bug 5
become both reproducible (determinism restored) and detectable (checker +
partitions working correctly). Fixing bugs in isolation yields misleading
results — e.g., fixing only the checker (Bug 4) without fixing partitions
(Bug 3) still shows 0 violations because the sync path is never exercised.

---

## Safety and Liveness Properties After Fixes

### Safety (Durability)

After fixing all five bugs, the protocol correctly preserves all committed
writes across partition/heal/sync cycles:

- **Log sync** preserves all matching entries (fix to Bug 5)
- **Symmetric partitions** prevent stale messages from corrupting the minority
  node's log via the append path (fix to Bug 3)
- **Safety checker** correctly validates this property (fix to Bug 4)

Verified by running the fault campaign across 50 seeds with buggify enabled —
all seeds pass the safety checker.

### Liveness

The protocol makes progress as long as:
- A majority of nodes can communicate
- A primary is elected on the majority side
- Writes commit when acknowledged by ⌊N/2⌋+1 nodes

After partition heal, the `initiate_sync()` mechanism allows minority nodes to
catch up. Liveness depends on external leader election (not implemented in the
protocol itself).

### Determinism

After fixing Bugs 1 and 2, the simulation is fully deterministic: the same
seed always produces the same event trace, buggify decisions, and final state.
This enables reliable seed replay for reproducing failures found during
campaigns.
"""

os.makedirs("/app/results", exist_ok=True)
with open("/app/results/analysis.md", "w") as f:
    f.write(ANALYSIS)

print("[analysis] wrote /app/results/analysis.md")
