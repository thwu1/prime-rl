#!/usr/bin/env python3
"""
Pure-Python Lux AI S3 game simulator for test data generation.
Implements core mechanics matching the reference JAX engine's behaviour.
"""

import math
import json
import copy
import numpy as np

W = H = 24
MAX_UNITS = 16
NUM_TEAMS = 2
MAX_ENERGY_NODES = 6
EMPTY, NEBULA, ASTEROID = 0, 1, 2

DIRECTIONS = np.array([[0,0],[0,-1],[1,0],[0,1],[-1,0]], dtype=np.int16)
ADJACENT_8 = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]


class GameState:
    def __init__(self):
        self.pos = np.zeros((2, MAX_UNITS, 2), dtype=np.int16)
        self.energy = np.zeros((2, MAX_UNITS), dtype=np.int32)
        self.mask = np.zeros((2, MAX_UNITS), dtype=bool)
        self.tile_type = np.zeros((W, H), dtype=np.int16)
        self.energy_field = np.zeros((W, H), dtype=np.int16)
        self.energy_nodes = np.zeros((MAX_ENERGY_NODES, 2), dtype=np.int16)
        self.energy_node_fns = np.zeros((MAX_ENERGY_NODES, 4), dtype=np.float64)
        self.energy_nodes_mask = np.zeros(MAX_ENERGY_NODES, dtype=bool)
        self.vision_power = np.zeros((2, W, H), dtype=np.int16)
        self.team_points = np.zeros(2, dtype=np.int32)
        self.team_wins = np.zeros(2, dtype=np.int32)
        self.steps = 0
        self.match_steps = 0

    def deep_copy(self):
        s = GameState()
        for attr in ['pos','energy','mask','tile_type','energy_field',
                      'energy_nodes','energy_node_fns','energy_nodes_mask',
                      'vision_power','team_points','team_wins']:
            setattr(s, attr, getattr(self, attr).copy())
        s.steps = self.steps
        s.match_steps = self.match_steps
        return s

    def to_dict(self):
        # Convert energy to [e] shape per unit for compatibility with replay format
        energy_nested = [[[int(self.energy[t, u])] for u in range(MAX_UNITS)] for t in range(2)]
        return {
            "units": {
                "position": self.pos.tolist(),
                "energy": energy_nested,
            },
            "units_mask": self.mask.tolist(),
            "map_features": {
                "tile_type": self.tile_type.tolist(),
                "energy": self.energy_field.tolist(),
            },
            "energy_nodes": self.energy_nodes.tolist(),
            "vision_power_map": self.vision_power.tolist(),
            "team_points": self.team_points.tolist(),
            "team_wins": self.team_wins.tolist(),
            "steps": int(self.steps),
            "match_steps": int(self.match_steps),
        }


def compute_energy_field(state):
    """Recompute energy field from energy nodes."""
    field = np.zeros((W, H), dtype=np.float64)
    for i in range(MAX_ENERGY_NODES):
        if not state.energy_nodes_mask[i]:
            continue
        nx, ny = state.energy_nodes[i]
        fn_id = int(state.energy_node_fns[i, 0])
        px, py, pz = state.energy_node_fns[i, 1], state.energy_node_fns[i, 2], state.energy_node_fns[i, 3]
        for x in range(W):
            for y in range(H):
                d = math.sqrt((x - nx)**2 + (y - ny)**2)
                if fn_id == 0:
                    field[x, y] += math.sin(d * px + py) * pz
                else:
                    field[x, y] += (px / (d + 1) + py) * pz
    m = field.mean()
    if m < 0.25:
        field += (0.25 - m)
    field = np.round(field).astype(np.int16)
    field = np.clip(field, -20, 20)
    state.energy_field = field


