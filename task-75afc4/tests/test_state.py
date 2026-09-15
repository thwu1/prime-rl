"""Reference PuzzleScript Lite engine, independent BFS verifier, and solution validator.

"""
import json
import os
import re
import subprocess
import pytest
from collections import deque

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIRS = {"right": (1, 0), "up": (0, -1), "left": (-1, 0), "down": (0, 1)}
DIR_LIST = ["right", "up", "left", "down"]

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


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
            "OBJECTS",
            "LEGEND",
            "COLLISIONLAYERS",
            "RULES",
            "WINCONDITIONS",
            "LEVELS",
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
            if section == "OBJECTS":
                pass
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
    m = re.match(r"(?i)some\s+(\w+)\s+on\s+(\w+)", s)
    if m:
        return ("some_on", m.group(1).lower(), m.group(2).lower())
    return None


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def load_level(game, level_idx):
    level = game["levels"][level_idx]
    objects = set()
    h = len(level)
    w = max(len(r) for r in level)
    for y, row in enumerate(level):
        for x, ch in enumerate(row):
            if ch in game["legend"]:
                for obj in game["legend"][ch]:
                    objects.add((x, y, obj))
    return frozenset(objects), w, h


def apply_turn(objects, direction, game, w, h):
    """Process one turn.  Returns (new_objects_frozenset, won_bool)."""
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
        elif kind == "some_on":
            found = False
            for x, y, o in objs:
                if o == o1 and o2 in _objs_at(objs, x, y):
                    found = True
                    break
            if not found:
                return False
    return True


# ---------------------------------------------------------------------------
# Independent BFS solver (for optimality verification)
# ---------------------------------------------------------------------------


def _bfs_optimal_length(game, level_idx):
    """Find optimal solution length via independent BFS."""
    init, w, h = load_level(game, level_idx)
    queue = deque([(init, 0)])
    visited = {init}

    while queue:
        state, depth = queue.popleft()
        for move in ("up", "down", "left", "right"):
            nstate, won = apply_turn(state, move, game, w, h)
            if won:
                return depth + 1
            if nstate not in visited:
                visited.add(nstate)
                queue.append((nstate, depth + 1))

    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

GAMES = [
    ("sokoban", 2),
    ("painter", 2),
    ("colorsort", 2),
]


def _read_solution(game_name, level_idx):
    path = f"/app/solutions/{game_name}_level{level_idx}.txt"
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return [line.strip().lower() for line in f if line.strip()]


def _cases():
    out = []
    for name, n_levels in GAMES:
        for li in range(n_levels):
            out.append((name, li))
    return out


# --- Solution correctness tests ---

@pytest.mark.parametrize("game_name,level_idx", _cases())
def test_solution_wins(game_name, level_idx):
    """Verify that the submitted solution reaches a winning state."""
    sol = _read_solution(game_name, level_idx)
    assert sol is not None, (
        f"Solution file /app/solutions/{game_name}_level{level_idx}.txt not found"
    )
    assert len(sol) > 0, "Solution file is empty"
    assert len(sol) <= 200, f"Solution too long ({len(sol)} moves)"

    game = parse_game(f"/app/games/{game_name}.pzl")
    objs, w, h = load_level(game, level_idx)

    won = False
    for move in sol:
        assert move in ("up", "down", "left", "right"), f"Invalid move: {move}"
        objs, won = apply_turn(objs, move, game, w, h)
        if won:
            break

    assert won, (
        f"Solution for {game_name} level {level_idx} does not reach a winning state"
    )


# --- Solution optimality tests ---

@pytest.mark.parametrize("game_name,level_idx", _cases())
def test_solution_is_optimal(game_name, level_idx):
    """Verify that the submitted solution has the minimum possible length."""
    sol = _read_solution(game_name, level_idx)
    assert sol is not None, (
        f"Solution file /app/solutions/{game_name}_level{level_idx}.txt not found"
    )

    game = parse_game(f"/app/games/{game_name}.pzl")
    optimal = _bfs_optimal_length(game, level_idx)
    assert optimal is not None, f"No solution found by independent BFS"

    # Count moves up to the win (not trailing moves)
    objs, w, h = load_level(game, level_idx)
    actual_moves = 0
    for move in sol:
        actual_moves += 1
        objs, won = apply_turn(objs, move, game, w, h)
        if won:
            break

    assert actual_moves == optimal, (
        f"Solution for {game_name} level {level_idx} uses {actual_moves} moves "
        f"but optimal is {optimal}"
    )


# --- Proof JSON tests ---

@pytest.mark.parametrize("game_name,level_idx", _cases())
def test_proof_json_valid(game_name, level_idx):
    """Verify the optimality proof JSON has correct structure and values."""
    proof_path = f"/app/proofs/{game_name}_level{level_idx}.json"
    assert os.path.exists(proof_path), f"Proof file {proof_path} not found"

    with open(proof_path) as f:
        proof = json.load(f)

    assert "optimal_length" in proof, "Missing field: optimal_length"
    assert "proven_optimal" in proof, "Missing field: proven_optimal"
    assert "proof_method" in proof, "Missing field: proof_method"
    assert "shorter_solution_feasible" in proof, (
        "Missing field: shorter_solution_feasible"
    )

    assert isinstance(proof["optimal_length"], int), "optimal_length must be int"
    assert proof["optimal_length"] > 0, "optimal_length must be positive"
    assert proof["proven_optimal"] is True, "proven_optimal must be true"
    assert isinstance(proof["proof_method"], str) and len(proof["proof_method"]) > 0, (
        "proof_method must be a non-empty string"
    )
    assert proof["shorter_solution_feasible"] == "infeasible", (
        "shorter_solution_feasible must be 'infeasible'"
    )

    # Cross-check with solution length
    sol = _read_solution(game_name, level_idx)
    if sol is not None:
        game = parse_game(f"/app/games/{game_name}.pzl")
        objs, w, h = load_level(game, level_idx)
        actual_moves = 0
        for move in sol:
            actual_moves += 1
            objs, won = apply_turn(objs, move, game, w, h)
            if won:
                break
        assert proof["optimal_length"] == actual_moves, (
            f"Proof claims optimal_length={proof['optimal_length']} but "
            f"solution uses {actual_moves} moves"
        )


# --- Graphviz DOT file tests ---

@pytest.mark.parametrize("game_name,level_idx", _cases())
def test_dot_file_valid(game_name, level_idx):
    """Verify the Graphviz DOT file is valid and contains expected structure."""
    dot_path = f"/app/graphs/{game_name}_level{level_idx}.dot"
    assert os.path.exists(dot_path), f"DOT file {dot_path} not found"

    with open(dot_path) as f:
        content = f.read()

    assert len(content) > 0, "DOT file is empty"
    assert "digraph" in content.lower(), "DOT file must contain a digraph declaration"
    assert "->" in content, "DOT file must contain directed edges (->)"

    # Check for move direction labels in edges
    has_move_labels = any(
        d in content for d in ("up", "down", "left", "right")
    )
    assert has_move_labels, (
        "DOT edges must be labeled with move directions (up/down/left/right)"
    )

    # Validate with graphviz dot command
    result = subprocess.run(
        ["dot", "-Tcanon", dot_path],
        capture_output=True, timeout=30
    )
    assert result.returncode == 0, (
        f"DOT file fails graphviz validation: {result.stderr.decode()[:500]}"
    )
