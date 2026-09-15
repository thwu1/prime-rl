A cluster simulation framework at `/app/` is implemented as a Go module. It provides transport, state machine, and cluster management layers for a distributed consensus protocol. The core node logic in `/app/raft/node.go` has all protocol methods stubbed with `panic("not implemented")`.

Implement every stubbed method so that a cluster of nodes:

- Reliably elects a single leader
- Replicates key-value state consistently to all nodes
- Recovers from node crashes and restarts
- Continues operating through network partitions (majority side)
- Converges to a consistent state when partitions heal
- Overwrites stale uncommitted entries from deposed leaders

Study the files in `/app/raft/` to understand the protocol types, transport API, and cluster lifecycle. Build and test with Go tooling (`go build`, `go test`).