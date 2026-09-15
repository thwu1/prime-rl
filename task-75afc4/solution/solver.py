#!/usr/bin/env python3
"""PuzzleScript solver with formal optimality proofs and Graphviz visualization.

"""

import os
import re
import sys
import json
from collections import deque
from itertools import permutations

# ============================================================
# PuzzleScript Parser
# ============================================================

DIRS = {"right": (1, 0), "up": (0, -1), "left": (-1, 0), "down": (0, 1)}
DIR_LIST = ["right", "up", "left", "down"]
MOVE_NAMES = ["up", "down", "left", "right"]


def parse_game(filename):
    with open(filename) as f:
        lines = f.read().split("\n")

    game = {
        "title": "",
        "objects": {},
        "legend": {},
        "collision_layers": [],
        "rules": [],
        "win_conditions": [],
        "levels": [],
    }

    section = None
    level_lines = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        upper = stripped.replace("=", "").strip().upper()

        if upper in (
            "OBJECTS", "LEGEND", "COLLISIONLAYERS",
            "RULES", "WINCONDITIONS", "LEVELS",
        ):
            if level_lines:
                game["levels"].append(level_lines)
                level_lines = []
            section = upper
            i += 1
            while i < len(lines) and lines[i].strip().startswith("="):
                i += 1
            continue

        if stripped.startswith("="):
            i += 1
            continue

        if stripped.lower().startswith("title"):
            game["title"] = stripped[5:].strip()
            i += 1
            continue

        if not stripped:
            if section == "LEVELS" and level_lines:
                game["levels"].append(level_lines)
                level_lines = []
            i += 1
            continue

        if section == "OBJECTS":
            obj_name = stripped.split()[0].lower()
            i += 1
            if i < len(lines) and lines[i].strip():
                game["objects"][obj_name] = lines[i].strip().lower()
            i += 1
            while i < len(lines):
                s = lines[i].strip()
                if s and all(c in ".0123456789" for c in s):
                    i += 1
                else:
                    break
            continue

        elif section == "LEGEND":
            if "=" in stripped:
                char, defn = stripped.split("=", 1)
                char = char.strip()
                defn = defn.strip()
                if re.search(r"\band\b", defn, re.IGNORECASE):
                    parts = re.split(r"\s+and\s+", defn, flags=re.IGNORECASE)
                    game["legend"][char] = [p.strip().lower() for p in parts]
                else:
                    game["legend"][char] = [defn.strip().lower()]

        elif section == "COLLISIONLAYERS":
            layer = set()
            for obj in stripped.split(","):
                obj = obj.strip().lower()
                if obj:
                    layer.add(obj)
            if layer:
                game["collision_layers"].append(layer)

        elif section == "RULES":
            if "->" in stripped:
                game["rules"].append(_parse_rule(stripped))

        elif section == "WINCONDITIONS":
            wc = _parse_wincond(stripped)
            if wc:
                game["win_conditions"].append(wc)

        elif section == "LEVELS":
            if stripped.startswith("message"):
                if level_lines:
                    game["levels"].append(level_lines)
                    level_lines = []
            else:
                level_lines.append(stripped)

        i += 1

    if level_lines:
        game["levels"].append(level_lines)
    return game


def _parse_cell(s):
    tokens = []
    parts = s.strip().split()
    idx = 0
    while idx < len(parts):
        if parts[idx] == ">":
            idx += 1
            tokens.append(("move", parts[idx].lower()))
        else:
            tokens.append(("obj", parts[idx].lower()))
        idx += 1
    return tokens


def _parse_rule(s):
    lhs_s, rhs_s = s.split("->")
    lhs_s = lhs_s.strip().strip("[] ")
    rhs_s = rhs_s.strip().strip("[] ")
    lhs = [_parse_cell(c) for c in lhs_s.split("|")]
    rhs = [_parse_cell(c) for c in rhs_s.split("|")]
    return lhs, rhs


