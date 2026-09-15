# PieceTable API

**Header**: `fredbuf/piece_table.h`
**Namespace**: `fredbuf`

## Class: `PieceTable`

A text buffer that represents document content as a sequence of pieces — each
piece is a reference into either the original text or an append-only add buffer.

### Constructors

- `PieceTable()` — empty buffer
- `PieceTable(const std::string& initial_text)` — buffer initialized with text

### Mutation

- `void insert(size_t offset, const std::string& text)`
  Insert `text` at character position `offset`. Appends to the add buffer
  and creates a new piece referencing it.

- `void erase(size_t offset, size_t length)`
  Remove `length` characters starting at `offset`. May split existing pieces.

### Query

- `std::string text() const` — full document text
- `size_t length() const` — total character count
- `size_t line_count() const` — number of lines
- `std::string line_at(size_t line_index) const` — text of line at 0-based index
- `size_t snapshot_id() const` — unique identifier for current buffer version
