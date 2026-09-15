"""TUI testing harness using tmux for terminal session management and
ANSI escape sequence capture/parsing."""

import subprocess
import time
import os
import shlex


class TUISession:
    """Automated testing interface for terminal applications via tmux.

    Launches a command in a detached tmux session, provides methods to
    send keystrokes, capture the full screen state (with parsed ANSI
    attributes), and poll for text appearance.
    """

    _counter = 0

    def __init__(self, cmd, rows=24, cols=80, timeout=5.0):
        TUISession._counter += 1
        self.session_name = f"tui_{os.getpid()}_{TUISession._counter}"
        self.rows = rows
        self.cols = cols
        self.timeout = timeout

        cmd_str = shlex.join(cmd) if isinstance(cmd, list) else cmd
        subprocess.run(
            [
                "tmux", "new-session", "-d",
                "-s", self.session_name,
                "-x", str(cols),
                "-y", str(rows),
                cmd_str,
            ],
            check=True,
            capture_output=True,
        )
        time.sleep(0.5)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_keys(self, keys, literal=False):
        """Send keystrokes to the tmux pane."""
        cmd = ["tmux", "send-keys", "-t", self.session_name]
        if literal:
            cmd.append("-l")
        cmd.append(keys)
        subprocess.run(cmd, check=True, capture_output=True)

    def capture(self):
        """Capture the current screen state as a snapshot dict.

        Returns a dict with the same structure as
        ``TerminalEmulator.snapshot()``: rows, cols, cursor, and a
        screen grid where each cell has char, fg, bg, bold, underline,
        and reverse fields.
        """
        raw = subprocess.run(
            ["tmux", "capture-pane", "-t", self.session_name, "-e", "-p"],
            capture_output=True, text=True,
        ).stdout

        cursor_out = subprocess.run(
            [
                "tmux", "display-message",
                "-t", self.session_name,
                "-p", "#{cursor_x} #{cursor_y}",
            ],
            capture_output=True, text=True,
        ).stdout.strip()

        parts = cursor_out.split()
        cursor_col = int(parts[0])
        cursor_row = int(parts[1])

        screen = self._parse_capture(raw)

        return {
            "rows": self.rows,
            "cols": self.cols,
            "cursor": {"row": cursor_row, "col": cursor_col},
            "screen": screen,
        }

    def wait_for_text(self, text, timeout=None):
        """Poll until *text* appears on screen or *timeout* expires."""
        timeout = timeout or self.timeout
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = subprocess.run(
                ["tmux", "capture-pane", "-t", self.session_name, "-p"],
                capture_output=True, text=True,
            ).stdout
            if text in raw:
                return True
            time.sleep(0.1)
        return False

    def close(self):
        """Kill the tmux session."""
        subprocess.run(
            ["tmux", "kill-session", "-t", self.session_name],
            capture_output=True,
        )

    # ------------------------------------------------------------------
    # ANSI parsing internals
    # ------------------------------------------------------------------

    def _parse_capture(self, raw):
        """Parse ``tmux capture-pane -e -p`` output into a cell grid.

        SGR attribute state is tracked across line boundaries (tmux
        carries state over between rows in its ``-e`` output).  Lines
        shorter than ``self.cols`` are padded with default-attribute
        space cells.
        """
        lines = raw.split("\n")
        if lines and lines[-1] == "":
            lines.pop()

        screen = []
        fg = None
        bg = None
        bold = False
        underline = False
        reverse = False

        for r in range(self.rows):
            row_cells = []
            if r < len(lines):
                line = lines[r]
                i = 0
                while i < len(line):
                    if (
                        line[i] == "\x1b"
                        and i + 1 < len(line)
                        and line[i + 1] == "["
                    ):
                        j = i + 2
                        while j < len(line) and (
                            line[j].isdigit() or line[j] == ";"
                        ):
                            j += 1
                        if j < len(line) and line[j] == "m":
                            params_str = line[i + 2 : j]
                            fg, bg, bold, underline, reverse = _parse_sgr(
                                params_str, fg, bg, bold, underline, reverse,
                            )
                            i = j + 1
                        else:
                            if j < len(line):
                                j += 1
                            i = j
                    else:
                        row_cells.append(
                            _cell(line[i], fg, bg, bold, underline, reverse)
                        )
                        i += 1

            while len(row_cells) < self.cols:
                row_cells.append(
                    _cell(" ", None, None, False, False, False)
                )
            screen.append(row_cells[: self.cols])

        return screen


# ----------------------------------------------------------------------
# Module-level helpers (no instance state needed)
# ----------------------------------------------------------------------

def _parse_sgr(params_str, fg, bg, bold, underline, reverse):
    """Apply an SGR parameter string to the current attribute state."""
    if not params_str:
        return None, None, False, False, False

    parts = params_str.split(";")
    i = 0
    while i < len(parts):
        try:
            val = int(parts[i]) if parts[i] else 0
        except ValueError:
            i += 1
            continue

        if val == 0:
            fg = bg = None
            bold = underline = reverse = False
        elif val == 1:
            bold = True
        elif val == 4:
            underline = True
        elif val == 7:
            reverse = True
        elif val == 22:
            bold = False
        elif val == 24:
            underline = False
        elif val == 27:
            reverse = False
        elif 30 <= val <= 37:
            fg = val - 30
        elif val == 39:
            fg = None
        elif 40 <= val <= 47:
            bg = val - 40
        elif val == 49:
            bg = None
        elif val in (38, 48):
            if i + 1 < len(parts):
                try:
                    sub = int(parts[i + 1]) if parts[i + 1] else 0
                except ValueError:
                    i += 2
                    continue
                if sub == 5 and i + 2 < len(parts):
                    try:
                        cidx = int(parts[i + 2]) if parts[i + 2] else 0
                    except ValueError:
                        i += 3
                        continue
                    if val == 38:
                        fg = cidx
                    else:
                        bg = cidx
                    i += 2
                elif sub == 2 and i + 4 < len(parts):
                    try:
                        rv = int(parts[i + 2]) if parts[i + 2] else 0
                        gv = int(parts[i + 3]) if parts[i + 3] else 0
                        bv = int(parts[i + 4]) if parts[i + 4] else 0
                    except ValueError:
                        i += 5
                        continue
                    if val == 38:
                        fg = [rv, gv, bv]
                    else:
                        bg = [rv, gv, bv]
                    i += 4
        i += 1

    return fg, bg, bold, underline, reverse


def _cell(char, fg, bg, bold, underline, reverse):
    """Build a snapshot-compatible cell dict."""
    return {
        "char": char,
        "fg": list(fg) if isinstance(fg, list) else fg,
        "bg": list(bg) if isinstance(bg, list) else bg,
        "bold": bold,
        "underline": underline,
        "reverse": reverse,
    }
