
"""Multi-ship planner for Halite III scenarios."""

import json
import math


def plan(scenario_path):
    """Plan moves for player 0 across all turns of a scenario.

    Returns a list of command lists, one per turn.
    """
    from simulator import GameState

    with open(scenario_path) as f:
        scenario = json.load(f)

    state = GameState.from_scenario(scenario_path)
    max_turns = scenario["max_turns"]
    w, h = state.width, state.height

    commands_sequence = []
    ship_info = {}        # sid -> {"mode": str, "target": (x,y)|None}
    claimed_targets = {}  # (x,y) -> sid

    for turn in range(max_turns):
        ships = state.get_ships(0)
        shipyard = state.get_shipyard(0)
        sx, sy = shipyard["x"], shipyard["y"]

        turn_cmds = []
        claimed_cells = set()  # collision avoidance this turn

        # Pre-claim positions of ships that will definitely stay this turn:
        # 1. Stuck ships (can't afford to move)
        # 2. Mining ships (choosing to stay and extract)
        # 3. Ships at shipyard in return mode (depositing, picking new target)
        ratio = state.constants["MOVE_COST_RATIO"]
        for ship in ships:
            sid = ship["id"]
            si = ship_info.get(sid, {})
            cell_h = state.get_cell_halite(ship["x"], ship["y"])
            cost = math.ceil(cell_h / ratio) if cell_h > 0 else 0
            if ship["halite"] < cost:
                claimed_cells.add((ship["x"], ship["y"]))
            elif si.get("mode") == "mine":
                claimed_cells.add((ship["x"], ship["y"]))
            elif (si.get("mode") == "return"
                  and ship["x"] == sx and ship["y"] == sy):
                claimed_cells.add((ship["x"], ship["y"]))

        # Clean up info for dead ships
        alive_ids = {s["id"] for s in ships}
        for sid in list(ship_info):
            if sid not in alive_ids:
                t = ship_info[sid].get("target")
                if t and claimed_targets.get(t) == sid:
                    del claimed_targets[t]
                del ship_info[sid]

        # Prioritize: mining/stuck ships first (claim cells), then returning, then traveling
        mining = [s for s in ships
                  if ship_info.get(s["id"], {}).get("mode") == "mine"]
        returning = [s for s in ships
                     if ship_info.get(s["id"], {}).get("mode") == "return"]
        mining_ids = {m["id"] for m in mining}
        returning_ids = {r["id"] for r in returning}
        others = [s for s in ships
                  if s["id"] not in mining_ids and s["id"] not in returning_ids]
        ordered = mining + returning + others

        for ship in ordered:
            sid = ship["id"]
            if sid not in ship_info:
                ship_info[sid] = {"mode": "idle", "target": None}
            si = ship_info[sid]

            dist_home = state.calculate_distance(ship["x"], ship["y"], sx, sy)
            turns_left = max_turns - turn - 1

            # Force return if running low on time
            if si["mode"] != "return" and turns_left <= dist_home + 3:
                _release_target(si, sid, claimed_targets)
                si["mode"] = "return"

            # --- IDLE: pick a target ---
            if si["mode"] == "idle":
                tgt = _find_target(state, ship, claimed_targets, sx, sy)
                if tgt:
                    si["target"] = tgt
                    claimed_targets[tgt] = sid
                    si["mode"] = "travel"
                else:
                    si["mode"] = "return"

            # --- TRAVEL: arrived? ---
            if si["mode"] == "travel" and si["target"]:
                tx, ty = si["target"]
                if ship["x"] == tx and ship["y"] == ty:
                    si["mode"] = "mine"

            # --- MINE: should we return? ---
            if si["mode"] == "mine":
                cell_h = state.get_cell_halite(ship["x"], ship["y"])
                if ship["halite"] >= 800 or cell_h < 15:
                    _release_target(si, sid, claimed_targets)
                    si["mode"] = "return"

            # --- Execute current mode ---
            if si["mode"] == "travel":
                tx, ty = si["target"]
                cmd = _try_navigate(state, ship, tx, ty, claimed_cells)
                if cmd:
                    turn_cmds.append(cmd)
                    dx, dy = GameState.DIRECTIONS[cmd["direction"]]
                    nx = (ship["x"] + dx) % w
                    ny = (ship["y"] + dy) % h
                    claimed_cells.add((nx, ny))
                else:
                    claimed_cells.add((ship["x"], ship["y"]))

            elif si["mode"] == "mine":
                claimed_cells.add((ship["x"], ship["y"]))
                # stay still — no command

            elif si["mode"] == "return":
                if ship["x"] == sx and ship["y"] == sy:
                    # On shipyard → deposited. Pick new target if time left.
                    claimed_cells.add((sx, sy))
                    if turns_left > 8:
                        si["mode"] = "idle"
                        tgt = _find_target(state, ship, claimed_targets, sx, sy)
                        if tgt:
                            si["target"] = tgt
                            claimed_targets[tgt] = sid
                            si["mode"] = "travel"
                else:
                    cmd = _try_navigate(state, ship, sx, sy, claimed_cells)
                    if cmd:
                        turn_cmds.append(cmd)
                        dx, dy = GameState.DIRECTIONS[cmd["direction"]]
                        nx = (ship["x"] + dx) % w
                        ny = (ship["y"] + dy) % h
                        claimed_cells.add((nx, ny))
                    else:
                        claimed_cells.add((ship["x"], ship["y"]))

            else:
                claimed_cells.add((ship["x"], ship["y"]))

        commands_sequence.append(turn_cmds)
        state = state.step({0: turn_cmds})

    return commands_sequence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _release_target(si, sid, claimed_targets):
    t = si.get("target")
    if t and claimed_targets.get(t) == sid:
        del claimed_targets[t]
    si["target"] = None


