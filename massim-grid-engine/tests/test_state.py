
"""
Tests for the MASSim simulation replay pipeline.
Verifies config resolution, SQLite replay schema, game mechanics correctness,
norm violation detection, energy tracking, and final results.
"""

import json
import os
import sqlite3

import pytest


# ---------------------------------------------------------------------------
# 1. Configuration resolution
# ---------------------------------------------------------------------------

class TestConfigResolution:
    """Verify jq-based include resolution produces correct merged JSON."""

    def test_resolved_config_exists(self):
        assert os.path.exists("/app/resolved_config.json"), \
            "resolved_config.json must exist after running resolve_config.sh"

    def test_roles_resolved_to_array(self):
        with open("/app/resolved_config.json") as f:
            cfg = json.load(f)
        roles = cfg["match"]["roles"]
        assert isinstance(roles, list), "roles must be a JSON array, not a string reference"
        assert len(roles) == 3

    def test_role_names(self):
        with open("/app/resolved_config.json") as f:
            cfg = json.load(f)
        names = {r["name"] for r in cfg["match"]["roles"]}
        assert names == {"default", "explorer", "worker"}

    def test_regulation_resolved_to_object(self):
        with open("/app/resolved_config.json") as f:
            cfg = json.load(f)
        reg = cfg["match"]["regulation"]
        assert isinstance(reg, dict), "regulation must be a JSON object, not a string reference"
        assert "subjects" in reg
        assert len(reg["subjects"]) == 2

    def test_no_unresolved_references(self):
        with open("/app/resolved_config.json") as f:
            text = f.read()
        assert "$(" not in text, "All $(path) references must be fully resolved"


# ---------------------------------------------------------------------------
# 2. SQLite replay database schema
# ---------------------------------------------------------------------------

class TestDatabaseSchema:
    """Verify the replay database has the required tables and columns."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect("/app/replay.db")
        yield conn
        conn.close()

    def test_replay_db_exists(self):
        assert os.path.exists("/app/replay.db")

    def test_agent_states_columns(self, db):
        cur = db.execute("SELECT * FROM agent_states LIMIT 1")
        cols = {d[0] for d in cur.description}
        for c in ("step", "agent_name", "x", "y", "energy", "role",
                  "deactivated", "num_attachments"):
            assert c in cols, f"agent_states missing column: {c}"

    def test_block_states_columns(self, db):
        cur = db.execute("SELECT * FROM block_states LIMIT 1")
        cols = {d[0] for d in cur.description}
        for c in ("step", "block_id", "block_type", "x", "y"):
            assert c in cols, f"block_states missing column: {c}"

    def test_action_results_columns(self, db):
        cur = db.execute("SELECT * FROM action_results LIMIT 1")
        cols = {d[0] for d in cur.description}
        for c in ("step", "agent_name", "action", "result"):
            assert c in cols, f"action_results missing column: {c}"

    def test_norm_violations_columns(self, db):
        cur = db.execute("SELECT * FROM norm_violations LIMIT 0")
        cols = {d[0] for d in cur.description}
        for c in ("step", "agent_name", "norm_name"):
            assert c in cols, f"norm_violations missing column: {c}"

    def test_scores_columns(self, db):
        cur = db.execute("SELECT * FROM scores LIMIT 1")
        cols = {d[0] for d in cur.description}
        for c in ("step", "team", "score"):
            assert c in cols, f"scores missing column: {c}"


# ---------------------------------------------------------------------------
# 3. Attachment mechanics and task submission
# ---------------------------------------------------------------------------

class TestAttachAndSubmit:
    """Verify attachment creation and multi-block task submission."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect("/app/replay.db")
        yield conn
        conn.close()

    def test_single_attach(self, db):
        row = db.execute(
            "SELECT num_attachments FROM agent_states "
            "WHERE step=1 AND agent_name='agentA0'"
        ).fetchone()
        assert row is not None
        assert row[0] == 1, "After attach s, agentA0 should have 1 attachment"

    def test_double_attach(self, db):
        row = db.execute(
            "SELECT num_attachments FROM agent_states "
            "WHERE step=2 AND agent_name='agentA0'"
        ).fetchone()
        assert row is not None
        assert row[0] == 2, "After second attach, agentA0 should have 2 attachments"

    def test_task1_submission_succeeds(self, db):
        row = db.execute(
            "SELECT result FROM action_results "
            "WHERE step=3 AND agent_name='agentA0'"
        ).fetchone()
        assert row is not None
        assert row[0] == "success", "task1 submission should succeed (both blocks attached at correct positions in goal zone)"

    def test_score_after_task1(self, db):
        row = db.execute(
            "SELECT score FROM scores WHERE step=3 AND team='A'"
        ).fetchone()
        assert row is not None
        assert row[0] == 50, "Score should be 50 after task1 (reward=50)"


