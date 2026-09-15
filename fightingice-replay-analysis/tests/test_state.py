
import json
import os
import pytest

RESULTS_PATH = "/app/output/results.json"


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), \
        f"Output file {RESULTS_PATH} does not exist"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestOutputStructure:
    def test_output_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_top_level_keys(self, results):
        required = {"matches", "standard_league", "speedrunning_league",
                     "final_rankings", "elo_ratings"}
        assert required.issubset(set(results.keys())), \
            f"Missing keys: {required - set(results.keys())}"

    def test_match_count(self, results):
        assert len(results["matches"]) == 20, \
            f"Expected 20 matches, got {len(results['matches'])}"


class TestRoundResults:
    """Verify round-level parsing for specific matches.
    These tests implicitly verify the proto schema was correctly fixed,
    since wrong field mappings produce incorrect damage/combo values."""

    def _find_match(self, results, match_id):
        for m in results["matches"]:
            if m["match_id"] == match_id:
                return m
        pytest.fail(f"Match {match_id} not found in output")

    def test_std01_rounds(self, results):
        m = self._find_match(results, "STD_01")
        assert m["p1_name"] == "AlphaStrike"
        assert m["p2_name"] == "GuardBot"
        rounds = m["rounds"]
        assert len(rounds) == 3

        r1 = rounds[0]
        assert r1["p1_hp"] == 280
        assert r1["p2_hp"] == 0
        assert r1["frames"] == 2400
        assert r1["winner"] == "AlphaStrike"

        r2 = rounds[1]
        assert r2["p1_hp"] == 0
        assert r2["p2_hp"] == 120
        assert r2["winner"] == "GuardBot"

        r3 = rounds[2]
        assert r3["p1_hp"] == 150
        assert r3["p2_hp"] == 0
        assert r3["winner"] == "AlphaStrike"

    def test_std04_rounds(self, results):
        m = self._find_match(results, "STD_04")
        assert m["p1_name"] == "ComboKing"
        assert m["p2_name"] == "AlphaStrike"
        rounds = m["rounds"]
        assert len(rounds) == 3

        for i, (exp_p1, exp_p2, exp_f) in enumerate([
            (350, 0, 1500), (320, 0, 1600), (280, 0, 1800)
        ]):
            r = rounds[i]
            assert r["p1_hp"] == exp_p1, f"R{i+1} p1_hp"
            assert r["p2_hp"] == exp_p2, f"R{i+1} p2_hp"
            assert r["frames"] == exp_f, f"R{i+1} frames"
            assert r["winner"] == "ComboKing", f"R{i+1} winner"

    def test_spd05_rounds(self, results):
        m = self._find_match(results, "SPD_05")
        assert m["p1_name"] == "ComboKing"
        assert m["p2_name"] == "MctsBot"
        rounds = m["rounds"]
        assert len(rounds) == 3
        for r in rounds:
            assert r["winner"] == "ComboKing"


class TestDamageConsistency:
    """Verify damage totals are consistent with HP changes.
    If the proto schema field mapping is wrong, these values will be
    wildly incorrect (near-zero instead of expected values)."""

    def _find_match(self, results, match_id):
        for m in results["matches"]:
            if m["match_id"] == match_id:
                return m
        pytest.fail(f"Match {match_id} not found")

    def test_comboking_damage_totals_std04(self, results):
        m = self._find_match(results, "STD_04")
        # ComboKing deals 400 damage per round (AS HP: 400->0) x 3 rounds = 1200
        assert m["p1_total_damage"] == 1200
        # AlphaStrike deals 50 + 80 + 120 = 250
        assert m["p2_total_damage"] == 250

    def test_alphastrike_damage_std01(self, results):
        m = self._find_match(results, "STD_01")
        # R1: AS deals 400 to GB, R2: AS deals 280 to GB, R3: AS deals 400 to GB
        # Total = 400 + 280 + 400 = 1080
        # Wait: R1 p2_hp=0 means AS dealt 400, R2 p2_hp=120 but GB wins so
        # we check AS (P1) total damage
        # R1: GB goes from 400 to 0 -> AS dealt 400
        # R2: AS goes from 400 to 0 -> GB dealt 400, AS's damage = 400-120=280
        # R3: GB goes from 400 to 0 -> AS dealt 400
        assert m["p1_total_damage"] == 400 + 280 + 400

    def test_nonzero_hits_std04(self, results):
        m = self._find_match(results, "STD_04")
        # ComboKing has 11+10+9 = 30 hits across 3 rounds
        assert m["p1_total_hits"] == 30
        # AlphaStrike has 2+2+3 = 7 hits
        assert m["p2_total_hits"] == 7


