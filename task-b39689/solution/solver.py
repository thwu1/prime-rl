#!/usr/bin/env python3
"""
Sokoban solver using A* search with dead-square pruning and Hungarian-method heuristic.

Implements:
  - XSB format parser
  - Dead-square computation via reverse-pull BFS from goals
  - State normalization via player-reachability flood-fill
  - A* search over push-states with the Hungarian method as admissible heuristic
  - LURD path reconstruction with walk-path interleaving

"""

import sys
import heapq
from collections import deque

DIRS = [('u', -1, 0), ('d', 1, 0), ('l', 0, -1), ('r', 0, 1)]


def parse_puzzle(path):
    """Parse an XSB-format puzzle file."""
    lines = []
    with open(path) as f:
        for raw in f:
            s = raw.rstrip('\n\r')
            if s.startswith(';'):
                continue
            if not s.strip():
                if lines:
                    break
                continue
            lines.append(s)

    rows = len(lines)
    cols = max(len(l) for l in lines) if lines else 0

    walls = set()
    player = None
    boxes = []
    goals = []

    for r in range(rows):
        for c in range(len(lines[r])):
            ch = lines[r][c]
            pos = (r, c)
            if ch == '#':
                walls.add(pos)
            elif ch == '@':
                player = pos
            elif ch == '+':
                player = pos
                goals.append(pos)
            elif ch == '$':
                boxes.append(pos)
            elif ch == '*':
                boxes.append(pos)
                goals.append(pos)
            elif ch == '.':
                goals.append(pos)

    # Compute floor cells: flood fill from player ignoring boxes
    floor = {player}
    queue = deque([player])
    while queue:
        r, c = queue.popleft()
        for _, dr, dc in DIRS:
            p = (r + dr, c + dc)
            if p not in floor and p not in walls and 0 <= p[0] < rows and 0 <= p[1] < cols:
                floor.add(p)
                queue.append(p)

    return walls, player, frozenset(boxes), tuple(sorted(goals)), floor


def compute_dead_squares(walls, goals, floor):
    """
    Compute dead squares via reverse-pull BFS from goals.
    A cell is dead if no sequence of pushes can ever move a box from that cell to any goal.
    """
    alive = set(goals)
    queue = deque(list(goals))
    while queue:
        r, c = queue.popleft()
        for _, dr, dc in DIRS:
            # Reverse pull: box was at (r+dr, c+dc), pulled to (r, c)
            # Player was at (r+2*dr, c+2*dc)
            box_from = (r + dr, c + dc)
            player_from = (r + 2 * dr, c + 2 * dc)
            if (box_from in floor and box_from not in walls and
                    player_from in floor and player_from not in walls and
                    box_from not in alive):
                alive.add(box_from)
                queue.append(box_from)
    return floor - alive - walls


def player_reachable(pos, walls, boxes, floor):
    """BFS: all cells the player can reach without pushing any box."""
    visited = {pos}
    queue = deque([pos])
    while queue:
        r, c = queue.popleft()
        for _, dr, dc in DIRS:
            p = (r + dr, c + dc)
            if p in floor and p not in walls and p not in boxes and p not in visited:
                visited.add(p)
                queue.append(p)
    return visited


def normalize_player(pos, walls, boxes, floor):
    """Canonical player position = minimum reachable cell."""
    return min(player_reachable(pos, walls, boxes, floor))


