#!/usr/bin/env python3
"""Generate Undead puzzle instances with diverse clue distributions."""
import random
import os


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
    """Try many seeds and pick the puzzle with most diverse clue set."""
    best = None
    best_score = -1

    for attempt in range(200):
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


def write_puzzle(fp, n, mirrors, v, g, z, t, b, l, r):
    with open(fp, 'w') as f:
        f.write("size: {}\n".format(n))
        f.write("vampires: {}\n".format(v))
        f.write("ghosts: {}\n".format(g))
        f.write("zombies: {}\n".format(z))
        f.write("mirrors:\n")
        for (mr, mc) in sorted(mirrors.keys()):
            f.write("  {},{} {}\n".format(mr, mc, mirrors[(mr, mc)]))
        f.write("top: {}\n".format(' '.join(map(str, t))))
        f.write("bottom: {}\n".format(' '.join(map(str, b))))
        f.write("left: {}\n".format(' '.join(map(str, l))))
        f.write("right: {}\n".format(' '.join(map(str, r))))


def main():
    os.makedirs('/app/puzzles', exist_ok=True)
    os.makedirs('/app/solutions', exist_ok=True)

    configs = [
        (4, 4, 42),
        (5, 6, 137),
        (6, 9, 256),
        (7, 12, 389),
        (8, 16, 512),
    ]

    for i, (n, nm, seed) in enumerate(configs, 1):
        grid, mirrors, v, g, z, t, b, l, r = generate(n, nm, seed)
        write_puzzle('/app/puzzles/puzzle_{}.txt'.format(i), n, mirrors, v, g, z, t, b, l, r)
        print("Puzzle {}: {}x{}, {} mirrors, {}V {}G {}Z".format(i, n, n, nm, v, g, z))


if __name__ == '__main__':
    main()
