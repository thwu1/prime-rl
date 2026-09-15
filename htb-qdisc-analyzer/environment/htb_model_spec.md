# HTB Bandwidth Allocation Model Specification

This document defines the simplified HTB (Hierarchical Token Bucket) model used
for computing steady-state per-leaf-class bandwidth allocation under full load
(all leaf classes demand infinite bandwidth).

## Class Parameters

Each HTB class has the following parameters:

- **rate** (Mbps): Guaranteed minimum bandwidth.
- **ceil** (Mbps): Maximum bandwidth the class may use (always >= rate).
- **prio**: Priority level. Lower number = higher priority (0 is highest).
- **quantum**: Weight for Deficit Round Robin (DRR) proportional distribution.

## Allocation Algorithm

The algorithm is recursive, starting from the root class of each interface.

### Input
- A class C with effective available bandwidth B (for the root class, B = C.rate)

### Step 1: Determine effective bandwidth
```
effective_bw = min(B, C.ceil)
```

### Step 2: Leaf check
If C has no children (leaf class):
- C receives effective_bw
- Return

### Step 3: Distribute effective_bw among C's children

Group children by their **prio** value. Process priority levels in ascending
order (0 first, then 1, then 2, ...).

#### Phase 1 — Guaranteed Rate Allocation

```
remaining = effective_bw
for each priority level P in ascending order:
    group = children at priority P
    total_rate = sum of group[i].rate for all i

    if total_rate <= remaining:
        # All guarantees fit
        for each child in group:
            child.allocation = child.rate
        remaining -= total_rate
    else:
        # OVERSUBSCRIPTION: cannot satisfy all guarantees at this priority
        # Distribute remaining bandwidth proportional to quantum
        total_quantum = sum of group[i].quantum for all i
        for each child in group:
            child.allocation = remaining * child.quantum / total_quantum
        remaining = 0
        # All children at priority levels > P get allocation = 0
        STOP Phase 1 (do not process further priority levels)
```

#### Phase 2 — Excess Bandwidth Distribution

This phase runs ONLY if no oversubscription occurred in Phase 1 AND
remaining > 0 after Phase 1.

Process priority levels in ascending order. At each level, use water-filling:

```
for each priority level P in ascending order:
    if remaining <= 0: break
    group = children at priority P

    repeat until convergence:
        active = children in group where allocation < ceil
        if no active children: break
        total_quantum = sum of active[i].quantum
        given = 0
        for each child in active:
            fair_share = remaining * child.quantum / total_quantum
            room = child.ceil - child.allocation
            actual = min(fair_share, room)
            child.allocation += actual
            given += actual
        remaining -= given
        if given ≈ 0: break  (convergence threshold: 0.001)
```

### Step 4: Recurse

For each child with allocation A:
```
child_effective_bw = min(A, child.ceil)
recurse into child with child_effective_bw
```

## Edge Cases

- **Orphan classes** (parent does not exist in the hierarchy) receive 0 bandwidth
  and are excluded from the parent's children list.
- The root class receives bandwidth equal to its configured **rate**.
- Multiple rounds of water-filling may be needed when a child hits its ceil
  during excess distribution, freeing bandwidth for other children at the same
  priority level.
