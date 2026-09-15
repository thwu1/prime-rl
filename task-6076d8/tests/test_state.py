"""
Tests for FIDE Dutch Swiss System Round 5 pairing.

Verifies the output at /app/round5_pairing.json against the reference pairing
computed according to FIDE C.04.3 (effective 2026-02-01).

The tournament state is hard-coded here to avoid external dependencies.

"""

import json
import os
import pytest


PAIRING_PATH = "/app/round5_pairing.json"

# Hard-coded tournament state (same data as /app/tournament.trf)
PLAYER_DATA = {
    1:  {"colours": ["W", "B", "W", "B"], "opponents": [9, 5, 3, 2], "score": 3.5},
    2:  {"colours": ["B", "W", "B", "W"], "opponents": [10, 6, 4, 1], "score": 1.5},
    3:  {"colours": ["W", "B", "B", "W"], "opponents": [11, 7, 1, 5], "score": 2.0},
    4:  {"colours": ["B", "W", "W", "B"], "opponents": [12, 8, 2, 6], "score": 2.5},
    5:  {"colours": ["W", "W", "B", "B"], "opponents": [13, 1, 8, 3], "score": 2.0},
    6:  {"colours": ["B", "B", "W", "W"], "opponents": [14, 2, 7, 4], "score": 1.0},
    7:  {"colours": ["W", "W", "B", "W"], "opponents": [15, 3, 6, 8], "score": 3.0},
    8:  {"colours": ["B", "B", "W", "B"], "opponents": [16, 4, 5, 7], "score": 1.5},
    9:  {"colours": ["B", "W", "B", "W"], "opponents": [1, 13, 12, 10], "score": 2.5},
    10: {"colours": ["W", "B", "W", "B"], "opponents": [2, 14, 11, 9], "score": 2.0},
    11: {"colours": ["B", "W", "B", "W"], "opponents": [3, 15, 10, 13], "score": 1.0},
    12: {"colours": ["W", "B", "W", "B"], "opponents": [4, 16, 9, 14], "score": 1.5},
    13: {"colours": ["B", "B", "W", "B"], "opponents": [5, 9, 16, 11], "score": 1.0},
    14: {"colours": ["W", "W", "B", "W"], "opponents": [6, 10, 15, 12], "score": 4.0},
    15: {"colours": ["B", "B", "W", "B"], "opponents": [7, 11, 14, 16], "score": 2.0},
    16: {"colours": ["W", "W", "B", "W"], "opponents": [8, 12, 13, 15], "score": 1.0},
}

# Reference pairing derived from manual application of FIDE Dutch System C.04.3
# to the tournament state (16 players, after 4 rounds, Round 5).
#
# Bracket trace:
#   4.0{14} -> 14 downfloats
#   3.5{1}+MDP{14} -> pair 1(W)v14(B), colour Art 5.2.1
#   3.0{7} -> 7 downfloats
#   2.5{4,9}+MDP{7} -> pair 4(W)v7(B) [C12=0, C14=0], 9 downfloats
#   2.0{3,5,10,15}+MDP{9} -> MDP pair 5(W)v9(B) [Art 4.2 trans 3],
#       remainder 10(W)v3(B), 15 downfloats
#   1.5{2,8,12}+MDP{15} -> MDP pair 15(W)v2(B), remainder 8(W)v12(B)
#   1.0{6,11,13,16} -> 13(W)v6(B), 11(W)v16(B) [Art 4.2 trans 2, C3 avoidance]

REFERENCE_PAIRINGS = [
    {"white": 1, "black": 14},
    {"white": 4, "black": 7},
    {"white": 5, "black": 9},
    {"white": 10, "black": 3},
    {"white": 15, "black": 2},
    {"white": 8, "black": 12},
    {"white": 13, "black": 6},
    {"white": 11, "black": 16},
]
REFERENCE_BYE = None


@pytest.fixture
def pairing():
    """Load the agent's pairing output."""
    assert os.path.exists(PAIRING_PATH), (
        f"Pairing output not found at {PAIRING_PATH}. "
        "The agent must write a JSON file with 'pairings' and 'bye' keys."
    )
    with open(PAIRING_PATH) as f:
        data = json.load(f)
    return data


class TestStructure:
    """Verify the output has correct JSON structure."""

    def test_has_pairings_key(self, pairing):
        assert "pairings" in pairing, "Output must have 'pairings' key"

    def test_has_bye_key(self, pairing):
        assert "bye" in pairing, "Output must have 'bye' key"

    def test_pairings_is_list(self, pairing):
        assert isinstance(pairing["pairings"], list), "'pairings' must be a list"

    def test_correct_number_of_pairs(self, pairing):
        assert len(pairing["pairings"]) == 8, (
            f"Expected 8 pairs for 16 players, got {len(pairing['pairings'])}"
        )

    def test_bye_is_null(self, pairing):
        assert pairing["bye"] is None, (
            f"Expected bye=null for 16 players (even), got {pairing['bye']}"
        )

    def test_each_pair_has_white_black(self, pairing):
        for i, pair in enumerate(pairing["pairings"]):
            assert "white" in pair, f"Pair {i} missing 'white' key"
            assert "black" in pair, f"Pair {i} missing 'black' key"
            assert isinstance(pair["white"], int), f"Pair {i} 'white' must be int"
            assert isinstance(pair["black"], int), f"Pair {i} 'black' must be int"

    def test_all_tpns_covered(self, pairing):
        tpns = set()
        for pair in pairing["pairings"]:
            tpns.add(pair["white"])
            tpns.add(pair["black"])
        expected = set(range(1, 17))
        assert tpns == expected, f"TPNs mismatch: got {sorted(tpns)}, expected 1-16"

    def test_no_self_pairing(self, pairing):
        for pair in pairing["pairings"]:
            assert pair["white"] != pair["black"], (
                f"Self-pairing detected: TPN {pair['white']}"
            )


