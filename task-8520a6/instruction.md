A text editor engine at `/app/` is maintained as a git repository with development history. It consists of `buffer.py`, `history.py`, `differ.py`, `session_store.py`, and `editor_engine.py`. A SQLite database at `/app/sessions.db` stores recorded editing sessions.

The engine has defects and unfinished features. The corrected engine must satisfy all of the following:

**Buffer**: `PieceTable(text)` creates a buffer. `.insert(offset, text)` and `.delete(offset, length)` each return a new `PieceTable`. Every previously returned instance must remain independently readable — retrieving text from any earlier version must always yield the same result, regardless of later operations on any derived version.

**History**: `UndoTree(text)` manages document states. `.apply_insert()` and `.apply_delete()` create new states. `.undo()` returns to the parent state. History must support branching — performing an edit after undo must not discard any reachable state. `.redo(branch_index)` selects among child branches. `.get_tree_structure()` returns `{"id": int, "children": [...]}`. `.get_node_text(node_id)` retrieves the text at any historical state. `.get_children_count()` returns the number of children of the current node.

**Diff**: `myers_diff(text_a, text_b)` returns a line-based edit script where each entry is prefixed `' '` (kept), `'-'` (removed), or `'+'` (added). The script must be optimal — minimum total insertions plus deletions to transform `text_a` into `text_b`.

**Merge**: `UndoTree.merge_branches(node_id_a, node_id_b) -> int` merges two branch tips. The merge base is the text at their lowest common ancestor in the undo tree. Non-conflicting changes from either branch are accepted. Identical changes to the same region are deduplicated. Different changes to the same region produce `<<<<<<< branch_a` / `=======` / `>>>>>>> branch_b` markers. The merged node becomes a child of the common ancestor. Returns the new node's ID.

**Session Store**: `SessionStore(db_path)` interfaces with the SQLite database. It must support listing sessions, replaying a session's recorded operations into an `UndoTree`, and recording new operations. `replay_session` raises `KeyError` for unknown session IDs.

All exports in `editor_engine.py` (`PieceTable`, `UndoTree`, `myers_diff`, `SessionStore`) must be preserved.