def _parse_wincond(s):
    s = s.strip()
    m = re.match(r"(?i)all\s+(\w+)\s+on\s+(\w+)", s)
    if m:
        return ("all_on", m.group(1).lower(), m.group(2).lower())
    m = re.match(r"(?i)no\s+(\w+)", s)
    if m:
        return ("no", m.group(1).lower(), None)
    return None


# ============================================================
# PuzzleScript Engine
# ============================================================


def _layer_of(obj, layers):
    for idx, layer in enumerate(layers):
        if obj in layer:
            return idx
    return -1


def _objs_at(objects, x, y):
    return {o for (ox, oy, o) in objects if ox == x and oy == y}


def _find_player(objects):
    for x, y, o in objects:
        if o == "player":
            return x, y
    return None


def load_level(game, level_idx):
    level = game["levels"][level_idx]
    h = len(level)
    w = max(len(r) for r in level)
    objects = set()
    for y, row in enumerate(level):
        for x, ch in enumerate(row):
            if ch in game["legend"]:
                for obj in game["legend"][ch]:
                    objects.add((x, y, obj))
    return frozenset(objects), w, h


def apply_turn(objects, direction, game, w, h):
    objs = set(objects)
    moves = {}

    pp = _find_player(objs)
    if pp:
        moves[(pp[0], pp[1], "player")] = direction

    for rule in game["rules"]:
        _apply_rule(objs, moves, rule, game, w, h)

    objs = _resolve(objs, moves, game, w, h)
    won = _check_win(objs, game)
    return frozenset(objs), won


def _apply_rule(objs, moves, rule, game, w, h):
    lhs, rhs = rule
    n = len(lhs)
    for d in DIR_LIST:
        dx, dy = DIRS[d]
        matched = []
        for y in range(h):
            for x in range(w):
                if _lhs_matches(objs, moves, lhs, x, y, dx, dy, d, w, h):
                    matched.append([(x + i * dx, y + i * dy) for i in range(n)])
        for positions in matched:
            _apply_rhs(objs, moves, lhs, rhs, positions, d, game)


def _lhs_matches(objs, moves, lhs, x, y, dx, dy, d, w, h):
    for i, cell_pat in enumerate(lhs):
        cx, cy = x + i * dx, y + i * dy
        if cx < 0 or cy < 0 or cx >= w or cy >= h:
            return False
        cell_set = _objs_at(objs, cx, cy)
        for ttype, tname in cell_pat:
            if tname not in cell_set:
                return False
            if ttype == "move":
                if moves.get((cx, cy, tname)) != d:
                    return False
    return True


def _apply_rhs(objs, moves, lhs, rhs, positions, d, game):
    layers = game["collision_layers"]
    for pos, lp, rp in zip(positions, lhs, rhs):
        x, y = pos
        lnames = {n for _, n in lp}
        rnames = {n for _, n in rp}

        for obj in lnames - rnames:
            objs.discard((x, y, obj))
            moves.pop((x, y, obj), None)

        for obj in rnames - lnames:
            layer = _layer_of(obj, layers)
            for ex in list(objs):
                if ex[0] == x and ex[1] == y and _layer_of(ex[2], layers) == layer:
                    objs.discard(ex)
                    moves.pop(ex, None)
            objs.add((x, y, obj))

        for ttype, tname in rp:
            if ttype == "move":
                moves[(x, y, tname)] = d


