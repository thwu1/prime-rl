# Deterministic Consensus Simulation Framework — Specification

## 1. PRNG (`dsim/prng.py`)

### Class: `DeterministicPRNG`

**Algorithm**: SplitMix64

State: 64-bit unsigned integer, initialized from seed.

Constants (hexadecimal):
- GOLDEN = 0x9e3779b97f4a7c15
- MIX1 = 0xbf58476d1ce4e5b9
- MIX2 = 0x94d049bb133111eb

All arithmetic is modulo 2^64.

#### `__init__(self, seed: int)`
Set `state = seed & ((1 << 64) - 1)`.

#### `next_u64(self) -> int`
```
state = (state + GOLDEN) mod 2^64
z = state
z = ((z XOR (z >> 30)) * MIX1) mod 2^64
z = ((z XOR (z >> 27)) * MIX2) mod 2^64
z = z XOR (z >> 31)
return z
```

#### `boolean(self) -> bool`
`(next_u64() & 1) == 1`

#### `chance(self, numerator: int, denominator: int) -> bool`
- If `denominator == 0` or `numerator <= 0`: return `False` (no PRNG consumption)
- If `numerator >= denominator`: return `True` (no PRNG consumption)
- Otherwise: `(next_u64() % denominator) < numerator`

#### `range_inclusive(self, low: int, high: int) -> int`
- If `low == high`: return `low` (no PRNG consumption)
- Otherwise: `low + (next_u64() % (high - low + 1))`

#### `shuffle(self, lst: list) -> list`
Fisher-Yates shuffle (reverse). Return a **new** list; do not mutate input.
```
result = copy of lst
for i from (len-1) down to 1:
    j = next_u64() % (i + 1)
    swap result[i] and result[j]
return result
```

#### `exponential(self, mean: float) -> float`
- If `mean <= 0`: return `0.0` (no PRNG consumption)
- `u = (next_u64() + 1.0) / 2^64`
- Return `-mean * ln(u)`

---

## 2. Quorum Calculator (`dsim/quorums.py`)

### Function: `compute_quorums(replica_count: int, quorum_replication_max: int = 3) -> dict`

Let R = replica_count, Q_max = quorum_replication_max.

**replication**:
- If R == 2: `2` (special case for small-cluster durability)
- Otherwise: `min(Q_max, ceil(R / 2))`

**view_change**:
- If R == 2: `2` (avoids single-replica view-change edge cases)
- Otherwise: `R - replication + 1`

**nack_prepare**: `R - replication + 1`

**majority**: `floor(R / 2) + 1`

**upgrade**: `R`

Returns `dict` with keys: `replication`, `view_change`, `nack_prepare`, `majority`, `upgrade`.

**Invariants** (must hold for all valid R):
- `replication + view_change > R` (Flexible Paxos intersection)
- `nack_prepare + replication > R`
- `majority > R // 2`
- `view_change >= R // 2 + 1`

---

## 3. Packet Simulator (`dsim/packet_simulator.py`)

### Dataclass: `PacketSimulatorOptions`

| Field | Type | Default |
|---|---|---|
| node_count | int | (required) |
| client_count | int | 0 |
| one_way_delay_mean | float | 50.0 |
| one_way_delay_min | float | 1.0 |
| packet_loss_probability | tuple(int,int) | (0, 100) |
| packet_replay_probability | tuple(int,int) | (0, 100) |
| partition_mode | str | "none" |
| partition_symmetry | str | "symmetric" |
| partition_probability | tuple(int,int) | (0, 100) |
| unpartition_probability | tuple(int,int) | (0, 100) |
| partition_stability | int | 0 |
| unpartition_stability | int | 0 |
| path_maximum_capacity | int | 20 |
| path_clog_duration_mean | float | 0.0 |
| path_clog_probability | tuple(int,int) | (0, 100) |

Probability tuples are (numerator, denominator) for `PRNG.chance()`.

### Class: `PacketSimulator`

#### `__init__(self, options: PacketSimulatorOptions, seed: int)`
- `process_count = node_count + client_count`
- Create one priority queue per directed path (source × target). Index: `source * process_count + target`.
- Initialize `DeterministicPRNG` with `seed`.
- `ticks = 0`, partition inactive, `partition_stability_remaining = unpartition_stability`.
- Use a monotonic counter for priority-queue tie-breaking.

#### `submit_packet(self, packet, source: int, target: int)`
1. If path queue length ≥ `path_maximum_capacity`: remove one random item (`PRNG.range_inclusive` over queue indices), then re-heapify.
2. Compute delay: `max(one_way_delay_min, PRNG.exponential(one_way_delay_mean))`.
3. Push `(ticks + delay, counter, packet, source, target)` onto path's priority queue.
4. Increment counter.

#### `tick(self)`
1. Increment `ticks`.
2. Partition state machine:
   - If `partition_stability_remaining > 0`: decrement it.
   - Else if currently partitioned: check `PRNG.chance(*unpartition_probability)` → if true, unpartition (reset all filters to True, set `partition_stability_remaining = unpartition_stability`).
   - Else if `node_count > 1`: check `PRNG.chance(*partition_probability)` → if true, create partition (see Partition Modes below).
