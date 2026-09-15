
import json
import math
import os
import sqlite3
import sys

sys.path.insert(0, "/app")
from engine import resolve_step


def find_unit(result, team, uid):
    for u in result["units"]:
        if u["team"] == team and u["id"] == uid:
            return u
    raise ValueError(f"Unit team={team} id={uid} not found")


# ---------------------------------------------------------------------------
# SQLite replay analysis database
# ---------------------------------------------------------------------------
class TestDatabase:
    def setup_method(self):
        assert os.path.exists("/app/replay_analysis.db"), \
            "replay_analysis.db must exist at /app/"
        self.conn = sqlite3.connect("/app/replay_analysis.db")

    def teardown_method(self):
        self.conn.close()

    def test_transitions_schema_and_data(self):
        cur = self.conn.execute("PRAGMA table_info(transitions)")
        cols = {row[1] for row in cur.fetchall()}
        assert {"match_id", "transition_id", "label", "unit_count"}.issubset(cols), \
            f"transitions missing columns, has: {cols}"
        cur = self.conn.execute(
            "SELECT DISTINCT match_id FROM transitions ORDER BY match_id"
        )
        matches = [row[0] for row in cur.fetchall()]
        assert "A" in matches and "B" in matches, \
            f"transitions must have data for both matches, has: {matches}"

    def test_unit_actions_schema_and_data(self):
        cur = self.conn.execute("PRAGMA table_info(unit_actions)")
        cols = {row[1] for row in cur.fetchall()}
        required = {
            "match_id", "transition_id", "team", "unit_id", "direction",
            "energy_before", "energy_after", "x_before", "y_before",
            "x_after", "y_after", "alive_after",
        }
        assert required.issubset(cols), \
            f"unit_actions missing columns: {required - cols}"
        cur = self.conn.execute("SELECT COUNT(*) FROM unit_actions")
        assert cur.fetchone()[0] > 0, "unit_actions must have data"

    def test_sap_events_view(self):
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name='sap_events'"
        )
        assert cur.fetchone() is not None, "View sap_events must exist"
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM sap_events WHERE direction != 5"
        )
        assert cur.fetchone()[0] == 0, "sap_events must only contain direction=5"
        cur = self.conn.execute("SELECT COUNT(*) FROM sap_events")
        assert cur.fetchone()[0] > 0, "sap_events must have data"

    def test_energy_deltas_view(self):
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name='energy_deltas'"
        )
        assert cur.fetchone() is not None, "View energy_deltas must exist"
        cur = self.conn.execute("SELECT * FROM energy_deltas LIMIT 1")
        cols = [desc[0] for desc in cur.description]
        assert "energy_delta" in cols, \
            f"energy_deltas must have energy_delta column, has: {cols}"

    def test_known_transition_data(self):
        """Verify data integrity: match_A transition 1, T0U0 energy 200->204."""
        cur = self.conn.execute(
            "SELECT energy_before, energy_after FROM unit_actions "
            "WHERE match_id='A' AND transition_id=1 AND team=0 AND unit_id=0"
        )
        row = cur.fetchone()
        assert row is not None, "T0U0 in match_A transition 1 must exist"
        assert row[0] == 200, f"energy_before should be 200, got {row[0]}"
        assert row[1] == 204, f"energy_after should be 204, got {row[1]}"


# ---------------------------------------------------------------------------
# Spec clarification verdicts
# ---------------------------------------------------------------------------
class TestSpecClarifications:
    def setup_method(self):
        with open("/app/spec_clarifications.json") as f:
            self.clarif = json.load(f)

    def test_all_keys_present(self):
        expected = {
            "void_energy_snapshot", "collision_tie_behavior",
            "sap_dropoff_rounding", "void_stacking_division",
        }
        assert expected.issubset(set(self.clarif.keys())), \
            f"Missing keys: {expected - set(self.clarif.keys())}"

    def test_void_snapshot(self):
        assert self.clarif["void_energy_snapshot"]["determination"] == \
            "post_movement_pre_sap"

    def test_collision_tie(self):
        assert self.clarif["collision_tie_behavior"]["determination"] == \
            "all_removed"

    def test_dropoff_rounding(self):
        assert self.clarif["sap_dropoff_rounding"]["determination"] == "floor"

    def test_void_stacking(self):
        assert self.clarif["void_stacking_division"]["determination"] == \
            "divide_by_friendly_count"

    def test_candidates_present(self):
        for key in self.clarif:
            assert "candidates" in self.clarif[key], \
                f"{key} must have candidates list"
            assert len(self.clarif[key]["candidates"]) >= 2, \
                f"{key} must have at least 2 candidates"