# ---------------------------------------------------------------------------
# 4. Rotation mechanics
# ---------------------------------------------------------------------------

class TestRotation:
    """Verify CW/CCW rotation transforms with toroidal wrapping."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect("/app/replay.db")
        yield conn
        conn.close()

    def test_cw_rotation_block0(self, db):
        # Step 4: B0 at (10,11) relative (0,1) CW→(-1,0) → absolute (9,10)
        row = db.execute(
            "SELECT x, y FROM block_states "
            "WHERE step=4 AND block_id='block_0'"
        ).fetchone()
        assert row == (9, 10), f"block_0 after CW rotation should be at (9,10), got {row}"

    def test_cw_rotation_block1(self, db):
        # Step 4: B1 at (11,10) relative (1,0) CW→(0,1) → absolute (10,11)
        row = db.execute(
            "SELECT x, y FROM block_states "
            "WHERE step=4 AND block_id='block_1'"
        ).fetchone()
        assert row == (10, 11), f"block_1 after CW rotation should be at (10,11), got {row}"

    def test_ccw_rotation(self, db):
        # Step 8: B1 at (10,10) relative (0,1) from A0(10,9), CCW→(1,0) → (11,9)
        row = db.execute(
            "SELECT x, y FROM block_states "
            "WHERE step=8 AND block_id='block_1'"
        ).fetchone()
        assert row == (11, 9), f"block_1 after CCW rotation should be at (11,9), got {row}"

    def test_block_returns_after_move_rotate(self, db):
        # Step 9: A0 moves south, B1 follows → (11,10)
        row = db.execute(
            "SELECT x, y FROM block_states "
            "WHERE step=9 AND block_id='block_1'"
        ).fetchone()
        assert row == (11, 10), f"block_1 after move south should be at (11,10), got {row}"


# ---------------------------------------------------------------------------
# 5. Movement and speed limits
# ---------------------------------------------------------------------------

class TestMovementSpeed:
    """Verify movement with role-based speed constraints."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect("/app/replay.db")
        yield conn
        conn.close()

    def test_overloaded_fails(self, db):
        # Step 5: A0 has 2 att, default speed[2]=0, move should fail
        row = db.execute(
            "SELECT result FROM action_results "
            "WHERE step=5 AND agent_name='agentA0'"
        ).fetchone()
        assert row is not None
        assert row[0] == "failed_path", "Movement with speed=0 should return failed_path"

    def test_worker_double_move_succeeds(self, db):
        # Step 4: A1 (worker) with 1 att, speed[1]=2, move n,n → success
        row = db.execute(
            "SELECT result FROM action_results "
            "WHERE step=4 AND agent_name='agentA1'"
        ).fetchone()
        assert row is not None
        assert row[0] == "success", "Worker with speed=2 should move twice successfully"

    def test_worker_position_after_double_move(self, db):
        # Step 4: A1 from (20,19) moves n,n → (20,17)
        row = db.execute(
            "SELECT x, y FROM agent_states "
            "WHERE step=4 AND agent_name='agentA1'"
        ).fetchone()
        assert row == (20, 17), f"agentA1 after n,n should be at (20,17), got {row}"

    def test_partial_success(self, db):
        # Step 7: A0 has 1 att, default speed[1]=1, move n,n → partial_success
        row = db.execute(
            "SELECT result FROM action_results "
            "WHERE step=7 AND agent_name='agentA0'"
        ).fetchone()
        assert row is not None
        assert row[0] == "partial_success", \
            "1 attachment with speed[1]=1 and 2 moves requested should yield partial_success"

    def test_position_after_partial_move(self, db):
        # Step 7: A0 from (10,10) moves n (only 1 step) → (10,9)
        row = db.execute(
            "SELECT x, y FROM agent_states "
            "WHERE step=7 AND agent_name='agentA0'"
        ).fetchone()
        assert row == (10, 9), f"agentA0 after partial move should be at (10,9), got {row}"


