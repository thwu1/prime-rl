#!/usr/bin/env python3
"""Static fixture: renders known ANSI content and waits forever."""
import sys
import time

sys.stdout.write('\x1b[2J\x1b[H')
# Row 0: bold + red foreground (8-color)
sys.stdout.write('\x1b[1;31mBoldRed\x1b[0m')
# Row 1: 256-color foreground (46 = bright green)
sys.stdout.write('\x1b[2;1H\x1b[38;5;46mGreen256\x1b[0m')
# Row 2: underline + blue background (8-color bg)
sys.stdout.write('\x1b[3;1H\x1b[4;44mUnderBluBg\x1b[0m')
# Row 3: reverse video
sys.stdout.write('\x1b[4;1H\x1b[7mReversed\x1b[0m')
# Row 4: plain text (default attributes)
sys.stdout.write('\x1b[5;1HPlainText')
# Position cursor at row 5 col 0 (CUP is 1-indexed)
sys.stdout.write('\x1b[6;1H')
sys.stdout.flush()
time.sleep(3600)
