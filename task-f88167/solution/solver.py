#!/usr/bin/env python3
"""
Sokoban A* solver with reverse-push deadlock detection and
minimum-weight bipartite matching heuristic (Hungarian algorithm).
"""

import sys
import os
import heapq
from collections import deque

DIRS = [(-1, 0, 'u'), (1, 0, 'd'), (0, -1, 'l'), (0, 1, 'r')]
D4 = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def parse_level(filename):
    with open(filename) as f:
        lines = f.read().rstrip('\n').split('\n')
    lines = [l for l in lines if not l.startswith(';') and l.strip()]
    walls = set()
    boxes = set()
    goals = set()
    player = None
    for r, line in enumerate(lines):
        for c, ch in enumerate(line):
            if ch == '#':
                walls.add((r, c))
            elif ch == '$':
                boxes.add((r, c))
            elif ch == '.':
                goals.add((r, c))
            elif ch == '@':
                player = (r, c)
            elif ch == '+':
                player = (r, c)
                goals.add((r, c))
            elif ch == '*':
                boxes.add((r, c))
                goals.add((r, c))
    return walls, frozenset(boxes), frozenset(goals), player


def get_floor(walls, player):
    """Flood-fill from player to find all interior floor cells."""
    visited = {player}
    queue = deque([player])
    while queue:
        r, c = queue.popleft()
        for dr, dc in D4:
            nb = (r + dr, c + dc)
            if nb not in walls and nb not in visited:
                visited.add(nb)
                queue.append(nb)
    return visited


def player_reachable(walls, boxes, start):
    """BFS avoiding walls and boxes.  Returns (reachable set, min position)."""
    visited = {start}
    queue = deque([start])
    mn = start
    while queue:
        pos = queue.popleft()
        if pos < mn:
            mn = pos
        r, c = pos
        for dr, dc in D4:
            nb = (r + dr, c + dc)
            if nb not in walls and nb not in boxes and nb not in visited:
                visited.add(nb)
                queue.append(nb)
    return visited, mn


def compute_deadlock_set(walls, goals, floor):
    """Positions from which a box can never reach any goal via pushes."""
    reachable = set(goals)
    queue = deque(list(goals))
    while queue:
        qr, qc = queue.popleft()
        for dr, dc in D4:
            prev = (qr - dr, qc - dc)
            puller = (qr - 2 * dr, qc - 2 * dc)
            if prev in floor and puller in floor and prev not in reachable:
                reachable.add(prev)
                queue.append(prev)
    return floor - reachable


def compute_push_dists(walls, goals, floor):
    """Reverse-push BFS distances from every floor cell to each goal."""
    goal_list = sorted(goals)
    dists = {}
    for gi, goal in enumerate(goal_list):
        d = {goal: 0}
        queue = deque([(goal, 0)])
        while queue:
            (qr, qc), cost = queue.popleft()
            for dr, dc in D4:
                prev = (qr - dr, qc - dc)
                puller = (qr - 2 * dr, qc - 2 * dc)
                if prev in floor and puller in floor and prev not in d:
                    d[prev] = cost + 1
                    queue.append((prev, cost + 1))
        dists[gi] = d
    return goal_list, dists


