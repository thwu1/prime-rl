"""
FightingICE Strategic Analyzer.
Computes frame advantage, optimal combos, punish tables, payoff matrix,
iterated strict dominance elimination (IESDS), and Nash equilibrium.

"""

import json
import math
import sys
import numpy as np
from scipy.optimize import linprog
import game_pb2


def load_moveset(path):
    with open(path, "rb") as f:
        ms = game_pb2.CharacterMoveSet()
        ms.ParseFromString(f.read())
    return ms


def load_rules(path):
    with open(path) as f:
        return json.load(f)


def compute_frame_advantage(moveset):
    """Derive frame advantage from move phase timing and stun mechanics.

    After a move connects, the attacker must finish active + recovery phases.
    The defender is locked in stun. FA = stun - (active + recovery).
    """
    result = {}
    for m in moveset.moves:
        fa_hit = m.hit_stun - m.active_frames - m.recovery_frames
        fa_block = m.block_stun - m.active_frames - m.recovery_frames
        result[m.name] = {"on_hit": fa_hit, "on_block": fa_block}
    return result


def compute_combo_window(move, hit_number, decay):
    """Determine if a follow-up can connect.

    Hit stun starts when the move becomes active (at startup_frames).
    Cancel starts at cancel_start_frame. Follow-up must complete its
    startup before hitstun expires: follow_up.startup <= startup + adjusted_hs - cancel_start.
    """
    adjusted_hs = move.hit_stun - decay * (hit_number - 1)
    if adjusted_hs <= 0 or move.cancel_start_frame <= 0:
        return 0
    return move.startup_frames + adjusted_hs - move.cancel_start_frame


def scaled_damage(base_damage, hit_number, scaling_per_hit, min_scaling):
    """Apply combo damage scaling: multiplier decreases linearly per hit,
    floored at minimum. Result rounded down."""
    scale = max(min_scaling, 1.0 - scaling_per_hit * (hit_number - 1))
    return math.floor(base_damage * scale)


def find_optimal_combo(moves_by_name, start_move_name, start_energy, rules):
    decay = rules["parameters"]["hit_stun_decay_per_hit"]
    scaling = rules["parameters"]["damage_scaling_per_hit"]
    min_scale = rules["parameters"]["minimum_damage_scaling"]
    max_hits = rules["parameters"]["max_combo_hits"]

    start_move = moves_by_name.get(start_move_name)
    if start_move is None:
        return [], 0
    if start_energy < start_move.energy_cost:
        return [], 0

    best = {"combo": [], "damage": 0}

    def dfs(current_move, hit_num, energy, combo, total_damage):
        dmg = scaled_damage(current_move.damage, hit_num, scaling, min_scale)
        new_total = total_damage + dmg
        new_energy = energy - current_move.energy_cost + current_move.energy_gain
        new_combo = combo + [current_move.name]

        if new_total > best["damage"]:
            best["damage"] = new_total
            best["combo"] = list(new_combo)

        if current_move.is_knockdown or hit_num >= max_hits or current_move.cancel_start_frame <= 0:
            return

        window = compute_combo_window(current_move, hit_num, decay)
        if window <= 0:
            return

        for target_name in current_move.cancel_into:
            target = moves_by_name.get(target_name)
            if target is None or target.startup_frames > window or new_energy < target.energy_cost:
                continue
            dfs(target, hit_num + 1, new_energy, new_combo, new_total)

    dfs(start_move, 1, start_energy, [], 0)
    return best["combo"], best["damage"]


def is_throw(move_name):
    return "THROW" in move_name


def compute_punish_table(moveset, frame_advantage, combo_results, ref_energy):
    ref_energy_str = str(ref_energy)
    punish_table = {}

    for m in moveset.moves:
        fa_block = frame_advantage[m.name]["on_block"]
        frames_avail = abs(fa_block)

        best_starter = None
        best_damage = 0
        best_combo = []

        for candidate in moveset.moves:
            if is_throw(candidate.name):
                continue
            if candidate.startup_frames > frames_avail:
                continue
            cdata = combo_results[candidate.name][ref_energy_str]
            if cdata["total_damage"] > best_damage:
                best_damage = cdata["total_damage"]
                best_combo = cdata["combo"]
                best_starter = candidate.name

        punish_table[m.name] = {
            "punish_starter": best_starter,
            "punish_combo": best_combo,
            "punish_damage": best_damage,
            "frames_available": frames_avail,
        }

    return punish_table


