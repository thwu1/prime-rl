
import subprocess
import json
import os
import pytest


def run_analyzer(scenario_name):
    """Run the CLang analyzer on a scenario and return parsed JSON output."""
    scenario_path = f"/app/scenarios/{scenario_name}"
    assert os.path.exists("/app/clang_analyzer.py"), "clang_analyzer.py must exist at /app/clang_analyzer.py"
    assert os.path.exists(scenario_path), f"Scenario file {scenario_path} must exist"
    result = subprocess.run(
        ["python3", "/app/clang_analyzer.py", scenario_path],
        capture_output=True, text=True, timeout=60, cwd="/app",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    )
    assert result.returncode == 0, f"Analyzer failed on {scenario_name}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"Analyzer output is not valid JSON for {scenario_name}:\n{result.stdout[:500]}")


# ===== Scenario 1: Basic definitions, activation, state tracking =====

@pytest.fixture(scope="class")
def scenario_1_data():
    return run_analyzer("scenario_1.clang")

class TestScenario1:
    def test_defined_conditions(self, scenario_1_data):
        assert scenario_1_data["defined_conditions"] == ["InOurHalf"]

    def test_defined_actions(self, scenario_1_data):
        assert scenario_1_data["defined_actions"] == ["PassTo7"]

    def test_defined_regions(self, scenario_1_data):
        assert scenario_1_data["defined_regions"] == ["BoxArea"]

    def test_active_rules(self, scenario_1_data):
        assert scenario_1_data["active_rules"] == ["Rule_A", "Rule_B"]

    def test_deleted_entities(self, scenario_1_data):
        assert scenario_1_data["deleted_entities"] == []

    def test_player_coverage(self, scenario_1_data):
        pc = scenario_1_data["player_coverage"]
        for p in ["2", "3", "4", "5"]:
            assert p in pc, f"Player {p} should be covered"
            assert "Rule_A" in pc[p]
        assert "6" in pc
        assert "Rule_B" in pc["6"]

    def test_dependencies_rule_a(self, scenario_1_data):
        deps = scenario_1_data["dependencies"]
        assert "Rule_A" in deps
        assert sorted(deps["Rule_A"]) == ["BoxArea"]

    def test_dependencies_rule_b(self, scenario_1_data):
        deps = scenario_1_data["dependencies"]
        assert "Rule_B" in deps
        assert sorted(deps["Rule_B"]) == ["InOurHalf"]

    def test_no_conflicts(self, scenario_1_data):
        assert scenario_1_data["conflicts"] == []

    def test_no_expanded_rules(self, scenario_1_data):
        assert scenario_1_data["expanded_rules"] == {} or len(scenario_1_data["expanded_rules"]) == 0


# ===== Scenario 2: Nested rules and expansion =====

@pytest.fixture(scope="class")
def scenario_2_data():
    return run_analyzer("scenario_2.clang")

class TestScenario2:
    def test_active_rules(self, scenario_2_data):
        assert sorted(scenario_2_data["active_rules"]) == ["Outer_X", "Outer_Y"]

    def test_outer_x_expanded(self, scenario_2_data):
        exp = scenario_2_data["expanded_rules"]
        assert "Outer_X" in exp
        assert exp["Outer_X"]["num_clauses"] == 2

    def test_outer_x_clause_players(self, scenario_2_data):
        clauses = scenario_2_data["expanded_rules"]["Outer_X"]["clauses"]
        all_players = set()
        for clause in clauses:
            for d in clause["directives"]:
                for p in d["players"]:
                    all_players.add(p)
        assert all_players == {2, 3}

    def test_outer_x_clause_actions(self, scenario_2_data):
        clauses = scenario_2_data["expanded_rules"]["Outer_X"]["clauses"]
        all_actions = set()
        for clause in clauses:
            for d in clause["directives"]:
                for a in d["actions"]:
                    all_actions.add(a)
        assert all_actions == {"pos"}

    def test_outer_y_expanded(self, scenario_2_data):
        exp = scenario_2_data["expanded_rules"]
        assert "Outer_Y" in exp
        assert exp["Outer_Y"]["num_clauses"] == 2

    def test_outer_y_clause_players(self, scenario_2_data):
        clauses = scenario_2_data["expanded_rules"]["Outer_Y"]["clauses"]
        all_players = set()
        for clause in clauses:
            for d in clause["directives"]:
                for p in d["players"]:
                    all_players.add(p)
        assert all_players == {3, 11}

    def test_outer_y_clause_actions(self, scenario_2_data):
        clauses = scenario_2_data["expanded_rules"]["Outer_Y"]["clauses"]
        all_actions = set()
        for clause in clauses:
            for d in clause["directives"]:
                for a in d["actions"]:
                    all_actions.add(a)
        assert all_actions == {"pos", "shoot"}

    def test_player_coverage(self, scenario_2_data):
        pc = scenario_2_data["player_coverage"]
        assert "2" in pc
        assert "3" in pc
        assert "11" in pc

    def test_dependencies_outer_x(self, scenario_2_data):
        deps = scenario_2_data["dependencies"]
        assert "Outer_X" in deps
        dep_set = set(deps["Outer_X"])
        assert "Inner_A" in dep_set
        assert "Inner_B" in dep_set

    def test_dependencies_outer_y(self, scenario_2_data):
        deps = scenario_2_data["dependencies"]
        assert "Outer_Y" in deps
        dep_set = set(deps["Outer_Y"])
        assert "Inner_B" in dep_set
        assert "Inner_E" in dep_set


