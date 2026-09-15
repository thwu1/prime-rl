#!/usr/bin/env python3
"""Build the Sokoban tournament database from level text files."""
import sqlite3
import sys
import os

LEVEL_FILES = [
    (1, "level_1.txt"),
    (2, "level_2.txt"),
    (3, "level_3.txt"),
    (4, "level_4.txt"),
]

STORED_TYPES = {
    '#': 'wall',
    '$': 'box',
    '.': 'goal',
    '@': 'player',
    '+': 'player_on_goal',
    '*': 'box_on_goal',
}


def main():
    levels_dir = sys.argv[1] if len(sys.argv) > 1 else '/tmp/build_levels'
    db_path = '/app/sokoban.db'

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE levels (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        width INTEGER NOT NULL,
        height INTEGER NOT NULL
    )''')

    c.execute('''CREATE TABLE cells (
        level_id INTEGER REFERENCES levels(id),
        row INTEGER NOT NULL,
        col INTEGER NOT NULL,
        cell_type TEXT NOT NULL CHECK(cell_type IN (
            'wall', 'box', 'goal', 'player', 'player_on_goal', 'box_on_goal'
        )),
        PRIMARY KEY (level_id, row, col)
    )''')

    c.execute('''CREATE TABLE solutions (
        level_id INTEGER PRIMARY KEY REFERENCES levels(id),
        moves TEXT NOT NULL,
        push_count INTEGER NOT NULL,
        move_count INTEGER NOT NULL,
        solved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    for level_id, filename in LEVEL_FILES:
        filepath = os.path.join(levels_dir, filename)
        with open(filepath) as f:
            lines = f.read().rstrip('\n').split('\n')
        lines = [l for l in lines if not l.startswith(';')]

        height = len(lines)
        width = max(len(l) for l in lines)

        c.execute('INSERT INTO levels VALUES (?, ?, ?, ?)',
                  (level_id, f"Level {level_id}", width, height))

        for r, line in enumerate(lines):
            for col, ch in enumerate(line):
                if ch in STORED_TYPES:
                    c.execute('INSERT INTO cells VALUES (?, ?, ?, ?)',
                              (level_id, r, col, STORED_TYPES[ch]))

    conn.commit()
    conn.close()
    print(f"Database created at {db_path}")


if __name__ == '__main__':
    main()