def compute_vision(state, params):
    """Compute vision power map for both teams."""
    sr = params['unit_sensor_range']
    vr = params['nebula_tile_vision_reduction']
    state.vision_power = np.zeros((2, W, H), dtype=np.int16)
    for t in range(2):
        for u in range(MAX_UNITS):
            if not state.mask[t, u]:
                continue
            ux, uy = state.pos[t, u]
            for dx in range(-sr, sr + 1):
                for dy in range(-sr, sr + 1):
                    nx, ny = int(ux + dx), int(uy + dy)
                    if 0 <= nx < W and 0 <= ny < H:
                        md = max(abs(dx), abs(dy))
                        pwr = 1 + sr - md
                        state.vision_power[t, nx, ny] += pwr
            state.vision_power[t, int(ux), int(uy)] += 10
        # Nebula reduction
        neb_mask = state.tile_type == NEBULA
        state.vision_power[t] -= neb_mask.astype(np.int16) * vr


def drift_check(speed, step):
    """Return True if drift occurs at this step."""
    prev = (step - 1) * abs(speed) % 1.0
    curr = step * abs(speed) % 1.0
    return prev > curr


def drift_tiles(state, params):
    """Apply nebula/asteroid tile drift if triggered."""
    speed = params['nebula_tile_drift_speed']
    if drift_check(speed, state.steps):
        sign = 1 if speed > 0 else -1
        state.tile_type = np.roll(state.tile_type, shift=(sign, -sign), axis=(0, 1))


def drift_energy_nodes(state, params, rng):
    """Apply energy node drift if triggered."""
    speed = params['energy_node_drift_speed']
    mag = params['energy_node_drift_magnitude']
    if drift_check(speed, state.steps):
        n_half = MAX_ENERGY_NODES // 2
        deltas_half = np.round(rng.uniform(-mag, mag, size=(n_half, 2))).astype(np.int16)
        deltas_sym = np.column_stack([-deltas_half[:, 1], -deltas_half[:, 0]])
        deltas = np.concatenate([deltas_half, deltas_sym], axis=0)
        new_nodes = np.clip(state.energy_nodes + deltas, 0, W - 1).astype(np.int16)
        # Only apply to active nodes
        for i in range(MAX_ENERGY_NODES):
            if state.energy_nodes_mask[i]:
                state.energy_nodes[i] = new_nodes[i]


def move_units(state, actions, params):
    """Process movement actions."""
    mc = params['unit_move_cost']
    for t in range(2):
        for u in range(MAX_UNITS):
            if not state.mask[t, u]:
                continue
            a = int(actions[t][u][0])
            if a < 1 or a > 4:
                continue
            new_pos = state.pos[t, u].copy() + DIRECTIONS[a]
            new_pos = np.clip(new_pos, 0, W - 1).astype(np.int16)
            is_ast = state.tile_type[new_pos[0], new_pos[1]] == ASTEROID
            has_e = state.energy[t, u] >= mc
            if has_e and not is_ast:
                state.pos[t, u] = new_pos
                state.energy[t, u] -= mc


def resolve_saps(state, actions, params, orig_energy):
    """Process sap actions."""
    sc = params['unit_sap_cost']
    sr = params['unit_sap_range']
    df = params['unit_sap_dropoff_factor']

    for t in range(2):
        ot = 1 - t
        # Determine valid sappers and their targets
        sapping = np.zeros(MAX_UNITS, dtype=bool)
        targets = np.zeros((MAX_UNITS, 2), dtype=np.int16)
        for u in range(MAX_UNITS):
            if not state.mask[t, u]:
                continue
            if int(actions[t][u][0]) != 5:
                continue
            if orig_energy[t, u] < sc:
                continue
            dx, dy = int(actions[t][u][1]), int(actions[t][u][2])
            if max(abs(dx), abs(dy)) > sr:
                continue
            tx = int(state.pos[t, u, 0]) + dx
            ty = int(state.pos[t, u, 1]) + dy
            if tx < 0 or tx >= W or ty < 0 or ty >= H:
                continue
            sapping[u] = True
            targets[u] = [tx, ty]
            state.energy[t, u] -= sc

        # Apply damage to enemies
        for eu in range(MAX_UNITS):
            if not state.mask[ot, eu]:
                continue
            ex, ey = int(state.pos[ot, eu, 0]), int(state.pos[ot, eu, 1])
            # Direct hits
            direct = 0
            for u in range(MAX_UNITS):
                if sapping[u] and targets[u, 0] == ex and targets[u, 1] == ey:
                    direct += 1
            if direct > 0:
                state.energy[ot, eu] -= sc * direct
            # Adjacent hits
            adj = 0
            for u in range(MAX_UNITS):
                if not sapping[u]:
                    continue
                for ox, oy in ADJACENT_8:
                    if int(targets[u, 0]) + ox == ex and int(targets[u, 1]) + oy == ey:
                        adj += 1
            if adj > 0:
                state.energy[ot, eu] -= int(sc * df * adj)


