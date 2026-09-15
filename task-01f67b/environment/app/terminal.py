"""
Terminal screen model, VT100 parser, and full-screen renderer.

Provides the data structures and parsing infrastructure for the screen diff task.
The VTParser processes ANSI escape sequences and updates a Screen object in place.
The render_full function generates escape sequences to reproduce a screen from scratch.

"""

import copy
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Attrs:
    """Terminal text attributes (immutable).

    fg/bg: -1 = default, 0-7 = basic, 8-15 = bright, 16-255 = extended palette.
    """
    fg: int = -1
    bg: int = -1
    bold: bool = False
    italic: bool = False
    underline: bool = False
    inverse: bool = False


@dataclass
class Cell:
    """A single terminal cell: one character with attributes."""
    char: str = ' '
    attrs: Attrs = field(default_factory=Attrs)

    def __eq__(self, other):
        if not isinstance(other, Cell):
            return NotImplemented
        return self.char == other.char and self.attrs == other.attrs

    def __ne__(self, other):
        eq = self.__eq__(other)
        if eq is NotImplemented:
            return eq
        return not eq

    def __repr__(self):
        if self.attrs == Attrs():
            return f"Cell({self.char!r})"
        return f"Cell({self.char!r}, {self.attrs})"


class Screen:
    """Terminal screen state: a grid of Cells plus cursor position."""

    def __init__(self, rows: int = 24, cols: int = 80):
        self.rows = rows
        self.cols = cols
        self.cursor_row = 0
        self.cursor_col = 0
        self.cells = [[Cell() for _ in range(cols)] for _ in range(rows)]

    def cell(self, row: int, col: int) -> Cell:
        return self.cells[row][col]

    def set_cell(self, row: int, col: int, char: str, attrs: Attrs = None):
        if attrs is None:
            attrs = Attrs()
        self.cells[row][col] = Cell(char=char, attrs=attrs)

    def clone(self) -> 'Screen':
        return copy.deepcopy(self)

    def __eq__(self, other):
        if not isinstance(other, Screen):
            return NotImplemented
        if self.rows != other.rows or self.cols != other.cols:
            return False
        if self.cursor_row != other.cursor_row or self.cursor_col != other.cursor_col:
            return False
        for r in range(self.rows):
            for c in range(self.cols):
                if self.cells[r][c] != other.cells[r][c]:
                    return False
        return True

    def diff_report(self, other: 'Screen') -> str:
        """Human-readable summary of differences (for debugging)."""
        lines = []
        if self.cursor_row != other.cursor_row or self.cursor_col != other.cursor_col:
            lines.append(
                f"cursor: ({self.cursor_row},{self.cursor_col}) vs "
                f"({other.cursor_row},{other.cursor_col})"
            )
        for r in range(min(self.rows, other.rows)):
            for c in range(min(self.cols, other.cols)):
                if self.cells[r][c] != other.cells[r][c]:
                    lines.append(
                        f"  cell({r},{c}): {self.cells[r][c]!r} vs {other.cells[r][c]!r}"
                    )
        if len(lines) > 60:
            lines = lines[:60] + [f"  ... and {len(lines)-60} more"]
        return '\n'.join(lines) if lines else "(identical)"


