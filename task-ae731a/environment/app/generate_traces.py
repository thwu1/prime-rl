#!/usr/bin/env python3
"""Generate binary trace files and expected JSON snapshots for validation."""

import json
import os

TRACES_DIR = '/app/traces'
EXPECTED_DIR = '/app/expected'

os.makedirs(TRACES_DIR, exist_ok=True)
os.makedirs(EXPECTED_DIR, exist_ok=True)


def write_trace(name, data, rows, cols, checks):
    with open(os.path.join(TRACES_DIR, f'{name}.bin'), 'wb') as f:
        f.write(data)
    with open(os.path.join(EXPECTED_DIR, f'{name}.json'), 'w') as f:
        json.dump({'rows': rows, 'cols': cols, 'checks': checks}, f, indent=2)


# Trace 1: Scroll region + deferred line wrapping interaction
# A pending wrap at the bottom of a scroll region should trigger
# region-local scrolling, not just move the cursor down.
def gen_region_wrap():
    seq = b''
    for i in range(8):
        seq += f'\x1b[{i+1};1HRow-{i}'.encode()
    seq += b'\x1b[4;7r'       # scroll region rows 3-6 (0-indexed)
    seq += b'\x1b[7;1H'       # cursor to (6, 0) - bottom of region
    seq += b'A' * 20          # fill 20 columns, sets pending wrap
    seq += b'X'               # resolves wrap -> should scroll region, place X

    # After correct execution:
    # Region scroll: row 3 deleted, rows 4-6 shift up, blank at row 6
    # X placed at (6, 0)
    checks = [
        {'type': 'row_text', 'row': 0, 'expected': 'Row-0'},
        {'type': 'row_text', 'row': 2, 'expected': 'Row-2'},
        {'type': 'row_text', 'row': 3, 'expected': 'Row-4'},
        {'type': 'row_text', 'row': 5, 'expected': 'AAAAAAAAAAAAAAAAAAAA'},
        {'type': 'row_text', 'row': 6, 'expected': 'X'},
        {'type': 'row_text', 'row': 7, 'expected': 'Row-7'},
        {'type': 'cursor', 'row': 6, 'col': 1},
    ]
    write_trace('region_wrap', seq, 8, 20, checks)


# Trace 2: ED mode 1 (erase above) boundary at cursor position
# The cursor cell itself must be erased (inclusive).
def gen_erase_above():
    seq = b''
    seq += b'\x1b[1;1H' + b'A' * 20   # row 0: all A's
    seq += b'\x1b[2;1H' + b'B' * 20   # row 1: all B's
    seq += b'\x1b[3;1H' + b'C' * 20   # row 2: all C's
    seq += b'\x1b[2;8H'               # cursor to (1, 7)
    seq += b'\x1b[1J'                 # ED mode 1: erase from start to cursor

    # Correct: row 0 fully erased. Row 1 cols 0-7 erased (inclusive).
    # Row 1 col 7 should be space, not 'B'.
    checks = [
        {'type': 'row_text', 'row': 0, 'expected': ''},
        {'type': 'cell_attr', 'row': 1, 'col': 7, 'attrs': {'char': ' '}},
        {'type': 'cell_attr', 'row': 1, 'col': 8, 'attrs': {'char': 'B'}},
        {'type': 'row_text', 'row': 2, 'expected': 'CCCCCCCCCCCCCCCCCCCC'},
    ]
    write_trace('erase_above', seq, 5, 20, checks)


# Trace 3: SGR 256-color followed by another SGR in the same sequence
# E.g. ESC[38;5;196;1m should set fg=196 AND bold=True
def gen_sgr_chain():
    seq = b''
    seq += b'\x1b[38;5;196;1mBoldRed\x1b[0m'
    seq += b'\x1b[2;1H'
    seq += b'\x1b[48;5;21;4mUndrBlu\x1b[0m'

    checks = [
        {'type': 'cell_attr', 'row': 0, 'col': 0,
         'attrs': {'char': 'B', 'fg': 196, 'bold': True}},
        {'type': 'cell_attr', 'row': 0, 'col': 6,
         'attrs': {'char': 'd', 'fg': 196, 'bold': True}},
        {'type': 'cell_attr', 'row': 1, 'col': 0,
         'attrs': {'char': 'U', 'bg': 21, 'underline': True}},
        {'type': 'cell_attr', 'row': 1, 'col': 6,
         'attrs': {'char': 'u', 'bg': 21, 'underline': True}},
    ]
    write_trace('sgr_chain', seq, 5, 40, checks)


