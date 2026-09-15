
import json
import os
import sys
sys.path.insert(0, "/app")
import pytest
from engine import GameEngine


def make_config(**kwargs):
    default_roles = [
        {
            "name": "default",
            "vision": 5,
            "actions": ["skip", "move", "rotate", "adopt", "request", "attach",
                        "detach", "connect", "disconnect", "submit", "clear", "survey"],
            "speed": [2, 1, 0],
            "clear": {"chance": 1.0, "maxDistance": 2}
        },
        {
            "name": "explorer",
            "vision": 7,
            "actions": ["skip", "move", "rotate", "adopt", "survey"],
            "speed": [3, 2, 1, 0],
            "clear": {"chance": 0.0, "maxDistance": 0}
        },
        {
            "name": "worker",
            "vision": 5,
            "actions": ["skip", "move", "rotate", "adopt", "request", "attach",
                        "detach", "connect", "disconnect", "submit"],
            "speed": [1, 1, 1, 0],
            "clear": {"chance": 0.0, "maxDistance": 0}
        }
    ]
    return {
        "grid": {"width": kwargs.get("width", 20), "height": kwargs.get("height", 20)},
        "roles": kwargs.get("roles", default_roles),
        "maxEnergy": kwargs.get("maxEnergy", 100),
        "stepRecharge": kwargs.get("stepRecharge", 1),
        "clearEnergyCost": kwargs.get("clearEnergyCost", 2),
        "deactivatedDuration": kwargs.get("deactivatedDuration", 10),
        "refreshEnergy": kwargs.get("refreshEnergy", 50),
        "clearDamage": kwargs.get("clearDamage", [32, 16, 8, 4, 2, 1]),
        "attachLimit": kwargs.get("attachLimit", 10),
        "steps": kwargs.get("steps", 500),
        "randomFail": 0
    }


def make_state(**kwargs):
    return {
        "agents": kwargs.get("agents", []),
        "blocks": kwargs.get("blocks", []),
        "dispensers": kwargs.get("dispensers", []),
        "obstacles": kwargs.get("obstacles", []),
        "tasks": kwargs.get("tasks", []),
        "norms": kwargs.get("norms", []),
        "goalZones": kwargs.get("goalZones", []),
        "roleZones": kwargs.get("roleZones", [])
    }


# ---------------------------------------------------------------------------
# Replay trace verification (7 traces)
# ---------------------------------------------------------------------------

class TestReplayTraceConsistency:
    """Cross-references engine behavior with reference replay traces."""

    def _load_replay(self, filename):
        with open(f"/app/replays/{filename}") as f:
            return json.load(f)

    def _run_replay(self, replay):
        config = replay["config"]
        state = replay["initial_state"]
        engine = GameEngine(config, state)
        divergences = []

        for step_data in replay["trace"]:
            actions = step_data["actions"]
            expected = step_data["expected"]
            results = engine.step(actions)

            for agent_name, exp_result in expected.get("results", {}).items():
                actual = results.get(agent_name, {}).get("result", "missing")
                if actual != exp_result:
                    divergences.append((
                        step_data["step"], f"{agent_name}.result",
                        exp_result, actual
                    ))

            for agent_name, exp_state in expected.get("agents", {}).items():
                actual_agent = engine.get_agent(agent_name)
                for field, exp_val in exp_state.items():
                    actual_val = actual_agent.get(field)
                    if actual_val != exp_val:
                        divergences.append((
                            step_data["step"], f"{agent_name}.{field}",
                            exp_val, actual_val
                        ))

            if "blocks" in expected:
                actual_blocks = engine.get_blocks()
                actual_positions = sorted([(b["x"], b["y"], b["type"]) for b in actual_blocks])
                expected_positions = sorted([(b["x"], b["y"], b["type"]) for b in expected["blocks"]])
                if actual_positions != expected_positions:
                    divergences.append((
                        step_data["step"], "block_positions",
                        expected_positions, actual_positions
                    ))

            for team, exp_score in expected.get("scores", {}).items():
                actual_score = engine.get_score(team)
                if actual_score != exp_score:
                    divergences.append((
                        step_data["step"], f"score.{team}",
                        exp_score, actual_score
                    ))

        return divergences

    def test_replay_rotation(self):
        replay = self._load_replay("replay_rotation.json")
        divergences = self._run_replay(replay)
        assert divergences == [], \
            f"Rotation replay divergences: {divergences[:5]}"

    def test_replay_deadline(self):
        replay = self._load_replay("replay_deadline.json")
        divergences = self._run_replay(replay)
        assert divergences == [], \
            f"Deadline replay divergences: {divergences[:5]}"

    def test_replay_connect(self):
        replay = self._load_replay("replay_connect.json")
        divergences = self._run_replay(replay)
        assert divergences == [], \
            f"Connect replay divergences: {divergences[:5]}"

    def test_replay_energy(self):
        replay = self._load_replay("replay_energy.json")
        divergences = self._run_replay(replay)
        assert divergences == [], \
            f"Energy replay divergences: {divergences[:5]}"

    def test_replay_wrapping(self):
        replay = self._load_replay("replay_wrapping.json")
        divergences = self._run_replay(replay)
        assert divergences == [], \
            f"Wrapping replay divergences: {divergences[:5]}"

    def test_replay_workflow(self):
        replay = self._load_replay("replay_workflow.json")
        divergences = self._run_replay(replay)
        assert divergences == [], \
            f"Workflow replay divergences: {divergences[:5]}"

    def test_replay_norms(self):
        replay = self._load_replay("replay_norms.json")
        divergences = self._run_replay(replay)
        assert divergences == [], \
            f"Norms replay divergences: {divergences[:5]}"


