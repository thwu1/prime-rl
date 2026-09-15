Build a terminal screen diff system at `/app/` consisting of two Python modules.

## `/app/diff_engine.py`

Implement `compute_diff(prev: Screen, curr: Screen) -> bytes`.

This function receives two `Screen` objects of the same dimensions and returns ANSI escape sequence bytes that transform `prev` into `curr`. When the returned bytes are processed by a `VTParser` initialized with a clone of `prev`, the resulting screen must be identical to `curr`:

- Every cell's character must match
- Every cell's attributes must match (all six fields: `fg`, `bg`, `bold`, `italic`, `underline`, `inverse`)
- Cursor must be at `(curr.cursor_row, curr.cursor_col)`

The VTParser begins with default drawing attributes (`Attrs()`) and the cursor at `(prev.cursor_row, prev.cursor_col)`.

The diff must be efficient — significantly smaller than `render_full(curr)` for localized changes:

| Scenario | Max ratio (diff size / full-redraw size) |
|---|---|
| Sparse: ≤5 scattered cells changed on a full 24×80 text screen | < 10% |
| Single-row: one row updated on a full 24×80 text screen | < 25% |
| Half-screen: bottom 12 rows changed with per-row coloring | < 70% |

For identical screens, the diff must be under 50 bytes.

## `/app/tmux_validator.py`

Implement `validate_via_tmux(prev: Screen, diff_bytes: bytes) -> Screen`.

This function validates a diff through a live tmux terminal session. It must create a temporary tmux pane with dimensions matching `prev` (`prev.rows` rows × `prev.cols` columns), render `prev`'s complete screen state into it, apply `diff_bytes` through tmux's terminal emulator, then capture the resulting screen state — including character content, text attributes (fg, bg, bold, italic, underline, inverse), and cursor position — as a `Screen` object. The tmux session must be cleaned up before the function returns.

tmux is installed at `/usr/bin/tmux`. No tmux server may be running when the function is first called.

## Infrastructure

`/app/terminal.py` provides the complete terminal model and parser. Read this file to understand:
- `Screen`, `Cell`, `Attrs` data classes and their fields
- `VTParser` — the escape sequence parser, including every sequence it supports
- `render_full(screen)` — generates escape sequences that reproduce a screen from scratch (used as the full-redraw baseline for efficiency comparison)