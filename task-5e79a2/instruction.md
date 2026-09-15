A Go model checker framework at `/app/` provides BFS state-space exploration for distributed protocols. The framework (`/app/pkg/base/`) is complete — it handles immutable state cloning, message delivery, network partitions, message drop-off/duplication, and timer events. Paxos message types and verification helpers are also provided in `/app/pkg/paxos/`.

Complete the following implementations so that all tests pass:

**1. Paxos Server (`/app/pkg/paxos/server.go`)**

Implement `MessageHandler()` and `StartPropose()`. The server handles `ProposeRequest`, `ProposeResponse`, `AcceptRequest`, `AcceptResponse`, and `DecideRequest`. Each node is immutable — `MessageHandler` returns new node(s) reflecting possible outcomes. When a proposer receives enough responses to reach majority, it must return both a node that transitions to the next phase and a node that stays in the current phase (modeling the nondeterministic choice of when to act on the majority).

**2. State-Space Analyzer (`/app/pkg/paxos/analyzer.go`)**

Implement four analysis functions using the BFS infrastructure in `pkg/base`:
- `CountReachableStates`: count unique states explored via BFS up to a depth
- `FindShortestConsensusPath`: find the minimum-depth path to any consensus state
- `VerifySafety`: verify no reachable state violates agreement safety
- `FindNonTerminatingExecution`: find an execution path where consensus is never reached

**3. Scenario Predicates (`/app/pkg/paxos/predicates.go`)**

Implement three predicate chains for guided state exploration via `reachState()` (defined in `helpers.go`):
- `LeadToValueAdoption`: guide to a state where a proposer adopts another proposer's value from acceptor responses
- `LeadToProgressiveContention`: guide to a state where a proposer's accept phase is disrupted by a competing prepare
- `LeadToThreeWayResolution`: guide three competing proposers to consensus

All tests must pass:

```
cd /app && go test ./pkg/paxos/... -v -count=1 -timeout 540s
```