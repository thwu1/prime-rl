#!/usr/bin/env python3
"""
Lux AI S3 Hidden Parameter Inference Engine.
Reads replay data from SQLite database (gzip-compressed blobs),
reverse-engineers hidden game parameters, and submits via replay-tool.
"""

import json
import os
import math
import gzip
import sqlite3
import subprocess
import numpy as np
from collections import Counter

W = H = 24
MAX_UNITS = 16
NEBULA = 1

DRIFT_SPEEDS = [-0.15, -0.1, -0.05, -0.025, 0.025, 0.05, 0.1, 0.15]
ENERGY_REDUCTIONS = [0, 1, 2, 3, 5, 25]
VISION_REDUCTIONS = [0, 1, 2, 3, 4, 5, 6, 7]
DROPOFF_FACTORS = [0.25, 0.5, 1.0]
VOID_FACTORS = [0.0625, 0.125, 0.25, 0.375]
NODE_DRIFT_SPEEDS = [0.01, 0.02, 0.03, 0.04, 0.05]
NODE_DRIFT_MAGS = [3, 4, 5]

ADJACENT_8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
CARDINAL = [(0, -1), (0, 1), (-1, 0), (1, 0)]

DB_PATH = "/app/replays.db"


def load_replay_from_db(db, replay_id):
    """Load a full replay from the SQLite database, decompressing gzip blobs."""
    states = []
    for _, blob in db.execute(
        "SELECT step_idx, data FROM states WHERE replay_id = ? ORDER BY step_idx",
        (replay_id,),
    ):
        states.append(json.loads(gzip.decompress(blob)))

    actions = []
    for _, blob in db.execute(
        "SELECT step_idx, data FROM actions WHERE replay_id = ? ORDER BY step_idx",
        (replay_id,),
    ):
        actions.append(json.loads(gzip.decompress(blob)))

    known = {}
    for name, val in db.execute(
        "SELECT param_name, param_value FROM known_params WHERE replay_id = ?",
        (replay_id,),
    ):
        known[name] = int(val) if val == int(val) else val

    return {"states": states, "actions": actions, "known_params": known}


def drift_check(speed, step):
    prev = (step - 1) * abs(speed) % 1.0
    curr = step * abs(speed) % 1.0
    return prev > curr


def infer_nebula_drift_speed(states):
    """Detect tile drift events and match timing against candidate speeds."""
    observed_steps = set()
    sign = 0

    for i in range(1, len(states)):
        tt_prev = np.array(states[i - 1]["map_features"]["tile_type"])
        tt_curr = np.array(states[i]["map_features"]["tile_type"])
        if not np.array_equal(tt_prev, tt_curr):
            sim_step = states[i - 1]["steps"]
            observed_steps.add(sim_step)
            if sign == 0:
                rolled_pos = np.roll(tt_prev, shift=(1, -1), axis=(0, 1))
                rolled_neg = np.roll(tt_prev, shift=(-1, 1), axis=(0, 1))
                if np.array_equal(rolled_pos, tt_curr):
                    sign = 1
                elif np.array_equal(rolled_neg, tt_curr):
                    sign = -1

    best_speed = DRIFT_SPEEDS[0]
    best_score = -999

    for speed in DRIFT_SPEEDS:
        if sign != 0 and (speed > 0) != (sign > 0):
            continue
        predicted = set()
        for i in range(1, len(states)):
            s = states[i - 1]["steps"]
            if drift_check(speed, s):
                predicted.add(s)
        score = len(predicted & observed_steps) - len(predicted ^ observed_steps)
        if score > best_score:
            best_score = score
            best_speed = speed

    return best_speed


def infer_nebula_vision_reduction(states, known_params):
    """Compare expected vs actual vision power at nebula tiles."""
    sr = known_params["unit_sensor_range"]
    candidates = []

    for idx in range(min(5, len(states))):
        state = states[idx]
        if idx == 0:
            tt = np.array(state["map_features"]["tile_type"])
        else:
            tt = np.array(states[idx - 1]["map_features"]["tile_type"])

        vpm = np.array(state["vision_power_map"])
        positions = np.array(state["units"]["position"])
        masks = np.array(state["units_mask"])

        for t in range(2):
            expected = np.zeros((W, H), dtype=np.int32)
            for u in range(MAX_UNITS):
                if not masks[t][u]:
                    continue
                ux, uy = int(positions[t][u][0]), int(positions[t][u][1])
                for dx in range(-sr, sr + 1):
                    for dy in range(-sr, sr + 1):
                        nx, ny = ux + dx, uy + dy
                        if 0 <= nx < W and 0 <= ny < H:
                            pwr = 1 + sr - max(abs(dx), abs(dy))
                            expected[nx, ny] += pwr
                if 0 <= ux < W and 0 <= uy < H:
                    expected[ux, uy] += 10

            for x in range(W):
                for y in range(H):
                    if tt[x, y] == NEBULA and expected[x, y] > 0:
                        diff = int(expected[x, y]) - int(vpm[t, x, y])
                        if 0 <= diff <= 10:
                            candidates.append(diff)

    if not candidates:
        return 0
    return min(
        VISION_REDUCTIONS,
        key=lambda v: abs(v - Counter(candidates).most_common(1)[0][0]),
    )