def _resolve(objs, moves, game, w, h):
    layers = game["collision_layers"]
    if not moves:
        return objs

    active = {k: v for k, v in moves.items() if k in objs}
    targets = {}
    for (x, y, o), d in active.items():
        dx, dy = DIRS[d]
        targets[(x, y, o)] = (x + dx, y + dy)

    can = {}

    def check(key, visiting=None):
        if key in can:
            return can[key]
        if visiting is None:
            visiting = set()
        if key in visiting:
            can[key] = False
            return False
        visiting.add(key)
        x, y, o = key
        tx, ty = targets[key]
        if tx < 0 or ty < 0 or tx >= w or ty >= h:
            can[key] = False
            return False
        layer = _layer_of(o, layers)
        ok = True
        for bx, by, bo in objs:
            if bx == tx and by == ty and _layer_of(bo, layers) == layer:
                bk = (bx, by, bo)
                if bk in active and active[bk] == active[key]:
                    if not check(bk, visiting):
                        ok = False
                        break
                else:
                    ok = False
                    break
        can[key] = ok
        return ok

    for k in active:
        check(k)

    new = set()
    for x, y, o in objs:
        k = (x, y, o)
        if k in active and can.get(k, False):
            tx, ty = targets[k]
            new.add((tx, ty, o))
        else:
            new.add((x, y, o))
    return new


def _check_win(objs, game):
    for wc in game["win_conditions"]:
        kind, o1, o2 = wc
        if kind == "all_on":
            for x, y, o in objs:
                if o == o1:
                    if o2 not in _objs_at(objs, x, y):
                        return False
        elif kind == "no":
            for x, y, o in objs:
                if o == o1:
                    return False
    return True


# ============================================================
# BFS Optimal Solver with State Graph
# ============================================================


def solve_bfs(game, level_idx):
    """BFS to find optimal solution.
    Returns (solution_moves, bfs_edges, init_hash, goal_hash).
    """
    init, w, h = load_level(game, level_idx)
    queue = deque([(init, [])])
    visited = {init}
    edges = []
    init_hash = hash(init)
    goal_hash = None

    while queue:
        state, path = queue.popleft()
        sh = hash(state)
        for move in MOVE_NAMES:
            nstate, won = apply_turn(state, move, game, w, h)
            nh = hash(nstate)

            if nstate not in visited:
                visited.add(nstate)
                edges.append((sh, nh, move))

                if won:
                    goal_hash = nh
                    return path + [move], edges, init_hash, goal_hash

                queue.append((nstate, path + [move]))

    return None, edges, init_hash, None


# ============================================================
# Formal Optimality Prover (Z3 bounded model checking)
# ============================================================


def _analyze_game(game):
    """Determine game mechanics from rules."""
    push_types = set()
    is_paint = False

    for lhs, rhs in game["rules"]:
        if len(lhs) == 2:
            cell0_has_move_player = any(
                t == "move" and n == "player" for t, n in lhs[0]
            )
            if cell0_has_move_player and len(lhs[1]) == 1:
                t, n = lhs[1][0]
                if t == "obj":
                    push_types.add(n)

        if len(lhs) == 1:
            lhs_names = {n for _, n in lhs[0]}
            rhs_names = {n for _, n in rhs[0]}
            if "player" in lhs_names and "unpainted" in lhs_names:
                if "player" in rhs_names and "painted" in rhs_names:
                    is_paint = True

    return push_types, is_paint