def resolve_collisions(state, orig_energy):
    """Remove losing units on shared tiles."""
    # Build per-tile aggregate energy using original energy
    agg = np.zeros((2, W, H), dtype=np.int32)
    cnt = np.zeros((2, W, H), dtype=np.int16)
    for t in range(2):
        for u in range(MAX_UNITS):
            if not state.mask[t, u]:
                continue
            x, y = int(state.pos[t, u, 0]), int(state.pos[t, u, 1])
            agg[t, x, y] += orig_energy[t, u]
            cnt[t, x, y] += 1

    for t in range(2):
        ot = 1 - t
        for u in range(MAX_UNITS):
            if not state.mask[t, u]:
                continue
            x, y = int(state.pos[t, u, 0]), int(state.pos[t, u, 1])
            if cnt[ot, x, y] > 0:
                if agg[t, x, y] <= agg[ot, x, y]:
                    state.mask[t, u] = False


def update_energy(state, params):
    """Apply energy field and nebula reduction to all units."""
    nr = params['nebula_tile_energy_reduction']
    for t in range(2):
        for u in range(MAX_UNITS):
            if not state.mask[t, u]:
                continue
            x, y = int(state.pos[t, u, 0]), int(state.pos[t, u, 1])
            gain = int(state.energy_field[x, y])
            if state.tile_type[x, y] == NEBULA:
                gain -= nr
            old_e = int(state.energy[t, u])
            if old_e < 0 and old_e + gain < 0:
                pass  # Keep negative energy
            else:
                state.energy[t, u] = max(0, min(400, old_e + gain))


def spawn_units(state, params):
    """Spawn new units at corners."""
    sr = params.get('spawn_rate', 3)
    ie = params.get('init_unit_energy', 100)
    if state.match_steps % sr != 0:
        return
    spawn_positions = [(0, 0), (W - 1, H - 1)]
    for t in range(2):
        count = int(state.mask[t].sum())
        if count >= MAX_UNITS:
            continue
        # Find first available slot
        slot = -1
        for u in range(MAX_UNITS):
            if not state.mask[t, u]:
                slot = u
                break
        if slot < 0:
            continue
        sx, sy = spawn_positions[t]
        state.pos[t, slot] = [sx, sy]
        state.energy[t, slot] = ie
        state.mask[t, slot] = True


