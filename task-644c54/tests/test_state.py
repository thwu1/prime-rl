"""
Tests for the VGDL game engine.

"""

import sys
sys.path.insert(0, '/app')

import pytest
from vgdl_engine import GameDescription, ForwardModel, Solver


# ---- helpers --------------------------------------------------------------

def _load_sokoban():
    with open('/app/games/sokoban.txt') as f:
        game_text = f.read()
    with open('/app/games/sokoban_lvl.txt') as f:
        level_text = f.read()
    desc = GameDescription.parse(game_text)
    state = desc.load_level(level_text)
    return desc, state


def _load_zelda():
    with open('/app/games/zelda.txt') as f:
        game_text = f.read()
    with open('/app/games/zelda_lvl.txt') as f:
        level_text = f.read()
    desc = GameDescription.parse(game_text)
    state = desc.load_level(level_text)
    return desc, state


def _load_boulderdash():
    with open('/app/games/boulderdash.txt') as f:
        game_text = f.read()
    with open('/app/games/boulderdash_lvl.txt') as f:
        level_text = f.read()
    desc = GameDescription.parse(game_text)
    state = desc.load_level(level_text)
    return desc, state


def _simulate(desc, state, actions):
    fm = ForwardModel(desc)
    for a in actions:
        state = fm.advance(state, a)
        if state.game_over:
            break
    return state


# ===========================================================================
# Parsing tests
# ===========================================================================

class TestParseSokoban:
    def test_sprite_types(self):
        desc, _ = _load_sokoban()
        assert 'floor' in desc.sprite_types
        assert 'hole' in desc.sprite_types
        assert 'avatar' in desc.sprite_types
        assert 'box' in desc.sprite_types
        assert 'wall' in desc.sprite_types
        assert desc.sprite_types['avatar'].base_type == 'MovingAvatar'
        assert desc.sprite_types['box'].base_type == 'Passive'
        assert desc.sprite_types['wall'].base_type == 'Immovable'
        assert desc.sprite_types['hole'].base_type == 'Immovable'

    def test_interactions(self):
        desc, _ = _load_sokoban()
        effects = [(i.sprite1, i.sprite2, i.effect) for i in desc.interactions]
        assert ('avatar', 'wall', 'stepBack') in effects
        assert ('box', 'avatar', 'bounceForward') in effects
        assert ('box', 'wall', 'undoAll') in effects
        assert ('box', 'box', 'undoAll') in effects
        assert ('box', 'hole', 'killSprite') in effects
        # killSprite should have scoreChange=1
        kill_inter = [i for i in desc.interactions
                      if i.sprite1 == 'box' and i.sprite2 == 'hole'][0]
        assert kill_inter.params.get('scoreChange') == 1

    def test_termination(self):
        desc, _ = _load_sokoban()
        assert len(desc.terminations) == 1
        t = desc.terminations[0]
        assert t.ttype == 'SpriteCounter'
        assert t.params['stype'] == 'box'
        assert t.params['limit'] == 0
        assert t.params['win'] is True


class TestParseZelda:
    def test_hierarchy(self):
        desc, _ = _load_zelda()
        # Direct parent relationships
        assert desc.sprite_types['nokey'].parent_name == 'avatar'
        assert desc.sprite_types['withkey'].parent_name == 'avatar'
        assert desc.sprite_types['avatar'].parent_name == 'movable'
        assert desc.sprite_types['monsterQuick'].parent_name == 'enemy'
        assert desc.sprite_types['enemy'].parent_name == 'movable'
        assert desc.sprite_types['wall'].parent_name == 'movable'

    def test_is_subtype(self):
        desc, _ = _load_zelda()
        # Positive cases
        assert desc.is_subtype('nokey', 'avatar')
        assert desc.is_subtype('nokey', 'movable')
        assert desc.is_subtype('withkey', 'avatar')
        assert desc.is_subtype('withkey', 'movable')
        assert desc.is_subtype('monsterQuick', 'enemy')
        assert desc.is_subtype('monsterQuick', 'movable')
        assert desc.is_subtype('wall', 'movable')
        assert desc.is_subtype('nokey', 'nokey')  # identity
        # Negative cases
        assert not desc.is_subtype('nokey', 'enemy')
        assert not desc.is_subtype('withkey', 'nokey')
        assert not desc.is_subtype('wall', 'avatar')
        assert not desc.is_subtype('avatar', 'nokey')

    def test_base_types_inherited(self):
        desc, _ = _load_zelda()
        assert desc.sprite_types['nokey'].base_type == 'ShootAvatar'
        assert desc.sprite_types['withkey'].base_type == 'ShootAvatar'
        assert desc.sprite_types['monsterQuick'].base_type == 'RandomNPC'
        assert desc.sprite_types['wall'].base_type == 'Immovable'
        assert desc.sprite_types['goal'].base_type == 'Door'


