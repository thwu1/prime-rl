
import json
import os
import math
import pytest
import numpy as np
import game_pb2


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def moveset():
    with open("/app/data/character_zen.bin", "rb") as f:
        ms = game_pb2.CharacterMoveSet()
        ms.ParseFromString(f.read())
    return ms


@pytest.fixture
def frame_advantage():
    path = "/app/output/frame_advantage.json"
    assert os.path.isfile(path), f"Missing {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def optimal_combos():
    path = "/app/output/optimal_combos.json"
    assert os.path.isfile(path), f"Missing {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def punish_table():
    path = "/app/output/punish_table.json"
    assert os.path.isfile(path), f"Missing {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def payoff_matrix():
    path = "/app/output/payoff_matrix.json"
    assert os.path.isfile(path), f"Missing {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def dominance_analysis():
    path = "/app/output/dominance_analysis.json"
    assert os.path.isfile(path), f"Missing {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def nash_equilibrium():
    path = "/app/output/nash_equilibrium.json"
    assert os.path.isfile(path), f"Missing {path}"
    with open(path) as f:
        return json.load(f)


# ── Protobuf deserialization ───────────────────────────────────────


def test_moveset_character_name(moveset):
    assert moveset.character_name == "ZEN"


def test_moveset_move_count(moveset):
    assert len(moveset.moves) == 20


def test_moveset_max_hp(moveset):
    assert moveset.max_hp == 400


def test_moveset_max_energy(moveset):
    assert moveset.max_energy == 100


# ── Frame advantage ───────────────────────────────────────────────

EXPECTED_FA_HIT = {
    "STAND_A": 4, "STAND_B": 5, "CROUCH_A": 3, "CROUCH_B": 4,
    "STAND_FA": 7, "STAND_FB": 8, "CROUCH_FA": 6, "CROUCH_FB": 7,
    "AIR_A": 4, "AIR_B": 5, "AIR_FA": 6, "AIR_FB": 7,
    "STAND_D_DF_FA": 8, "STAND_D_DF_FB": 10,
    "STAND_F_D_DFA": 10, "STAND_F_D_DFB": 12,
    "STAND_D_DB_BA": 7, "STAND_D_DB_BB": 9,
    "THROW_A": -22, "THROW_B": -24,
}

EXPECTED_FA_BLOCK = {
    "STAND_A": -3, "STAND_B": -4, "CROUCH_A": -4, "CROUCH_B": -5,
    "STAND_FA": -6, "STAND_FB": -7, "CROUCH_FA": -5, "CROUCH_FB": -6,
    "AIR_A": -3, "AIR_B": -4, "AIR_FA": -5, "AIR_FB": -6,
    "STAND_D_DF_FA": -7, "STAND_D_DF_FB": -8,
    "STAND_F_D_DFA": -8, "STAND_F_D_DFB": -10,
    "STAND_D_DB_BA": -6, "STAND_D_DB_BB": -8,
    "THROW_A": -22, "THROW_B": -24,
}


def test_frame_advantage_all_moves_present(frame_advantage):
    for name in EXPECTED_FA_HIT:
        assert name in frame_advantage, f"Missing move: {name}"


@pytest.mark.parametrize("move", list(EXPECTED_FA_HIT.keys()))
def test_frame_advantage_on_hit(frame_advantage, move):
    assert frame_advantage[move]["on_hit"] == EXPECTED_FA_HIT[move]


@pytest.mark.parametrize("move", list(EXPECTED_FA_BLOCK.keys()))
def test_frame_advantage_on_block(frame_advantage, move):
    assert frame_advantage[move]["on_block"] == EXPECTED_FA_BLOCK[move]


# ── Optimal combo damage (E=0) ────────────────────────────────────

EXPECTED_COMBO_DMG_E0 = {
    "STAND_A": 200, "CROUCH_A": 196, "STAND_B": 196, "CROUCH_B": 178,
    "STAND_FA": 142, "STAND_FB": 154, "CROUCH_FA": 118, "CROUCH_FB": 148,
    "AIR_A": 125, "AIR_B": 109, "AIR_FA": 56, "AIR_FB": 70,
    "STAND_D_DF_FA": 0, "STAND_D_DF_FB": 0,
    "STAND_F_D_DFA": 0, "STAND_F_D_DFB": 0,
    "STAND_D_DB_BA": 0, "STAND_D_DB_BB": 0,
    "THROW_A": 78, "THROW_B": 0,
}