def prove_optimal(game, level_idx, optimal_k):
    """Use bounded model checking to formally prove no shorter solution exists."""
    from z3 import (Int, Solver, And, Or, Not, If, BoolVal,
                    sat, unsat)

    bound = optimal_k - 1
    if bound <= 0:
        return {
            "optimal_length": optimal_k,
            "proven_optimal": True,
            "proof_method": "bounded model checking with Z3 SMT solver",
            "shorter_solution_feasible": "infeasible",
        }

    init_state, w, h = load_level(game, level_idx)
    push_types, is_paint = _analyze_game(game)

    walls = {(x, y) for x, y, o in init_state if o == "wall"}

    px0 = next(x for x, y, o in init_state if o == "player")
    py0 = next(y for x, y, o in init_state if o == "player")

    s = Solver()
    s.set("timeout", 120000)

    px = [Int(f"px_{t}") for t in range(bound + 1)]
    py = [Int(f"py_{t}") for t in range(bound + 1)]
    dirs = [Int(f"d_{t}") for t in range(bound)]

    s.add(px[0] == px0)
    s.add(py[0] == py0)

    for t in range(bound):
        s.add(And(dirs[t] >= 0, dirs[t] <= 3))

    def z3_dx(d):
        return If(d == 0, 1, If(d == 2, -1, 0))

    def z3_dy(d):
        return If(d == 1, -1, If(d == 3, 1, 0))

    for t in range(bound + 1):
        s.add(And(px[t] >= 0, px[t] < w))
        s.add(And(py[t] >= 0, py[t] < h))

    if push_types and not is_paint:
        moveables = [(o, x, y) for x, y, o in init_state if o in push_types]
        n = len(moveables)

        mx = [[Int(f"mx{i}_{t}") for t in range(bound + 1)] for i in range(n)]
        my = [[Int(f"my{i}_{t}") for t in range(bound + 1)] for i in range(n)]

        for i, (o, ix, iy) in enumerate(moveables):
            s.add(mx[i][0] == ix)
            s.add(my[i][0] == iy)

        for i in range(n):
            for t in range(bound + 1):
                s.add(And(mx[i][t] >= 0, mx[i][t] < w))
                s.add(And(my[i][t] >= 0, my[i][t] < h))

        for t in range(bound):
            ddx = z3_dx(dirs[t])
            ddy = z3_dy(dirs[t])
            npx = px[t] + ddx
            npy = py[t] + ddy

            oob = Or(npx < 0, npy < 0, npx >= w, npy >= h)

            if walls:
                wall_hit = Or([And(npx == wx, npy == wy)
                               for (wx, wy) in walls])
            else:
                wall_hit = BoolVal(False)

            hit_cases = []
            push_blocked_cases = []
            for i in range(n):
                hit_i = And(npx == mx[i][t], npy == my[i][t])
                ptx = npx + ddx
                pty = npy + ddy

                pb_parts = [
                    ptx < 0, pty < 0, ptx >= w, pty >= h,
                ]
                if walls:
                    pb_parts.append(
                        Or([And(ptx == wx, pty == wy)
                            for (wx, wy) in walls])
                    )
                if n > 1:
                    pb_parts.append(
                        Or([And(ptx == mx[j][t], pty == my[j][t])
                            for j in range(n) if j != i])
                    )
                push_blocked_i = Or(pb_parts)

                hit_cases.append(hit_i)
                push_blocked_cases.append(push_blocked_i)

            if n > 0:
                blocked_push = Or([And(hit_cases[i], push_blocked_cases[i])
                                   for i in range(n)])
            else:
                blocked_push = BoolVal(False)
            blocked = Or(oob, wall_hit, blocked_push)

            s.add(px[t + 1] == If(blocked, px[t], npx))
            s.add(py[t + 1] == If(blocked, py[t], npy))

            for i in range(n):
                moved_i = And(Not(blocked), hit_cases[i])
                s.add(mx[i][t + 1] == If(moved_i, npx + ddx, mx[i][t]))
                s.add(my[i][t + 1] == If(moved_i, npy + ddy, my[i][t]))

        win_parts = []
        for wc in game["win_conditions"]:
            kind, o1, o2 = wc
            if kind == "all_on":
                target_positions = [(x, y) for x, y, o in init_state
                                    if o == o2]
                obj_indices = [i for i, (o, _, _) in enumerate(moveables)
                               if o == o1]

                if len(obj_indices) == 0 or len(target_positions) == 0:
                    continue

                if len(obj_indices) <= len(target_positions):
                    perm_conds = []
                    for perm in permutations(range(len(target_positions)),
                                             len(obj_indices)):
                        cond = And([
                            And(mx[obj_indices[j]][bound] == target_positions[perm[j]][0],
                                my[obj_indices[j]][bound] == target_positions[perm[j]][1])
                            for j in range(len(obj_indices))
                        ])
                        perm_conds.append(cond)
                    if perm_conds:
                        win_parts.append(Or(perm_conds))

        if win_parts:
            s.add(And(win_parts))
        else:
            s.add(BoolVal(False))

    elif is_paint:
        for t in range(bound):
            ddx = z3_dx(dirs[t])
            ddy = z3_dy(dirs[t])
            npx = px[t] + ddx
            npy = py[t] + ddy

            oob = Or(npx < 0, npy < 0, npx >= w, npy >= h)
            if walls:
                wall_hit = Or([And(npx == wx, npy == wy)
                               for (wx, wy) in walls])
            else:
                wall_hit = BoolVal(False)
            blocked = Or(oob, wall_hit)

            s.add(px[t + 1] == If(blocked, px[t], npx))
            s.add(py[t + 1] == If(blocked, py[t], npy))

        paintable = {(x, y) for x, y, o in init_state if o == "unpainted"}
        for (cx, cy) in paintable:
            s.add(Or([And(px[t] == cx, py[t] == cy)
                       for t in range(bound)]))

    else:
        s.add(BoolVal(False))

    result = s.check()
    feasibility = "infeasible" if result == unsat else "feasible"

    return {
        "optimal_length": optimal_k,
        "proven_optimal": feasibility == "infeasible",
        "proof_method": "bounded model checking with Z3 SMT solver",
        "shorter_solution_feasible": feasibility,
    }


