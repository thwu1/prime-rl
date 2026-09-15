"""VT100/xterm-compatible terminal emulator with virtual screen buffer."""


class Cell:
    __slots__ = ('char', 'fg', 'bg', 'bold', 'underline', 'reverse')

    def __init__(self):
        self.char = ' '
        self.fg = None
        self.bg = None
        self.bold = False
        self.underline = False
        self.reverse = False

    def to_dict(self):
        return {
            'char': self.char,
            'fg': list(self.fg) if isinstance(self.fg, list) else self.fg,
            'bg': list(self.bg) if isinstance(self.bg, list) else self.bg,
            'bold': self.bold,
            'underline': self.underline,
            'reverse': self.reverse,
        }

    def reset(self):
        self.char = ' '
        self.fg = None
        self.bg = None
        self.bold = False
        self.underline = False
        self.reverse = False


class Attributes:
    __slots__ = ('fg', 'bg', 'bold', 'underline', 'reverse')

    def __init__(self):
        self.fg = None
        self.bg = None
        self.bold = False
        self.underline = False
        self.reverse = False

    def copy(self):
        a = Attributes()
        a.fg = list(self.fg) if isinstance(self.fg, list) else self.fg
        a.bg = list(self.bg) if isinstance(self.bg, list) else self.bg
        a.bold = self.bold
        a.underline = self.underline
        a.reverse = self.reverse
        return a

    def apply(self, cell):
        cell.fg = list(self.fg) if isinstance(self.fg, list) else self.fg
        cell.bg = list(self.bg) if isinstance(self.bg, list) else self.bg
        cell.bold = self.bold
        cell.underline = self.underline
        cell.reverse = self.reverse

    def reset(self):
        self.fg = None
        self.bg = None
        self.bold = False
        self.underline = False
        self.reverse = False


