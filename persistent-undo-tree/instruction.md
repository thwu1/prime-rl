A partially-implemented text editor buffer system is at `/app/`. It uses an immutable piece table as its core text representation, enabling a branching undo/redo history where all past editing states are preserved through structural sharing.

The system has four modules:

- `/app/piece_table.py` -- Immutable piece table. Each insert/delete returns a new PieceTable instance; the original is unchanged. **Complete and working.**
- `/app/undo_tree.py` -- Tree-structured undo/redo history. Records editing states as nodes in a tree with parent-child relationships. Branching occurs when the user undoes, then makes a different edit. Core navigation methods (`undo`, `redo`, `navigate_to`, `get_path`) are stubbed.
- `/app/myers_diff.py` -- Myers diff algorithm for computing the shortest edit script between two strings. Entirely stubbed.
- `/app/text_buffer.py` -- Main API combining piece table and undo tree. `insert`, `delete`, `get_text` work. Methods `get_state_text` and `diff` are stubbed, and `undo`/`redo`/`navigate_to` delegate to the undo tree (which is also stubbed).

Complete the implementation so all tests pass. Key requirements:

- **Undo/redo** navigates up/down the undo tree. Redo accepts a `branch_index` to select among multiple branches.
- **`get_path(from_id, to_id)`** returns the sequence of state IDs from `from_id` up to the lowest common ancestor, then down to `to_id`.
- **Myers diff** must produce a minimal edit script as a list of `('equal'|'delete'|'insert', char)` tuples that, when applied, transforms the first string into the second.
- **`diff(state_a, state_b)`** computes the Myers diff between the text content of two arbitrary states in the undo tree.

Tests are at `/tests/test_state.py`.