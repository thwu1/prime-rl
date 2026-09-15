#!/usr/bin/env python3
"""Interactive fixture: navigable list responding to j/k/q keys."""
import sys
import tty
import termios

items = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
selected = 0


def render():
    sys.stdout.write('\x1b[2J\x1b[H')
    for i, item in enumerate(items):
        if i == selected:
            sys.stdout.write(
                f'\x1b[{i + 1};1H\x1b[7m> {item:<18}\x1b[0m'
            )
        else:
            sys.stdout.write(f'\x1b[{i + 1};1H  {item}')
    sys.stdout.write(f'\x1b[7;1HSelected: {selected}')
    sys.stdout.write(f'\x1b[{selected + 1};1H')
    sys.stdout.flush()


old_settings = termios.tcgetattr(sys.stdin)
try:
    tty.setraw(sys.stdin.fileno())
    render()
    while True:
        ch = sys.stdin.read(1)
        if ch == 'q':
            break
        elif ch == 'j':
            selected = min(len(items) - 1, selected + 1)
        elif ch == 'k':
            selected = max(0, selected - 1)
        render()
finally:
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
    sys.stdout.write('\x1b[2J\x1b[H')
    sys.stdout.flush()