class TestComboAnalysis:
    """Verify combo detection and damage proration for STD_04."""

    def _find_match(self, results, match_id):
        for m in results["matches"]:
            if m["match_id"] == match_id:
                return m
        pytest.fail(f"Match {match_id} not found")

    def test_comboking_max_combo_length(self, results):
        m = self._find_match(results, "STD_04")
        # ComboKing has a 4-hit combo in Round 1
        assert m["p1_max_combo_length"] == 4

    def test_comboking_max_combo_raw_damage(self, results):
        m = self._find_match(results, "STD_04")
        # Highest raw damage combo: R3 combo [80, 64, 51] = 195
        assert m["p1_max_combo_raw_damage"] == 195

    def test_comboking_max_combo_scaled_damage(self, results):
        m = self._find_match(results, "STD_04")
        # R3 combo [80, 64, 51] with factor 0.8:
        # 80*1.0 + 64*0.8 + 51*0.64 = 80 + 51.2 + 32.64 = 163.84
        assert abs(m["p1_max_combo_scaled_damage"] - 163.84) < 0.01

    def test_alphastrike_no_combos(self, results):
        m = self._find_match(results, "STD_04")
        assert m["p2_max_combo_length"] == 0
        assert m["p2_max_combo_raw_damage"] == 0
        assert m["p2_max_combo_scaled_damage"] == 0.0

    def test_no_combos_non_combo_match(self, results):
        """Non-ComboKing matches have no combos (hit spacing > stun duration)."""
        m = self._find_match(results, "STD_01")
        assert m["p1_max_combo_length"] == 0
        assert m["p2_max_combo_length"] == 0
        assert m["p1_max_combo_scaled_damage"] == 0.0
        assert m["p2_max_combo_scaled_damage"] == 0.0


class TestStandardLeague:
    """Verify Standard league rankings."""

    def test_standard_ranking_order(self, results):
        rankings = results["standard_league"]["rankings"]
        assert len(rankings) == 4
        names = [r["ai"] for r in rankings]
        assert names == ["ComboKing", "AlphaStrike", "Rushdown", "GuardBot"]

    def test_standard_round_wins(self, results):
        rankings = results["standard_league"]["rankings"]
        wins = {r["ai"]: r["round_wins"] for r in rankings}
        assert wins["ComboKing"] == 15
        assert wins["AlphaStrike"] == 10
        assert wins["Rushdown"] == 7
        assert wins["GuardBot"] == 4

    def test_standard_remaining_hp(self, results):
        rankings = results["standard_league"]["rankings"]
        hp = {r["ai"]: r["total_remaining_hp"] for r in rankings}
        assert hp["ComboKing"] == 4660
        assert hp["AlphaStrike"] == 1860
        assert hp["Rushdown"] == 730
        assert hp["GuardBot"] == 340

    def test_standard_f1_points(self, results):
        rankings = results["standard_league"]["rankings"]
        pts = {r["ai"]: r["f1_points"] for r in rankings}
        assert pts["ComboKing"] == 25
        assert pts["AlphaStrike"] == 18
        assert pts["Rushdown"] == 15
        assert pts["GuardBot"] == 12


class TestSpeedrunningLeague:
    """Verify Speedrunning league rankings."""

    def test_speedrunning_ranking_order(self, results):
        rankings = results["speedrunning_league"]["rankings"]
        assert len(rankings) == 4
        names = [r["ai"] for r in rankings]
        assert names == ["ComboKing", "AlphaStrike", "Rushdown", "GuardBot"]

    def test_speedrunning_avg_frames(self, results):
        rankings = results["speedrunning_league"]["rankings"]
        avgs = {r["ai"]: r["avg_frames"] for r in rankings}
        assert abs(avgs["ComboKing"] - 1250.0) < 0.01
        assert abs(avgs["AlphaStrike"] - 2800.0) < 0.01
        assert abs(avgs["Rushdown"] - 17600.0 / 6) < 0.1
        assert abs(avgs["GuardBot"] - 3900.0) < 0.01

    def test_speedrunning_f1_points(self, results):
        rankings = results["speedrunning_league"]["rankings"]
        pts = {r["ai"]: r["f1_points"] for r in rankings}
        assert pts["ComboKing"] == 25
        assert pts["AlphaStrike"] == 18
        assert pts["Rushdown"] == 15
        assert pts["GuardBot"] == 12


