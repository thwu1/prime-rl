
import json
import os
import sqlite3
import pytest


DB_PATH = "/app/games.db"


@pytest.fixture(scope="session")
def db():
    assert os.path.exists(DB_PATH), f"Database not found at {DB_PATH}"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchema:
    def test_sprites_table(self, db):
        rows = db.execute(
            "SELECT game, name, parent, base_class, is_leaf FROM sprites LIMIT 1"
        ).fetchall()
        assert rows is not None

    def test_sprite_params_table(self, db):
        rows = db.execute(
            "SELECT game, sprite, key, value FROM sprite_params LIMIT 1"
        ).fetchall()
        assert rows is not None

    def test_interactions_table(self, db):
        rows = db.execute(
            "SELECT game, idx, sprite1, sprite2_csv, effect, params_json "
            "FROM interactions LIMIT 1"
        ).fetchall()
        assert rows is not None

    def test_terminations_table(self, db):
        rows = db.execute(
            "SELECT game, idx, term_type, win, params_json "
            "FROM terminations LIMIT 1"
        ).fetchall()
        assert rows is not None

    def test_level_dims_table(self, db):
        rows = db.execute(
            "SELECT game, level, rows, cols FROM level_dims LIMIT 1"
        ).fetchall()
        assert rows is not None

    def test_level_sprite_counts_table(self, db):
        rows = db.execute(
            "SELECT game, level, sprite, count FROM level_sprite_counts LIMIT 1"
        ).fetchall()
        assert rows is not None

    def test_winnability_table(self, db):
        rows = db.execute(
            "SELECT game, level, winnable, reason FROM winnability LIMIT 1"
        ).fetchall()
        assert rows is not None

    def test_all_six_games_present(self, db):
        games = {r[0] for r in db.execute(
            "SELECT DISTINCT game FROM sprites"
        ).fetchall()}
        for g in ("zelda", "aliens", "sokoban", "chipschallenge",
                   "firecaster", "lemmings"):
            assert g in games, f"Game '{g}' missing from sprites table"


# ---------------------------------------------------------------------------
# Zelda sprite hierarchy
# ---------------------------------------------------------------------------

class TestZeldaHierarchy:
    def _q(self, db, name):
        row = db.execute(
            "SELECT parent, base_class, is_leaf FROM sprites "
            "WHERE game='zelda' AND name=?", (name,)
        ).fetchone()
        assert row is not None, f"Sprite '{name}' not found for zelda"
        return row

    def test_nokey_class(self, db):
        assert self._q(db, "nokey")["base_class"] == "ShootAvatar"

    def test_withkey_class(self, db):
        assert self._q(db, "withkey")["base_class"] == "ShootAvatar"

    def test_nokey_parent(self, db):
        assert self._q(db, "nokey")["parent"] == "avatar"

    def test_avatar_parent(self, db):
        assert self._q(db, "avatar")["parent"] == "movable"

    def test_movable_is_root(self, db):
        assert self._q(db, "movable")["parent"] is None

    def test_movable_no_class(self, db):
        assert self._q(db, "movable")["base_class"] is None

    def test_monsterQuick_class(self, db):
        assert self._q(db, "monsterQuick")["base_class"] == "RandomNPC"

    def test_monsterNormal_class(self, db):
        assert self._q(db, "monsterNormal")["base_class"] == "RandomNPC"

    def test_enemy_not_leaf(self, db):
        assert self._q(db, "enemy")["is_leaf"] == 0

    def test_nokey_is_leaf(self, db):
        assert self._q(db, "nokey")["is_leaf"] == 1

    def test_wall_class(self, db):
        assert self._q(db, "wall")["base_class"] == "Immovable"

    def test_sword_class(self, db):
        assert self._q(db, "sword")["base_class"] == "OrientedFlicker"

    def test_goal_class(self, db):
        assert self._q(db, "goal")["base_class"] == "Door"

    def test_movable_children(self, db):
        rows = db.execute(
            "SELECT name FROM sprites "
            "WHERE game='zelda' AND parent='movable' ORDER BY name"
        ).fetchall()
        names = [r[0] for r in rows]
        assert names == ["avatar", "enemy", "wall"]


