"""
Persistent Text Buffer with Branching Undo and Diff.

"""


class PieceTable:
    """A text buffer supporting efficient editing, snapshots, branching undo/redo, and diff.

    All editing operations (insert, delete, char_at) must be O(log n).
    Snapshots must remain valid after subsequent edits.
    """

    def __init__(self, initial_text: str = ""):
        """Initialize with optional initial text."""
        raise NotImplementedError

    def insert(self, offset: int, text: str) -> None:
        """Insert text at character offset."""
        raise NotImplementedError

    def delete(self, offset: int, length: int) -> None:
        """Delete length characters starting at offset."""
        raise NotImplementedError

    def get_text(self) -> str:
        """Return full document text."""
        raise NotImplementedError

    def char_at(self, offset: int) -> str:
        """Return character at given offset."""
        raise NotImplementedError

    def length(self) -> int:
        """Return total character count."""
        raise NotImplementedError

    def line_count(self) -> int:
        """Return number of lines (at least 1 for empty text)."""
        raise NotImplementedError

    def get_line(self, line_num: int) -> str:
        """Return line at 0-indexed line number, including trailing newline if present."""
        raise NotImplementedError

    def snapshot(self) -> int:
        """Save current state. Returns snapshot ID."""
        raise NotImplementedError

    def restore(self, snapshot_id: int) -> None:
        """Restore to a saved snapshot. Creates an undo entry so restore is undoable."""
        raise NotImplementedError

    def undo(self) -> bool:
        """Undo last operation. Returns False if at root."""
        raise NotImplementedError

    def redo(self, branch: int = 0) -> bool:
        """Redo at given branch index. Returns False if invalid."""
        raise NotImplementedError

    def redo_branch_count(self) -> int:
        """Return number of redo branches from current position."""
        raise NotImplementedError

    def undo_depth(self) -> int:
        """Return depth from undo root to current position."""
        raise NotImplementedError

    def diff_snapshots(self, snap_a: int, snap_b: int) -> list:
        """Compute line-level diff between two snapshots.

        Returns list of (op, line) tuples where op is '+', '-', or ' '.
        Lines do not include trailing newlines in the tuples.
        """
        raise NotImplementedError

    # --- Internal structure inspection (for testing) ---

    def _tree_height(self) -> int:
        """Return height of internal tree structure."""
        raise NotImplementedError

    def _piece_count(self) -> int:
        """Return number of pieces."""
        raise NotImplementedError

    def _is_balanced(self) -> bool:
        """Return True if internal structure satisfies balance invariants."""
        raise NotImplementedError

    def _get_buffers(self) -> tuple:
        """Return (original_buffer, add_buffer) for inspection."""
        raise NotImplementedError