class TestParseBoulderdash:
    def test_sprite_types(self):
        desc, _ = _load_boulderdash()
        assert 'background' in desc.sprite_types
        assert 'wall' in desc.sprite_types
        assert 'dirt' in desc.sprite_types
        assert 'exitdoor' in desc.sprite_types
        assert 'diamond' in desc.sprite_types
        assert 'avatar' in desc.sprite_types
        assert desc.sprite_types['exitdoor'].base_type == 'Door'
        assert desc.sprite_types['diamond'].base_type == 'Resource'
        assert desc.sprite_types['avatar'].base_type == 'MovingAvatar'
        assert desc.sprite_types['dirt'].base_type == 'Immovable'

    def test_interactions(self):
        desc, _ = _load_boulderdash()
        effects = [(i.sprite1, i.sprite2, i.effect) for i in desc.interactions]
        assert ('dirt', 'avatar', 'killSprite') in effects
        assert ('diamond', 'avatar', 'collectResource') in effects
        assert ('avatar', 'wall', 'stepBack') in effects
        assert ('exitdoor', 'avatar', 'killIfOtherHasMore') in effects
        # killIfOtherHasMore params
        exit_inter = [i for i in desc.interactions
                      if i.effect == 'killIfOtherHasMore'][0]
        assert exit_inter.params.get('resource') == 'diamond'
        assert exit_inter.params.get('limit') == 2

    def test_termination(self):
        desc, _ = _load_boulderdash()
        assert len(desc.terminations) == 2
        ttypes = [(t.ttype, t.params.get('stype'), t.params.get('win'))
                  for t in desc.terminations]
        assert ('SpriteCounter', 'avatar', False) in ttypes
        assert ('SpriteCounter', 'exitdoor', True) in ttypes


# ===========================================================================
# Level loading tests
# ===========================================================================

class TestLoadLevel:
    def test_sokoban_dimensions(self):
        desc, state = _load_sokoban()
        assert state.width == 6
        assert state.height == 5

    def test_sokoban_avatar_position(self):
        desc, state = _load_sokoban()
        avatar = state.get_avatar(desc)
        assert avatar is not None
        assert avatar.x == 2 and avatar.y == 3

    def test_sokoban_box_position(self):
        desc, state = _load_sokoban()
        boxes = state.get_sprites_of_type('box', desc)
        assert len(boxes) == 1
        assert boxes[0].x == 2 and boxes[0].y == 2

    def test_sokoban_hole_position(self):
        desc, state = _load_sokoban()
        holes = state.get_sprites_of_type('hole', desc)
        assert len(holes) == 1
        assert holes[0].x == 1 and holes[0].y == 1

    def test_zelda_avatar(self):
        desc, state = _load_zelda()
        avatar = state.get_avatar(desc)
        assert avatar is not None
        assert avatar.stype == 'nokey'
        assert avatar.x == 1 and avatar.y == 3

    def test_zelda_key_position(self):
        desc, state = _load_zelda()
        keys = state.get_sprites_of_type('key', desc)
        assert len(keys) == 1
        assert keys[0].x == 4 and keys[0].y == 3

    def test_zelda_goal_position(self):
        desc, state = _load_zelda()
        goals = state.get_sprites_of_type('goal', desc)
        assert len(goals) == 1
        assert goals[0].x == 2 and goals[0].y == 1

    def test_boulderdash_dimensions(self):
        desc, state = _load_boulderdash()
        assert state.width == 6
        assert state.height == 5

    def test_boulderdash_avatar_position(self):
        desc, state = _load_boulderdash()
        avatar = state.get_avatar(desc)
        assert avatar is not None
        assert avatar.x == 1 and avatar.y == 3

    def test_boulderdash_diamond_positions(self):
        desc, state = _load_boulderdash()
        diamonds = state.get_sprites_of_type('diamond', desc)
        assert len(diamonds) == 2
        positions = {(d.x, d.y) for d in diamonds}
        assert (1, 1) in positions
        assert (3, 1) in positions

    def test_boulderdash_exitdoor_position(self):
        desc, state = _load_boulderdash()
        exits = state.get_sprites_of_type('exitdoor', desc)
        assert len(exits) == 1
        assert exits[0].x == 4 and exits[0].y == 3


