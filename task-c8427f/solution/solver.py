#!/usr/bin/env python3
"""Sokoban puzzle forensics solver: analyze attempts, solve levels, compute dead positions.

Reads puzzle data from SQLite, performs analysis, and writes results back.

"""

import sqlite3
import sys
from collections import deque

DB_PATH = "/app/sokoban.db"

DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
DIR_CHAR = {(-1, 0): 'u', (1, 0): 'd', (0, -1): 'l', (0, 1): 'r'}
PUSH_CHAR = {(-1, 0): 'U', (1, 0): 'D', (0, -1): 'L', (0, 1): 'R'}
MOVE_DIR = {
    'u': (-1, 0), 'd': (1, 0), 'l': (0, -1), 'r': (0, 1),
    'U': (-1, 0), 'D': (1, 0), 'L': (0, -1), 'R': (0, 1),
}


def parse_level(board_text):
    """Parse a Sokoban level from board text."""
    lines = board_text.rstrip('\n').split('\n')
    lines = [l for l in lines if l.strip() and not l.strip().startswith(';')]
    walls, boxes, goals = set(), set(), set()
    player = None
    for r, line in enumerate(lines):
        for c, ch in enumerate(line):
            p = (r, c)
            if ch == '#':
                walls.add(p)
            elif ch == '@':
                player = p
            elif ch == '+':
                player = p
                goals.add(p)
            elif ch == '$':
                boxes.add(p)
            elif ch == '*':
                boxes.add(p)
                goals.add(p)
            elif ch == '.':
                goals.add(p)
    assert player is not None, "No player found"
    assert len(boxes) == len(goals), f"Box/goal mismatch: {len(boxes)} vs {len(goals)}"
    return walls, frozenset(boxes), frozenset(goals), player


def flood_fill(start, walls, blocked=frozenset()):
    """BFS reachability from start, avoiding walls and blocked cells."""
    if not walls:
        return {start}
    bound_r = max(r for r, _ in walls) + 2
    bound_c = max(c for _, c in walls) + 2
    visited = {start}
    q = deque([start])
    while q:
        r, c = q.popleft()
        for dr, dc in DIRS:
            nr, nc = r + dr, c + dc
            np_ = (nr, nc)
            if 0 <= nr < bound_r and 0 <= nc < bound_c:
                if np_ not in walls and np_ not in blocked and np_ not in visited:
                    visited.add(np_)
                    q.append(np_)
    return visited


def compute_dead_squares(walls, floor, goals):
    """Compute simple dead positions via reverse reachability from each goal.

    For each goal, BFS backward: a box at position `pos` could have been
    pushed there from `prev` by a player at `plyr`. Mark all reachable
    positions as alive. Floor cells never marked alive are dead.
    """
    alive = set()
    for goal in goals:
        visited = {goal}
        q = deque([goal])
        while q:
            pos = q.popleft()
            alive.add(pos)
            for dr, dc in DIRS:
                prev = (pos[0] - dr, pos[1] - dc)
                plyr = (pos[0] - 2 * dr, pos[1] - 2 * dc)
                if prev in floor and plyr in floor and prev not in visited:
                    visited.add(prev)
                    q.append(prev)
    return frozenset(p for p in floor if p not in alive)


def analyze_attempt(walls, boxes, goals, player, moves):
    """Replay an attempt and return (valid, first_error_move, error_type).

    valid: 1 if all moves legal and all boxes on goals, else 0
    first_error_move: 0-indexed index of first illegal move, or None
    error_type: description of error, or None if fully valid
    """
    boxes = set(boxes)
    pr, pc = player

    for i, ch in enumerate(moves):
        if ch not in MOVE_DIR:
            return 0, i, f"invalid_character_{ch}"
        dr, dc = MOVE_DIR[ch]
        nr, nc = pr + dr, pc + dc

        if ch in 'udlr':
            if (nr, nc) in walls:
                return 0, i, "walk_into_wall"
            if (nr, nc) in boxes:
                return 0, i, "walk_into_box"
            pr, pc = nr, nc
        else:
            if (nr, nc) not in boxes:
                return 0, i, "push_no_box"
            br, bc = nr + dr, nc + dc
            if (br, bc) in walls:
                return 0, i, "push_into_wall"
            if (br, bc) in boxes:
                return 0, i, "push_into_box"
            boxes.remove((nr, nc))
            boxes.add((br, bc))
            pr, pc = nr, nc

    if boxes == goals:
        return 1, None, None
    else:
        return 0, None, "incomplete_not_all_boxes_on_goals"


def normalize(player, boxes, walls):
    """Canonical player position = minimum reachable cell."""
    return min(flood_fill(player, walls, boxes))