# ---------------------------------------------------------------------------
# 6. Norm violations and energy penalties
# ---------------------------------------------------------------------------

class TestNormViolations:
    """Verify carry norm detection, energy penalties, and temporal window."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect("/app/replay.db")
        yield conn
        conn.close()

    def test_violation_at_step6(self, db):
        row = db.execute(
            "SELECT norm_name FROM norm_violations "
            "WHERE step=6 AND agent_name='agentA0'"
        ).fetchone()
        assert row is not None, "agentA0 should violate norm_carry1 at step 6 (2 att > max 1)"
        assert row[0] == "norm_carry1"

    def test_no_violation_for_compliant_agent(self, db):
        cnt = db.execute(
            "SELECT COUNT(*) FROM norm_violations WHERE agent_name='agentA1'"
        ).fetchone()[0]
        assert cnt == 0, "agentA1 (1 att ≤ max 1) should never violate norm_carry1"

    def test_energy_penalty(self, db):
        row = db.execute(
            "SELECT energy FROM agent_states "
            "WHERE step=6 AND agent_name='agentA0'"
        ).fetchone()
        assert row is not None
        assert row[0] == 85, "Energy should be 100 - 15 (punishment) = 85 at step 6"

    def test_no_violation_before_norm_start(self, db):
        cnt = db.execute(
            "SELECT COUNT(*) FROM norm_violations WHERE step < 6"
        ).fetchone()[0]
        assert cnt == 0, "No violations should occur before norm start step 6"

    def test_no_violation_after_detach(self, db):
        cnt = db.execute(
            "SELECT COUNT(*) FROM norm_violations "
            "WHERE step > 6 AND agent_name='agentA0'"
        ).fetchone()[0]
        assert cnt == 0, "After detaching to 1 att, no carry violation should occur"

    def test_attachment_count_after_detach(self, db):
        row = db.execute(
            "SELECT num_attachments FROM agent_states "
            "WHERE step=6 AND agent_name='agentA0'"
        ).fetchone()
        assert row is not None
        assert row[0] == 1, "After detach at step 6, agentA0 should have 1 attachment"


# ---------------------------------------------------------------------------
# 7. Energy recharge tracking
# ---------------------------------------------------------------------------

class TestEnergyRecharge:
    """Verify per-step energy recharge after norm penalty."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect("/app/replay.db")
        yield conn
        conn.close()

    def test_recharge_step7(self, db):
        row = db.execute(
            "SELECT energy FROM agent_states "
            "WHERE step=7 AND agent_name='agentA0'"
        ).fetchone()
        assert row[0] == 86, "Energy should be 85 + 1 (recharge) = 86 at step 7"

    def test_recharge_step8(self, db):
        row = db.execute(
            "SELECT energy FROM agent_states "
            "WHERE step=8 AND agent_name='agentA0'"
        ).fetchone()
        assert row[0] == 87, "Energy should be 86 + 1 = 87 at step 8"

    def test_recharge_step10(self, db):
        row = db.execute(
            "SELECT energy FROM agent_states "
            "WHERE step=10 AND agent_name='agentA0'"
        ).fetchone()
        assert row[0] == 89, "Energy should be 88 + 1 = 89 at step 10"


# ---------------------------------------------------------------------------
# 8. Second submission and final results
# ---------------------------------------------------------------------------

class TestFinalResults:
    """Verify second task submission and end-to-end results."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect("/app/replay.db")
        yield conn
        conn.close()

    def test_task2_submission(self, db):
        row = db.execute(
            "SELECT result FROM action_results "
            "WHERE step=10 AND agent_name='agentA0'"
        ).fetchone()
        assert row is not None
        assert row[0] == "success", "task2 submission should succeed at step 10"

    def test_final_score_in_db(self, db):
        row = db.execute(
            "SELECT score FROM scores WHERE step=10 AND team='A'"
        ).fetchone()
        assert row is not None
        assert row[0] == 80, "Final score should be 50 + 30 = 80"

    def test_results_json_exists(self):
        assert os.path.exists("/app/results.json")

    def test_results_json_content(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        assert results["teams"]["A"] == 80, "results.json must report team A score = 80"
        assert results["steps_played"] == 10, "results.json must report 10 steps played"