# ===========================================================================
# Simulation tests
# ===========================================================================

class TestSokobanSimulation:
    def test_push_box(self):
        """Push box UP via bounceForward."""
        desc, state = _load_sokoban()
        state = _simulate(desc, state, ['UP'])

        avatar = state.get_avatar(desc)
        assert avatar.x == 2 and avatar.y == 2

        boxes = state.get_sprites_of_type('box', desc)
        assert len(boxes) == 1
        assert boxes[0].x == 2 and boxes[0].y == 1

        assert not state.game_over

    def test_wall_blocks_push(self):
        """Push box UP twice — second push hits wall, undoAll restores."""
        desc, state = _load_sokoban()
        state = _simulate(desc, state, ['UP', 'UP'])

        avatar = state.get_avatar(desc)
        assert avatar.x == 2 and avatar.y == 2  # restored by undoAll

        boxes = state.get_sprites_of_type('box', desc)
        assert len(boxes) == 1
        assert boxes[0].x == 2 and boxes[0].y == 1  # restored by undoAll

        assert not state.game_over

    def test_avatar_wall_stepback(self):
        """Avatar walks into wall — stepBack."""
        desc, state = _load_sokoban()
        state = _simulate(desc, state, ['LEFT', 'LEFT'])  # (2,3)->(1,3)->(0,3)=wall

        avatar = state.get_avatar(desc)
        assert avatar.x == 1 and avatar.y == 3  # stopped at wall
        assert not state.game_over

    def test_win(self):
        """Full winning sequence: push box into hole."""
        desc, state = _load_sokoban()
        # UP: push box to (2,1); RIGHT: avatar to (3,2);
        # UP: avatar to (3,1); LEFT: push box from (2,1) to (1,1)=hole
        state = _simulate(desc, state, ['UP', 'RIGHT', 'UP', 'LEFT'])

        assert state.game_over is True
        assert state.game_win is True
        assert state.score >= 1

        boxes = state.get_sprites_of_type('box', desc)
        assert len(boxes) == 0  # box destroyed


class TestZeldaSimulation:
    def test_key_pickup(self):
        """Pick up key — avatar transforms from nokey to withkey."""
        desc, state = _load_zelda()
        # 3 RIGHTs: avatar (1,3) -> (2,3) -> (3,3) -> (4,3) where key is
        state = _simulate(desc, state, ['RIGHT', 'RIGHT', 'RIGHT'])

        avatar = state.get_avatar(desc)
        assert avatar.stype == 'withkey'
        assert avatar.x == 4 and avatar.y == 3

        keys = state.get_sprites_of_type('key', desc)
        assert len(keys) == 0  # key consumed

        assert state.score >= 1
        assert not state.game_over

    def test_wall_collision(self):
        """Avatar cannot walk through interior wall."""
        desc, state = _load_zelda()
        # RIGHT then UP: avatar at (2,3), tries UP to (2,2) which is wall
        state = _simulate(desc, state, ['RIGHT', 'UP'])

        avatar = state.get_avatar(desc)
        assert avatar.x == 2 and avatar.y == 3  # stayed

    def test_nokey_blocked_by_goal(self):
        """nokey avatar cannot pass through goal."""
        desc, state = _load_zelda()
        # UP, UP: avatar (1,3)->(1,2)->(1,1). RIGHT: try (2,1)=goal, blocked
        state = _simulate(desc, state, ['UP', 'UP', 'RIGHT'])

        avatar = state.get_avatar(desc)
        assert avatar.x == 1 and avatar.y == 1  # blocked by goal
        assert not state.game_over

        goals = state.get_sprites_of_type('goal', desc)
        assert len(goals) == 1  # goal still alive

    def test_win(self):
        """Full winning sequence: get key, reach goal."""
        desc, state = _load_zelda()
        # RIGHT*3: pick key at (4,3). UP*2: to (4,1). LEFT*2: to (2,1)=goal
        state = _simulate(desc, state,
                          ['RIGHT', 'RIGHT', 'RIGHT', 'UP', 'UP', 'LEFT', 'LEFT'])

        assert state.game_over is True
        assert state.game_win is True
        assert state.score >= 2  # key pickup + goal

        goals = state.get_sprites_of_type('goal', desc)
        assert len(goals) == 0


