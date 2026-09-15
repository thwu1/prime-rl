
import sys
import json
import os
import glob
import pytest

sys.path.insert(0, '/app')

# ---------------------------------------------------------------------------
# Helpers for replay verification
# ---------------------------------------------------------------------------

REPLAYS_DIR = '/app/replays'


def discover_replay_games():
    """Find all replay game directories."""
    games = []
    for entry in sorted(os.listdir(REPLAYS_DIR)):
        game_dir = os.path.join(REPLAYS_DIR, entry)
        if os.path.isdir(game_dir) and os.path.exists(os.path.join(game_dir, 'metadata.json')):
            games.append(entry)
    return games


def load_turn(game_dir, turn_num):
    """Load a turn state snapshot."""
    path = os.path.join(REPLAYS_DIR, game_dir, f'turn_{turn_num:03d}.json')
    with open(path) as f:
        return json.load(f)


def load_commands(game_dir, turn_num):
    """Load commands for a turn."""
    path = os.path.join(REPLAYS_DIR, game_dir, f'commands_{turn_num:03d}.json')
    with open(path) as f:
        data = json.load(f)
    # Convert string keys back to int
    return {int(k): v for k, v in data.items()}


def load_metadata(game_dir):
    """Load game metadata."""
    path = os.path.join(REPLAYS_DIR, game_dir, 'metadata.json')
    with open(path) as f:
        return json.load(f)


def count_turns(game_dir):
    """Count how many turn files exist (turn_000, turn_001, ...)."""
    turn_files = glob.glob(os.path.join(REPLAYS_DIR, game_dir, 'turn_*.json'))
    return len(turn_files)


def compare_states(actual_state, expected_data, width, height, turn_label):
    """Compare a GameState against expected turn data."""
    errors = []

    # Compare halite grid
    expected_grid = expected_data['halite_grid']
    for y in range(height):
        for x in range(width):
            expected_val = expected_grid[y][x]
            actual_val = actual_state.get_cell_halite(x, y)
            if actual_val != expected_val:
                errors.append(
                    f"{turn_label} cell ({x},{y}): expected {expected_val}, got {actual_val}")

    # Compare each player
    for ep in expected_data['players']:
        pid = ep['id']

        # Player stored halite
        actual_h = actual_state.get_player_halite(pid)
        if actual_h != ep['halite']:
            errors.append(
                f"{turn_label} player {pid} halite: expected {ep['halite']}, got {actual_h}")

        # Ships
        actual_ships = sorted(actual_state.get_ships(pid), key=lambda s: s['id'])
        expected_ships = sorted(ep['ships'], key=lambda s: s['id'])

        if len(actual_ships) != len(expected_ships):
            errors.append(
                f"{turn_label} player {pid} ship count: expected {len(expected_ships)}, got {len(actual_ships)}")
        else:
            for a_ship, e_ship in zip(actual_ships, expected_ships):
                for key in ['id', 'x', 'y', 'halite']:
                    if a_ship.get(key) != e_ship.get(key):
                        errors.append(
                            f"{turn_label} player {pid} ship {e_ship['id']} {key}: "
                            f"expected {e_ship[key]}, got {a_ship.get(key)}")

        # Dropoffs
        actual_drops = sorted(actual_state.get_dropoffs(pid), key=lambda d: (d['x'], d['y']))
        expected_drops = sorted(ep.get('dropoffs', []), key=lambda d: (d['x'], d['y']))

        if len(actual_drops) != len(expected_drops):
            errors.append(
                f"{turn_label} player {pid} dropoff count: expected {len(expected_drops)}, got {len(actual_drops)}")

        # Shipyard
        actual_sy = actual_state.get_shipyard(pid)
        expected_sy = ep['shipyard']
        if actual_sy['x'] != expected_sy['x'] or actual_sy['y'] != expected_sy['y']:
            errors.append(
                f"{turn_label} player {pid} shipyard: expected ({expected_sy['x']},{expected_sy['y']}), "
                f"got ({actual_sy['x']},{actual_sy['y']})")

    return errors


# ===========================================================================
# Replay fidelity tests
# ===========================================================================

class TestReplayFidelity:
    """Verify simulator reproduces recorded game state transitions exactly."""

    @pytest.mark.parametrize("game_name", discover_replay_games())
    def test_replay(self, game_name):
        from simulator import GameState

        meta = load_metadata(game_name)
        width = meta['width']
        height = meta['height']
        constants = meta['constants']

        num_turns = count_turns(game_name)
        num_steps = num_turns - 1  # turn_000 is initial, each step produces next turn

        # Load initial state
        turn0 = load_turn(game_name, 0)
        state = GameState(width, height, turn0['halite_grid'], turn0['players'], constants)

        all_errors = []

        for step in range(num_steps):
            cmds = load_commands(game_name, step)
            state = state.step(cmds)

            expected = load_turn(game_name, step + 1)
            errors = compare_states(state, expected, width, height,
                                    f"[{game_name} turn {step + 1}]")
            all_errors.extend(errors)

        assert len(all_errors) == 0, \
            f"Replay {game_name} has {len(all_errors)} mismatches:\n" + \
            "\n".join(all_errors[:20])  # Show first 20


# ===========================================================================
# Planner tests
# ===========================================================================

class TestPlanSingleShip:
    """Single-ship planning scenario must meet halite threshold."""

    def test_plan_single(self):
        from simulator import GameState
        from planner import plan

        scenario_path = '/app/scenarios/plan_single.json'
        with open(scenario_path) as f:
            scenario = json.load(f)

        commands_seq = plan(scenario_path)
        assert isinstance(commands_seq, list), "plan() must return a list"

        state = GameState.from_scenario(scenario_path)
        initial_halite = state.get_player_halite(0)
        max_turns = scenario['max_turns']
        target = scenario['target_halite_gain']

        for turn in range(max_turns):
            cmds = commands_seq[turn] if turn < len(commands_seq) else []
            assert isinstance(cmds, list), f"Turn {turn} commands must be a list"
            state = state.step({0: cmds})

        gain = state.get_player_halite(0) - initial_halite
        assert gain >= target, \
            f"Single-ship scenario: gained {gain} halite, need >= {target}"


class TestPlanMultiShip:
    """Multi-ship planning: meet threshold with no friendly collisions."""

    def test_plan_multi(self):
        from simulator import GameState
        from planner import plan

        scenario_path = '/app/scenarios/plan_multi.json'
        with open(scenario_path) as f:
            scenario = json.load(f)

        commands_seq = plan(scenario_path)
        assert isinstance(commands_seq, list), "plan() must return a list"

        state = GameState.from_scenario(scenario_path)
        initial_halite = state.get_player_halite(0)
        max_turns = scenario['max_turns']
        target = scenario['target_halite_gain']

        for turn in range(max_turns):
            cmds = commands_seq[turn] if turn < len(commands_seq) else []
            old_ids = {s['id'] for s in state.get_ships(0)}
            state = state.step({0: cmds})
            new_ids = {s['id'] for s in state.get_ships(0)}
            lost = old_ids - new_ids
            assert len(lost) == 0, \
                f"Turn {turn}: ships {lost} lost (likely collision)"

        gain = state.get_player_halite(0) - initial_halite
        assert gain >= target, \
            f"Multi-ship scenario: gained {gain} halite, need >= {target}"
