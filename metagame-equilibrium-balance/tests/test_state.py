
"""
Verification tests for meta-game equilibrium analysis and balance optimization.
"""

import json
import csv
import os
import sys
import math

import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, "/app")
from engine import load_config, run_matchup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TOLERANCE_WINRATE = 0.07
TOLERANCE_NASH = 0.10
MAX_REGRET = 0.05
NUM_VERIFICATION_GAMES = 2000
VERIFICATION_SEED = 99999

# ---------------------------------------------------------------------------
# Helpers (cached ground truth)
# ---------------------------------------------------------------------------
_gt_cache = {}


def _get_strategies(config):
    return sorted(config["strategies"].keys())


def compute_ground_truth_matrix(config, strategies, num_games, base_seed):
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
    return matrix


def solve_nash_equilibrium(payoff_matrix, strategies):
    n = len(strategies)
    A = np.zeros((n, n))
    for i, s1 in enumerate(strategies):
        for j, s2 in enumerate(strategies):
            A[i, j] = payoff_matrix[s1][s2] - 0.5

    c = [0.0] * n + [-1.0]
    A_ub, b_ub = [], []
    for j in range(n):
        row = [-A[i, j] for i in range(n)] + [1.0]
        A_ub.append(row)
        b_ub.append(0.0)
    A_eq = [[1.0] * n + [0.0]]
    b_eq = [1.0]
    bounds = [(0.0, None)] * n + [(None, None)]

    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                  bounds=bounds, method="highs")
    assert res.success, f"LP solver failed: {res.message}"
    probs = np.maximum(res.x[:n], 0.0)
    probs = probs / probs.sum()
    return {strategies[i]: float(probs[i]) for i in range(n)}


def compute_entropy(probs):
    return -sum(p * math.log(p) for p in probs if p > 1e-10)


def get_ground_truth():
    """Return cached ground-truth matrix & Nash for original config."""
    if not _gt_cache:
        cfg = load_config("/app/config.json")
        strats = _get_strategies(cfg)
        mat = compute_ground_truth_matrix(cfg, strats, NUM_VERIFICATION_GAMES, VERIFICATION_SEED)
        nash = solve_nash_equilibrium(mat, strats)
        _gt_cache["config"] = cfg
        _gt_cache["strategies"] = strats
        _gt_cache["matrix"] = mat
        _gt_cache["nash"] = nash
    return _gt_cache


def load_agent_matrix():
    """Load the agent's reported payoff matrix from CSV."""
    agent = {}
    with open("/app/results/payoff_matrix.csv") as f:
        reader = csv.reader(f)
        header = next(reader)
        strat_names = [h.strip() for h in header[1:]]
        for row in reader:
            rname = row[0].strip()
            agent[rname] = {}
            for j, s2 in enumerate(strat_names):
                agent[rname][s2] = float(row[j + 1])
    return agent, strat_names


# ===================================================================
# Test classes
# ===================================================================

class TestPayoffMatrix:

    def test_file_exists(self):
        assert os.path.exists("/app/results/payoff_matrix.csv"), \
            "Missing /app/results/payoff_matrix.csv"

    def test_format(self):
        with open("/app/results/payoff_matrix.csv") as f:
            reader = csv.reader(f)
            header = next(reader)
            cols = [h.strip() for h in header[1:]]
            assert len(cols) == 6, f"Expected 6 column headers, got {len(cols)}"
            rows = list(reader)
            assert len(rows) == 6, f"Expected 6 data rows, got {len(rows)}"
            for row in rows:
                vals = [float(v) for v in row[1:]]
                assert len(vals) == 6
                for v in vals:
                    assert 0.0 <= v <= 1.0, f"Value {v} outside [0,1]"

    def test_diagonal(self):
        agent, strats = load_agent_matrix()
        for s in strats:
            val = agent[s][s]
            assert abs(val - 0.5) < 0.05, \
                f"Diagonal [{s}][{s}] = {val}, expected ~0.5"

    def test_accuracy(self):
        gt = get_ground_truth()
        agent, _ = load_agent_matrix()
        errors = []
        for s1 in gt["strategies"]:
            for s2 in gt["strategies"]:
                if s1 == s2:
                    continue
                a_val = agent[s1][s2]
                g_val = gt["matrix"][s1][s2]
                if abs(a_val - g_val) > TOLERANCE_WINRATE:
                    errors.append(
                        f"  {s1} vs {s2}: agent={a_val:.3f}  truth={g_val:.3f}")
        assert not errors, \
            f"Win rates outside ±{TOLERANCE_WINRATE}:\n" + "\n".join(errors)


