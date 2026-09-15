"""Tests for the UCI chess engine and benchmarking pipeline."""

import os
import subprocess
import sys
import time
import threading
import queue
import json


sys.path.insert(0, '/app')
from chess_core import (
    Position, Move, from_fen, can_kill_king,
    parse_square, render_square, initial,
    A1, H1, A8, H8, N, S, E, W
)


class UCIEngine:
    """Subprocess wrapper for UCI engine communication."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, '/app/engine.py'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        self._q = queue.Queue()
        self._t = threading.Thread(target=self._reader, daemon=True)
        self._t.start()

    def _reader(self):
        try:
            for line in self.proc.stdout:
                self._q.put(line.strip())
        except Exception:
            pass

    def send(self, cmd):
        self.proc.stdin.write(cmd + '\n')
        self.proc.stdin.flush()

    def read_until(self, prefix, timeout=60):
        deadline = time.time() + timeout
        lines = []
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            try:
                line = self._q.get(timeout=min(1.0, remaining))
                lines.append(line)
                if line.startswith(prefix):
                    return lines
            except queue.Empty:
                continue
        raise TimeoutError(
            f"'{prefix}' not received within {timeout}s. Got: {lines}"
        )

    def init_uci(self):
        self.send('uci')
        self.read_until('uciok', timeout=10)
        self.send('isready')
        self.read_until('readyok', timeout=10)

    def get_bestmove(self, fen, depth=6, timeout=90):
        self.send('isready')
        self.read_until('readyok', timeout=10)
        self.send(f'position fen {fen}')
        self.send(f'go depth {depth}')
        lines = self.read_until('bestmove', timeout=timeout)
        for line in lines:
            if line.startswith('bestmove'):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
        return None

    def close(self):
        try:
            self.send('quit')
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
            self.proc.wait()


def is_in_check(pos):
    """Check if the side to move is in check (opponent can capture our king)."""
    opp_view = pos.rotate(nullmove=True)
    return can_kill_king(opp_view)


def has_legal_moves(pos):
    """Check if the side to move has any legal moves."""
    for move in pos.gen_moves():
        child = pos.move(move)
        if not can_kill_king(child):
            return True
    return False


def is_checkmate(pos):
    """Check if the side to move is in checkmate."""
    return is_in_check(pos) and not has_legal_moves(pos)


def apply_uci_move_white(pos, uci_str):
    """Apply a UCI move to position where white is to move (no coordinate flip)."""
    from_sq = parse_square(uci_str[:2])
    to_sq = parse_square(uci_str[2:4])
    prom = uci_str[4:].upper() if len(uci_str) > 4 else ""
    return pos.move(Move(from_sq, to_sq, prom))


# ---------------------------------------------------------------------------
# Test: UCI protocol basic compliance
# ---------------------------------------------------------------------------
def test_uci_protocol():
    """Engine must respond to 'uci' with 'uciok' and 'isready' with 'readyok'."""
    engine = UCIEngine()
    try:
        engine.send('uci')
        lines = engine.read_until('uciok', timeout=10)
        assert any('uciok' in l for l in lines), "Missing 'uciok'"

        engine.send('isready')
        lines = engine.read_until('readyok', timeout=10)
        assert any('readyok' in l for l in lines), "Missing 'readyok'"
    finally:
        engine.close()


# ---------------------------------------------------------------------------
# Test: Mate in 1 — Queen back-rank with pawns
# ---------------------------------------------------------------------------
def test_mate_in_1_queen_backrank():
    """6k1/5ppp/4p3/8/8/8/1Q6/2K5 w - - 0 1
    Qb8# delivers back-rank checkmate (pawns trap the king)."""
    fen = '6k1/5ppp/4p3/8/8/8/1Q6/2K5 w - - 0 1'
    engine = UCIEngine()
    try:
        engine.init_uci()
        bestmove = engine.get_bestmove(fen, depth=4)
        assert bestmove and bestmove != '(none)', f"No bestmove: {bestmove}"

        pos = from_fen(fen)
        new_pos = apply_uci_move_white(pos, bestmove)
        assert is_checkmate(new_pos), (
            f"Move {bestmove} does not produce checkmate"
        )
    finally:
        engine.close()


# ---------------------------------------------------------------------------
# Test: Mate in 1 — Rook back-rank with pawns
# ---------------------------------------------------------------------------
def test_mate_in_1_rook_pawn_backrank():
    """6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1
    Ra8# is the only checkmate (back-rank mate, pawns trap king)."""
    fen = '6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1'
    engine = UCIEngine()
    try:
        engine.init_uci()
        bestmove = engine.get_bestmove(fen, depth=4)
        assert bestmove and bestmove != '(none)', f"No bestmove: {bestmove}"

        pos = from_fen(fen)
        new_pos = apply_uci_move_white(pos, bestmove)
        assert is_checkmate(new_pos), (
            f"Move {bestmove} does not produce checkmate"
        )
    finally:
        engine.close()