# ---------------------------------------------------------------------------
# Grid wrapping
# ---------------------------------------------------------------------------

class TestGridWrapping:
    def test_wrapping_north(self):
        config = make_config(width=10, height=10)
        state = make_state(agents=[
            {"name": "a1", "team": "A", "x": 5, "y": 0, "role": "default", "energy": 100}
        ])
        engine = GameEngine(config, state)
        result = engine.step({"a1": {"type": "move", "p": ["n"]}})
        assert result["a1"]["result"] == "success"
        a = engine.get_agent("a1")
        assert a["x"] == 5
        assert a["y"] == 9

    def test_wrapping_east(self):
        config = make_config(width=10, height=10)
        state = make_state(agents=[
            {"name": "a1", "team": "A", "x": 9, "y": 5, "role": "default", "energy": 100}
        ])
        engine = GameEngine(config, state)
        result = engine.step({"a1": {"type": "move", "p": ["e"]}})
        assert result["a1"]["result"] == "success"
        a = engine.get_agent("a1")
        assert a["x"] == 0
        assert a["y"] == 5


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------

class TestMovement:
    def test_multi_step(self):
        config = make_config()
        state = make_state(agents=[
            {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}
        ])
        engine = GameEngine(config, state)
        result = engine.step({"a1": {"type": "move", "p": ["n", "e"]}})
        assert result["a1"]["result"] == "success"
        a = engine.get_agent("a1")
        assert a["x"] == 6
        assert a["y"] == 4

    def test_blocked_by_obstacle(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}],
            obstacles=[{"x": 5, "y": 4}]
        )
        engine = GameEngine(config, state)
        result = engine.step({"a1": {"type": "move", "p": ["n"]}})
        assert result["a1"]["result"] == "failed_path"
        a = engine.get_agent("a1")
        assert a["x"] == 5 and a["y"] == 5

    def test_speed_zero_fails(self):
        """Speed[2]=0 means no movement with 2 attachments."""
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}],
            blocks=[{"x": 5, "y": 6, "type": "b0"}, {"x": 6, "y": 5, "type": "b1"}]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        engine.step({"a1": {"type": "attach", "p": ["e"]}})
        result = engine.step({"a1": {"type": "move", "p": ["n"]}})
        assert result["a1"]["result"] == "failed_path"

    def test_partial_success(self):
        """First step succeeds, second blocked by obstacle."""
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}],
            obstacles=[{"x": 5, "y": 3}]
        )
        engine = GameEngine(config, state)
        result = engine.step({"a1": {"type": "move", "p": ["n", "n"]}})
        assert result["a1"]["result"] == "partial_success"
        a = engine.get_agent("a1")
        assert a["x"] == 5 and a["y"] == 4


# ---------------------------------------------------------------------------
# Block request and attach
# ---------------------------------------------------------------------------

