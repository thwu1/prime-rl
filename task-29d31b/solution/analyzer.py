#!/usr/bin/env python3

"""
Sokoban state-space analyzer. Computes dead squares, full state-space
metrics, and deadlock census for each level. Writes results to SQLite.
"""

import sqlite3
from collections import deque

DB_PATH = '/app/sokoban.db'


def parse_grid(grid_text):
    lines = grid_text.split('\n')
    walls, goals, boxes = set(), set(), set()
    player = None
    for y, line in enumerate(lines):
        for x, ch in enumerate(line):
            if ch == '#':
                walls.add((x, y))
            elif ch == '$':
                boxes.add((x, y))
            elif ch == '.':
                goals.add((x, y))
            elif ch == '@':
                player = (x, y)
            elif ch == '*':
                goals.add((x, y))
                boxes.add((x, y))
            elif ch == '+':
                goals.add((x, y))
                player = (x, y)
    max_x = max(len(l) for l in lines)
    max_y = len(lines)
    floor = set()
    vis = {player}
    q = deque([player])
    while q:
        x, y = q.popleft()
        floor.add((x, y))
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if ((nx, ny) not in walls and (nx, ny) not in vis
                    and 0 <= nx < max_x and 0 <= ny < max_y):
                vis.add((nx, ny))
                q.append((nx, ny))
    return walls, floor, goals, frozenset(boxes), player


def compute_dead_squares(walls, floor, goals):
    reachable = set()
    for goal in goals:
        vis = {goal}
        q = deque([goal])
        while q:
            px, py = q.popleft()
            reachable.add((px, py))
            for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                bf = (px + dx, py + dy)
                pf = (px + 2 * dx, py + 2 * dy)
                if bf in floor and pf in floor and bf not in vis:
                    vis.add(bf)
                    q.append(bf)
    return frozenset(p for p in floor if p not in reachable and p not in goals)


def get_reachable(player, walls, boxes):
    vis = {player}
    q = deque([player])
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if ((nx, ny) not in walls and (nx, ny) not in boxes
                    and (nx, ny) not in vis):
                vis.add((nx, ny))
                q.append((nx, ny))
    return vis


def normalize_player(player, walls, boxes):
    return min(get_reachable(player, walls, boxes))


def enumerate_states(walls, floor, goals, boxes, player):
    """Full state-space BFS without deadlock pruning."""
    goals_fs = frozenset(goals)
    norm = normalize_player(player, walls, boxes)
    start = (norm, boxes)
    visited = {start}
    queue = deque([(start, 0)])
    total = 0
    dead_ends = 0
    total_succ = 0
    non_goal = 0
    sol_depth = -1

    while queue:
        state, depth = queue.popleft()
        np, bxs = state
        total += 1
        if bxs == goals_fs:
            if sol_depth < 0:
                sol_depth = depth
            continue
        non_goal += 1
        reach = get_reachable(np, walls, bxs)
        succs = set()
        for box in bxs:
            bx, by = box
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                pf = (bx - dx, by - dy)
                if pf not in reach:
                    continue
                tgt = (bx + dx, by + dy)
                if tgt in walls or tgt in bxs or tgt not in floor:
                    continue
                nb = frozenset((bxs - {box}) | {tgt})
                nn = normalize_player(box, walls, nb)
                succs.add((nn, nb))
        total_succ += len(succs)
        if not succs:
            dead_ends += 1
        for s in succs:
            if s not in visited:
                visited.add(s)
                queue.append((s, depth + 1))

    avg_bf = total_succ / non_goal if non_goal > 0 else 0.0
    return total, dead_ends, sol_depth, avg_bf


def compute_corner_deadlocks(walls, floor, goals):
    count = 0
    for x, y in floor:
        if (x, y) in goals:
            continue
        u = (x, y - 1) in walls
        d = (x, y + 1) in walls
        l = (x - 1, y) in walls
        r = (x + 1, y) in walls
        if (u and l) or (u and r) or (d and l) or (d and r):
            count += 1
    return count


def compute_freeze_positions(walls, floor, goals):
    all_cells = walls | floor
    if not all_cells:
        return 0
    xs = [c[0] for c in all_cells]
    ys = [c[1] for c in all_cells]
    count = 0
    for x in range(min(xs), max(xs)):
        for y in range(min(ys), max(ys)):
            cells = [(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)]
            if not all(c in all_cells for c in cells):
                continue
            nw = sum(1 for c in cells if c in walls)
            ngf = sum(1 for c in cells if c in floor and c not in goals)
            if nw >= 1 and ngf >= 2:
                count += 1
    return count


def main():
    conn = sqlite3.connect(DB_PATH)

    conn.execute('''CREATE TABLE IF NOT EXISTS dead_squares (
        level_id INTEGER NOT NULL,
        x INTEGER NOT NULL,
        y INTEGER NOT NULL,
        PRIMARY KEY (level_id, x, y))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS state_metrics (
        level_id INTEGER PRIMARY KEY,
        reachable_states INTEGER NOT NULL,
        dead_end_states INTEGER NOT NULL,
        solution_depth INTEGER NOT NULL,
        avg_branching_factor REAL NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS deadlock_census (
        level_id INTEGER PRIMARY KEY,
        corner_deadlocks INTEGER NOT NULL,
        freeze_deadlocks INTEGER NOT NULL)''')
    conn.commit()

    levels = conn.execute("SELECT id, grid FROM levels ORDER BY id").fetchall()

    for level_id, grid in levels:
        print(f"Analyzing level {level_id}...", flush=True)
        walls, floor, goals, boxes, player = parse_grid(grid)

        # Dead squares
        ds = compute_dead_squares(walls, floor, goals)
        for x, y in ds:
            conn.execute(
                "INSERT OR REPLACE INTO dead_squares VALUES (?,?,?)",
                (level_id, x, y))

        # State-space enumeration
        total, dead_ends, sol_depth, avg_bf = enumerate_states(
            walls, floor, goals, boxes, player)
        conn.execute(
            "INSERT OR REPLACE INTO state_metrics VALUES (?,?,?,?,?)",
            (level_id, total, dead_ends, sol_depth, round(avg_bf, 6)))

        # Deadlock census
        corners = compute_corner_deadlocks(walls, floor, goals)
        freezes = compute_freeze_positions(walls, floor, goals)
        conn.execute(
            "INSERT OR REPLACE INTO deadlock_census VALUES (?,?,?)",
            (level_id, corners, freezes))

        conn.commit()
        print(f"  Done: {total} states, {len(ds)} dead squares, "
              f"depth={sol_depth}, corners={corners}, freezes={freezes}",
              flush=True)

    conn.close()
    print("Analysis complete.")


if __name__ == '__main__':
    main()
