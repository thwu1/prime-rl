# VT100 Terminal Emulator Specification

## Snapshot Format

The `snapshot()` method must return a dict with this structure:

```json
{
  "rows": 24,
  "cols": 80,
  "cursor": {"row": 0, "col": 0},
  "screen": [
    [{"char": " ", "fg": null, "bg": null, "bold": false, "underline": false, "reverse": false}, ...],
    ...
  ]
}
```

### Cell fields

| Field       | Type                          | Default | Description                            |
|-------------|-------------------------------|---------|----------------------------------------|
| `char`      | str (single character)        | `" "`   | The character displayed                |
| `fg`        | `null`, `int`, or `list[int]` | `null`  | Foreground color (see Color Encoding)  |
| `bg`        | `null`, `int`, or `list[int]` | `null`  | Background color (see Color Encoding)  |
| `bold`      | bool                          | `false` | Bold/bright attribute                  |
| `underline` | bool                          | `false` | Underline attribute                    |
| `reverse`   | bool                          | `false` | Reverse video attribute                |

### Color Encoding

- **Default color**: `null` (terminal default fg/bg)
- **8-color (SGR 30-37 / 40-47)**: integer `0`-`7` (0=black, 1=red, 2=green, 3=yellow, 4=blue, 5=magenta, 6=cyan, 7=white)
- **256-color (SGR 38;5;n / 48;5;n)**: integer `0`-`255`
- **RGB (SGR 38;2;r;g;b / 48;2;r;g;b)**: list `[r, g, b]` with ints 0-255

## Control Characters

| Byte   | Name | Behavior                                    |
|--------|------|---------------------------------------------|
| `0x07` | BEL  | Ignored (no audible bell)                   |
| `0x08` | BS   | Move cursor left by 1 (stops at column 0)   |
| `0x09` | HT   | Advance to next tab stop (every 8 columns)  |
| `0x0A` | LF   | Move cursor down; scroll if at region bottom |
| `0x0D` | CR   | Move cursor to column 0                     |
| `0x1B` | ESC  | Begin escape sequence                       |

## Escape Sequences

| Sequence | Name   | Behavior                                      |
|----------|--------|-----------------------------------------------|
| ESC `7`  | DECSC  | Save cursor position and attributes            |
| ESC `8`  | DECRC  | Restore saved cursor position and attributes   |
| ESC `[`  | CSI    | Begin Control Sequence Introducer              |

## CSI Sequences (ESC `[` params final)

Parameters are semicolon-separated integers. Missing parameters default to 0 or 1 depending on the command.

| Final | Name    | Params           | Behavior                                       |
|-------|---------|------------------|-------------------------------------------------|
| `H`/`f` | CUP  | `row;col` (1-indexed, default 1;1) | Move cursor to absolute position |
| `A`   | CUU    | `n` (default 1)  | Move cursor up n rows (clamp at row 0)          |
| `B`   | CUD    | `n` (default 1)  | Move cursor down n rows (clamp at last row)     |
| `C`   | CUF    | `n` (default 1)  | Move cursor right n columns (clamp at last col) |
| `D`   | CUB    | `n` (default 1)  | Move cursor left n columns (clamp at column 0)  |
| `J`   | ED     | `n` (default 0)  | Erase in display (see below)                    |
| `K`   | EL     | `n` (default 0)  | Erase in line (see below)                       |
| `m`   | SGR    | params           | Set graphic rendition (see below)               |
| `r`   | DECSTBM| `top;bottom` (1-indexed, default 1;rows) | Set scroll region; cursor moves to (0,0) |

### ED (Erase in Display) modes

- **0**: Erase from cursor position to end of display (inclusive of cursor cell)
- **1**: Erase from start of display to cursor position (inclusive of cursor cell)
- **2**: Erase entire display

### EL (Erase in Line) modes

- **0**: Erase from cursor to end of line (inclusive of cursor cell)
- **1**: Erase from start of line to cursor (inclusive of cursor cell)
- **2**: Erase entire line

Erased cells are reset to default attributes (space character, null colors, no bold/underline/reverse).

### SGR (Select Graphic Rendition)

| Code    | Effect                                     |
|---------|--------------------------------------------|
| 0       | Reset all attributes to defaults           |
| 1       | Bold on                                    |
| 4       | Underline on                               |
| 7       | Reverse video on                           |
| 22      | Bold off (normal intensity)                |
| 24      | Underline off                              |
| 27      | Reverse off                                |
| 30-37   | Set foreground to 8-color (value = code-30)|
| 39      | Set foreground to default (null)           |
| 40-47   | Set background to 8-color (value = code-40)|
| 49      | Set background to default (null)           |
| 38;5;n  | Set foreground to 256-color n              |
| 48;5;n  | Set background to 256-color n              |
| 38;2;r;g;b | Set foreground to RGB [r, g, b]         |
| 48;2;r;g;b | Set background to RGB [r, g, b]         |

Multiple SGR parameters in a single sequence accumulate (e.g., `ESC[1;31m` sets bold AND red foreground).

## DEC Private Modes

| Sequence            | Name          | Behavior                                   |
|---------------------|---------------|---------------------------------------------|
| CSI `?1049h`        | DECSET 1049   | Save main screen, switch to alt screen, clear alt screen, cursor to (0,0) |
| CSI `?1049l`        | DECRST 1049   | Switch back to main screen, restore cursor  |

## Deferred Line Wrapping

When a printable character is written at the last column (cols-1), the character is placed and a **pending wrap** flag is set. The cursor logically remains at the last column. Only the **next printable character** triggers the actual wrap: the cursor moves to column 0 of the next row (scrolling if needed), then the character is placed.

All explicit cursor movement commands (CUP, CUU, CUD, CUF, CUB), CR, and BS clear the pending wrap flag. SGR and other attribute-only sequences do NOT clear it.

## Scroll Regions

DECSTBM sets the top and bottom rows (1-indexed) of the scroll region. When the cursor is at the bottom of the scroll region and LF occurs, only the rows within the region scroll up. Rows outside the region are unaffected.

After DECSTBM, the cursor moves to position (0, 0).

## Tab Stops

Default tab stops are at every 8 columns (0, 8, 16, 24, ...). HT advances the cursor to the next tab stop, clamping at the last column.
