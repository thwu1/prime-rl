#!/usr/bin/env python3

"""
Fixes all 5 bugs in the distributed lock manager specification and writes
the diagnosis report. Bugs fixed:

1. castVote: voter's epoch not updated — enables double-voting
2. grantLock: fencingToken not incremented — violates fencingTokenOrder
3. partitionNode: role not stepped down — violates splitBrainPrevention
4. epochMonotonicity invariant: uses > instead of >= for leader-lockEpoch
5. voteConsistency invariant: trivially true, needs full formalization
"""

import json

CORRECTED_SPEC = r'''// Distributed Lock Manager with Epoch-Based Leader Election
//
// Formal specification of a distributed lock manager for a three-node cluster.
// Nodes elect a leader through epoch-based majority voting. The leader manages
// an exclusive lock protected by monotonically increasing fencing tokens.
// Network partitions are modeled explicitly.
//

module lockManager {
  pure val NODES = Set("n1", "n2", "n3")
  pure val MAJORITY = 2

  var epoch: str -> int
  var role: str -> str
  var votedFor: str -> str
  var votesReceived: str -> Set[str]
  var lockHolder: str
  var lockEpoch: int
  var fencingToken: int
  var partitioned: Set[str]
  var lockRequests: Set[str]

  action init = all {
    epoch' = NODES.mapBy(_ => 0),
    role' = NODES.mapBy(_ => "follower"),
    votedFor' = NODES.mapBy(_ => ""),
    votesReceived' = NODES.mapBy(_ => Set()),
    lockHolder' = "",
    lockEpoch' = 0,
    fencingToken' = 0,
    partitioned' = Set(),
    lockRequests' = Set(),
  }

  pure def canComm(a: str, b: str, iso: Set[str]): bool = {
    not(iso.contains(a)) and not(iso.contains(b))
  }

  // A follower or candidate starts a new election by incrementing its epoch
  action startElection(node) = all {
    not(partitioned.contains(node)),
    role.get(node) != "leader",
    epoch' = epoch.set(node, epoch.get(node) + 1),
    role' = role.set(node, "candidate"),
    votedFor' = votedFor.set(node, node),
    votesReceived' = votesReceived.set(node, Set(node)),
    lockHolder' = lockHolder,
    lockEpoch' = lockEpoch,
    fencingToken' = fencingToken,
    partitioned' = partitioned,
    lockRequests' = lockRequests,
  }

  // A node grants its vote to a candidate in a higher or equal epoch
  action castVote(voter, candidate) = all {
    voter != candidate,
    canComm(voter, candidate, partitioned),
    role.get(candidate) == "candidate",
    epoch.get(candidate) >= epoch.get(voter),
    (epoch.get(candidate) > epoch.get(voter)) or (votedFor.get(voter) == ""),
    epoch' = epoch.set(voter, epoch.get(candidate)),
    role' = role.set(voter, "follower"),
    votedFor' = votedFor.set(voter, candidate),
    votesReceived' = votesReceived.set(candidate, votesReceived.get(candidate).union(Set(voter))),
    lockHolder' = lockHolder,
    lockEpoch' = lockEpoch,
    fencingToken' = fencingToken,
    partitioned' = partitioned,
    lockRequests' = lockRequests,
  }

  // A candidate with enough votes transitions to leader and invalidates existing locks
  action becomeLeader(node) = all {
    role.get(node) == "candidate",
    votesReceived.get(node).size() >= MAJORITY,
    not(partitioned.contains(node)),
    epoch' = epoch,
    role' = role.set(node, "leader"),
    votedFor' = votedFor,
    votesReceived' = votesReceived,
    lockHolder' = "",
    lockEpoch' = lockEpoch,
    fencingToken' = fencingToken,
    partitioned' = partitioned,
    lockRequests' = lockRequests,
  }

  // The leader grants the lock to a requesting node with a new fencing token
  action grantLock(leader, requester) = all {
    role.get(leader) == "leader",
    leader != requester,
    canComm(leader, requester, partitioned),
    lockHolder == "",
    lockRequests.contains(requester),
    epoch' = epoch,
    role' = role,
    votedFor' = votedFor,
    votesReceived' = votesReceived,
    lockHolder' = requester,
    lockEpoch' = epoch.get(leader),
    fencingToken' = fencingToken + 1,
    partitioned' = partitioned,
    lockRequests' = lockRequests.filter(r => r != requester),
  }

  // The leader revokes the currently held lock
  action revokeLock(leader) = all {
    role.get(leader) == "leader",
    lockHolder != "",
    lockEpoch == epoch.get(leader),
    epoch' = epoch,
    role' = role,
    votedFor' = votedFor,
    votesReceived' = votesReceived,
    lockHolder' = "",
    lockEpoch' = lockEpoch,
    fencingToken' = fencingToken,
    partitioned' = partitioned,
    lockRequests' = lockRequests,
  }

  // A node is isolated from the network
  action partitionNode(node) = all {
    not(partitioned.contains(node)),
    epoch' = epoch,
    role' = role.set(node, "follower"),
    votedFor' = votedFor,
    votesReceived' = votesReceived,
    lockHolder' = lockHolder,
    lockEpoch' = lockEpoch,
    fencingToken' = fencingToken,
    partitioned' = partitioned.union(Set(node)),
    lockRequests' = lockRequests,
  }

  // A partitioned node recovers
  action healPartition(node) = all {
    partitioned.contains(node),
    epoch' = epoch,
    role' = role.set(node, "follower"),
    votedFor' = votedFor.set(node, ""),
    votesReceived' = votesReceived,
    lockHolder' = lockHolder,
    lockEpoch' = lockEpoch,
    fencingToken' = fencingToken,
    partitioned' = partitioned.filter(n => n != node),
    lockRequests' = lockRequests,
  }

  // A non-partitioned node requests the lock
  action requestLock(node) = all {
    not(partitioned.contains(node)),
    lockHolder != node,
    not(lockRequests.contains(node)),
    epoch' = epoch,
    role' = role,
    votedFor' = votedFor,
    votesReceived' = votesReceived,
    lockHolder' = lockHolder,
    lockEpoch' = lockEpoch,
    fencingToken' = fencingToken,
    partitioned' = partitioned,
    lockRequests' = lockRequests.union(Set(node)),
  }

  action step = {
    nondet n1 = NODES.oneOf()
    nondet n2 = NODES.oneOf()
    any {
      startElection(n1),
      castVote(n1, n2),
      becomeLeader(n1),
      grantLock(n1, n2),
      revokeLock(n1),
      partitionNode(n1),
      healPartition(n1),
      requestLock(n1),
    }
  }

  // Safety: at most one leader per epoch
  val singleLeader = NODES.forall(n1 => NODES.forall(n2 =>
    (role.get(n1) == "leader" and role.get(n2) == "leader" and epoch.get(n1) == epoch.get(n2))
      implies n1 == n2
  ))

  // Safety: epoch ordering — all epochs non-negative, leader epoch dominates lock epoch
  val epochMonotonicity =
    NODES.forall(n => epoch.get(n) >= 0)
    and lockEpoch >= 0
    and NODES.forall(n => (role.get(n) == "leader") implies (epoch.get(n) >= lockEpoch))

  // Safety: fencing token integrity — positive when lock held, holder is a valid node
  val fencingTokenOrder =
    fencingToken >= 0
    and ((lockHolder != "") implies (fencingToken > 0))
    and ((lockHolder != "") implies NODES.contains(lockHolder))

  // Safety: no partitioned node may be leader
  val splitBrainPrevention =
    NODES.forall(n => partitioned.contains(n) implies role.get(n) != "leader")

  // Safety: vote consistency — for candidates/leaders in the same epoch,
  // their received vote sets must be disjoint (no double-voting)
  val voteConsistency = NODES.forall(n1 => NODES.forall(n2 =>
    (n1 != n2
     and (role.get(n1) == "candidate" or role.get(n1) == "leader")
     and (role.get(n2) == "candidate" or role.get(n2) == "leader")
     and epoch.get(n1) == epoch.get(n2))
      implies votesReceived.get(n1).intersect(votesReceived.get(n2)) == Set()
  ))
}
'''

