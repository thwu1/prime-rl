#!/usr/bin/env python3
"""Demo: shows the expected interface for screen_diff.py and verifies a sample scenario."""

import sys
sys.path.insert(0, '/app')

from terminal_emulator import TerminalEmulator

try:
    from screen_diff import generate_diff
except ImportError:
    print("=" * 60)
    print("screen_diff module not found.")
    print()
    print("Create /app/screen_diff.py with a function:")
    print()
    print("  def generate_diff(before: dict, after: dict) -> bytes")
    print()
    print("  before, after: snapshots from TerminalEmulator.snapshot()")
    print("  returns: ANSI escape sequence bytes")
    print()
    print("The returned bytes, when fed to the emulator whose screen")
    print("matches 'before' (SGR reset, no pending wrap), must produce")
    print("a screen and cursor position matching 'after'.")
    print()
    print("The diff should skip unchanged cells, batch sequential")
    print("writes, and avoid redundant SGR changes.")
    print("=" * 60)
    sys.exit(1)

from baseline import naive_rewrite

# --- Scenario: minor text edit ---
emu1 = TerminalEmulator(5, 40)
emu1.feed(b"\x1b[1;31mHello World\x1b[0m\r\nLine two here\r\nThird line")
before = emu1.snapshot()

emu2 = TerminalEmulator(5, 40)
emu2.feed(b"\x1b[1;31mHello Earth\x1b[0m\r\nLine two here\r\nThird line")
after = emu2.snapshot()

diff = generate_diff(before, after)
naive = naive_rewrite(after)

print(f"Diff size:  {len(diff):>6} bytes")
print(f"Naive size: {len(naive):>6} bytes")
print(f"Ratio:      {len(diff) / len(naive) * 100:>6.1f}%")
print()

# Verify correctness
emu3 = TerminalEmulator(5, 40)
emu3.feed(b"\x1b[1;31mHello World\x1b[0m\r\nLine two here\r\nThird line")
emu3.feed(b'\x1b[0m')       # Reset SGR to known state
emu3.pending_wrap = False    # Clear pending wrap
emu3.feed(diff)

result = emu3.snapshot()
ok = True
for r in range(5):
    for c in range(40):
        if result['screen'][r][c] != after['screen'][r][c]:
            print(f"MISMATCH at ({r},{c}): got {result['screen'][r][c]}, "
                  f"expected {after['screen'][r][c]}")
            ok = False

if result['cursor'] != after['cursor']:
    print(f"CURSOR MISMATCH: got {result['cursor']}, expected {after['cursor']}")
    ok = False

if ok:
    print("PASS: diff correctly transforms before -> after")
else:
    print("FAIL: diff produces incorrect result")
    sys.exit(1)
