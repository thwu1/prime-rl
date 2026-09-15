#!/usr/bin/env python3
"""Collapse perf script output into folded format.

Equivalent to FlameGraph/stackcollapse-perf.pl.

Usage: stackcollapse.py <perf-script-file> [comm-filter]

Output (to stdout): one line per unique stack, root-first, semicolon-delimited:
    comm;frame1;frame2;...;leaf count
"""

import re
import sys
from collections import defaultdict


def parse_perf_script(path, comm_filter=None):
    """Parse perf script output and return collapsed stacks."""
    stacks = defaultdict(int)

    header_re = re.compile(r'^(\S+)\s+\d+')
    frame_re = re.compile(r'^\s+\S+\s+(\S+)')

    current_comm = None
    current_frames = []

    with open(path) as f:
        for line in f:
            line = line.rstrip('\n')

            if not line or line.startswith('#'):
                # End of event block
                if current_comm and current_frames:
                    if comm_filter is None or current_comm == comm_filter:
                        # Frames are leaf-first in perf output; reverse to root-first
                        root_first = list(reversed(current_frames))
                        key = current_comm + ';' + ';'.join(root_first)
                        stacks[key] += 1
                    current_comm = None
                    current_frames = []
                continue

            m = header_re.match(line)
            if m and ':' in line and ('cpu-clock' in line or 'cycles' in line
                                       or 'task-clock' in line or ':ppp:' in line
                                       or 'clock' in line):
                # Flush any pending event
                if current_comm and current_frames:
                    if comm_filter is None or current_comm == comm_filter:
                        root_first = list(reversed(current_frames))
                        key = current_comm + ';' + ';'.join(root_first)
                        stacks[key] += 1

                current_comm = m.group(1)
                current_frames = []
                continue

            fm = frame_re.match(line)
            if fm and current_comm is not None:
                symbol = fm.group(1)
                # Strip offset (+0x...)
                symbol = re.sub(r'\+0x[0-9a-fA-F]+$', '', symbol)
                current_frames.append(symbol)

    # Flush last event
    if current_comm and current_frames:
        if comm_filter is None or current_comm == comm_filter:
            root_first = list(reversed(current_frames))
            key = current_comm + ';' + ';'.join(root_first)
            stacks[key] += 1

    return stacks


def main():
    if len(sys.argv) < 2:
        print("Usage: stackcollapse.py <perf-script-file> [comm-filter]",
              file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    comm_filter = sys.argv[2] if len(sys.argv) > 2 else None

    stacks = parse_perf_script(path, comm_filter)

    for stack in sorted(stacks.keys()):
        print(f"{stack} {stacks[stack]}")


if __name__ == '__main__':
    main()