@pytest.mark.parametrize("move", list(EXPECTED_COMBO_DMG_E0.keys()))
def test_optimal_combo_damage_e0(optimal_combos, move):
    result = optimal_combos[move]["0"]
    assert result["total_damage"] == EXPECTED_COMBO_DMG_E0[move], \
        f"{move} at E=0: expected {EXPECTED_COMBO_DMG_E0[move]}, got {result['total_damage']}"


# ── Optimal combo damage (E=50) ───────────────────────────────────

EXPECTED_COMBO_DMG_E50 = {
    "STAND_A": 200, "CROUCH_A": 196, "STAND_B": 196, "CROUCH_B": 192,
    "STAND_FA": 164, "STAND_FB": 176, "CROUCH_FA": 156, "CROUCH_FB": 170,
    "AIR_A": 125, "AIR_B": 109, "AIR_FA": 56, "AIR_FB": 70,
    "STAND_D_DF_FA": 82, "STAND_D_DF_FB": 104,
    "STAND_F_D_DFA": 92, "STAND_F_D_DFB": 116,
    "STAND_D_DB_BA": 74, "STAND_D_DB_BB": 98,
    "THROW_A": 78, "THROW_B": 100,
}


@pytest.mark.parametrize("move", list(EXPECTED_COMBO_DMG_E50.keys()))
def test_optimal_combo_damage_e50(optimal_combos, move):
    result = optimal_combos[move]["50"]
    assert result["total_damage"] == EXPECTED_COMBO_DMG_E50[move], \
        f"{move} at E=50: expected {EXPECTED_COMBO_DMG_E50[move]}, got {result['total_damage']}"


# ── Combo structure checks ────────────────────────────────────────


def test_stand_a_best_combo_is_4_hits(optimal_combos):
    assert optimal_combos["STAND_A"]["0"]["hit_count"] == 4


def test_throw_a_is_single_hit(optimal_combos):
    result = optimal_combos["THROW_A"]["0"]
    assert result["hit_count"] == 1
    assert result["combo"] == ["THROW_A"]


def test_specials_unavailable_at_e0(optimal_combos):
    for move in ["STAND_D_DF_FA", "STAND_F_D_DFA", "STAND_D_DB_BA",
                  "STAND_D_DB_BB", "STAND_D_DF_FB", "STAND_F_D_DFB"]:
        assert optimal_combos[move]["0"]["total_damage"] == 0


def test_combo_starts_with_correct_move(optimal_combos):
    for move_name in EXPECTED_COMBO_DMG_E0:
        result = optimal_combos[move_name]["0"]
        if result["total_damage"] > 0:
            assert result["combo"][0] == move_name


# ── Punish table ──────────────────────────────────────────────────

EXPECTED_PUNISH_DAMAGE = {
    "STAND_A": 0, "AIR_A": 0,
    "STAND_B": 196, "CROUCH_A": 196, "AIR_B": 196,
    "CROUCH_B": 200, "STAND_FA": 200, "STAND_FB": 200,
    "CROUCH_FA": 200, "CROUCH_FB": 200,
    "AIR_FA": 200, "AIR_FB": 200,
    "STAND_D_DF_FA": 200, "STAND_D_DF_FB": 200,
    "STAND_F_D_DFA": 200, "STAND_F_D_DFB": 200,
    "STAND_D_DB_BA": 200, "STAND_D_DB_BB": 200,
    "THROW_A": 200, "THROW_B": 200,
}


@pytest.mark.parametrize("move", list(EXPECTED_PUNISH_DAMAGE.keys()))
def test_punish_damage(punish_table, move):
    assert punish_table[move]["punish_damage"] == EXPECTED_PUNISH_DAMAGE[move], \
        f"{move}: expected punish {EXPECTED_PUNISH_DAMAGE[move]}, got {punish_table[move]['punish_damage']}"


def test_unpunishable_moves_have_null_starter(punish_table):
    for move in ["STAND_A", "AIR_A"]:
        assert punish_table[move]["punish_starter"] is None
        assert punish_table[move]["punish_combo"] == []


