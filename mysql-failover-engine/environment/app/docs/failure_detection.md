# Failure Detection

`orchestrator` uses a holistic approach to detect master and intermediate master failures. Rather than simply checking if a server is reachable, it cross-references the state of the server with the state of all its replicas to reach a failure conclusion.

In a naive approach, a monitoring tool would probe the master and alert when it cannot contact it. Such an approach is susceptible to false positives caused by network glitches. `orchestrator` harnesses the replication topology itself — it observes not only the server but also its replicas. For example, to diagnose a dead master scenario, `orchestrator` must both fail to contact the master AND confirm via its replicas that they, too, cannot see the master.

## Failure Taxonomy

### Master Failure Types

| Failure Type | Description |
|---|---|
| DeadMaster | Master unreachable, all replicas confirm replication failure |
| DeadMasterAndSomeReplicas | Master unreachable, some replicas also unreachable, remaining replicas failing |
| DeadMasterAndReplicas | Master and all replicas unreachable |
| DeadMasterWithoutReplicas | Master unreachable, no replicas exist |
| UnreachableMaster | Master unreachable but replicas still replicating normally |
| UnreachableMasterWithLaggingReplicas | Master unreachable, all non-delayed replicas are lagging |
| LockedSemiSyncMaster | Master reachable but locked due to insufficient semi-sync acknowledgements |
| MasterWithTooManySemiSyncReplicas | More connected semi-sync replicas than required by wait_count |
| AllMasterReplicasNotReplicating | Master reachable, all replicas have stopped or failed replication |
| AllMasterReplicasNotReplicatingOrDead | Master reachable, replicas are either unreachable or not replicating |

### Intermediate Master Failure Types

| Failure Type | Description |
|---|---|
| DeadIntermediateMaster | IM unreachable, multiple replicas all failing |
| DeadIntermediateMasterWithSingleReplica | IM unreachable, single replica failing |
| DeadIntermediateMasterWithSingleReplicaFailingToConnect | IM unreachable, single replica also unreachable |
| DeadIntermediateMasterAndSomeReplicas | IM unreachable, some replicas also unreachable, rest failing |
| DeadIntermediateMasterAndReplicas | IM and all replicas unreachable |
| AllIntermediateMasterReplicasFailingToConnectOrDead | IM reachable, all replicas unreachable |
| AllIntermediateMasterReplicasNotReplicating | IM reachable, all replicas stopped or failed |
| UnreachableIntermediateMaster | IM unreachable but replicas still replicating normally |
| UnreachableIntermediateMasterWithLaggingReplicas | IM unreachable, all non-delayed replicas lagging |

## Top-Level Masters and Intermediate Masters

A **top-level master** is identified as a server with no master of its own (`master_hostname` is NULL) and `read_only` disabled — it accepts writes. An **intermediate master** is a server that has both a master and its own replicas (it replicates from above and is replicated from below).

`orchestrator` analyzes top-level masters and intermediate masters separately, and can detect failures on both in the same topology scan.

## Detection: When a Master Cannot Be Reached

When `orchestrator` cannot reach a master, it examines the master's replicas to determine the nature and severity of the failure:

If the master has **no replicas at all**, it is classified as `DeadMasterWithoutReplicas`. There is nothing `orchestrator` can do without replicas to promote.

If **all replicas are also unreachable**, the entire cluster is down (`DeadMasterAndReplicas`). `orchestrator` cannot take action since there are no reachable servers to promote.

If some replicas are reachable, `orchestrator` examines their replication state. If any non-SQL-delayed reachable replica reports replication is still **running normally**, this may be a transient network issue — the master might still be operational but temporarily unreachable from `orchestrator`'s vantage point. This is classified as `UnreachableMaster` and is not immediately actionable. `orchestrator` will re-probe to see if the situation changes.

If all non-SQL-delayed reachable replicas report they are **lagging** (receiving heartbeats but falling behind), this suggests the master may be overloaded or locked. Clients would see "Too many connections" while replicas, connected since long ago, may still claim the master is fine. However, since apps cannot connect to the master, no actual data gets written, and using a heartbeat mechanism such as `pt-heartbeat`, we can observe growing lag on replicas. This is `UnreachableMasterWithLaggingReplicas` and is actionable.

If **some replicas are unreachable** and the remaining reachable replicas all report replication **failure or stopped**, the situation is `DeadMasterAndSomeReplicas` — actionable.

If **all replicas are reachable** but all report replication **failure or stopped**, this is a clear `DeadMaster` scenario — the primary is confirmed dead by consensus of its replicas.

