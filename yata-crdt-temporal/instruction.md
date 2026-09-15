Build a Python module at `/app/crdt.py` that implements a collaborative text editing CRDT reproducing the conflict resolution semantics of the Yjs library's sequence type.

The algorithm specification is at `/app/yata_reference.md` and the required Python API is defined in `/app/spec.md`. Study both carefully — the conflict resolution rules are subtle, and the test suite checks exact character ordering against known expected outcomes.

Your `CRDTDoc` class must satisfy the following properties:

- **Convergence**: any two replicas that have received the same set of operations produce identical document content, regardless of application order
- **Commutativity**: applying the same set of updates in any order yields identical results
- **Idempotency**: re-applying an update already seen is a no-op
- **Correct conflict ordering**: when multiple clients concurrently insert at the same position, the resolved character order must match the YATA rules (lower client IDs are placed to the left)
- **Temporal reconstruction**: snapshots capture a point-in-time view; restoring a snapshot from the current document state recovers historical content exactly
- **Delta encoding**: deltas between snapshots encode structural and deletion differences, and applying a delta advances a document to the target state

The test suite validates 37 scenarios covering basic operations, state vectors, concurrent inserts with 2–4 clients, sync property verification, snapshot creation/restoration, delta encoding/application, complex multi-phase editing, and advanced conflict resolution including phased edit-sync cycles and interleaved insert/delete conflicts.

Validation: `/tests/test_state.py`