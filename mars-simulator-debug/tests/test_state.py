"""
Test suite for Core War gauntlet challenger.
Verifies that /app/challenger.red is a valid, competitive ICWS'94 warrior
that performs well against the 5 opponents on the hill.

"""
import subprocess
import os
import hashlib
import pytest

PMARS = "/usr/local/bin/pmars"
OPPONENTS_DIR = "/app/opponents"
CHALLENGER = "/app/challenger.red"

CORE_SIZE = 8000
MAX_PROCS = 8000
MAX_CYCLES = 80000
ROUNDS = 200
FIXED_POS = 4000

OPPONENTS = ["imp.red", "dwarf.red", "stone.red", "scanner.red", "splitter.red"]

# Minimum per-opponent wins required
MIN_WINS_PER_OPP = 1
# Minimum per-opponent non-losses (wins + ties)
MIN_NONLOSS_PER_OPP = 40
# Minimum total wins across all matchups
MIN_TOTAL_WINS = 200
# Maximum instructions allowed
MAX_INSTRUCTIONS = 100

VALID_OPCODES = frozenset([
    'DAT', 'MOV', 'ADD', 'SUB', 'MUL', 'DIV', 'MOD',
    'JMP', 'JMZ', 'JMN', 'DJN', 'CMP', 'SEQ', 'SNE',
    'SLT', 'SPL', 'NOP'
])


def run_pmars(w1, w2, rounds=ROUNDS):
    """Run pMARS battle and return (w1_wins, w2_wins, ties).

    pMARS -k output for 2 warriors:
        warrior0_wins warrior0_ties
        warrior1_wins warrior1_ties
    """
    cmd = [PMARS,
           "-s", str(CORE_SIZE), "-p", str(MAX_PROCS),
           "-c", str(MAX_CYCLES), "-r", str(rounds),
           "-k", "-b", "-F", str(FIXED_POS),
           w1, w2]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, (
        f"pMARS exited {result.returncode}: {result.stderr[:500]}"
    )
    lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
    assert len(lines) >= 2, f"Unexpected pMARS output:\n{result.stdout[:500]}"

    w1_parts = lines[-2].split()
    w2_parts = lines[-1].split()
    w1_wins = int(w1_parts[0])
    w1_ties = int(w1_parts[1])
    w2_wins = int(w2_parts[0])
    w2_ties = int(w2_parts[1])
    assert w1_ties == w2_ties, f"Tie mismatch: {w1_ties} != {w2_ties}"
    assert w1_wins + w2_wins + w1_ties == rounds, (
        f"Score total {w1_wins + w2_wins + w1_ties} != {rounds}"
    )
    return w1_wins, w2_wins, w1_ties


def count_instructions(filepath):
    """Count the number of Redcode instructions in a warrior file.

    Handles labels with and without colons (e.g., 'bomb DAT #0, #0'
    and 'bomb: DAT #0, #0').
    """
    directives = frozenset(['FOR', 'ROF', 'ORG', 'END', 'EQU', 'PIN'])
    count = 0
    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith(';'):
                continue
            # Strip inline comments
            if ';' in stripped:
                stripped = stripped[:stripped.index(';')].strip()
            if not stripped:
                continue
            tokens = stripped.split()
            # Scan the first few tokens for an opcode
            found = False
            for tok in tokens[:3]:
                if tok.endswith(':'):
                    continue  # colon-style label
                upper = tok.upper().split('.')[0]
                if upper in VALID_OPCODES:
                    count += 1
                    found = True
                    break
                elif upper in directives:
                    found = True
                    break
                # Otherwise it might be a bare label — check next token
            if found:
                continue
    return count


def file_hash(filepath):
    """Compute SHA-256 hash of file contents (ignoring trailing whitespace)."""
    with open(filepath) as f:
        content = f.read().strip()
    return hashlib.sha256(content.encode()).hexdigest()


# ---------- Fixtures ----------

@pytest.fixture(scope="module")
def gauntlet_results():
    """Run the challenger against every opponent and cache the results.

    Returns dict: opponent_name -> (challenger_wins, opponent_wins, ties)
    """
    assert os.path.exists(CHALLENGER), (
        f"Challenger file not found at {CHALLENGER}"
    )
    results = {}
    for opp in OPPONENTS:
        opp_path = os.path.join(OPPONENTS_DIR, opp)
        assert os.path.exists(opp_path), f"Opponent not found: {opp_path}"
        results[opp] = run_pmars(CHALLENGER, opp_path, ROUNDS)
    return results


# ---------- Validity tests ----------

class TestChallengerValidity:
    """Verify the challenger warrior file meets format requirements."""

    def test_file_exists(self):
        assert os.path.exists(CHALLENGER), (
            f"No warrior found at {CHALLENGER}"
        )

    def test_parseable_by_pmars(self):
        """pMARS must be able to load the warrior without errors."""
        # Run a 1-round self-play to verify parsing
        result = subprocess.run(
            [PMARS, "-s", str(CORE_SIZE), "-p", str(MAX_PROCS),
             "-c", "1", "-r", "1", "-k", "-b",
             "-F", str(FIXED_POS), CHALLENGER, CHALLENGER],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"pMARS cannot parse challenger:\n{result.stderr[:500]}"
        )

    def test_instruction_count(self):
        """Warrior must contain between 1 and 100 instructions."""
        n = count_instructions(CHALLENGER)
        assert 1 <= n <= MAX_INSTRUCTIONS, (
            f"Challenger has {n} instructions (must be 1-{MAX_INSTRUCTIONS})"
        )

    def test_not_identical_to_opponent(self):
        """Challenger must not be a verbatim copy of any opponent."""
        challenger_hash = file_hash(CHALLENGER)
        for opp in OPPONENTS:
            opp_hash = file_hash(os.path.join(OPPONENTS_DIR, opp))
            assert challenger_hash != opp_hash, (
                f"Challenger is identical to opponent {opp}"
            )