# ---------------------------------------------------------------------------
# Zelda sprite params
# ---------------------------------------------------------------------------

class TestZeldaParams:
    def test_nokey_inherits_stype(self, db):
        row = db.execute(
            "SELECT value FROM sprite_params "
            "WHERE game='zelda' AND sprite='nokey' AND key='stype'"
        ).fetchone()
        assert row is not None and row[0] == "sword"

    def test_nokey_inherits_frameRate(self, db):
        row = db.execute(
            "SELECT value FROM sprite_params "
            "WHERE game='zelda' AND sprite='nokey' AND key='frameRate'"
        ).fetchone()
        assert row is not None and row[0] == "8"


# ---------------------------------------------------------------------------
# Zelda level analysis
# ---------------------------------------------------------------------------

class TestZeldaLevel:
    def test_zelda_0_dims(self, db):
        row = db.execute(
            "SELECT rows, cols FROM level_dims "
            "WHERE game='zelda' AND level='zelda_0'"
        ).fetchone()
        assert row is not None
        assert row["rows"] == 9
        assert row["cols"] == 13

    def test_zelda_0_wall_count(self, db):
        row = db.execute(
            "SELECT count FROM level_sprite_counts "
            "WHERE game='zelda' AND level='zelda_0' AND sprite='wall'"
        ).fetchone()
        assert row is not None and row[0] == 53

    def test_zelda_0_nokey_count(self, db):
        row = db.execute(
            "SELECT count FROM level_sprite_counts "
            "WHERE game='zelda' AND level='zelda_0' AND sprite='nokey'"
        ).fetchone()
        assert row is not None and row[0] == 1

    def test_zelda_0_key_count(self, db):
        row = db.execute(
            "SELECT count FROM level_sprite_counts "
            "WHERE game='zelda' AND level='zelda_0' AND sprite='key'"
        ).fetchone()
        assert row is not None and row[0] == 1

    def test_zelda_0_monsterNormal_count(self, db):
        row = db.execute(
            "SELECT count FROM level_sprite_counts "
            "WHERE game='zelda' AND level='zelda_0' AND sprite='monsterNormal'"
        ).fetchone()
        assert row is not None and row[0] == 3

    def test_zelda_0_goal_count(self, db):
        row = db.execute(
            "SELECT count FROM level_sprite_counts "
            "WHERE game='zelda' AND level='zelda_0' AND sprite='goal'"
        ).fetchone()
        assert row is not None and row[0] == 1


# ---------------------------------------------------------------------------
# Zelda interactions
# ---------------------------------------------------------------------------

class TestZeldaInteractions:
    def test_interaction_count(self, db):
        row = db.execute(
            "SELECT COUNT(*) FROM interactions WHERE game='zelda'"
        ).fetchone()
        assert row[0] == 7

    def test_has_transformTo(self, db):
        row = db.execute(
            "SELECT COUNT(*) FROM interactions "
            "WHERE game='zelda' AND effect='transformTo'"
        ).fetchone()
        assert row[0] >= 1

    def test_transformTo_params(self, db):
        row = db.execute(
            "SELECT params_json FROM interactions "
            "WHERE game='zelda' AND effect='transformTo'"
        ).fetchone()
        params = json.loads(row[0])
        assert params.get("stype") == "withkey"


# ---------------------------------------------------------------------------
# Zelda terminations
# ---------------------------------------------------------------------------

class TestZeldaTerminations:
    def test_termination_count(self, db):
        row = db.execute(
            "SELECT COUNT(*) FROM terminations WHERE game='zelda'"
        ).fetchone()
        assert row[0] == 2

    def test_has_win_condition(self, db):
        row = db.execute(
            "SELECT term_type FROM terminations "
            "WHERE game='zelda' AND win=1"
        ).fetchone()
        assert row is not None
        assert row[0] == "SpriteCounter"


# ---------------------------------------------------------------------------
# Zelda winnability
# ---------------------------------------------------------------------------

