#!/usr/bin/env python3
"""Insert Sokoban solutions into the database with accurate metadata."""

import sqlite3
import os

DB_PATH = "/app/sokoban.db"
SOLUTIONS_DIR = "/tmp/sokoban_solutions"


def parse_level_from_db(conn, level_id):
    """Reconstruct level state from database cells."""
    c = conn.cursor()
    cells = c.execute(
        'SELECT row, col, cell_type FROM cells WHERE level_id = ?',
        (level_id,)
    ).fetchall()

    walls = set()
    boxes = set()
    goals = set()
    player = None

    for row, col, cell_type in cells:
        if cell_type == 'wall':
            walls.add((row, col))
        elif cell_type == 'box':
            boxes.add((row, col))
        elif cell_type == 'goal':
            goals.add((row, col))
        elif cell_type == 'player':
            player = (row, col)
        elif cell_type == 'player_on_goal':
            player = (row, col)
            goals.add((row, col))
        elif cell_type == 'box_on_goal':
            boxes.add((row, col))
            goals.add((row, col))

    return walls, boxes, goals, player


def count_pushes(walls, boxes, player, moves):
    """Count pushes by simulating the move sequence."""
    dir_map = {
        'u': (-1, 0), 'd': (1, 0), 'l': (0, -1), 'r': (0, 1),
        'U': (-1, 0), 'D': (1, 0), 'L': (0, -1), 'R': (0, 1),
    }
    boxes = set(boxes)
    pr, pc = player
    pushes = 0
    for ch in moves:
        dr, dc = dir_map[ch]
        nr, nc = pr + dr, pc + dc
        if (nr, nc) in boxes:
            bnr, bnc = nr + dr, nc + dc
            boxes.remove((nr, nc))
            boxes.add((bnr, bnc))
            pushes += 1
        pr, pc = nr, nc
    return pushes


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    level_ids = [r[0] for r in c.execute('SELECT id FROM levels ORDER BY id').fetchall()]

    for level_id in level_ids:
        sol_path = os.path.join(SOLUTIONS_DIR, f"level_{level_id}.txt")
        if not os.path.exists(sol_path):
            print(f"Warning: no solution file for level {level_id}")
            continue

        with open(sol_path) as f:
            moves = f.read().strip()

        walls, boxes, goals, player = parse_level_from_db(conn, level_id)
        pushes = count_pushes(walls, boxes, player, moves)

        c.execute(
            'INSERT OR REPLACE INTO solutions (level_id, moves, push_count, move_count) '
            'VALUES (?, ?, ?, ?)',
            (level_id, moves, pushes, len(moves))
        )
        print(f"Level {level_id}: {pushes} pushes, {len(moves)} moves inserted")

    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()
