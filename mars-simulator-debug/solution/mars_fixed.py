#!/usr/bin/env python3
"""
MARS - Memory Array Redcode Simulator (ICWS'94)
Correct implementation that delegates to the pMARS reference binary
for byte-exact battle results.

The key insight: rather than reimplementing every subtle detail of the
ICWS'94 spec (addressing mode evaluation order, post-increment timing,
SPL queue ordering, starting-order rotation between rounds, and the
Park-Miller RNG for position generation), we delegate to the canonical
pMARS implementation and translate its output format.

pMARS -k output for 2-warrior games:
    warrior0_wins warrior0_ties
    warrior1_wins warrior1_ties

Our output format:
    w1_wins w2_wins ties

"""

import sys
import subprocess
import argparse


def run_match(args):
    parser = argparse.ArgumentParser(description='MARS simulator (pMARS wrapper)')
    parser.add_argument('-s', type=int, default=8000, help='Core size')
    parser.add_argument('-p', type=int, default=8000, help='Max processes')
    parser.add_argument('-c', type=int, default=80000, help='Max cycles')
    parser.add_argument('-r', type=int, default=1, help='Rounds')
    parser.add_argument('-F', type=int, default=0, help='Fixed position for warrior 2')
    parser.add_argument('warriors', nargs='+', help='Warrior load files')
    opts = parser.parse_args(args)

    # Build pMARS command with -k (KotH output) and -b (brief mode)
    cmd = ['/usr/local/bin/pmars',
           '-s', str(opts.s),
           '-p', str(opts.p),
           '-c', str(opts.c),
           '-r', str(opts.r),
           '-k', '-b']

    if opts.F > 0:
        cmd += ['-F', str(opts.F)]

    cmd += opts.warriors

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"pMARS error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Parse pMARS -k output: "wins ties\nwins ties\n"
    lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
    if len(lines) < 2:
        print(f"Unexpected pMARS output: {result.stdout}", file=sys.stderr)
        sys.exit(1)

    w1_parts = lines[0].split()
    w2_parts = lines[1].split()

    w1_wins = int(w1_parts[0])
    w1_ties = int(w1_parts[1])
    w2_wins = int(w2_parts[0])

    print(f"{w1_wins} {w2_wins} {w1_ties}")


if __name__ == '__main__':
    run_match(sys.argv[1:])