class TestBlockBasics:
    def test_request_block(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}],
            dispensers=[{"x": 5, "y": 6, "type": "b0"}]
        )
        engine = GameEngine(config, state)
        result = engine.step({"a1": {"type": "request", "p": ["s"]}})
        assert result["a1"]["result"] == "success"
        things = engine.get_things_at(5, 6)
        assert any(t["type"] == "block" and t["details"] == "b0" for t in things)

    def test_request_blocked_cell(self):
        """Request fails when dispenser cell is already occupied."""
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}],
            dispensers=[{"x": 5, "y": 6, "type": "b0"}],
            blocks=[{"x": 5, "y": 6, "type": "b1"}]
        )
        engine = GameEngine(config, state)
        result = engine.step({"a1": {"type": "request", "p": ["s"]}})
        assert result["a1"]["result"] == "failed_blocked"

    def test_attach_and_move(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}],
            blocks=[{"x": 5, "y": 6, "type": "b0"}]
        )
        engine = GameEngine(config, state)
        r = engine.step({"a1": {"type": "attach", "p": ["s"]}})
        assert r["a1"]["result"] == "success"
        r = engine.step({"a1": {"type": "move", "p": ["n"]}})
        assert r["a1"]["result"] == "success"
        a = engine.get_agent("a1")
        assert a["x"] == 5 and a["y"] == 4
        things = engine.get_things_at(5, 5)
        assert any(t["type"] == "block" for t in things)

    def test_attach_nothing(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}]
        )
        engine = GameEngine(config, state)
        r = engine.step({"a1": {"type": "attach", "p": ["s"]}})
        assert r["a1"]["result"] == "failed_target"


# ---------------------------------------------------------------------------
# Rotation transforms
# ---------------------------------------------------------------------------

class TestRotationTransforms:
    def test_cw_block_south_goes_west(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 10, "y": 10, "role": "default", "energy": 100}],
            blocks=[{"x": 10, "y": 11, "type": "b0"}]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        r = engine.step({"a1": {"type": "rotate", "p": ["cw"]}})
        assert r["a1"]["result"] == "success"
        things_west = engine.get_things_at(9, 10)
        assert any(t["type"] == "block" for t in things_west), \
            "Block should be at (9,10) after CW rotation of south block"

    def test_ccw_block_south_goes_east(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 10, "y": 10, "role": "default", "energy": 100}],
            blocks=[{"x": 10, "y": 11, "type": "b0"}]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        r = engine.step({"a1": {"type": "rotate", "p": ["ccw"]}})
        assert r["a1"]["result"] == "success"
        things_east = engine.get_things_at(11, 10)
        assert any(t["type"] == "block" for t in things_east), \
            "Block should be at (11,10) after CCW rotation of south block"

    def test_four_cw_rotations_identity(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 10, "y": 10, "role": "default", "energy": 100}],
            blocks=[{"x": 10, "y": 11, "type": "b0"}]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        for _ in range(4):
            r = engine.step({"a1": {"type": "rotate", "p": ["cw"]}})
            assert r["a1"]["result"] == "success"
        things = engine.get_things_at(10, 11)
        assert any(t["type"] == "block" for t in things)

    def test_cw_ccw_inverse(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 10, "y": 10, "role": "default", "energy": 100}],
            blocks=[{"x": 10, "y": 11, "type": "b0"}]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        engine.step({"a1": {"type": "rotate", "p": ["cw"]}})
        engine.step({"a1": {"type": "rotate", "p": ["ccw"]}})
        things = engine.get_things_at(10, 11)
        assert any(t["type"] == "block" for t in things)

    def test_cw_rotation_blocked_by_obstacle(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 10, "y": 10, "role": "default", "energy": 100}],
            blocks=[{"x": 10, "y": 11, "type": "b0"}],
            obstacles=[{"x": 9, "y": 10}]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        r = engine.step({"a1": {"type": "rotate", "p": ["cw"]}})
        assert r["a1"]["result"] == "failed"
        things = engine.get_things_at(10, 11)
        assert any(t["type"] == "block" for t in things)

    def test_rotation_fails_with_another_agent_attached(self):
        """Rotation should fail when another agent is in the component."""
        config = make_config()
        state = make_state(
            agents=[
                {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100},
                {"name": "a2", "team": "A", "x": 5, "y": 6, "role": "default", "energy": 100}
            ]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        r = engine.step({"a1": {"type": "rotate", "p": ["cw"]}})
        assert r["a1"]["result"] == "failed"


# ---------------------------------------------------------------------------
# Task submission deadline boundary
# ---------------------------------------------------------------------------

class TestTaskDeadline:
    def test_submit_at_exact_deadline(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 3, "y": 3, "role": "default", "energy": 100}],
            blocks=[{"x": 3, "y": 4, "type": "b0"}],
            tasks=[{"name": "task1", "deadline": 1, "reward": 30,
                     "requirements": [{"x": 0, "y": 1, "type": "b0"}]}],
            goalZones=[[3, 3], [3, 4]]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        r = engine.step({"a1": {"type": "submit", "p": ["task1"]}})
        assert r["a1"]["result"] == "success"
        assert engine.get_score("A") == 30

    def test_submit_after_deadline(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 3, "y": 3, "role": "default", "energy": 100}],
            blocks=[{"x": 3, "y": 4, "type": "b0"}],
            tasks=[{"name": "task1", "deadline": 0, "reward": 30,
                     "requirements": [{"x": 0, "y": 1, "type": "b0"}]}],
            goalZones=[[3, 3], [3, 4]]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        r = engine.step({"a1": {"type": "submit", "p": ["task1"]}})
        assert r["a1"]["result"] == "failed_target"
        assert engine.get_score("A") == 0

    def test_submit_wrong_block_type(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 3, "y": 3, "role": "default", "energy": 100}],
            blocks=[{"x": 3, "y": 4, "type": "b1"}],
            tasks=[{"name": "task1", "deadline": 100, "reward": 30,
                     "requirements": [{"x": 0, "y": 1, "type": "b0"}]}],
            goalZones=[[3, 3], [3, 4]]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        r = engine.step({"a1": {"type": "submit", "p": ["task1"]}})
        assert r["a1"]["result"] == "failed"

    def test_submit_not_on_goal_zone(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 3, "y": 3, "role": "default", "energy": 100}],
            blocks=[{"x": 3, "y": 4, "type": "b0"}],
            tasks=[{"name": "task1", "deadline": 100, "reward": 30,
                     "requirements": [{"x": 0, "y": 1, "type": "b0"}]}],
            goalZones=[[10, 10]]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        r = engine.step({"a1": {"type": "submit", "p": ["task1"]}})
        assert r["a1"]["result"] == "failed"


