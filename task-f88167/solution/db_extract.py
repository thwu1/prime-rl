#!/usr/bin/env python3
"""Extract Sokoban levels from the normalized database into text files."""

import sqlite3
import os

DB_PATH = "/app/sokoban.db"
OUTPUT_DIR = "/tmp/sokoban_levels"

CELL_TO_CHAR = {
    'wall': '#',
    'box': '$',
    'goal': '.',
    'player': '@',
    'player_on_goal': '+',
    'box_on_goal': '*',
}


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    levels = c.execute('SELECT id, width, height FROM levels ORDER BY id').fetchall()

    for level_id, width, height in levels:
        cells = c.execute(
            'SELECT row, col, cell_type FROM cells WHERE level_id = ?',
            (level_id,)
        ).fetchall()

        grid = [[' '] * width for _ in range(height)]
        for row, col, cell_type in cells:
            if row < height and col < width:
                grid[row][col] = CELL_TO_CHAR.get(cell_type, ' ')

        filepath = os.path.join(OUTPUT_DIR, f"level_{level_id}.txt")
        with open(filepath, 'w') as f:
            for line in grid:
                f.write(''.join(line).rstrip() + '\n')

        print(f"Extracted level {level_id} ({width}x{height}) to {filepath}")

    conn.close()


if __name__ == '__main__':
    main()
