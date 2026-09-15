A distributed systems model checker framework is provided at `/app/`. It models an entire distributed system as a deterministic state machine — nodes exchange messages, and the checker exhaustively explores all possible event interleavings (via BFS and random walks) to verify protocol safety and liveness properties.

The model checker core (`/app/pkg/base/`) is fully implemented. Two files in `/app/pkg/paxos/` contain stub implementations that must be completed:

## Files to implement

**`/app/pkg/paxos/server.go`** — Complete the `MessageHandler` and `StartPropose` methods (currently `panic("implement me")`). These must correctly implement the Paxos consensus protocol on top of the model checker's node interface. Study the existing type definitions in `server.go`, the message types in `/app/pkg/paxos/message.go`, the helper methods already provided (e.g. `copy()`, `TriggerTimer()`), and especially the detailed test expectations in `/app/pkg/paxos/paxos_test.go` (`TestUnit` in particular) to understand the exact behavior and return values required.

**`/app/pkg/paxos/test_student.go`** — Complete the seven predicate functions (currently `panic("fill me in")`). These return slices of state predicates that guide the model checker's BFS through specific Paxos execution scenarios. Study `/app/pkg/paxos/scenario_test.go` to understand how these predicates are composed by `reachState` and the surrounding test harness, what scenarios each test expects to reach, and the depth constraints involved.

## Required tests

The following tests in `/app/pkg/paxos/` must all pass:

- **TestUnit** — Verifies individual Paxos message handler correctness through expected state comparison. Covers proposer and acceptor behavior across Propose/Accept/Decide phases.
- **TestBasic** — Verifies that BFS can find a basic consensus path from the initial state.
- **TestBfs1, TestBfs2, TestBfs3** — BFS scenario tests that verify the model checker can find consensus paths through specific protocol orderings using predefined predicate chains.
- **TestInvariant** — Consensus safety check. Uses exhaustive BFS and random walks to verify that once a value is decided, it is never changed (the key Paxos safety property).
- **TestPartition1, TestPartition2** — Verify that BFS can find consensus paths even under network partitions where some messages are dropped.
- **TestCase5Failures** — Verifies student-written predicates in `test_student.go` guide BFS through a scenario where a higher-numbered proposal preempts an earlier one after acceptor failures.
- **TestNotTerminate** — Verifies student-written predicates guide BFS through a livelock scenario where competing proposers repeatedly preempt each other.
- **TestConcurrentProposer** — Verifies student-written predicates guide BFS through a scenario where a concurrent proposer preempts and reaches consensus on its own value.

`TestFailChecks` is excluded from verification — it is an ungraded reference test with tight predicate constraints.

## Verification command

```
cd /app && go test ./pkg/paxos/ -v -count=1 -timeout 240s -run "TestUnit|TestBasic|TestBfs|TestInvariant|TestPartition|TestCase5Failures|TestNotTerminate|TestConcurrentProposer"
```

All listed tests must pass with exit code 0.