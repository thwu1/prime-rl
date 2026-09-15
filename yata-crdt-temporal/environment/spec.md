# CRDTDoc API Specification

## Module: `/app/crdt.py`

### Class: `CRDTDoc`

```python
class CRDTDoc:
    def __init__(self, client_id: int):
        """Create a new CRDT document for the given client.
        Each client must have a unique integer ID."""

    def insert(self, index: int, text: str) -> None:
        """Insert text at the given visible (non-deleted) character index.
        Each character is tracked individually with a unique (client_id, clock)
        identifier. The clock increments by 1 for each character inserted."""

    def delete(self, index: int, length: int = 1) -> None:
        """Delete `length` characters starting at visible index `index`."""

    def get_content(self) -> str:
        """Return current visible content (non-deleted characters in
        document order)."""

    def get_state_vector(self) -> dict:
        """Return {client_id: next_expected_clock} for all known clients.
        If client 1 has inserted 5 characters (clocks 0..4), its entry is {1: 5}.
        An empty document returns {}."""

    def encode_update(self, remote_sv: dict = None) -> dict:
        """Encode operations the remote peer is missing, based on its state vector.

        Args:
            remote_sv: The remote peer's state vector. If None, treated as {}.

        Returns:
            {
                "structs": [
                    {
                        "id": (client, clock),
                        "origin": (client, clock) or None,
                        "origin_right": (client, clock) or None,
                        "char": str,
                        "deleted": bool
                    },
                    ...
                ],
                "delete_set": {
                    client_id: [clock, clock, ...],
                    ...
                }
            }

        Each struct represents one character. The `origin` field is the ID of
        the item immediately to the left at the time this character was inserted
        (None if inserted at document start). The `origin_right` field is the ID
        of the item immediately to the right at insertion time (None if inserted
        at document end). These fields capture insertion context.

        Includes all items with clock >= remote_sv[client] for each client.
        The delete_set includes all currently deleted item clocks.
        """

    def apply_update(self, update: dict) -> None:
        """Apply a remote update to this document.

        Integrates new items from update["structs"] and applies deletions
        from update["delete_set"]. Must handle operations arriving in
        arbitrary order and produce convergent results when concurrent
        operations target overlapping regions."""

    def merge(self, other: 'CRDTDoc') -> None:
        """Bidirectional sync: both documents exchange and apply updates
        so that they converge to identical content."""

    def snapshot(self) -> dict:
        """Create a point-in-time snapshot of current document state.

        Returns:
            {
                "state_vector": {client_id: next_clock, ...},
                "delete_set": {client_id: [deleted_clock, ...], ...}
            }
        """

    def restore_snapshot(self, snap: dict) -> str:
        """Reconstruct document content at a prior snapshot's point in time.
        Uses the current document's internal state but filters through the
        snapshot's state vector and delete set to recover historical content."""

    def encode_delta(self, old_snap: dict, new_snap: dict) -> dict:
        """Compute the delta between two snapshots.

        Returns:
            {
                "structs": [...],
                "deletions": [(client, clock), ...],
                "base_sv": {...},
                "target_sv": {...}
            }

        structs: items present at new_snap but not at old_snap.
        deletions: items deleted at new_snap but not at old_snap.
        """

    def apply_delta(self, delta: dict) -> None:
        """Apply a delta (from encode_delta) to advance document state.
        Integrates new items and applies new deletions."""
```