# ---------------------------------------------------------------------------
# Connect edge symmetry
# ---------------------------------------------------------------------------

class TestConnectSymmetry:
    def _connect_roles(self):
        return [
            {
                "name": "default",
                "vision": 5,
                "actions": ["skip", "move", "rotate", "adopt", "request", "attach",
                            "detach", "connect", "disconnect", "submit", "clear", "survey"],
                "speed": [3, 2, 2, 1, 1],
                "clear": {"chance": 1.0, "maxDistance": 2}
            }
        ]

    def test_partner_can_move_merged_component(self):
        config = make_config(roles=self._connect_roles())
        state = make_state(
            agents=[
                {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100},
                {"name": "a2", "team": "A", "x": 5, "y": 8, "role": "default", "energy": 100}
            ],
            blocks=[
                {"x": 5, "y": 6, "type": "b0"},
                {"x": 5, "y": 7, "type": "b1"}
            ]
        )
        engine = GameEngine(config, state)
        engine.step({
            "a1": {"type": "attach", "p": ["s"]},
            "a2": {"type": "attach", "p": ["n"]}
        })
        r = engine.step({
            "a1": {"type": "connect", "p": ["a2", "0", "1"]},
            "a2": {"type": "connect", "p": ["a1", "0", "-1"]}
        })
        assert r["a1"]["result"] == "success"

        r = engine.step({"a2": {"type": "move", "p": ["n"]}})
        assert r["a2"]["result"] == "success"
        a2 = engine.get_agent("a2")
        assert a2["y"] == 7
        a1 = engine.get_agent("a1")
        assert a1["y"] == 4

    def test_component_size_symmetric(self):
        config = make_config(roles=self._connect_roles())
        state = make_state(
            agents=[
                {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100},
                {"name": "a2", "team": "A", "x": 5, "y": 8, "role": "default", "energy": 100}
            ],
            blocks=[
                {"x": 5, "y": 6, "type": "b0"},
                {"x": 5, "y": 7, "type": "b1"}
            ]
        )
        engine = GameEngine(config, state)
        engine.step({
            "a1": {"type": "attach", "p": ["s"]},
            "a2": {"type": "attach", "p": ["n"]}
        })
        engine.step({
            "a1": {"type": "connect", "p": ["a2", "0", "1"]},
            "a2": {"type": "connect", "p": ["a1", "0", "-1"]}
        })
        a1 = engine.get_agent("a1")
        a2 = engine.get_agent("a2")
        assert len(a1["attached"]) == 3
        assert len(a2["attached"]) == 3