class VTParser:
    """Minimal VT100 escape sequence parser.

    Supports the subset of sequences relevant to screen diffing:
    - Cursor:  CSI H (CUP), CSI A/B/C/D (relative), CSI G (CHA)
    - Erase:   CSI K (EL), CSI J (ED), CSI X (ECH)
    - Attrs:   CSI m (SGR) with basic/bright/256-colour fg/bg,
               bold(1), italic(3), underline(4), inverse(7),
               and their off codes (22,23,24,27,39,49)
    - Control: CR (0x0D), LF (0x0A)
    - Print:   ASCII 0x20-0x7E
    """

    def __init__(self, screen: Screen):
        self.screen = screen
        self.attrs = Attrs()  # current drawing attributes

    def process(self, data: bytes):
        """Feed bytes through the parser, updating the screen."""
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == 0x1B:  # ESC
                if i + 1 < n and data[i + 1] == 0x5B:  # CSI  '['
                    i = self._parse_csi(data, i + 2)
                else:
                    i += 2  # skip unknown ESC sequence
            elif b == 0x0D:  # CR
                self.screen.cursor_col = 0
                i += 1
            elif b == 0x0A:  # LF
                if self.screen.cursor_row < self.screen.rows - 1:
                    self.screen.cursor_row += 1
                i += 1
            elif 0x20 <= b <= 0x7E:  # printable ASCII
                s = self.screen
                # Auto-wrap: if cursor is past end of line, wrap to next row
                if s.cursor_col >= s.cols:
                    s.cursor_col = 0
                    if s.cursor_row < s.rows - 1:
                        s.cursor_row += 1
                s.cells[s.cursor_row][s.cursor_col] = Cell(
                    char=chr(b), attrs=self.attrs
                )
                s.cursor_col += 1
                i += 1
            else:
                i += 1  # skip other control bytes

    # ---- CSI parsing ----

    def _parse_csi(self, data: bytes, i: int) -> int:
        """Parse CSI sequence starting after ESC[.  Returns new index."""
        params = []
        current = []
        n = len(data)
        while i < n:
            b = data[i]
            if 0x30 <= b <= 0x39:  # digit
                current.append(b - 0x30)
                i += 1
            elif b == 0x3B:  # ';'
                params.append(self._digits_to_int(current))
                current = []
                i += 1
            elif 0x40 <= b <= 0x7E:  # final byte
                if current:
                    params.append(self._digits_to_int(current))
                self._exec_csi(chr(b), params)
                return i + 1
            else:
                return i + 1  # malformed
        return i

    @staticmethod
    def _digits_to_int(digits):
        if not digits:
            return 0
        v = 0
        for d in digits:
            v = v * 10 + d
        return v

    def _exec_csi(self, cmd: str, params: list):
        s = self.screen

        if cmd in ('H', 'f'):  # CUP / HVP
            row = (params[0] if params else 1) - 1
            col = (params[1] if len(params) > 1 else 1) - 1
            s.cursor_row = max(0, min(row, s.rows - 1))
            s.cursor_col = max(0, min(col, s.cols - 1))

        elif cmd == 'A':  # CUU
            n = params[0] if params else 1
            s.cursor_row = max(0, s.cursor_row - n)

        elif cmd == 'B':  # CUD
            n = params[0] if params else 1
            s.cursor_row = min(s.rows - 1, s.cursor_row + n)

        elif cmd == 'C':  # CUF
            n = params[0] if params else 1
            s.cursor_col = min(s.cols - 1, s.cursor_col + n)

        elif cmd == 'D':  # CUB
            n = params[0] if params else 1
            s.cursor_col = max(0, s.cursor_col - n)

        elif cmd == 'G':  # CHA
            col = (params[0] if params else 1) - 1
            s.cursor_col = max(0, min(col, s.cols - 1))

        elif cmd == 'K':  # EL – erase in line
            mode = params[0] if params else 0
            r = s.cursor_row
            if mode == 0:   # cursor to end
                for c in range(s.cursor_col, s.cols):
                    s.cells[r][c] = Cell(char=' ', attrs=self.attrs)
            elif mode == 1: # start to cursor
                for c in range(0, s.cursor_col + 1):
                    s.cells[r][c] = Cell(char=' ', attrs=self.attrs)
            elif mode == 2: # whole line
                for c in range(s.cols):
                    s.cells[r][c] = Cell(char=' ', attrs=self.attrs)

        elif cmd == 'J':  # ED – erase in display
            mode = params[0] if params else 0
            if mode == 0:   # cursor to end of display
                for c in range(s.cursor_col, s.cols):
                    s.cells[s.cursor_row][c] = Cell(char=' ', attrs=self.attrs)
                for r in range(s.cursor_row + 1, s.rows):
                    for c in range(s.cols):
                        s.cells[r][c] = Cell(char=' ', attrs=self.attrs)
            elif mode == 1: # start to cursor
                for r in range(0, s.cursor_row):
                    for c in range(s.cols):
                        s.cells[r][c] = Cell(char=' ', attrs=self.attrs)
                for c in range(0, s.cursor_col + 1):
                    s.cells[s.cursor_row][c] = Cell(char=' ', attrs=self.attrs)
            elif mode == 2: # whole display
                for r in range(s.rows):
                    for c in range(s.cols):
                        s.cells[r][c] = Cell(char=' ', attrs=self.attrs)

        elif cmd == 'X':  # ECH – erase characters
            n = params[0] if params else 1
            r = s.cursor_row
            for c in range(s.cursor_col, min(s.cursor_col + n, s.cols)):
                s.cells[r][c] = Cell(char=' ', attrs=self.attrs)

        elif cmd == 'm':  # SGR
            self._handle_sgr(params if params else [0])

    def _handle_sgr(self, params: list):
        fg = self.attrs.fg
        bg = self.attrs.bg
        bold = self.attrs.bold
        italic = self.attrs.italic
        underline = self.attrs.underline
        inverse = self.attrs.inverse

        i = 0
        while i < len(params):
            p = params[i]
            if p == 0:
                fg = bg = -1
                bold = italic = underline = inverse = False
            elif p == 1:
                bold = True
            elif p == 3:
                italic = True
            elif p == 4:
                underline = True
            elif p == 7:
                inverse = True
            elif p == 22:
                bold = False
            elif p == 23:
                italic = False
            elif p == 24:
                underline = False
            elif p == 27:
                inverse = False
            elif 30 <= p <= 37:
                fg = p - 30
            elif p == 38:
                if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                    fg = params[i + 2]
                    i += 2
            elif p == 39:
                fg = -1
            elif 40 <= p <= 47:
                bg = p - 40
            elif p == 48:
                if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                    bg = params[i + 2]
                    i += 2
            elif p == 49:
                bg = -1
            elif 90 <= p <= 97:
                fg = p - 90 + 8
            elif 100 <= p <= 107:
                bg = p - 100 + 8
            i += 1

        self.attrs = Attrs(fg=fg, bg=bg, bold=bold, italic=italic,
                           underline=underline, inverse=inverse)


