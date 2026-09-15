#!/usr/bin/env python3

"""
Sokoban push-optimal solver using A* with minimum-matching heuristic,
dead-square detection via reverse-pull BFS, and 2x2 freeze-deadlock pruning.
Reads levels from SQLite, writes solutions to SQLite.
"""

import sqlite3
import heapq
from collections import deque
from itertools import permutations

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


def find_walk_path(start, end, walls, boxes):
    if start == end:
        return []
    dc = {(0, -1): 'u', (0, 1): 'd', (-1, 0): 'l', (1, 0): 'r'}
    vis = {start}
    par = {}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for (dx, dy), ch in dc.items():
            np_ = (x + dx, y + dy)
            if np_ not in vis and np_ not in walls and np_ not in boxes:
                vis.add(np_)
                par[np_] = ((x, y), ch)
                if np_ == end:
                    path = []
                    p = end
                    while p in par:
                        prev, mc = par[p]
                        path.append(mc)
                        p = prev
                    path.reverse()
                    return path
                q.append(np_)
    return None


def is_freeze(target, boxes, walls, goals):
    tx, ty = target
    for dx in (0, -1):
        for dy in (0, -1):
            cells = [(tx + dx + i, ty + dy + j)
                     for i in range(2) for j in range(2)]
            if all(c in boxes or c in walls for c in cells):
                if any(c in boxes and c not in goals for c in cells):
                    return True
    return False


def min_matching(boxes, goals_list):
    bl = list(boxes)
    n = len(bl)
    if n == 0:
        return 0
    cost = [[abs(bl[i][0] - goals_list[j][0])
             + abs(bl[i][1] - goals_list[j][1])
             for j in range(n)] for i in range(n)]
    if n <= 8:
        best = float('inf')
        for perm in permutations(range(n)):
            s = sum(cost[i][perm[i]] for i in range(n))
            if s < best:
                best = s
        return best
    return sum(min(row) for row in cost)


PUSH_DIRS = (((0, -1), 'U'), ((0, 1), 'D'), ((-1, 0), 'L'), ((1, 0), 'R'))


def solve(walls, floor, goals, boxes, player):
    goals_fs = frozenset(goals)
    if boxes == goals_fs:
        return ""
    dead = compute_dead_squares(walls, floor, goals)
    gl = list(goals)
    norm = normalize_player(player, walls, boxes)
    start = (norm, boxes)
    h0 = min_matching(boxes, gl)
    cnt = 0
    heap = [(h0, cnt, 0, start, player)]
    vis = set()
    parent = {}
    best_g = {start: 0}

    while heap:
        f, _, g, state, ppos = heapq.heappop(heap)
        if state in vis:
            continue
        vis.add(state)
        _, bxs = state
        if bxs == goals_fs:
            return reconstruct(parent, state, start, player, walls)
        reach = get_reachable(ppos, walls, bxs)
        for box in bxs:
            bx, by = box
            for (dx, dy), pch in PUSH_DIRS:
                pf = (bx - dx, by - dy)
                if pf not in reach:
                    continue
                tgt = (bx + dx, by + dy)
                if (tgt in walls or tgt in bxs or tgt in dead
                        or tgt not in floor):
                    continue
                nb = frozenset((bxs - {box}) | {tgt})
                if is_freeze(tgt, nb, walls, goals):
                    continue
                np_ = box
                nn = normalize_player(np_, walls, nb)
                ns = (nn, nb)
                if ns in vis:
                    continue
                ng = g + 1
                if ns in best_g and ng >= best_g[ns]:
                    continue
                best_g[ns] = ng
                parent[ns] = (state, ppos, pf, pch, box)
                h = min_matching(nb, gl)
                cnt += 1
                heapq.heappush(heap, (ng + h, cnt, ng, ns, np_))
    return None


def reconstruct(parent, final, start, init_player, walls):
    steps = []
    state = final
    while state != start:
        info = parent[state]
        steps.append(info)
        state = info[0]
    steps.reverse()
    sol = []
    cur_p = init_player
    cur_b = set(start[1])
    for _, _, pf, pch, box in steps:
        walk = find_walk_path(cur_p, pf, walls, frozenset(cur_b))
        if walk is None:
            raise RuntimeError(f"No walk path {cur_p} -> {pf}")
        sol.extend(walk)
        sol.append(pch)
        dx, dy = {'U': (0, -1), 'D': (0, 1),
                  'L': (-1, 0), 'R': (1, 0)}[pch]
        tgt = (box[0] + dx, box[1] + dy)
        cur_b.discard(box)
        cur_b.add(tgt)
        cur_p = box
    return ''.join(sol)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS solutions (
        level_id INTEGER PRIMARY KEY,
        move_string TEXT NOT NULL,
        num_moves INTEGER NOT NULL,
        num_pushes INTEGER NOT NULL)''')
    conn.commit()

    levels = conn.execute(
        "SELECT id, grid FROM levels ORDER BY id").fetchall()
    for level_id, grid in levels:
        print(f"Solving level {level_id}...", flush=True)
        walls, floor, goals, boxes, player = parse_grid(grid)
        s = solve(walls, floor, goals, boxes, player)
        if s is None:
            print("  FAILED", flush=True)
            continue
        nm = len(s)
        np_ = sum(1 for c in s if c.isupper())
        conn.execute(
            "INSERT OR REPLACE INTO solutions VALUES (?,?,?,?)",
            (level_id, s, nm, np_))
        conn.commit()
        print(f"  Solved: {nm} moves, {np_} pushes", flush=True)
    conn.close()
    print("All levels solved.")


if __name__ == '__main__':
    main()