def infer_nebula_energy_reduction(states, actions, known_params):
    """Find stationary units on nebula tiles with no combat to measure energy drain."""
    candidates = []

    for i in range(len(actions)):
        s0 = states[i]
        s1 = states[i + 1]
        acts = actions[i]

        for t in range(2):
            pa = acts[f"player_{t}"]
            ot = 1 - t
            for u in range(MAX_UNITS):
                if not s0["units_mask"][t][u] or not s1["units_mask"][t][u]:
                    continue
                if pa[u][0] != 0:
                    continue

                x = s0["units"]["position"][t][u][0]
                y = s0["units"]["position"][t][u][1]
                tile = s0["map_features"]["tile_type"][x][y]
                if tile != NEBULA:
                    continue

                has_adj = False
                for eu in range(MAX_UNITS):
                    if not s0["units_mask"][ot][eu]:
                        continue
                    ex = s0["units"]["position"][ot][eu][0]
                    ey = s0["units"]["position"][ot][eu][1]
                    for dx, dy in CARDINAL:
                        if ex + dx == x and ey + dy == y:
                            has_adj = True
                            break
                    if has_adj:
                        break
                if has_adj:
                    continue

                sap_hit = False
                enemy_acts = acts[f"player_{ot}"]
                for eu in range(MAX_UNITS):
                    if not s0["units_mask"][ot][eu] or enemy_acts[eu][0] != 5:
                        continue
                    if (
                        s0["units"]["energy"][ot][eu][0]
                        < known_params["unit_sap_cost"]
                    ):
                        continue
                    edx, edy = enemy_acts[eu][1], enemy_acts[eu][2]
                    if max(abs(edx), abs(edy)) > known_params["unit_sap_range"]:
                        continue
                    tx = s0["units"]["position"][ot][eu][0] + edx
                    ty = s0["units"]["position"][ot][eu][1] + edy
                    if tx == x and ty == y:
                        sap_hit = True
                        break
                    for ox, oy in ADJACENT_8:
                        if tx + ox == x and ty + oy == y:
                            sap_hit = True
                            break
                    if sap_hit:
                        break
                if sap_hit:
                    continue

                e0 = s0["units"]["energy"][t][u][0]
                e1 = s1["units"]["energy"][t][u][0]
                ef = s1["map_features"]["energy"][x][y]
                reduction = ef - (e1 - e0)
                if 0 <= reduction <= 30:
                    candidates.append(int(round(reduction)))

    if not candidates:
        return 0
    best = Counter(candidates).most_common(1)[0][0]
    return min(ENERGY_REDUCTIONS, key=lambda v: abs(v - best))


