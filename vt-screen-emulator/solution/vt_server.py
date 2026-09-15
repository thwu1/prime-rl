#!/usr/bin/env python3
"""
VT-420 Terminal Emulator — Protocol Server

Reads raw escape sequences byte-by-byte from stdin, maintains an
internal screen buffer, and responds to DECRQCRA queries by writing
DCS responses to stdout.

Launched as:  python3 vt_server.py <cols> <rows>

Escape sequence grammar handled:
  CSI = ESC [
  CSI <prefix?> <params> <intermediate?> <final>
  ESC D  → IND (Index)
  ESC M  → RI  (Reverse Index)
"""

import os
import select
import sys

# ────────────────────────── configuration ──────────────────────────

cols = int(sys.argv[1]) if len(sys.argv) > 1 else 80
rows = int(sys.argv[2]) if len(sys.argv) > 2 else 24

# ────────────────────────── screen state ──────────────────────────

screen = [[0] * cols for _ in range(rows)]
cursor_row = 0          # 0-based
cursor_col = 0          # 0-based
margin_top = 0          # 0-based inclusive
margin_bottom = rows - 1  # 0-based inclusive
origin_mode = False

# ───────────────────────── output helper ──────────────────────────

def _write_out(data):
    """Write string to stdout (fd 1), bypassing Python buffering."""
    os.write(1, data.encode("latin-1"))

# ────────────────────────── VT operations ─────────────────────────

def put_char(ch):
    global cursor_col
    if cursor_col < cols:
        screen[cursor_row][cursor_col] = ord(ch)
        cursor_col += 1


def do_cup(params):
    global cursor_row, cursor_col
    row = (params[0] if params else 1) or 1
    col = (params[1] if len(params) > 1 else 1) or 1
    if origin_mode:
        row = row + margin_top   # origin-relative → absolute
    cursor_row = max(0, min(rows - 1, row - 1))
    cursor_col = max(0, min(cols - 1, col - 1))


def do_ed(params):
    mode = params[0] if params else 0
    if mode == 2:
        for r in range(rows):
            for c in range(cols):
                screen[r][c] = 0


def do_decstbm(params):
    global margin_top, margin_bottom, cursor_row, cursor_col
    top = (params[0] if params else 1) or 1
    bottom = (params[1] if len(params) > 1 else rows) or rows
    margin_top = top - 1
    margin_bottom = bottom - 1
    cursor_row = 0
    cursor_col = 0


def do_ind():
    global cursor_row
    if cursor_row == margin_bottom:
        # Scroll up within margins
        for r in range(margin_top, margin_bottom):
            screen[r] = screen[r + 1][:]
        screen[margin_bottom] = [0] * cols
    elif cursor_row < rows - 1:
        cursor_row += 1


def do_ri():
    global cursor_row
    if cursor_row == margin_top:
        # Scroll down within margins
        for r in range(margin_bottom, margin_top, -1):
            screen[r] = screen[r - 1][:]
        screen[margin_top] = [0] * cols
    elif cursor_row > 0:
        cursor_row -= 1


def do_deccra(params):
    src_top   = (params[0] if len(params) > 0 else 1) or 1
    src_left  = (params[1] if len(params) > 1 else 1) or 1
    src_bot   = (params[2] if len(params) > 2 else rows) or rows
    src_right = (params[3] if len(params) > 3 else cols) or cols
    # params[4] = src_page (ignored)
    dst_top   = (params[5] if len(params) > 5 else 1) or 1
    dst_left  = (params[6] if len(params) > 6 else 1) or 1
    # params[7] = dst_page (ignored)

    h = src_bot - src_top + 1
    w = src_right - src_left + 1

    # Snapshot semantics: capture entire source before writing
    snapshot = []
    for r in range(h):
        row_data = []
        for c in range(w):
            sr = src_top - 1 + r
            sc = src_left - 1 + c
            if 0 <= sr < rows and 0 <= sc < cols:
                row_data.append(screen[sr][sc])
            else:
                row_data.append(0)
        snapshot.append(row_data)

    for r in range(h):
        for c in range(w):
            dr = dst_top - 1 + r
            dc = dst_left - 1 + c
            if 0 <= dr < rows and 0 <= dc < cols:
                screen[dr][dc] = snapshot[r][c]


def do_decfra(params):
    char_code = (params[0] if len(params) > 0 else 0) or 0
    top   = (params[1] if len(params) > 1 else 1) or 1
    left  = (params[2] if len(params) > 2 else 1) or 1
    bot   = (params[3] if len(params) > 3 else rows) or rows
    right = (params[4] if len(params) > 4 else cols) or cols
    for r in range(top - 1, min(bot, rows)):
        for c in range(left - 1, min(right, cols)):
            screen[r][c] = char_code