# ---------------------------------------------------------------------------
# Parameter extraction verification
# ---------------------------------------------------------------------------
class TestParameterExtraction:
    def setup_method(self):
        with open("/app/extracted_params.json") as f:
            self.params = json.load(f)

    # Match A
    def test_a_move_cost(self):
        assert self.params["match_A"]["unit_move_cost"] == 3

    def test_a_sap_cost(self):
        assert self.params["match_A"]["unit_sap_cost"] == 35

    def test_a_sap_range(self):
        assert self.params["match_A"]["unit_sap_range"] == 4

    def test_a_dropoff(self):
        assert self.params["match_A"]["unit_sap_dropoff_factor"] == 0.25

    def test_a_void_factor(self):
        assert self.params["match_A"]["unit_energy_void_factor"] == 0.25

    def test_a_nebula(self):
        assert self.params["match_A"]["nebula_tile_energy_reduction"] == 3

    def test_a_max_energy(self):
        assert self.params["match_A"]["max_unit_energy"] == 400

    # Match B
    def test_b_move_cost(self):
        assert self.params["match_B"]["unit_move_cost"] == 5

    def test_b_sap_cost(self):
        assert self.params["match_B"]["unit_sap_cost"] == 45

    def test_b_sap_range(self):
        assert self.params["match_B"]["unit_sap_range"] == 6

    def test_b_dropoff(self):
        assert self.params["match_B"]["unit_sap_dropoff_factor"] == 1.0

    def test_b_void_factor(self):
        assert self.params["match_B"]["unit_energy_void_factor"] == 0.0625

    def test_b_nebula(self):
        assert self.params["match_B"]["nebula_tile_energy_reduction"] == 25

    def test_b_max_energy(self):
        assert self.params["match_B"]["max_unit_energy"] == 400


