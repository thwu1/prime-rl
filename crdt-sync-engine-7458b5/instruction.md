A multi-peer CRDT synchronization engine at `/app/src/sync-engine.ts` uses the Yjs library to manage document state replication across simulated peers. The implementation contains defects across multiple methods — some interacting — that prevent correct synchronization. Several methods are incorrectly implemented stubs that must be rewritten. Fix all issues so the engine passes its complete test suite of 18 scenarios.

**Files:**
- `/app/src/sync-engine.ts` — Implementation to fix (only file you need to modify)
- `/app/package.json` — Dependencies (yjs 13.6.20, typescript 5.5.4)
- `/app/tsconfig.json` — TypeScript configuration (strict mode, commonjs output to `dist/`)

**Public API contract for `SyncEngine`:**

- `addPeer(id)` — Register a new peer. The `pendingUpdates` buffer must only accumulate locally-originated document mutations.
- `forkPeer(existingId, newId)` — Clone an existing peer's document state into a new fully-functional peer with update tracking. Initial state transfer must not appear in the new peer's pending buffer.
- `localEdit(peerId, fn)` — Execute a transacted edit on a peer's document.
- `syncFull(id1, id2)` — Exchange complete document state. Both peers must converge. Compacted snapshots must be invalidated.
- `syncDelta(id1, id2)` — Synchronize via state-vector-based differential encoding. Each peer computes the diff the other is missing. Snapshots must be invalidated.
- `syncDocless(id1, id2)` — Synchronize using binary-level update operations only. Diffs must be computed entirely from compacted snapshots, not from the live document objects.
- `syncIncremental(id1, id2)` — Lightweight sync by exchanging buffered pending updates. Each peer must receive the other's buffered changes. Pending buffers must be cleared and snapshots invalidated after exchange.
- `compact(peerId)` — Rebuild the compacted snapshot from current document state. Must never return stale data regardless of prior sync history.
- `checkConvergence()` — Report whether all peers hold identical document state via value-based state vector comparison.
- `broadcastSync(strategy)` — Synchronize all peers to full convergence using the specified strategy, regardless of peer count.
- `drainPendingUpdates(peerId)` — Return buffered pending updates merged into a single update, clearing the buffer. Return `null` if empty.
- `createCheckpoint(peerId)` — Capture a compact reference to the peer's current document version, suitable as a baseline for computing future differential updates. Return the checkpoint ID.
- `diffSinceCheckpoint(peerId, checkpointId)` — Compute an update containing only changes since the checkpoint. Return `null` if unchanged.
- `getNetworkStats()` — Return aggregate sync statistics with valid numeric values in all edge cases including zero syncs.

**Success criteria:**

```
cd /app && npm install && npx tsc
```

The compiled `/app/dist/sync-engine.js` must pass all 18 test scenarios covering two-peer sync (full, delta, docless, incremental), multi-peer broadcast convergence, fork workflows, update buffer integrity, snapshot freshness, checkpoint-based diffing, repeated edit-sync cycles, drain semantics, and statistics edge cases.
