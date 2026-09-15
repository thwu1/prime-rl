"""Generate an extra puzzle at test time to prevent hardcoded solutions."""

import random
import os


def trace_path(grid, n, start_row, start_col, direction):
    """Trace a sight line through the grid."""
    dr = [1, 0, -1, 0]
    dc = [0, 1, 0, -1]
    r, c = start_row, start_col
    reflected = False
    cells = []
    visited = set()
    while 0 <= r < n and 0 <= c < n:
        state = (r, c, direction)
        if state in visited:
            break
        visited.add(state)
        cell = grid[r][c]
        if cell == '/':
            direction = {0: 3, 1: 2, 2: 1, 3: 0}[direction]
            reflected = not reflected
        elif cell == '\\':
            direction = {0: 1, 1: 0, 2: 3, 3: 2}[direction]
            reflected = not reflected
        else:
            cells.append((r, c, reflected))
        r += dr[direction]
        c += dc[direction]
    return cells


def encode_grid(grid, n):
    """Encode grid cells into compact letter-based format."""
    desc = ""
    empty_count = 0
    for r in range(n):
        for c in range(n):
            cell = grid[r][c]
            if cell in ('.', 'G', 'V', 'Z'):
                empty_count += 1
            else:
                while empty_count > 26:
                    desc += 'z'
                    empty_count -= 26
                if empty_count > 0:
                    desc += chr(ord('a') + empty_count - 1)
                    empty_count = 0
                if cell == '\\':
                    desc += 'L'
                elif cell == '/':
                    desc += 'R'
    while empty_count > 26:
        desc += 'z'
        empty_count -= 26
    if empty_count > 0:
        desc += chr(ord('a') + empty_count - 1)
    return desc


def generate_puzzle(n, num_mirrors, seed):
    """Generate a random puzzle with a guaranteed valid solution."""
    random.seed(seed)
    grid = [['.' for _ in range(n)] for _ in range(n)]
    positions = [(r, c) for r in range(n) for c in range(n)]
    random.shuffle(positions)
    for r, c in positions[:num_mirrors]:
        grid[r][c] = random.choice(['/', '\\'])
    for r in range(n):
        for c in range(n):
            if grid[r][c] == '.':
                grid[r][c] = random.choice(['G', 'V', 'Z'])

    top, bottom, left, right = [], [], [], []

    for col in range(n):
        path = trace_path(grid, n, 0, col, 0)
        vis = sum(
            1 if (grid[r2][c2] == 'Z' or
                  (grid[r2][c2] == 'G' and not refl) or
                  (grid[r2][c2] == 'V' and refl))
            else 0
            for r2, c2, refl in path
        )
        top.append(vis)

    for col in range(n):
        path = trace_path(grid, n, n - 1, col, 2)
        vis = sum(
            1 if (grid[r2][c2] == 'Z' or
                  (grid[r2][c2] == 'G' and not refl) or
                  (grid[r2][c2] == 'V' and refl))
            else 0
            for r2, c2, refl in path
        )
        bottom.append(vis)

    for row in range(n):
        path = trace_path(grid, n, row, 0, 1)
        vis = sum(
            1 if (grid[r2][c2] == 'Z' or
                  (grid[r2][c2] == 'G' and not refl) or
                  (grid[r2][c2] == 'V' and refl))
            else 0
            for r2, c2, refl in path
        )
        left.append(vis)

    for row in range(n):
        path = trace_path(grid, n, row, n - 1, 3)
        vis = sum(
            1 if (grid[r2][c2] == 'Z' or
                  (grid[r2][c2] == 'G' and not refl) or
                  (grid[r2][c2] == 'V' and refl))
            else 0
            for r2, c2, refl in path
        )
        right.append(vis)

    g = sum(row.count('G') for row in grid)
    v = sum(row.count('V') for row in grid)
    z = sum(row.count('Z') for row in grid)

    puzzle_grid = [
        ['.' if grid[r][c] in ('G', 'V', 'Z') else grid[r][c]
         for c in range(n)]
        for r in range(n)
    ]

    return n, puzzle_grid, top, bottom, left, right, g, v, z


def write_puzzle_encoded(filepath, n, grid, top, bottom, left, right, g, v, z):
    """Write puzzle as an encoded game description string."""
    desc = encode_grid(grid, n)
    clues = top + bottom + left + right + [g, v, z]
    game_desc = f"{n}x{n}:{desc},{','.join(map(str, clues))}"
    with open(filepath, 'w') as f:
        f.write(game_desc + '\n')


if __name__ == '__main__':
    os.makedirs('/app/puzzles', exist_ok=True)
    n, grid, top, bottom, left, right, g, v, z = generate_puzzle(5, 3, 31415)
    write_puzzle_encoded(
        '/app/puzzles/puzzle_5.txt', n, grid, top, bottom, left, right, g, v, z
    )
    print("Generated extra puzzle: puzzle_5.txt")
