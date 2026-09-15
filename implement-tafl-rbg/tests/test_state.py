"""
Tests for the Isolation Breakthrough RBG implementation.
Compiles both a reference and the agent's .rbg file, builds perft binaries,
and compares exhaustive move-tree counts at multiple depths.
Additionally tests capture mechanics using custom board positions.

"""

import subprocess
import os
import pytest

RBG2CPP = "/app/rbg_system/rbg2cpp/bin/rbg2cpp"
PERFT_SRC = "/tests/perft.cpp"
REFERENCE_RBG = "/tests/reference_game.rbg"
AGENT_RBG = "/app/isolation_breakthrough.rbg"

COMPILE_FLAGS = ["-O2", "-std=c++20", "-DRBG_RANDOM_GENERATOR=0", "-DNDEBUG"]


# ---------------------------------------------------------------------------
# Custom board definitions for targeted capture tests
# ---------------------------------------------------------------------------

# Board where white can create a custodial capture of an isolated black piece.
# After white moves (0,2)->(0,1), black at (2,1) is isolated and sandwiched
# between white at (1,1) and (3,1).
CAPTURE_BOARD = """#board = rectangle(up,down,left,right,
         [b, e, e, e, e, b]
         [e, w, b, w, e, e]
         [w, e, e, e, e, e]
         [e, e, e, e, e, e]
         [e, e, e, e, e, e]
         [e, e, e, e, e, e])"""

# Board where the sandwiched black piece is NOT isolated (adjacent friendly
# piece above at (2,0)), so the isolation rule should prevent the capture.
SHIELD_BOARD = """#board = rectangle(up,down,left,right,
         [e, e, b, e, e, b]
         [e, w, b, w, e, e]
         [w, e, e, e, e, e]
         [e, e, e, e, e, e]
         [e, e, e, e, e, e]
         [e, e, e, e, e, e])"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def replace_board(content, new_board):
    """Replace the #board = rectangle(...) section in an RBG file."""
    board_start = content.find("#board")
    if board_start == -1:
        raise ValueError("Could not find #board in the file")

    rect_start = content.find("rectangle(", board_start)
    if rect_start == -1:
        raise ValueError("Could not find rectangle( after #board")

    depth = 0
    i = rect_start
    board_end = None
    while i < len(content):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                board_end = i + 1
                break
        i += 1

    if board_end is None:
        raise ValueError("Could not find matching ) for rectangle(")

    return content[:board_start] + new_board + content[board_end:]