def test_punish_starters_for_4frame_window(punish_table):
    for move in ["STAND_B", "CROUCH_A", "AIR_B"]:
        assert punish_table[move]["punish_starter"] == "CROUCH_A", \
            f"{move}: expected CROUCH_A punish starter, got {punish_table[move]['punish_starter']}"


def test_punish_starters_for_5plus_frame_window(punish_table):
    moves_with_stand_a_punish = [
        "CROUCH_B", "STAND_FA", "STAND_FB", "CROUCH_FA", "CROUCH_FB",
        "AIR_FA", "AIR_FB", "STAND_D_DF_FA", "STAND_D_DF_FB",
        "STAND_F_D_DFA", "STAND_F_D_DFB", "STAND_D_DB_BA", "STAND_D_DB_BB",
        "THROW_A", "THROW_B",
    ]
    for move in moves_with_stand_a_punish:
        assert punish_table[move]["punish_starter"] == "STAND_A", \
            f"{move}: expected STAND_A punish starter, got {punish_table[move]['punish_starter']}"


def test_punish_frames_available(punish_table):
    for move, expected_block in EXPECTED_FA_BLOCK.items():
        assert punish_table[move]["frames_available"] == abs(expected_block)


def test_punish_no_throw_starters(punish_table):
    for move_name, data in punish_table.items():
        if data["punish_starter"] is not None:
            assert "THROW" not in data["punish_starter"], \
                f"{move_name}: throw used as punish starter"


# ── Payoff matrix structure ───────────────────────────────────────


def test_payoff_matrix_dimensions(payoff_matrix):
    opts = payoff_matrix["options"]
    mat = payoff_matrix["matrix"]
    assert len(opts) == 21
    assert len(mat) == 21
    for row in mat:
        assert len(row) == 21


def test_payoff_matrix_block_is_last(payoff_matrix):
    assert payoff_matrix["options"][-1] == "BLOCK"


def test_payoff_matrix_diagonal_zero(payoff_matrix):
    mat = payoff_matrix["matrix"]
    for i in range(len(mat)):
        assert mat[i][i] == 0


def test_payoff_matrix_antisymmetric(payoff_matrix):
    opts = payoff_matrix["options"]
    mat = payoff_matrix["matrix"]
    n = len(opts)
    for i in range(n):
        for j in range(i + 1, n):
            assert mat[i][j] == -mat[j][i], \
                f"Not antisymmetric: M[{opts[i]}][{opts[j]}]={mat[i][j]}, M[{opts[j]}][{opts[i]}]={mat[j][i]}"


def test_payoff_matrix_attack_vs_attack(payoff_matrix):
    idx = {name: i for i, name in enumerate(payoff_matrix["options"])}
    mat = payoff_matrix["matrix"]
    # STAND_A (startup 5) beats STAND_B (startup 8) → STAND_A combo 200
    assert mat[idx["STAND_A"]][idx["STAND_B"]] == 200
    # CROUCH_A (startup 4) beats STAND_A (startup 5) → CROUCH_A combo 196
    assert mat[idx["CROUCH_A"]][idx["STAND_A"]] == 196


def test_payoff_matrix_attack_vs_block(payoff_matrix):
    idx = {name: i for i, name in enumerate(payoff_matrix["options"])}
    mat = payoff_matrix["matrix"]
    # STAND_A vs BLOCK: unpunishable → 0
    assert mat[idx["STAND_A"]][idx["BLOCK"]] == 0
    # STAND_FA vs BLOCK: punished for 200
    assert mat[idx["STAND_FA"]][idx["BLOCK"]] == -200
    # STAND_B vs BLOCK: punished for 196
    assert mat[idx["STAND_B"]][idx["BLOCK"]] == -196


def test_payoff_matrix_throw_vs_block(payoff_matrix):
    idx = {name: i for i, name in enumerate(payoff_matrix["options"])}
    mat = payoff_matrix["matrix"]
    # THROW_A vs BLOCK: throw lands, combo 78
    assert mat[idx["THROW_A"]][idx["BLOCK"]] == 78
    # THROW_B vs BLOCK: throw lands, combo 100
    assert mat[idx["THROW_B"]][idx["BLOCK"]] == 100


