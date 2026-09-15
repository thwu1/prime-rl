
"""Text buffer with branching undo/redo and diff support.

This is the main API. It composes a PieceTable (for text storage)
with an UndoTree (for history management) and Myers diff (for
computing changes between states).
"""

from piece_table import PieceTable
from undo_tree import UndoTree
from myers_diff import myers_diff


class TextBuffer:
    def __init__(self, initial_text: str = ""):
        self._piece_table = PieceTable(initial_text)
        self._undo_tree = UndoTree(self._piece_table)

    def get_text(self) -> str:
        return self._piece_table.get_text()

    def length(self) -> int:
        return self._piece_table.length()

    def insert(self, offset: int, text: str, description: str = "") -> int:
        """Insert text at offset. Returns the new state ID."""
        self._piece_table = self._piece_table.insert(offset, text)
        return self._undo_tree.record(
            self._piece_table,
            description or f"insert at {offset}"
        )

    def delete(self, offset: int, length: int, description: str = "") -> int:
        """Delete length chars at offset. Returns the new state ID."""
        self._piece_table = self._piece_table.delete(offset, length)
        return self._undo_tree.record(
            self._piece_table,
            description or f"delete {length} at {offset}"
        )

    def undo(self) -> bool:
        """Undo the last operation. Returns True if successful."""
        result = self._undo_tree.undo()
        if result is not None:
            self._piece_table = result
            return True
        return False

    def redo(self, branch_index: int = 0) -> bool:
        """Redo. branch_index selects among branches. Returns True if successful."""
        result = self._undo_tree.redo(branch_index)
        if result is not None:
            self._piece_table = result
            return True
        return False

    def navigate_to(self, state_id: int) -> bool:
        """Jump to any state in the undo tree. Returns True if successful."""
        result = self._undo_tree.navigate_to(state_id)
        if result is not None:
            self._piece_table = result
            return True
        return False

    @property
    def current_state_id(self) -> int:
        return self._undo_tree.current_id

    def can_undo(self) -> bool:
        return self._undo_tree.can_undo()

    def can_redo(self) -> bool:
        return self._undo_tree.can_redo()

    def num_redo_branches(self) -> int:
        return self._undo_tree.num_branches()

    def get_state_text(self, state_id: int):
        """Get the text content of a specific state.
        Returns the text string, or None if state_id is invalid."""
        raise NotImplementedError("get_state_text() not yet implemented")

    def diff(self, state_a: int, state_b: int):
        """Compute the Myers diff between two states in the undo tree.
        Returns a list of (op, char) tuples, or None if invalid state IDs."""
        raise NotImplementedError("diff() not yet implemented")

    def get_undo_tree_structure(self):
        return self._undo_tree.get_tree_structure()