class TestZeldaWinnability:
    def test_zelda_0_winnable(self, db):
        row = db.execute(
            "SELECT winnable FROM winnability "
            "WHERE game='zelda' AND level='zelda_0'"
        ).fetchone()
        assert row is not None and row[0] == 1

    def test_zelda_nokey_not_winnable(self, db):
        row = db.execute(
            "SELECT winnable FROM winnability "
            "WHERE game='zelda' AND level='zelda_nokey'"
        ).fetchone()
        assert row is not None and row[0] == 0


# ---------------------------------------------------------------------------
# Aliens hierarchy
# ---------------------------------------------------------------------------

class TestAliensHierarchy:
    def _q(self, db, name):
        row = db.execute(
            "SELECT parent, base_class, is_leaf FROM sprites "
            "WHERE game='aliens' AND name=?", (name,)
        ).fetchone()
        assert row is not None, f"Sprite '{name}' not found for aliens"
        return row

    def test_avatar_class(self, db):
        assert self._q(db, "avatar")["base_class"] == "FlakAvatar"

    def test_sam_class(self, db):
        assert self._q(db, "sam")["base_class"] == "Missile"

    def test_bomb_class(self, db):
        assert self._q(db, "bomb")["base_class"] == "Missile"

    def test_alienGreen_class(self, db):
        assert self._q(db, "alienGreen")["base_class"] == "Bomber"

    def test_portalSlow_class(self, db):
        assert self._q(db, "portalSlow")["base_class"] == "SpawnPoint"

    def test_portal_no_class(self, db):
        assert self._q(db, "portal")["base_class"] is None

    def test_missile_children(self, db):
        rows = db.execute(
            "SELECT name FROM sprites "
            "WHERE game='aliens' AND parent='missile' ORDER BY name"
        ).fetchall()
        assert [r[0] for r in rows] == ["bomb", "sam"]


# ---------------------------------------------------------------------------
# Aliens params
# ---------------------------------------------------------------------------

class TestAliensParams:
    def test_portalSlow_total(self, db):
        row = db.execute(
            "SELECT value FROM sprite_params "
            "WHERE game='aliens' AND sprite='portalSlow' AND key='total'"
        ).fetchone()
        assert row is not None and row[0] == "20"

    def test_portalSlow_inherits_hidden(self, db):
        row = db.execute(
            "SELECT value FROM sprite_params "
            "WHERE game='aliens' AND sprite='portalSlow' AND key='hidden'"
        ).fetchone()
        assert row is not None and row[0] == "True"


# ---------------------------------------------------------------------------
# Aliens level & winnability
# ---------------------------------------------------------------------------

class TestAliensLevel:
    def test_aliens_0_dims(self, db):
        row = db.execute(
            "SELECT rows, cols FROM level_dims "
            "WHERE game='aliens' AND level='aliens_0'"
        ).fetchone()
        assert row["rows"] == 11
        assert row["cols"] == 30

    def test_aliens_0_base_count(self, db):
        row = db.execute(
            "SELECT count FROM level_sprite_counts "
            "WHERE game='aliens' AND level='aliens_0' AND sprite='base'"
        ).fetchone()
        assert row is not None and row[0] == 47

    def test_aliens_0_portalSlow_count(self, db):
        row = db.execute(
            "SELECT count FROM level_sprite_counts "
            "WHERE game='aliens' AND level='aliens_0' AND sprite='portalSlow'"
        ).fetchone()
        assert row is not None and row[0] == 1

    def test_aliens_0_winnable(self, db):
        row = db.execute(
            "SELECT winnable FROM winnability "
            "WHERE game='aliens' AND level='aliens_0'"
        ).fetchone()
        assert row is not None and row[0] == 1

    def test_aliens_has_multi_sprite_counter(self, db):
        row = db.execute(
            "SELECT term_type FROM terminations "
            "WHERE game='aliens' AND win=1"
        ).fetchone()
        assert row is not None
        assert row[0] == "MultiSpriteCounter"


# ---------------------------------------------------------------------------
# Sokoban
# ---------------------------------------------------------------------------

