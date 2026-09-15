"""
tmux-based terminal diff validator — implement validate_via_tmux().

"""

from terminal import Screen


def validate_via_tmux(prev: Screen, diff_bytes: bytes) -> Screen:
    """Validate a diff by applying it through a real tmux terminal session.

    Renders prev into a temporary tmux pane, applies diff_bytes through the
    terminal emulator, captures the resulting screen state, and returns it
    as a Screen object with all cell attributes and cursor position set.

    See terminal.py for the Screen data model.
    """
    raise NotImplementedError("Implement tmux-based validation")
