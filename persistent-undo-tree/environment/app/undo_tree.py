
"""Tree-structured undo/redo history.

Each node stores a reference to an immutable PieceTable snapshot.
Unlike linear undo, this preserves all branches of editing history:
when the user undoes and then makes a different edit, a new branch
is created rather than discarding the old redo chain.

The tree supports:
  - undo: navigate to parent state
  - redo: navigate to a child state (selected by branch index)
  - navigate_to: jump to any state by ID
  - get_path: find the path between any two states via their LCA
"""


class UndoNode:
    """A single state in the undo tree."""
    __slots__ = ('state_id', 'piece_table', 'parent_id', 'children_ids', 'description')

    def __init__(self, state_id, piece_table, parent_id=None, description=""):
        self.state_id = state_id
        self.piece_table = piece_table
        self.parent_id = parent_id
        self.children_ids = []
        self.description = description


class UndoTree:
    """Manages a tree of editing states."""

    def __init__(self, initial_piece_table):
        self._nodes = {}
        self._next_id = 0
        self._current_id = self._create_node(initial_piece_table, None, "initial")

    def _create_node(self, piece_table, parent_id, description):
        state_id = self._next_id
        self._next_id += 1
        node = UndoNode(state_id, piece_table, parent_id, description)
        self._nodes[state_id] = node
        if parent_id is not None and parent_id in self._nodes:
            self._nodes[parent_id].children_ids.append(state_id)
        return state_id

    @property
    def current_id(self):
        return self._current_id

    @property
    def current_state(self):
        return self._nodes[self._current_id].piece_table

    def record(self, piece_table, description=""):
        """Record a new state as a child of the current state.
        Returns the new state's ID."""
        state_id = self._create_node(piece_table, self._current_id, description)
        self._current_id = state_id
        return state_id

    def get_node(self, state_id):
        """Return the UndoNode for the given state ID."""
        return self._nodes[state_id]

    def can_undo(self):
        return self._nodes[self._current_id].parent_id is not None

    def can_redo(self):
        return len(self._nodes[self._current_id].children_ids) > 0

    def num_branches(self):
        """Number of redo branches from current state."""
        return len(self._nodes[self._current_id].children_ids)

    def undo(self):
        """Navigate to the parent state.
        Returns the parent's PieceTable, or None if already at root."""
        raise NotImplementedError("undo() not yet implemented")

    def redo(self, branch_index=0):
        """Navigate to a child state.
        branch_index selects which branch when there are multiple children.
        Returns the child's PieceTable, or None if no children or invalid index."""
        raise NotImplementedError("redo() not yet implemented")

    def navigate_to(self, target_id):
        """Navigate directly to any state in the undo tree.
        Returns the target state's PieceTable, or None if target_id is invalid."""
        raise NotImplementedError("navigate_to() not yet implemented")

    def get_path(self, from_id, to_id):
        """Find the path between two states through the undo tree.

        Returns a list of state IDs: [from_id, ..., lca_id, ..., to_id]
        where lca_id is their lowest common ancestor. The path goes up
        from from_id to the LCA, then down from the LCA to to_id.

        Returns None if either state ID is invalid.
        """
        raise NotImplementedError("get_path() not yet implemented")

    def get_all_states(self):
        return list(self._nodes.keys())

    def get_tree_structure(self):
        return {sid: list(n.children_ids) for sid, n in self._nodes.items()}
