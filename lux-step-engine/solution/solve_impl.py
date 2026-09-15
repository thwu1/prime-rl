#!/usr/bin/env python3
"""
Solve the Lux AI S3 replay forensics task:
1. Create replay analysis SQLite database
2. Write spec clarifications
3. Extract hidden parameters from replay data
4. Write corrected engine.py
5. Write extracted_params.json
"""

import json
import math
import os
import sqlite3


# ---------------------------------------------------------------------------
# Step 1: Create replay analysis SQLite database
# ---------------------------------------------------------------------------

def create_replay_database():
    """Build SQLite database from replay JSON files."""
    db_path = "/app/replay_analysis.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)

    conn.execute("""CREATE TABLE transitions (
        match_id TEXT,
        transition_id INTEGER,
        label TEXT,
        unit_count INTEGER
    )""")

    conn.execute("""CREATE TABLE unit_actions (
        match_id TEXT,
        transition_id INTEGER,
        team INTEGER,
        unit_id INTEGER,
        direction INTEGER,
        sap_dx INTEGER,
        sap_dy INTEGER,
        energy_before INTEGER,
        energy_after INTEGER,
        x_before INTEGER,
        y_before INTEGER,
        x_after INTEGER,
        y_after INTEGER,
        alive_after INTEGER
    )""")

    conn.execute("""CREATE VIEW sap_events AS
        SELECT * FROM unit_actions WHERE direction = 5""")

    conn.execute("""CREATE VIEW energy_deltas AS
        SELECT *, (energy_after - energy_before) AS energy_delta
        FROM unit_actions""")

    for mid, path in [("A", "/app/replays/match_A.json"),
                      ("B", "/app/replays/match_B.json")]:
        with open(path) as f:
            replay = json.load(f)

        for trans in replay["transitions"]:
            tid = trans["id"]
            label = trans.get("label", "")
            before_units = trans["before"]["units"]
            conn.execute(
                "INSERT INTO transitions VALUES (?,?,?,?)",
                (mid, tid, label, len(before_units)),
            )

            # Build action lookup: (team, unit_id) -> action dict
            actions_by_unit = {}
            for tstr, acts in trans["actions"].items():
                t = int(tstr)
                for a in acts:
                    actions_by_unit[(t, a["i"])] = a

            # Build after-state lookup: (team, unit_id) -> after dict
            after_by_unit = {}
            for ua in trans["after"]["units"]:
                after_by_unit[(ua["t"], ua["i"])] = ua

            for ub in before_units:
                key = (ub["t"], ub["i"])
                act = actions_by_unit.get(key, {"d": 0, "sx": 0, "sy": 0})
                ua = after_by_unit[key]
                conn.execute(
                    "INSERT INTO unit_actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (mid, tid, ub["t"], ub["i"],
                     act["d"], act.get("sx", 0), act.get("sy", 0),
                     ub["e"], ua["e"],
                     ub["x"], ub["y"], ua["x"], ua["y"],
                     1 if ua["alive"] else 0),
                )

    conn.commit()
    conn.close()
    print("Created replay_analysis.db")


# ---------------------------------------------------------------------------
# Step 2: Write spec clarifications
# ---------------------------------------------------------------------------

def write_spec_clarifications():
    """Resolve spec ambiguities based on replay evidence analysis."""
    clarif = {
        "void_energy_snapshot": {
            "candidates": ["pre_movement", "post_movement_pre_sap", "post_sap"],
            "determination": "post_movement_pre_sap",
        },
        "collision_tie_behavior": {
            "candidates": ["lower_team_removed", "higher_team_removed", "all_removed"],
            "determination": "all_removed",
        },
        "sap_dropoff_rounding": {
            "candidates": ["floor", "round", "ceil"],
            "determination": "floor",
        },
        "void_stacking_division": {
            "candidates": ["no_division", "divide_by_friendly_count"],
            "determination": "divide_by_friendly_count",
        },
    }
    with open("/app/spec_clarifications.json", "w") as f:
        json.dump(clarif, f, indent=2)
    print("Wrote spec_clarifications.json")


# ---------------------------------------------------------------------------
# Step 3: Parameter extraction from replay data
# ---------------------------------------------------------------------------