def infer_void_factor(states, actions, known_params, energy_reduction):
    """Find units with adjacent enemies and measure void damage."""
    candidates = []

    for i in range(len(actions)):
        s0 = states[i]
        s1 = states[i + 1]
        acts = actions[i]

        for t in range(2):
            ot = 1 - t
            pa = acts[f"player_{t}"]
            for u in range(MAX_UNITS):
                if not s0["units_mask"][t][u] or not s1["units_mask"][t][u]:
                    continue
                if pa[u][0] != 0:
                    continue

                x = s0["units"]["position"][t][u][0]
                y = s0["units"]["position"][t][u][1]

                void_strength = 0
                for eu in range(MAX_UNITS):
                    if not s0["units_mask"][ot][eu]:
                        continue
                    ex = s0["units"]["position"][ot][eu][0]
                    ey = s0["units"]["position"][ot][eu][1]
                    for dx, dy in CARDINAL:
                        if ex + dx == x and ey + dy == y:
                            void_strength += s0["units"]["energy"][ot][eu][0]

                if void_strength <= 0:
                    continue

                sap_hit = False
                enemy_acts = acts[f"player_{ot}"]
                for eu in range(MAX_UNITS):
                    if not s0["units_mask"][ot][eu] or enemy_acts[eu][0] != 5:
                        continue
                    if (
                        s0["units"]["energy"][ot][eu][0]
                        < known_params["unit_sap_cost"]
                    ):
                        continue
                    edx, edy = enemy_acts[eu][1], enemy_acts[eu][2]
                    if max(abs(edx), abs(edy)) > known_params["unit_sap_range"]:
                        continue
                    tx = s0["units"]["position"][ot][eu][0] + edx
                    ty = s0["units"]["position"][ot][eu][1] + edy
                    if 0 <= tx < W and 0 <= ty < H:
                        if (tx == x and ty == y) or any(
                            tx + ox == x and ty + oy == y for ox, oy in ADJACENT_8
                        ):
                            sap_hit = True
                            break
                if sap_hit:
                    continue

                my_cnt = sum(
                    1
                    for u2 in range(MAX_UNITS)
                    if s0["units_mask"][t][u2]
                    and s0["units"]["position"][t][u2][0] == x
                    and s0["units"]["position"][t][u2][1] == y
                )
                my_cnt = max(my_cnt, 1)

                e0 = s0["units"]["energy"][t][u][0]
                e1 = s1["units"]["energy"][t][u][0]
                ef = s1["map_features"]["energy"][x][y]
                tile = s0["map_features"]["tile_type"][x][y]
                neb_cost = energy_reduction if tile == NEBULA else 0

                void_dmg = e0 - e1 + ef - neb_cost
                if void_dmg <= 0:
                    continue

                factor = void_dmg * my_cnt / void_strength
                best_f = min(VOID_FACTORS, key=lambda v: abs(v - factor))
                expected_dmg = int(math.floor(best_f * void_strength / my_cnt))
                if expected_dmg == void_dmg:
                    candidates.append(best_f)

    if not candidates:
        return 0.125
    return Counter(candidates).most_common(1)[0][0]


def infer_sap_dropoff(states, actions, known_params, energy_reduction, void_factor):
    """Find sap events and compare adjacent vs direct damage."""
    sc = known_params["unit_sap_cost"]
    sr = known_params["unit_sap_range"]
    candidates = []

    for i in range(len(actions)):
        s0 = states[i]
        s1 = states[i + 1]
        acts = actions[i]

        for t in range(2):
            ot = 1 - t
            pa = acts[f"player_{t}"]

            sappers = []
            for u in range(MAX_UNITS):
                if not s0["units_mask"][t][u] or pa[u][0] != 5:
                    continue
                if s0["units"]["energy"][t][u][0] < sc:
                    continue
                dx, dy = pa[u][1], pa[u][2]
                if max(abs(dx), abs(dy)) > sr:
                    continue
                tx = s0["units"]["position"][t][u][0] + dx
                ty = s0["units"]["position"][t][u][1] + dy
                if 0 <= tx < W and 0 <= ty < H:
                    sappers.append((tx, ty))

            if not sappers:
                continue

            for eu in range(MAX_UNITS):
                if not s0["units_mask"][ot][eu] or not s1["units_mask"][ot][eu]:
                    continue
                enemy_pa = acts[f"player_{ot}"][eu]
                if enemy_pa[0] != 0:
                    continue

                ex = s0["units"]["position"][ot][eu][0]
                ey = s0["units"]["position"][ot][eu][1]

                direct = sum(1 for tx, ty in sappers if tx == ex and ty == ey)
                adj = 0
                for tx, ty in sappers:
                    for ox, oy in ADJACENT_8:
                        if tx + ox == ex and ty + oy == ey:
                            adj += 1

                if adj == 0 or direct > 0:
                    continue

                e0 = s0["units"]["energy"][ot][eu][0]
                e1 = s1["units"]["energy"][ot][eu][0]
                ef = s1["map_features"]["energy"][ex][ey]
                tile = s0["map_features"]["tile_type"][ex][ey]
                neb_cost = energy_reduction if tile == NEBULA else 0

                void_str = 0
                for fu in range(MAX_UNITS):
                    if not s0["units_mask"][t][fu]:
                        continue
                    fx = s0["units"]["position"][t][fu][0]
                    fy = s0["units"]["position"][t][fu][1]
                    for dx, dy in CARDINAL:
                        if fx + dx == ex and fy + dy == ey:
                            void_str += s0["units"]["energy"][t][fu][0]
                e_cnt = sum(
                    1
                    for u2 in range(MAX_UNITS)
                    if s0["units_mask"][ot][u2]
                    and s0["units"]["position"][ot][u2][0] == ex
                    and s0["units"]["position"][ot][u2][1] == ey
                )
                e_cnt = max(e_cnt, 1)
                void_dmg = (
                    int(math.floor(void_factor * void_str / e_cnt))
                    if void_str > 0
                    else 0
                )

                non_sap_gain = ef - neb_cost - void_dmg
                sap_dmg = (e0 - e1) + non_sap_gain
                if sap_dmg <= 0:
                    continue

                ratio = sap_dmg / (sc * adj)
                best_df = min(DROPOFF_FACTORS, key=lambda v: abs(v - ratio))
                expected_sap = int(sc * best_df * adj)
                if expected_sap == sap_dmg:
                    candidates.append(best_df)

    if not candidates:
        return 0.5
    return Counter(candidates).most_common(1)[0][0]