class TestAbsoluteCriteria:
    """Verify absolute criteria C1-C3."""

    def test_no_rematches_c1(self, pairing):
        """C1: No two players shall play each other more than once."""
        for pair in pairing["pairings"]:
            w, b = pair["white"], pair["black"]
            pw, pb = PLAYER_DATA[w], PLAYER_DATA[b]
            assert b not in pw["opponents"], (
                f"C1 violation: {w} and {b} already played "
                f"(opponents of {w}: {pw['opponents']})"
            )
            assert w not in pb["opponents"], (
                f"C1 violation: {w} and {b} already played "
                f"(opponents of {b}: {pb['opponents']})"
            )

    def test_colour_constraint_c3(self, pairing):
        """C3: Non-topscorers with same absolute colour preference shall not meet.
        Round 5 of 7 is not final round, so all are non-topscorers."""

        def get_pref(p):
            played = [c for c in p["colours"] if c is not None]
            if not played:
                return ("none", None)
            cd = sum(1 for c in played if c == "W") - \
                 sum(1 for c in played if c == "B")
            if cd > 1:
                return ("absolute", "B")
            if cd < -1:
                return ("absolute", "W")
            if len(played) >= 2 and played[-1] == played[-2]:
                return ("absolute", "W" if played[-1] == "B" else "B")
            if cd == 1:
                return ("strong", "B")
            if cd == -1:
                return ("strong", "W")
            return ("mild", "B" if played[-1] == "W" else "W")

        for pair in pairing["pairings"]:
            w, b = pair["white"], pair["black"]
            pw, pb = PLAYER_DATA[w], PLAYER_DATA[b]
            pr_w = get_pref(pw)
            pr_b = get_pref(pb)
            if pr_w[0] == "absolute" and pr_b[0] == "absolute":
                assert pr_w[1] != pr_b[1], (
                    f"C3 violation: TPNs {w} (pref {pr_w}) and {b} (pref {pr_b}) "
                    f"both have same absolute colour preference"
                )


class TestExactPairing:
    """Verify the pairing exactly matches the reference."""

    def test_exact_pairs(self, pairing):
        """The set of (white, black) pairs must exactly match the reference."""
        actual = set()
        for p in pairing["pairings"]:
            actual.add((p["white"], p["black"]))

        expected = set()
        for p in REFERENCE_PAIRINGS:
            expected.add((p["white"], p["black"]))

        assert actual == expected, (
            f"Pairing mismatch.\n"
            f"Expected pairs: {sorted(expected)}\n"
            f"Got pairs:      {sorted(actual)}\n"
            f"Missing: {sorted(expected - actual)}\n"
            f"Extra:   {sorted(actual - expected)}"
        )

    def test_exact_bye(self, pairing):
        assert pairing["bye"] == REFERENCE_BYE, (
            f"Bye mismatch: expected {REFERENCE_BYE}, got {pairing['bye']}"
        )


class TestColourAllocation:
    """Verify colour allocation follows Article 5 rules."""

    def test_colour_correctness(self, pairing):
        """Each pair's colour assignment must follow Art. 5 priority rules."""
        for ref_pair in REFERENCE_PAIRINGS:
            w, b = ref_pair["white"], ref_pair["black"]
            found = False
            for p in pairing["pairings"]:
                pair_set = {p["white"], p["black"]}
                if pair_set == {w, b}:
                    assert p["white"] == w, (
                        f"Colour allocation error for pair ({w},{b}): "
                        f"expected white={w}, got white={p['white']}. "
                        f"Art. 5 colour rules not followed."
                    )
                    assert p["black"] == b, (
                        f"Colour allocation error for pair ({w},{b}): "
                        f"expected black={b}, got black={p['black']}. "
                        f"Art. 5 colour rules not followed."
                    )
                    found = True
                    break
            assert found, f"Pair ({w},{b}) not found in output"


class TestQualityCriteria:
    """Verify key quality criteria are satisfied."""

    def test_no_downfloaters_escaped(self, pairing):
        """All 16 players must be paired (C6: maximize pairs)."""
        tpns = set()
        for p in pairing["pairings"]:
            tpns.add(p["white"])
            tpns.add(p["black"])
        assert len(tpns) == 16, f"Only {len(tpns)} players paired, expected 16"

    def test_c12_colour_preferences(self, pairing):
        """Count how many players don't get their colour preference.
        The reference pairing achieves minimum C12 violations."""

        def get_pref(p):
            played = [c for c in p["colours"] if c is not None]
            if not played:
                return None
            cd = sum(1 for c in played if c == "W") - \
                 sum(1 for c in played if c == "B")
            if cd > 1:
                return "B"
            if cd < -1:
                return "W"
            if len(played) >= 2 and played[-1] == played[-2]:
                return "W" if played[-1] == "B" else "B"
            if cd == 1:
                return "B"
            if cd == -1:
                return "W"
            return "B" if played[-1] == "W" else "W"

        c12 = 0
        for pair in pairing["pairings"]:
            w_tpn, b_tpn = pair["white"], pair["black"]
            pw, pb = PLAYER_DATA[w_tpn], PLAYER_DATA[b_tpn]
            pref_w = get_pref(pw)
            pref_b = get_pref(pb)
            if pref_w and pref_w != "W":
                c12 += 1
            if pref_b and pref_b != "B":
                c12 += 1

        assert c12 <= 3, (
            f"C12 too high: {c12} players didn't get colour preference. "
            f"Reference achieves C12=2."
        )
