"""
YATA Sequence CRDT - Interface Specification

Implement these classes in /app/crdt.py.
See /app/spec.md for the full algorithm specification.
"""

from __future__ import annotations
from typing import Optional, Dict, Any


class YText:
    """A shared text sequence within a YDoc."""

    def insert(self, index: int, text: str) -> None:
        """Insert text at the given visible position index.

        Each character becomes a separate Item in the CRDT linked list.
        The origin of each character is the ID of the item to its left
        at creation time, and origin_right is the original right boundary.
        """
        raise NotImplementedError

    def delete(self, index: int, length: int) -> None:
        """Delete `length` characters starting at visible position `index`.

        Marks items as deleted (tombstoned). Does not remove them from
        the linked list. Does not increment the client's clock.
        """
        raise NotImplementedError

    def to_string(self) -> str:
        """Return the visible (non-deleted) text content."""
        raise NotImplementedError

    def __str__(self) -> str:
        return self.to_string()

    def __len__(self) -> int:
        """Return the count of visible (non-deleted) characters."""
        raise NotImplementedError


class YDoc:
    """A YATA CRDT document replica.

    Each YDoc instance represents one client's view of the shared document.
    Multiple YDoc instances synchronize via updates.
    """

    def __init__(self, client_id: int):
        """Create a new document for the given client.

        Args:
            client_id: Unique integer identifying this client/replica.
        """
        raise NotImplementedError

    def get_text(self, name: str) -> YText:
        """Get or create a named text sequence.

        Multiple named text sequences can coexist in a single document.
        Each maintains its own independent linked list of items.
        """
        raise NotImplementedError

    def get_state_vector(self) -> Dict[int, int]:
        """Compute the state vector of this document.

        Returns a dict mapping client_id to the next expected clock value
        (one past the maximum clock seen from that client).
        An empty dict means no items have been received.
        """
        raise NotImplementedError

    def encode_update(self, target_sv: Optional[Dict[int, int]] = None) -> Dict[str, Any]:
        """Encode the document state (or diff) as a JSON-serializable update.

        Args:
            target_sv: The state vector of the target document. If None,
                       encodes the full document state. If provided, encodes
                       only items the target is missing.

        Returns:
            A dict with 'items' and 'delete_set' keys.
        """
        raise NotImplementedError

    def apply_update(self, update: Dict[str, Any]) -> None:
        """Apply an update to this document.

        Integrates new items using the YATA conflict resolution algorithm
        and applies the delete set. Updates are commutative, associative,
        and idempotent.

        Args:
            update: A dict with 'items' and 'delete_set' keys, as produced
                    by encode_update().
        """
        raise NotImplementedError

    def snapshot(self) -> Dict[str, Any]:
        """Create a snapshot of the current document state.

        Returns a dict with 'state_vector' and 'delete_set' keys.
        The snapshot can be used later with text_at_snapshot() to
        reconstruct the document text at this point in time.
        """
        raise NotImplementedError

    def text_at_snapshot(self, name: str, snap: Dict[str, Any]) -> str:
        """Reconstruct the text of a named sequence at a snapshot point.

        Walks the current linked list (which contains all items ever created)
        and filters based on the snapshot's state vector and delete set.

        Args:
            name: The name of the text sequence.
            snap: A snapshot dict as returned by snapshot().

        Returns:
            The text content as it was at the snapshot point.
        """
        raise NotImplementedError