def build_payoff_matrix(moveset, combo_results, punish_table, ref_energy):
    ref_energy_str = str(ref_energy)
    move_names = [m.name for m in moveset.moves]
    options = move_names + ["BLOCK"]
    n = len(options)

    startup_map = {}
    for m in moveset.moves:
        startup_map[m.name] = m.startup_frames

    combo_dmg = {}
    for name in move_names:
        combo_dmg[name] = combo_results[name][ref_energy_str]["total_damage"]

    punish_dmg = {}
    for name in move_names:
        punish_dmg[name] = punish_table[name]["punish_damage"]

    matrix = [[0] * n for _ in range(n)]

    for i, opt_i in enumerate(options):
        for j, opt_j in enumerate(options):
            if i == j:
                continue

            i_block = opt_i == "BLOCK"
            j_block = opt_j == "BLOCK"
            i_throw = not i_block and is_throw(opt_i)
            j_throw = not j_block and is_throw(opt_j)
            i_attack = not i_block and not i_throw
            j_attack = not j_block and not j_throw

            if i_attack and j_attack:
                si, sj = startup_map[opt_i], startup_map[opt_j]
                if si < sj:
                    matrix[i][j] = combo_dmg[opt_i]
                elif si > sj:
                    matrix[i][j] = -combo_dmg[opt_j]
                else:
                    matrix[i][j] = combo_dmg[opt_i] - combo_dmg[opt_j]
            elif i_attack and j_block:
                matrix[i][j] = -punish_dmg[opt_i]
            elif i_block and j_attack:
                matrix[i][j] = punish_dmg[opt_j]
            elif i_attack and j_throw:
                matrix[i][j] = combo_dmg[opt_i]
            elif i_throw and j_attack:
                matrix[i][j] = -combo_dmg[opt_j]
            elif i_throw and j_block:
                matrix[i][j] = combo_dmg[opt_i]
            elif i_block and j_throw:
                matrix[i][j] = -combo_dmg[opt_j]
            # throw_vs_throw and block_vs_block remain 0

    return {"options": options, "matrix": matrix}


def compute_iesds(payoff_data):
    """Iterated Elimination of Strictly Dominated Strategies.

    In each round, identify all strategies strictly dominated by some
    mixed strategy over the remaining strategies (via LP). Eliminate
    simultaneously. Repeat until stable.
    """
    options = payoff_data["options"]
    M = np.array(payoff_data["matrix"], dtype=float)
    n = len(options)
    active = list(range(n))
    elimination_rounds = []
    round_num = 0

    while True:
        M_sub = M[np.ix_(active, active)]
        nsub = len(active)
        dominated = set()

        for s in range(nsub):
            # Check if strategy s is strictly dominated by a mixture of others.
            # LP: find p >= 0 over others, sum p = 1, and eps >= 0
            # such that for all j: sum_k p[k]*M_sub[others[k]][j] - M_sub[s][j] >= eps
            # Maximize eps. If optimal eps > 0, s is strictly dominated.
            others = [i for i in range(nsub) if i != s]
            m = len(others)
            if m == 0:
                continue

            # Variables: p[0..m-1], eps
            c = np.zeros(m + 1)
            c[-1] = -1.0  # maximize eps

            # Constraints: for each column j:
            #   sum_k p[k]*M_sub[others[k]][j] - eps >= M_sub[s][j]
            #   => -sum_k p[k]*M_sub[others[k]][j] + eps <= -M_sub[s][j]
            A_ub = np.zeros((nsub, m + 1))
            b_ub = np.zeros(nsub)
            for j in range(nsub):
                for k_idx, k in enumerate(others):
                    A_ub[j][k_idx] = -M_sub[k][j]
                A_ub[j][-1] = 1.0
                b_ub[j] = -M_sub[s][j]

            A_eq = np.zeros((1, m + 1))
            A_eq[0, :m] = 1.0
            b_eq = np.array([1.0])

            bounds = [(0, None)] * m + [(0, None)]

            result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                             bounds=bounds, method="highs",
                             options={"presolve": True})

            if result.success and result.x[-1] > 1e-8:
                dominated.add(s)

        if not dominated:
            break

        round_num += 1
        eliminated_names = sorted([options[active[d]] for d in dominated])
        elimination_rounds.append({
            "round": round_num,
            "eliminated": eliminated_names,
        })

        dom_global = {active[d] for d in dominated}
        active = [i for i in active if i not in dom_global]

    survivors = sorted([options[i] for i in active])
    return {
        "elimination_rounds": elimination_rounds,
        "survivors": survivors,
    }


