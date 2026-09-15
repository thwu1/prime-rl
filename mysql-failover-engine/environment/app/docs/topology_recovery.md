# Topology Recovery

`orchestrator` supports automated recovery following failure detection. Recovery is opt-in and subject to several conditions.

## Automated Recovery

The analysis mechanism runs at all times and checks periodically for failure/recovery scenarios. It will initiate an automated recovery for:

- An **actionable** type of failure scenario
- For an instance belonging to a cluster where **global recoveries are enabled**
- For an instance in a cluster where **auto-recovery is enabled**
- For an instance that is **not downtimed** (administrators can "downtime" an instance via `orchestrator-client -c begin-downtime` to suppress automated failover)
- For an instance in a cluster that has **not recently been recovered**, unless the blocking period has expired

Recovery is blocked at the first failing condition encountered.

### Anti-Flapping

`orchestrator` avoids flapping (cascading failures causing continuous outage) by introducing a block period. On any given cluster, `orchestrator` will not kick in automated recovery on an interval smaller than said period, unless cleared to do so by a human.

The block period is indicated by `RecoveryPeriodBlockSeconds`. If `last_recovery_timestamp` is set and `(current_timestamp - last_recovery_timestamp) < RecoveryPeriodBlockSeconds`, automated recovery is blocked. It only applies to recoveries on the *same cluster*. There is nothing to prevent concurrent recoveries running on *different clusters*.

Pending recoveries are unblocked either once `RecoveryPeriodBlockSeconds` has passed or the recovery has been *acknowledged* by an operator.

Manual recovery (e.g., `orchestrator-client -c recover`) ignores the blocking period.

## Downtime

All failure/recovery scenarios are analyzed. However, the downtime status of an instance is also considered. An instance can be downtimed and this is noted in the analysis summary. When considering automated recovery, downtimed servers are skipped.

## Promotion Rules

When selecting a replica for promotion after a master failure, `orchestrator` considers several criteria to find the best candidate. Servers are annotated with promotion rules:

- **prefer**: This server is a preferred promotion candidate
- **neutral**: No special preference
- **prefer_not**: Avoid promoting this server if alternatives exist
- **must_not**: Never promote this server under any circumstances

Promotion rules are registered via `orchestrator-client -c register-candidate -i hostname --promotion-rule prefer`. They expire after an hour, so typically a cron job re-announces the promotion rule periodically.

### Candidate Selection

Replicas with `must_not` promotion rule are excluded entirely from candidacy. Unreachable replicas are also excluded — you cannot promote a server you cannot communicate with.

Among eligible candidates, `orchestrator` evaluates multiple factors:

- **Promotion rule priority**: Servers with `prefer` are strongly favored over `neutral`, which is favored over `prefer_not`.
- **Semi-synchronous replication**: Replicas with semi-sync enabled (`semi_sync_replica_enabled`) are preferred as they have confirmed receipt of the most recent transactions.
- **GTID position**: Among otherwise equal candidates, the replica with the highest GTID position (most transactions replayed) is preferred, as it has the least data loss.
- **Datacenter locality**: Promoting within the same datacenter as the failed server is preferred to minimize cross-DC latency and reduce failover time.
- **Hostname**: As a final deterministic tiebreaker, alphabetical hostname ordering is used.

These criteria are evaluated in priority order — a higher-priority criterion always takes precedence over lower-priority ones.

### Recovering a Dead Master

Recovering from a dead master is complex:
- There is outage implied and recovery is expected to be as fast as possible.
- Some servers may be lost in the process. `orchestrator` must determine which, if any.
- A naive approach would be to pick the most up-to-date replica, but that may not always be the right choice. The most up-to-date replica may not have the necessary configuration to act as master.
- `orchestrator` attempts to promote a replica that will retain the most serving capacity.
- Master service discovery must take place: the app must be able to communicate with the new master.

### Recovering a Dead Intermediate Master

A "simple" recovery case. Orphaned replicas can be re-connected to the topology using GTID. Options include finding a sibling, promoting one of the orphaned replicas, or relocating all orphaned replicas.

## Recovery Pipeline

The full recovery pipeline integrates failure detection, consensus, and promotion:

1. Analyze the topology for failures
2. If no failures are detected, no recovery is needed
3. Verify consensus (raft quorum) if orchestrator nodes are configured — recovery cannot proceed without quorum to prevent split-brain
4. Among detected failures, master-level failures take priority over intermediate master failures, as restoring write capability is more urgent than fixing replication chains
5. Check recovery conditions for the target failure
6. Select and promote the best candidate
7. Estimate expected outage duration

If orchestrator nodes are configured but no raft quorum can be established, recovery is blocked. If no orchestrator nodes are configured at all, the raft check is skipped.