# ---------------------------------------------------------------------------
# Full-screen renderer (reference implementation for size comparison)
# ---------------------------------------------------------------------------

def _sgr_encode(current: Attrs, target: Attrs) -> bytes:
    """Generate SGR escape code bytes to transition from current to target attrs.

    Chooses the shorter of incremental-change vs reset-and-rebuild.
    """
    if current == target:
        return b''

    # --- incremental approach ---
    inc = []
    if current.bold != target.bold:
        inc.append(1 if target.bold else 22)
    if current.italic != target.italic:
        inc.append(3 if target.italic else 23)
    if current.underline != target.underline:
        inc.append(4 if target.underline else 24)
    if current.inverse != target.inverse:
        inc.append(7 if target.inverse else 27)
    if current.fg != target.fg:
        inc.extend(_color_params(target.fg, foreground=True))
    if current.bg != target.bg:
        inc.extend(_color_params(target.bg, foreground=False))

    # --- reset approach ---
    rst = [0]
    if target.bold:
        rst.append(1)
    if target.italic:
        rst.append(3)
    if target.underline:
        rst.append(4)
    if target.inverse:
        rst.append(7)
    if target.fg != -1:
        rst.extend(_color_params(target.fg, foreground=True))
    if target.bg != -1:
        rst.extend(_color_params(target.bg, foreground=False))

    inc_s = ';'.join(str(p) for p in inc)
    rst_s = ';'.join(str(p) for p in rst)

    inc_b = f'\x1b[{inc_s}m'.encode() if inc else b''
    rst_b = f'\x1b[{rst_s}m'.encode()

    if not inc_b:
        return rst_b
    return inc_b if len(inc_b) <= len(rst_b) else rst_b


def _color_params(color: int, foreground: bool) -> list:
    """Return SGR parameter list for a colour value."""
    if color == -1:
        return [39 if foreground else 49]
    base = 30 if foreground else 40
    if 0 <= color <= 7:
        return [base + color]
    if 8 <= color <= 15:
        return [base + 60 + color - 8]
    return [base + 8, 5, color]


def render_full(screen: Screen) -> bytes:
    """Generate escape sequences to reproduce *screen* from a blank terminal.

    Used as a reference for diff-size comparison; intentionally writes every
    cell so the output size represents a worst-case full redraw.
    """
    out = bytearray()
    out += b'\x1b[0m\x1b[H\x1b[2J'  # reset, home, clear
    current = Attrs()

    for r in range(screen.rows):
        out += f'\x1b[{r + 1};1H'.encode()  # position at row start
        for c in range(screen.cols):
            cell = screen.cells[r][c]
            if cell.attrs != current:
                out += _sgr_encode(current, cell.attrs)
                current = cell.attrs
            out += cell.char.encode('ascii')

    # reset and final cursor
    if current != Attrs():
        out += b'\x1b[0m'
    out += f'\x1b[{screen.cursor_row + 1};{screen.cursor_col + 1}H'.encode()
    return bytes(out)
