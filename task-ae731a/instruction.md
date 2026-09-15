A terminal emulator library at `/app/terminal_emulator.py` processes ANSI escape sequences and maintains a virtual screen buffer. Its `snapshot()` method returns a structured cell grid — see `/app/spec.md` for the snapshot format and the full ANSI protocol it supports. Two fixture applications are provided:

- `/app/fixtures/static_screen.py` — renders a fixed layout using various ANSI attributes (bold, colors, underline, reverse) and positions the cursor at a known location.
- `/app/fixtures/interactive_screen.py` — renders a navigable list that responds to `j`/`k`/`q` keystrokes, highlights the selected row, and displays a selection counter.

tmux is installed and configured at `/root/.tmux.conf` with 256-color/RGB support and the status bar disabled.

Create `/app/tui_harness.py` exporting a `TUISession` class that enables automated end-to-end testing of terminal applications by managing real terminal sessions. The class must conform to this interface:

```python
class TUISession:
    session_name: str  # unique identifier for the underlying terminal session

    def __init__(self, cmd: list[str], rows: int = 24, cols: int = 80, timeout: float = 5.0):
        """Launch cmd in an isolated terminal session with the given dimensions."""

    def send_keys(self, keys: str, literal: bool = False) -> None:
        """Send keystrokes to the running application. literal=True sends raw characters."""

    def capture(self) -> dict:
        """Return a snapshot dict identical in structure to TerminalEmulator.snapshot()."""

    def wait_for_text(self, text: str, timeout: float | None = None) -> bool:
        """Poll until text appears on screen or timeout expires. Returns True if found."""

    def close(self) -> None:
        """Terminate the session and clean up resources."""
```

The `capture()` method must return snapshots that are structurally identical to `TerminalEmulator.snapshot()` — same top-level keys, same cell fields, same color encoding, same dimensions — with per-cell attributes accurately reflecting what the running application has rendered (including foreground/background colors at 8-color and 256-color depth, bold, underline, and reverse). Every row must contain exactly `cols` cells, and cursor position must be accurate. Multiple `TUISession` instances must coexist without interfering with each other.