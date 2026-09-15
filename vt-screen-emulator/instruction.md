Implement a VT-420 terminal emulator at `/app/vt_server.py` that operates as a process-level protocol server. It reads raw escape sequences byte-by-byte from stdin, maintains an internal screen buffer, and responds to DECRQCRA checksum queries by writing DCS responses to stdout. The server is launched via PTY by the test driver at `/app/test_driver.py` as `python3 /app/vt_server.py <cols> <rows>`.

The server must parse CSI sequences from the raw byte stream in the standard format `ESC [ <prefix?> <params> <intermediate?> <final>` where parameters are semicolon-separated decimal integers, the optional prefix byte is `?` (0x3F), intermediate bytes are in range 0x20–0x2F (notably `$` = 0x24 and `*` = 0x2A), and the final byte is in range 0x40–0x7E. It must also handle two-byte escape sequences `ESC D` (IND) and `ESC M` (RI).

**Supported CSI commands** (parameters shown positionally; defaults are 1 or screen-dimension for bounds):

| Command | Sequence | Notes |
|---------|----------|-------|
| CUP | `CSI row;col H` | Cursor position (1-based) |
| ED | `CSI mode J` | Erase display (mode 2 = all) |
| DECSTBM | `CSI top;bot r` | Set scroll margins; no params resets; always homes cursor |
| DECCRA | `CSI st;sl;sb;sr;sp;dt;dl;dp $ v` | Copy rect area — snapshot semantics required |
| DECFRA | `CSI ch;t;l;b;r $ x` | Fill rect with character ordinal |
| DECERA | `CSI t;l;b;r $ z` | Erase (zero-fill) rect |
| DECRQCRA | `CSI pid;pg;t;l;b;r * y` | Request checksum — must emit DCS response |
| DECSET DECOM | `CSI ? 6 h` | Enable origin mode, home cursor |
| DECRESET DECOM | `CSI ? 6 l` | Disable origin mode |

**DCS response format for DECRQCRA**: Write `ESC P <pid> ! ~ <HEX> ESC \` to stdout, where `<HEX>` is the uppercase zero-padded 4-digit hex checksum.

**Screen buffer semantics**:
- Cells initialized to 0 (NUL). DECRQCRA = sum of ordinals in the rectangle, mod 65536.
- DECCRA must snapshot the entire source rectangle before writing to the destination — naive cell-by-cell copying produces wrong results when source and destination overlap.
- IND (`ESC D`) at the bottom scroll margin scrolls the margin region up (top line lost, blank inserted at bottom). RI (`ESC M`) at the top margin scrolls down. Away from the respective margin boundary, they just move the cursor vertically.
- In origin mode (DECOM), CUP row coordinates are relative to the top scroll margin (row 1 in origin mode = top margin row in absolute terms).
- All coordinates are 1-based and inclusive. Omitted parameters default to 1 (or screen dimension for bottom/right bounds).