class TestBoulderdashSimulation:
    def test_dig_dirt(self):
        """Avatar destroys dirt by moving onto it."""
        desc, state = _load_boulderdash()
        state = _simulate(desc, state, ['UP'])
        avatar = state.get_avatar(desc)
        assert avatar.x == 1 and avatar.y == 2
        # Dirt at (1,2) should be destroyed
        dirt_here = [s for s in state.sprites
                     if s.stype == 'dirt' and s.x == 1 and s.y == 2 and s.alive]
        assert len(dirt_here) == 0

    def test_collect_diamond(self):
        """Avatar collects diamond, gaining a resource."""
        desc, state = _load_boulderdash()
        # UP twice: (1,3)->(1,2) dig dirt, (1,2)->(1,1) collect diamond
        state = _simulate(desc, state, ['UP', 'UP'])
        avatar = state.get_avatar(desc)
        assert avatar.x == 1 and avatar.y == 1
        assert avatar.resources.get('diamond', 0) == 1
        assert state.score >= 2
        # One diamond consumed
        diamonds = state.get_sprites_of_type('diamond', desc)
        assert len(diamonds) == 1

    def test_collect_two_diamonds(self):
        """Avatar collects both diamonds sequentially."""
        desc, state = _load_boulderdash()
        actions = ['UP', 'UP', 'RIGHT', 'RIGHT']
        state = _simulate(desc, state, actions)
        avatar = state.get_avatar(desc)
        assert avatar.resources.get('diamond', 0) == 2
        assert state.score >= 4
        diamonds = state.get_sprites_of_type('diamond', desc)
        assert len(diamonds) == 0

    def test_exit_blocked_without_diamonds(self):
        """Exit stays alive when avatar lacks required resources."""
        desc, state = _load_boulderdash()
        # Walk right to exit without collecting diamonds
        state = _simulate(desc, state, ['RIGHT', 'RIGHT', 'RIGHT'])
        assert not state.game_over
        exits = state.get_sprites_of_type('exitdoor', desc)
        assert len(exits) == 1  # exit still alive

    def test_wall_blocking(self):
        """Avatar cannot move through walls."""
        desc, state = _load_boulderdash()
        state = _simulate(desc, state, ['LEFT'])
        avatar = state.get_avatar(desc)
        assert avatar.x == 1 and avatar.y == 3  # blocked

    def test_win_with_diamonds(self):
        """Collect enough diamonds then exit to win."""
        desc, state = _load_boulderdash()
        # Collect diamond at (1,1): UP, UP
        # Collect diamond at (3,1): RIGHT, RIGHT
        # Navigate to exit at (4,3): DOWN, DOWN, RIGHT
        actions = ['UP', 'UP', 'RIGHT', 'RIGHT', 'DOWN', 'DOWN', 'RIGHT']
        state = _simulate(desc, state, actions)
        assert state.game_over is True
        assert state.game_win is True
        assert state.score >= 9  # 2*2 for diamonds + 5 for exit


# ===========================================================================
# Solver tests
# ===========================================================================