class TerminalEmulator:
    STATE_GROUND = 0
    STATE_ESCAPE = 1
    STATE_CSI = 2

    def __init__(self, rows, cols):
        self.rows = rows
        self.cols = cols
        self.screen = self._new_screen()
        self.cursor_row = 0
        self.cursor_col = 0
        self.pending_wrap = False
        self.attrs = Attributes()
        self.scroll_top = 0
        self.scroll_bottom = rows - 1
        self.saved_cursor_pos = None
        self.saved_attrs = None
        self.alt_screen = None
        self.alt_cursor = None
        self._state = self.STATE_GROUND
        self._csi_params = ''
        self._csi_private = False

    def _new_screen(self):
        return [[Cell() for _ in range(self.cols)] for _ in range(self.rows)]

    def _scroll_up(self, top, bottom):
        """Remove top row of region, insert blank row at bottom."""
        self.screen.pop(top)
        self.screen.insert(bottom, [Cell() for _ in range(self.cols)])

    def _linefeed(self):
        if self.cursor_row == self.scroll_bottom:
            self._scroll_up(self.scroll_top, self.scroll_bottom)
        elif self.cursor_row < self.rows - 1:
            self.cursor_row += 1

    def _put_char(self, ch):
        if self.pending_wrap:
            self.cursor_col = 0
            self._linefeed()
            self.pending_wrap = False

        cell = self.screen[self.cursor_row][self.cursor_col]
        cell.char = ch
        self.attrs.apply(cell)

        if self.cursor_col >= self.cols - 1:
            self.pending_wrap = True
        else:
            self.cursor_col += 1

    def feed(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        for b in data:
            self._process_byte(b)

    def _process_byte(self, b):
        if self._state == self.STATE_GROUND:
            if b == 0x1b:
                self._state = self.STATE_ESCAPE
            elif b == 0x0d:  # CR
                self.cursor_col = 0
                self.pending_wrap = False
            elif b == 0x0a:  # LF
                self.pending_wrap = False
                self._linefeed()
            elif b == 0x08:  # BS
                if self.cursor_col > 0:
                    self.cursor_col -= 1
                self.pending_wrap = False
            elif b == 0x09:  # HT
                next_stop = ((self.cursor_col // 8) + 1) * 8
                self.cursor_col = min(next_stop, self.cols - 1)
                self.pending_wrap = False
            elif b == 0x07:  # BEL
                pass
            elif 0x20 <= b <= 0x7e:
                self._put_char(chr(b))

        elif self._state == self.STATE_ESCAPE:
            if b == ord('['):
                self._state = self.STATE_CSI
                self._csi_params = ''
                self._csi_private = False
            elif b == ord('7'):  # DECSC - save cursor and attributes
                self.saved_cursor_pos = (self.cursor_row, self.cursor_col)
                self.saved_attrs = self.attrs.copy()
                self._state = self.STATE_GROUND
            elif b == ord('8'):  # DECRC - restore cursor and attributes
                if self.saved_cursor_pos is not None:
                    self.cursor_row, self.cursor_col = self.saved_cursor_pos
                if self.saved_attrs is not None:
                    self.attrs = self.saved_attrs.copy()
                self.pending_wrap = False
                self._state = self.STATE_GROUND
            else:
                self._state = self.STATE_GROUND

        elif self._state == self.STATE_CSI:
            ch = chr(b) if b < 128 else None
            if ch == '?':
                self._csi_private = True
            elif ch and (ch.isdigit() or ch == ';'):
                self._csi_params += ch
            elif ch and '@' <= ch <= '~':
                self._dispatch_csi(ch)
                self._state = self.STATE_GROUND
            else:
                self._state = self.STATE_GROUND

    def _get_params(self, defaults=None):
        if not self._csi_params:
            return list(defaults) if defaults else []
        parts = self._csi_params.split(';')
        result = []
        for i, p in enumerate(parts):
            if p == '':
                if defaults and i < len(defaults):
                    result.append(defaults[i])
                else:
                    result.append(0)
            else:
                result.append(int(p))
        return result

    def _dispatch_csi(self, final):
        if self._csi_private:
            self._handle_dec_mode(final)
            return

        if final in ('H', 'f'):  # CUP / HVP
            params = self._get_params([1, 1])
            r = max(0, params[0] - 1)
            c = max(0, (params[1] - 1) if len(params) > 1 else 0)
            self.cursor_row = min(r, self.rows - 1)
            self.cursor_col = min(c, self.cols - 1)
            self.pending_wrap = False

        elif final == 'A':  # CUU
            params = self._get_params([1])
            n = max(1, params[0])
            self.cursor_row = max(0, self.cursor_row - n)
            self.pending_wrap = False

        elif final == 'B':  # CUD
            params = self._get_params([1])
            n = max(1, params[0])
            self.cursor_row = min(self.rows - 1, self.cursor_row + n)
            self.pending_wrap = False

        elif final == 'C':  # CUF
            params = self._get_params([1])
            n = max(1, params[0])
            self.cursor_col = min(self.cols - 1, self.cursor_col + n)
            self.pending_wrap = False

        elif final == 'D':  # CUB
            params = self._get_params([1])
            n = max(1, params[0])
            self.cursor_col = max(0, self.cursor_col - n)
            self.pending_wrap = False

        elif final == 'J':  # ED
            params = self._get_params([0])
            self._erase_display(params[0])

        elif final == 'K':  # EL
            params = self._get_params([0])
            self._erase_line(params[0])

        elif final == 'm':  # SGR
            self._handle_sgr()

        elif final == 'r':  # DECSTBM
            params = self._get_params([1, self.rows])
            top = max(0, params[0] - 1)
            bot = max(0, (params[1] - 1) if len(params) > 1 else self.rows - 1)
            if top < bot <= self.rows - 1:
                self.scroll_top = top
                self.scroll_bottom = bot
            self.cursor_row = 0
            self.cursor_col = 0
            self.pending_wrap = False

    def _handle_dec_mode(self, final):
        params = self._get_params()
        if not params:
            return
        mode = params[0]
        if mode == 1049:
            if final == 'h':
                self.alt_screen = self.screen
                self.alt_cursor = (self.cursor_row, self.cursor_col)
                self.screen = self._new_screen()
                self.cursor_row = 0
                self.cursor_col = 0
                self.pending_wrap = False
                self.scroll_top = 0
                self.scroll_bottom = self.rows - 1
            elif final == 'l':
                if self.alt_screen is not None:
                    self.screen = self.alt_screen
                    self.cursor_row, self.cursor_col = self.alt_cursor
                    self.alt_screen = None
                    self.alt_cursor = None
                self.pending_wrap = False

    def _erase_display(self, mode):
        if mode == 0:  # Erase from cursor to end
            for c in range(self.cursor_col, self.cols):
                self.screen[self.cursor_row][c].reset()
            for r in range(self.cursor_row + 1, self.rows):
                for c in range(self.cols):
                    self.screen[r][c].reset()
        elif mode == 1:  # Erase from start to cursor (inclusive)
            for r in range(self.cursor_row):
                for c in range(self.cols):
                    self.screen[r][c].reset()
            for c in range(self.cursor_col + 1):
                self.screen[self.cursor_row][c].reset()
        elif mode == 2:  # Erase entire display
            for r in range(self.rows):
                for c in range(self.cols):
                    self.screen[r][c].reset()

    def _erase_line(self, mode):
        if mode == 0:
            for c in range(self.cursor_col, self.cols):
                self.screen[self.cursor_row][c].reset()
        elif mode == 1:
            for c in range(self.cursor_col + 1):
                self.screen[self.cursor_row][c].reset()
        elif mode == 2:
            for c in range(self.cols):
                self.screen[self.cursor_row][c].reset()

    def _handle_sgr(self):
        if not self._csi_params:
            self.attrs.reset()
            return

        parts = self._csi_params.split(';')
        i = 0
        while i < len(parts):
            val = int(parts[i]) if parts[i] else 0

            if val == 0:
                self.attrs.reset()
            elif val == 1:
                self.attrs.bold = True
            elif val == 4:
                self.attrs.underline = True
            elif val == 7:
                self.attrs.reverse = True
            elif val == 22:
                self.attrs.bold = False
            elif val == 24:
                self.attrs.underline = False
            elif val == 27:
                self.attrs.reverse = False
            elif 30 <= val <= 37:
                self.attrs.fg = val - 30
            elif val == 39:
                self.attrs.fg = None
            elif 40 <= val <= 47:
                self.attrs.bg = val - 40
            elif val == 49:
                self.attrs.bg = None
            elif val in (38, 48):
                if i + 1 < len(parts):
                    sub = int(parts[i + 1]) if parts[i + 1] else 0
                    if sub == 5 and i + 2 < len(parts):
                        color_idx = int(parts[i + 2]) if parts[i + 2] else 0
                        if val == 38:
                            self.attrs.fg = color_idx
                        else:
                            self.attrs.bg = color_idx
                        i += 2
                    elif sub == 2 and i + 4 < len(parts):
                        r = int(parts[i + 2]) if parts[i + 2] else 0
                        g = int(parts[i + 3]) if parts[i + 3] else 0
                        bv = int(parts[i + 4]) if parts[i + 4] else 0
                        if val == 38:
                            self.attrs.fg = [r, g, bv]
                        else:
                            self.attrs.bg = [r, g, bv]
                        i += 4
            i += 1

    def snapshot(self):
        return {
            'rows': self.rows,
            'cols': self.cols,
            'cursor': {'row': self.cursor_row, 'col': self.cursor_col},
            'screen': [[cell.to_dict() for cell in row] for row in self.screen],
        }

    def get_cell(self, row, col):
        return self.screen[row][col].to_dict()

    def get_cursor(self):
        return (self.cursor_row, self.cursor_col)