def extract_params(replay_path):
    with open(replay_path) as f:
        replay = json.load(f)

    transitions = replay["transitions"]
    params = {"max_unit_energy": 400}

    # --- Extract unit_move_cost ---
    for trans in transitions:
        if "unit_move_cost" in params:
            break
        tiles_map = {(t["x"], t["y"]): t for t in trans["before"].get("tiles", [])}
        for ub in trans["before"]["units"]:
            actions = trans["actions"].get(str(ub["t"]), [])
            act = next((a for a in actions if a["i"] == ub["i"]), None)
            if act is None or act["d"] not in [1, 2, 3, 4]:
                continue
            ua = next(
                (u for u in trans["after"]["units"]
                 if u["t"] == ub["t"] and u["i"] == ub["i"]),
                None,
            )
            if ua is None or not ua["alive"]:
                continue
            if [ub["x"], ub["y"]] == [ua["x"], ua["y"]]:
                continue
            tile = tiles_map.get((ua["x"], ua["y"]))
            tile_e = tile["e"] if tile else 0
            tile_type = tile["type"] if tile else 0
            if tile_type == 1:
                continue
            params["unit_move_cost"] = ub["e"] - ua["e"] + tile_e
            break

    # --- Extract unit_sap_cost ---
    for trans in transitions:
        if "unit_sap_cost" in params:
            break
        for ub in trans["before"]["units"]:
            actions = trans["actions"].get(str(ub["t"]), [])
            act = next((a for a in actions if a["i"] == ub["i"]), None)
            if act is None or act["d"] != 5:
                continue
            ua = next(
                (u for u in trans["after"]["units"]
                 if u["t"] == ub["t"] and u["i"] == ub["i"]),
                None,
            )
            if ua is None:
                continue
            cost = ub["e"] - ua["e"]
            if cost > 0:
                params["unit_sap_cost"] = cost
                break

    # --- Extract unit_sap_range ---
    max_ok = 0
    for trans in transitions:
        for team_str, acts in trans["actions"].items():
            for a in acts:
                if a["d"] != 5:
                    continue
                team = int(team_str)
                ub = next(u for u in trans["before"]["units"]
                          if u["t"] == team and u["i"] == a["i"])
                ua = next(u for u in trans["after"]["units"]
                          if u["t"] == team and u["i"] == a["i"])
                r = max(abs(a["sx"]), abs(a["sy"]))
                if ub["e"] - ua["e"] > 0:
                    max_ok = max(max_ok, r)
    params["unit_sap_range"] = max_ok

    # --- Extract unit_sap_dropoff_factor ---
    sap_cost = params["unit_sap_cost"]
    for trans in transitions:
        if "unit_sap_dropoff_factor" in params:
            break
        for team_str, acts in trans["actions"].items():
            if "unit_sap_dropoff_factor" in params:
                break
            for a in acts:
                if a["d"] != 5:
                    continue
                team = int(team_str)
                ub = next(u for u in trans["before"]["units"]
                          if u["t"] == team and u["i"] == a["i"])
                ua = next(u for u in trans["after"]["units"]
                          if u["t"] == team and u["i"] == a["i"])
                if ub["e"] - ua["e"] <= 0:
                    continue
                tx = ub["x"] + a["sx"]
                ty = ub["y"] + a["sy"]
                enemy = 1 - team
                for eb in trans["before"]["units"]:
                    if eb["t"] != enemy:
                        continue
                    dx_t = eb["x"] - tx
                    dy_t = eb["y"] - ty
                    if abs(dx_t) <= 1 and abs(dy_t) <= 1 and (dx_t != 0 or dy_t != 0):
                        ea = next(u for u in trans["after"]["units"]
                                  if u["t"] == eb["t"] and u["i"] == eb["i"])
                        dmg = eb["e"] - ea["e"]
                        if dmg > 0:
                            for df in [0.25, 0.5, 1.0]:
                                if math.floor(sap_cost * df) == dmg:
                                    params["unit_sap_dropoff_factor"] = df
                                    break
                        break

    # --- Extract unit_energy_void_factor ---
    for trans in transitions:
        if "unit_energy_void_factor" in params:
            break
        has_sap = any(
            a["d"] == 5
            for acts in trans["actions"].values()
            for a in acts
        )
        if has_sap:
            continue
        before_units = trans["before"]["units"]
        after_units = trans["after"]["units"]
        if len(before_units) != 2:
            continue
        u0, u1 = before_units[0], before_units[1]
        if u0["t"] == u1["t"]:
            continue
        dx = abs(u0["x"] - u1["x"])
        dy = abs(u0["y"] - u1["y"])
        if dx + dy != 1:
            continue
        a0 = next(u for u in after_units if u["t"] == u0["t"] and u["i"] == u0["i"])
        a1 = next(u for u in after_units if u["t"] == u1["t"] and u["i"] == u1["i"])
        if not a0["alive"] or not a1["alive"]:
            continue
        drain0 = u0["e"] - a0["e"]
        if drain0 > 0:
            for vf in [0.0625, 0.125, 0.25, 0.375]:
                if math.floor(vf * u1["e"]) == drain0:
                    params["unit_energy_void_factor"] = vf
                    break
            break

    # --- Extract nebula_tile_energy_reduction ---
    for trans in transitions:
        if "nebula_tile_energy_reduction" in params:
            break
        tiles_map = {(t["x"], t["y"]): t for t in trans["before"].get("tiles", [])}
        for ub in trans["before"]["units"]:
            actions = trans["actions"].get(str(ub["t"]), [])
            act = next((a for a in actions if a["i"] == ub["i"]), None)
            if act is None:
                d = 0
            else:
                d = act["d"]
            if d != 0:
                continue
            tile = tiles_map.get((ub["x"], ub["y"]))
            if tile is None or tile["type"] != 1:
                continue
            ua = next(
                (u for u in trans["after"]["units"]
                 if u["t"] == ub["t"] and u["i"] == ub["i"]),
                None,
            )
            if ua is None or not ua["alive"]:
                continue
            if ua["e"] >= 400:
                continue
            has_adj_enemy = False
            for other in trans["before"]["units"]:
                if other["t"] != ub["t"]:
                    dx = abs(other["x"] - ub["x"])
                    dy = abs(other["y"] - ub["y"])
                    if dx + dy == 1:
                        has_adj_enemy = True
                        break
            if has_adj_enemy:
                continue
            neb_red = ub["e"] + tile["e"] - ua["e"]
            if neb_red > 0:
                params["nebula_tile_energy_reduction"] = neb_red
                break

    return params