# ---------- Per-opponent performance tests ----------

class TestPerOpponentPerformance:
    """Each matchup must meet minimum win and resilience thresholds."""

    def test_wins_vs_imp(self, gauntlet_results):
        wins, losses, ties = gauntlet_results["imp.red"]
        assert wins >= MIN_WINS_PER_OPP, (
            f"vs imp.red: {wins}W {losses}L {ties}T — need >= {MIN_WINS_PER_OPP} wins"
        )
        assert wins + ties >= MIN_NONLOSS_PER_OPP, (
            f"vs imp.red: wins+ties={wins + ties}, need >= {MIN_NONLOSS_PER_OPP}"
        )

    def test_wins_vs_dwarf(self, gauntlet_results):
        wins, losses, ties = gauntlet_results["dwarf.red"]
        assert wins >= MIN_WINS_PER_OPP, (
            f"vs dwarf.red: {wins}W {losses}L {ties}T — need >= {MIN_WINS_PER_OPP} wins"
        )
        assert wins + ties >= MIN_NONLOSS_PER_OPP, (
            f"vs dwarf.red: wins+ties={wins + ties}, need >= {MIN_NONLOSS_PER_OPP}"
        )

    def test_wins_vs_stone(self, gauntlet_results):
        wins, losses, ties = gauntlet_results["stone.red"]
        assert wins >= MIN_WINS_PER_OPP, (
            f"vs stone.red: {wins}W {losses}L {ties}T — need >= {MIN_WINS_PER_OPP} wins"
        )
        assert wins + ties >= MIN_NONLOSS_PER_OPP, (
            f"vs stone.red: wins+ties={wins + ties}, need >= {MIN_NONLOSS_PER_OPP}"
        )

    def test_wins_vs_scanner(self, gauntlet_results):
        wins, losses, ties = gauntlet_results["scanner.red"]
        assert wins >= MIN_WINS_PER_OPP, (
            f"vs scanner.red: {wins}W {losses}L {ties}T — need >= {MIN_WINS_PER_OPP} wins"
        )
        assert wins + ties >= MIN_NONLOSS_PER_OPP, (
            f"vs scanner.red: wins+ties={wins + ties}, need >= {MIN_NONLOSS_PER_OPP}"
        )

    def test_wins_vs_splitter(self, gauntlet_results):
        wins, losses, ties = gauntlet_results["splitter.red"]
        assert wins >= MIN_WINS_PER_OPP, (
            f"vs splitter.red: {wins}W {losses}L {ties}T — need >= {MIN_WINS_PER_OPP} wins"
        )
        assert wins + ties >= MIN_NONLOSS_PER_OPP, (
            f"vs splitter.red: wins+ties={wins + ties}, need >= {MIN_NONLOSS_PER_OPP}"
        )


# ---------- Aggregate performance test ----------

class TestAggregatePerformance:
    """Overall hill score must exceed the minimum threshold."""

    def test_total_wins(self, gauntlet_results):
        total_wins = sum(gauntlet_results[opp][0] for opp in OPPONENTS)
        total_rounds = ROUNDS * len(OPPONENTS)
        pct = 100.0 * total_wins / total_rounds
        assert total_wins >= MIN_TOTAL_WINS, (
            f"Aggregate: {total_wins}/{total_rounds} wins ({pct:.1f}%), "
            f"need >= {MIN_TOTAL_WINS}"
        )

    def test_total_nonlosses(self, gauntlet_results):
        """Aggregate wins + ties should dominate."""
        total_nonloss = sum(
            gauntlet_results[opp][0] + gauntlet_results[opp][2]
            for opp in OPPONENTS
        )
        total_rounds = ROUNDS * len(OPPONENTS)
        # Must not lose more than 70% overall
        assert total_nonloss >= total_rounds * 0.30, (
            f"Aggregate non-losses: {total_nonloss}/{total_rounds} "
            f"({100.0 * total_nonloss / total_rounds:.1f}%), need >= 30%"
        )


# ---------- Anti-trivial solution tests ----------

class TestNonTrivialSolution:
    """Ensure the warrior represents genuine strategic design."""

    def test_not_pure_imp(self, gauntlet_results):
        """A pure imp (MOV $0, $1) ties everything and wins nothing.
        The aggregate wins check already prevents this, but this test
        documents the intent."""
        total_wins = sum(gauntlet_results[opp][0] for opp in OPPONENTS)
        assert total_wins > 0, "Warrior appears to be a non-competitive design (0 total wins)"

    def test_not_passive(self, gauntlet_results):
        """Warrior must actively win rounds, not just survive."""
        total_wins = sum(gauntlet_results[opp][0] for opp in OPPONENTS)
        total_ties = sum(gauntlet_results[opp][2] for opp in OPPONENTS)
        # Must have more wins than just ties
        assert total_wins >= 50, (
            f"Warrior too passive: only {total_wins} wins vs {total_ties} ties"
        )
