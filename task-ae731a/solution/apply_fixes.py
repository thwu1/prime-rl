#!/usr/bin/env python3

"""
Apply all six fixes to the buggy terminal emulator.

Bug 1: _put_char resolves pending wrap by manually incrementing cursor_row
        instead of calling _linefeed(), breaking scroll-region-aware wrapping.
Bug 2: _erase_display mode 1 uses range(self.cursor_col) instead of
        range(self.cursor_col + 1), making the erase exclusive of cursor cell.
Bug 3: _handle_sgr advances i by 3 (256-color) / 5 (RGB) instead of 2 / 4,
        causing the loop's i+=1 to skip the next SGR parameter.
Bug 4: DECSC/DECRC only saves/restores cursor position, not SGR attributes.
Bug 5: Alt screen switch (CSI ?1049h) doesn't reset scroll region.
Bug 6: CUP only recognizes 'H' final byte, not the 'f' variant.
"""

import sys

path = '/app/terminal_emulator.py'

with open(path, 'r') as f:
    code = f.read()

original = code

# --- Fix 1: Pending wrap must use _linefeed() for scroll-aware behavior ---
old_1 = """\
        if self.pending_wrap:
            self.cursor_col = 0
            if self.cursor_row < self.rows - 1:
                self.cursor_row += 1
            self.pending_wrap = False"""
new_1 = """\
        if self.pending_wrap:
            self.cursor_col = 0
            self._linefeed()
            self.pending_wrap = False"""
code = code.replace(old_1, new_1)

# --- Fix 2: ED mode 1 must include cursor cell (inclusive) ---
old_2 = """\
            for c in range(self.cursor_col):
                self.screen[self.cursor_row][c].reset()"""
new_2 = """\
            for c in range(self.cursor_col + 1):
                self.screen[self.cursor_row][c].reset()"""
code = code.replace(old_2, new_2)

# --- Fix 3a: SGR 256-color index advance (3 -> 2, net advance 3 with loop) ---
old_3a = "                        i += 3  # skip past 38/48, mode, color index"
new_3a = "                        i += 2  # skip past mode and color index"
code = code.replace(old_3a, new_3a)

# --- Fix 3b: SGR RGB index advance (5 -> 4, net advance 5 with loop) ---
old_3b = "                        i += 5  # skip past 38/48, mode, r, g, b"
new_3b = "                        i += 4  # skip past mode, r, g, b"
code = code.replace(old_3b, new_3b)

# --- Fix 4a: DECSC must save SGR attributes ---
old_4a = """\
            elif b == ord('7'):  # DECSC - save cursor
                self.saved_cursor_pos = (self.cursor_row, self.cursor_col)
                self._state = self.STATE_GROUND"""
new_4a = """\
            elif b == ord('7'):  # DECSC - save cursor and attributes
                self.saved_cursor_pos = (self.cursor_row, self.cursor_col)
                self.saved_attrs = self.attrs.copy()
                self._state = self.STATE_GROUND"""
code = code.replace(old_4a, new_4a)

# --- Fix 4b: DECRC must restore SGR attributes ---
old_4b = """\
            elif b == ord('8'):  # DECRC - restore cursor
                if self.saved_cursor_pos is not None:
                    self.cursor_row, self.cursor_col = self.saved_cursor_pos
                self.pending_wrap = False
                self._state = self.STATE_GROUND"""
new_4b = """\
            elif b == ord('8'):  # DECRC - restore cursor and attributes
                if self.saved_cursor_pos is not None:
                    self.cursor_row, self.cursor_col = self.saved_cursor_pos
                if hasattr(self, 'saved_attrs') and self.saved_attrs is not None:
                    self.attrs = self.saved_attrs.copy()
                self.pending_wrap = False
                self._state = self.STATE_GROUND"""
code = code.replace(old_4b, new_4b)

# --- Fix 5: Alt screen must reset scroll region ---
old_5 = """\
                self.screen = self._new_screen()
                self.cursor_row = 0
                self.cursor_col = 0
                self.pending_wrap = False"""
new_5 = """\
                self.screen = self._new_screen()
                self.cursor_row = 0
                self.cursor_col = 0
                self.pending_wrap = False
                self.scroll_top = 0
                self.scroll_bottom = self.rows - 1"""
code = code.replace(old_5, new_5)

# --- Fix 6: CUP must accept both 'H' and 'f' final bytes ---
old_6 = "        if final == 'H':  # CUP"
new_6 = "        if final in ('H', 'f'):  # CUP"
code = code.replace(old_6, new_6)

# Verify all replacements were applied
if code == original:
    print("ERROR: No changes were made. Source may have changed.", file=sys.stderr)
    sys.exit(1)

with open(path, 'w') as f:
    f.write(code)

print("All 6 fixes applied to /app/terminal_emulator.py")