class TestSokoban:
    def test_avatar_class(self, db):
        row = db.execute(
            "SELECT base_class FROM sprites "
            "WHERE game='sokoban' AND name='avatar'"
        ).fetchone()
        assert row[0] == "MovingAvatar"

    def test_box_class(self, db):
        row = db.execute(
            "SELECT base_class FROM sprites "
            "WHERE game='sokoban' AND name='box'"
        ).fetchone()
        assert row[0] == "Passive"

    def test_sokoban_0_dims(self, db):
        row = db.execute(
            "SELECT rows, cols FROM level_dims "
            "WHERE game='sokoban' AND level='sokoban_0'"
        ).fetchone()
        assert row["rows"] == 9
        assert row["cols"] == 13

    def test_sokoban_0_box_count(self, db):
        row = db.execute(
            "SELECT count FROM level_sprite_counts "
            "WHERE game='sokoban' AND level='sokoban_0' AND sprite='box'"
        ).fetchone()
        assert row is not None and row[0] == 4

    def test_sokoban_0_hole_count(self, db):
        row = db.execute(
            "SELECT count FROM level_sprite_counts "
            "WHERE game='sokoban' AND level='sokoban_0' AND sprite='hole'"
        ).fetchone()
        assert row is not None and row[0] == 2

    def test_sokoban_0_winnable(self, db):
        row = db.execute(
            "SELECT winnable FROM winnability "
            "WHERE game='sokoban' AND level='sokoban_0'"
        ).fetchone()
        assert row is not None and row[0] == 1

    def test_sokoban_noholes_not_winnable(self, db):
        row = db.execute(
            "SELECT winnable FROM winnability "
            "WHERE game='sokoban' AND level='sokoban_noholes'"
        ).fetchone()
        assert row is not None and row[0] == 0


# ---------------------------------------------------------------------------
# Chipschallenge
# ---------------------------------------------------------------------------

class TestChipschallenge:
    def test_avatar_class(self, db):
        row = db.execute(
            "SELECT base_class FROM sprites "
            "WHERE game='chipschallenge' AND name='avatar'"
        ).fetchone()
        assert row[0] == "MovingAvatar"

    def test_redkey_class(self, db):
        row = db.execute(
            "SELECT base_class FROM sprites "
            "WHERE game='chipschallenge' AND name='redkey'"
        ).fetchone()
        assert row[0] == "Resource"

    def test_flippers_class(self, db):
        row = db.execute(
            "SELECT base_class FROM sprites "
            "WHERE game='chipschallenge' AND name='flippers'"
        ).fetchone()
        assert row[0] == "Resource"

    def test_redkey_parent(self, db):
        row = db.execute(
            "SELECT parent FROM sprites "
            "WHERE game='chipschallenge' AND name='redkey'"
        ).fetchone()
        assert row[0] == "key"

    def test_chipschallenge_0_dims(self, db):
        row = db.execute(
            "SELECT rows, cols FROM level_dims "
            "WHERE game='chipschallenge' AND level='chipschallenge_0'"
        ).fetchone()
        assert row["rows"] == 14
        assert row["cols"] == 15

    def test_chipschallenge_0_chip_count(self, db):
        row = db.execute(
            "SELECT count FROM level_sprite_counts "
            "WHERE game='chipschallenge' AND level='chipschallenge_0' "
            "AND sprite='chip'"
        ).fetchone()
        assert row is not None and row[0] == 11

    def test_chipschallenge_0_winnable(self, db):
        row = db.execute(
            "SELECT winnable FROM winnability "
            "WHERE game='chipschallenge' AND level='chipschallenge_0'"
        ).fetchone()
        assert row is not None and row[0] == 1


# ---------------------------------------------------------------------------
# Firecaster
# ---------------------------------------------------------------------------

