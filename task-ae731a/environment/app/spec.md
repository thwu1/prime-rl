# VT100 Terminal Emulator — Protocol Reference

This document covers the escape sequences handled by the terminal emulator.
For authoritative behavior on edge cases, consult ECMA-48 or `infocmp xterm-256color`.

## Snapshot Format

The `snapshot()` method returns a dict:

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

### Cell Fields

| Field       | Type                          | Default | Description                            |
|-------------|-------------------------------|---------|----------------------------------------|
| `char`      | str (single character)        | `" "`   | The character displayed                |
| `fg`        | `null`, `int`, or `list[int]` | `null`  | Foreground color                       |
| `bg`        | `null`, `int`, or `list[int]` | `null`  | Background color                       |
| `bold`      | bool                          | `false` | Bold/bright attribute                  |
| `underline` | bool                          | `false` | Underline attribute                    |
| `reverse`   | bool                          | `false` | Reverse video attribute                |

### Color Encoding

- **Default**: `null`
- **8-color** (SGR 30–37 / 40–47): integer `0`–`7`
- **256-color** (SGR 38;5;n / 48;5;n): integer `0`–`255`
- **RGB** (SGR 38;2;r;g;b / 48;2;r;g;b): list `[r, g, b]`

## Control Characters

| Byte   | Name | Behavior                                      |
|--------|------|-----------------------------------------------|
| `0x07` | BEL  | Ignored                                       |
| `0x08` | BS   | Move cursor left by 1 (stops at column 0)     |
| `0x09` | HT   | Advance to next tab stop (every 8 columns)    |
| `0x0A` | LF   | Move cursor down; scroll if at region bottom  |
| `0x0D` | CR   | Move cursor to column 0                       |
| `0x1B` | ESC  | Begin escape sequence                         |

## Escape Sequences

| Sequence | Name   | Behavior                                        |
|----------|--------|-------------------------------------------------|
| ESC `7`  | DECSC  | Save cursor position and SGR attributes         |
| ESC `8`  | DECRC  | Restore cursor position and SGR attributes      |
| ESC `[`  | CSI    | Begin Control Sequence Introducer                |

## CSI Sequences (ESC `[` params final-byte)

Parameters are semicolon-separated integers. Missing parameters default per command.

| Final | Name    | Params             | Default   | Behavior                               |
|-------|---------|--------------------|-----------|-----------------------------------------|
| `H`   | CUP    | `row;col` (1-idx)  | `1;1`     | Move cursor to absolute position        |
| `f`   | HVP    | `row;col` (1-idx)  | `1;1`     | Move cursor (identical to CUP)          |
| `A`   | CUU    | `n`                | `1`       | Move cursor up n rows                   |
| `B`   | CUD    | `n`                | `1`       | Move cursor down n rows                 |
| `C`   | CUF    | `n`                | `1`       | Move cursor right n columns             |
| `D`   | CUB    | `n`                | `1`       | Move cursor left n columns              |
| `J`   | ED     | `n`                | `0`       | Erase in display                        |
| `K`   | EL     | `n`                | `0`       | Erase in line                           |
| `m`   | SGR    | params             | `0`       | Set graphic rendition                   |
| `r`   | DECSTBM| `top;bottom`(1-idx)| `1;rows`  | Set scrolling region; cursor -> (0,0)   |

### ED (Erase in Display)

- **0**: Erase from cursor to end of display (cursor cell included)
- **1**: Erase from start of display to cursor (cursor cell included)
- **2**: Erase entire display

Erased cells get default attributes.

### EL (Erase in Line)

- **0**: Erase from cursor to end of line (cursor cell included)
- **1**: Erase from start of line to cursor (cursor cell included)
- **2**: Erase entire line

### SGR (Select Graphic Rendition)

| Code      | Effect                                     |
|-----------|--------------------------------------------|
| 0         | Reset all attributes                       |
| 1         | Bold on                                    |
| 4         | Underline on                               |
| 7         | Reverse video on                           |
| 22        | Bold off                                   |
| 24        | Underline off                              |
| 27        | Reverse off                                |
| 30-37     | Set foreground (value = code - 30)         |
| 39        | Default foreground                         |
| 40-47     | Set background (value = code - 40)         |
| 49        | Default background                         |
| 38;5;n    | 256-color foreground                       |
| 48;5;n    | 256-color background                       |
| 38;2;r;g;b| RGB foreground                             |
| 48;2;r;g;b| RGB background                             |

Multiple SGR codes in one sequence accumulate (e.g., `ESC[1;31m` = bold + red).

## DEC Private Modes

| Sequence         | Behavior                                           |
|------------------|----------------------------------------------------|
| CSI `?1049h`     | Switch to alternate screen buffer, clear it         |
| CSI `?1049l`     | Switch back to main screen buffer                   |

## Deferred Line Wrapping

When a character is placed at the last column, the cursor stays at that column with a
pending-wrap flag. The next printable character resolves the wrap: cursor moves to column 0
of the next line (scrolling if needed), then the character is placed.

Cursor movement commands (CUP, CUU, CUD, CUF, CUB), CR, and BS clear the pending-wrap flag.

## Scroll Regions

DECSTBM sets the scrolling region. LF at the bottom of the region scrolls only those rows.
Rows outside the region are unaffected.

## Tab Stops

Default tab stops at every 8 columns (0, 8, 16, 24, ...). HT advances to the next stop.