class TestSolver:
    def test_solve_sokoban(self):
        """Solver finds a winning sequence for sokoban."""
        desc, state = _load_sokoban()
        solver = Solver()
        solution = solver.solve(desc, state)

        assert solution is not None, "Solver returned None — no solution found"
        assert len(solution) > 0

        # Validate by simulation
        final = _simulate(desc, state, solution)
        assert final.game_over is True
        assert final.game_win is True

    def test_solve_zelda(self):
        """Solver finds a winning sequence for zelda."""
        desc, state = _load_zelda()
        solver = Solver()
        solution = solver.solve(desc, state)

        assert solution is not None, "Solver returned None — no solution found"
        assert len(solution) > 0

        # Validate by simulation
        final = _simulate(desc, state, solution)
        assert final.game_over is True
        assert final.game_win is True

    def test_solve_boulderdash(self):
        """Solver finds a winning sequence for boulderdash."""
        desc, state = _load_boulderdash()
        solver = Solver()
        solution = solver.solve(desc, state)

        assert solution is not None, "Solver returned None — no solution found"
        assert len(solution) > 0

        final = _simulate(desc, state, solution)
        assert final.game_over is True
        assert final.game_win is True

    def test_sokoban_solution_all_valid_actions(self):
        """Solver's solution only uses valid actions."""
        desc, state = _load_sokoban()
        solver = Solver()
        solution = solver.solve(desc, state)
        assert solution is not None
        valid = {'UP', 'DOWN', 'LEFT', 'RIGHT'}
        for a in solution:
            assert a in valid, f"Invalid action: {a}"

    def test_zelda_solution_all_valid_actions(self):
        """Solver's solution only uses valid actions."""
        desc, state = _load_zelda()
        solver = Solver()
        solution = solver.solve(desc, state)
        assert solution is not None
        valid = {'UP', 'DOWN', 'LEFT', 'RIGHT'}
        for a in solution:
            assert a in valid, f"Invalid action: {a}"

    def test_boulderdash_solution_all_valid_actions(self):
        """Solver's solution only uses valid actions."""
        desc, state = _load_boulderdash()
        solver = Solver()
        solution = solver.solve(desc, state)
        assert solution is not None
        valid = {'UP', 'DOWN', 'LEFT', 'RIGHT'}
        for a in solution:
            assert a in valid, f"Invalid action: {a}"


# ===========================================================================
# CLI trace tests
# ===========================================================================

class TestCLI:
    def test_trace_sokoban_push(self):
        """CLI outputs valid JSON after simulating actions."""
        import subprocess, json
        result = subprocess.run(
            ['python3', '/app/vgdl_engine.py', 'trace',
             '/app/games/sokoban.txt', '/app/games/sokoban_lvl.txt',
             'UP'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        data = json.loads(result.stdout.strip())
        assert data['tick'] == 1
        assert data['score'] == 0
        assert data['game_over'] is False
        assert 'sprites' in data
        assert isinstance(data['sprites'], list)

    def test_trace_boulderdash_win(self):
        """CLI reports correct win state for boulderdash."""
        import subprocess, json
        result = subprocess.run(
            ['python3', '/app/vgdl_engine.py', 'trace',
             '/app/games/boulderdash.txt', '/app/games/boulderdash_lvl.txt',
             'UP,UP,RIGHT,RIGHT,DOWN,DOWN,RIGHT'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        data = json.loads(result.stdout.strip())
        assert data['game_over'] is True
        assert data['win'] is True
        assert data['score'] >= 9

    def test_trace_jq_compatible(self):
        """CLI output is valid JSON processable by jq."""
        import subprocess
        trace = subprocess.run(
            ['python3', '/app/vgdl_engine.py', 'trace',
             '/app/games/sokoban.txt', '/app/games/sokoban_lvl.txt',
             'UP'],
            capture_output=True, text=True, timeout=30
        )
        assert trace.returncode == 0

        jq = subprocess.run(
            ['jq', '.score'],
            input=trace.stdout,
            capture_output=True, text=True, timeout=10
        )
        assert jq.returncode == 0, f"jq failed: {jq.stderr}"
        assert jq.stdout.strip() == '0'