# ---------------------------------------------------------------------------
# Step 4: Corrected engine
# ---------------------------------------------------------------------------

CORRECT_ENGINE = '''\
import math
from collections import defaultdict


def resolve_step(scenario):
    params = scenario["params"]
    units_data = scenario["units"]
    map_data = scenario["map_features"]
    relic_nodes = scenario.get("relic_nodes", [])
    actions_data = scenario["actions"]

    map_w = params["map_width"]
    map_h = params["map_height"]
    move_cost = params["unit_move_cost"]
    sap_cost = params["unit_sap_cost"]
    sap_range = params["unit_sap_range"]
    sap_dropoff = params["unit_sap_dropoff_factor"]
    void_factor = params["unit_energy_void_factor"]
    max_energy = params["max_unit_energy"]
    nebula_reduction = params["nebula_tile_energy_reduction"]

    tile_type_map = {}
    tile_energy_map = {}
    for t in map_data.get("tiles", []):
        key = (t["x"], t["y"])
        tile_type_map[key] = t.get("tile_type", 0)
        tile_energy_map[key] = t.get("energy", 0)

    def get_tile_type(x, y):
        return tile_type_map.get((x, y), 0)

    def get_tile_energy(x, y):
        return tile_energy_map.get((x, y), 0)

    def in_bounds(x, y):
        return 0 <= x < map_w and 0 <= y < map_h

    units = []
    for u in units_data:
        units.append({
            "team": u["team"], "id": u["id"],
            "x": u["position"][0], "y": u["position"][1],
            "energy": u["energy"], "alive": True,
        })

    action_map = {}
    for team_key in ["team_0", "team_1"]:
        team_idx = int(team_key.split("_")[1])
        for a in actions_data.get(team_key, []):
            action_map[(team_idx, a["unit_id"])] = a

    MOVE_DELTAS = {1: (0, -1), 2: (1, 0), 3: (0, 1), 4: (-1, 0)}

    # Phase 1: Movement
    for u in units:
        if not u["alive"]:
            continue
        act = action_map.get((u["team"], u["id"]), {"direction": 0})
        d = act["direction"]
        if d in MOVE_DELTAS:
            dx, dy = MOVE_DELTAS[d]
            nx, ny = u["x"] + dx, u["y"] + dy
            if not in_bounds(nx, ny):
                u["energy"] -= move_cost
            elif get_tile_type(nx, ny) == 2:
                pass
            else:
                u["x"], u["y"] = nx, ny
                u["energy"] -= move_cost

    # FIX 1: Save energy snapshot AFTER movement, BEFORE sap
    original_energy = {(u["team"], u["id"]): u["energy"] for u in units}

    # Phase 2: Sap Actions
    ADJ_8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    for u in units:
        if not u["alive"]:
            continue
        act = action_map.get((u["team"], u["id"]), {"direction": 0})
        if act["direction"] != 5:
            continue
        sdx = act.get("sap_dx", 0)
        sdy = act.get("sap_dy", 0)
        tx, ty = u["x"] + sdx, u["y"] + sdy
        if u["energy"] < sap_cost:
            continue
        if max(abs(sdx), abs(sdy)) > sap_range:
            continue
        if not in_bounds(tx, ty):
            continue
        u["energy"] -= sap_cost
        enemy_team = 1 - u["team"]
        for v in units:
            if not v["alive"] or v["team"] != enemy_team:
                continue
            if v["x"] == tx and v["y"] == ty:
                v["energy"] -= sap_cost
        # FIX 3: Use math.floor, not round
        dropoff_damage = math.floor(sap_cost * sap_dropoff)
        for adx, ady in ADJ_8:
            ax, ay = tx + adx, ty + ady
            if not in_bounds(ax, ay):
                continue
            for v in units:
                if not v["alive"] or v["team"] != enemy_team:
                    continue
                if v["x"] == ax and v["y"] == ay:
                    v["energy"] -= dropoff_damage

    # Phase 3: Collision Resolution
    tile_units = defaultdict(list)
    for u in units:
        if u["alive"]:
            tile_units[(u["x"], u["y"])].append(u)
    for pos, us_on_tile in tile_units.items():
        teams_present = set(u["team"] for u in us_on_tile)
        if len(teams_present) < 2:
            continue
        team_energy = defaultdict(int)
        for u in us_on_tile:
            team_energy[u["team"]] += u["energy"]
        t0_e = team_energy[0]
        t1_e = team_energy[1]
        # FIX 2: Tie removes ALL units, not just one team
        if t0_e == t1_e:
            for u in us_on_tile:
                u["alive"] = False
        elif t0_e > t1_e:
            for u in us_on_tile:
                if u["team"] == 1:
                    u["alive"] = False
        else:
            for u in us_on_tile:
                if u["team"] == 0:
                    u["alive"] = False

    # Phase 4: Energy Void Fields
    ADJ_CARDINAL = [(0, -1), (0, 1), (-1, 0), (1, 0)]

    # FIX 1: Use original_energy (post-movement, pre-sap) for void map
    void_contrib = defaultdict(lambda: defaultdict(int))
    for u in units:
        if not u["alive"]:
            continue
        u_orig = original_energy[(u["team"], u["id"])]
        for adx, ady in ADJ_CARDINAL:
            ax, ay = u["x"] + adx, u["y"] + ady
            if in_bounds(ax, ay):
                void_contrib[u["team"]][(ax, ay)] += u_orig

    # FIX 4: Count friendly units per tile for stacking division
    tile_team_counts = defaultdict(lambda: defaultdict(int))
    for u in units:
        if u["alive"]:
            tile_team_counts[(u["x"], u["y"])][u["team"]] += 1

    for u in units:
        if not u["alive"]:
            continue
        opposing_void = sum(
            void_contrib[t].get((u["x"], u["y"]), 0)
            for t in range(2) if t != u["team"]
        )
        n_friendly = tile_team_counts[(u["x"], u["y"])][u["team"]]
        drain = math.floor(void_factor * opposing_void / n_friendly)
        u["energy"] -= drain

    # Phase 5: Tile Energy + Nebula
    for u in units:
        if not u["alive"]:
            continue
        u["energy"] += get_tile_energy(u["x"], u["y"])
        if get_tile_type(u["x"], u["y"]) == 1:
            u["energy"] -= nebula_reduction
        if u["energy"] > max_energy:
            u["energy"] = max_energy

    # Phase 6: Remove negative energy
    for u in units:
        if u["alive"] and u["energy"] < 0:
            u["alive"] = False

    # Phase 7: Relic scoring
    point_tiles = set()
    for relic in relic_nodes:
        rx, ry = relic["position"]
        config = relic["config"]
        for r in range(5):
            for c in range(5):
                if config[r][c] == 1:
                    px, py = rx - 2 + c, ry - 2 + r
                    if in_bounds(px, py):
                        point_tiles.add((px, py))
    team_points = [0, 0]
    for team in [0, 1]:
        occupied = set()
        for u in units:
            if u["alive"] and u["team"] == team and (u["x"], u["y"]) in point_tiles:
                occupied.add((u["x"], u["y"]))
        team_points[team] = len(occupied)

    out_units = []
    for u in units:
        out_units.append({
            "team": u["team"], "id": u["id"],
            "position": [u["x"], u["y"]],
            "energy": u["energy"], "alive": u["alive"],
        })
    return {"units": out_units, "team_points": team_points}
'''


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Step 1: Create replay analysis database
    create_replay_database()

    # Step 2: Write spec clarifications
    write_spec_clarifications()

    # Step 3: Extract parameters from both matches
    params_a = extract_params("/app/replays/match_A.json")
    params_b = extract_params("/app/replays/match_B.json")

    # Step 4: Write extracted parameters
    result = {"match_A": params_a, "match_B": params_b}
    with open("/app/extracted_params.json", "w") as f:
        json.dump(result, f, indent=2)
    print(f"Extracted params A: {params_a}")
    print(f"Extracted params B: {params_b}")

    # Step 5: Write corrected engine
    with open("/app/engine.py", "w") as f:
        f.write(CORRECT_ENGINE)
    print("Wrote corrected engine.py")


if __name__ == "__main__":
    main()
