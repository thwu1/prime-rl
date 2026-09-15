# Rasterizer Specification

## Overview

The rasterizer converts a flat grid of composited cells (produced by
`composite_scene()`) into a byte stream of ANSI escape sequences. When
this byte stream is written to a terminal, the terminal must display
the exact visual content represented by the cell grid.

Two operations are required:

1. **Full render** (`rasterize_full`): convert an entire cell grid.
2. **Differential render** (`rasterize_diff`): emit only the changes
   between a previous and current cell grid.

Both functions append output to a pre-initialized `raster_buf_t`.

## ANSI Escape Sequence Reference

All sequences use the CSI (Control Sequence Introducer) format: `ESC [`.
In C source, ESC is `\x1b` or `\033`.

### CUP — Cursor Position

`\033[<row>;<col>H`

Moves the cursor to an absolute position. Row and column are **1-indexed**.
Example: `\033[3;5H` positions the cursor at row 3, column 5.

### SGR — Select Graphic Rendition

`\033[<param1>;<param2>;...m`

Sets display attributes. Multiple parameters are semicolon-separated
and processed left to right.

| Code | Meaning |
|------|---------|
| 0 | Reset all attributes to defaults |
| 1 | Bold on |
| 3 | Italic on |
| 4 | Underline on |
| 9 | Strikethrough on |
| 22 | Bold off |
| 23 | Italic off |
| 24 | Underline off |
| 29 | Strikethrough off |
| 38;2;R;G;B | Set foreground color to 24-bit RGB |
| 39 | Reset foreground to terminal default |
| 48;2;R;G;B | Set background color to 24-bit RGB |
| 49 | Reset background to terminal default |

Parameters may be combined in a single sequence:
`\033[0;1;38;2;255;0;0m` resets all, enables bold, sets fg to red.

### Style flag mapping

The composited cell's `style` field uses these bitmask values:

| Flag | Value | SGR on | SGR off |
|------|-------|--------|---------|
| STRUCK | 0x0001 | 9 | 29 |
| BOLD | 0x0002 | 1 | 22 |
| UNDERCURL | 0x0004 | 4 | 24 |
| UNDERLINE | 0x0008 | 4 | 24 |
| ITALIC | 0x0010 | 3 | 23 |

UNDERCURL and UNDERLINE both map to SGR 4 (on) and SGR 24 (off).

### Character output

Any printable character written to the terminal appears at the current
cursor position and advances the cursor one column to the right.

## Terminal state model

The terminal starts in the default state:
- Cursor at row 1, column 1
- Foreground color: default (represented as RGB -1,-1,-1)
- Background color: default (represented as RGB -1,-1,-1)
- All style attributes off (style mask = 0)
- All cells contain space (' ') with default colors and no styles

Writing a character to a cell **only changes that cell**. It does not
affect any other cell's appearance. SGR commands change the *drawing
state* (what future characters look like), not existing cells.

## rasterize_full() specification

Convert the entire cell grid to escape sequences.

### Requirements

1. Output **MUST** begin with `\033[0m` (full reset).
2. For each row containing visible content, emit a CUP sequence to
   position the cursor, then emit cells left-to-right. For each cell,
   emit any necessary SGR changes before the character.
3. Output **MUST** end with `\033[0m` (full reset).

### Optimization requirements

a. **SGR state tracking**: Do not emit SGR parameters for attributes
   that already match the terminal's current drawing state. For example,
   if the current foreground is already (255,0,0), do not emit
   `38;2;255;0;0` again for the next cell.

b. **SGR combining**: When multiple SGR changes are needed for a single
   cell, combine them into one `\033[...m` sequence rather than emitting
   separate sequences.

c. **Trailing trim**: Do not emit trailing cells in a row that are
   plain spaces (' ') with default foreground, default background, and
   no style attributes. The terminal already has spaces in those
   positions by default.

## rasterize_diff() specification

Emit escape sequences that transform a terminal currently showing `prev`
into one showing `curr`. Only cells that differ between the two frames
should generate output.

### Requirements

1. Output **MUST** begin and end with `\033[0m` (reset).
2. For each cell that differs between prev and curr, use CUP to position
   the cursor and emit the updated cell with correct SGR.
3. Cells that are identical in prev and curr **MUST NOT** generate any
   character output.
4. When consecutive changed cells are adjacent on the same row, rely on
   implicit cursor advance instead of emitting CUP for each one.

### Optimization requirements

a. **Minimal output**: The diff output for a frame with few changed
   cells must be substantially smaller than a full render of curr.

b. **SGR state tracking**: Same as full render — do not emit redundant
   SGR sequences.

## Correctness requirement

The escape sequence output, when played through a standard VT state
machine, must produce a terminal state that exactly matches the
composited cell grid. Every cell's character, foreground color (or
default), background color (or default), and style mask must match.
