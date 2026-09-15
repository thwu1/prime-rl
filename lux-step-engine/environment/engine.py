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

    # Build tile lookup tables
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

    # Build mutable unit list
    units = []
    for u in units_data:
        units.append({
            "team": u["team"],
            "id": u["id"],
            "x": u["position"][0],
            "y": u["position"][1],
            "energy": u["energy"],
            "alive": True,
        })

    # Build action lookup
    action_map = {}
    for team_key in ["team_0", "team_1"]:
        team_idx = int(team_key.split("_")[1])
        for a in actions_data.get(team_key, []):
            action_map[(team_idx, a["unit_id"])] = a

    MOVE_DELTAS = {1: (0, -1), 2: (1, 0), 3: (0, 1), 4: (-1, 0)}

    # --- Phase 1: Movement ---
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

    # --- Phase 2: Sap Actions ---
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

        dropoff_damage = round(sap_cost * sap_dropoff)
        for adx, ady in ADJ_8:
            ax, ay = tx + adx, ty + ady
            if not in_bounds(ax, ay):
                continue
            for v in units:
                if not v["alive"] or v["team"] != enemy_team:
                    continue
                if v["x"] == ax and v["y"] == ay:
                    v["energy"] -= dropoff_damage

    # --- Phase 3: Collision Resolution ---
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

        if t0_e >= t1_e:
            for u in us_on_tile:
                if u["team"] == 1:
                    u["alive"] = False
        else:
            for u in us_on_tile:
                if u["team"] == 0:
                    u["alive"] = False

    # --- Phase 4: Energy Void Fields ---
    ADJ_CARDINAL = [(0, -1), (0, 1), (-1, 0), (1, 0)]

    # Build void contribution map per team
    void_contrib = defaultdict(lambda: defaultdict(int))
    for u in units:
        if not u["alive"]:
            continue
        for adx, ady in ADJ_CARDINAL:
            ax, ay = u["x"] + adx, u["y"] + ady
            if in_bounds(ax, ay):
                void_contrib[u["team"]][(ax, ay)] += u["energy"]

    # Apply void drains
    for u in units:
        if not u["alive"]:
            continue
        opposing_void = sum(
            void_contrib[t].get((u["x"], u["y"]), 0)
            for t in range(2)
            if t != u["team"]
        )
        drain = math.floor(void_factor * opposing_void)
        u["energy"] -= drain

    # --- Phase 5: Tile Energy + Nebula ---
    for u in units:
        if not u["alive"]:
            continue
        u["energy"] += get_tile_energy(u["x"], u["y"])
        if get_tile_type(u["x"], u["y"]) == 1:
            u["energy"] -= nebula_reduction
        if u["energy"] > max_energy:
            u["energy"] = max_energy

    # --- Phase 6: Remove units with negative energy ---
    for u in units:
        if u["alive"] and u["energy"] < 0:
            u["alive"] = False

    # --- Phase 7: Relic Point Scoring ---
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
            "team": u["team"],
            "id": u["id"],
            "position": [u["x"], u["y"]],
            "energy": u["energy"],
            "alive": u["alive"],
        })

    return {"units": out_units, "team_points": team_points}