def test_payoff_matrix_attack_vs_throw(payoff_matrix):
    idx = {name: i for i, name in enumerate(payoff_matrix["options"])}
    mat = payoff_matrix["matrix"]
    # STAND_A vs THROW_A: counter-hit, combo 200
    assert mat[idx["STAND_A"]][idx["THROW_A"]] == 200
    # THROW_A vs STAND_A: gets counter-hit, -200
    assert mat[idx["THROW_A"]][idx["STAND_A"]] == -200


def test_payoff_matrix_throw_vs_throw(payoff_matrix):
    idx = {name: i for i, name in enumerate(payoff_matrix["options"])}
    mat = payoff_matrix["matrix"]
    assert mat[idx["THROW_A"]][idx["THROW_B"]] == 0


def test_payoff_matrix_block_vs_attack(payoff_matrix):
    idx = {name: i for i, name in enumerate(payoff_matrix["options"])}
    mat = payoff_matrix["matrix"]
    # BLOCK vs STAND_FA: block and punish for 200
    assert mat[idx["BLOCK"]][idx["STAND_FA"]] == 200
    # BLOCK vs STAND_A: block but unpunishable
    assert mat[idx["BLOCK"]][idx["STAND_A"]] == 0


# ── Dominance analysis (IESDS) ───────────────────────────────────


def test_dominance_output_exists(dominance_analysis):
    assert "elimination_rounds" in dominance_analysis
    assert "survivors" in dominance_analysis


def test_dominance_has_eliminations(dominance_analysis):
    """With 21 options and Nash support of ~2, many strategies must be eliminated."""
    rounds = dominance_analysis["elimination_rounds"]
    assert len(rounds) >= 1, "IESDS should eliminate at least one round of strategies"
    total_eliminated = sum(len(r["eliminated"]) for r in rounds)
    assert total_eliminated >= 15, \
        f"Expected at least 15 eliminations but got {total_eliminated}"


def test_dominance_survivors_include_nash_support(dominance_analysis, nash_equilibrium):
    """Nash support must survive IESDS — dominated strategies can't be in equilibrium."""
    survivors = set(dominance_analysis["survivors"])
    for opt, prob in nash_equilibrium["strategy"].items():
        if prob > 1e-6:
            assert opt in survivors, \
                f"Nash support strategy {opt} (p={prob}) was eliminated by IESDS"


def test_dominance_survivors_contain_stand_a(dominance_analysis):
    assert "STAND_A" in dominance_analysis["survivors"]


def test_dominance_survivors_contain_block(dominance_analysis):
    assert "BLOCK" in dominance_analysis["survivors"]


def test_dominance_specials_eliminated(dominance_analysis):
    """Specials (slow, punishable, energy-costly) should be strictly dominated."""
    survivors = set(dominance_analysis["survivors"])
    specials = [
        "STAND_D_DF_FA", "STAND_D_DF_FB", "STAND_F_D_DFA",
        "STAND_F_D_DFB", "STAND_D_DB_BA", "STAND_D_DB_BB",
    ]
    for s in specials:
        assert s not in survivors, f"Special {s} should have been eliminated"


def test_dominance_heavy_normals_eliminated(dominance_analysis):
    """Slow heavy normals dominated by faster options + BLOCK mix."""
    survivors = set(dominance_analysis["survivors"])
    heavies = ["STAND_FA", "STAND_FB", "CROUCH_FA", "CROUCH_FB"]
    for h in heavies:
        assert h not in survivors, f"Heavy normal {h} should have been eliminated"


def test_dominance_air_moves_eliminated(dominance_analysis):
    """Air normals offer worse risk/reward than grounded options."""
    survivors = set(dominance_analysis["survivors"])
    air_moves = ["AIR_A", "AIR_B", "AIR_FA", "AIR_FB"]
    for a in air_moves:
        assert a not in survivors, f"Air move {a} should have been eliminated"


def test_dominance_round_structure(dominance_analysis):
    """Each round must have sequential numbering and non-empty eliminations."""
    rounds = dominance_analysis["elimination_rounds"]
    for i, r in enumerate(rounds):
        assert r["round"] == i + 1, f"Round numbering incorrect at index {i}"
        assert len(r["eliminated"]) > 0, f"Round {r['round']} has no eliminations"
        # Each elimination list should be sorted alphabetically
        assert r["eliminated"] == sorted(r["eliminated"]), \
            f"Round {r['round']} eliminations not sorted"