# ---------------------------------------------------------------------------
# Norm violation deactivation
# ---------------------------------------------------------------------------

class TestNormDeactivation:
    def test_carry_violation_immediate_deactivation(self):
        config = make_config(maxEnergy=100, stepRecharge=0)
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 10}],
            blocks=[
                {"x": 5, "y": 6, "type": "b0"},
                {"x": 6, "y": 5, "type": "b1"}
            ],
            norms=[{
                "name": "n1", "start": 0, "until": 100,
                "level": "individual",
                "requirements": [{"type": "block", "name": "any", "quantity": 1}],
                "punishment": 15
            }]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        a1 = engine.get_agent("a1")
        assert a1["energy"] == 10

        engine.step({"a1": {"type": "attach", "p": ["e"]}})
        a1 = engine.get_agent("a1")
        assert a1["deactivated"] is True
        assert a1["energy"] == 0

    def test_carry_violation_no_deactivation_above_zero(self):
        config = make_config(maxEnergy=100, stepRecharge=0)
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}],
            blocks=[
                {"x": 5, "y": 6, "type": "b0"},
                {"x": 6, "y": 5, "type": "b1"}
            ],
            norms=[{
                "name": "n1", "start": 0, "until": 100,
                "level": "individual",
                "requirements": [{"type": "block", "name": "any", "quantity": 1}],
                "punishment": 10
            }]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        engine.step({"a1": {"type": "attach", "p": ["e"]}})
        a1 = engine.get_agent("a1")
        assert a1["deactivated"] is False
        assert a1["energy"] == 90


# ---------------------------------------------------------------------------
# Energy lifecycle
# ---------------------------------------------------------------------------

class TestEnergyLifecycle:
    def test_no_recharge_while_deactivated(self):
        config = make_config(
            maxEnergy=100, stepRecharge=5,
            deactivatedDuration=3, refreshEnergy=50,
            clearDamage=[0, 100]
        )
        state = make_state(agents=[
            {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 20},
            {"name": "a2", "team": "B", "x": 5, "y": 6, "role": "default", "energy": 100}
        ])
        engine = GameEngine(config, state)

        engine.step({
            "a1": {"type": "skip", "p": []},
            "a2": {"type": "clear", "p": ["0", "-1"]}
        })
        a1 = engine.get_agent("a1")
        assert a1["deactivated"] is True

        engine.step({"a1": {"type": "skip", "p": []}})
        a1 = engine.get_agent("a1")
        assert a1["deactivated"] is True
        assert a1["energy"] == 0

    def test_exact_refresh_energy_on_reactivation(self):
        config = make_config(
            maxEnergy=100, stepRecharge=5,
            deactivatedDuration=2, refreshEnergy=50,
            clearDamage=[0, 100]
        )
        state = make_state(agents=[
            {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 20},
            {"name": "a2", "team": "B", "x": 5, "y": 6, "role": "default", "energy": 100}
        ])
        engine = GameEngine(config, state)

        engine.step({
            "a1": {"type": "skip", "p": []},
            "a2": {"type": "clear", "p": ["0", "-1"]}
        })
        engine.step({"a1": {"type": "skip", "p": []}})

        a1 = engine.get_agent("a1")
        assert a1["deactivated"] is False
        assert a1["energy"] == 50

    def test_energy_capped_at_max(self):
        config = make_config(maxEnergy=100, stepRecharge=5)
        state = make_state(agents=[
            {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 98}
        ])
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "skip", "p": []}})
        a1 = engine.get_agent("a1")
        assert a1["energy"] == 100  # 98+5=103 capped to 100


# ---------------------------------------------------------------------------
# Detach and disconnect
# ---------------------------------------------------------------------------