# ---------------------------------------------------------------------------
# Engine bug tests — each isolates one bug
# ---------------------------------------------------------------------------
class TestEngineBugs:
    def _params(self, **kw):
        p = {
            "map_width": 24, "map_height": 24,
            "unit_move_cost": 2, "unit_sap_cost": 40,
            "unit_sap_range": 5, "unit_sap_dropoff_factor": 0.5,
            "unit_energy_void_factor": 0.25, "max_unit_energy": 400,
            "nebula_tile_energy_reduction": 10,
        }
        p.update(kw)
        return p

    def test_sap_dropoff_uses_floor_not_round(self):
        """Bug 3: dropoff must use floor, not round."""
        scenario = {
            "params": self._params(
                unit_sap_cost=35,
                unit_sap_dropoff_factor=0.25,
            ),
            "units": [
                {"team": 0, "id": 0, "position": [3, 3], "energy": 200},
                {"team": 1, "id": 0, "position": [6, 4], "energy": 100},
            ],
            "map_features": {"tiles": []},
            "relic_nodes": [],
            "actions": {
                "team_0": [{"unit_id": 0, "direction": 5, "sap_dx": 2, "sap_dy": 0}],
                "team_1": [{"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0}],
            },
        }
        result = resolve_step(scenario)
        # Sap target [5,3]. T1U0 at [6,4]: diag adj (dx=1,dy=1).
        # floor(35*0.25) = floor(8.75) = 8, NOT round(8.75) = 9
        t1u0 = find_unit(result, 1, 0)
        assert t1u0["energy"] == 92, (
            f"AoE dropoff must use floor: expected 100-8=92, got {t1u0['energy']}"
        )

    def test_collision_tie_removes_all(self):
        """Bug 2: equal aggregate energy must remove ALL units on tile."""
        scenario = {
            "params": self._params(),
            "units": [
                {"team": 0, "id": 0, "position": [5, 5], "energy": 150},
                {"team": 1, "id": 0, "position": [5, 5], "energy": 150},
            ],
            "map_features": {"tiles": []},
            "relic_nodes": [],
            "actions": {
                "team_0": [{"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0}],
                "team_1": [{"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0}],
            },
        }
        result = resolve_step(scenario)
        assert find_unit(result, 0, 0)["alive"] is False, "Tie: team 0 must die"
        assert find_unit(result, 1, 0)["alive"] is False, "Tie: team 1 must die"

    def test_void_uses_pre_sap_energy(self):
        """Bug 1: void field must use energy snapshot from AFTER movement, BEFORE sap."""
        scenario = {
            "params": self._params(
                unit_sap_cost=40,
                unit_energy_void_factor=0.25,
            ),
            "units": [
                {"team": 0, "id": 0, "position": [5, 5], "energy": 200},
                {"team": 1, "id": 0, "position": [6, 5], "energy": 300},
            ],
            "map_features": {"tiles": []},
            "relic_nodes": [],
            "actions": {
                "team_0": [{"unit_id": 0, "direction": 5, "sap_dx": 1, "sap_dy": 0}],
                "team_1": [{"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0}],
            },
        }
        result = resolve_step(scenario)
        # After sap: T0U0=160, T1U0=260
        # Void uses ORIGINAL energy: T0U0_orig=200, T1U0_orig=300
        # Drain on T0U0: floor(0.25*300)=75 -> 160-75=85
        # Drain on T1U0: floor(0.25*200)=50 -> 260-50=210
        t0u0 = find_unit(result, 0, 0)
        t1u0 = find_unit(result, 1, 0)
        assert t0u0["energy"] == 85, (
            f"Void must use pre-sap energy: expected 85, got {t0u0['energy']}"
        )
        assert t1u0["energy"] == 210, (
            f"Void must use pre-sap energy: expected 210, got {t1u0['energy']}"
        )

    def test_void_divides_by_friendly_count(self):
        """Bug 4: void drain must be divided by number of friendly units on tile."""
        scenario = {
            "params": self._params(unit_energy_void_factor=0.25),
            "units": [
                {"team": 0, "id": 0, "position": [10, 10], "energy": 200},
                {"team": 0, "id": 1, "position": [10, 10], "energy": 200},
                {"team": 1, "id": 0, "position": [11, 10], "energy": 400},
            ],
            "map_features": {"tiles": []},
            "relic_nodes": [],
            "actions": {
                "team_0": [
                    {"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0},
                    {"unit_id": 1, "direction": 0, "sap_dx": 0, "sap_dy": 0},
                ],
                "team_1": [
                    {"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0},
                ],
            },
        }
        result = resolve_step(scenario)
        # Void from T1U0(400) at [10,10]. 2 friendly T0 units on tile.
        # Drain = floor(0.25 * 400 / 2) = 50 each
        t0u0 = find_unit(result, 0, 0)
        t0u1 = find_unit(result, 0, 1)
        assert t0u0["energy"] == 150, (
            f"Void stacking: expected 200-50=150, got {t0u0['energy']}"
        )
        assert t0u1["energy"] == 150, (
            f"Void stacking: expected 200-50=150, got {t0u1['energy']}"
        )


# ---------------------------------------------------------------------------
# Dynamic anti-cheat tests
# ---------------------------------------------------------------------------
class TestDynamic:
    def _params(self, **kw):
        p = {
            "map_width": 20, "map_height": 20,
            "unit_move_cost": 4, "unit_sap_cost": 33,
            "unit_sap_range": 3, "unit_sap_dropoff_factor": 0.5,
            "unit_energy_void_factor": 0.125, "max_unit_energy": 400,
            "nebula_tile_energy_reduction": 5,
        }
        p.update(kw)
        return p

    def test_movement_basic(self):
        scenario = {
            "params": self._params(),
            "units": [
                {"team": 0, "id": 0, "position": [5, 5], "energy": 100},
            ],
            "map_features": {"tiles": []},
            "relic_nodes": [],
            "actions": {
                "team_0": [{"unit_id": 0, "direction": 2, "sap_dx": 0, "sap_dy": 0}],
                "team_1": [],
            },
        }
        result = resolve_step(scenario)
        u = find_unit(result, 0, 0)
        assert u["position"] == [6, 5]
        assert u["energy"] == 96  # 100 - 4
        assert u["alive"] is True

    def test_sap_with_custom_params(self):
        scenario = {
            "params": self._params(),
            "units": [
                {"team": 0, "id": 0, "position": [5, 5], "energy": 200},
                {"team": 1, "id": 0, "position": [7, 5], "energy": 150},
                {"team": 1, "id": 1, "position": [8, 6], "energy": 100},
            ],
            "map_features": {"tiles": []},
            "relic_nodes": [],
            "actions": {
                "team_0": [{"unit_id": 0, "direction": 5, "sap_dx": 2, "sap_dy": 0}],
                "team_1": [
                    {"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0},
                    {"unit_id": 1, "direction": 0, "sap_dx": 0, "sap_dy": 0},
                ],
            },
        }
        result = resolve_step(scenario)
        # Target [7,5]. T1U0 direct hit: 150-33=117.
        # T1U1 at [8,6]: diag adj to [7,5]. AoE = floor(33*0.5)=floor(16.5)=16. 100-16=84.
        # T0U0: 200-33=167
        assert find_unit(result, 0, 0)["energy"] == 167
        assert find_unit(result, 1, 0)["energy"] == 117
        assert find_unit(result, 1, 1)["energy"] == 84

    def test_collision_multi_unit_tie(self):
        scenario = {
            "params": self._params(),
            "units": [
                {"team": 0, "id": 0, "position": [5, 5], "energy": 80},
                {"team": 0, "id": 1, "position": [5, 5], "energy": 70},
                {"team": 1, "id": 0, "position": [5, 5], "energy": 100},
                {"team": 1, "id": 1, "position": [5, 5], "energy": 50},
            ],
            "map_features": {"tiles": []},
            "relic_nodes": [],
            "actions": {
                "team_0": [
                    {"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0},
                    {"unit_id": 1, "direction": 0, "sap_dx": 0, "sap_dy": 0},
                ],
                "team_1": [
                    {"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0},
                    {"unit_id": 1, "direction": 0, "sap_dx": 0, "sap_dy": 0},
                ],
            },
        }
        result = resolve_step(scenario)
        # T0 aggregate: 80+70=150, T1 aggregate: 100+50=150 -> TIE, all die
        for t in [0, 1]:
            for i in [0, 1]:
                assert find_unit(result, t, i)["alive"] is False, \
                    f"Tie collision: team {t} unit {i} must die"

    def test_void_with_stacking_and_sap(self):
        scenario = {
            "params": self._params(
                unit_sap_cost=30,
                unit_energy_void_factor=0.25,
                unit_sap_range=5,
            ),
            "units": [
                {"team": 0, "id": 0, "position": [5, 5], "energy": 200},
                {"team": 0, "id": 1, "position": [5, 5], "energy": 160},
                {"team": 1, "id": 0, "position": [6, 5], "energy": 300},
            ],
            "map_features": {"tiles": []},
            "relic_nodes": [],
            "actions": {
                "team_0": [
                    {"unit_id": 0, "direction": 5, "sap_dx": 1, "sap_dy": 0},
                    {"unit_id": 1, "direction": 0, "sap_dx": 0, "sap_dy": 0},
                ],
                "team_1": [
                    {"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0},
                ],
            },
        }
        result = resolve_step(scenario)
        # Phase 2: T0U0 saps [6,5]. T0U0: 200-30=170. T1U0: 300-30=270.
        # Original energy: T0U0=200, T0U1=160, T1U0=300
        # Phase 4: Void
        # Void map team 0 at [6,5]: T0U0 orig(200) + T0U1 orig(160) = 360
        # Void map team 1 at [5,5]: T1U0 orig(300)
        # Drain on T0U0: floor(0.25 * 300 / 2) = floor(37.5) = 37. 170-37=133
        # Drain on T0U1: floor(0.25 * 300 / 2) = floor(37.5) = 37. 160-37=123
        # Drain on T1U0: floor(0.25 * 360 / 1) = floor(90) = 90. 270-90=180
        t0u0 = find_unit(result, 0, 0)
        t0u1 = find_unit(result, 0, 1)
        t1u0 = find_unit(result, 1, 0)
        assert t0u0["energy"] == 133, f"Expected 133, got {t0u0['energy']}"
        assert t0u1["energy"] == 123, f"Expected 123, got {t0u1['energy']}"
        assert t1u0["energy"] == 180, f"Expected 180, got {t1u0['energy']}"

    def test_relic_scoring(self):
        scenario = {
            "params": self._params(),
            "units": [
                {"team": 0, "id": 0, "position": [12, 11], "energy": 200},
                {"team": 1, "id": 0, "position": [14, 11], "energy": 200},
            ],
            "map_features": {"tiles": []},
            "relic_nodes": [
                {
                    "position": [12, 11],
                    "config": [
                        [0, 0, 0, 0, 0],
                        [0, 0, 0, 0, 0],
                        [0, 0, 1, 0, 0],
                        [0, 0, 0, 1, 0],
                        [0, 0, 0, 0, 0],
                    ],
                }
            ],
            "actions": {
                "team_0": [{"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0}],
                "team_1": [{"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0}],
            },
        }
        result = resolve_step(scenario)
        # config[2][2]=1 -> tile (12,11). config[3][3]=1 -> tile (13,12).
        # T0U0 at (12,11) -> 1 point. T1U0 at (14,11) -> 0 points.
        assert result["team_points"] == [1, 0]


# ---------------------------------------------------------------------------
# Replay matching — uses extracted params + replay data
# ---------------------------------------------------------------------------
class TestReplayMatching:
    def _convert(self, trans, map_size, params):
        units = []
        for u in trans["before"]["units"]:
            units.append({
                "team": u["t"], "id": u["i"],
                "position": [u["x"], u["y"]], "energy": u["e"],
            })
        tiles = []
        for t in trans["before"].get("tiles", []):
            tiles.append({
                "x": t["x"], "y": t["y"],
                "tile_type": t["type"], "energy": t["e"],
            })
        actions = {"team_0": [], "team_1": []}
        for team_str, acts in trans["actions"].items():
            key = f"team_{team_str}"
            for a in acts:
                actions[key].append({
                    "unit_id": a["i"], "direction": a["d"],
                    "sap_dx": a["sx"], "sap_dy": a["sy"],
                })
        return {
            "params": {
                **params,
                "map_width": map_size[0],
                "map_height": map_size[1],
            },
            "units": units,
            "map_features": {"tiles": tiles},
            "relic_nodes": trans["before"].get("relics", []),
            "actions": actions,
        }

    def _verify(self, trans, result, label):
        for exp in trans["after"]["units"]:
            u = find_unit(result, exp["t"], exp["i"])
            assert u["position"] == [exp["x"], exp["y"]], \
                f"[{label}] t{exp['t']}u{exp['i']} pos: {u['position']} != [{exp['x']},{exp['y']}]"
            assert u["energy"] == exp["e"], \
                f"[{label}] t{exp['t']}u{exp['i']} energy: {u['energy']} != {exp['e']}"
            assert u["alive"] == exp["alive"], \
                f"[{label}] t{exp['t']}u{exp['i']} alive: {u['alive']} != {exp['alive']}"
        assert result["team_points"] == trans["after"]["points"], \
            f"[{label}] points: {result['team_points']} != {trans['after']['points']}"

    def test_match_a(self):
        with open("/app/extracted_params.json") as f:
            all_params = json.load(f)
        with open("/app/replays/match_A.json") as f:
            replay = json.load(f)
        params = all_params["match_A"]
        for trans in replay["transitions"]:
            scenario = self._convert(trans, replay["map_size"], params)
            result = resolve_step(scenario)
            self._verify(trans, result, f"A.{trans['id']}")

    def test_match_b(self):
        with open("/app/extracted_params.json") as f:
            all_params = json.load(f)
        with open("/app/replays/match_B.json") as f:
            replay = json.load(f)
        params = all_params["match_B"]
        for trans in replay["transitions"]:
            scenario = self._convert(trans, replay["map_size"], params)
            result = resolve_step(scenario)
            self._verify(trans, result, f"B.{trans['id']}")
