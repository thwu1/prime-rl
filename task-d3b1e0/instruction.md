The Go application at `/app/main.go` implements an in-memory MVCC (multi-version concurrency control) key-value store with transaction support. The data model stores multiple versions of each value tagged with creating (`txStartId`) and deleting (`txEndId`) transaction IDs. Transaction metadata tracks which transactions were in-progress at start time, along with read and write sets for conflict detection.

Only Read Uncommitted isolation is currently implemented. The `isvisible()`, `completeTransaction()`, and `vacuum()` functions contain TODO stubs that must be replaced with working implementations.

Design and implement the remaining isolation levels and garbage collection in `/app/main.go`:

**Read Committed**: Transactions see only data from committed transactions (or their own writes). Uncommitted or aborted mutations by other transactions must not affect visibility.

**Repeatable Read / Snapshot Isolation / Serializable**: These share identical visibility rules providing a consistent snapshot as of the transaction's start time. Concurrent commits must not alter what the transaction sees. Values from transactions in-progress at start time are invisible regardless of later commits.

**Snapshot Isolation** additionally requires write-write conflict detection at commit time (error: `"write-write conflict"`).

**Serializable** requires read-write conflict detection at commit time via Write Snapshot Isolation (error: `"read-write conflict"`).

**Vacuum**: Garbage-collect value versions no longer reachable by any active or future transaction. Remove versions from aborted transactions. Remove versions superseded before all active transactions. Clean up keys with no remaining versions.

Helper functions `hasConflict()` and `setsShareItem()` are provided. Study the `Transaction` struct fields, `Value` type, and existing `completeTransaction()` structure to inform your design.