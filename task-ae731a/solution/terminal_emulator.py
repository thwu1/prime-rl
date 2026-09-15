
"""
VT100/xterm terminal state machine implementation.

Processes raw terminal output byte streams and maintains a virtual screen
buffer with per-cell character and attribute state.
"""


class Cell:
    """A single character cell in the terminal screen buffer."""

    __slots__ = ("char", "fg", "bg", "bold", "underline", "reverse")

    def __init__(self):
        self.char = " "
        self.fg = None
        self.bg = None
        self.bold = False
        self.underline = False
        self.reverse = False

    def to_dict(self):
        return {
            "char": self.char,
            "fg": self.fg,
            "bg": self.bg,
            "bold": self.bold,
            "underline": self.underline,
            "reverse": self.reverse,
        }


class TerminalEmulator:
    """VT100/xterm-compatible terminal state machine."""

    def __init__(self, rows=24, cols=80):
        self.rows = rows
        self.cols = cols
        self.cursor_row = 0
        self.cursor_col = 0
        self._pending_wrap = False

        # Current SGR attributes
        self._fg = None
        self._bg = None
        self._bold = False
        self._underline = False
        self._reverse = False

        # Screen buffer
        self._screen = self._make_screen()

        # Alternate screen buffer
        self._alt_screen = None
        self._alt_cursor = None
        self._in_alt = False

        # Scroll region (0-indexed, inclusive)
        self._scroll_top = 0
        self._scroll_bottom = rows - 1

        # Saved cursor (DECSC / DECRC)
        self._saved = None

        # Parser state
        self._state = "ground"
        self._csi_buf = ""

    # ------------------------------------------------------------------
    # Screen buffer management
    # ------------------------------------------------------------------

    def _make_screen(self):
        return [[Cell() for _ in range(self.cols)] for _ in range(self.rows)]

    def _make_row(self):
        return [Cell() for _ in range(self.cols)]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed(self, data):
        """Process raw terminal output bytes."""
        if isinstance(data, str):
            data = data.encode("utf-8")

        for byte in data:
            self._process_byte(byte)

    def snapshot(self):
        """Return complete terminal state as a JSON-serializable dict."""
        return {
            "rows": self.rows,
            "cols": self.cols,
            "cursor": {"row": self.cursor_row, "col": self.cursor_col},
            "screen": [[cell.to_dict() for cell in row] for row in self._screen],
        }

    def get_cell(self, row, col):
        """Return a single cell's state dict."""
        return self._screen[row][col].to_dict()

    def get_cursor(self):
        """Return (row, col) cursor position."""
        return (self.cursor_row, self.cursor_col)

    # ------------------------------------------------------------------
    # Byte-level state machine
    # ------------------------------------------------------------------

    def _process_byte(self, byte):
        if self._state == "ground":
            self._ground(byte)
        elif self._state == "escape":
            self._escape(byte)
        elif self._state == "csi":
            self._csi(byte)

    def _ground(self, byte):
        if byte == 0x1B:  # ESC
            self._state = "escape"
        elif byte == 0x0D:  # CR
            self.cursor_col = 0
            self._pending_wrap = False
        elif byte == 0x0A:  # LF
            self._linefeed()
            self._pending_wrap = False
        elif byte == 0x08:  # BS
            if self.cursor_col > 0:
                self.cursor_col -= 1
            self._pending_wrap = False
        elif byte == 0x09:  # HT
            self._tab()
            self._pending_wrap = False
        elif byte == 0x07:  # BEL
            pass
        elif 0x20 <= byte <= 0x7E:  # Printable ASCII
            self._putchar(chr(byte))

    def _escape(self, byte):
        if byte == ord("["):
            self._state = "csi"
            self._csi_buf = ""
        elif byte == ord("7"):  # DECSC
            self._save_cursor()
            self._state = "ground"
        elif byte == ord("8"):  # DECRC
            self._restore_cursor()
            self._state = "ground"
        elif byte == ord("D"):  # IND
            self._linefeed()
            self._state = "ground"
        elif byte == ord("M"):  # RI
            self._reverse_index()
            self._state = "ground"
        elif byte == ord("E"):  # NEL
            self.cursor_col = 0
            self._linefeed()
            self._state = "ground"
        elif byte == ord("c"):  # RIS
            self.__init__(self.rows, self.cols)
        else:
            self._state = "ground"

    def _csi(self, byte):
        if 0x30 <= byte <= 0x3F:  # Parameter / private-mode bytes
            self._csi_buf += chr(byte)
        elif 0x20 <= byte <= 0x2F:  # Intermediate bytes
            self._csi_buf += chr(byte)
        elif 0x40 <= byte <= 0x7E:  # Final byte
            self._dispatch_csi(chr(byte))
            self._state = "ground"
        else:
            self._state = "ground"

    # ------------------------------------------------------------------
    # Character output with deferred wrap
    # ------------------------------------------------------------------

    def _putchar(self, ch):
        if self._pending_wrap:
            self.cursor_col = 0
            self._linefeed()
            self._pending_wrap = False

        cell = self._screen[self.cursor_row][self.cursor_col]
        cell.char = ch
        cell.fg = self._fg
        cell.bg = self._bg
        cell.bold = self._bold
        cell.underline = self._underline
        cell.reverse = self._reverse

        if self.cursor_col < self.cols - 1:
            self.cursor_col += 1
        else:
            self._pending_wrap = True

    # ------------------------------------------------------------------
    # Line feed and scrolling
    # ------------------------------------------------------------------

    def _linefeed(self):
        if self.cursor_row == self._scroll_bottom:
            self._scroll_up()
        elif self.cursor_row < self.rows - 1:
            self.cursor_row += 1

    def _reverse_index(self):
        if self.cursor_row == self._scroll_top:
            self._scroll_down()
        elif self.cursor_row > 0:
            self.cursor_row -= 1

    def _scroll_up(self):
        """Scroll the scroll region up by one line."""
        del self._screen[self._scroll_top]
        self._screen.insert(self._scroll_bottom, self._make_row())

    def _scroll_down(self):
        """Scroll the scroll region down by one line."""
        del self._screen[self._scroll_bottom]
        self._screen.insert(self._scroll_top, self._make_row())

    # ------------------------------------------------------------------
    # Tab
    # ------------------------------------------------------------------

    def _tab(self):
        next_stop = ((self.cursor_col // 8) + 1) * 8
        self.cursor_col = min(next_stop, self.cols - 1)

    # ------------------------------------------------------------------
    # Save / restore cursor
    # ------------------------------------------------------------------

    def _save_cursor(self):
        self._saved = (
            self.cursor_row, self.cursor_col,
            self._fg, self._bg,
            self._bold, self._underline, self._reverse,
        )

    def _restore_cursor(self):
        if self._saved is not None:
            (
                self.cursor_row, self.cursor_col,
                self._fg, self._bg,
                self._bold, self._underline, self._reverse,
            ) = self._saved
            self._pending_wrap = False

    # ------------------------------------------------------------------
    # CSI dispatch
    # ------------------------------------------------------------------

    def _dispatch_csi(self, final):
        raw = self._csi_buf

        # DEC private modes
        if raw.startswith("?"):
            self._dispatch_dec_private(raw[1:], final)
            return

        params = self._parse_params(raw)

        if final in ("H", "f"):     # CUP
            r = max(0, (params[0] if params else 1) - 1)
            c = max(0, (params[1] if len(params) > 1 else 1) - 1)
            self.cursor_row = min(r, self.rows - 1)
            self.cursor_col = min(c, self.cols - 1)
            self._pending_wrap = False

        elif final == "A":          # CUU
            n = params[0] if params else 1
            self.cursor_row = max(0, self.cursor_row - n)
            self._pending_wrap = False

        elif final == "B":          # CUD
            n = params[0] if params else 1
            self.cursor_row = min(self.rows - 1, self.cursor_row + n)
            self._pending_wrap = False

        elif final == "C":          # CUF
            n = params[0] if params else 1
            self.cursor_col = min(self.cols - 1, self.cursor_col + n)
            self._pending_wrap = False

        elif final == "D":          # CUB
            n = params[0] if params else 1
            self.cursor_col = max(0, self.cursor_col - n)
            self._pending_wrap = False

        elif final == "J":          # ED
            self._erase_display(params[0] if params else 0)

        elif final == "K":          # EL
            self._erase_line(params[0] if params else 0)

        elif final == "m":          # SGR
            self._sgr(params if params else [0])

        elif final == "r":          # DECSTBM
            top = (params[0] if params else 1) - 1
            bot = (params[1] if len(params) > 1 else self.rows) - 1
            self._scroll_top = max(0, top)
            self._scroll_bottom = min(self.rows - 1, bot)
            self.cursor_row = 0
            self.cursor_col = 0
            self._pending_wrap = False

        elif final == "G":          # CHA
            c = max(0, (params[0] if params else 1) - 1)
            self.cursor_col = min(c, self.cols - 1)
            self._pending_wrap = False

        elif final == "d":          # VPA
            r = max(0, (params[0] if params else 1) - 1)
            self.cursor_row = min(r, self.rows - 1)
            self._pending_wrap = False

        elif final == "S":          # SU
            n = params[0] if params else 1
            for _ in range(n):
                self._scroll_up()

        elif final == "T":          # SD
            n = params[0] if params else 1
            for _ in range(n):
                self._scroll_down()

    def _parse_params(self, raw):
        if not raw:
            return []
        parts = raw.split(";")
        result = []
        for p in parts:
            try:
                result.append(int(p))
            except ValueError:
                result.append(0)
        return result

    # ------------------------------------------------------------------
    # DEC private modes
    # ------------------------------------------------------------------

    def _dispatch_dec_private(self, raw, final):
        params = self._parse_params(raw)
        for p in params:
            if final == "h":       # DECSET
                if p == 1049:
                    self._alt_screen = self._screen
                    self._alt_cursor = (self.cursor_row, self.cursor_col)
                    self._screen = self._make_screen()
                    self.cursor_row = 0
                    self.cursor_col = 0
                    self._in_alt = True
                    self._pending_wrap = False
            elif final == "l":     # DECRST
                if p == 1049 and self._alt_screen is not None:
                    self._screen = self._alt_screen
                    self.cursor_row, self.cursor_col = self._alt_cursor
                    self._alt_screen = None
                    self._alt_cursor = None
                    self._in_alt = False
                    self._pending_wrap = False

    # ------------------------------------------------------------------
    # Erase operations
    # ------------------------------------------------------------------

    def _erase_display(self, mode):
        if mode == 0:
            # Erase from cursor to end
            for c in range(self.cursor_col, self.cols):
                self._screen[self.cursor_row][c] = Cell()
            for r in range(self.cursor_row + 1, self.rows):
                self._screen[r] = self._make_row()
        elif mode == 1:
            # Erase from start to cursor
            for r in range(self.cursor_row):
                self._screen[r] = self._make_row()
            for c in range(self.cursor_col + 1):
                self._screen[self.cursor_row][c] = Cell()
        elif mode in (2, 3):
            self._screen = self._make_screen()

    def _erase_line(self, mode):
        if mode == 0:
            for c in range(self.cursor_col, self.cols):
                self._screen[self.cursor_row][c] = Cell()
        elif mode == 1:
            for c in range(self.cursor_col + 1):
                self._screen[self.cursor_row][c] = Cell()
        elif mode == 2:
            self._screen[self.cursor_row] = self._make_row()

    # ------------------------------------------------------------------
    # SGR (Select Graphic Rendition)
    # ------------------------------------------------------------------

    def _sgr(self, params):
        i = 0
        while i < len(params):
            p = params[i]
            if p == 0:
                self._fg = None
                self._bg = None
                self._bold = False
                self._underline = False
                self._reverse = False
            elif p == 1:
                self._bold = True
            elif p == 4:
                self._underline = True
            elif p == 7:
                self._reverse = True
            elif p == 22:
                self._bold = False
            elif p == 24:
                self._underline = False
            elif p == 27:
                self._reverse = False
            elif 30 <= p <= 37:
                self._fg = p - 30
            elif p == 39:
                self._fg = None
            elif 40 <= p <= 47:
                self._bg = p - 40
            elif p == 49:
                self._bg = None
            elif p == 38:
                # Extended foreground
                if i + 1 < len(params):
                    if params[i + 1] == 5 and i + 2 < len(params):
                        self._fg = params[i + 2]
                        i += 2
                    elif params[i + 1] == 2 and i + 4 < len(params):
                        self._fg = [params[i + 2], params[i + 3], params[i + 4]]
                        i += 4
            elif p == 48:
                # Extended background
                if i + 1 < len(params):
                    if params[i + 1] == 5 and i + 2 < len(params):
                        self._bg = params[i + 2]
                        i += 2
                    elif params[i + 1] == 2 and i + 4 < len(params):
                        self._bg = [params[i + 2], params[i + 3], params[i + 4]]
                        i += 4
            i += 1
