
import pytest
import sqlite3
import json
import os
from collections import deque

DB_PATH = '/app/sokoban.db'
REPORT_PATH = '/app/report.json'

DIRS = {
    'u': (0, -1), 'd': (0, 1), 'l': (-1, 0), 'r': (1, 0),
    'U': (0, -1), 'D': (0, 1), 'L': (-1, 0), 'R': (1, 0),
}


# ---- Utility functions (independent recomputation) ----

def parse_grid(grid_text):
    lines = grid_text.split('\n')
    walls, goals, boxes = set(), set(), set()
    player = None
    for y, line in enumerate(lines):
        for x, ch in enumerate(line):
            if ch == '#':
                walls.add((x, y))
            elif ch == '$':
                boxes.add((x, y))
            elif ch == '.':
                goals.add((x, y))
            elif ch == '@':
                player = (x, y)
            elif ch == '*':
                goals.add((x, y))
                boxes.add((x, y))
            elif ch == '+':
                goals.add((x, y))
                player = (x, y)
    max_x = max(len(l) for l in lines) if lines else 0
    max_y = len(lines)
    floor = set()
    vis = {player}
    q = deque([player])
    while q:
        x, y = q.popleft()
        floor.add((x, y))
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if ((nx, ny) not in walls and (nx, ny) not in vis
                    and 0 <= nx < max_x and 0 <= ny < max_y):
                vis.add((nx, ny))
                q.append((nx, ny))
    return walls, floor, goals, frozenset(boxes), player


def simulate_solution(grid_text, move_string):
    lines = grid_text.split('\n')
    walls, goals, boxes_init = set(), set(), set()
    player = None
    for y, line in enumerate(lines):
        for x, ch in enumerate(line):
            if ch == '#':
                walls.add((x, y))
            elif ch == '$':
                boxes_init.add((x, y))
            elif ch == '.':
                goals.add((x, y))
            elif ch == '@':
                player = (x, y)
            elif ch == '*':
                goals.add((x, y))
                boxes_init.add((x, y))
            elif ch == '+':
                goals.add((x, y))
                player = (x, y)
    boxes = set(boxes_init)
    for i, m in enumerate(move_string):
        assert m in DIRS, f"Invalid char '{m}' at position {i}"
        dx, dy = DIRS[m]
        tgt = (player[0] + dx, player[1] + dy)
        if m.isupper():
            assert tgt in boxes, f"Push {i} '{m}': no box at {tgt}"
            bt = (tgt[0] + dx, tgt[1] + dy)
            assert bt not in walls, f"Push {i} '{m}': box would hit wall at {bt}"
            assert bt not in boxes, f"Push {i} '{m}': box would hit box at {bt}"
            boxes.remove(tgt)
            boxes.add(bt)
            player = tgt
        else:
            assert tgt not in walls, f"Move {i} '{m}': wall at {tgt}"
            assert tgt not in boxes, f"Move {i} '{m}': box at {tgt}"
            player = tgt
    for g in goals:
        assert g in boxes, f"Goal {g} has no box after solution"


def compute_dead_squares(walls, floor, goals):
    reachable = set()
    for goal in goals:
        vis = {goal}
        q = deque([goal])
        while q:
            px, py = q.popleft()
            reachable.add((px, py))
            for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                bf = (px + dx, py + dy)
                pf = (px + 2 * dx, py + 2 * dy)
                if bf in floor and pf in floor and bf not in vis:
                    vis.add(bf)
                    q.append(bf)
    return frozenset(p for p in floor if p not in reachable and p not in goals)


def get_reachable(player, walls, boxes):
    vis = {player}
    q = deque([player])
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if ((nx, ny) not in walls and (nx, ny) not in boxes
                    and (nx, ny) not in vis):
                vis.add((nx, ny))
                q.append((nx, ny))
    return vis


def normalize_player(player, walls, boxes):
    return min(get_reachable(player, walls, boxes))


def enumerate_state_space(walls, floor, goals, boxes, player):
    goals_fs = frozenset(goals)
    norm = normalize_player(player, walls, boxes)
    start = (norm, boxes)
    visited = {start}
    queue = deque([(start, 0)])
    total = 0
    dead_ends = 0
    total_succ = 0
    non_goal = 0
    sol_depth = -1

    while queue:
        state, depth = queue.popleft()
        np, bxs = state
        total += 1
        if bxs == goals_fs:
            if sol_depth < 0:
                sol_depth = depth
            continue
        non_goal += 1
        reach = get_reachable(np, walls, bxs)
        succs = set()
        for box in bxs:
            bx, by = box
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                pf = (bx - dx, by - dy)
                if pf not in reach:
                    continue
                tgt = (bx + dx, by + dy)
                if tgt in walls or tgt in bxs or tgt not in floor:
                    continue
                nb = frozenset((bxs - {box}) | {tgt})
                nn = normalize_player(box, walls, nb)
                succs.add((nn, nb))
        total_succ += len(succs)
        if not succs:
            dead_ends += 1
        for s in succs:
            if s not in visited:
                visited.add(s)
                queue.append((s, depth + 1))

    avg_bf = total_succ / non_goal if non_goal > 0 else 0.0
    return total, dead_ends, sol_depth, avg_bf