def hungarian(cost):
    """O(n^3) Hungarian algorithm.  Returns minimum total assignment cost."""
    n = len(cost)
    INF = float('inf')
    u = [0] * (n + 1)
    v = [0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
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
            if p[j0] == 0:
                break
        while j0:
            p[j0] = p[way[j0]]
            j0 = way[j0]
    return sum(cost[p[j] - 1][j - 1] for j in range(1, n + 1))


def h_matching(boxes, goal_list, goal_dists):
    """Minimum matching lower bound via Hungarian algorithm."""
    blist = sorted(boxes)
    n = len(blist)
    BIG = 999999
    mat = [[goal_dists[gi].get(b, BIG) for gi in range(n)] for b in blist]
    return hungarian(mat)


def solve(walls, init_boxes, goals, init_player):
    """A* in push-space with normalised player positions."""
    floor = get_floor(walls, init_player)
    dead = compute_deadlock_set(walls, goals, floor)
    goal_list, gdists = compute_push_dists(walls, goals, floor)

    _, norm0 = player_reachable(walls, init_boxes, init_player)
    h0 = h_matching(init_boxes, goal_list, gdists)

    s0 = (init_boxes, norm0)
    g_score = {s0: 0}
    came = {s0: None}

    cnt = 0
    heap = [(h0, 0, cnt, s0)]
    expanded = 0
    limit = 8_000_000

    while heap:
        f, g, _, state = heapq.heappop(heap)
        boxes, np = state

        if g > g_score.get(state, float('inf')):
            continue

        expanded += 1
        if expanded % 200_000 == 0:
            print(f"  exp={expanded} f={f} g={g} heap={len(heap)}",
                  file=sys.stderr)
        if expanded > limit:
            print(f"  Hit node limit {limit}", file=sys.stderr)
            return None

        if boxes == goals:
            seq = []
            s = state
            while came[s] is not None:
                prev, info = came[s]
                seq.append(info)
                s = prev
            seq.reverse()
            print(f"  Solved: {len(seq)} pushes, {expanded} nodes",
                  file=sys.stderr)
            return seq

        reach, _ = player_reachable(walls, boxes, np)

        for br, bc in list(boxes):
            for dr, dc, dch in DIRS:
                pp = (br - dr, bc - dc)
                nbp = (br + dr, bc + dc)
                if pp not in reach:
                    continue
                if nbp in walls or nbp in boxes or nbp in dead:
                    continue

                nb = frozenset((boxes - {(br, bc)}) | {nbp})
                _, nnp = player_reachable(walls, nb, (br, bc))
                ns = (nb, nnp)
                ng = g + 1

                if ng < g_score.get(ns, float('inf')):
                    g_score[ns] = ng
                    came[ns] = (state, ((br, bc), dch, pp))
                    nh = h_matching(nb, goal_list, gdists)
                    cnt += 1
                    heapq.heappush(heap, (ng + nh, ng, cnt, ns))

    print("  No solution found", file=sys.stderr)
    return None


def walk_path(walls, boxes, start, end):
    """BFS shortest walk from start to end, avoiding walls and boxes."""
    if start == end:
        return ""
    parent = {start: (None, '')}
    queue = deque([start])
    while queue:
        r, c = queue.popleft()
        if (r, c) == end:
            parts = []
            pos = end
            while parent[pos][0] is not None:
                parts.append(parent[pos][1])
                pos = parent[pos][0]
            return ''.join(reversed(parts))
        for dr, dc, dch in DIRS:
            nb = (r + dr, c + dc)
            if nb not in walls and nb not in boxes and nb not in parent:
                parent[nb] = ((r, c), dch)
                queue.append(nb)
    return None


def reconstruct(walls, init_boxes, init_player, push_seq):
    """Turn push sequence into full direction string."""
    DIR_MAP = {'u': (-1, 0), 'd': (1, 0), 'l': (0, -1), 'r': (0, 1)}
    parts = []
    player = init_player
    boxes = set(init_boxes)
    for box_pos, pdir, ptarget in push_seq:
        w = walk_path(walls, boxes, player, ptarget)
        if w is None:
            raise RuntimeError(
                f"No walk from {player} to {ptarget}, boxes={sorted(boxes)}")
        parts.append(w)
        parts.append(pdir)
        dr, dc = DIR_MAP[pdir]
        nbp = (box_pos[0] + dr, box_pos[1] + dc)
        boxes.discard(box_pos)
        boxes.add(nbp)
        player = box_pos
    return ''.join(parts)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <level> <outfile>", file=sys.stderr)
        sys.exit(1)
    lf, sf = sys.argv[1], sys.argv[2]
    print(f"Solving {lf} ...", file=sys.stderr)
    walls, boxes, goals, player = parse_level(lf)
    print(f"  {len(boxes)} boxes, {len(goals)} goals", file=sys.stderr)

    seq = solve(walls, boxes, goals, player)
    if seq is None:
        print("FAILED", file=sys.stderr)
        sys.exit(1)

    sol = reconstruct(walls, boxes, player, seq)
    print(f"  {len(sol)} total moves", file=sys.stderr)

    d = os.path.dirname(sf)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(sf, 'w') as f:
        f.write(sol + '\n')


if __name__ == '__main__':
    main()