class TestNashEquilibrium:

    def test_file_exists(self):
        assert os.path.exists("/app/results/nash_equilibrium.json"), \
            "Missing /app/results/nash_equilibrium.json"

    def test_format(self):
        with open("/app/results/nash_equilibrium.json") as f:
            data = json.load(f)
        assert "equilibrium" in data, "Missing 'equilibrium' key"
        eq = data["equilibrium"]
        assert isinstance(eq, dict) and len(eq) == 6

    def test_probabilities_sum(self):
        with open("/app/results/nash_equilibrium.json") as f:
            data = json.load(f)
        total = sum(data["equilibrium"].values())
        assert abs(total - 1.0) < 0.02, f"Probabilities sum to {total}"

    def test_correctness(self):
        """Verify the agent's Nash equilibrium is consistent with their
        own submitted payoff matrix — compute Nash from the CSV and compare."""
        agent_mat, strats = load_agent_matrix()
        computed_nash = solve_nash_equilibrium(agent_mat, strats)

        with open("/app/results/nash_equilibrium.json") as f:
            agent_eq = json.load(f)["equilibrium"]

        errors = []
        for s in strats:
            a_p = agent_eq.get(s, 0.0)
            c_p = computed_nash.get(s, 0.0)
            if abs(a_p - c_p) > TOLERANCE_NASH:
                errors.append(f"  {s}: reported={a_p:.4f}  computed={c_p:.4f}")
        assert not errors, \
            f"Nash probs inconsistent with own matrix (±{TOLERANCE_NASH}):\n" + "\n".join(errors)

    def test_no_profitable_deviation(self):
        agent_mat, strats = load_agent_matrix()
        with open("/app/results/nash_equilibrium.json") as f:
            eq = json.load(f)["equilibrium"]

        # Expected payoff under the mixed strategy
        mixed = sum(eq[s1] * eq[s2] * agent_mat[s1][s2]
                     for s1 in strats for s2 in strats)

        for s_pure in strats:
            payoff = sum(eq[s2] * agent_mat[s_pure][s2] for s2 in strats)
            regret = payoff - mixed
            assert regret < MAX_REGRET, \
                f"{s_pure} regret = {regret:.4f} > {MAX_REGRET}"

    def test_ground_truth_regret(self):
        """Verify the agent's Nash equilibrium is approximately optimal
        against an independently simulated ground truth matrix."""
        gt = get_ground_truth()
        strats = gt["strategies"]
        gt_mat = gt["matrix"]

        with open("/app/results/nash_equilibrium.json") as f:
            agent_eq = json.load(f)["equilibrium"]

        game_value = sum(agent_eq.get(s1, 0) * agent_eq.get(s2, 0) * gt_mat[s1][s2]
                         for s1 in strats for s2 in strats)

        for s in strats:
            payoff = sum(agent_eq.get(s2, 0) * gt_mat[s][s2] for s2 in strats)
            regret = payoff - game_value
            assert regret < 0.10, \
                f"Strategy {s} has regret {regret:.4f} > 0.10 against ground truth"


class TestBalanceImprovement:

    def test_file_exists(self):
        assert os.path.exists("/app/results/balanced_config.json"), \
            "Missing /app/results/balanced_config.json"

    def test_valid_config(self):
        with open("/app/results/balanced_config.json") as f:
            cfg = json.load(f)
        assert "matchup_table" in cfg, "Missing matchup_table"
        assert "strategies" in cfg, "Missing strategies"
        required = [
            "warriors_vs_warriors", "warriors_vs_mages", "warriors_vs_archers",
            "mages_vs_warriors", "mages_vs_mages", "mages_vs_archers",
            "archers_vs_warriors", "archers_vs_mages", "archers_vs_archers",
        ]
        for k in required:
            assert k in cfg["matchup_table"], f"Missing key {k}"
            v = cfg["matchup_table"][k]
            assert 0.1 <= v <= 3.0, f"{k}={v} out of range"

    def test_strategies_unchanged(self):
        orig = load_config("/app/config.json")
        with open("/app/results/balanced_config.json") as f:
            bal = json.load(f)
        for sname, ostrat in orig["strategies"].items():
            assert sname in bal["strategies"], f"Missing strategy {sname}"
            bstrat = bal["strategies"][sname]
            for field in ("warriors", "mages", "archers", "lane_weights", "noise"):
                assert ostrat[field] == bstrat[field], \
                    f"{sname}.{field} was modified"

    def test_entropy_improved(self):
        gt = get_ground_truth()
        strats = gt["strategies"]
        orig_entropy = compute_entropy([gt["nash"][s] for s in strats])

        with open("/app/results/balanced_config.json") as f:
            bal_cfg = json.load(f)
        bal_mat = compute_ground_truth_matrix(
            bal_cfg, strats, NUM_VERIFICATION_GAMES, VERIFICATION_SEED + 2000)
        bal_nash = solve_nash_equilibrium(bal_mat, strats)
        bal_entropy = compute_entropy([bal_nash[s] for s in strats])

        assert bal_entropy > orig_entropy, \
            f"Balanced entropy ({bal_entropy:.4f}) <= original ({orig_entropy:.4f})"
