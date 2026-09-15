
import subprocess
import json
import os
import sys
import chess

TIMEOUT = 120


def compile_perft():
    """Build all targets using /app/Makefile."""
    result = subprocess.run(
        ["make", "-C", "/app"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"Build failed:\n{result.stderr}"


def run_perft(fen, depth):
    """Run the perft binary and parse its key: value output."""
    result = subprocess.run(
        ["/app/perft", fen, str(depth)],
        capture_output=True, text=True, timeout=TIMEOUT
    )
    assert result.returncode == 0, (
        f"perft returned {result.returncode}\nstderr: {result.stderr}\nstdout: {result.stdout}"
    )
    stats = {}
    for line in result.stdout.strip().split('\n'):
        if ':' not in line:
            continue
        key, val = line.split(':', 1)
        stats[key.strip()] = int(val.strip())
    return stats


def python_perft(board, depth):
    """Compute extended perft stats using chess library as an authoritative oracle."""
    stats = {
        "nodes": 0, "captures": 0, "ep": 0, "castles": 0,
        "promotions": 0, "checks": 0, "checkmates": 0
    }

    for move in board.legal_moves:
        is_capture = board.is_capture(move)
        is_ep = board.is_en_passant(move)
        is_castle = board.is_castling(move)
        is_promo = move.promotion is not None

        board.push(move)

        if depth == 1:
            stats["nodes"] += 1
            if is_capture:
                stats["captures"] += 1
            if is_ep:
                stats["ep"] += 1
            if is_castle:
                stats["castles"] += 1
            if is_promo:
                stats["promotions"] += 1
            if board.is_check():
                stats["checks"] += 1
                if board.is_checkmate():
                    stats["checkmates"] += 1
        else:
            sub = python_perft(board, depth - 1)
            for k in stats:
                stats[k] += sub[k]

        board.pop()

    return stats


CHESS960_POSITIONS = {
    "pos1": "nrkbbqrn/pppppppp/8/8/8/8/PPPPPPPP/NRKBBQRN w BGbg - 0 1",
    "pos2": "rbbkrqnn/pppppppp/8/8/8/8/PPPPPPPP/RBBKRQNN w AEae - 0 1",
    "pos3": "qnrbbnkr/pppppppp/8/8/8/8/PPPPPPPP/QNRBBNKR w HChc - 0 1",
}


# ============================================================
# Build artifact and tooling tests
# ============================================================
class TestBuildArtifacts:
    """Verify shared library, header, ctypes bridge, and binary exist."""

    def test_binary_exists(self):
        assert os.path.isfile("/app/perft"), "/app/perft not found"

    def test_shared_library_exists(self):
        assert os.path.isfile("/app/libperft960.so"), "/app/libperft960.so not found"

    def test_header_exists(self):
        assert os.path.isfile("/app/perft960.h"), "/app/perft960.h not found"

    def test_bridge_exists(self):
        assert os.path.isfile("/app/perft_bridge.py"), "/app/perft_bridge.py not found"

    def test_shared_library_exports_parse_fen(self):
        """Verify libperft960.so exports parse_fen as a dynamic symbol."""
        result = subprocess.run(
            ["nm", "-D", "/app/libperft960.so"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"nm -D failed: {result.stderr}"
        symbol_names = []
        for line in result.stdout.strip().split('\n'):
            parts = line.split()
            if len(parts) >= 3:
                symbol_names.append(parts[2])
            elif len(parts) == 2:
                symbol_names.append(parts[1])
        assert "parse_fen" in symbol_names, (
            f"parse_fen not found in dynamic symbols. Found: {symbol_names[:20]}"
        )

    def test_shared_library_exports_perft(self):
        """Verify libperft960.so exports perft as a dynamic symbol."""
        result = subprocess.run(
            ["nm", "-D", "/app/libperft960.so"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"nm -D failed: {result.stderr}"
        symbol_names = []
        for line in result.stdout.strip().split('\n'):
            parts = line.split()
            if len(parts) >= 3:
                symbol_names.append(parts[2])
            elif len(parts) == 2:
                symbol_names.append(parts[1])
        assert "perft" in symbol_names, (
            f"perft not found in dynamic symbols. Found: {symbol_names[:20]}"
        )

    def test_makefile_shared_library_target(self):
        """Verify Makefile builds shared library with correct flags."""
        with open("/app/Makefile") as f:
            content = f.read()
        assert "libperft960.so" in content, "Makefile missing libperft960.so target"
        assert "-shared" in content, "Makefile missing -shared flag"
        assert "-fPIC" in content, "Makefile missing -fPIC flag"

    def test_header_declares_structs(self):
        """Verify perft960.h declares Board and Stats structs."""
        with open("/app/perft960.h") as f:
            content = f.read()
        assert "Board" in content, "perft960.h missing Board declaration"
        assert "Stats" in content, "perft960.h missing Stats declaration"
        assert "parse_fen" in content, "perft960.h missing parse_fen prototype"
        assert "perft" in content, "perft960.h missing perft prototype"


# ============================================================
# Python ctypes bridge tests
# ============================================================
class TestCtypesBridge:
    """Verify the Python ctypes bridge loads the .so and works correctly."""

    @classmethod
    def setup_class(cls):
        compile_perft()
        if '/app' not in sys.path:
            sys.path.insert(0, '/app')

    def test_bridge_imports(self):
        """The bridge module must be importable and have run_perft."""
        if 'perft_bridge' in sys.modules:
            del sys.modules['perft_bridge']
        import perft_bridge
        assert hasattr(perft_bridge, 'run_perft'), "run_perft function not found in perft_bridge"

    def test_bridge_standard_chess(self):
        """Bridge must produce correct standard chess perft via ctypes."""
        if 'perft_bridge' in sys.modules:
            del sys.modules['perft_bridge']
        import perft_bridge
        result = perft_bridge.run_perft(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 4
        )
        assert result["nodes"] == 197281, f"nodes: {result['nodes']}"

    def test_bridge_chess960_oracle(self):
        """Bridge must match chess library oracle on a Chess960 position."""
        if 'perft_bridge' in sys.modules:
            del sys.modules['perft_bridge']
        import perft_bridge
        fen = CHESS960_POSITIONS["pos1"]
        result = perft_bridge.run_perft(fen, 3)
        board = chess.Board(fen, chess960=True)
        expected = python_perft(board, 3)
        for k in expected:
            assert result[k] == expected[k], (
                f"ctypes bridge pos1 depth 3 {k}: got {result[k]}, expected {expected[k]}"
            )


# ============================================================
# Valgrind memcheck tests
# ============================================================
class TestValgrind:
    """Verify Valgrind memcheck report exists and shows zero errors."""

    def test_report_exists(self):
        assert os.path.isfile("/app/valgrind_report.txt"), (
            "/app/valgrind_report.txt not found"
        )

    def test_zero_errors(self):
        with open("/app/valgrind_report.txt") as f:
            content = f.read()
        assert "ERROR SUMMARY: 0 errors" in content, (
            f"Valgrind reported errors. Tail of report:\n{content[-500:]}"
        )

    def test_report_mentions_memcheck(self):
        """Confirm the report was actually produced by memcheck."""
        with open("/app/valgrind_report.txt") as f:
            content = f.read()
        assert "Memcheck" in content or "memcheck" in content, (
            "Report does not appear to be from Valgrind memcheck"
        )


# ============================================================
# Standard chess tests (hardcoded reference values)
# ============================================================
class TestStandardChess:
    """Verify standard chess perft still works after Chess960 extension."""

    @classmethod
    def setup_class(cls):
        compile_perft()

    def test_initial_position_depth5(self):
        """Initial position: baseline correctness."""
        stats = run_perft(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 5
        )
        assert stats['nodes'] == 4865609, f"got {stats['nodes']}"

    def test_kiwipete_depth4(self):
        """Position 2 (Kiwipete): exercises castling, captures, promotions."""
        stats = run_perft(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -", 4
        )
        assert stats['nodes'] == 4085603, f"nodes: got {stats['nodes']}"
        assert stats['captures'] == 757163, f"captures: got {stats['captures']}"
        assert stats['ep'] == 1929, f"ep: got {stats['ep']}"
        assert stats['castles'] == 128013, f"castles: got {stats['castles']}"
        assert stats['promotions'] == 15172, f"promotions: got {stats['promotions']}"
        assert stats['checks'] == 25523, f"checks: got {stats['checks']}"

    def test_position5_depth4(self):
        """Position 5: promotion-heavy, tests underpromotion generation."""
        stats = run_perft(
            "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 4
        )
        assert stats['nodes'] == 2103487, f"got {stats['nodes']}"


# ============================================================
# Chess960 tests (chess library oracle verification)
# ============================================================
class TestChess960:
    """Verify Chess960 perft against chess library oracle."""

    @classmethod
    def setup_class(cls):
        compile_perft()

    def test_position1_depth3(self):
        """NRKBBQRN at depth 3: king c1, rooks b1/g1."""
        fen = CHESS960_POSITIONS["pos1"]
        c_stats = run_perft(fen, 3)
        board = chess.Board(fen, chess960=True)
        py_stats = python_perft(board, 3)
        for k in py_stats:
            assert c_stats[k] == py_stats[k], (
                f"pos1 depth 3 {k}: C={c_stats[k]} chess={py_stats[k]}"
            )

    def test_position2_depth3(self):
        """RBBKRQNN at depth 3: king d1, rooks a1/e1."""
        fen = CHESS960_POSITIONS["pos2"]
        c_stats = run_perft(fen, 3)
        board = chess.Board(fen, chess960=True)
        py_stats = python_perft(board, 3)
        for k in py_stats:
            assert c_stats[k] == py_stats[k], (
                f"pos2 depth 3 {k}: C={c_stats[k]} chess={py_stats[k]}"
            )

    def test_position3_depth3(self):
        """QNRBBNKR at depth 3: king g1, rooks c1/h1."""
        fen = CHESS960_POSITIONS["pos3"]
        c_stats = run_perft(fen, 3)
        board = chess.Board(fen, chess960=True)
        py_stats = python_perft(board, 3)
        for k in py_stats:
            assert c_stats[k] == py_stats[k], (
                f"pos3 depth 3 {k}: C={c_stats[k]} chess={py_stats[k]}"
            )

    def test_chess960_castling_minimal(self):
        """Minimal position: immediate Chess960 castling both sides."""
        fen = "k7/8/8/8/8/8/8/1RK3R1 w BG - 0 1"
        c_stats = run_perft(fen, 1)
        board = chess.Board(fen, chess960=True)
        py_stats = python_perft(board, 1)
        for k in py_stats:
            assert c_stats[k] == py_stats[k], (
                f"minimal castling {k}: C={c_stats[k]} chess={py_stats[k]}"
            )

    def test_chess960_king_stays_castle(self):
        """Edge case: king already on c1, queenside castling = king stays, rook moves."""
        fen = "k7/8/8/8/8/8/8/1RK5 w B - 0 1"
        c_stats = run_perft(fen, 1)
        board = chess.Board(fen, chess960=True)
        py_stats = python_perft(board, 1)
        for k in py_stats:
            assert c_stats[k] == py_stats[k], (
                f"king-stays castling {k}: C={c_stats[k]} chess={py_stats[k]}"
            )

    def test_chess960_rook_dest_is_king_origin(self):
        """Edge case: queenside castling rook destination = king's origin square."""
        fen = "k7/8/8/8/8/8/8/R2K4 w A - 0 1"
        c_stats = run_perft(fen, 1)
        board = chess.Board(fen, chess960=True)
        py_stats = python_perft(board, 1)
        for k in py_stats:
            assert c_stats[k] == py_stats[k], (
                f"rook-to-king-origin {k}: C={c_stats[k]} chess={py_stats[k]}"
            )


# ============================================================
# results.json verification
# ============================================================
class TestResultsJSON:
    """Verify /app/results.json contains correct Chess960 perft stats."""

    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "/app/results.json not found"

    def test_results_correct(self):
        with open("/app/results.json") as f:
            data = json.load(f)

        for pos_name, fen in CHESS960_POSITIONS.items():
            assert pos_name in data, f"Missing {pos_name} in results.json"
            board = chess.Board(fen, chess960=True)
            expected = python_perft(board, 4)
            actual = data[pos_name]
            for k in expected:
                assert actual[k] == expected[k], (
                    f"{pos_name} depth 4 {k}: got {actual[k]}, expected {expected[k]}"
                )