def infer_energy_node_drift_speed(states):
    """Detect when energy node positions change."""
    observed = set()
    for i in range(1, len(states)):
        nodes_prev = np.array(states[i - 1]["energy_nodes"])
        nodes_curr = np.array(states[i]["energy_nodes"])
        if not np.array_equal(nodes_prev, nodes_curr):
            observed.add(states[i - 1]["steps"])

    best_speed = NODE_DRIFT_SPEEDS[0]
    best_score = -999

    for speed in NODE_DRIFT_SPEEDS:
        predicted = set()
        for i in range(1, len(states)):
            s = states[i - 1]["steps"]
            if drift_check(speed, s):
                predicted.add(s)
        score = len(predicted & observed) - len(predicted ^ observed)
        if score > best_score:
            best_score = score
            best_speed = speed

    return best_speed


def infer_energy_node_drift_magnitude(states):
    """Find maximum absolute position delta when energy nodes drift."""
    max_delta = 0
    for i in range(1, len(states)):
        nodes_prev = np.array(states[i - 1]["energy_nodes"])
        nodes_curr = np.array(states[i]["energy_nodes"])
        if not np.array_equal(nodes_prev, nodes_curr):
            max_delta = max(max_delta, int(np.abs(nodes_curr - nodes_prev).max()))
    if max_delta == 0:
        return 3
    return min(NODE_DRIFT_MAGS, key=lambda v: abs(v - max_delta))


def infer_all(replay):
    """Infer all hidden parameters in dependency order."""
    states = replay["states"]
    actions = replay.get("actions", [])
    known = replay["known_params"]

    result = {}

    result["nebula_tile_drift_speed"] = infer_nebula_drift_speed(states)
    result["nebula_tile_vision_reduction"] = infer_nebula_vision_reduction(
        states, known
    )
    result["energy_node_drift_speed"] = infer_energy_node_drift_speed(states)
    result["energy_node_drift_magnitude"] = infer_energy_node_drift_magnitude(states)

    result["nebula_tile_energy_reduction"] = infer_nebula_energy_reduction(
        states, actions, known
    )
    neb_red = result["nebula_tile_energy_reduction"]

    result["unit_energy_void_factor"] = infer_void_factor(
        states, actions, known, neb_red
    )
    void_f = result["unit_energy_void_factor"]

    result["unit_sap_dropoff_factor"] = infer_sap_dropoff(
        states, actions, known, neb_red, void_f
    )

    return result


def main():
    db = sqlite3.connect(DB_PATH)

    # Get all non-example replay IDs
    replay_ids = [
        r[0]
        for r in db.execute(
            "SELECT id FROM replays WHERE description IS NULL OR description != 'example' ORDER BY id"
        )
    ]

    if not replay_ids:
        print("No non-example replays found in database.")
        db.close()
        return

    os.makedirs("/app/results", exist_ok=True)

    for rid in replay_ids:
        print(f"Processing replay {rid}...")
        replay = load_replay_from_db(db, rid)
        result = infer_all(replay)

        # Write temporary JSON file
        tmp_path = f"/tmp/result_{rid}.json"
        with open(tmp_path, "w") as f:
            json.dump(result, f, indent=2)

        # Submit via replay-tool (writes to both JSON output and SQLite results table)
        subprocess.run(
            ["/app/replay-tool", "submit", str(rid), tmp_path], check=True
        )
        print(f"  -> {result}")

    db.close()


if __name__ == "__main__":
    main()