# ===== Scenario 3: Conflict detection =====

@pytest.fixture(scope="class")
def scenario_3_data():
    return run_analyzer("scenario_3.clang")

class TestScenario3:
    def test_all_rules_active(self, scenario_3_data):
        expected = ["Hit1", "Hit2", "Hit3", "Hit4", "Hit5", "Hit6", "Hit7"]
        assert scenario_3_data["active_rules"] == sorted(expected)

    def test_conflict_hit1_hit2(self, scenario_3_data):
        conflicts = scenario_3_data["conflicts"]
        assert ["Hit1", "Hit2"] in conflicts

    def test_conflict_hit1_hit3(self, scenario_3_data):
        conflicts = scenario_3_data["conflicts"]
        assert ["Hit1", "Hit3"] in conflicts

    def test_conflict_hit2_hit3(self, scenario_3_data):
        conflicts = scenario_3_data["conflicts"]
        assert ["Hit2", "Hit3"] in conflicts

    def test_no_conflict_hit1_hit4(self, scenario_3_data):
        conflicts = scenario_3_data["conflicts"]
        assert ["Hit1", "Hit4"] not in conflicts

    def test_no_conflict_hit2_hit4(self, scenario_3_data):
        conflicts = scenario_3_data["conflicts"]
        assert ["Hit2", "Hit4"] not in conflicts

    def test_no_conflict_hit3_hit4(self, scenario_3_data):
        conflicts = scenario_3_data["conflicts"]
        assert ["Hit3", "Hit4"] not in conflicts

    def test_no_conflict_hit1_hit5(self, scenario_3_data):
        conflicts = scenario_3_data["conflicts"]
        assert ["Hit1", "Hit5"] not in conflicts

    def test_no_conflict_hit6_hit7(self, scenario_3_data):
        conflicts = scenario_3_data["conflicts"]
        assert ["Hit6", "Hit7"] not in conflicts

    def test_conflict_hit4_hit7(self, scenario_3_data):
        conflicts = scenario_3_data["conflicts"]
        assert ["Hit4", "Hit7"] not in conflicts

    def test_conflict_hit4_hit5(self, scenario_3_data):
        conflicts = scenario_3_data["conflicts"]
        assert ["Hit4", "Hit5"] not in conflicts

    def test_conflict_count(self, scenario_3_data):
        conflicts = scenario_3_data["conflicts"]
        expected_conflicts = [
            ["Hit1", "Hit2"], ["Hit1", "Hit3"], ["Hit1", "Hit6"], ["Hit1", "Hit7"],
            ["Hit2", "Hit3"], ["Hit2", "Hit6"], ["Hit2", "Hit7"],
            ["Hit3", "Hit6"], ["Hit3", "Hit7"],
            ["Hit4", "Hit6"],
            ["Hit5", "Hit6"], ["Hit5", "Hit7"],
        ]
        assert sorted(conflicts) == sorted(expected_conflicts), f"Expected {len(expected_conflicts)} conflicts, got {len(conflicts)}: {conflicts}"


# ===== Scenario 4: Dependencies, deletions, deactivations =====

@pytest.fixture(scope="class")
def scenario_4_data():
    return run_analyzer("scenario_4.clang")