def compute_corner_deadlocks(walls, floor, goals):
    count = 0
    for x, y in floor:
        if (x, y) in goals:
            continue
        u = (x, y - 1) in walls
        d = (x, y + 1) in walls
        l = (x - 1, y) in walls
        r = (x + 1, y) in walls
        if (u and l) or (u and r) or (d and l) or (d and r):
            count += 1
    return count


def compute_freeze_positions(walls, floor, goals):
    all_cells = walls | floor
    if not all_cells:
        return 0
    xs = [c[0] for c in all_cells]
    ys = [c[1] for c in all_cells]
    count = 0
    for x in range(min(xs), max(xs)):
        for y in range(min(ys), max(ys)):
            cells = [(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)]
            if not all(c in all_cells for c in cells):
                continue
            nw = sum(1 for c in cells if c in walls)
            ngf = sum(1 for c in cells if c in floor and c not in goals)
            if nw >= 1 and ngf >= 2:
                count += 1
    return count


# ---- Test class ----

class TestSokobanPipeline:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self.levels = self.conn.execute(
            "SELECT id, name, grid, num_boxes FROM levels ORDER BY id"
        ).fetchall()

    def test_solutions_table_schema(self):
        cols = self.conn.execute("PRAGMA table_info(solutions)").fetchall()
        col_names = {c['name'] for c in cols}
        assert 'level_id' in col_names
        assert 'move_string' in col_names
        assert 'num_moves' in col_names
        assert 'num_pushes' in col_names

    def test_solutions_count(self):
        count = self.conn.execute(
            "SELECT COUNT(*) FROM solutions").fetchone()[0]
        assert count == 5, f"Expected 5 solutions, got {count}"

    def test_each_solution_valid(self):
        for level in self.levels:
            row = self.conn.execute(
                "SELECT move_string FROM solutions WHERE level_id=?",
                (level['id'],)).fetchone()
            assert row is not None, f"No solution for level {level['id']}"
            simulate_solution(level['grid'], row['move_string'])

    def test_solution_move_counts(self):
        for level in self.levels:
            row = self.conn.execute(
                "SELECT move_string, num_moves, num_pushes "
                "FROM solutions WHERE level_id=?",
                (level['id'],)).fetchone()
            ms = row['move_string']
            assert row['num_moves'] == len(ms), (
                f"Level {level['id']}: num_moves={row['num_moves']} "
                f"!= len(move_string)={len(ms)}")
            pushes = sum(1 for c in ms if c.isupper())
            assert row['num_pushes'] == pushes, (
                f"Level {level['id']}: num_pushes={row['num_pushes']} "
                f"!= actual pushes={pushes}")

    def test_solutions_contain_pushes(self):
        for level in self.levels:
            row = self.conn.execute(
                "SELECT move_string FROM solutions WHERE level_id=?",
                (level['id'],)).fetchone()
            assert any(c.isupper() for c in row['move_string']), (
                f"Level {level['id']}: solution has no pushes")

    def test_dead_squares_table_schema(self):
        cols = self.conn.execute(
            "PRAGMA table_info(dead_squares)").fetchall()
        col_names = {c['name'] for c in cols}
        assert 'level_id' in col_names
        assert 'x' in col_names
        assert 'y' in col_names

    def test_dead_squares_correct(self):
        for level in self.levels:
            lid = level['id']
            walls, floor, goals, boxes, player = parse_grid(level['grid'])
            expected = compute_dead_squares(walls, floor, goals)
            rows = self.conn.execute(
                "SELECT x, y FROM dead_squares WHERE level_id=?",
                (lid,)).fetchall()
            actual = frozenset((r['x'], r['y']) for r in rows)
            assert actual == expected, (
                f"Level {lid}: dead squares mismatch. "
                f"Expected {len(expected)}, got {len(actual)}. "
                f"Missing: {expected - actual}, Extra: {actual - expected}")

    def test_state_metrics_table_schema(self):
        cols = self.conn.execute(
            "PRAGMA table_info(state_metrics)").fetchall()
        col_names = {c['name'] for c in cols}
        for col in ['level_id', 'reachable_states', 'dead_end_states',
                     'solution_depth', 'avg_branching_factor']:
            assert col in col_names, f"Missing column: {col}"

    def test_state_metrics_correct(self):
        for level in self.levels:
            lid = level['id']
            walls, floor, goals, boxes, player = parse_grid(level['grid'])
            exp_total, exp_de, exp_sd, exp_bf = enumerate_state_space(
                walls, floor, goals, boxes, player)
            row = self.conn.execute(
                "SELECT * FROM state_metrics WHERE level_id=?",
                (lid,)).fetchone()
            assert row is not None, f"No state_metrics for level {lid}"
            assert row['reachable_states'] == exp_total, (
                f"Level {lid}: reachable_states "
                f"{row['reachable_states']} != {exp_total}")
            assert row['dead_end_states'] == exp_de, (
                f"Level {lid}: dead_end_states "
                f"{row['dead_end_states']} != {exp_de}")
            assert row['solution_depth'] == exp_sd, (
                f"Level {lid}: solution_depth "
                f"{row['solution_depth']} != {exp_sd}")
            assert abs(row['avg_branching_factor'] - exp_bf) < 0.01, (
                f"Level {lid}: avg_branching_factor "
                f"{row['avg_branching_factor']} != {exp_bf:.6f}")

    def test_solution_depth_matches_pushes(self):
        for level in self.levels:
            lid = level['id']
            sm = self.conn.execute(
                "SELECT solution_depth FROM state_metrics WHERE level_id=?",
                (lid,)).fetchone()
            sol = self.conn.execute(
                "SELECT num_pushes FROM solutions WHERE level_id=?",
                (lid,)).fetchone()
            assert sm is not None and sol is not None
            assert sm['solution_depth'] == sol['num_pushes'], (
                f"Level {lid}: BFS solution_depth={sm['solution_depth']} "
                f"!= solver num_pushes={sol['num_pushes']}")

    def test_deadlock_census_table_schema(self):
        cols = self.conn.execute(
            "PRAGMA table_info(deadlock_census)").fetchall()
        col_names = {c['name'] for c in cols}
        assert 'level_id' in col_names
        assert 'corner_deadlocks' in col_names
        assert 'freeze_deadlocks' in col_names

    def test_deadlock_census_correct(self):
        for level in self.levels:
            lid = level['id']
            walls, floor, goals, boxes, player = parse_grid(level['grid'])
            exp_corners = compute_corner_deadlocks(walls, floor, goals)
            exp_freezes = compute_freeze_positions(walls, floor, goals)
            row = self.conn.execute(
                "SELECT * FROM deadlock_census WHERE level_id=?",
                (lid,)).fetchone()
            assert row is not None, f"No deadlock_census for level {lid}"
            assert row['corner_deadlocks'] == exp_corners, (
                f"Level {lid}: corner_deadlocks "
                f"{row['corner_deadlocks']} != {exp_corners}")
            assert row['freeze_deadlocks'] == exp_freezes, (
                f"Level {lid}: freeze_deadlocks "
                f"{row['freeze_deadlocks']} != {exp_freezes}")

    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH), "report.json not found"

    def test_report_structure(self):
        with open(REPORT_PATH) as f:
            report = json.load(f)
        assert 'levels' in report, "report missing 'levels'"
        assert 'difficulty_ranking' in report, (
            "report missing 'difficulty_ranking'")
        assert len(report['levels']) == 5, (
            f"Expected 5 levels in report, got {len(report['levels'])}")
        assert len(report['difficulty_ranking']) == 5, (
            f"Expected 5 IDs in ranking, got "
            f"{len(report['difficulty_ranking'])}")
        required_keys = [
            'id', 'name', 'num_pushes', 'num_moves',
            'dead_square_count', 'reachable_states', 'solution_depth',
            'corner_deadlocks', 'freeze_deadlocks']
        for entry in report['levels']:
            for key in required_keys:
                assert key in entry, (
                    f"Report entry missing '{key}'")

    def test_report_difficulty_ranking(self):
        with open(REPORT_PATH) as f:
            report = json.load(f)
        states = {e['id']: e['reachable_states'] for e in report['levels']}
        ranking = report['difficulty_ranking']
        for i in range(len(ranking) - 1):
            assert states[ranking[i]] >= states[ranking[i + 1]], (
                f"Ranking out of order: level {ranking[i]} "
                f"({states[ranking[i]]} states) < level {ranking[i + 1]} "
                f"({states[ranking[i + 1]]} states)")

    def test_report_matches_database(self):
        with open(REPORT_PATH) as f:
            report = json.load(f)
        for entry in report['levels']:
            lid = entry['id']
            sol = self.conn.execute(
                "SELECT num_pushes, num_moves FROM solutions "
                "WHERE level_id=?", (lid,)).fetchone()
            assert entry['num_pushes'] == sol['num_pushes'], (
                f"Level {lid}: report num_pushes != db")
            assert entry['num_moves'] == sol['num_moves'], (
                f"Level {lid}: report num_moves != db")
            ds_count = self.conn.execute(
                "SELECT COUNT(*) FROM dead_squares WHERE level_id=?",
                (lid,)).fetchone()[0]
            assert entry['dead_square_count'] == ds_count, (
                f"Level {lid}: report dead_square_count != db")