def solve_nash_equilibrium(payoff_data):
    options = payoff_data["options"]
    M = np.array(payoff_data["matrix"], dtype=float)
    n = len(options)

    # LP: maximize v subject to  sum_i p[i]*M[i][j] >= v for all j,
    #                            sum_i p[i] = 1, p[i] >= 0
    c = np.zeros(n + 1)
    c[-1] = -1.0

    A_ub = np.zeros((n, n + 1))
    for j in range(n):
        for i in range(n):
            A_ub[j][i] = -M[i][j]
        A_ub[j][n] = 1.0
    b_ub = np.zeros(n)

    A_eq = np.zeros((1, n + 1))
    A_eq[0, :n] = 1.0
    b_eq = np.array([1.0])

    bounds = [(0, None)] * n + [(None, None)]

    result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                     bounds=bounds, method="highs")

    if not result.success:
        raise RuntimeError(f"LP solver failed: {result.message}")

    probs = result.x[:n]
    game_value = result.x[n]

    probs = np.maximum(probs, 0.0)
    total = probs.sum()
    if total > 0:
        probs = probs / total

    strategy = {}
    support = []
    for i, opt in enumerate(options):
        p = round(float(probs[i]), 6)
        strategy[opt] = p
        if p > 1e-6:
            support.append(opt)

    return {
        "game_value": round(float(game_value), 2),
        "strategy": strategy,
        "support": sorted(support),
    }


def main():
    moveset = load_moveset("/app/data/character_zen.bin")
    rules = load_rules("/app/data/rules.json")
    moves_by_name = {m.name: m for m in moveset.moves}

    ref_energy = rules["analysis_parameters"]["reference_energy"]
    energy_levels = sorted(set(
        rules["analysis_parameters"]["starting_energy_levels"] + [ref_energy]
    ))

    # 1. Frame advantage
    fa = compute_frame_advantage(moveset)
    with open("/app/output/frame_advantage.json", "w") as f:
        json.dump(fa, f, indent=2)
    print(f"Frame advantage: {len(fa)} moves")

    # 2. Optimal combos
    combos = {}
    for move in moveset.moves:
        combos[move.name] = {}
        for energy in energy_levels:
            combo, damage = find_optimal_combo(moves_by_name, move.name, energy, rules)
            combos[move.name][str(energy)] = {
                "combo": combo,
                "total_damage": damage,
                "hit_count": len(combo),
            }
    with open("/app/output/optimal_combos.json", "w") as f:
        json.dump(combos, f, indent=2)
    print(f"Optimal combos: {len(combos)} moves x {len(energy_levels)} energy levels")

    # 3. Punish table
    punish = compute_punish_table(moveset, fa, combos, ref_energy)
    with open("/app/output/punish_table.json", "w") as f:
        json.dump(punish, f, indent=2)
    print(f"Punish table: {len(punish)} moves")

    # 4. Payoff matrix
    payoff = build_payoff_matrix(moveset, combos, punish, ref_energy)
    with open("/app/output/payoff_matrix.json", "w") as f:
        json.dump(payoff, f, indent=2)
    print(f"Payoff matrix: {len(payoff['options'])}x{len(payoff['options'])}")

    # 5. Dominance analysis (IESDS)
    dominance = compute_iesds(payoff)
    with open("/app/output/dominance_analysis.json", "w") as f:
        json.dump(dominance, f, indent=2)
    print(f"IESDS: {len(dominance['elimination_rounds'])} rounds, "
          f"{len(dominance['survivors'])} survivors: {dominance['survivors']}")

    # 6. Nash equilibrium
    nash = solve_nash_equilibrium(payoff)
    with open("/app/output/nash_equilibrium.json", "w") as f:
        json.dump(nash, f, indent=2)
    print(f"Nash equilibrium: value={nash['game_value']}, support={nash['support']}")


if __name__ == "__main__":
    main()
