#!/usr/bin/env python3
"""
Sokoban solver: A* search with deadlock detection and Hungarian heuristic.

"""

import sys
import heapq
from collections import deque

DIRS = ((-1, 0), (1, 0), (0, -1), (0, 1))
PUSH_CHARS = {(-1, 0): "U", (1, 0): "D", (0, -1): "L", (0, 1): "R"}
MOVE_CHARS = {(-1, 0): "u", (1, 0): "d", (0, -1): "l", (0, 1): "r"}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_xsb(filename):
    with open(filename) as f:
        content = f.read()
    lines = [l.rstrip() for l in content.split("\n") if l.rstrip() and not l.startswith(";")]

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
# Dead-square detection (reverse pull reachability from goals)
# ---------------------------------------------------------------------------

def compute_dead_squares(walls, goals):
    """Squares from which a box can never reach any goal (ignoring other boxes)."""
    reachable = set()
    for goal in goals:
        visited = {goal}
        q = deque([goal])
        while q:
            r, c = q.popleft()
            reachable.add((r, c))
            for dr, dc in DIRS:
                # Reverse of a push: box was at (r-dr, c-dc), pushed here
                # by a player at (r-2*dr, c-2*dc).
                bf = (r - dr, c - dc)
                pf = (r - 2 * dr, c - 2 * dc)
                if bf not in walls and pf not in walls and bf not in visited:
                    visited.add(bf)
                    q.append(bf)

    # All non-wall positions inside bounding box
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
    """BFS from player avoiding walls and boxes.
    Returns (canonical_pos, reachable_set).
    canonical_pos = lexicographically smallest reachable position."""
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
    """Minimum-cost bipartite matching of boxes to goals (Manhattan distance)."""
    bl = list(boxes) if not isinstance(boxes, (list, tuple)) else boxes
    n = len(bl)
    if n == 0:
        return 0
    cost = [[abs(bl[i][0] - goal_list[j][0]) + abs(bl[i][1] - goal_list[j][1])
             for j in range(n)] for i in range(n)]
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
    """Check if pos participates in a 2x2 block of boxes/walls with a non-goal box."""
    r, c = pos
    for dr in (0, -1):
        for dc in (0, -1):
            cells = [(r + dr, c + dc), (r + dr, c + dc + 1),
                     (r + dr + 1, c + dc), (r + dr + 1, c + dc + 1)]
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

    # Use weighted A* for harder puzzles (more boxes → higher weight)
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

        # Goal check
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

                new_boxes = tuple(sorted(
                    push_to if b == box else b for b in cur_boxes
                ))
                new_bs = set(new_boxes)

                # Quick 2x2 deadlock check (faster than freeze detection)
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
    """Build full LURD string from push sequence."""
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
# Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: solver <puzzle.xsb>", file=sys.stderr)
        sys.exit(1)

    walls, player, boxes, goals = parse_xsb(sys.argv[1])

    if player is None:
        print("Error: no player found", file=sys.stderr)
        sys.exit(1)
    if len(boxes) != len(goals):
        print(f"Error: {len(boxes)} boxes vs {len(goals)} goals", file=sys.stderr)
        sys.exit(1)

    solution = solve(walls, player, boxes, goals)

    if solution is None:
        print("No solution found", file=sys.stderr)
        sys.exit(1)

    print(solution)


if __name__ == "__main__":
    main()