# Trace 4: DECSC/DECRC should save and restore SGR attributes, not just position
def gen_save_restore():
    seq = b''
    seq += b'\x1b[1;31m'       # bold + red fg
    seq += b'\x1b[3;6H'        # cursor to (2, 5)
    seq += b'STYLED'           # write with bold red
    seq += b'\x1b7'            # DECSC: save cursor (and attrs)
    seq += b'\x1b[0m'          # reset attrs
    seq += b'\x1b[1;1H'        # cursor to (0, 0)
    seq += b'PLAIN'            # write with default attrs
    seq += b'\x1b8'            # DECRC: restore cursor (and attrs)
    seq += b'MORE'             # should use restored bold red attrs

    # "STYLED" at (2,5-10): fg=1, bold=True
    # "PLAIN" at (0,0-4): fg=None, bold=False
    # "MORE" at (2,11-14): fg=1, bold=True (restored)
    checks = [
        {'type': 'cell_attr', 'row': 2, 'col': 5,
         'attrs': {'char': 'S', 'fg': 1, 'bold': True}},
        {'type': 'cell_attr', 'row': 0, 'col': 0,
         'attrs': {'char': 'P', 'fg': None, 'bold': False}},
        {'type': 'cell_attr', 'row': 2, 'col': 11,
         'attrs': {'char': 'M', 'fg': 1, 'bold': True}},
        {'type': 'cell_attr', 'row': 2, 'col': 14,
         'attrs': {'char': 'E', 'fg': 1, 'bold': True}},
        {'type': 'cursor', 'row': 2, 'col': 15},
    ]
    write_trace('save_restore', seq, 5, 40, checks)


# Trace 5: Switching to alt screen should reset scroll region to full screen
def gen_alt_region():
    seq = b''
    seq += b'\x1b[3;7r'        # set scroll region rows 2-6 (0-indexed)
    seq += b'\x1b[?1049h'      # switch to alt screen
    seq += b'\x1b[1;1HTOP'     # write "TOP" at row 0
    seq += b'\x1b[10;1HBOTTOM' # write "BOTTOM" at row 9
    seq += b'\n'               # LF at bottom row

    # Correct (region reset): LF at row 9 == scroll_bottom(9) -> full scroll
    #   Row 0 ("TOP") scrolls off. "BOTTOM" shifts to row 8.
    # Buggy (region preserved from main): LF at row 9 != scroll_bottom(6),
    #   nothing happens. "TOP" stays at row 0.
    checks = [
        {'type': 'row_text', 'row': 0, 'expected': ''},
        {'type': 'row_text', 'row': 8, 'expected': 'BOTTOM'},
        {'type': 'row_text', 'row': 9, 'expected': ''},
    ]
    write_trace('alt_region', seq, 10, 20, checks)


# Trace 6: CUP 'f' variant (CSI row;col f) should work like CSI row;col H
def gen_cup_f():
    seq = b''
    seq += b'\x1b[3;10f'       # CUP using 'f' final byte
    seq += b'HERE'

    # Correct: "HERE" at row 2, cols 9-12. Cursor at (2, 13).
    # Buggy: 'f' not recognized, cursor stays at (0,0), "HERE" at (0,0-3).
    checks = [
        {'type': 'cell_attr', 'row': 2, 'col': 9, 'attrs': {'char': 'H'}},
        {'type': 'cell_attr', 'row': 2, 'col': 12, 'attrs': {'char': 'E'}},
        {'type': 'row_text', 'row': 0, 'expected': ''},
        {'type': 'cursor', 'row': 2, 'col': 13},
    ]
    write_trace('cup_f', seq, 5, 20, checks)


if __name__ == '__main__':
    gen_region_wrap()
    gen_erase_above()
    gen_sgr_chain()
    gen_save_restore()
    gen_alt_region()
    gen_cup_f()
    print(f"Generated {len(os.listdir(TRACES_DIR))} traces in {TRACES_DIR}")
    print(f"Generated {len(os.listdir(EXPECTED_DIR))} expected files in {EXPECTED_DIR}")