def game_step(state, actions, params, rng):
    """Execute one full game step. Modifies state in-place."""
    # 1. Energy field
    compute_energy_field(state)

    # 2. Remove dead units / match reset
    if state.match_steps == 0:
        state.mask[:] = False
    state.mask &= (state.energy >= 0)

    # 3. Move
    move_units(state, actions, params)

    # 4. Save original energy (post-move, pre-sap)
    orig_energy = state.energy.copy()

    # 5. Sap
    resolve_saps(state, actions, params, orig_energy)

    # 6. Pre-collision unit counts
    pre_cnt = np.zeros((2, W, H), dtype=np.int16)
    for t in range(2):
        for u in range(MAX_UNITS):
            if not state.mask[t, u]:
                continue
            x, y = int(state.pos[t, u, 0]), int(state.pos[t, u, 1])
            pre_cnt[t, x, y] += 1

    # 7. Build void maps BEFORE collision (using orig energy, pre-collision mask)
    void_map = np.zeros((2, W, H), dtype=np.int32)
    card = [(0, -1), (0, 1), (-1, 0), (1, 0)]
    pre_mask = state.mask.copy()
    for t in range(2):
        for u in range(MAX_UNITS):
            if not pre_mask[t, u]:
                continue
            x, y = int(state.pos[t, u, 0]), int(state.pos[t, u, 1])
            e = int(orig_energy[t, u])
            for dx, dy in card:
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H:
                    void_map[t, nx, ny] += e

    # 8. Collisions
    resolve_collisions(state, orig_energy)

    # 9. Apply void fields (using pre-computed void_map and pre_collision counts)
    vf = params['unit_energy_void_factor']
    for t in range(2):
        ot = 1 - t
        for u in range(MAX_UNITS):
            if not state.mask[t, u]:
                continue
            x, y = int(state.pos[t, u, 0]), int(state.pos[t, u, 1])
            opp_void = int(void_map[ot, x, y])
            my_cnt = max(int(pre_cnt[t, x, y]), 1)
            dmg = int(math.floor(vf * opp_void / my_cnt))
            state.energy[t, u] -= dmg

    # 10. Energy update
    update_energy(state, params)

    # 11. Spawn
    spawn_units(state, params)

    # 12. Remove units with negative energy (post energy update)
    # (Actually this happens at start of NEXT step, but we track here for cleanliness)

    # 13. Vision
    compute_vision(state, params)

    # 14. Drift
    drift_tiles(state, params)
    drift_energy_nodes(state, params, rng)

    # 15. Increment
    state.steps += 1
    state.match_steps += 1


def create_test_state(params, rng):
    """Create a game state suitable for testing parameter inference.
    Places units near each other so combat interactions happen."""
    s = GameState()

    # Create a map with nebula tiles in a distinctive pattern
    # Nebula band from (3,0) to (3,23) and (8,0) to (8,23) etc.
    for x in range(W):
        for y in range(H):
            if (x + y) % 7 == 0:
                s.tile_type[x, y] = NEBULA
            elif (x * 3 + y * 5) % 31 == 0:
                s.tile_type[x, y] = ASTEROID

    # Energy nodes
    s.energy_nodes[0] = [6, 10]
    s.energy_nodes[1] = [18, 8]
    s.energy_nodes[2] = [10, 15]
    s.energy_nodes[3] = [17, 14]  # symmetric of node 0: (W-1-10, H-1-6) = (13,17)
    s.energy_nodes[4] = [5, 15]   # symmetric of node 1
    s.energy_nodes[5] = [13, 8]   # symmetric of node 2
    s.energy_nodes_mask[:4] = True  # 4 active nodes

    # Energy node functions
    s.energy_node_fns[0] = [0, 1.2, 1.0, 4.0]  # sin(d*1.2 + 1.0) * 4.0
    s.energy_node_fns[1] = [0, 0.8, 0.5, 3.0]
    s.energy_node_fns[2] = [1, 2.0, 0.0, 2.0]  # (2/(d+1) + 0) * 2
    s.energy_node_fns[3] = [0, 1.2, 1.0, 4.0]
    s.energy_node_fns[4] = [0, 0.8, 0.5, 3.0]
    s.energy_node_fns[5] = [1, 2.0, 0.0, 2.0]

    # Place units near center for interactions
    # Team 0: units in the (8-12, 10-14) area
    team0_positions = [(8,10),(9,10),(10,10),(8,11),(10,12),(9,13),(11,10),(12,11)]
    # Team 1: units in the (12-16, 10-14) area
    team1_positions = [(13,10),(14,10),(13,11),(14,12),(15,10),(12,13),(13,13),(14,11)]

    for i, (x, y) in enumerate(team0_positions):
        s.pos[0, i] = [x, y]
        s.energy[0, i] = 150 + rng.integers(-30, 30)
        s.mask[0, i] = True

    for i, (x, y) in enumerate(team1_positions):
        s.pos[1, i] = [x, y]
        s.energy[1, i] = 150 + rng.integers(-30, 30)
        s.mask[1, i] = True

    s.steps = 1  # Start at step 1 to avoid step-0 drift ambiguity
    s.match_steps = 1

    compute_energy_field(s)
    compute_vision(s, params)

    return s


