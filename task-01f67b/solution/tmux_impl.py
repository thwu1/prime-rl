"""
Solution: tmux-based terminal diff validator.

Validates diffs by rendering screen states into live tmux sessions,
applying escape sequences through tmux's terminal emulator, and
capturing the resulting pane state.

"""

import os
import subprocess
import tempfile
import time

from terminal import Screen, Cell, Attrs, VTParser, render_full


def validate_via_tmux(prev: Screen, diff_bytes: bytes) -> Screen:
    """Validate a diff by applying it through a real tmux terminal session."""
    session_name = "vtvalidate"
    socket_name = f"vtdiff_{os.getpid()}"
    data_file = None
    config_file = None

    try:
        # Prepare payload: render prev state, then apply diff
        payload = render_full(prev)
        if diff_bytes:
            payload += diff_bytes

        # Write payload to temp file
        fd, data_file = tempfile.mkstemp(suffix='.bin', prefix='vtdata_')
        with os.fdopen(fd, 'wb') as f:
            f.write(payload)

        # Create tmux config that disables status bar for full pane dimensions
        fd2, config_file = tempfile.mkstemp(suffix='.conf', prefix='tmux_vt_')
        with os.fdopen(fd2, 'w') as f:
            f.write("set -g status off\n")

        # Kill any existing server on this socket
        subprocess.run(
            ['tmux', '-L', socket_name, 'kill-server'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Create detached session with exact pane dimensions.
        # Use stty -opost to disable output processing (prevents LF -> CR+LF
        # translation that would break cursor positioning in escape sequences).
        # cat outputs the escape sequence data; sleep holds the pane open.
        subprocess.run([
            'tmux', '-L', socket_name, '-f', config_file,
            'new-session', '-d', '-s', session_name,
            '-x', str(prev.cols), '-y', str(prev.rows),
            'bash', '-c',
            f'stty -opost 2>/dev/null; cat {data_file}; sleep 120'
        ], check=True, capture_output=True)

        # Wait for cat to output data and tmux to process escape sequences
        time.sleep(1.0)

        # Capture pane state with ANSI escape sequences preserved
        capture_result = subprocess.run(
            ['tmux', '-L', socket_name,
             'capture-pane', '-t', session_name, '-e', '-p'],
            check=True, capture_output=True
        )
        captured = capture_result.stdout.decode('utf-8', errors='replace')

        # Get cursor position from tmux pane variables (0-based)
        cursor_result = subprocess.run(
            ['tmux', '-L', socket_name,
             'display-message', '-t', session_name,
             '-p', '#{cursor_x} #{cursor_y}'],
            check=True, capture_output=True, text=True
        )
        parts = cursor_result.stdout.strip().split()
        cursor_x = int(parts[0])
        cursor_y = int(parts[1])

        # Parse captured ANSI output into Screen
        screen = _parse_capture(captured, prev.rows, prev.cols)
        screen.cursor_col = cursor_x
        screen.cursor_row = cursor_y

        return screen

    finally:
        # Kill the isolated tmux server (cleans up all sessions and panes)
        subprocess.run(
            ['tmux', '-L', socket_name, 'kill-server'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        for f in [data_file, config_file]:
            if f and os.path.exists(f):
                try:
                    os.unlink(f)
                except OSError:
                    pass


def _parse_capture(text: str, rows: int, cols: int) -> Screen:
    """Parse tmux capture-pane -e -p output into a Screen object.

    Uses VTParser to process each line of the capture output, which contains
    ANSI SGR escape codes for text attributes. Attribute state is maintained
    across lines since tmux may not re-emit unchanged attributes.
    """
    screen = Screen(rows, cols)
    parser = VTParser(screen)

    lines = text.split('\n')
    # Remove trailing empty lines from capture output
    while lines and lines[-1] == '':
        lines.pop()

    for r, line in enumerate(lines[:rows]):
        # Position cursor at start of this row
        screen.cursor_row = r
        screen.cursor_col = 0
        # Process the line (ANSI SGR codes + printable characters)
        parser.process(line.encode('utf-8', errors='replace'))

    return screen