# ---------------------------------------------------------------------------
# Test: Mate in 1 — Scholar's mate (complex position)
# ---------------------------------------------------------------------------
def test_scholars_mate():
    """r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 0 4
    Qxf7# is the only checkmate."""
    fen = 'r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 0 4'
    engine = UCIEngine()
    try:
        engine.init_uci()
        bestmove = engine.get_bestmove(fen, depth=4)
        assert bestmove and bestmove != '(none)', f"No bestmove: {bestmove}"

        pos = from_fen(fen)
        new_pos = apply_uci_move_white(pos, bestmove)
        assert is_checkmate(new_pos), (
            f"Move {bestmove} does not produce checkmate"
        )
    finally:
        engine.close()


# ---------------------------------------------------------------------------
# Test: Mate in 1 — Double rook back-rank
# ---------------------------------------------------------------------------
def test_mate_in_1_double_rook():
    """6k1/5ppp/8/8/8/8/8/3RK2R w - - 0 1
    Rd8# is back-rank checkmate (Rh1 covers h8, pawns trap king)."""
    fen = '6k1/5ppp/8/8/8/8/8/3RK2R w - - 0 1'
    engine = UCIEngine()
    try:
        engine.init_uci()
        bestmove = engine.get_bestmove(fen, depth=4)
        assert bestmove and bestmove != '(none)', f"No bestmove: {bestmove}"

        pos = from_fen(fen)
        new_pos = apply_uci_move_white(pos, bestmove)
        assert is_checkmate(new_pos), (
            f"Move {bestmove} does not produce checkmate"
        )
    finally:
        engine.close()


# ---------------------------------------------------------------------------
# Test: Mate in 2
# ---------------------------------------------------------------------------
def test_mate_in_2():
    """k7/2p5/1K6/8/8/8/8/2R5 w - - 0 1
    1. Kxc7 Ka7 2. Ra1#"""
    fen = 'k7/2p5/1K6/8/8/8/8/2R5 w - - 0 1'
    engine = UCIEngine()
    try:
        engine.init_uci()
        bestmove = engine.get_bestmove(fen, depth=6)
        assert bestmove and bestmove != '(none)', f"No bestmove: {bestmove}"

        valid_first_moves = {'c1c7', 'b6c7'}
        assert bestmove in valid_first_moves, (
            f"Move {bestmove} is not a known mate-in-2 first move. "
            f"Expected one of {valid_first_moves}"
        )
    finally:
        engine.close()


# ---------------------------------------------------------------------------
# Test: Engine handles startpos
# ---------------------------------------------------------------------------
def test_startpos():
    """Engine must handle 'position startpos' and return a legal bestmove."""
    engine = UCIEngine()
    try:
        engine.init_uci()
        engine.send('isready')
        engine.read_until('readyok', timeout=10)
        engine.send('position startpos')
        engine.send('go depth 3')
        lines = engine.read_until('bestmove', timeout=60)
        bestmove = None
        for line in lines:
            if line.startswith('bestmove'):
                parts = line.split()
                if len(parts) >= 2:
                    bestmove = parts[1]
        assert bestmove and bestmove != '(none)', "No bestmove for startpos"
        assert len(bestmove) >= 4, f"Invalid move format: {bestmove}"
    finally:
        engine.close()


# ---------------------------------------------------------------------------
# Test: Engine handles position with moves
# ---------------------------------------------------------------------------
def test_position_with_moves():
    """Engine must handle 'position startpos moves e2e4 e7e5'."""
    engine = UCIEngine()
    try:
        engine.init_uci()
        engine.send('isready')
        engine.read_until('readyok', timeout=10)
        engine.send('position startpos moves e2e4 e7e5')
        engine.send('go depth 3')
        lines = engine.read_until('bestmove', timeout=60)
        bestmove = None
        for line in lines:
            if line.startswith('bestmove'):
                parts = line.split()
                if len(parts) >= 2:
                    bestmove = parts[1]
        assert bestmove and bestmove != '(none)', (
            "No bestmove for position with moves"
        )
    finally:
        engine.close()


