#!/usr/bin/env python3
"""Validate Sokoban solutions from the database against level data."""
import sqlite3
import json
import sys


def parse_level_from_db(conn, level_id):
    """Reconstruct level state from normalized cell records."""
    c = conn.cursor()
    cells = c.execute(
        'SELECT row, col, cell_type FROM cells WHERE level_id = ? ORDER BY row, col',
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


def simulate(walls, boxes, goals, player, moves):
    """Simulate a move sequence. Returns (success, push_count, message)."""
    dir_map = {
        'u': (-1, 0), 'd': (1, 0), 'l': (0, -1), 'r': (0, 1),
        'U': (-1, 0), 'D': (1, 0), 'L': (0, -1), 'R': (0, 1),
    }

    boxes = set(boxes)
    pr, pc = player
    pushes = 0

    for i, ch in enumerate(moves):
        if ch not in dir_map:
            return False, pushes, f"Invalid character '{ch}' at position {i}"
        dr, dc = dir_map[ch]
        nr, nc = pr + dr, pc + dc
        if (nr, nc) in walls:
            return False, pushes, f"Move {i}: walked into wall at ({nr},{nc})"
        if (nr, nc) in boxes:
            bnr, bnc = nr + dr, nc + dc
            if (bnr, bnc) in walls:
                return False, pushes, f"Move {i}: pushed box into wall at ({bnr},{bnc})"
            if (bnr, bnc) in boxes:
                return False, pushes, f"Move {i}: pushed box into box at ({bnr},{bnc})"
            boxes.remove((nr, nc))
            boxes.add((bnr, bnc))
            pushes += 1
        pr, pc = nr, nc

    if boxes == goals:
        return True, pushes, "Solved"
    remaining = len(boxes - goals)
    return False, pushes, f"{remaining} box(es) not on goals after all moves"


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <db_path> <config_path>", file=sys.stderr)
        sys.exit(1)

    db_path = sys.argv[1]
    config_path = sys.argv[2]

    with open(config_path) as f:
        config = json.load(f)

    constraints = {lvl['id']: lvl for lvl in config['levels']}

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    level_ids = [r[0] for r in c.execute('SELECT id FROM levels ORDER BY id').fetchall()]
    solutions = {}
    for row in c.execute('SELECT level_id, moves, push_count, move_count FROM solutions').fetchall():
        solutions[row[0]] = {'moves': row[1], 'push_count': row[2], 'move_count': row[3]}

    results = []
    for lid in level_ids:
        if lid not in solutions:
            results.append({
                "level_id": lid,
                "status": "fail",
                "reason": "no solution submitted"
            })
            continue

        sol = solutions[lid]
        moves = sol['moves'].strip()
        walls, boxes, goals, player = parse_level_from_db(conn, lid)

        cons = constraints.get(lid, {"max_pushes": 500, "max_moves": 10000})

        success, actual_pushes, msg = simulate(walls, boxes, goals, player, moves)

        if not success:
            results.append({"level_id": lid, "status": "fail", "reason": msg})
        elif actual_pushes > cons['max_pushes']:
            results.append({
                "level_id": lid, "status": "fail",
                "reason": f"push count {actual_pushes} exceeds limit {cons['max_pushes']}"
            })
        elif len(moves) > cons['max_moves']:
            results.append({
                "level_id": lid, "status": "fail",
                "reason": f"move count {len(moves)} exceeds limit {cons['max_moves']}"
            })
        else:
            results.append({
                "level_id": lid, "status": "pass",
                "pushes": actual_pushes,
                "moves": len(moves),
                "push_count_recorded": sol['push_count'],
                "move_count_recorded": sol['move_count']
            })

    conn.close()

    all_pass = all(r['status'] == 'pass' for r in results)
    report = {
        "tournament": config.get("tournament_name", ""),
        "all_passed": all_pass,
        "results": results
    }

    print(json.dumps(report))


if __name__ == '__main__':
    main()