def hungarian_assignment(cost_matrix):
    """
    Hungarian method for the linear assignment problem.
    cost_matrix: n x n list of lists of integers.
    Returns the minimum total cost of an optimal assignment.
    Adapted from the Kuhn-Munkres implementation in celicom11/SokoBoy.
    """
    n = len(cost_matrix)
    if n == 0:
        return 0

    INF = 10 ** 9
    u = [0] * (n + 1)
    v = [0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        min_v = [INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost_matrix[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < min_v[j]:
                        min_v[j] = cur
                        way[j] = j0
                    if min_v[j] < delta:
                        delta = min_v[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    min_v[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    return -v[0]


# Heuristic cache: boxes -> h_value
_h_cache = {}


def heuristic(boxes, goals_list):
    """
    Admissible heuristic: minimum-cost assignment of boxes to goals
    using Manhattan distances, computed via the Hungarian method.
    """
    if boxes in _h_cache:
        return _h_cache[boxes]
    box_list = sorted(boxes)
    n = len(box_list)
    if n == 0:
        _h_cache[boxes] = 0
        return 0
    cost = [
        [abs(box_list[i][0] - goals_list[j][0]) + abs(box_list[i][1] - goals_list[j][1])
         for j in range(n)]
        for i in range(n)
    ]
    val = hungarian_assignment(cost)
    _h_cache[boxes] = val
    return val


def find_walk_path(start, end, walls, boxes, floor):
    """BFS shortest walk path from start to end. Returns list of direction chars."""
    if start == end:
        return []
    visited = {start}
    queue = deque([(start, [])])
    while queue:
        (r, c), path = queue.popleft()
        for name, dr, dc in DIRS:
            p = (r + dr, c + dc)
            if p not in visited and p in floor and p not in walls and p not in boxes:
                new_path = path + [name]
                if p == end:
                    return new_path
                visited.add(p)
                queue.append((p, new_path))
    return None


def solve(walls, player, boxes, goals_tuple, floor, dead_squares):
    """A* solver over push-states. Returns LURD solution string or None."""
    goals_set = frozenset(goals_tuple)
    goals_list = list(goals_tuple)
    _h_cache.clear()

    norm0 = normalize_player(player, walls, boxes, floor)
    state0 = (boxes, norm0)
    h0 = heuristic(boxes, goals_list)

    counter = 0
    # heap: (f_score, tiebreaker, g_score, boxes_frozen, actual_player, norm_player)
    heap = [(h0, counter, 0, boxes, player, norm0)]
    counter += 1

    best_g = {state0: 0}
    # came_from: state -> (parent_state, push_from_pos, push_direction) or None
    came_from = {state0: None}
    actual_player_at = {state0: player}

    while heap:
        _, _, g, bx, actual_p, norm_p = heapq.heappop(heap)
        state = (bx, norm_p)

        if best_g.get(state, 10 ** 9) < g:
            continue  # stale entry

        if bx == goals_set:
            return _reconstruct(came_from, actual_player_at, state, walls, floor,
                                state0, player)

        reachable = player_reachable(actual_p, walls, bx, floor)

        for dir_name, dr, dc in DIRS:
            for box in bx:
                push_from = (box[0] - dr, box[1] - dc)
                push_to = (box[0] + dr, box[1] + dc)

                if push_from not in reachable:
                    continue
                if (push_to not in floor or push_to in walls or
                        push_to in bx or push_to in dead_squares):
                    continue

                new_bx = frozenset((bx - {box}) | {push_to})
                new_actual = box  # player moves to box's old position
                new_norm = normalize_player(new_actual, walls, new_bx, floor)
                new_state = (new_bx, new_norm)
                new_g = g + 1

                if new_g >= best_g.get(new_state, 10 ** 9):
                    continue

                best_g[new_state] = new_g
                new_h = heuristic(new_bx, goals_list)
                new_f = new_g + new_h

                heapq.heappush(heap, (new_f, counter, new_g, new_bx, new_actual, new_norm))
                counter += 1

                came_from[new_state] = (state, push_from, dir_name)
                actual_player_at[new_state] = new_actual

    return None  # no solution


def _reconstruct(came_from, actual_player_at, goal_state, walls, floor,
                 start_state, start_player):
    """Reconstruct LURD path by backtracking through came_from chain."""
    chain = []
    current = goal_state
    while came_from[current] is not None:
        parent_state, push_from, push_dir = came_from[current]
        chain.append((parent_state, push_from, push_dir, current))
        current = parent_state
    chain.reverse()

    lurd = []
    cur_player = start_player
    cur_boxes = start_state[0]

    for _, push_from, push_dir, new_state in chain:
        # Walk from current player position to the push position
        walk = find_walk_path(cur_player, push_from, walls, cur_boxes, floor)
        if walk:
            lurd.extend(walk)

        # Execute push (uppercase)
        lurd.append(push_dir.upper())

        # Update player position: player moved from push_from in push_dir
        for name, dr, dc in DIRS:
            if name == push_dir:
                cur_player = (push_from[0] + dr, push_from[1] + dc)
                break

        cur_boxes = new_state[0]

    return ''.join(lurd)


def main():
    if len(sys.argv) < 2:
        print("Usage: solver <puzzle.xsb>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    walls, player, boxes, goals, floor = parse_puzzle(path)
    dead = compute_dead_squares(walls, goals, floor)
    solution = solve(walls, player, boxes, goals, floor, dead)

    if solution is not None:
        print(solution)
    else:
        print("No solution found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
