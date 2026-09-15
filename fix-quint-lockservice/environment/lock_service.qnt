// Distributed Lock Service with Fencing Tokens
//
// Models a lock service where nodes can request, acquire, and release
// a distributed lock. Fencing tokens provide monotonically increasing
// identifiers to prevent stale lock holders from performing operations.
//

module lockService {
  pure val NODES = Set("n1", "n2", "n3")

  var lockHolder: str
  var fencingToken: int
  var nodeTokens: str -> int
  var requests: Set[str]
  var nodeState: str -> str

  action init = all {
    lockHolder' = "",
    fencingToken' = 0,
    nodeTokens' = NODES.mapBy(_ => 0),
    requests' = Set(),
    nodeState' = NODES.mapBy(_ => "idle"),
  }

  // A node requests the lock
  action requestLock(node) = all {
    nodeState.get(node) == "idle",
    requests' = requests.union(Set(node)),
    nodeState' = nodeState.set(node, "waiting"),
    lockHolder' = lockHolder,
    fencingToken' = fencingToken,
    nodeTokens' = nodeTokens,
  }

  // The lock manager grants the lock to a requesting node
  action grantLock(node) = all {
    requests.contains(node),
    fencingToken' = fencingToken + 1,
    lockHolder' = node,
    nodeTokens' = nodeTokens.set(node, fencingToken + 1),
    requests' = requests.filter(r => r != node),
    nodeState' = nodeState.set(node, "holding"),
  }

  // A node voluntarily releases the lock
  action releaseLock(node) = all {
    nodeState.get(node) == "holding",
    lockHolder == node,
    lockHolder' = lockHolder,
    nodeState' = nodeState.set(node, "idle"),
    fencingToken' = fencingToken,
    nodeTokens' = nodeTokens,
    requests' = requests,
  }

  // The lock lease expires (models crash or timeout of the holder)
  action lockExpires = all {
    lockHolder != "",
    lockHolder' = "",
    nodeState' = nodeState,
    fencingToken' = fencingToken,
    nodeTokens' = nodeTokens,
    requests' = requests,
  }

  // An expired node recovers and becomes idle
  action recoverNode(node) = all {
    nodeState.get(node) == "expired",
    nodeState' = nodeState.set(node, "idle"),
    lockHolder' = lockHolder,
    fencingToken' = fencingToken,
    nodeTokens' = nodeTokens,
    requests' = requests,
  }

  action step = {
    nondet node = NODES.oneOf()
    any {
      requestLock(node),
      grantLock(node),
      releaseLock(node),
      lockExpires,
      recoverNode(node),
    }
  }

  // Safety: At most one node holds the lock at any time
  val mutualExclusion = NODES.forall(n1 => NODES.forall(n2 =>
    (nodeState.get(n1) == "holding" or nodeState.get(n2) == "holding")
      implies (n1 == n2)
  ))

  // Safety: Lock holder state is consistent with node states
  val holderConsistency =
    NODES.forall(n => (nodeState.get(n) == "holding") implies (lockHolder == n))
    and (lockHolder == "" or NODES.exists(n => n == lockHolder and nodeState.get(n) == "holding"))
}
