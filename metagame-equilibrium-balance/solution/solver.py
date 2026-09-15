#!/usr/bin/env python3

"""
Solution for the meta-game equilibrium analysis and balance optimization task.

Steps:
  1. Compute the 6x6 pairwise win-rate matrix via simulation.
  2. Formulate and solve the Nash Equilibrium as a linear program.
  3. Search over symmetric matchup multiplier values to maximize
     Nash Equilibrium entropy (= meta-game balance).
"""

import json
import sys
import os
import csv
import math
import copy

sys.path.insert(0, "/app")
from engine import load_config, run_matchup

import numpy as np
from scipy.optimize import linprog


# -------------------------------------------------------------------
# Core helpers
# -------------------------------------------------------------------

def compute_payoff_matrix(config, strategies, num_games=2000, base_seed=42,
                          verbose=False):
    """Run round-robin tournament and return win-rate matrix."""
    n = len(strategies)
    matrix = {}
    for i, s1 in enumerate(strategies):
        matrix[s1] = {}
        for j, s2 in enumerate(strategies):
            if s1 == s2:
                matrix[s1][s2] = 0.5
            else:
                res = run_matchup(s1, s2, config, num_games, base_seed + i * n + j)
                matrix[s1][s2] = res["win_rate_1"]
                if verbose:
                    print(f"  {s1:10s} vs {s2:10s}: {res['win_rate_1']:.3f}")
    return matrix


def solve_nash(matrix, strategies):
    """Compute Nash Equilibrium of a 2-player zero-sum game via LP.

    For payoff matrix A (row = player 1 strategy, col = player 2):
        maximize  v
        s.t.      A^T p >= v * 1      (for each column j)
                  sum(p) = 1
                  p >= 0
    """
    n = len(strategies)
    A = np.zeros((n, n))
    for i, s1 in enumerate(strategies):
        for j, s2 in enumerate(strategies):
            A[i, j] = matrix[s1][s2] - 0.5  # centre on zero

    # Variables: [p_0 .. p_{n-1}, v]
    c = [0.0] * n + [-1.0]          # minimise -v  =>  maximise v

    A_ub, b_ub = [], []
    for j in range(n):
        # -sum_i A[i,j] p_i + v <= 0
        row = [-A[i, j] for i in range(n)] + [1.0]
        A_ub.append(row)
        b_ub.append(0.0)

    A_eq = [[1.0] * n + [0.0]]
    b_eq = [1.0]
    bounds = [(0.0, None)] * n + [(None, None)]

    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                  bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"LP failed: {res.message}")

    probs = np.maximum(res.x[:n], 0.0)
    probs = probs / probs.sum()
    return {strategies[i]: float(probs[i]) for i in range(n)}


def entropy(probs_dict):
    return -sum(p * math.log(p) for p in probs_dict.values() if p > 1e-10)


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main():
    os.makedirs("/app/results", exist_ok=True)

    config = load_config("/app/config.json")
    strategies = sorted(config["strategies"].keys())
    print(f"Strategies: {strategies}\n")

    # ---- Step 1: payoff matrix ----
    print("=== Step 1: Compute payoff matrix (2000 games/matchup) ===")
    matrix = compute_payoff_matrix(config, strategies, num_games=2000, base_seed=42,
                                   verbose=True)

    with open("/app/results/payoff_matrix.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([""] + strategies)
        for s1 in strategies:
            w.writerow([s1] + [f"{matrix[s1][s2]:.4f}" for s2 in strategies])
    print("\nPayoff matrix written to /app/results/payoff_matrix.csv\n")

    # ---- Step 2: Nash Equilibrium ----
    print("=== Step 2: Compute Nash Equilibrium ===")
    nash = solve_nash(matrix, strategies)
    ent = entropy(nash)
    max_ent = math.log(len(strategies))

    game_val = sum(nash[s1] * nash[s2] * matrix[s1][s2]
                   for s1 in strategies for s2 in strategies)

    eq_result = {
        "equilibrium": nash,
        "game_value": round(game_val, 6),
        "entropy": round(ent, 6),
        "max_entropy": round(max_ent, 6),
        "balance_ratio": round(ent / max_ent, 6),
    }
    with open("/app/results/nash_equilibrium.json", "w") as f:
        json.dump(eq_result, f, indent=2)

    for s, p in sorted(nash.items(), key=lambda x: -x[1]):
        print(f"  {s:10s}  {p:.4f}")
    print(f"\nEntropy: {ent:.4f}  (max {max_ent:.4f},  ratio {ent/max_ent:.1%})\n")

    # ---- Step 3: Balance optimisation ----
    print("=== Step 3: Optimise matchup multipliers for balance ===")

    best_ent = 0.0
    best_cfg = None

    # Grid-search over symmetric advantage / disadvantage values
    for adv in [1.3, 1.4, 1.5, 1.6, 1.7, 1.75]:
        for disadv in [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6]:
            trial = copy.deepcopy(config)
            mt = trial["matchup_table"]
            mt["warriors_vs_archers"] = adv
            mt["mages_vs_warriors"] = adv
            mt["archers_vs_mages"] = adv
            mt["warriors_vs_mages"] = disadv
            mt["mages_vs_archers"] = disadv
            mt["archers_vs_warriors"] = disadv

            m = compute_payoff_matrix(trial, strategies,
                                      num_games=500, base_seed=7777)
            n = solve_nash(m, strategies)
            e = entropy(n)

            if e > best_ent:
                best_ent = e
                best_cfg = trial
                print(f"  NEW BEST  adv={adv:.2f}  disadv={disadv:.2f}  "
                      f"entropy={e:.4f}")
                # Write immediately so file exists even if process is interrupted
                with open("/app/results/balanced_config.json", "w") as f:
                    json.dump(best_cfg, f, indent=2)

    print(f"\nOriginal entropy:  {ent:.4f}")
    print(f"Balanced entropy:  {best_ent:.4f}")
    print(f"Improvement:       {best_ent - ent:+.4f}")
    print("\nAll results written to /app/results/")


if __name__ == "__main__":
    main()