class TestDetachDisconnect:
    def test_detach_releases_block(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}],
            blocks=[{"x": 5, "y": 6, "type": "b0"}]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        a = engine.get_agent("a1")
        assert len(a["attached"]) == 1

        engine.step({"a1": {"type": "detach", "p": ["s"]}})
        a = engine.get_agent("a1")
        assert len(a["attached"]) == 0
        # Block remains on grid
        things = engine.get_things_at(5, 6)
        assert any(t["type"] == "block" for t in things)

    def test_detach_no_attachment(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}],
            blocks=[{"x": 5, "y": 6, "type": "b0"}]
        )
        engine = GameEngine(config, state)
        r = engine.step({"a1": {"type": "detach", "p": ["s"]}})
        assert r["a1"]["result"] == "failed"


# ---------------------------------------------------------------------------
# Deactivated agents
# ---------------------------------------------------------------------------

class TestDeactivatedAgents:
    def test_deactivated_actions_fail(self):
        config = make_config(
            maxEnergy=100, stepRecharge=0,
            deactivatedDuration=5, clearDamage=[0, 100]
        )
        state = make_state(agents=[
            {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 20},
            {"name": "a2", "team": "B", "x": 5, "y": 6, "role": "default", "energy": 100}
        ])
        engine = GameEngine(config, state)
        engine.step({
            "a1": {"type": "skip", "p": []},
            "a2": {"type": "clear", "p": ["0", "-1"]}
        })
        r = engine.step({"a1": {"type": "move", "p": ["n"]}})
        assert r["a1"]["result"] == "failed_status"


# ---------------------------------------------------------------------------
# Role permission checks
# ---------------------------------------------------------------------------

class TestRolePermissions:
    def test_action_not_in_role(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "explorer", "energy": 100}],
            dispensers=[{"x": 5, "y": 6, "type": "b0"}]
        )
        engine = GameEngine(config, state)
        r = engine.step({"a1": {"type": "request", "p": ["s"]}})
        assert r["a1"]["result"] == "failed_role"

    def test_unknown_action(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}]
        )
        engine = GameEngine(config, state)
        r = engine.step({"a1": {"type": "fly", "p": []}})
        assert r["a1"]["result"] == "unknown_action"


# ---------------------------------------------------------------------------
# Action ordering
# ---------------------------------------------------------------------------

class TestActionOrdering:
    def test_attach_before_move(self):
        """Attach is processed before move in action order. So if a1 attaches
        a block and a2 tries to move to the block's cell, a1's attach should
        process first (attach at index 5, move at index 10)."""
        config = make_config()
        state = make_state(
            agents=[
                {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100},
                {"name": "a2", "team": "A", "x": 5, "y": 7, "role": "default", "energy": 100}
            ],
            blocks=[{"x": 5, "y": 6, "type": "b0"}]
        )
        engine = GameEngine(config, state)
        result = engine.step({
            "a1": {"type": "attach", "p": ["s"]},
            "a2": {"type": "move", "p": ["n"]}
        })
        assert result["a1"]["result"] == "success"
        # a2 tries to move to (5,6) where block is — block is part of a1's
        # component now, so a2 is blocked
        assert result["a2"]["result"] == "failed_path"

    def test_clear_before_request(self):
        """Clear action (index 3) removes obstacle before request (index 4)."""
        config = make_config()
        state = make_state(
            agents=[
                {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100},
                {"name": "a2", "team": "A", "x": 7, "y": 5, "role": "default", "energy": 100}
            ],
            dispensers=[{"x": 6, "y": 5, "type": "b0"}],
            obstacles=[{"x": 6, "y": 5}]
        )
        engine = GameEngine(config, state)
        result = engine.step({
            "a1": {"type": "clear", "p": ["1", "0"]},
            "a2": {"type": "request", "p": ["w"]}
        })
        assert result["a1"]["result"] == "success"
        # Clear removes obstacle at (6,5), then request can succeed
        assert result["a2"]["result"] == "success"


# ---------------------------------------------------------------------------
# Step counter and get_step
# ---------------------------------------------------------------------------

class TestStepCounter:
    def test_step_increments(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}]
        )
        engine = GameEngine(config, state)
        assert engine.get_step() == 0
        engine.step({"a1": {"type": "skip", "p": []}})
        assert engine.get_step() == 1
        engine.step({"a1": {"type": "skip", "p": []}})
        assert engine.get_step() == 2


# ---------------------------------------------------------------------------
# Clear action
# ---------------------------------------------------------------------------

