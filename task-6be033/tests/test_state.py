
"""
Verification tests for multi-objective game balance optimization with
mechanism discovery and game-theoretic analysis.

Contains an independent reference copy of the game engine (matching the actual
woa-sim simulator) to prevent tampering. Also verifies that the solver
correctly identified hidden mechanics and computed valid game-theoretic
artifacts (payoff matrix, Nash equilibrium).
"""

import json
import math
import os
import random
import sqlite3
import pytest


# ========================================================================
# REFERENCE GAME ENGINE — independent copy for verification
# ========================================================================

MAX_TURNS = 100
ATTACK, DEFEND, CHARGE, CAST = 0, 1, 2, 3

PARAM_SPEC = {
    "base_hp":       {"min": 20, "max": 100},
    "base_mana":     {"min": 3,  "max": 25},
    "attack_damage": {"min": 2,  "max": 15},
    "defend_block":  {"min": 1,  "max": 10},
    "charge_gain":   {"min": 1,  "max": 8},
    "spell_damage":  {"min": 5,  "max": 25},
    "spell_cost":    {"min": 3,  "max": 20},
    "mana_regen":    {"min": 0,  "max": 5},
}

STRATEGIES = ["heuristic", "aggressive", "defensive"]

ALL_MATCHUPS = [
    "heuristic-vs-heuristic",
    "heuristic-vs-aggressive",
    "heuristic-vs-defensive",
    "aggressive-vs-aggressive",
    "aggressive-vs-defensive",
    "defensive-vs-defensive",
]


class PlayerState:
    __slots__ = ["hp", "mana", "shield", "consec_atk"]

    def __init__(self, hp, mana):
        self.hp = hp
        self.mana = mana
        self.shield = 0
        self.consec_atk = 0


