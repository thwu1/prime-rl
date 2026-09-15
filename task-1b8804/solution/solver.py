#!/usr/bin/env python3
"""
Sokoban solver using weighted A* search with minimum-cost matching heuristic.

Uses weight w=3 for faster search (trades optimality for speed).
State: (frozenset of box positions, normalized player position).
Heuristic: minimum-cost perfect matching via brute-force permutation (cached).
Deadlock detection: corners, wall edges, simple freeze deadlocks.
"""

import sys
import time
from collections import deque
import heapq
from itertools import permutations
from functools import lru_cache

TIME_LIMIT = 170
HEURISTIC_WEIGHT = 3


def parse_level(filename):
    with open(filename) as f:
        lines = f.read().rstrip("\n").split("\n")
    lines = [l for l in lines if not l.strip().startswith(";")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    walls = set()
    boxes = set()
    goals = set()
    player = None

    for r, line in enumerate(lines):
        for c, ch in enumerate(line):
            if ch == "#":
                walls.add((r, c))
            elif ch == "@":
                player = (r, c)
            elif ch == "+":
                player = (r, c)
                goals.add((r, c))
            elif ch == "$":
                boxes.add((r, c))
            elif ch == "*":
                boxes.add((r, c))
                goals.add((r, c))
            elif ch == ".":
                goals.add((r, c))

    assert player is not None, "No player found"
    assert len(boxes) == len(goals), "Box/goal count mismatch"
    return frozenset(walls), frozenset(boxes), frozenset(goals), player


def get_reachable_and_norm(player, walls, boxes):
    """BFS flood-fill returning (reachable_set, normalized_player)."""
    visited = set()
    visited.add(player)
    queue = deque([player])
    norm = player
    while queue:
        pos = queue.popleft()
        r, c = pos
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            npos = (r + dr, c + dc)
            if npos not in walls and npos not in boxes and npos not in visited:
                visited.add(npos)
                queue.append(npos)
                if npos < norm:
                    norm = npos
    return visited, norm


def find_path(start, end, walls, boxes):
    """BFS shortest path for player, returns list of move chars."""
    if start == end:
        return []
    parent = {start: None}
    queue = deque([start])
    dirs = ((-1, 0, "u"), (1, 0, "d"), (0, -1, "l"), (0, 1, "r"))
    while queue:
        r, c = queue.popleft()
        for dr, dc, ch in dirs:
            npos = (r + dr, c + dc)
            if npos == end:
                path = [ch]
                cur = (r, c)
                while parent[cur] is not None:
                    prev_pos, prev_ch = parent[cur]
                    path.append(prev_ch)
                    cur = prev_pos
                path.reverse()
                return path
            if npos not in walls and npos not in boxes and npos not in parent:
                parent[npos] = ((r, c), ch)
                queue.append(npos)
    return None


def compute_dead_positions(walls, goals):
    """Compute positions where placing a box creates an unsolvable deadlock."""
    dead = set()
    if not walls:
        return frozenset(dead)
    max_r = max(r for r, c in walls) + 2
    max_c = max(c for r, c in walls) + 2

    for r in range(max_r):
        for c in range(max_c):
            pos = (r, c)
            if pos in walls or pos in goals:
                continue
            u = (r - 1, c) in walls
            d = (r + 1, c) in walls
            l = (r, c - 1) in walls
            ri = (r, c + 1) in walls
            if (u and l) or (u and ri) or (d and l) or (d and ri):
                dead.add(pos)

    checks = [
        (-1, 0, 0, 1),
        (1, 0, 0, 1),
        (0, -1, 1, 0),
        (0, 1, 1, 0),
    ]
    for wall_dr, wall_dc, move_dr, move_dc in checks:
        visited_seg = set()
        for r in range(max_r):
            for c in range(max_c):
                pos = (r, c)
                if pos in walls or pos in visited_seg:
                    continue
                if (r + wall_dr, c + wall_dc) not in walls:
                    continue
                segment = []
                rr, cc = r, c
                while (
                    0 <= rr < max_r
                    and 0 <= cc < max_c
                    and (rr, cc) not in walls
                    and (rr + wall_dr, cc + wall_dc) in walls
                ):
                    segment.append((rr, cc))
                    visited_seg.add((rr, cc))
                    rr += move_dr
                    cc += move_dc
                if len(segment) < 2:
                    continue
                first = segment[0]
                last = segment[-1]
                before = (first[0] - move_dr, first[1] - move_dc)
                after = (last[0] + move_dr, last[1] + move_dc)
                if before in walls and after in walls:
                    if not any(p in goals for p in segment):
                        dead.update(segment)

    return frozenset(dead)


def has_freeze_deadlock(boxes_frozen, walls, goals):
    """Check for simple freeze deadlocks: pairs of adjacent boxes that
    are mutually frozen and at least one is not on a goal."""
    boxes = set(boxes_frozen)
    for box in boxes_frozen:
        r, c = box
        right = (r, c + 1)
        if right in boxes:
            b1_v_blocked = (r - 1, c) in walls or (r + 1, c) in walls
            b2_v_blocked = (r - 1, c + 1) in walls or (r + 1, c + 1) in walls
            if b1_v_blocked and b2_v_blocked:
                if box not in goals or right not in goals:
                    return True
        below = (r + 1, c)
        if below in boxes:
            b1_h_blocked = (r, c - 1) in walls or (r, c + 1) in walls
            b2_h_blocked = (r + 1, c - 1) in walls or (r + 1, c + 1) in walls
            if b1_h_blocked and b2_h_blocked:
                if box not in goals or below not in goals:
                    return True
    return False


def bfs_dist(start, walls):
    """BFS from start ignoring boxes, returns {position: distance}."""
    dist = {start: 0}
    queue = deque([start])
    while queue:
        r, c = queue.popleft()
        d = dist[(r, c)]
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            npos = (r + dr, c + dc)
            if npos not in walls and npos not in dist:
                dist[npos] = d + 1
                queue.append(npos)
    return dist


def solve(walls, initial_boxes, goals, initial_player):
    start_time = time.time()
    dead_pos = compute_dead_positions(walls, goals)

    for b in initial_boxes:
        if b in dead_pos:
            return None

    goal_tuple = tuple(sorted(goals))
    n = len(goal_tuple)
    goal_dists = {}
    for g in goal_tuple:
        goal_dists[g] = bfs_dist(g, walls)

    all_perms = list(permutations(range(n)))

    @lru_cache(maxsize=None)
    def heuristic(boxes_frozen):
        bl = tuple(sorted(boxes_frozen))
        best = 999999
        for perm in all_perms:
            cost = 0
            for i in range(n):
                d = goal_dists[goal_tuple[perm[i]]].get(bl[i], 999999)
                cost += d
                if cost >= best:
                    break
            else:
                if cost < best:
                    best = cost
        return best

    reachable, start_norm = get_reachable_and_norm(
        initial_player, walls, initial_boxes
    )
    start_state = (initial_boxes, start_norm)

    h0 = heuristic(initial_boxes)
    if h0 >= 999999:
        return None

    counter = 0
    open_heap = [(HEURISTIC_WEIGHT * h0, counter, start_state)]
    g_score = {start_state: 0}
    came_from = {}
    closed = set()

    push_dirs = (
        ((-1, 0), "U"),
        ((1, 0), "D"),
        ((0, -1), "L"),
        ((0, 1), "R"),
    )

    expanded = 0

    while open_heap:
        if expanded % 5000 == 0:
            if time.time() - start_time > TIME_LIMIT:
                return None

        f, _, state = heapq.heappop(open_heap)

        if state in closed:
            continue
        closed.add(state)

        boxes_frozen, norm_player = state
        cur_g = g_score[state]

        if boxes_frozen == goals:
            return reconstruct(
                state, came_from, walls, initial_player, initial_boxes
            )

        expanded += 1
        reachable, _ = get_reachable_and_norm(norm_player, walls, boxes_frozen)
        boxes_set = set(boxes_frozen)

        for box in boxes_frozen:
            br, bc = box
            for (dr, dc), push_char in push_dirs:
                push_from = (br - dr, bc - dc)
                push_to = (br + dr, bc + dc)

                if push_from not in reachable:
                    continue
                if push_to in walls or push_to in boxes_set:
                    continue
                if push_to in dead_pos:
                    continue

                new_boxes = set(boxes_set)
                new_boxes.discard(box)
                new_boxes.add(push_to)
                new_boxes_frozen = frozenset(new_boxes)

                if has_freeze_deadlock(new_boxes_frozen, walls, goals):
                    continue

                new_player = box
                _, new_norm = get_reachable_and_norm(
                    new_player, walls, new_boxes_frozen
                )
                new_state = (new_boxes_frozen, new_norm)

                if new_state in closed:
                    continue

                new_g = cur_g + 1
                if new_g >= g_score.get(new_state, 999999):
                    continue

                new_h = heuristic(new_boxes_frozen)
                if new_h >= 999999:
                    continue

                g_score[new_state] = new_g
                counter += 1
                new_f = new_g + HEURISTIC_WEIGHT * new_h
                heapq.heappush(open_heap, (new_f, counter, new_state))
                came_from[new_state] = (state, box, (dr, dc), push_char)

    return None


def reconstruct(final_state, came_from, walls, initial_player, initial_boxes):
    """Reconstruct full move sequence from A* predecessors."""
    pushes = []
    state = final_state
    while state in came_from:
        prev_state, box_pos, push_dir, push_char = came_from[state]
        pushes.append((box_pos, push_dir, push_char))
        state = prev_state
    pushes.reverse()

    solution = []
    current_player = initial_player
    current_boxes = set(initial_boxes)

    for box_pos, (dr, dc), push_char in pushes:
        target = (box_pos[0] - dr, box_pos[1] - dc)
        path = find_path(
            current_player, target, walls, frozenset(current_boxes)
        )
        if path is None:
            return None
        solution.extend(path)
        solution.append(push_char)
        current_boxes.discard(box_pos)
        current_boxes.add((box_pos[0] + dr, box_pos[1] + dc))
        current_player = box_pos

    return "".join(solution)


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 solver.py <level_file>", file=sys.stderr)
        sys.exit(1)

    walls, boxes, goals, player = parse_level(sys.argv[1])
    result = solve(walls, boxes, goals, player)
    if result is not None:
        print(result)
    else:
        print("NO SOLUTION FOUND", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
