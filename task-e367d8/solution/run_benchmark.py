#!/usr/bin/env python3
"""
Sokoban benchmark runner: queries the SQLite database for targets,
loads puzzles from XSB files or SSX XML libraries, solves them with
A* search, and writes results.json.

"""

import sys
import os
import json
import sqlite3
import subprocess
import heapq
from collections import deque

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = "/app/benchmark.db"
RESULTS_PATH = "/app/results.json"
SOKOVALIDATE = "/app/tools/sokovalidate"

DIRS = ((-1, 0), (1, 0), (0, -1), (0, 1))
PUSH_CHARS = {(-1, 0): "U", (1, 0): "D", (0, -1): "L", (0, 1): "R"}
MOVE_CHARS = {(-1, 0): "u", (1, 0): "d", (0, -1): "l", (0, 1): "r"}


# ---------------------------------------------------------------------------
# XSB Parsing
# ---------------------------------------------------------------------------

def parse_xsb_text(text):
    lines = [l.rstrip() for l in text.split("\n") if l.rstrip() and not l.startswith(";")]
    walls = set()
    goals = set()
    boxes = []
    player = None
    for r, line in enumerate(lines):
        for c, ch in enumerate(line):
            pos = (r, c)
            if ch == "#":
                walls.add(pos)
            elif ch == "@":
                player = pos
            elif ch == "+":
                player = pos
                goals.add(pos)
            elif ch == "$":
                boxes.append(pos)
            elif ch == "*":
                boxes.append(pos)
                goals.add(pos)
            elif ch == ".":
                goals.add(pos)
    return frozenset(walls), player, tuple(sorted(boxes)), frozenset(goals)


# ---------------------------------------------------------------------------
# Puzzle loading (XSB files and SSX extraction via sokovalidate)
# ---------------------------------------------------------------------------

def load_puzzle(fmt, base_path, puzzle_ref):
    if fmt == "xsb":
        path = os.path.join(base_path, puzzle_ref)
        with open(path) as f:
            return f.read()
    elif fmt == "ssx":
        result = subprocess.run(
            [SOKOVALIDATE, "extract", "--ssx", base_path, "--puzzle-id", puzzle_ref],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"  extract failed: {result.stderr.strip()}", file=sys.stderr)
            return None
        return result.stdout
    return None


# ---------------------------------------------------------------------------
# Dead-square detection (reverse pull reachability from goals)
# ---------------------------------------------------------------------------

def compute_dead_squares(walls, goals):
    reachable = set()
    for goal in goals:
        visited = {goal}
        q = deque([goal])
        while q:
            r, c = q.popleft()
            reachable.add((r, c))
            for dr, dc in DIRS:
                bf = (r - dr, c - dc)
                pf = (r - 2 * dr, c - 2 * dc)
                if bf not in walls and pf not in walls and bf not in visited:
                    visited.add(bf)
                    q.append(bf)
    if not walls:
        return set()
    rs = [r for r, _ in walls]
    cs = [c for _, c in walls]
    all_floors = set()
    for r in range(min(rs), max(rs) + 1):
        for c in range(min(cs), max(cs) + 1):
            if (r, c) not in walls:
                all_floors.add((r, c))
    return all_floors - reachable


# ---------------------------------------------------------------------------
# Player flood fill + normalisation
# ---------------------------------------------------------------------------

def flood_fill(player, walls, boxes_set):
    visited = {player}
    q = deque([player])
    best = player
    while q:
        r, c = q.popleft()
        for dr, dc in DIRS:
            npos = (r + dr, c + dc)
            if npos not in walls and npos not in boxes_set and npos not in visited:
                visited.add(npos)
                q.append(npos)
                if npos < best:
                    best = npos
    return best, visited


# ---------------------------------------------------------------------------
# Hungarian algorithm (O(n^3) minimum cost perfect matching)
# ---------------------------------------------------------------------------