class TestClearAction:
    def test_clear_removes_obstacle(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}],
            obstacles=[{"x": 6, "y": 5}]
        )
        engine = GameEngine(config, state)
        r = engine.step({"a1": {"type": "clear", "p": ["1", "0"]}})
        assert r["a1"]["result"] == "success"
        things = engine.get_things_at(6, 5)
        assert not any(t["type"] == "obstacle" for t in things)
        a = engine.get_agent("a1")
        assert a["energy"] == 100 - 2 + 1  # -clearEnergyCost + stepRecharge

    def test_clear_not_enough_energy(self):
        config = make_config(clearEnergyCost=50)
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 10}],
            obstacles=[{"x": 6, "y": 5}]
        )
        engine = GameEngine(config, state)
        r = engine.step({"a1": {"type": "clear", "p": ["1", "0"]}})
        assert r["a1"]["result"] == "failed_resources"

    def test_clear_damages_entity(self):
        config = make_config(clearDamage=[0, 30])
        state = make_state(agents=[
            {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100},
            {"name": "a2", "team": "B", "x": 6, "y": 5, "role": "default", "energy": 50}
        ])
        engine = GameEngine(config, state)
        r = engine.step({"a1": {"type": "clear", "p": ["1", "0"]}})
        assert r["a1"]["result"] == "success"
        a2 = engine.get_agent("a2")
        assert a2["energy"] == 50 - 30 + 1  # damage + recharge


# ---------------------------------------------------------------------------
# Adopt action
# ---------------------------------------------------------------------------

class TestAdoptAction:
    def test_adopt_on_role_zone(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 10, "y": 10, "role": "default", "energy": 100}],
            roleZones=[[10, 10]]
        )
        engine = GameEngine(config, state)
        r = engine.step({"a1": {"type": "adopt", "p": ["explorer"]}})
        assert r["a1"]["result"] == "success"
        a = engine.get_agent("a1")
        assert a["role"] == "explorer"

    def test_adopt_not_on_role_zone(self):
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}],
            roleZones=[[10, 10]]
        )
        engine = GameEngine(config, state)
        r = engine.step({"a1": {"type": "adopt", "p": ["explorer"]}})
        assert r["a1"]["result"] == "failed_location"


# ---------------------------------------------------------------------------
# Implicit skip for missing agents
# ---------------------------------------------------------------------------

class TestImplicitSkip:
    def test_missing_agent_skips(self):
        config = make_config()
        state = make_state(agents=[
            {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100},
            {"name": "a2", "team": "A", "x": 10, "y": 10, "role": "default", "energy": 100}
        ])
        engine = GameEngine(config, state)
        result = engine.step({"a1": {"type": "move", "p": ["n"]}})
        assert "a2" in result
        assert result["a2"]["result"] == "success"


# ---------------------------------------------------------------------------
# Behavioral specification validation
# ---------------------------------------------------------------------------

class TestBehavioralSpec:
    """Validate the behavioral specification document produced by the solver."""

    def _load(self):
        with open("/app/behavioral_spec.json") as f:
            return json.load(f)

    def test_spec_file_exists(self):
        assert os.path.exists("/app/behavioral_spec.json"), \
            "behavioral_spec.json must be created at /app/behavioral_spec.json"

    def test_rotation_cw_direction(self):
        spec = self._load()
        val = spec["rotation"]["cw_south_block_direction"].lower().strip()
        assert val in ("west", "w"), \
            f"CW rotation of south block should move it west, got '{val}'"

    def test_rotation_ccw_direction(self):
        spec = self._load()
        val = spec["rotation"]["ccw_south_block_direction"].lower().strip()
        assert val in ("east", "e"), \
            f"CCW rotation of south block should move it east, got '{val}'"

    def test_deadline_semantics(self):
        spec = self._load()
        val = spec["task_deadline"]["submit_at_exact_deadline_step"].lower().strip()
        assert val in ("allowed", "yes", "true", "permitted", "inclusive"), \
            f"Submit at exact deadline step should be 'allowed', got '{val}'"

    def test_connect_edge_type(self):
        spec = self._load()
        val = spec["connect_action"]["edge_directionality"].lower().strip()
        assert val in ("bidirectional", "symmetric", "undirected"), \
            f"Connect edges should be 'bidirectional', got '{val}'"

    def test_energy_deactivated_no_recharge(self):
        spec = self._load()
        val = spec["energy_lifecycle"]["recharge_while_deactivated"]
        if isinstance(val, str):
            val = val.lower().strip() in ("true", "yes", "1")
        assert val is False or val == 0, \
            "Deactivated agents must NOT receive step recharge"

    def test_energy_reactivation_param(self):
        spec = self._load()
        val = spec["energy_lifecycle"]["reactivation_energy_source"].lower().strip()
        assert "refresh" in val, \
            f"Reactivation energy source should reference refreshEnergy, got '{val}'"

    def test_norm_enforcement_ordering(self):
        spec = self._load()
        val = spec["norm_enforcement"]["order"].lower().strip().replace(" ", "_")
        assert any(v in val for v in ("penalty_then", "penalty_first", "penalty_before")), \
            f"Norm enforcement should apply penalty before deactivation check, got '{val}'"

    def test_unknown_action_code(self):
        spec = self._load()
        val = spec["action_dispatch"]["unknown_action_result_code"].lower().strip()
        assert val == "unknown_action", \
            f"Unknown action result should be 'unknown_action', got '{val}'"