class TestEloRatings:
    """Verify Elo rating computation from standard league matches."""

    def test_elo_ratings_present(self, results):
        elo = results["elo_ratings"]
        for ai in ["ComboKing", "AlphaStrike", "Rushdown", "GuardBot"]:
            assert ai in elo, f"Missing Elo rating for {ai}"

    def test_elo_ratings_order(self, results):
        elo = results["elo_ratings"]
        assert elo["ComboKing"] > elo["AlphaStrike"] > \
               elo["Rushdown"] > elo["GuardBot"], \
            f"Unexpected Elo order: CK={elo['ComboKing']}, " \
            f"AS={elo['AlphaStrike']}, RD={elo['Rushdown']}, " \
            f"GB={elo['GuardBot']}"

    def test_elo_ratings_sum_conserved(self, results):
        """Elo is zero-sum: total should remain 4*1500 = 6000."""
        elo = results["elo_ratings"]
        total = sum(elo.values())
        assert abs(total - 6000.0) < 1.0, \
            f"Elo sum should be ~6000, got {total}"

    def test_elo_comboking_range(self, results):
        """ComboKing wins 15/18 rounds, should be well above 1500."""
        elo = results["elo_ratings"]
        assert 1600 < elo["ComboKing"] < 1625, \
            f"ComboKing Elo {elo['ComboKing']} outside expected range"

    def test_elo_guardbot_range(self, results):
        """GuardBot wins only 4/18 rounds, should be well below 1500."""
        elo = results["elo_ratings"]
        assert 1390 < elo["GuardBot"] < 1415, \
            f"GuardBot Elo {elo['GuardBot']} outside expected range"

    def test_elo_alphastrike_range(self, results):
        elo = results["elo_ratings"]
        assert 1515 < elo["AlphaStrike"] < 1535, \
            f"AlphaStrike Elo {elo['AlphaStrike']} outside expected range"

    def test_elo_rushdown_range(self, results):
        elo = results["elo_ratings"]
        assert 1455 < elo["Rushdown"] < 1480, \
            f"Rushdown Elo {elo['Rushdown']} outside expected range"


class TestFinalRankings:
    """Verify combined final rankings with Elo bonus."""

    def test_final_ranking_order(self, results):
        rankings = results["final_rankings"]
        assert len(rankings) == 4
        names = [r["ai"] for r in rankings]
        assert names == ["ComboKing", "AlphaStrike", "Rushdown", "GuardBot"]

    def test_final_points_breakdown(self, results):
        rankings = results["final_rankings"]
        pts = {r["ai"]: r for r in rankings}

        # ComboKing: std=25, spd=25, elo_bonus=2 (highest Elo), total=52
        assert pts["ComboKing"]["std_f1"] == 25
        assert pts["ComboKing"]["spd_f1"] == 25
        assert pts["ComboKing"]["elo_bonus"] == 2
        assert pts["ComboKing"]["total_points"] == 52

        # AlphaStrike: std=18, spd=18, elo_bonus=1 (2nd highest Elo), total=37
        assert pts["AlphaStrike"]["std_f1"] == 18
        assert pts["AlphaStrike"]["spd_f1"] == 18
        assert pts["AlphaStrike"]["elo_bonus"] == 1
        assert pts["AlphaStrike"]["total_points"] == 37

        # Rushdown: std=15, spd=15, elo_bonus=0, total=30
        assert pts["Rushdown"]["std_f1"] == 15
        assert pts["Rushdown"]["spd_f1"] == 15
        assert pts["Rushdown"]["elo_bonus"] == 0
        assert pts["Rushdown"]["total_points"] == 30

        # GuardBot: std=12, spd=12, elo_bonus=0, total=24
        assert pts["GuardBot"]["std_f1"] == 12
        assert pts["GuardBot"]["spd_f1"] == 12
        assert pts["GuardBot"]["elo_bonus"] == 0
        assert pts["GuardBot"]["total_points"] == 24