def solve(walls, initial_boxes, goals, initial_player, dead_squares):
    """BFS over push-based state space. Returns list of (dr, dc, box_from, box_to)."""
    norm = normalize(initial_player, initial_boxes, walls)
    init_state = (norm, initial_boxes)
    came_from = {init_state: None}
    q = deque([(init_state, initial_player)])

    while q:
        state, player = q.popleft()
        _, boxes = state

        if boxes == goals:
            path = []
            s = state
            while came_from[s] is not None:
                ps, dr, dc, bf, bt = came_from[s]
                path.append((dr, dc, bf, bt))
                s = ps
            path.reverse()
            return path

        reachable = flood_fill(player, walls, boxes)

        for box in boxes:
            for dr, dc in DIRS:
                needed = (box[0] - dr, box[1] - dc)
                target = (box[0] + dr, box[1] + dc)

                if needed not in reachable:
                    continue
                if target in walls or target in boxes:
                    continue
                if target in dead_squares:
                    continue

                new_boxes = frozenset((boxes - {box}) | {target})

                # Freeze-deadlock pruning: box stuck on both axes and not on goal
                if target not in goals:
                    tr, tc = target
                    h_stuck = (
                        ((tr, tc - 1) in walls or (tr, tc - 1) in new_boxes)
                        and ((tr, tc + 1) in walls or (tr, tc + 1) in new_boxes)
                    )
                    v_stuck = (
                        ((tr - 1, tc) in walls or (tr - 1, tc) in new_boxes)
                        and ((tr + 1, tc) in walls or (tr + 1, tc) in new_boxes)
                    )
                    if h_stuck and v_stuck:
                        continue

                new_player = box
                new_norm = normalize(new_player, new_boxes, walls)
                new_state = (new_norm, new_boxes)

                if new_state not in came_from:
                    came_from[new_state] = (state, dr, dc, box, target)
                    q.append((new_state, new_player))

    return None


def find_walk(start, end, walls, boxes):
    """BFS walk path from start to end, avoiding walls and boxes."""
    if start == end:
        return []
    parent = {start: None}
    q = deque([start])
    while q:
        pos = q.popleft()
        for dr, dc in DIRS:
            npos = (pos[0] + dr, pos[1] + dc)
            if npos == end:
                path = [(dr, dc)]
                cur = pos
                while parent[cur] is not None:
                    prev, d = parent[cur]
                    path.append(d)
                    cur = prev
                path.reverse()
                return path
            if npos not in walls and npos not in boxes and npos not in parent:
                parent[npos] = (pos, (dr, dc))
                q.append(npos)
    return None


def pushes_to_moves(pushes, initial_player, initial_boxes, walls):
    """Convert push sequence to full walk+push move string."""
    moves = []
    player = initial_player
    boxes = set(initial_boxes)

    for dr, dc, box_from, box_to in pushes:
        needed = (box_from[0] - dr, box_from[1] - dc)
        walk = find_walk(player, needed, walls, frozenset(boxes))
        if walk is None:
            raise RuntimeError(f"No walk path from {player} to {needed}")
        for wdr, wdc in walk:
            moves.append(DIR_CHAR[(wdr, wdc)])
            player = (player[0] + wdr, player[1] + wdc)
        moves.append(PUSH_CHAR[(dr, dc)])
        boxes.discard(box_from)
        boxes.add(box_to)
        player = box_from

    return ''.join(moves)


def main():
    conn = sqlite3.connect(DB_PATH)

    # Create output tables
    conn.execute(
        "CREATE TABLE IF NOT EXISTS analysis ("
        "level_id INTEGER PRIMARY KEY, "
        "attempt_valid INTEGER NOT NULL, "
        "first_error_move INTEGER, "
        "error_type TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS solutions ("
        "level_id INTEGER PRIMARY KEY, "
        "moves TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dead_positions ("
        "level_id INTEGER NOT NULL, "
        "row INTEGER NOT NULL, "
        "col INTEGER NOT NULL, "
        "PRIMARY KEY (level_id, row, col))"
    )

    levels = conn.execute("SELECT id, board FROM levels ORDER BY id").fetchall()

    for level_id, board in levels:
        print(f"Processing level {level_id}...")
        walls, boxes, goals, player = parse_level(board)
        floor = flood_fill(player, walls)

        # 1. Analyze attempt
        attempt_row = conn.execute(
            "SELECT moves FROM attempts WHERE level_id=?", (level_id,)
        ).fetchone()
        if attempt_row:
            valid, err_move, err_type = analyze_attempt(
                walls, boxes, goals, player, attempt_row[0]
            )
            conn.execute(
                "INSERT OR REPLACE INTO analysis VALUES (?,?,?,?)",
                (level_id, valid, err_move, err_type),
            )
            print(f"  Analysis: valid={valid}, error_move={err_move}, type={err_type}")

        # 2. Compute dead positions
        dead = compute_dead_squares(walls, floor, goals)
        for r, c in sorted(dead):
            conn.execute(
                "INSERT OR REPLACE INTO dead_positions VALUES (?,?,?)",
                (level_id, r, c),
            )
        print(f"  Dead positions: {len(dead)}")

        # 3. Solve the level
        pushes = solve(walls, boxes, goals, player, dead)
        if pushes is not None:
            move_str = pushes_to_moves(pushes, player, boxes, walls)
            conn.execute(
                "INSERT OR REPLACE INTO solutions VALUES (?,?)",
                (level_id, move_str),
            )
            print(f"  Solution: {len(pushes)} pushes, {len(move_str)} total moves")
        else:
            print(f"  WARNING: No solution found for level {level_id}", file=sys.stderr)
            sys.exit(1)

    conn.commit()
    conn.close()
    print("All levels processed successfully.")


if __name__ == "__main__":
    main()