## Detection: When a Master Is Reachable

Even when the master itself is operational, there can be problems in the replication topology.

### Semi-Synchronous Replication Issues

If the master has semi-sync enabled (`rpl_semi_sync_master_enabled`), `orchestrator` checks whether enough semi-sync replicas are connected. A **"connected" semi-sync replica** is one that is reachable, has `semi_sync_replica_enabled` set, and has replication in a running state.

If connected semi-sync replicas fall below `rpl_semi_sync_master_wait_for_slave_count` and the master's `rpl_semi_sync_master_timeout` is set high enough that the master will lock writes rather than falling back to asynchronous replication, this is a `LockedSemiSyncMaster`. A timeout value of tens of seconds (well above the default of a few hundred milliseconds) indicates the master is configured to wait indefinitely for acks rather than falling back gracefully. In practice, timeouts of 30 seconds or more reliably produce this locking behavior.

If `EnforceExactSemiSyncReplicas` is configured and there are **more** connected semi-sync replicas than `wait_count`, this is `MasterWithTooManySemiSyncReplicas`. This is an informational finding, not immediately actionable.

### Replica Health Issues (Master Reachable)

If the master is healthy but replicas have problems:

- **All replicas unreachable**: `AllMasterReplicasNotReplicatingOrDead`
- **Some replicas unreachable, all reachable replicas have failed/stopped replication**: `AllMasterReplicasNotReplicatingOrDead`
- **No replicas unreachable, all reachable replicas have failed/stopped replication**: `AllMasterReplicasNotReplicating`

## Detection: Intermediate Masters

Intermediate masters are analyzed using the same principles as top-level masters, but with their own failure type taxonomy. When an intermediate master is **unreachable**, `orchestrator` examines its replicas similarly to how it examines a top-level master's replicas, classifying into the corresponding intermediate master failure types.

Key differences in intermediate master analysis:
- When an IM is unreachable with all replicas also unreachable, the single-replica case (`DeadIntermediateMasterWithSingleReplicaFailingToConnect`) is distinguished from the multi-replica case (`DeadIntermediateMasterAndReplicas`)
- When an IM is unreachable with all reachable replicas failing, the single-replica case (`DeadIntermediateMasterWithSingleReplica`) is distinguished from the multi-replica case (`DeadIntermediateMaster`)
- When an IM is reachable, the analysis follows the same pattern: all replicas unreachable → `AllIntermediateMasterReplicasFailingToConnectOrDead`; all reachable replicas failed/stopped → `AllIntermediateMasterReplicasNotReplicating`

## SQL-Delayed Replicas

Replicas configured with `SQL_Delay` (SQL-delayed replicas, identified by `is_sql_delayed`) are intentionally behind. `orchestrator` **excludes** these replicas when determining whether replicas are "replicating normally" or "all lagging." A SQL-delayed replica reporting `RUNNING` replication does not count as evidence that the master is healthy. However, SQL-delayed replicas still count toward **reachability analysis** — they can be reachable or unreachable, and this affects the failure type classification.

## Actionability

Not all detected failures are actionable. A failure is actionable when there exists a meaningful automated recovery action:

- **Actionable**: `DeadMaster`, `DeadMasterAndSomeReplicas`, `UnreachableMasterWithLaggingReplicas`, `LockedSemiSyncMaster`, `AllMasterReplicasNotReplicating`, `AllMasterReplicasNotReplicatingOrDead`, and the corresponding actionable intermediate master types (`DeadIntermediateMaster`, `DeadIntermediateMasterWithSingleReplica`, `DeadIntermediateMasterAndSomeReplicas`, `UnreachableIntermediateMasterWithLaggingReplicas`, `AllIntermediateMasterReplicasFailingToConnectOrDead`, `AllIntermediateMasterReplicasNotReplicating`)

- **Not actionable**: `DeadMasterAndReplicas`, `DeadMasterWithoutReplicas`, `UnreachableMaster`, `MasterWithTooManySemiSyncReplicas`, and their intermediate master equivalents (`DeadIntermediateMasterAndReplicas`, `DeadIntermediateMasterWithSingleReplicaFailingToConnect`, `UnreachableIntermediateMaster`)

## Failures of No Interest

The following scenarios are not recognized as failures by `orchestrator`:
- Failure of simple replicas (leaves on the replication topology graph), unless they are semi-sync replicas causing `LockedSemiSyncMaster`
- Replication lag, even severe, on individual replicas
- A master with no replicas that is reachable (healthy standalone server)