# ---------------------------------------------------------------------------
# Test: Engine handles complex middlegame
# ---------------------------------------------------------------------------
def test_complex_middlegame():
    """A position with many pieces. Engine must not crash and must return
    a legal bestmove within a reasonable time."""
    fen = 'r1bqkbnr/pppppppp/2n5/8/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 0 2'
    engine = UCIEngine()
    try:
        engine.init_uci()
        engine.send('isready')
        engine.read_until('readyok', timeout=10)
        engine.send(f'position fen {fen}')
        engine.send('go depth 4')
        lines = engine.read_until('bestmove', timeout=90)
        bestmove = None
        for line in lines:
            if line.startswith('bestmove'):
                parts = line.split()
                if len(parts) >= 2:
                    bestmove = parts[1]
        assert bestmove and bestmove != '(none)', (
            "No bestmove for complex position"
        )
        assert len(bestmove) >= 4, f"Invalid move format: {bestmove}"
    finally:
        engine.close()


# ---------------------------------------------------------------------------
# Pipeline infrastructure and end-to-end tests
# ---------------------------------------------------------------------------
class TestPipeline:
    """Tests for the benchmarking pipeline (Makefile, run_suite.sh, SQLite, jq)."""

    @classmethod
    def setup_class(cls):
        """Run the full pipeline once for all pipeline tests."""
        subprocess.run(
            ['make', '-C', '/app', 'clean'],
            capture_output=True, timeout=30
        )
        result_test = subprocess.run(
            ['make', '-C', '/app', 'test'],
            capture_output=True, text=True, timeout=300
        )
        cls.make_test_rc = result_test.returncode
        cls.make_test_stderr = result_test.stderr
        cls.make_test_stdout = result_test.stdout

        result_report = subprocess.run(
            ['make', '-C', '/app', 'report'],
            capture_output=True, text=True, timeout=120
        )
        cls.make_report_rc = result_report.returncode
        cls.make_report_stderr = result_report.stderr

    def test_makefile_exists(self):
        """Makefile must exist at /app/Makefile."""
        assert os.path.isfile('/app/Makefile'), "Makefile not found at /app/Makefile"

    def test_run_suite_executable(self):
        """run_suite.sh must exist and be executable."""
        assert os.path.isfile('/app/run_suite.sh'), "run_suite.sh not found"
        assert os.access('/app/run_suite.sh', os.X_OK), "run_suite.sh not executable"

    def test_make_test_succeeds(self):
        """make test must complete successfully."""
        assert self.make_test_rc == 0, (
            f"make test failed (exit {self.make_test_rc}): "
            f"{self.make_test_stderr}\n{self.make_test_stdout}"
        )

    def test_database_exists(self):
        """results.db must be created by the pipeline."""
        assert os.path.isfile('/app/results.db'), "results.db not created"

    def test_database_schema(self):
        """results.db must have correct table schema."""
        import sqlite3 as sql
        conn = sql.connect('/app/results.db')
        cursor = conn.execute("PRAGMA table_info(results)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        required = {
            'id', 'fen', 'expected_moves', 'engine_move',
            'correct', 'depth', 'time_ms'
        }
        missing = required - columns
        assert not missing, f"Missing columns in results table: {missing}"

    def test_database_row_count(self):
        """results.db must have exactly 8 rows (one per test position)."""
        import sqlite3 as sql
        conn = sql.connect('/app/results.db')
        count = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        conn.close()
        assert count == 8, f"Expected 8 rows in results, got {count}"

    def test_make_report_succeeds(self):
        """make report must complete successfully."""
        assert self.make_report_rc == 0, (
            f"make report failed (exit {self.make_report_rc}): "
            f"{self.make_report_stderr}"
        )

    def test_report_structure(self):
        """report.json must have correct structure and fields."""
        assert os.path.isfile('/app/report.json'), "report.json not created"
        with open('/app/report.json') as f:
            report = json.load(f)
        assert 'total' in report, "Missing 'total' field in report"
        assert report['total'] == 8, f"Expected total=8, got {report.get('total')}"
        assert 'correct' in report, "Missing 'correct' field in report"
        assert isinstance(report['correct'], (int, float)), \
            f"'correct' must be a number, got {type(report['correct'])}"
        assert 'accuracy' in report, "Missing 'accuracy' field in report"
        assert isinstance(report['accuracy'], (int, float)), \
            f"'accuracy' must be a number, got {type(report['accuracy'])}"
        assert 'positions' in report, "Missing 'positions' field in report"
        assert isinstance(report['positions'], list), "'positions' must be an array"
        assert len(report['positions']) == 8, \
            f"Expected 8 positions in report, got {len(report['positions'])}"

    def test_report_accuracy(self):
        """Engine must solve at least 50% of test positions correctly."""
        with open('/app/report.json') as f:
            report = json.load(f)
        accuracy = report.get('accuracy', 0)
        assert accuracy >= 50, (
            f"Accuracy {accuracy}% is below 50% threshold. "
            f"Correct: {report.get('correct')}/{report.get('total')}"
        )
