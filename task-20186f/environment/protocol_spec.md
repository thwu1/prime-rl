# Kafka KIP-966 Replication Protocol Specification

## Overview

This specification describes the Kafka partition replication protocol with KIP-966
(Eligible Leader Replicas) extensions. The protocol manages replica sets for a single
partition, maintaining data durability while handling broker failures including unclean
shutdowns that may cause data loss on individual brokers.

## System Model

### Entities

- **Partition**: A log replicated across multiple brokers.
- **Replica**: An instance of a partition on a broker. Named R1, R2, ..., Rn.
- **Controller**: Manages partition metadata and leader elections.

### Per-Replica State

- **LEO (Log End Offset)**: The number of records in the replica's log. A replica with LEO=10 contains records at offsets 0-9.
- **Fenced**: Whether the broker hosting the replica is fenced (unreachable/offline).

### Partition-Level State

- **Leader**: The replica that accepts produce requests. May be `None` if no leader exists.
- **ISR (In-Sync Replicas)**: The set of replicas in sync with the leader. Serves as the replication quorum.
- **ELR (Eligible Leader Replicas)**: Replicas not in ISR but guaranteed to host all committed data. They are leader candidates when unfenced.
- **LastKnownELR**: Replicas that were in ELR but experienced an unclean shutdown. They *may* still have all committed data, but this is not guaranteed.
- **HWM (High Watermark)**: The offset up to which data is considered committed. All ISR members are guaranteed to have records up to HWM.

### Configuration

- `replication_factor`: Number of replicas (determines replica names R1..Rn).
- `min_isr`: Minimum ISR size required to advance HWM.
- `recovery_mode`: One of `"balanced"`, `"proactive"`, or `"manual"`.

### Initial State

- Leader = R1
- ISR = {R1, R2, ..., Rn}
- ELR = {} (empty)
- LastKnownELR = {} (empty)
- All replica LEOs = 0
- HWM = 0
- No replicas are fenced

## Key Invariants

1. **Leader Candidate Completeness**: Every member of ISR or ELR hosts all committed data (records below HWM at the time they last left the ISR or when HWM was last advanced).

2. **HWM Advancement Condition**: HWM may only advance when |ISR| >= min_isr.

3. **HWM Monotonicity**: Within a leader's term, HWM never decreases. On leader change, HWM may decrease to the new leader's LEO (representing committed data loss).

## Events and State Transitions

### produce(count)

**Precondition**: Leader exists.

The leader appends `count` records. Leader's LEO increases by `count`. No other replica is affected.

### replicate(replica, up_to=None)

**Precondition**: Leader exists. Replica is not the leader. Replica is not fenced.

The follower fetches records from the leader:
1. Compute target: if `up_to` is specified, target = min(up_to, leader.LEO); otherwise target = leader.LEO.
2. If replica.LEO > leader.LEO, truncate to leader.LEO (divergent log suffix).
3. Set replica.LEO = max(replica.LEO, target).

### advance_hwm

**Precondition**: Leader exists.

If |ISR| >= min_isr: HWM = max(current_HWM, min(LEO of all ISR members)).

If |ISR| < min_isr: HWM does not change.

### fence(replica)

The controller fences a broker.

1. Mark replica as fenced.
2. Record whether replica was the leader.
3. Remove replica from ISR.
4. If replica was leader, set leader = None.
5. **ELR Addition**: If |ISR| < min_isr AND |ISR| + |ELR| < min_isr, add replica to ELR.

The ELR addition captures the insight: when HWM is blocked (ISR too small), the fenced replica's data is still complete.

### unfence(replica, unclean=false, records_lost=0)

A broker comes back online.

1. Mark replica as not fenced.
2. If `unclean` and `records_lost > 0`: reduce replica's LEO by records_lost (minimum LEO of 0).
3. If `unclean` and replica is in ELR: remove from ELR, add to LastKnownELR.

An unclean shutdown means potential data loss on that broker. The replica loses its completeness guarantee.

### elect_leader

The controller attempts to elect a new leader. If there is already a leader, this is a no-op.

**Step 1 - Clean Election from ISR:**

Candidates = sorted unfenced ISR members. If candidates exist, elect the one with the highest LEO (ties broken by lexicographically smallest replica name). This is a clean election.

On clean election from ISR: preserve ISR membership. Set ISR = {r in ISR | r is not fenced}. If the resulting |ISR| >= min_isr, clear ELR and LastKnownELR.

**Step 2 - Clean Election from ELR:**

If no ISR candidates: candidates = sorted unfenced ELR members. If candidates exist, elect the one with the highest LEO (same tiebreaker). This is a clean election.

On clean election from ELR: set ISR = {elected}. Remove elected from ELR.

**Step 3 - Recovery:**

If no clean candidates, apply recovery based on `recovery_mode`:

- **proactive**: Triggers when ELR is non-empty but ALL ELR members are fenced. The controller picks any unfenced replica (from the full replica set) with the highest LEO. Election type: `unclean_proactive`. After election: ISR = {elected}. If elected was in ELR, remove it; if in LastKnownELR, remove it.

  If proactive conditions are not met (e.g., ELR is empty), fall through to balanced logic.

- **balanced**: Triggers when ISR is empty AND ELR is empty. Pick the unfenced LastKnownELR member with the highest LEO (same tiebreaker). Election type: `unclean_balanced`. ISR = {elected}. Remove elected from LastKnownELR.

- **manual**: No automatic recovery. Election fails.

**Step 4**: If no candidate found, record a failed election with type `"failed"`.

**On any successful election:**

1. Compute data_lost = max(0, old_HWM - elected.LEO).
2. Accumulate total committed_data_lost.
3. Set leader = elected.
4. Set HWM = min(old_HWM, elected.LEO).
5. Apply ISR update as described per election source above.
6. Truncate all non-leader replicas: for each r != elected, r.LEO = min(r.LEO, elected.LEO).
7. Record election in history: `{"type": <election_type>, "leader": <elected>, "data_lost": <data_lost>}`.

### add_to_isr(replica)

The leader recognizes a follower has caught up and adds it to ISR.

**Preconditions**: Leader exists. Replica is not fenced. Replica is not the leader. Replica.LEO >= HWM.

1. Add replica to ISR.
2. **ELR Cleanup**: If |ISR| >= min_isr, clear ELR and LastKnownELR entirely.

## Simulator Interface

The simulator must expose:

```python
class PartitionSimulator:
    def __init__(self, config: dict): ...
    def process_event(self, event: dict) -> None: ...
    def get_result(self) -> SimulationResult: ...
```

Where `SimulationResult` has these attributes:
- `leader`: str or None
- `isr`: list of str (sorted)
- `elr`: list of str (sorted)
- `last_known_elr`: list of str (sorted)
- `hwm`: int
- `leo`: dict mapping replica name to int
- `committed_data_lost`: int (total across all elections)
- `election_history`: list of dicts with keys `type`, `leader` (if successful), `data_lost` (if successful)

SimulationResult must also have a `to_dict()` method returning a JSON-serializable dict.
