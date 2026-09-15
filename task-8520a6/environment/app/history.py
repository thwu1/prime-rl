
"""Edit history management with undo/redo support."""

from __future__ import annotations
from typing import List
from buffer import PieceTable


class UndoTree:
    """Edit history with undo and redo support.

    Tracks document states for navigation through edit history.
    """

    def __init__(self, initial_text: str):
        self._states: List[PieceTable] = [PieceTable(initial_text)]
        self._pos = 0
        self._redo: List[int] = []
        self._next_id = 1

    @property
    def current_node_id(self) -> int:
        return self._pos

    def current_text(self) -> str:
        return self._states[self._pos].get_text()

    def apply_insert(self, offset: int, text: str) -> None:
        pt = self._states[self._pos].insert(offset, text)
        self._states = self._states[: self._pos + 1]
        self._states.append(pt)
        self._pos = len(self._states) - 1
        self._redo.clear()

    def apply_delete(self, offset: int, length: int) -> None:
        pt = self._states[self._pos].delete(offset, length)
        self._states = self._states[: self._pos + 1]
        self._states.append(pt)
        self._pos = len(self._states) - 1
        self._redo.clear()

    def undo(self) -> bool:
        if self._pos == 0:
            return False
        self._redo.append(self._pos)
        self._pos -= 1
        return True

    def redo(self, branch: int = 0) -> bool:
        if not self._redo:
            return False
        self._pos = self._redo.pop()
        return True

    def get_node_text(self, node_id: int) -> str:
        if node_id < 0 or node_id >= len(self._states):
            raise KeyError(f"Unknown node: {node_id}")
        return self._states[node_id].get_text()

    def get_children_count(self) -> int:
        return 1 if self._redo else 0

    def get_tree_structure(self) -> dict:
        raise NotImplementedError("Tree structure query not yet supported")
