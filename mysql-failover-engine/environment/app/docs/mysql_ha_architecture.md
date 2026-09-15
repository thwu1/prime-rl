# MySQL HA Architecture at GitHub

GitHub uses MySQL as its main datastore for all things non-git, and its availability is critical to GitHub's operation. We run multiple MySQL clusters serving different services. Our clusters use classic primary-replica setup, where a single node in a cluster (the primary) accepts writes. The rest of the cluster nodes (the replicas) asynchronously replay changes from the primary and serve read traffic.

## Architecture Overview

The system consists of:

- **MySQL replication topology**: Primary-replica setup, optionally with semi-synchronous replication for data durability
- **orchestrator**: Failure detection and automated failover, running in a cross-DC raft configuration
- **Consul**: Key-value store for service discovery (cluster primary identity)
- **GLB/HAProxy**: Proxy layer routing application traffic to the current primary

### Normal Flow

Apps connect to write nodes through GLB/HAProxy. They use a DNS name (e.g., `mysql-writer-1.github.net`) that resolves to an anycast IP, routing to the local datacenter's GLB cluster. Each GLB/HAProxy instance has writer pools — one pool per MySQL cluster — where each pool has exactly one backend server: the cluster's primary.

### Discovery via Consul

Within Consul's KV store, the identities of cluster primaries are written. Each GLB/HAProxy node runs `consul-template`, which listens for changes to Consul data and reconfigures HAProxy accordingly.

### orchestrator/raft

orchestrator nodes communicate via raft consensus. On primary failure, the raft leader kicks off recovery, promotes a new primary, and advertises the change to all raft nodes. Each node then writes to its local Consul cluster, which triggers GLB/HAProxy reconfiguration.

## Failover Outage Analysis

The total outage time during a failover is the sum of several sequential phases:

### Detection Phase

orchestrator detects master failure through its holistic approach — probing both the master and its replicas. Under normal conditions, failure detection completes in approximately **5 seconds** from the time the master actually becomes unavailable.

### Promotion Phase

The time to promote a replica to primary depends on the quality of the promotion candidate:

- An **ideal candidate** — one with a `prefer` promotion rule AND semi-synchronous replication enabled — can be promoted in approximately **3 seconds**. These candidates have minimal data lag and are pre-configured for quick promotion.
- A **non-ideal candidate** (any other combination) requires additional steps such as catching up on the replication stream and verifying data consistency, taking approximately **10 seconds**.

### Service Discovery Propagation (Consul)

After promotion, orchestrator writes the new primary's identity to Consul's KV store. Propagation time depends on datacenter topology:

- **Same datacenter** as the new primary: approximately **1 second** (local Consul cluster update)
- **Cross-datacenter**: approximately **2 seconds** (requires cross-DC Consul communication)

The relevant comparison is between the new primary's datacenter and the failed primary's datacenter.

### Proxy Reconfiguration (HAProxy)

GLB/HAProxy watches for Consul KV changes via `consul-template` and reconfigures backend pools:

- **Same datacenter**: approximately **1 second** to reload configuration
- **Cross-datacenter**: approximately **2 seconds** for the full reconfiguration cycle

### No Candidate Available

When no promotion candidate is available (all replicas are unreachable or excluded), automated recovery cannot proceed. Manual intervention is required. The estimated automated outage time in this case is **0** — meaning the system cannot estimate a recovery time and the outage is indefinite until an operator intervenes.

## Semi-Synchronous Replication

GitHub runs semi-synchronous replication on critical clusters. In semi-sync mode, a transaction commit on the primary waits for at least one (or more, configurable via `wait_count`) replica to acknowledge receiving the transaction before returning success to the client.

This provides stronger data durability guarantees at the cost of slightly higher write latency. During failover, a semi-sync replica is preferred for promotion because it is guaranteed to have all committed transactions.

## Cross-Datacenter Considerations

Clusters span multiple datacenters for geographic redundancy. Whenever possible, promotion within the same datacenter as the failed primary is preferred. Cross-DC promotion adds latency to both Consul propagation and HAProxy reconfiguration.
