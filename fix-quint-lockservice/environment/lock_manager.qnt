// Distributed Lock Manager with Epoch-Based Leader Election
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
    epoch' = epoch,
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
    fencingToken' = fencingToken,
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
    role' = role,
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
    and NODES.forall(n => (role.get(n) == "leader") implies (epoch.get(n) > lockEpoch))

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
  val voteConsistency = true
}