3. For each path: check `PRNG.chance(*path_clog_probability)` → if true, clog until `ticks + PRNG.exponential(path_clog_duration_mean)`.

#### `step(self) -> list[tuple]`
For each path `(source, target)` in order `(0,0), (0,1), ..., (N-1,N-1)`:
1. Skip if path is clogged (clogged_till > ticks).
2. If queue front has `ready_at <= ticks`: pop it.
3. If link filter is False (partitioned): skip (discard packet).
4. If `PRNG.chance(*packet_loss_probability)`: skip (drop).
5. If `PRNG.chance(*packet_replay_probability)`: call `submit_packet` with same packet/path (re-queue with new delay).
6. Append `(packet, source, target)` to delivered list.

Process **at most one packet per path per step call**.
Return list of delivered `(packet, source, target)`.

#### Partition Modes

After selecting a partition assignment `partition[i] ∈ {True, False}` for each node:

- **none**: All False. No partition applied.
- **uniform_size**: Draw `size = PRNG.range_inclusive(1, N-1)`. Shuffle node indices. First `size` nodes → True.
- **uniform_partition**: Each node gets `PRNG.boolean()`. If all values are the same, set one random node (`PRNG.range_inclusive`) to True.
- **isolate_single**: All False, then set one random node (`PRNG.range_inclusive`) to True.

After assignment, set `partition_active = True`, `partition_stability_remaining = partition_stability`.

**Filter update**: Draw `asymmetric_side = PRNG.boolean()`. For each `(source, target)`:
- If either endpoint ≥ `node_count` (client): filter = True.
- If `partition[source] == partition[target]`: filter = True.
- If `partition_symmetry == "asymmetric"` and `partition[source] == asymmetric_side`: filter = True.
- Otherwise: filter = False.

#### Additional methods
- `get_partition(self) -> list[bool]`: Current partition assignment.
- `is_partitioned(self) -> bool`: Whether partition is active.

---

## 4. State Checker (`dsim/state_checker.py`)

### Exception: `SafetyViolation`

### Class: `StateChecker`

#### `__init__(self, replica_count: int)`
- Store root commit: `op=0, checksum=0, parent_checksum=0`, committed by all replicas.
- Track `commit_min[r] = 0` for each replica r.

#### `on_commit(self, replica_index: int, op: int, checksum: int, parent_checksum: int)`
1. If `op <= commit_min[replica_index]`: already committed. If `op` is in commits and checksums differ → raise `SafetyViolation`. Otherwise return.
2. If `op != commit_min[replica_index] + 1`: raise `SafetyViolation` (skipped op).
3. Verify `parent_checksum` matches `commits[commit_min[replica_index]]['checksum']` → raise `SafetyViolation` if not.
4. If `op` already committed by another replica with a different checksum → raise `SafetyViolation` (divergence).
5. Record commit: store `checksum`, `parent_checksum`, add replica to the set of replicas that committed this op.
6. Update `commit_min[replica_index] = op`.

#### `check_convergence(self, replica_indices: set[int]) -> bool`
True iff all specified replicas have `commit_min` equal to the global maximum op.

#### `get_commit_count(self) -> int`
Number of ops in commit history (including root).

#### `get_replica_commit_min(self, replica_index: int) -> int`
Latest op committed by this replica.

---

## 5. Liveness (`dsim/liveness.py`)

### Function: `select_random_core(prng, replica_count, standby_count, view_change_quorum) -> set[int]`
1. `replica_core_count = prng.range_inclusive(view_change_quorum, replica_count)`.
2. Shuffle `[0, ..., replica_count-1]` and take first `replica_core_count` as core replicas.
3. If `standby_count > 0`: `standby_core_count = prng.range_inclusive(0, standby_count)`. Shuffle `[replica_count, ..., replica_count+standby_count-1]` and take first `standby_core_count`.
4. Return union of core replicas and standbys.

### Function: `detect_repair_deadlock(available_ops: dict, all_ops: set) -> list[int]`

Detects the **resonance bug** pattern: with round-robin repair targeting, a replica might consistently direct repair requests to replicas that lack the needed ops.

Parameters:
- `available_ops`: `{replica_index: set_of_ops_this_replica_has}`
- `all_ops`: set of all ops that every replica should have

Algorithm:
```
replica_indices = sorted keys of available_ops
N = len(replica_indices)
stuck = []

For each replica r in replica_indices:
    missing = sorted(all_ops - available_ops[r])
    if missing is empty: continue

    For each counter in [0, N):
        can_repair = True
        For i, op in enumerate(missing):
            target_pos = (counter + i) % N
            target = replica_indices[target_pos]
            if target == r:
                target_pos = (target_pos + 1) % N
                target = replica_indices[target_pos]
            if op not in available_ops[target]:
                can_repair = False
                break
        if not can_repair:
            stuck.append(r)
            break  # Found a deadlock counter for r

return stuck
```

A replica is "stuck" if there exists **any** round-robin counter value where it cannot repair all missing ops. This models the real scenario where a long-running replica's counter could stabilize at a bad value.