class Game:
    def __init__(self, params):
        self.p = params
        self.players = [
            PlayerState(params["base_hp"], params["base_mana"]),
            PlayerState(params["base_hp"], params["base_mana"]),
        ]
        self.turn = 0
        self.ply = 0
        self.current = 0
        self.history = []
        self.done = False
        self.winner = None

    def legal_actions(self):
        me = self.players[self.current]
        acts = [ATTACK, DEFEND, CHARGE]
        if me.mana >= self.p["spell_cost"]:
            acts.append(CAST)
        return acts

    def step(self, action):
        if self.done:
            return
        me = self.players[self.current]
        opp = self.players[1 - self.current]
        me.shield = max(0, me.shield - 1)

        if action == ATTACK:
            raw = self.p["attack_damage"]
            me.consec_atk += 1
            if me.consec_atk >= 3:
                raw = int(raw * 1.25)
            blocked = min(raw, opp.shield)
            damage = max(1, raw - blocked)
            if me.hp <= self.p["base_hp"] * 0.25:
                damage = int(damage * 1.5)
            opp.hp -= damage
            opp.shield = max(0, opp.shield - raw)
        elif action == DEFEND:
            me.consec_atk = 0
            gain = self.p["defend_block"]
            if self.turn > 50:
                factor = max(0.3, 1.0 - (self.turn - 50) * 0.014)
                gain = max(1, int(gain * factor))
            cap = self.p["defend_block"] * 2
            me.shield = min(me.shield + gain, cap)
        elif action == CHARGE:
            me.consec_atk = 0
            me.mana += self.p["charge_gain"]
        elif action == CAST:
            me.consec_atk = 0
            me.mana -= self.p["spell_cost"]
            base_dmg = self.p["spell_damage"]
            if me.mana > 0:
                ratio = me.mana / self.p["spell_cost"]
                base_dmg += int(self.p["spell_damage"] * 0.1 * ratio)
            eff_shield = opp.shield // 2
            damage = max(1, base_dmg - eff_shield)
            opp.hp -= damage
            opp.shield = max(0, opp.shield - base_dmg // 3)

        me.mana += self.p["mana_regen"]
        self.history.append((self.current, action))

        if opp.hp <= 0:
            self.done = True
            self.winner = self.current
            return

        self.ply += 1
        if self.current == 1:
            self.turn += 1
        self.current = 1 - self.current

        # Attrition: after turn 50, symmetric HP drain each full turn
        if self.current == 0 and self.turn > 50:
            drain = 1 + (self.turn - 50) // 10
            self.players[0].hp -= drain
            self.players[1].hp -= drain
            for idx in [0, 1]:
                self.players[idx].hp = max(0, self.players[idx].hp)
            if self.players[0].hp <= 0 or self.players[1].hp <= 0:
                self.done = True
                if self.players[0].hp > self.players[1].hp:
                    self.winner = 0
                elif self.players[1].hp > self.players[0].hp:
                    self.winner = 1
                else:
                    self.winner = None
                return

        if self.turn >= MAX_TURNS:
            self.done = True
            if self.players[0].hp > self.players[1].hp:
                self.winner = 0
            elif self.players[1].hp > self.players[0].hp:
                self.winner = 1
            else:
                self.winner = None


def heuristic_player(game, rng):
    acts = game.legal_actions()
    me = game.players[game.current]
    opp = game.players[1 - game.current]
    p = game.p
    if CAST in acts:
        eff = opp.shield // 2
        if max(1, p["spell_damage"] - eff) >= opp.hp:
            return CAST
    raw = p["attack_damage"]
    blocked = min(raw, opp.shield)
    admg = max(1, raw - blocked)
    if admg >= opp.hp:
        return ATTACK
    if me.hp < p["base_hp"] * 0.35 and me.shield < p["defend_block"]:
        if rng.random() < 0.6:
            return DEFEND
    if CAST in acts and me.mana >= p["spell_cost"] * 1.3:
        eff = opp.shield // 2
        if max(1, p["spell_damage"] - eff) > admg:
            return CAST
    if me.mana < p["spell_cost"] and p["spell_damage"] > p["attack_damage"]:
        if rng.random() < 0.45:
            return CHARGE
    if me.shield == 0 and p["attack_damage"] > p["base_hp"] * 0.08:
        if rng.random() < 0.25:
            return DEFEND
    return ATTACK


def aggressive_player(game, rng):
    acts = game.legal_actions()
    me = game.players[game.current]
    opp = game.players[1 - game.current]
    p = game.p
    if CAST in acts:
        eff = opp.shield // 2
        if max(1, p["spell_damage"] - eff) >= opp.hp:
            return CAST
    raw = p["attack_damage"]
    blocked = min(raw, opp.shield)
    if max(1, raw - blocked) >= opp.hp:
        return ATTACK
    if CAST in acts and p["spell_damage"] >= p["attack_damage"]:
        return CAST
    if me.mana < p["spell_cost"] and p["spell_damage"] >= p["attack_damage"] * 2:
        if rng.random() < 0.3:
            return CHARGE
    return ATTACK


def defensive_player(game, rng):
    acts = game.legal_actions()
    me = game.players[game.current]
    opp = game.players[1 - game.current]
    p = game.p
    if CAST in acts:
        eff = opp.shield // 2
        if max(1, p["spell_damage"] - eff) >= opp.hp:
            return CAST
    raw = p["attack_damage"]
    blocked = min(raw, opp.shield)
    if max(1, raw - blocked) >= opp.hp:
        return ATTACK
    if me.hp < p["base_hp"] * 0.5 and me.shield < p["defend_block"]:
        if rng.random() < 0.65:
            return DEFEND
    if me.shield == 0:
        if rng.random() < 0.4:
            return DEFEND
    if CAST in acts and me.mana >= p["spell_cost"] * 1.5:
        if opp.shield == 0 or p["spell_damage"] > opp.shield:
            if rng.random() < 0.7:
                return CAST
    if me.mana < p["spell_cost"] * 1.5:
        if rng.random() < 0.5:
            return CHARGE
    if opp.hp < p["base_hp"] * 0.3:
        return ATTACK
    if rng.random() < 0.55:
        return DEFEND
    return ATTACK


AI_REGISTRY = {
    "heuristic": heuristic_player,
    "aggressive": aggressive_player,
    "defensive": defensive_player,
}


def play_game(params, p1_fn, p2_fn, seed):
    rng = random.Random(seed)
    game = Game(params)
    fns = [p1_fn, p2_fn]
    while not game.done:
        action = fns[game.current](game, rng)
        if action not in game.legal_actions():
            action = game.legal_actions()[0]
        game.step(action)
    return {
        "winner": game.winner,
        "turns": game.turn,
        "history": game.history,
        "p1_hp": game.players[0].hp,
        "p2_hp": game.players[1].hp,
    }


def evaluate_matchup(params, p1_name, p2_name, n_games=200, base_seed=42):
    p1_fn = AI_REGISTRY[p1_name]
    p2_fn = AI_REGISTRY[p2_name]
    results = []
    for i in range(n_games):
        results.append(play_game(params, p1_fn, p2_fn, seed=base_seed + i))

    n = len(results)
    p1_wins = sum(1 for r in results if r["winner"] == 0)
    p2_wins = sum(1 for r in results if r["winner"] == 1)
    draws = sum(1 for r in results if r["winner"] is None)
    win_rate = p1_wins / n
    draw_rate = draws / n
    avg_turns = sum(r["turns"] for r in results) / n

    fairness = max(0.0, 1.0 - 2.0 * abs(win_rate - 0.5))
    decisiveness = 1.0 - draw_rate

    if 30 <= avg_turns <= 70:
        depth = 1.0
    elif avg_turns < 30:
        depth = max(0.0, avg_turns / 30.0)
    else:
        depth = max(0.0, 1.0 - (avg_turns - 70) / 30.0)

    action_counts = {}
    total_actions = 0
    for r in results:
        for _, a in r["history"]:
            action_counts[a] = action_counts.get(a, 0) + 1
            total_actions += 1

    if total_actions > 0:
        entropy = 0.0
        for cnt in action_counts.values():
            p_val = cnt / total_actions
            if p_val > 0:
                entropy -= p_val * math.log2(p_val)
        variety = entropy / math.log2(4)
    else:
        variety = 0.0

    composite = 0.35 * fairness + 0.25 * decisiveness + 0.25 * depth + 0.15 * variety

    return {
        "matchup": f"{p1_name}-vs-{p2_name}",
        "n_games": n,
        "p1_wins": p1_wins,
        "p2_wins": p2_wins,
        "draws": draws,
        "win_rate": round(win_rate, 6),
        "draw_rate": round(draw_rate, 6),
        "avg_turns": round(avg_turns, 4),
        "fairness": round(fairness, 6),
        "decisiveness": round(decisiveness, 6),
        "depth": round(depth, 6),
        "variety": round(variety, 6),
        "composite": round(composite, 6),
    }


def validate_params(params):
    for key, spec in PARAM_SPEC.items():
        if key not in params:
            return False
        v = params[key]
        if not isinstance(v, int):
            return False
        if v < spec["min"] or v > spec["max"]:
            return False
    return True


# ========================================================================
# HIDDEN MECHANICS SPECIFICATION (for verifying discovery)
# ========================================================================

HIDDEN_MECHANICS_SPEC = [
    {
        "id": "consecutive_attack",
        "keyword_groups": [
            ["consecutive", "combo", "streak", "repeat", "successive",
             "chain", "row", "sequential", "series", "multi"],
            ["attack", "damage", "25", "1.25", "bonus", "amplif",
             "increase", "hit", "strike"],
        ],
    },
    {
        "id": "low_hp_boost",
        "keyword_groups": [
            ["critical", "low hp", "low_hp", "desperate", "quarter",
             "25%", "dying", "threshold", "below", "health low",
             "near death", "wounded", "injured", "weak"],
            ["damage", "1.5", "50%", "boost", "multipl", "increase",
             "bonus", "extra", "amplif", "enhanced"],
        ],
    },
    {
        "id": "shield_fatigue",
        "keyword_groups": [
            ["fatigue", "diminish", "degrad", "decay", "weaken",
             "reduc", "less effective", "wane", "deteriorat",
             "decreasing", "scaling down"],
            ["shield", "defend", "block", "turn 50", "late",
             "after 50", "prolonged", "long game"],
        ],
    },
    {
        "id": "mana_surplus",
        "keyword_groups": [
            ["surplus", "excess", "leftover", "remaining", "extra",
             "unused", "overflow", "reserve", "spare", "residual",
             "stored"],
            ["spell", "cast", "mana", "magic", "damage", "bonus",
             "scaling", "power"],
        ],
    },
    {
        "id": "attrition_drain",
        "keyword_groups": [
            ["attrition", "drain", "bleed", "tick", "dot", "passive",
             "gradual", "overtime", "over time", "erosion", "sap",
             "wither", "chip", "burn"],
            ["hp", "health", "hit point", "life", "both", "symmetric",
             "player", "damage", "lose", "loss"],
        ],
    },
]


def _mechanic_matches_entry(spec, entry_text):
    """Check if a mechanic specification matches an entry's text."""
    text = entry_text.lower().replace("-", " ").replace("_", " ")
    for group in spec["keyword_groups"]:
        if not any(kw.lower() in text for kw in group):
            return False
    return True


# ========================================================================
# TEST CONSTANTS
# ========================================================================

RESULTS_PATH = "/app/results/optimal_params.json"
DB_PATH = "/app/results/tournament.db"
REPORT_PATH = "/app/results/balance_report.json"
MECHANICS_PATH = "/app/results/mechanics_report.json"
PAYOFF_PATH = "/app/results/payoff_matrix.json"
NASH_PATH = "/app/results/nash_equilibrium.json"

VERIFICATION_SEED = 50000
VERIFICATION_GAMES = 300
ROBUSTNESS_SEED = 60000
PAYOFF_GAMES = 500


# ========================================================================
# FIXTURES
# ========================================================================

@pytest.fixture(scope="module")
def submitted_params():
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert "params" in data, "JSON must contain a 'params' key"
    return data["params"]


@pytest.fixture(scope="module")
def all_matchup_results(submitted_params):
    results = {}
    for mu in ALL_MATCHUPS:
        p1, p2 = mu.split("-vs-")
        metrics = evaluate_matchup(
            submitted_params, p1, p2, VERIFICATION_GAMES, VERIFICATION_SEED
        )
        results[mu] = metrics
    return results


@pytest.fixture(scope="module")
def strategy_win_rates(all_matchup_results):
    strat_games = {s: 0 for s in STRATEGIES}
    strat_wins = {s: 0 for s in STRATEGIES}
    for mu, metrics in all_matchup_results.items():
        p1, p2 = mu.split("-vs-")
        n = metrics["n_games"]
        strat_games[p1] += n
        strat_games[p2] += n
        strat_wins[p1] += metrics["p1_wins"]
        strat_wins[p2] += metrics["p2_wins"]
    return {
        s: strat_wins[s] / strat_games[s] if strat_games[s] > 0 else 0.0
        for s in STRATEGIES
    }


@pytest.fixture(scope="module")
def robustness_results(submitted_params):
    results = {}
    for mu in ALL_MATCHUPS:
        p1, p2 = mu.split("-vs-")
        metrics = evaluate_matchup(
            submitted_params, p1, p2, VERIFICATION_GAMES, ROBUSTNESS_SEED
        )
        results[mu] = metrics
    return results


@pytest.fixture(scope="module")
def submitted_mechanics():
    with open(MECHANICS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def submitted_payoff_matrix():
    with open(PAYOFF_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def submitted_nash_eq():
    with open(NASH_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference_payoff(submitted_params):
    """Compute reference 3x3 payoff matrix via simulation."""
    strats = STRATEGIES
    matrix = [[0.0] * 3 for _ in range(3)]
    for i, si in enumerate(strats):
        for j, sj in enumerate(strats):
            metrics = evaluate_matchup(
                submitted_params, si, sj, PAYOFF_GAMES, VERIFICATION_SEED
            )
            matrix[i][j] = metrics["win_rate"]
    return matrix


# ========================================================================
# TESTS: Parameter Validation
# ========================================================================

def test_params_complete(submitted_params):
    """All 8 required parameters must be present."""
    for key in PARAM_SPEC:
        assert key in submitted_params, f"Missing parameter: {key}"


def test_params_are_integers(submitted_params):
    """All parameters must be integers."""
    for key in PARAM_SPEC:
        assert isinstance(submitted_params[key], int), (
            f"{key} must be int, got {type(submitted_params[key]).__name__}"
        )


def test_params_in_range(submitted_params):
    """All parameters must be within valid ranges."""
    for key, spec in PARAM_SPEC.items():
        v = submitted_params[key]
        assert spec["min"] <= v <= spec["max"], (
            f"{key}={v} out of range [{spec['min']}, {spec['max']}]"
        )


# ========================================================================
# TESTS: Per-Matchup Balance (primary seed, tightened thresholds)
# ========================================================================

@pytest.mark.parametrize("matchup", ALL_MATCHUPS)
def test_matchup_fairness(matchup, all_matchup_results):
    """Fairness (win rate balance) must be >= 0.72 for each matchup."""
    m = all_matchup_results[matchup]
    assert m["fairness"] >= 0.72, (
        f"{matchup}: fairness {m['fairness']:.4f} < 0.72 "
        f"(win_rate={m['win_rate']:.4f})"
    )


@pytest.mark.parametrize("matchup", ALL_MATCHUPS)
def test_matchup_decisiveness(matchup, all_matchup_results):
    """Decisiveness (1 - draw_rate) must be >= 0.72 for each matchup."""
    m = all_matchup_results[matchup]
    assert m["decisiveness"] >= 0.72, (
        f"{matchup}: decisiveness {m['decisiveness']:.4f} < 0.72 "
        f"(draw_rate={m['draw_rate']:.4f})"
    )


@pytest.mark.parametrize("matchup", ALL_MATCHUPS)
def test_matchup_depth(matchup, all_matchup_results):
    """Depth (game length appropriateness) must be >= 0.58 for each matchup."""
    m = all_matchup_results[matchup]
    assert m["depth"] >= 0.58, (
        f"{matchup}: depth {m['depth']:.4f} < 0.58 "
        f"(avg_turns={m['avg_turns']:.1f}, sweet_spot=[30,70])"
    )


@pytest.mark.parametrize("matchup", ALL_MATCHUPS)
def test_matchup_variety(matchup, all_matchup_results):
    """Variety (action entropy) must be >= 0.48 for each matchup."""
    m = all_matchup_results[matchup]
    assert m["variety"] >= 0.48, (
        f"{matchup}: variety {m['variety']:.4f} < 0.48"
    )


# ========================================================================
# TESTS: Cross-Strategy Balance
# ========================================================================

def test_no_dominant_strategy(strategy_win_rates):
    """No single AI strategy may win more than 56% of its aggregate games."""
    for strat, wr in strategy_win_rates.items():
        assert wr <= 0.56, (
            f"Strategy '{strat}' dominates with {wr:.4f} aggregate win rate (> 0.56). "
            f"All rates: {json.dumps({k: round(v, 4) for k, v in strategy_win_rates.items()})}"
        )


def test_overall_composite(all_matchup_results):
    """Mean composite score across all 6 matchups must be >= 0.80."""
    composites = [m["composite"] for m in all_matchup_results.values()]
    overall = sum(composites) / len(composites)
    assert overall >= 0.80, (
        f"Overall composite {overall:.4f} < 0.80. "
        f"Per-matchup: {json.dumps({k: v['composite'] for k, v in all_matchup_results.items()}, indent=2)}"
    )


# ========================================================================
# TESTS: Robustness (secondary seed)
# ========================================================================

def test_robustness_overall_composite(robustness_results):
    """Balance must generalize: composite >= 0.70 on secondary seed."""
    composites = [m["composite"] for m in robustness_results.values()]
    overall = sum(composites) / len(composites)
    assert overall >= 0.70, (
        f"Robustness check failed: composite {overall:.4f} < 0.70 on seed={ROBUSTNESS_SEED}. "
        f"Solution may be overfit to primary seed."
    )


@pytest.mark.parametrize("matchup", ALL_MATCHUPS)
def test_robustness_per_matchup(matchup, robustness_results):
    """Each matchup composite must be >= 0.50 on secondary seed."""
    m = robustness_results[matchup]
    assert m["composite"] >= 0.50, (
        f"Robustness: {matchup} composite {m['composite']:.4f} < 0.50 on seed={ROBUSTNESS_SEED}"
    )


# ========================================================================
# TESTS: Hidden Mechanics Discovery
# ========================================================================

def test_mechanics_report_exists():
    """Mechanics report JSON must exist."""
    assert os.path.exists(MECHANICS_PATH), f"{MECHANICS_PATH} not found"


def test_mechanics_report_structure(submitted_mechanics):
    """Mechanics report must have valid structure."""
    assert "hidden_mechanics" in submitted_mechanics, (
        "Missing 'hidden_mechanics' key"
    )
    entries = submitted_mechanics["hidden_mechanics"]
    assert isinstance(entries, list), "'hidden_mechanics' must be a list"
    assert len(entries) >= 3, (
        f"Expected at least 3 hidden mechanics, found {len(entries)}"
    )
    for i, entry in enumerate(entries):
        assert "name" in entry, f"Entry {i} missing 'name' field"
        assert "description" in entry, f"Entry {i} missing 'description' field"


def test_mechanics_report_completeness(submitted_mechanics):
    """At least 4 of 5 hidden mechanics must be correctly identified."""
    entries = submitted_mechanics["hidden_mechanics"]
    identified = []
    for spec in HIDDEN_MECHANICS_SPEC:
        found = False
        for entry in entries:
            entry_text = " ".join([
                str(entry.get("name", "")),
                str(entry.get("description", "")),
                str(entry.get("impact", "")),
            ])
            if _mechanic_matches_entry(spec, entry_text):
                found = True
                break
        if found:
            identified.append(spec["id"])

    assert len(identified) >= 4, (
        f"Only {len(identified)}/5 hidden mechanics identified: {identified}. "
        f"Expected at least 4 of: "
        f"{[s['id'] for s in HIDDEN_MECHANICS_SPEC]}"
    )


# ========================================================================
# TESTS: Payoff Matrix
# ========================================================================

def test_payoff_matrix_exists():
    """Payoff matrix JSON must exist."""
    assert os.path.exists(PAYOFF_PATH), f"{PAYOFF_PATH} not found"


def test_payoff_matrix_structure(submitted_payoff_matrix):
    """Payoff matrix must have correct structure."""
    assert "matrix" in submitted_payoff_matrix, "Missing 'matrix' key"
    assert "strategies" in submitted_payoff_matrix, "Missing 'strategies' key"
    strats = submitted_payoff_matrix["strategies"]
    assert len(strats) == 3, f"Expected 3 strategies, got {len(strats)}"
    matrix = submitted_payoff_matrix["matrix"]
    assert len(matrix) == 3, f"Expected 3x3 matrix, got {len(matrix)} rows"
    for i, row in enumerate(matrix):
        assert len(row) == 3, f"Row {i} has {len(row)} columns, expected 3"


def test_payoff_matrix_accuracy(submitted_payoff_matrix, reference_payoff):
    """Payoff matrix entries must match reference simulation within tolerance.

    This verifies that the solver used the correct game engine (with all
    hidden mechanics), not the simplified reference engine.
    """
    strats = submitted_payoff_matrix["strategies"]
    matrix = submitted_payoff_matrix["matrix"]
    ref_strats = STRATEGIES

    # Build mapping from submitted strategy order to reference order
    strat_map = {}
    for i, s in enumerate(strats):
        assert s in ref_strats, f"Unknown strategy '{s}'"
        strat_map[i] = ref_strats.index(s)

    for i in range(3):
        for j in range(3):
            ri, rj = strat_map[i], strat_map[j]
            submitted_val = matrix[i][j]
            reference_val = reference_payoff[ri][rj]
            assert abs(submitted_val - reference_val) < 0.015, (
                f"Payoff [{strats[i]}][{strats[j]}]={submitted_val:.4f} "
                f"differs from reference {reference_val:.4f} by "
                f"{abs(submitted_val - reference_val):.4f} (tolerance=0.015). "
                f"Check that the correct game engine was used."
            )


# ========================================================================
# TESTS: Nash Equilibrium
# ========================================================================

def test_nash_equilibrium_exists():
    """Nash equilibrium JSON must exist."""
    assert os.path.exists(NASH_PATH), f"{NASH_PATH} not found"


def test_nash_equilibrium_structure(submitted_nash_eq):
    """Nash equilibrium must have correct structure."""
    assert "probabilities" in submitted_nash_eq, "Missing 'probabilities' key"
    assert "expected_value" in submitted_nash_eq, "Missing 'expected_value' key"
    probs = submitted_nash_eq["probabilities"]
    for s in STRATEGIES:
        assert s in probs, f"Missing strategy '{s}' in probabilities"
        assert isinstance(probs[s], (int, float)), (
            f"Probability for '{s}' must be numeric"
        )


def test_nash_equilibrium_valid_distribution(submitted_nash_eq):
    """Nash equilibrium probabilities must form a valid distribution."""
    probs = submitted_nash_eq["probabilities"]
    values = [probs[s] for s in STRATEGIES]
    total = sum(values)
    assert abs(total - 1.0) < 0.015, (
        f"Probabilities sum to {total:.6f}, expected ~1.0"
    )
    for s in STRATEGIES:
        assert probs[s] >= -0.01, (
            f"Probability for '{s}' is negative: {probs[s]:.6f}"
        )


def test_nash_equilibrium_best_response(submitted_payoff_matrix, submitted_nash_eq):
    """Nash equilibrium must satisfy the best-response property.

    For strategies with positive probability, expected payoffs must be
    approximately equal. No inactive strategy may have a strictly higher
    expected payoff.
    """
    strats = submitted_payoff_matrix["strategies"]
    M = submitted_payoff_matrix["matrix"]
    probs_dict = submitted_nash_eq["probabilities"]
    probs = [max(0.0, probs_dict.get(s, 0.0)) for s in strats]

    # Compute expected payoff for each pure strategy against the mix
    expected = []
    for i in range(3):
        ep = sum(probs[j] * M[i][j] for j in range(3))
        expected.append(ep)

    # Identify active strategies (positive probability)
    active_indices = [i for i in range(3) if probs[i] > 0.01]
    assert len(active_indices) >= 1, "At least one strategy must be active"

    # Active strategies must have approximately equal expected payoffs
    if len(active_indices) > 1:
        active_payoffs = [expected[i] for i in active_indices]
        max_diff = max(active_payoffs) - min(active_payoffs)
        assert max_diff < 0.045, (
            f"Active strategies have unequal expected payoffs (gap={max_diff:.4f}): "
            + ", ".join(
                f"{strats[i]}={expected[i]:.4f}" for i in active_indices
            )
        )

    # Inactive strategies must not yield higher expected payoff
    if active_indices:
        active_value = sum(expected[i] for i in active_indices) / len(active_indices)
        for i in range(3):
            if probs[i] <= 0.01:
                assert expected[i] <= active_value + 0.045, (
                    f"Inactive strategy '{strats[i]}' has expected payoff "
                    f"{expected[i]:.4f} > active value {active_value:.4f}"
                )


# ========================================================================
# TESTS: Output Artifacts
# ========================================================================

def test_tournament_db_exists():
    """Tournament SQLite database must exist."""
    assert os.path.exists(DB_PATH), f"{DB_PATH} not found"


def test_tournament_db_schema():
    """Tournament database must have required tables."""
    conn = sqlite3.connect(DB_PATH)
    tables = {
        r[0] for r in
        conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()
    assert "game_results" in tables, "Missing table: game_results"
    assert "matchup_summary" in tables, "Missing table: matchup_summary"


def test_tournament_db_data():
    """Tournament database must have at least 100 game records per matchup."""
    conn = sqlite3.connect(DB_PATH)
    for mu in ALL_MATCHUPS:
        count = conn.execute(
            "SELECT COUNT(*) FROM game_results WHERE matchup=?", (mu,)
        ).fetchone()[0]
        assert count >= 100, (
            f"matchup '{mu}': only {count} game records in DB, need >= 100"
        )
    conn.close()


def test_balance_report_exists():
    """Balance report JSON must exist."""
    assert os.path.exists(REPORT_PATH), f"{REPORT_PATH} not found"


def test_balance_report_structure():
    """Balance report must have all required fields."""
    with open(REPORT_PATH) as f:
        report = json.load(f)
    assert "matchups" in report, "Missing 'matchups' key in balance report"
    assert "strategy_win_rates" in report, "Missing 'strategy_win_rates' key"
    assert "overall_composite" in report, "Missing 'overall_composite' key"
    for mu in ALL_MATCHUPS:
        assert mu in report["matchups"], f"Missing matchup '{mu}' in report"
        m = report["matchups"][mu]
        for key in ["fairness", "decisiveness", "depth", "variety", "composite"]:
            assert key in m, f"Missing '{key}' in matchup {mu}"
    for strat in STRATEGIES:
        assert strat in report["strategy_win_rates"], (
            f"Missing strategy '{strat}' in strategy_win_rates"
        )