def hungarian(cost):
    n = len(cost)
    if n == 0:
        return 0
    INF = float("inf")
    u = [0] * (n + 1)
    v = [0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)
        while p[j0] != 0:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1
            for j in range(1, n + 1):
                if not used[j]:
                    val = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if val < minv[j]:
                        minv[j] = val
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
        while j0:
            p[j0] = p[way[j0]]
            j0 = way[j0]
    total = 0
    for j in range(1, n + 1):
        total += cost[p[j] - 1][j - 1]
    return total


def compute_heuristic(boxes, goal_list):
    bl = list(boxes) if not isinstance(boxes, (list, tuple)) else boxes
    n = len(bl)
    if n == 0:
        return 0
    cost = [
        [abs(bl[i][0] - goal_list[j][0]) + abs(bl[i][1] - goal_list[j][1]) for j in range(n)]
        for i in range(n)
    ]
    return hungarian(cost)


# ---------------------------------------------------------------------------
# Freeze deadlock detection
# ---------------------------------------------------------------------------

def _is_frozen(pos, boxes_set, walls, checked):
    if pos in checked:
        return True
    checked.add(pos)
    r, c = pos
    lb = (r, c - 1) in walls or ((r, c - 1) in boxes_set and _is_frozen((r, c - 1), boxes_set, walls, checked))
    rb = (r, c + 1) in walls or ((r, c + 1) in boxes_set and _is_frozen((r, c + 1), boxes_set, walls, checked))
    if not (lb and rb):
        checked.discard(pos)
        return False
    ub = (r - 1, c) in walls or ((r - 1, c) in boxes_set and _is_frozen((r - 1, c), boxes_set, walls, checked))
    db = (r + 1, c) in walls or ((r + 1, c) in boxes_set and _is_frozen((r + 1, c), boxes_set, walls, checked))
    if not (ub and db):
        checked.discard(pos)
        return False
    return True


def has_freeze_deadlock(new_pos, boxes_set, walls, goals):
    checked = set()
    if _is_frozen(new_pos, boxes_set, walls, checked):
        for b in checked:
            if b in boxes_set and b not in goals:
                return True
    return False


def has_2x2_deadlock(pos, boxes_set, walls, goals):
    r, c = pos
    for dr in (0, -1):
        for dc in (0, -1):
            cells = [
                (r + dr, c + dc), (r + dr, c + dc + 1),
                (r + dr + 1, c + dc), (r + dr + 1, c + dc + 1),
            ]
            if all(p in walls or p in boxes_set for p in cells):
                if any(p in boxes_set and p not in goals for p in cells):
                    return True
    return False


# ---------------------------------------------------------------------------
# BFS pathfinding (for LURD reconstruction)
# ---------------------------------------------------------------------------

def find_path(start, end, walls, boxes_set):
    if start == end:
        return []
    visited = {start}
    q = deque([(start, [])])
    while q:
        (r, c), path = q.popleft()
        for d in DIRS:
            dr, dc = d
            npos = (r + dr, c + dc)
            if npos == end:
                return path + [d]
            if npos not in walls and npos not in boxes_set and npos not in visited:
                visited.add(npos)
                q.append((npos, path + [d]))
    return None


# ---------------------------------------------------------------------------
# A* solver
# ---------------------------------------------------------------------------

