#!/usr/bin/env python3
"""Undead puzzle solution validator.

Usage: validate PUZZLE_ID SOLUTION_FILE

Checks a solution file against puzzle constraints from /app/puzzles.db.
Exit code 0 = valid, 1 = invalid, 2 = usage error.

Solution file format: N lines, each with N space-separated tokens.
Mirror cells use '/' or '\\'. Monster cells use 'V', 'G', or 'Z'.
"""

import sys
import os
import sqlite3

DB_PATH = '/app/puzzles.db'


def load_puzzle(puzzle_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute('SELECT dim, nv, ng, nz FROM instances WHERE iid = ?',
                (puzzle_id,))
    row = cur.fetchone()
    if not row:
        print("Error: puzzle {} not found".format(puzzle_id), file=sys.stderr)
        sys.exit(2)

    dim, nv, ng, nz = row

    mirrors = {}
    cur.execute('SELECT r, c, kind FROM obstacles WHERE iid = ?',
                (puzzle_id,))
    for r, c, kind in cur.fetchall():
        mirrors[(r, c)] = '/' if kind == 'F' else '\\'

    clues = {'T': {}, 'B': {}, 'L': {}, 'R': {}}
    cur.execute('SELECT edge, pos, val FROM constraints WHERE iid = ?',
                (puzzle_id,))
    for edge, pos, val in cur.fetchall():
        clues[edge][pos] = val

    top = [clues['T'][i] for i in range(dim)]
    bottom = [clues['B'][i] for i in range(dim)]
    left = [clues['L'][i] for i in range(dim)]
    right = [clues['R'][i] for i in range(dim)]

    conn.close()
    return dim, nv, ng, nz, mirrors, top, bottom, left, right


def trace_sight(grid, n, sr, sc, dr, dc):
    count = 0
    reflected = False
    r, c = sr, sc
    while 0 <= r < n and 0 <= c < n:
        cell = grid[r][c]
        if cell == '/':
            dr, dc = -dc, -dr
            reflected = True
        elif cell == '\\':
            dr, dc = dc, dr
            reflected = True
        elif cell == 'Z':
            count += 1
        elif cell == 'V' and not reflected:
            count += 1
        elif cell == 'G' and reflected:
            count += 1
        r += dr
        c += dc
    return count


def validate(puzzle_id, solution_file):
    dim, nv, ng, nz, mirrors, top, bottom, left, right = load_puzzle(
        puzzle_id)

    with open(solution_file) as f:
        lines = f.read().strip().split('\n')

    grid = [line.strip().split() for line in lines]

    if len(grid) != dim:
        print("INVALID: expected {} rows, got {}".format(dim, len(grid)))
        return False

    for r in range(dim):
        if len(grid[r]) != dim:
            print("INVALID: row {}: expected {} cols, got {}".format(
                r, dim, len(grid[r])))
            return False

    for (r, c), m in mirrors.items():
        if grid[r][c] != m:
            print("INVALID: mirror at ({},{}): expected '{}', got '{}'".format(
                r, c, m, grid[r][c]))
            return False

    vc = gc = zc = 0
    for r in range(dim):
        for c in range(dim):
            cell = grid[r][c]
            if (r, c) in mirrors:
                continue
            if cell not in ('V', 'G', 'Z'):
                print("INVALID: cell ({},{}): expected V/G/Z, got '{}'".format(
                    r, c, cell))
                return False
            if cell == 'V':
                vc += 1
            elif cell == 'G':
                gc += 1
            else:
                zc += 1

    if vc != nv:
        print("INVALID: expected {} vampires, got {}".format(nv, vc))
        return False
    if gc != ng:
        print("INVALID: expected {} ghosts, got {}".format(ng, gc))
        return False
    if zc != nz:
        print("INVALID: expected {} zombies, got {}".format(nz, zc))
        return False

    for c in range(dim):
        v = trace_sight(grid, dim, 0, c, 1, 0)
        if v != top[c]:
            print("INVALID: top clue col {}: expected {}, got {}".format(
                c, top[c], v))
            return False

    for c in range(dim):
        v = trace_sight(grid, dim, dim - 1, c, -1, 0)
        if v != bottom[c]:
            print("INVALID: bottom clue col {}: expected {}, got {}".format(
                c, bottom[c], v))
            return False

    for r in range(dim):
        v = trace_sight(grid, dim, r, 0, 0, 1)
        if v != left[r]:
            print("INVALID: left clue row {}: expected {}, got {}".format(
                r, left[r], v))
            return False

    for r in range(dim):
        v = trace_sight(grid, dim, r, dim - 1, 0, -1)
        if v != right[r]:
            print("INVALID: right clue row {}: expected {}, got {}".format(
                r, right[r], v))
            return False

    print("VALID")
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2 or '--help' in sys.argv or '-h' in sys.argv:
        print(__doc__)
        sys.exit(0)

    if len(sys.argv) != 3:
        print("Usage: validate PUZZLE_ID SOLUTION_FILE", file=sys.stderr)
        sys.exit(2)

    try:
        pid = int(sys.argv[1])
    except ValueError:
        print("Error: PUZZLE_ID must be integer, got '{}'".format(
            sys.argv[1]), file=sys.stderr)
        sys.exit(2)

    sol_file = sys.argv[2]
    if not os.path.exists(sol_file):
        print("Error: file not found: {}".format(sol_file), file=sys.stderr)
        sys.exit(2)

    ok = validate(pid, sol_file)
    sys.exit(0 if ok else 1)