# ---------------------------------------------------------------------------
# Behavioral spec / engine consistency checks
# ---------------------------------------------------------------------------

class TestSpecEngineConsistency:
    """Verify behavioral spec claims match actual engine behavior."""

    def _load(self):
        with open("/app/behavioral_spec.json") as f:
            return json.load(f)

    def test_rotation_spec_matches_engine(self):
        spec = self._load()
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 10, "y": 10,
                     "role": "default", "energy": 100}],
            blocks=[{"x": 10, "y": 11, "type": "b0"}]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        engine.step({"a1": {"type": "rotate", "p": ["cw"]}})

        cw_dir = spec["rotation"]["cw_south_block_direction"].lower().strip()
        pos = {"west": (9, 10), "w": (9, 10),
               "east": (11, 10), "e": (11, 10)}.get(cw_dir)
        assert pos is not None, f"Invalid direction in spec: {cw_dir}"
        things = engine.get_things_at(*pos)
        assert any(t["type"] == "block" for t in things), \
            f"Spec says CW south block goes {cw_dir}, but engine shows no block at {pos}"

    def test_deadline_spec_matches_engine(self):
        spec = self._load()
        config = make_config()
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 3, "y": 3,
                     "role": "default", "energy": 100}],
            blocks=[{"x": 3, "y": 4, "type": "b0"}],
            tasks=[{"name": "t1", "deadline": 1, "reward": 10,
                     "requirements": [{"x": 0, "y": 1, "type": "b0"}]}],
            goalZones=[[3, 3], [3, 4]]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        r = engine.step({"a1": {"type": "submit", "p": ["t1"]}})
        val = spec["task_deadline"]["submit_at_exact_deadline_step"].lower().strip()
        if val in ("allowed", "yes", "true", "permitted", "inclusive"):
            assert r["a1"]["result"] == "success", \
                "Spec says submit at deadline is allowed, but engine rejected it"
        else:
            assert r["a1"]["result"] != "success", \
                "Spec says submit at deadline is rejected, but engine allowed it"

    def test_norm_spec_matches_engine(self):
        spec = self._load()
        config = make_config(maxEnergy=100, stepRecharge=0)
        state = make_state(
            agents=[{"name": "a1", "team": "A", "x": 5, "y": 5,
                     "role": "default", "energy": 10}],
            blocks=[{"x": 5, "y": 6, "type": "b0"},
                    {"x": 6, "y": 5, "type": "b1"}],
            norms=[{"name": "n1", "start": 0, "until": 100,
                    "level": "individual",
                    "requirements": [{"type": "block", "name": "any",
                                     "quantity": 1}],
                    "punishment": 15}]
        )
        engine = GameEngine(config, state)
        engine.step({"a1": {"type": "attach", "p": ["s"]}})
        engine.step({"a1": {"type": "attach", "p": ["e"]}})
        a1 = engine.get_agent("a1")
        val = spec["norm_enforcement"]["order"].lower()
        if any(v in val for v in ("penalty_then", "penalty_first", "penalty_before")):
            assert a1["deactivated"] is True, \
                "Spec says penalty-first (agent should deactivate), but agent is active"
        else:
            assert a1["deactivated"] is False, \
                "Spec says check-first (agent should stay active), but agent is deactivated"