def solve(walls, player, initial_boxes, goals):
    dead_sq = compute_dead_squares(walls, goals)
    goal_list = sorted(goals)
    n_boxes = len(initial_boxes)

    if n_boxes <= 4:
        W = 1.0
    elif n_boxes <= 6:
        W = 1.5
    else:
        W = 3.0

    boxes = initial_boxes
    bs = set(boxes)
    norm, _ = flood_fill(player, walls, bs)
    init_state = (norm, boxes)

    parent = {init_state: None}
    actual_player = {init_state: player}
    expanded = set()

    counter = 0
    h0 = compute_heuristic(boxes, goal_list)
    pq = [(W * h0, 0, counter, init_state)]
    g_best = {init_state: 0}

    MAX_STATES = 3_000_000

    while pq and len(expanded) < MAX_STATES:
        f_val, cur_g, _, state = heapq.heappop(pq)
        if state in expanded:
            continue
        expanded.add(state)
        _, cur_boxes = state

        if all(b in goals for b in cur_boxes):
            pushes = []
            s = state
            while parent[s] is not None:
                par, pf, pd = parent[s]
                pushes.append((pf, pd))
                s = par
            pushes.reverse()
            return reconstruct(walls, player, initial_boxes, pushes)

        act = actual_player[state]
        cur_bs = set(cur_boxes)
        _, reachable = flood_fill(act, walls, cur_bs)

        for box in cur_boxes:
            br, bc = box
            for dr, dc in DIRS:
                push_from = (br - dr, bc - dc)
                push_to = (br + dr, bc + dc)
                if push_from not in reachable:
                    continue
                if push_to in walls or push_to in cur_bs:
                    continue
                if push_to in dead_sq:
                    continue
                new_boxes = tuple(sorted(push_to if b == box else b for b in cur_boxes))
                new_bs = set(new_boxes)
                if has_2x2_deadlock(push_to, new_bs, walls, goals):
                    continue
                if has_freeze_deadlock(push_to, new_bs, walls, goals):
                    continue
                new_act = box
                new_norm, _ = flood_fill(new_act, walls, new_bs)
                new_state = (new_norm, new_boxes)
                if new_state in expanded:
                    continue
                new_g = cur_g + 1
                if new_state not in g_best or new_g < g_best[new_state]:
                    g_best[new_state] = new_g
                    parent[new_state] = (state, push_from, (dr, dc))
                    actual_player[new_state] = new_act
                    h = compute_heuristic(new_boxes, goal_list)
                    counter += 1
                    heapq.heappush(pq, (new_g + W * h, new_g, counter, new_state))

    return None


def reconstruct(walls, init_player, init_boxes, pushes):
    result = []
    player = init_player
    boxes = set(init_boxes)
    for push_from, (dr, dc) in pushes:
        path = find_path(player, push_from, walls, boxes)
        if path is None:
            return None
        for d in path:
            result.append(MOVE_CHARS[d])
        box_pos = (push_from[0] + dr, push_from[1] + dc)
        new_box = (box_pos[0] + dr, box_pos[1] + dc)
        boxes.remove(box_pos)
        boxes.add(new_box)
        player = box_pos
        result.append(PUSH_CHARS[(dr, dc)])
    return "".join(result)


# ---------------------------------------------------------------------------
# Main: query DB, solve all targets, write results
# ---------------------------------------------------------------------------

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    targets = conn.execute(
        "SELECT t.target_id, t.puzzle_ref, t.max_pushes, t.time_limit_sec, "
        "c.format, c.base_path "
        "FROM targets t JOIN collections c ON t.collection_id = c.id "
        "ORDER BY t.target_id"
    ).fetchall()
    conn.close()

    results = []

    for target in targets:
        tid = target["target_id"]
        fmt = target["format"]
        base_path = target["base_path"]
        puzzle_ref = target["puzzle_ref"]

        print(f"=== {tid}: {puzzle_ref} (format={fmt}) ===", file=sys.stderr)

        puzzle_text = load_puzzle(fmt, base_path, puzzle_ref)
        if puzzle_text is None:
            print(f"  SKIP: could not load puzzle", file=sys.stderr)
            continue

        walls, player, boxes, goals = parse_xsb_text(puzzle_text)
        if player is None or len(boxes) == 0 or len(boxes) != len(goals):
            print(f"  SKIP: invalid puzzle (player={player}, boxes={len(boxes)}, goals={len(goals)})",
                  file=sys.stderr)
            continue

        solution = solve(walls, player, boxes, goals)
        if solution is None:
            print(f"  FAIL: no solution found", file=sys.stderr)
            continue

        push_count = sum(1 for c in solution if c.isupper())
        print(f"  SOLVED: {len(solution)} moves, {push_count} pushes "
              f"(limit {target['max_pushes']})", file=sys.stderr)

        results.append({"target_id": tid, "solution": solution})

    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nWrote {len(results)} results to {RESULTS_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