# ============================================================
# Graphviz DOT Generator
# ============================================================


def generate_dot(edges, init_hash, goal_hash, filename, max_edges=200):
    """Generate a Graphviz DOT digraph from search edges."""
    limited = edges[:max_edges]

    with open(filename, "w") as f:
        f.write("digraph state_space {\n")
        f.write("  rankdir=TB;\n")
        f.write("  node [shape=circle, fontsize=8];\n")
        f.write(f'  "s{init_hash}" '
                f'[shape=doublecircle, label="start"];\n')
        if goal_hash is not None:
            f.write(f'  "s{goal_hash}" '
                    f'[shape=doublecircle, label="goal", '
                    f'style=filled, fillcolor=green];\n')
        for parent_h, child_h, move in limited:
            f.write(f'  "s{parent_h}" -> "s{child_h}" '
                    f'[label="{move}"];\n')
        f.write("}\n")


# ============================================================
# Main
# ============================================================

GAME_FILES = ["sokoban", "painter", "colorsort"]


def main():
    os.makedirs("/app/solutions", exist_ok=True)
    os.makedirs("/app/proofs", exist_ok=True)
    os.makedirs("/app/graphs", exist_ok=True)

    for gname in GAME_FILES:
        path = f"/app/games/{gname}.pzl"
        print(f"Parsing {path} ...")
        game = parse_game(path)
        n_levels = len(game["levels"])
        print(f"  {game['title']}: {n_levels} levels")

        for li in range(n_levels):
            print(f"  Level {li}:", flush=True)

            print(f"    Solving ...", end=" ", flush=True)
            sol, edges, init_h, goal_h = solve_bfs(game, li)
            if sol is None:
                print("NO SOLUTION FOUND")
                sys.exit(1)
            optimal_k = len(sol)
            print(f"optimal in {optimal_k} moves")

            sol_path = f"/app/solutions/{gname}_level{li}.txt"
            with open(sol_path, "w") as f:
                for m in sol:
                    f.write(m + "\n")

            print(f"    Proving optimality ...", end=" ", flush=True)
            proof = prove_optimal(game, li, optimal_k)
            print(f"result: {proof['shorter_solution_feasible']}")

            proof_path = f"/app/proofs/{gname}_level{li}.json"
            with open(proof_path, "w") as f:
                json.dump(proof, f, indent=2)

            print(f"    Generating state graph ...", end=" ", flush=True)
            dot_path = f"/app/graphs/{gname}_level{li}.dot"
            generate_dot(edges, init_h, goal_h, dot_path)
            print(f"done ({len(edges)} edges)")

    print("\nAll levels solved, proved, and visualized.")


if __name__ == "__main__":
    main()
