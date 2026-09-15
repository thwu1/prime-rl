
import subprocess
import os
import pytest


# Standard English Draughts perft values from the initial position.
# Black moves first.
# Source: universally accepted values from the computer-checkers community.
EXPECTED_PERFT = {
    1: 7,
    2: 49,
    3: 302,
    4: 1469,
    5: 7361,
    6: 36768,
    7: 179740,
}


@pytest.fixture(scope="session")
def perft_binary():
    """Ensure the draughts file exists and the perft binary is compiled."""
    rbg_path = "/app/draughts.rbg"
    binary_path = "/app/perft_test"

    assert os.path.exists(rbg_path), (
        "draughts.rbg not found at /app/draughts.rbg"
    )
    assert os.path.exists(binary_path), (
        "perft_test binary not found — compilation may have failed"
    )

    return binary_path


def run_perft(binary: str, depth: int) -> int:
    """Run the perft binary at a given depth and parse the leaf count."""
    result = subprocess.run(
        [binary, str(depth)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"perft binary exited with code {result.returncode} at depth {depth}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    for line in result.stdout.splitlines():
        if line.strip().startswith("perft:"):
            count_str = line.split(":", 1)[1].strip()
            return int(count_str)

    raise ValueError(
        f"Could not find 'perft:' line in output at depth {depth}.\n"
        f"Full output:\n{result.stdout}"
    )


class TestDraughtsPerft:
    """Verify the draughts.rbg produces correct perft counts."""

    def test_rbg_file_exists(self):
        """The draughts.rbg file must exist."""
        assert os.path.exists("/app/draughts.rbg"), (
            "draughts.rbg not found at /app/draughts.rbg"
        )

    def test_perft_binary_exists(self):
        """The perft binary must have compiled successfully."""
        assert os.path.exists("/app/perft_test"), (
            "perft_test binary not found — RBG or C++ compilation failed"
        )

    def test_perft_depth_1(self, perft_binary):
        """Depth 1: 7 opening moves for black (4 pieces with 2 moves each,
        except the corner piece which has only 1)."""
        count = run_perft(perft_binary, 1)
        assert count == EXPECTED_PERFT[1], (
            f"Perft depth 1: got {count}, expected {EXPECTED_PERFT[1]}. "
            f"Basic man forward-diagonal movement is incorrect."
        )

    def test_perft_depth_2(self, perft_binary):
        """Depth 2: 49 positions (7 x 7 by symmetry)."""
        count = run_perft(perft_binary, 2)
        assert count == EXPECTED_PERFT[2], (
            f"Perft depth 2: got {count}, expected {EXPECTED_PERFT[2]}. "
            f"Both players' movement must be symmetric."
        )

    def test_perft_depth_3(self, perft_binary):
        """Depth 3: 302 leaf positions. Forced-capture rule begins
        to restrict available moves in some branches."""
        count = run_perft(perft_binary, 3)
        assert count == EXPECTED_PERFT[3], (
            f"Perft depth 3: got {count}, expected {EXPECTED_PERFT[3]}. "
            f"Capture mechanics or forced-capture enforcement is incorrect."
        )

    def test_perft_depth_4(self, perft_binary):
        """Depth 4: 1469 leaves. Multi-jump sequences and mandatory
        capture continuation are exercised."""
        count = run_perft(perft_binary, 4)
        assert count == EXPECTED_PERFT[4], (
            f"Perft depth 4: got {count}, expected {EXPECTED_PERFT[4]}. "
            f"Multi-jump or forced-capture continuation is incorrect."
        )

    def test_perft_depth_5(self, perft_binary):
        """Depth 5: 7361 leaves. Deeper tactical interactions."""
        count = run_perft(perft_binary, 5)
        assert count == EXPECTED_PERFT[5], (
            f"Perft depth 5: got {count}, expected {EXPECTED_PERFT[5]}. "
            f"Complex capture sequences or move generation is incorrect."
        )

    def test_perft_depth_6(self, perft_binary):
        """Depth 6: 36768 leaves. King promotion and its interaction
        with capture sequences may begin to appear."""
        count = run_perft(perft_binary, 6)
        assert count == EXPECTED_PERFT[6], (
            f"Perft depth 6: got {count}, expected {EXPECTED_PERFT[6]}. "
            f"King promotion or promotion-stops-jump rule may be incorrect."
        )

    def test_perft_depth_7(self, perft_binary):
        """Depth 7: 179740 leaves. Comprehensive coverage of all rule
        interactions including king movement, multi-jumps, and forced captures."""
        count = run_perft(perft_binary, 7)
        assert count == EXPECTED_PERFT[7], (
            f"Perft depth 7: got {count}, expected {EXPECTED_PERFT[7]}. "
            f"Rule interaction at depth is incorrect — check all edge cases."
        )