def build_perft_binary(rbg_file, workdir):
    """Compile an RBG file into a perft test binary. Returns the binary path."""
    os.makedirs(workdir, exist_ok=True)

    result = subprocess.run(
        [RBG2CPP, "-o", "reasoner", os.path.abspath(rbg_file)],
        cwd=workdir,
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"rbg2cpp failed for {rbg_file}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    result = subprocess.run(
        ["g++", "-c", "-o", os.path.join(workdir, "reasoner.o"),
         os.path.join(workdir, "reasoner.cpp")]
        + COMPILE_FLAGS + [f"-I{workdir}"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Reasoner compilation failed:\n{result.stderr}")

    result = subprocess.run(
        ["g++", "-c", "-o", os.path.join(workdir, "perft.o"), PERFT_SRC]
        + COMPILE_FLAGS + [f"-I{workdir}"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Perft harness compilation failed:\n{result.stderr}")

    binary = os.path.join(workdir, "perft")
    result = subprocess.run(
        ["g++", "-o", binary,
         os.path.join(workdir, "reasoner.o"),
         os.path.join(workdir, "perft.o")]
        + COMPILE_FLAGS,
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Linking failed:\n{result.stderr}")

    return binary


def build_perft_from_content(rbg_content, workdir):
    """Write RBG content to a temp file and build a perft binary."""
    os.makedirs(workdir, exist_ok=True)
    rbg_path = os.path.join(workdir, "game.rbg")
    with open(rbg_path, "w") as f:
        f.write(rbg_content)
    return build_perft_binary(rbg_path, workdir)


def run_perft(binary, depth, timeout=120):
    """Run a perft binary at the given depth and return the leaf count."""
    result = subprocess.run(
        [binary, str(depth)],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Perft execution failed (depth {depth}):\n{result.stdout}\n{result.stderr}"
        )
    for line in result.stdout.strip().split("\n"):
        if line.startswith("perft:"):
            return int(line.split(":")[1].strip())
    raise RuntimeError(f"Could not parse perft output:\n{result.stdout}")


# ---------------------------------------------------------------------------
# Fixtures — build once per module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def reference_binary():
    return build_perft_binary(REFERENCE_RBG, "/tmp/ref_build")


@pytest.fixture(scope="module")
def agent_binary():
    return build_perft_binary(AGENT_RBG, "/tmp/agent_build")


@pytest.fixture(scope="module")
def agent_content():
    with open(AGENT_RBG) as f:
        return f.read()


@pytest.fixture(scope="module")
def reference_content():
    with open(REFERENCE_RBG) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Standard game tests (6x6 board, depths 1-4)
# ---------------------------------------------------------------------------

class TestIsolationBreakthroughRBG:
    """Verify the agent's Isolation Breakthrough RBG implementation."""

    def test_file_exists(self):
        assert os.path.isfile(AGENT_RBG), f"{AGENT_RBG} does not exist"

    def test_compiles_with_rbg2cpp(self):
        """The .rbg file must be accepted by the rbg2cpp compiler."""
        workdir = "/tmp/compile_check"
        os.makedirs(workdir, exist_ok=True)
        result = subprocess.run(
            [RBG2CPP, "-o", "reasoner", os.path.abspath(AGENT_RBG)],
            cwd=workdir,
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"rbg2cpp rejected {AGENT_RBG}:\n{result.stderr}"
        )

    def test_perft_depth1(self, reference_binary, agent_binary):
        expected = run_perft(reference_binary, 1)
        actual = run_perft(agent_binary, 1)
        assert actual == expected, (
            f"Perft depth 1 mismatch: expected {expected}, got {actual}"
        )

    def test_perft_depth2(self, reference_binary, agent_binary):
        expected = run_perft(reference_binary, 2)
        actual = run_perft(agent_binary, 2)
        assert actual == expected, (
            f"Perft depth 2 mismatch: expected {expected}, got {actual}"
        )

    def test_perft_depth3(self, reference_binary, agent_binary):
        expected = run_perft(reference_binary, 3)
        actual = run_perft(agent_binary, 3)
        assert actual == expected, (
            f"Perft depth 3 mismatch: expected {expected}, got {actual}"
        )

    def test_perft_depth4(self, reference_binary, agent_binary):
        expected = run_perft(reference_binary, 4, timeout=180)
        actual = run_perft(agent_binary, 4, timeout=180)
        assert actual == expected, (
            f"Perft depth 4 mismatch: expected {expected}, got {actual}"
        )


# ---------------------------------------------------------------------------
# Targeted capture-mechanics tests (custom boards)
# ---------------------------------------------------------------------------

class TestCaptureMechanics:
    """Verify custodial capture and isolation shield using custom boards."""

    def test_capture_isolated_piece(self, agent_content, reference_content):
        """On the capture board, an isolated+sandwiched piece must be captured.
        The reference and agent should agree on perft(2)."""
        ref_modified = replace_board(reference_content, CAPTURE_BOARD)
        ref_binary = build_perft_from_content(ref_modified, "/tmp/cap_ref")

        agent_modified = replace_board(agent_content, CAPTURE_BOARD)
        agent_binary = build_perft_from_content(agent_modified, "/tmp/cap_agent")

        expected = run_perft(ref_binary, 2)
        actual = run_perft(agent_binary, 2)
        assert actual == expected, (
            f"Capture-board perft(2) mismatch: expected {expected}, got {actual}. "
            f"The custodial capture of isolated pieces may be incorrect."
        )

    def test_shield_prevents_capture(self, agent_content, reference_content):
        """On the shield board, a sandwiched but non-isolated piece must NOT
        be captured. The reference and agent should agree on perft(2)."""
        ref_modified = replace_board(reference_content, SHIELD_BOARD)
        ref_binary = build_perft_from_content(ref_modified, "/tmp/shd_ref")

        agent_modified = replace_board(agent_content, SHIELD_BOARD)
        agent_binary = build_perft_from_content(agent_modified, "/tmp/shd_agent")

        expected = run_perft(ref_binary, 2)
        actual = run_perft(agent_binary, 2)
        assert actual == expected, (
            f"Shield-board perft(2) mismatch: expected {expected}, got {actual}. "
            f"The isolation condition for custodial capture may be incorrect."
        )

    def test_capture_vs_shield_differ(self, reference_content):
        """The capture and shield boards must produce different perft(2) counts
        in the reference, confirming the isolation rule is load-bearing."""
        cap_binary = build_perft_from_content(
            replace_board(reference_content, CAPTURE_BOARD), "/tmp/cap_ref2"
        )
        shd_binary = build_perft_from_content(
            replace_board(reference_content, SHIELD_BOARD), "/tmp/shd_ref2"
        )
        cap_count = run_perft(cap_binary, 2)
        shd_count = run_perft(shd_binary, 2)
        assert cap_count != shd_count, (
            f"Capture and shield boards produced the same perft(2)={cap_count}. "
            f"The test boards may not be exercising the isolation rule."
        )
