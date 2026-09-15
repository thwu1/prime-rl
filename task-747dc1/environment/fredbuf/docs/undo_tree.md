# UndoTree API

**Header**: `fredbuf/undo_tree.h`
**Namespace**: `fredbuf`

## Class: `UndoTree`

Wraps a `PieceTable` and maintains a branching undo/redo history. Each
`commit()` creates a new history node. Undoing and then committing a new
edit preserves the old redo branch — forming a tree of edit histories.

### Text Operations (delegated to internal PieceTable)

- `void insert(size_t offset, const std::string& text)`
- `void erase(size_t offset, size_t length)`
- `std::string text() const`

### History Management

- `void commit()` — snapshot current buffer state as a new history node
- `void undo()` — move to parent history node, restoring its buffer state
- `void redo(size_t branch_index)` — move to the child at `branch_index`

### History Query

- `size_t current_snapshot_id() const` — ID of the current history node
- `size_t history_node_count() const` — total number of history nodes
- `size_t branches_at(size_t snapshot_id) const` — number of child branches
  at the given snapshot
- `void checkout(size_t snapshot_id)` — jump to any historical snapshot
- `std::string text_at(size_t snapshot_id) const` — retrieve text at any
  historical snapshot without changing current position