def test_dominance_no_duplicate_eliminations(dominance_analysis):
    """A strategy can only be eliminated once across all rounds."""
    all_eliminated = []
    for r in dominance_analysis["elimination_rounds"]:
        all_eliminated.extend(r["eliminated"])
    assert len(all_eliminated) == len(set(all_eliminated)), \
        "Duplicate elimination detected"


def test_dominance_survivors_plus_eliminated_equals_all(dominance_analysis, payoff_matrix):
    """Survivors + all eliminated must equal the full option set."""
    all_options = set(payoff_matrix["options"])
    survivors = set(dominance_analysis["survivors"])
    eliminated = set()
    for r in dominance_analysis["elimination_rounds"]:
        eliminated.update(r["eliminated"])
    assert survivors | eliminated == all_options
    assert survivors & eliminated == set()


def test_dominance_throw_a_eliminated(dominance_analysis):
    """THROW_A is strictly dominated: THROW_B has better payoff vs BLOCK,
    and a mixture with BLOCK/other strategies strictly dominates THROW_A
    across all opponent columns."""
    survivors = set(dominance_analysis["survivors"])
    assert "THROW_A" not in survivors, \
        "THROW_A should be eliminated — dominated by mix involving THROW_B"


def test_dominance_survivors_sorted(dominance_analysis):
    assert dominance_analysis["survivors"] == sorted(dominance_analysis["survivors"])


# ── Nash equilibrium ──────────────────────────────────────────────


def test_nash_game_value_zero(nash_equilibrium):
    assert nash_equilibrium["game_value"] == 0.0, \
        f"Antisymmetric game must have value 0, got {nash_equilibrium['game_value']}"


def test_nash_valid_distribution(nash_equilibrium):
    strategy = nash_equilibrium["strategy"]
    total = sum(strategy.values())
    assert abs(total - 1.0) < 0.01, f"Probabilities sum to {total}"
    for k, v in strategy.items():
        assert v >= -0.001, f"{k} has negative probability {v}"


def test_nash_stand_a_positive(nash_equilibrium):
    p = nash_equilibrium["strategy"].get("STAND_A", 0)
    assert p >= 0.3, f"STAND_A should have significant probability, got {p}"


def test_nash_block_positive(nash_equilibrium):
    p = nash_equilibrium["strategy"].get("BLOCK", 0)
    assert p >= 0.45, f"BLOCK should have significant probability, got {p}"


def test_nash_stand_a_plus_block_dominant(nash_equilibrium):
    pa = nash_equilibrium["strategy"].get("STAND_A", 0)
    pb = nash_equilibrium["strategy"].get("BLOCK", 0)
    assert pa + pb >= 0.95, \
        f"STAND_A + BLOCK should account for nearly all weight, got {pa + pb}"


def test_nash_dominated_moves_zero(nash_equilibrium):
    dominated = [
        "STAND_F_D_DFA", "STAND_D_DB_BA", "AIR_FB",
        "STAND_D_DB_BB", "STAND_F_D_DFB", "STAND_D_DF_FA",
        "STAND_D_DF_FB", "AIR_FA", "AIR_B",
        "STAND_B", "STAND_FA", "STAND_FB",
        "CROUCH_FA", "CROUCH_FB", "CROUCH_B",
        "AIR_A",
    ]
    for move in dominated:
        p = nash_equilibrium["strategy"].get(move, 0)
        assert p < 0.01, f"Dominated move {move} should have ~0 probability, got {p}"


def test_nash_optimality_condition(nash_equilibrium, payoff_matrix):
    """No pure opponent strategy should beat the Nash mix."""
    options = payoff_matrix["options"]
    M = np.array(payoff_matrix["matrix"], dtype=float)
    p = np.array([nash_equilibrium["strategy"].get(opt, 0) for opt in options])

    # Expected payoff for P1 against each pure P2 strategy
    expected = p @ M

    for j, val in enumerate(expected):
        assert val >= -2.0, \
            f"Nash mix loses to pure {options[j]}: expected payoff {val:.2f}"


def test_nash_support_consistency(nash_equilibrium):
    support = nash_equilibrium["support"]
    strategy = nash_equilibrium["strategy"]
    for opt in support:
        assert strategy[opt] > 1e-6, f"{opt} in support but has zero probability"
    for opt, prob in strategy.items():
        if prob > 1e-6:
            assert opt in support, f"{opt} has probability {prob} but not in support"
