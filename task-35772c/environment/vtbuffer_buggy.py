"""VT420-level terminal screen buffer with DEC rectangular area operations."""


class Cell:
    __slots__ = ('char', 'protected')

    def __init__(self):
        self.char = '\x00'
        self.protected = 0  # 0=none, 1=DEC, 2=ISO


class ScreenBuffer:
    def __init__(self, width: int, height: int):
        self._width = width
        self._height = height
        self._grid = [[Cell() for _ in range(width)] for _ in range(height)]
        self._cursor_row = 1
        self._cursor_col = 1
        self._scroll_top = 1
        self._scroll_bottom = height
        self._lrm_enabled = False
        self._margin_left = 1
        self._margin_right = width
        self._origin_mode = False
        self._current_protection = 0

    # -- Cursor --

    def set_cursor(self, row: int, col: int):
        if self._origin_mode:
            row = row + self._scroll_top - 1
            col = col + self._effective_left() - 1
            row = max(self._scroll_top, min(row, self._scroll_bottom))
            col = max(self._effective_left(), min(col, self._effective_right()))
        else:
            row = max(1, min(row, self._height))
            col = max(1, min(col, self._width))
        self._cursor_row = row
        self._cursor_col = col

    def get_cursor(self):
        if self._origin_mode:
            return (self._cursor_row - self._scroll_top + 1,
                    self._cursor_col - self._effective_left() + 1)
        return (self._cursor_row, self._cursor_col)

    # -- Cell access --

    def get_cell(self, row: int, col: int) -> str:
        if 1 <= row <= self._height and 1 <= col <= self._width:
            return self._grid[row - 1][col - 1].char
        return '\x00'

    def get_rect(self, top: int, left: int, bottom: int, right: int) -> list:
        result = []
        for r in range(top, bottom + 1):
            line = ''
            for c in range(left, right + 1):
                line += self.get_cell(r, c)
            result.append(line)
        return result

    # -- Writing --

    def write_char(self, ch: str):
        if 1 <= self._cursor_row <= self._height and 1 <= self._cursor_col <= self._width:
            cell = self._grid[self._cursor_row - 1][self._cursor_col - 1]
            cell.char = ch
            cell.protected = self._current_protection
        if self._cursor_col < self._width:
            self._cursor_col += 1

    def carriage_return(self):
        if self._origin_mode and self._lrm_enabled:
            self._cursor_col = self._effective_left()
        else:
            self._cursor_col = 1

    def linefeed(self):
        if self._cursor_row == self._scroll_bottom:
            self._scroll_up_region()
        elif self._cursor_row < self._height:
            self._cursor_row += 1

    def newline(self):
        self.carriage_return()
        self.linefeed()

    # -- Scrolling --

    def set_scrolling_region(self, top=None, bottom=None):
        if top is None and bottom is None:
            self._scroll_top = 1
            self._scroll_bottom = self._height
        else:
            t = top if top and top >= 1 else 1
            b = bottom if bottom and bottom <= self._height else self._height
            if t < b:
                self._scroll_top = t
                self._scroll_bottom = b
            else:
                self._scroll_top = 1
                self._scroll_bottom = self._height

    def set_left_right_margins(self, left=None, right=None):
        self._margin_left = left if left and left >= 1 else 1
        self._margin_right = right if right and right <= self._width else self._width

    def set_left_right_margin_mode(self, enabled: bool):
        self._lrm_enabled = enabled
        if not enabled:
            self._margin_left = 1
            self._margin_right = self._width

    def set_origin_mode(self, enabled: bool):
        self._origin_mode = enabled

    def set_character_protection(self, mode: int):
        self._current_protection = mode

    def _effective_left(self):
        return self._margin_left if self._lrm_enabled else 1

    def _effective_right(self):
        return self._margin_right if self._lrm_enabled else self._width

    def _scroll_up_region(self):
        left = 1
        right = self._width
        for r in range(self._scroll_top, self._scroll_bottom):
            for c in range(left, right + 1):
                src = self._grid[r][c - 1]
                dst = self._grid[r - 1][c - 1]
                dst.char = src.char
                dst.protected = src.protected
        for c in range(left, right + 1):
            cell = self._grid[self._scroll_bottom - 1][c - 1]
            cell.char = '\x00'
            cell.protected = 0

    # -- Coordinate translation --

    def _translate_coords(self, top, left, bottom, right):
        if self._origin_mode:
            eff_left = self._effective_left()
            t = (top + self._scroll_top - 1) if top is not None else self._scroll_top
            l = (left + eff_left - 1) if left is not None else eff_left
            b = (bottom + self._scroll_top - 1) if bottom is not None else self._scroll_bottom
            r = (right + eff_left - 1) if right is not None else self._effective_right()
        else:
            t = top if top is not None else 1
            l = left if left is not None else 1
            b = bottom if bottom is not None else self._height
            r = right if right is not None else self._width
        return t, l, b, r

    def _clip_rect(self, t, l, b, r):
        t = max(1, t)
        l = max(1, l)
        b = min(self._height, b)
        r = min(self._width, r)
        return t, l, b, r

    # -- DECCRA --

    def deccra(self, src_top, src_left, src_bottom, src_right,
               src_page, dst_top, dst_left, dst_page):
        st, sl, sb, sr = self._translate_coords(src_top, src_left, src_bottom, src_right)
        dt_raw, dl_raw, _, _ = self._translate_coords(dst_top, dst_left, None, None)
        dt = dt_raw
        dl = dl_raw

        st, sl, sb, sr = self._clip_rect(st, sl, sb, sr)

        if st > sb or sl > sr:
            return

        src_h = sb - st + 1
        src_w = sr - sl + 1

        for r in range(src_h):
            for c in range(src_w):
                ar = st + r
                ac = sl + c
                dr = dt + r
                dc = dl + c
                if 1 <= dr <= self._height and 1 <= dc <= self._width:
                    if 1 <= ar <= self._height and 1 <= ac <= self._width:
                        src_cell = self._grid[ar - 1][ac - 1]
                        dst_cell = self._grid[dr - 1][dc - 1]
                        dst_cell.char = src_cell.char
                        dst_cell.protected = src_cell.protected

    # -- DECFRA --

    def decfra(self, ch_code, top, left, bottom, right):
        t = top if top is not None else 1
        l = left if left is not None else 1
        b = bottom if bottom is not None else self._height
        r = right if right is not None else self._width
        t, l, b, r = self._clip_rect(t, l, b, r)
        if t > b or l > r:
            return
        ch = chr(ch_code)
        for row in range(t, b + 1):
            for col in range(l, r + 1):
                cell = self._grid[row - 1][col - 1]
                cell.char = ch

    # -- DECERA --

    def decera(self, top, left, bottom, right):
        t, l, b, r = self._translate_coords(top, left, bottom, right)
        t, l, b, r = self._clip_rect(t, l, b, r)
        if t > b or l > r:
            return
        for row in range(t, b + 1):
            for col in range(l, r + 1):
                cell = self._grid[row - 1][col - 1]
                if cell.protected != 1:
                    cell.char = '\x00'
                    cell.protected = 0

    # -- DECSERA --

    def decsera(self, top, left, bottom, right):
        t, l, b, r = self._translate_coords(top, left, bottom, right)
        t, l, b, r = self._clip_rect(t, l, b, r)
        if t > b or l > r:
            return
        for row in range(t, b + 1):
            for col in range(l, r + 1):
                cell = self._grid[row - 1][col - 1]
                if not cell.protected:
                    cell.char = '\x00'
                    cell.protected = 0
