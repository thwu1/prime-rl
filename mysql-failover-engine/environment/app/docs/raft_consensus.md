# Raft Consensus

`orchestrator` nodes communicate via the Raft consensus protocol to ensure reliable leader election and prevent split-brain scenarios during failover.

## orchestrator/raft Setup

In the `orchestrator/raft` deployment, several `orchestrator` nodes communicate with each other via the raft consensus protocol. This solves both high-availability for `orchestrator` itself and network isolation issues, particularly cross-datacenter network partitioning/fencing.

We recommend running 3 or 5 `orchestrator` nodes, one per datacenter.

## Quorum

By using a consensus protocol, the `orchestrator` nodes are able to pick a leader that has *quorum*, implying it is not isolated. In a cluster of N nodes, a quorum requires a strict majority:

    quorum = (N ÷ 2) + 1    (integer division)

For example:
- 3 nodes: quorum = 2
- 5 nodes: quorum = 3

A node cannot become leader if it does not have quorum. In a 3-node setup, the quorum size is 2. In a 5-node setup, the quorum size is 3.

## Leader Election

Each `orchestrator` node maintains a view of which other nodes it can communicate with. For leader election purposes:

- A node always counts itself as reachable (reachable count starts at 1)
- For each other node in the cluster, the node checks whether it can reach that peer
- A node is eligible for leadership only if its reachable count meets or exceeds the quorum
- Among eligible nodes, the node reaching the **most peers** is preferred as leader — it has the best overall network connectivity
- Ties are broken alphabetically by hostname for deterministic behavior

If no node can reach quorum (e.g., in a complete network partition), no leader is elected and automated recovery is suspended until connectivity is restored.

## Datacenter Fencing

Consider a 3-node `orchestrator` cluster spanning DC1, DC2, and DC3. If DC2 becomes network-isolated:

- The node in DC2 can only reach itself (1 node < quorum of 2), so it **cannot** become leader
- Nodes in DC1 and DC3 can reach each other (2 nodes >= quorum of 2), so one becomes leader
- Failover decisions are made only from the quorum side, preventing conflicting actions from the isolated DC

This architecture ensures that even during datacenter-level network events, failover decisions are consistent and prevent split-brain scenarios.

## Five-Node Example

In a 5-node cluster (quorum = 3), partial network partitions create more nuanced scenarios. Consider:

- Node A can reach B and C (reachable = 3, including self) → eligible
- Node B can reach A, C, and D (reachable = 4) → eligible, with better connectivity
- Node C can reach A and B (reachable = 3) → eligible
- Node D can only reach B (reachable = 2) → NOT eligible (2 < 3)
- Node E is fully isolated (reachable = 1) → NOT eligible

In this case, B would be elected leader as the eligible node with the most reachable peers.

## Recovery Without Orchestrator Nodes

If no orchestrator nodes are configured at all (empty node list), the raft consensus check is skipped entirely and recovery proceeds based solely on failure detection and recovery conditions. This supports standalone or single-node orchestrator deployments where consensus is not required.

## Behavior and Implications

- Each `orchestrator` node independently runs discoveries of all MySQL servers
- In normal times, all nodes see a more-or-less identical picture of the topologies
- All user changes must go through the leader via the HTTP API
- A failure of a single node does not affect availability (in a 3-node setup, 1 can fail; in 5-node, 2 can fail)
- An `orchestrator` node may go down and come back; it will rejoin the raft group and receive missed events
