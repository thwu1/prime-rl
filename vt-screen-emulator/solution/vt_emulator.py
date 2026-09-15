#!/usr/bin/env python3
"""
VT-420 Terminal Screen Buffer Emulator

Implements a VTEmulator class that maintains a character cell grid and
supports a subset of VT-420 escape sequence operations needed by the
scenario script.

Cell values:
  - 0 (NUL) for uninitialized / erased cells
  - ord(char) for written characters

Coordinates are 1-based and inclusive throughout the public API.
"""


class VTEmulator:
    def __init__(self, cols, rows):
        self.cols = cols
        self.rows = rows
        self.screen = [[0] * cols for _ in range(rows)]
        self.cursor_row = 0  # 0-indexed
        self.cursor_col = 0  # 0-indexed
        self.margin_top = 1  # 1-indexed inclusive
        self.margin_bottom = rows  # 1-indexed inclusive
        self.origin_mode = False

    # ---- Cursor positioning ----

    def cup(self, row, col):
        """CUP — Cursor Position. Parameters are 1-based."""
        if self.origin_mode:
            actual_row = self.margin_top + row - 1
        else:
            actual_row = row
        actual_col = col
        self.cursor_row = max(0, min(self.rows - 1, actual_row - 1))
        self.cursor_col = max(0, min(self.cols - 1, actual_col - 1))

    # ---- Character output ----

    def write(self, text):
        """Write printable characters at the current cursor position.

        Handles CR (\\r) and LF (\\n). LF at the bottom of the scroll
        region triggers a scroll-up. Characters beyond the right margin
        are silently dropped (no autowrap).
        """
        for ch in text:
            if ch == '\r':
                self.cursor_col = 0
            elif ch == '\n':
                if self.cursor_row == self.margin_bottom - 1:
                    self._scroll_up()
                elif self.cursor_row < self.rows - 1:
                    self.cursor_row += 1
            else:
                if self.cursor_col < self.cols:
                    self.screen[self.cursor_row][self.cursor_col] = ord(ch)
                    self.cursor_col += 1

    # ---- Scrolling helpers ----

    def _scroll_up(self):
        top = self.margin_top - 1
        bottom = self.margin_bottom - 1
        for r in range(top, bottom):
            self.screen[r] = self.screen[r + 1][:]
        self.screen[bottom] = [0] * self.cols

    def _scroll_down(self):
        top = self.margin_top - 1
        bottom = self.margin_bottom - 1
        for r in range(bottom, top, -1):
            self.screen[r] = self.screen[r - 1][:]
        self.screen[top] = [0] * self.cols

    # ---- Index / Reverse Index ----

    def ind(self):
        """IND — Index. Move cursor down; scroll region up if at bottom margin."""
        if self.cursor_row == self.margin_bottom - 1:
            self._scroll_up()
        elif self.cursor_row < self.rows - 1:
            self.cursor_row += 1

    def ri(self):
        """RI — Reverse Index. Move cursor up; scroll region down if at top margin."""
        if self.cursor_row == self.margin_top - 1:
            self._scroll_down()
        elif self.cursor_row > 0:
            self.cursor_row -= 1

    # ---- Scroll margins ----

    def decstbm(self, top=None, bottom=None):
        """DECSTBM — Set Top and Bottom Margins. Resets cursor to home."""
        if top is None and bottom is None:
            self.margin_top = 1
            self.margin_bottom = self.rows
        else:
            self.margin_top = top if top else 1
            self.margin_bottom = bottom if bottom else self.rows
        # DECSTBM moves cursor to home
        if self.origin_mode:
            self.cursor_row = self.margin_top - 1
        else:
            self.cursor_row = 0
        self.cursor_col = 0

    # ---- Origin mode ----

    def decset_decom(self):
        """Enable Origin Mode (DECOM). CUP coordinates become relative
        to the top margin of the scroll region."""
        self.origin_mode = True
        self.cursor_row = self.margin_top - 1
        self.cursor_col = 0

    def decreset_decom(self):
        """Disable Origin Mode."""
        self.origin_mode = False

    # ---- Rectangular operations ----

    def deccra(self, src_top, src_left, src_bottom, src_right,
               src_page, dst_top, dst_left, dst_page):
        """DECCRA — Copy Rectangular Area.

        Uses snapshot semantics: the entire source rectangle is captured
        before any cells are written to the destination. This is critical
        when source and destination overlap.
        """
        # Snapshot the source rectangle
        src_data = []
        for r in range(src_top - 1, src_bottom):
            row_data = []
            for c in range(src_left - 1, src_right):
                if 0 <= r < self.rows and 0 <= c < self.cols:
                    row_data.append(self.screen[r][c])
                else:
                    row_data.append(0)
            src_data.append(row_data)

        # Paste to destination
        for dr, src_row in enumerate(src_data):
            for dc, val in enumerate(src_row):
                dest_r = dst_top - 1 + dr
                dest_c = dst_left - 1 + dc
                if 0 <= dest_r < self.rows and 0 <= dest_c < self.cols:
                    self.screen[dest_r][dest_c] = val

    def decfra(self, char_code, top, left, bottom, right):
        """DECFRA — Fill Rectangular Area with the specified character ordinal."""
        for r in range(max(0, top - 1), min(self.rows, bottom)):
            for c in range(max(0, left - 1), min(self.cols, right)):
                self.screen[r][c] = char_code

    def decera(self, top, left, bottom, right):
        """DECERA — Erase Rectangular Area (set cells to NUL/0)."""
        for r in range(max(0, top - 1), min(self.rows, bottom)):
            for c in range(max(0, left - 1), min(self.cols, right)):
                self.screen[r][c] = 0

    # ---- Erase display ----

    def ed(self, mode=0):
        """ED — Erase in Display.
        mode 0: cursor to end  |  mode 1: start to cursor  |  mode 2: all
        """
        if mode == 0:
            for c in range(self.cursor_col, self.cols):
                self.screen[self.cursor_row][c] = 0
            for r in range(self.cursor_row + 1, self.rows):
                self.screen[r] = [0] * self.cols
        elif mode == 1:
            for r in range(0, self.cursor_row):
                self.screen[r] = [0] * self.cols
            for c in range(0, self.cursor_col + 1):
                self.screen[self.cursor_row][c] = 0
        elif mode == 2:
            self.screen = [[0] * self.cols for _ in range(self.rows)]

    # ---- Checksum ----

    def decrqcra(self, top, left, bottom, right):
        """DECRQCRA — Compute checksum of a rectangular area.

        Returns the sum of character ordinal values for all cells in the
        specified rectangle, taken modulo 65536.
        """
        checksum = 0
        for r in range(max(0, top - 1), min(self.rows, bottom)):
            for c in range(max(0, left - 1), min(self.cols, right)):
                checksum += self.screen[r][c]
        return checksum % 65536
