#!/usr/bin/env python3
"""Generate Undead puzzle instances and store in SQLite database."""
import random
import os
import sqlite3


def trace(grid, n, sr, sc, dr, dc):
    """Trace a sight line, counting visible monsters."""
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


def compute_clues(grid, n):
    t = [trace(grid, n, 0, c, 1, 0) for c in range(n)]
    b = [trace(grid, n, n - 1, c, -1, 0) for c in range(n)]
    l = [trace(grid, n, r, 0, 0, 1) for r in range(n)]
    ri = [trace(grid, n, r, n - 1, 0, -1) for r in range(n)]
    return t, b, l, ri


def generate(n, num_mirrors, base_seed):
    """Generate a puzzle with diverse clue distribution."""
    best = None
    best_score = -1

    for attempt in range(300):
        rng = random.Random(base_seed * 1000 + attempt)
        grid = [['.' for _ in range(n)] for _ in range(n)]

        positions = [(r, c) for r in range(n) for c in range(n)]
        rng.shuffle(positions)
        mirrors = {}
        for i in range(num_mirrors):
            r, c = positions[i]
            m = rng.choice(['/', '\\'])
            grid[r][c] = m
            mirrors[(r, c)] = m

        empty = [(r, c) for r in range(n) for c in range(n) if grid[r][c] == '.']
        ne = len(empty)
        vc = ne // 3
        gc = ne // 3
        zc = ne - vc - gc

        monsters = ['V'] * vc + ['G'] * gc + ['Z'] * zc
        rng.shuffle(monsters)
        for i, (r, c) in enumerate(empty):
            grid[r][c] = monsters[i]

        t, b, l, ri = compute_clues(grid, n)
        all_c = t + b + l + ri
        diversity = len(set(all_c))
        nonzero = sum(1 for x in all_c if x > 0)
        score = diversity * 10 + nonzero

        if score > best_score:
            best_score = score
            best = (grid, mirrors, vc, gc, zc, t, b, l, ri)

    return best


def main():
    db_path = '/app/puzzles.db'
    os.makedirs('/app/src', exist_ok=True)
    os.makedirs('/app/solutions', exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute('''CREATE TABLE instances (
        iid INTEGER PRIMARY KEY,
        dim INTEGER NOT NULL,
        nv INTEGER NOT NULL,
        ng INTEGER NOT NULL,
        nz INTEGER NOT NULL
    )''')

    cur.execute('''CREATE TABLE obstacles (
        iid INTEGER NOT NULL REFERENCES instances(iid),
        r INTEGER NOT NULL,
        c INTEGER NOT NULL,
        kind CHAR(1) NOT NULL,
        PRIMARY KEY (iid, r, c)
    )''')

    cur.execute('''CREATE TABLE constraints (
        iid INTEGER NOT NULL REFERENCES instances(iid),
        edge CHAR(1) NOT NULL,
        pos INTEGER NOT NULL,
        val INTEGER NOT NULL,
        PRIMARY KEY (iid, edge, pos)
    )''')

    configs = [
        (4, 4, 42),
        (5, 6, 137),
        (6, 9, 256),
        (7, 12, 389),
        (8, 16, 512),
        (9, 20, 673),
        (10, 25, 841),
    ]

    for i, (n, nm, seed) in enumerate(configs, 1):
        grid, mirrors, v, g, z, top, bot, left, right = generate(n, nm, seed)

        cur.execute('INSERT INTO instances VALUES (?,?,?,?,?)', (i, n, v, g, z))

        for (r, c), m in mirrors.items():
            kind = 'F' if m == '/' else 'B'
            cur.execute('INSERT INTO obstacles VALUES (?,?,?,?)', (i, r, c, kind))

        for pos, val in enumerate(top):
            cur.execute('INSERT INTO constraints VALUES (?,?,?,?)',
                        (i, 'T', pos, val))
        for pos, val in enumerate(bot):
            cur.execute('INSERT INTO constraints VALUES (?,?,?,?)',
                        (i, 'B', pos, val))
        for pos, val in enumerate(left):
            cur.execute('INSERT INTO constraints VALUES (?,?,?,?)',
                        (i, 'L', pos, val))
        for pos, val in enumerate(right):
            cur.execute('INSERT INTO constraints VALUES (?,?,?,?)',
                        (i, 'R', pos, val))

        print("Puzzle {}: {}x{}, {} mirrors, {}V {}G {}Z".format(
            i, n, n, nm, v, g, z))

    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()
