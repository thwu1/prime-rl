#!/usr/bin/env python3

"""
Fixes the buggy lock_service.qnt specification and writes results.json.

Bugs fixed:
1. grantLock: Missing lockHolder == "" guard allows double-granting.
2. releaseLock: lockHolder' = lockHolder stutters instead of clearing to "".
3. lockExpires: nodeState' = nodeState leaves the expired holder in "holding" state.
4. mutualExclusion: Uses "or" instead of "and", making it trivially violated
   whenever any single node holds the lock.

Invariant added:
5. tokenValidity: Ensures fencing token properties are maintained.
"""

import json

FIXED_SPEC = r'''// Distributed Lock Service with Fencing Tokens
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
  // FIX 1: Added lockHolder == "" guard to prevent granting while lock is held
  action grantLock(node) = all {
    requests.contains(node),
    lockHolder == "",
    fencingToken' = fencingToken + 1,
    lockHolder' = node,
    nodeTokens' = nodeTokens.set(node, fencingToken + 1),
    requests' = requests.filter(r => r != node),
    nodeState' = nodeState.set(node, "holding"),
  }

  // A node voluntarily releases the lock
  // FIX 2: Changed lockHolder' = lockHolder to lockHolder' = "" to actually release
  action releaseLock(node) = all {
    nodeState.get(node) == "holding",
    lockHolder == node,
    lockHolder' = "",
    nodeState' = nodeState.set(node, "idle"),
    fencingToken' = fencingToken,
    nodeTokens' = nodeTokens,
    requests' = requests,
  }

  // The lock lease expires (models crash or timeout of the holder)
  // FIX 3: Update expired holder's nodeState to "expired" instead of leaving unchanged
  action lockExpires = all {
    lockHolder != "",
    nodeState' = nodeState.set(lockHolder, "expired"),
    lockHolder' = "",
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
  // FIX 4: Changed "or" to "and" - both nodes must be holding for implication to apply
  val mutualExclusion = NODES.forall(n1 => NODES.forall(n2 =>
    (nodeState.get(n1) == "holding" and nodeState.get(n2) == "holding")
      implies (n1 == n2)
  ))

  // Safety: Lock holder state is consistent with node states
  val holderConsistency =
    NODES.forall(n => (nodeState.get(n) == "holding") implies (lockHolder == n))
    and (lockHolder == "" or NODES.exists(n => n == lockHolder and nodeState.get(n) == "holding"))

  // FIX 5: Added tokenValidity invariant
  // Ensures fencing token properties: all node tokens in [0, fencingToken],
  // and any holding node's token equals fencingToken
  val tokenValidity = NODES.forall(n =>
    nodeTokens.get(n) >= 0
    and nodeTokens.get(n) <= fencingToken
    and ((nodeState.get(n) == "holding") implies (nodeTokens.get(n) == fencingToken))
  )
}
'''

# Write the fixed specification
with open('/app/lock_service.qnt', 'w') as f:
    f.write(FIXED_SPEC)

# Write results
results = {
    "bugs_fixed": [
        "grantLock: Added guard 'lockHolder == \"\"' to prevent granting the lock when it is already held by another node",
        "releaseLock: Changed 'lockHolder' = lockHolder' (stutter) to 'lockHolder' = \"\"' so the lock is actually released",
        "lockExpires: Changed 'nodeState' = nodeState' (stutter) to 'nodeState' = nodeState.set(lockHolder, \"expired\")' so the expired holder's state is correctly updated",
        "mutualExclusion: Changed 'or' to 'and' in the invariant predicate - the original used disjunction which made the invariant trivially false whenever any single node held the lock"
    ],
    "invariants_added": ["tokenValidity"],
    "description": "tokenValidity ensures that every node's fencing token is non-negative and at most the global fencingToken, and that any node currently holding the lock has a fencing token equal to the global fencingToken"
}

with open('/app/results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Fixed specification written to /app/lock_service.qnt")
print("Results written to /app/results.json")