class TestFirecaster:
    def test_avatar_class(self, db):
        row = db.execute(
            "SELECT base_class FROM sprites "
            "WHERE game='firecaster' AND name='avatar'"
        ).fetchone()
        assert row[0] == "ShootAvatar"

    def test_fire_class(self, db):
        row = db.execute(
            "SELECT base_class FROM sprites "
            "WHERE game='firecaster' AND name='fire'"
        ).fetchone()
        assert row[0] == "Spreader"

    def test_spark_class(self, db):
        row = db.execute(
            "SELECT base_class FROM sprites "
            "WHERE game='firecaster' AND name='spark'"
        ).fetchone()
        assert row[0] == "SpawnPoint"

    def test_firecaster_0_dims(self, db):
        row = db.execute(
            "SELECT rows, cols FROM level_dims "
            "WHERE game='firecaster' AND level='firecaster_0'"
        ).fetchone()
        assert row["rows"] == 11
        assert row["cols"] == 19

    def test_firecaster_0_goal_count(self, db):
        row = db.execute(
            "SELECT count FROM level_sprite_counts "
            "WHERE game='firecaster' AND level='firecaster_0' "
            "AND sprite='goal'"
        ).fetchone()
        assert row is not None and row[0] == 1

    def test_firecaster_0_winnable(self, db):
        row = db.execute(
            "SELECT winnable FROM winnability "
            "WHERE game='firecaster' AND level='firecaster_0'"
        ).fetchone()
        assert row is not None and row[0] == 1


# ---------------------------------------------------------------------------
# Lemmings
# ---------------------------------------------------------------------------

class TestLemmings:
    def test_lemming_class(self, db):
        row = db.execute(
            "SELECT base_class FROM sprites "
            "WHERE game='lemmings' AND name='lemming'"
        ).fetchone()
        assert row[0] == "Chaser"

    def test_avatar_class(self, db):
        row = db.execute(
            "SELECT base_class FROM sprites "
            "WHERE game='lemmings' AND name='avatar'"
        ).fetchone()
        assert row[0] == "ShootAvatar"

    def test_entrance_class(self, db):
        row = db.execute(
            "SELECT base_class FROM sprites "
            "WHERE game='lemmings' AND name='entrance'"
        ).fetchone()
        assert row[0] == "SpawnPoint"

    def test_lemming_parent(self, db):
        row = db.execute(
            "SELECT parent FROM sprites "
            "WHERE game='lemmings' AND name='lemming'"
        ).fetchone()
        assert row[0] == "moving"

    def test_lemmings_0_dims(self, db):
        row = db.execute(
            "SELECT rows, cols FROM level_dims "
            "WHERE game='lemmings' AND level='lemmings_0'"
        ).fetchone()
        assert row["rows"] == 11
        assert row["cols"] == 21

    def test_lemmings_has_multi_sprite_counter(self, db):
        row = db.execute(
            "SELECT term_type FROM terminations "
            "WHERE game='lemmings' AND win=1"
        ).fetchone()
        assert row[0] == "MultiSpriteCounter"

    def test_lemmings_0_winnable(self, db):
        row = db.execute(
            "SELECT winnable FROM winnability "
            "WHERE game='lemmings' AND level='lemmings_0'"
        ).fetchone()
        assert row is not None and row[0] == 1


# ---------------------------------------------------------------------------
# Cross-game completeness
# ---------------------------------------------------------------------------

class TestCrossGame:
    def test_all_levels_have_winnability(self, db):
        level_count = db.execute(
            "SELECT COUNT(*) FROM level_dims"
        ).fetchone()[0]
        win_count = db.execute(
            "SELECT COUNT(*) FROM winnability"
        ).fetchone()[0]
        assert level_count == win_count
        assert level_count >= 8

    def test_all_games_have_interactions(self, db):
        games_with_ix = db.execute(
            "SELECT COUNT(DISTINCT game) FROM interactions"
        ).fetchone()[0]
        assert games_with_ix == 6

    def test_all_games_have_terminations(self, db):
        games_with_t = db.execute(
            "SELECT COUNT(DISTINCT game) FROM terminations"
        ).fetchone()[0]
        assert games_with_t == 6

    def test_sprite_params_populated(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM sprite_params"
        ).fetchone()[0]
        assert count > 50

    def test_interactions_have_params_json(self, db):
        row = db.execute(
            "SELECT params_json FROM interactions "
            "WHERE effect='transformTo' LIMIT 1"
        ).fetchone()
        assert row is not None
        params = json.loads(row[0])
        assert isinstance(params, dict)
