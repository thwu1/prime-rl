Implement a YATA sequence CRDT engine at `/app/crdt_engine.py` that enables multiple clients to concurrently edit a shared text document with guaranteed convergence.

Each character (or compound run of characters) in the sequence is an Item identified by a Lamport timestamp `ID(client_id, clock)`. Items carry `origin` and `origin_right` references — the IDs of the characters immediately to their left and right at insertion time. When concurrent insertions target the same position, the YATA conflict resolution algorithm determines ordering through a scan between origin and origin_right. The scan uses two distinct tracking sets: one that accumulates all items encountered (never cleared) and one tracking the current conflict group (cleared when the insertion point advances past a new origin). This two-set distinction is the critical invariant — it correctly handles items whose causal origins chain through earlier parts of the conflict zone. Among items sharing both origin and origin_right, lower `client_id` is placed first.

The `Document` class must support:

- Construction with a `client_id`
- `insert(pos, text)` / `delete(pos, length)` — local edits at visible positions
- `get_text()` — current visible text
- `get_state_vector()` — returns `{client_id: next_expected_clock}` for each known client
- `encode_update(target_sv=None)` — serializes items (optionally only those missing from `target_sv`) as an update
- `apply_update(update)` — integrates a remote update with dependency resolution for out-of-order delivery
- `snapshot()` — captures `{state_vector, delete_set}` at the current point in time
- `text_at_snapshot(snap)` — reconstructs document text as it existed at that snapshot, regardless of later edits

Required CRDT properties:

- Updates are commutative, associative, and idempotent — all replicas converge to identical text after receiving the same updates in any order
- Multi-character compound items must be supported, with correct splitting when remote operations target interior positions
- Snapshots reconstruct text using the state vector to determine item existence and the delete set for deletion status at that point in time