# Write the corrected specification
with open('/app/lock_manager.qnt', 'w') as f:
    f.write(CORRECTED_SPEC)

# Write diagnosis
diagnosis = [
    {
        "definition": "castVote",
        "bug": (
            "The castVote action does not update the voter's epoch to the candidate's "
            "epoch (epoch' = epoch instead of epoch' = epoch.set(voter, epoch.get(candidate))). "
            "This allows a voter whose epoch remains at a stale value to pass the epoch guard "
            "for multiple candidates in the same logical term, enabling double-voting."
        ),
        "fix": (
            "Changed epoch' = epoch to epoch' = epoch.set(voter, epoch.get(candidate)). "
            "After voting, the voter's epoch is synchronized to the candidate's epoch, "
            "which prevents the voter from passing the epoch comparison guard for any "
            "other candidate in the same epoch, ensuring at most one vote per epoch."
        ),
    },
    {
        "definition": "grantLock",
        "bug": (
            "The grantLock action does not increment the fencing token when granting a "
            "lock (fencingToken' = fencingToken instead of fencingToken' = fencingToken + 1). "
            "This means the fencing token stays at 0 after the first lock grant, violating "
            "the fencingTokenOrder invariant which requires fencingToken > 0 when a lock is held."
        ),
        "fix": (
            "Changed fencingToken' = fencingToken to fencingToken' = fencingToken + 1. "
            "Each lock grant now produces a strictly increasing fencing token, ensuring "
            "the token is always positive when a lock is held and enabling downstream "
            "systems to reject operations from stale lock holders."
        ),
    },
    {
        "definition": "partitionNode",
        "bug": (
            "The partitionNode action does not step down a leader or candidate when the "
            "node is partitioned (role' = role leaves the role unchanged). A partitioned "
            "leader retains its role even though it cannot communicate with the cluster, "
            "directly violating the splitBrainPrevention safety invariant."
        ),
        "fix": (
            "Changed role' = role to role' = role.set(node, \"follower\"). When a node is "
            "partitioned, it is unconditionally stepped down to follower regardless of its "
            "previous role. This ensures no partitioned node retains a leader or candidate "
            "role, maintaining the split-brain prevention safety property."
        ),
    },
    {
        "definition": "epochMonotonicity",
        "bug": (
            "The epochMonotonicity invariant uses strict greater-than (>) instead of "
            "greater-than-or-equal (>=) for the leader-lockEpoch comparison. When a leader "
            "grants a lock, lockEpoch is correctly set to the leader's epoch, making them "
            "equal. The strict comparison then falsely reports a violation."
        ),
        "fix": (
            "Changed the leader comparison from epoch.get(n) > lockEpoch to "
            "epoch.get(n) >= lockEpoch. A leader's epoch must be at least as large as "
            "lockEpoch, but they can be equal immediately after the leader grants a lock "
            "in its own epoch. The weak inequality correctly captures this property."
        ),
    },
    {
        "definition": "voteConsistency",
        "bug": (
            "The voteConsistency invariant was set to the trivial value 'true' instead "
            "of being formalized as a quantified predicate. This means no actual safety "
            "check was performed for vote consistency, allowing double-voting violations "
            "to go undetected during simulation."
        ),
        "fix": (
            "Formalized voteConsistency as: for all pairs of distinct nodes that are both "
            "candidates or leaders AND share the same epoch, their votesReceived sets must "
            "be disjoint (intersection is empty). The same-epoch condition is essential "
            "because votes in different epochs are independent and legitimately overlap."
        ),
    },
]

with open('/app/diagnosis.json', 'w') as f:
    json.dump(diagnosis, f, indent=2)

print("Corrected specification written to /app/lock_manager.qnt")
print("Diagnosis written to /app/diagnosis.json")