class TestScenario4:
    def test_deleted_entities(self, scenario_4_data):
        assert "Alpha" in scenario_4_data["deleted_entities"]

    def test_active_rules(self, scenario_4_data):
        active = scenario_4_data["active_rules"]
        assert "Alpha" not in active
        assert "Beta" not in active
        assert "Gamma" in active
        assert "Alpha_v2" in active

    def test_defined_conditions(self, scenario_4_data):
        assert sorted(scenario_4_data["defined_conditions"]) == ["OppBall", "OurBall"]

    def test_defined_actions(self, scenario_4_data):
        assert scenario_4_data["defined_actions"] == ["GoShoot"]

    def test_defined_regions(self, scenario_4_data):
        assert scenario_4_data["defined_regions"] == ["Wing_L"]

    def test_dependencies_gamma(self, scenario_4_data):
        deps = scenario_4_data["dependencies"]
        assert "Gamma" in deps, f"Gamma not in dependencies: {list(deps.keys())}"
        assert "OurBall" in deps["Gamma"], f"OurBall not in Gamma deps: {deps['Gamma']}"

    def test_dependencies_alpha_v2(self, scenario_4_data):
        deps = scenario_4_data["dependencies"]
        assert "Alpha_v2" in deps, f"Alpha_v2 not in dependencies: {list(deps.keys())}"
        assert "OurBall" in deps["Alpha_v2"], f"OurBall not in Alpha_v2 deps: {deps['Alpha_v2']}"

    def test_dependencies_beta(self, scenario_4_data):
        deps = scenario_4_data["dependencies"]
        assert "Beta" in deps, f"Beta not in dependencies: {list(deps.keys())}"
        dep_set = set(deps["Beta"])
        assert "OppBall" in dep_set, f"OppBall not in Beta deps: {deps['Beta']}"
        assert "Wing_L" in dep_set, f"Wing_L not in Beta deps: {deps['Beta']}"

    def test_player_coverage(self, scenario_4_data):
        pc = scenario_4_data["player_coverage"]
        assert "10" in pc
        assert "Gamma" in pc["10"]
        assert "9" in pc
        assert "Alpha_v2" in pc["9"]


# ===== Scenario 5: Full tactical analysis =====

@pytest.fixture(scope="class")
def scenario_5_data():
    return run_analyzer("scenario_5.clang")

class TestScenario5:
    def test_defined_conditions(self, scenario_5_data):
        expected = ["BallInOppThird", "BallInOurThird", "Midfield", "OppBall", "OurBall"]
        assert scenario_5_data["defined_conditions"] == expected

    def test_defined_actions(self, scenario_5_data):
        assert sorted(scenario_5_data["defined_actions"]) == ["GoShoot", "HoldBall"]

    def test_defined_regions(self, scenario_5_data):
        assert sorted(scenario_5_data["defined_regions"]) == ["CenterZone", "LeftFlank", "RightFlank"]

    def test_deleted_entities(self, scenario_5_data):
        assert "Def_Mid" in scenario_5_data["deleted_entities"]

    def test_active_rules(self, scenario_5_data):
        active = scenario_5_data["active_rules"]
        assert "Def_Mid" not in active
        assert "Def_Mid_v2" in active
        assert "Atk_Wings" in active
        assert "Atk_Final" in active
        assert "Atk_Hold" in active
        assert "Def_Deep" in active

    def test_no_conflict_defense_vs_attack(self, scenario_5_data):
        conflicts = scenario_5_data["conflicts"]
        for pair in conflicts:
            has_def = any(r.startswith("Def_") for r in pair)
            has_atk = any(r.startswith("Atk_") for r in pair)
            assert not (has_def and has_atk), f"Defense vs attack conflict should not exist: {pair}"

    def test_conflict_atk_final_vs_atk_hold(self, scenario_5_data):
        conflicts = scenario_5_data["conflicts"]
        assert ["Atk_Final", "Atk_Hold"] in conflicts

    def test_player_coverage_comprehensive(self, scenario_5_data):
        pc = scenario_5_data["player_coverage"]
        for p in ["2", "3", "4", "5"]:
            assert p in pc
            assert "Def_Deep" in pc[p]
        assert "6" in pc
        assert "Def_Mid_v2" in pc["6"]
        assert "8" in pc
        assert "Def_Mid_v2" in pc["8"]
        assert "7" in pc
        assert "Atk_Wings" in pc["7"]
        assert "11" in pc
        assert "Atk_Wings" in pc["11"]
        assert "9" in pc
        assert "Atk_Final" in pc["9"]
        assert "10" in pc
        assert "Atk_Final" in pc["10"]
        assert "Atk_Hold" in pc["9"]

    def test_dependencies_atk_wings(self, scenario_5_data):
        deps = scenario_5_data["dependencies"]
        assert "Atk_Wings" in deps
        dep_set = set(deps["Atk_Wings"])
        assert "OurBall" in dep_set
        assert "Midfield" in dep_set
        assert "LeftFlank" in dep_set
        assert "RightFlank" in dep_set

    def test_dependencies_atk_final(self, scenario_5_data):
        deps = scenario_5_data["dependencies"]
        assert "Atk_Final" in deps
        dep_set = set(deps["Atk_Final"])
        assert "OurBall" in dep_set
        assert "BallInOppThird" in dep_set
        assert "GoShoot" in dep_set

    def test_dependencies_def_mid_v2(self, scenario_5_data):
        deps = scenario_5_data["dependencies"]
        assert "Def_Mid_v2" in deps
        dep_set = set(deps["Def_Mid_v2"])
        assert "OppBall" in dep_set
        assert "Midfield" in dep_set