def do_decera(params):
    top   = (params[0] if len(params) > 0 else 1) or 1
    left  = (params[1] if len(params) > 1 else 1) or 1
    bot   = (params[2] if len(params) > 2 else rows) or rows
    right = (params[3] if len(params) > 3 else cols) or cols
    for r in range(top - 1, min(bot, rows)):
        for c in range(left - 1, min(right, cols)):
            screen[r][c] = 0


def do_decrqcra(params):
    pid   = params[0] if len(params) > 0 else 0
    # params[1] = page (ignored)
    top   = (params[2] if len(params) > 2 else 1) or 1
    left  = (params[3] if len(params) > 3 else 1) or 1
    bot   = (params[4] if len(params) > 4 else rows) or rows
    right = (params[5] if len(params) > 5 else cols) or cols

    checksum = 0
    for r in range(top - 1, min(bot, rows)):
        for c in range(left - 1, min(right, cols)):
            checksum += screen[r][c]
    checksum %= 65536

    hexval = format(checksum, "04X")
    _write_out(f"\x1bP{pid}!~{hexval}\x1b\\")


def do_decset(params):
    global origin_mode
    mode = params[0] if params else 0
    if mode == 6:
        origin_mode = True
        do_cup([1, 1])


def do_decreset(params):
    global origin_mode
    mode = params[0] if params else 0
    if mode == 6:
        origin_mode = False

# ─────────────────────── parameter parser ─────────────────────────

def parse_params(param_str):
    """Parse semicolon-separated CSI parameter string → list of ints."""
    if not param_str:
        return []
    result = []
    for p in param_str.split(";"):
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    return result

# ──────────────────────── CSI dispatcher ──────────────────────────

def dispatch_csi(prefix, params_str, intermediate, final):
    params = parse_params(params_str)

    if prefix == "?" and final == "h":
        do_decset(params)
    elif prefix == "?" and final == "l":
        do_decreset(params)
    elif final == "H" and not intermediate:
        do_cup(params)
    elif final == "J" and not intermediate:
        do_ed(params)
    elif final == "r" and not intermediate:
        do_decstbm(params)
    elif final == "v" and intermediate == "$":
        do_deccra(params)
    elif final == "x" and intermediate == "$":
        do_decfra(params)
    elif final == "z" and intermediate == "$":
        do_decera(params)
    elif final == "y" and intermediate == "*":
        do_decrqcra(params)

# ──────────────────── byte-level state machine ────────────────────

STATE_GROUND     = 0
STATE_ESC        = 1
STATE_CSI_ENTRY  = 2
STATE_CSI_PARAMS = 3

state = STATE_GROUND
csi_prefix = ""
csi_params = ""
csi_intermediate = ""


def process_byte(b):
    global state, csi_prefix, csi_params, csi_intermediate
    global cursor_col

    ch = chr(b)

    if state == STATE_GROUND:
        if b == 0x1B:                   # ESC
            state = STATE_ESC
        elif b == 0x0A:                 # LF → IND
            do_ind()
        elif b == 0x0D:                 # CR
            cursor_col = 0
        elif b >= 0x20:                 # printable
            put_char(ch)

    elif state == STATE_ESC:
        if ch == "[":                   # CSI introducer
            state = STATE_CSI_ENTRY
            csi_prefix = ""
            csi_params = ""
            csi_intermediate = ""
        elif ch == "D":                 # IND
            do_ind()
            state = STATE_GROUND
        elif ch == "M":                 # RI
            do_ri()
            state = STATE_GROUND
        else:
            state = STATE_GROUND        # unrecognised → ignore

    elif state == STATE_CSI_ENTRY:
        # First byte after ESC [
        if ch == "?":
            csi_prefix = "?"
            state = STATE_CSI_PARAMS
        elif ch.isdigit() or ch == ";":
            csi_params += ch
            state = STATE_CSI_PARAMS
        elif 0x20 <= b <= 0x2F:         # intermediate byte
            csi_intermediate += ch
            state = STATE_CSI_PARAMS
        elif 0x40 <= b <= 0x7E:         # final byte (no params)
            dispatch_csi(csi_prefix, csi_params, csi_intermediate, ch)
            state = STATE_GROUND
        else:
            state = STATE_GROUND

    elif state == STATE_CSI_PARAMS:
        if ch.isdigit() or ch == ";":
            csi_params += ch
        elif 0x20 <= b <= 0x2F:         # intermediate byte
            csi_intermediate += ch
        elif 0x40 <= b <= 0x7E:         # final byte → dispatch
            dispatch_csi(csi_prefix, csi_params, csi_intermediate, ch)
            state = STATE_GROUND
        else:
            state = STATE_GROUND        # invalid → abort sequence

# ──────────────────────── main read loop ──────────────────────────

def main():
    stdin_fd = sys.stdin.fileno()
    while True:
        try:
            r, _, _ = select.select([stdin_fd], [], [], 1.0)
            if r:
                data = os.read(stdin_fd, 4096)
                if not data:
                    break
                for b in data:
                    process_byte(b)
        except (OSError, IOError):
            break


if __name__ == "__main__":
    main()