def generate_actions(state, params, step_num, rng):
    """Generate actions with periodic quiet phases for clean parameter inference.

    Action schedule (10-step cycle):
      0-2: all stationary — void + energy_reduction inference
      3:   team 0 saps, team 1 stays still — dropoff inference on team 1
      4-5: move toward center — positioning
      6-8: all stationary — void data
      9:   team 1 saps, team 0 stays still — dropoff inference on team 0
    """
    actions = [np.zeros((MAX_UNITS, 3), dtype=np.int16) for _ in range(2)]
    phase = step_num % 10

    sap_team = -1
    if phase == 3:
        sap_team = 0
    elif phase == 9:
        sap_team = 1

    for t in range(2):
        ot = 1 - t
        for u in range(MAX_UNITS):
            if not state.mask[t, u]:
                continue
            ux, uy = int(state.pos[t, u, 0]), int(state.pos[t, u, 1])

            if t == sap_team:
                # This team saps
                if state.energy[t, u] >= params['unit_sap_cost']:
                    best_d = 999
                    best_dx, best_dy = 0, 0
                    found = False
                    for eu in range(MAX_UNITS):
                        if not state.mask[ot, eu]:
                            continue
                        ex, ey = int(state.pos[ot, eu, 0]), int(state.pos[ot, eu, 1])
                        dx, dy = ex - ux, ey - uy
                        if max(abs(dx), abs(dy)) <= params['unit_sap_range']:
                            d = abs(dx) + abs(dy)
                            if d < best_d:
                                best_d = d
                                best_dx, best_dy = dx, dy
                                found = True
                    if found:
                        actions[t][u] = [5, best_dx, best_dy]
                # else: stay still (action 0)

            elif phase in (4, 5):
                # Movement phase: move toward center
                target_x = 12 if t == 0 else 11
                target_y = 11
                dx = np.sign(target_x - ux)
                dy = np.sign(target_y - uy)
                if abs(dx) >= abs(dy) and dx != 0:
                    actions[t][u][0] = 2 if dx > 0 else 4
                elif dy != 0:
                    actions[t][u][0] = 3 if dy > 0 else 1

            # All other phases: do nothing (action 0) — quiet for inference

    return actions


def generate_replay(seed, all_params, n_steps=60):
    """Generate a full replay with given parameters."""
    rng = np.random.default_rng(seed)
    state = create_test_state(all_params, rng)

    states = [state.to_dict()]
    all_actions = []

    for i in range(n_steps):
        actions = generate_actions(state, all_params, i, rng)
        all_actions.append({
            "player_0": actions[0].tolist(),
            "player_1": actions[1].tolist(),
        })
        game_step(state, actions, all_params, rng)
        states.append(state.to_dict())

    known_params = {
        "max_units": MAX_UNITS,
        "match_count_per_episode": 5,
        "max_steps_in_match": 100,
        "map_height": H,
        "map_width": W,
        "num_teams": 2,
        "unit_move_cost": all_params['unit_move_cost'],
        "unit_sap_cost": all_params['unit_sap_cost'],
        "unit_sap_range": all_params['unit_sap_range'],
        "unit_sensor_range": all_params['unit_sensor_range'],
    }

    return {
        "states": states,
        "actions": all_actions,
        "known_params": known_params,
    }