def _find_target(state, ship, claimed_targets, sx, sy):
    """Find the richest unclaimed cell."""
    best_score = -1
    best_pos = None
    w, h = state.width, state.height
    for y in range(h):
        for x in range(w):
            if (x, y) in claimed_targets:
                continue
            if x == sx and y == sy:
                continue
            val = state.get_cell_halite(x, y)
            dist = state.calculate_distance(ship["x"], ship["y"], x, y)
            if dist == 0:
                continue
            # Score: value adjusted by distance
            score = val / (dist + 1)
            if score > best_score:
                best_score = score
                best_pos = (x, y)
    return best_pos


def _get_unsafe_moves(state, sx, sy, tx, ty):
    """Directions that move closer to target on torus."""
    w, h = state.width, state.height
    dx = (tx - sx) % w
    dy = (ty - sy) % h
    moves = []
    if dx != 0:
        moves.append("east" if dx <= w // 2 else "west")
    if dy != 0:
        moves.append("south" if dy <= h // 2 else "north")
    return moves


def _try_navigate(state, ship, tx, ty, claimed_cells):
    """Try to move ship toward (tx,ty), avoiding claimed cells and checking
    that the ship can afford the move."""
    from simulator import GameState

    w, h = state.width, state.height
    directions = _get_unsafe_moves(state, ship["x"], ship["y"], tx, ty)

    cell_h = state.get_cell_halite(ship["x"], ship["y"])
    ratio = state.constants["MOVE_COST_RATIO"]
    cost = math.ceil(cell_h / ratio) if cell_h > 0 else 0

    if ship["halite"] < cost:
        return None  # can't afford any move

    # Try preferred directions first
    for d in directions:
        dx, dy = GameState.DIRECTIONS[d]
        nx, ny = (ship["x"] + dx) % w, (ship["y"] + dy) % h
        if (nx, ny) not in claimed_cells:
            return {"ship_id": ship["id"], "type": "move", "direction": d}

    # Try all other directions
    for d in ["north", "south", "east", "west"]:
        if d in directions:
            continue
        dx, dy = GameState.DIRECTIONS[d]
        nx, ny = (ship["x"] + dx) % w, (ship["y"] + dy) % h
        if (nx, ny) not in claimed_cells:
            return {"ship_id": ship["id"], "type": "move", "direction": d}

    return None  # stay still
