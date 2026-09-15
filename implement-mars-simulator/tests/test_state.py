
import subprocess
import sys
import os
import importlib.util
import pytest
from collections import deque

MARS_PATH = "/app/mars.py"
WARRIORS_DIR = "/app/warriors"

# ====================================================================
# Load mars.py as a module for unit testing
# ====================================================================

def load_mars_module():
    spec = importlib.util.spec_from_file_location("mars", MARS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def mars_mod():
    return load_mars_module()


# ====================================================================
# Module-level unit tests (import mars.py, test internal behavior)
# ====================================================================

class TestSPLQueueOrder:
    """SPL must queue PC+1 FIRST, then A-target.
    ICWS'94 5.5.15: SPL queues the next instruction (PC+1) and then
    queues the sum of the program counter and the A-pointer."""

    def test_spl_queues_pc_plus_1_before_target(self, mars_mod):
        sim = mars_mod.MARS(core_size=200, max_cycles=1000, max_processes=100,
                            max_length=50, min_distance=50)
        sim.init_core()

        # Place SPL.B $15, #0 at position 10
        instr = mars_mod.Instruction(
            mars_mod.SPL, mars_mod.mB, mars_mod.DIRECT, 15,
            mars_mod.IMMEDIATE, 0, mars_mod.PMARS_OP['SPL']
        )
        sim.core[10] = instr

        queue = deque()
        result = sim.execute(10, queue)
        assert result is True, "SPL should not kill the process"
        assert len(queue) == 2, f"SPL should queue 2 tasks, got {len(queue)}"
        assert queue[0] == 11, f"First queued should be PC+1=11, got {queue[0]}"
        assert queue[1] == 25, f"Second queued should be target=25, got {queue[1]}"


class TestCMPIFullComparison:
    """CMP.I / SEQ.I must compare the ENTIRE instruction — opcode,
    modifier, and addressing modes — not just field values.
    ICWS'94 5.4.7 and 5.5.12: CMP.I compares A-instruction to B-instruction."""

    def test_cmp_i_different_opcodes_same_values(self, mars_mod):
        sim = mars_mod.MARS(core_size=200, max_cycles=1000, max_processes=100,
                            max_length=50, min_distance=50)
        sim.init_core()

        # Position 50: SEQ.I $10, $20 (compare pos 60 vs pos 70)
        cmp_instr = mars_mod.Instruction(
            mars_mod.CMP, mars_mod.mI, mars_mod.DIRECT, 10,
            mars_mod.DIRECT, 20, mars_mod.PMARS_OP['CMP']
        )
        sim.core[50] = cmp_instr

        # Position 60: MOV.A $0, $0
        instr_a = mars_mod.Instruction(
            mars_mod.MOV, mars_mod.mA, mars_mod.DIRECT, 0,
            mars_mod.DIRECT, 0, mars_mod.PMARS_OP['MOV']
        )
        sim.core[60] = instr_a

        # Position 70: DAT.F $0, $0 (different opcode/modifier, same values)
        instr_b = mars_mod.Instruction(
            mars_mod.DAT, mars_mod.mF, mars_mod.DIRECT, 0,
            mars_mod.DIRECT, 0, mars_mod.PMARS_OP['DAT']
        )
        sim.core[70] = instr_b

        queue = deque()
        result = sim.execute(50, queue)
        assert result is True
        assert len(queue) == 1
        # Different opcodes → NOT equal → queue PC+1 = 51
        assert queue[0] == 51, (
            f"CMP.I with different opcodes should NOT skip (queue 51), got {queue[0]}. "
            "CMP.I must compare opcode/modifier/modes, not just field values."
        )

    def test_sne_i_different_modes_same_values(self, mars_mod):
        sim = mars_mod.MARS(core_size=200, max_cycles=1000, max_processes=100,
                            max_length=50, min_distance=50)
        sim.init_core()

        # Position 50: SNE.I $10, $20
        sne_instr = mars_mod.Instruction(
            mars_mod.SNE, mars_mod.mI, mars_mod.DIRECT, 10,
            mars_mod.DIRECT, 20, mars_mod.PMARS_OP['SNE']
        )
        sim.core[50] = sne_instr

        # Position 60: MOV.I #0, $0 (IMMEDIATE A-mode)
        instr_a = mars_mod.Instruction(
            mars_mod.MOV, mars_mod.mI, mars_mod.IMMEDIATE, 0,
            mars_mod.DIRECT, 0, mars_mod.PMARS_OP['MOV']
        )
        sim.core[60] = instr_a

        # Position 70: MOV.I $0, $0 (DIRECT A-mode, same values)
        instr_b = mars_mod.Instruction(
            mars_mod.MOV, mars_mod.mI, mars_mod.DIRECT, 0,
            mars_mod.DIRECT, 0, mars_mod.PMARS_OP['MOV']
        )
        sim.core[70] = instr_b

        queue = deque()
        result = sim.execute(50, queue)
        assert result is True
        assert len(queue) == 1
        # Different A-modes → not equal → SNE skips → queue PC+2 = 52
        assert queue[0] == 52, (
            f"SNE.I with different addressing modes should skip (queue 52), got {queue[0]}. "
            "SNE.I must compare modes, not just field values."
        )


class TestBPostIncTiming:
    """B-operand post-increment must happen AFTER pointer resolution,
    not before. ICWS'94 5.3.8: the B-number is incremented after the
    B-instruction is stored."""

    def test_b_postinc_resolves_before_increment(self, mars_mod):
        sim = mars_mod.MARS(core_size=200, max_cycles=1000, max_processes=100,
                            max_length=50, min_distance=50)
        sim.init_core()

        # Position 10: MOV.A #99, >5  (B-operand uses B-postinc at position 15)
        mov_instr = mars_mod.Instruction(
            mars_mod.MOV, mars_mod.mA, mars_mod.IMMEDIATE, 99,
            mars_mod.POSTINC, 5, mars_mod.PMARS_OP['MOV']
        )
        sim.core[10] = mov_instr

        # Position 15 (the indirect cell): DAT.F $0, $3
        # B-number=3 → target = 15+3 = 18 (BEFORE increment)
        # After: B-number becomes 4
        dat_instr = mars_mod.Instruction(
            mars_mod.DAT, mars_mod.mF, mars_mod.DIRECT, 0,
            mars_mod.DIRECT, 3, mars_mod.PMARS_OP['DAT']
        )
        sim.core[15] = dat_instr

        queue = deque()
        sim.execute(10, queue)

        # The B-pointer should use original value 3 → target is position 18
        # Value 99 should be written to core[18].an
        assert sim.core[18].an == 99, (
            f"MOV.A with B-postinc should write to position 18 (original pointer=3), "
            f"but core[18].an={sim.core[18].an}. "
            f"core[19].an={sim.core[19].an} (would be wrong if increment happened first)."
        )
        # The indirect cell's B-number should now be incremented to 4
        assert sim.core[15].bn == 4, (
            f"B-postinc should increment pointer after use: expected 4, got {sim.core[15].bn}"
        )


class TestDivFPartialZero:
    """DIV.F with one zero divisor: the non-zero component must still
    be computed. ICWS'94 5.5.6: If either component of the A-value
    is zero, the corresponding component of the B-value is unchanged
    (the other component is divided normally)."""

    def test_div_f_one_zero_one_nonzero(self, mars_mod):
        sim = mars_mod.MARS(core_size=200, max_cycles=1000, max_processes=100,
                            max_length=50, min_distance=50)
        sim.init_core()

        # Position 10: DIV.F $5, $10
        div_instr = mars_mod.Instruction(
            mars_mod.DIV, mars_mod.mF, mars_mod.DIRECT, 5,
            mars_mod.DIRECT, 10, mars_mod.PMARS_OP['DIV']
        )
        sim.core[10] = div_instr

        # Position 15 (A-instruction): DAT.F #4, #0
        # A-number=4 (nonzero), B-number=0 (zero divisor)
        a_instr = mars_mod.Instruction(
            mars_mod.DAT, mars_mod.mF, mars_mod.DIRECT, 4,
            mars_mod.DIRECT, 0, mars_mod.PMARS_OP['DAT']
        )
        sim.core[15] = a_instr

        # Position 20 (B-instruction/target): DAT.F #100, #50
        b_instr = mars_mod.Instruction(
            mars_mod.DAT, mars_mod.mF, mars_mod.DIRECT, 100,
            mars_mod.DIRECT, 50, mars_mod.PMARS_OP['DAT']
        )
        sim.core[20] = b_instr

        queue = deque()
        result = sim.execute(10, queue)

        # Process should die (because B-number divisor is zero)
        assert result is False, "DIV.F with a zero component should kill the process"

        # But the A-number component (100 / 4 = 25) MUST still be written
        assert sim.core[20].an == 25, (
            f"DIV.F: non-zero component should still compute: 100/4=25, "
            f"got core[20].an={sim.core[20].an}. "
            "The zero divisor in one component must not prevent the other from executing."
        )
        # The B-number component (50 / 0) should be unchanged
        assert sim.core[20].bn == 50, (
            f"DIV.F: zero-divisor component should leave B unchanged: expected 50, "
            f"got core[20].bn={sim.core[20].bn}"
        )

    def test_mod_x_partial_zero(self, mars_mod):
        sim = mars_mod.MARS(core_size=200, max_cycles=1000, max_processes=100,
                            max_length=50, min_distance=50)
        sim.init_core()

        # Position 10: MOD.X $5, $10
        mod_instr = mars_mod.Instruction(
            mars_mod.MOD, mars_mod.mX, mars_mod.DIRECT, 5,
            mars_mod.DIRECT, 10, mars_mod.PMARS_OP['MOD']
        )
        sim.core[10] = mod_instr

        # Position 15 (A-instruction): DAT.F #3, #0
        # For MOD.X: uses (B-number=0 for A-target, A-number=3 for B-target)
        a_instr = mars_mod.Instruction(
            mars_mod.DAT, mars_mod.mF, mars_mod.DIRECT, 3,
            mars_mod.DIRECT, 0, mars_mod.PMARS_OP['DAT']
        )
        sim.core[15] = a_instr

        # Position 20 (B-target): DAT.F #70, #40
        # MOD.X: A-target = 70 % 0 → zero divisor, unchanged
        #         B-target = 40 % 3 = 1
        b_instr = mars_mod.Instruction(
            mars_mod.DAT, mars_mod.mF, mars_mod.DIRECT, 70,
            mars_mod.DIRECT, 40, mars_mod.PMARS_OP['DAT']
        )
        sim.core[20] = b_instr

        queue = deque()
        result = sim.execute(10, queue)

        assert result is False, "MOD.X with a zero component should kill the process"
        # A-component (70 % 0) → unchanged
        assert sim.core[20].an == 70, (
            f"MOD.X: zero-divisor component should leave A unchanged: expected 70, "
            f"got {sim.core[20].an}"
        )
        # B-component (40 % 3 = 1) → should be computed
        assert sim.core[20].bn == 1, (
            f"MOD.X: non-zero component should compute: 40%3=1, "
            f"got {sim.core[20].bn}"
        )


# ====================================================================
# CLI integration tests — run mars.py as subprocess, check output
# ====================================================================

CORE_SIZE = 8000
MAX_CYCLES = 80000
MAX_PROCS = 8000
MAX_LENGTH = 100
MIN_DISTANCE = 100
ROUNDS = 100


def run_candidate(w1: str, w2: str, rounds: int = ROUNDS, coresize: int = CORE_SIZE,
                  cycles: int = MAX_CYCLES, procs: int = MAX_PROCS,
                  length: int = MAX_LENGTH, distance: int = MIN_DISTANCE):
    """Run candidate MARS and return (w1_wlt, w2_wlt) tuples."""
    cmd = [
        'python3', MARS_PATH,
        '-s', str(coresize), '-c', str(cycles), '-p', str(procs),
        '-l', str(length), '-d', str(distance),
        '-r', str(rounds), '-f',
        w1, w2
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    results = {}
    for line in result.stdout.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 4:
            try:
                name = parts[0]
                w, l, t = int(parts[1]), int(parts[2]), int(parts[3])
                results[name] = (w, l, t)
            except ValueError:
                continue

    bn1 = os.path.basename(w1).replace('.red', '')
    bn2 = os.path.basename(w2).replace('.red', '')

    if bn1 not in results or bn2 not in results:
        raise ValueError(
            f"Could not parse candidate output. Expected '{bn1}' and '{bn2}' "
            f"in output:\n{result.stdout}\nstderr:\n{result.stderr[:500]}"
        )

    return results[bn1], results[bn2]


def wp(name: str) -> str:
    return os.path.join(WARRIORS_DIR, f"{name}.red")


class TestBasicSetup:
    def test_mars_file_exists(self):
        assert os.path.isfile(MARS_PATH), "mars.py not found at /app/mars.py"

    def test_candidate_runs_without_crash(self):
        cmd = [
            'python3', MARS_PATH,
            '-s', '8000', '-c', '80000', '-p', '8000',
            '-l', '100', '-d', '100', '-r', '1', '-f',
            wp("imp"), wp("dwarf")
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, f"Crashed: {result.stderr[:500]}"


class TestImpVsImp:
    """Two Imps must always tie — this is analytically provable."""

    def test_all_ties(self):
        r1, r2 = run_candidate(wp("imp"), wp("imp"), rounds=50)
        assert r1 == (0, 0, 50), f"Imp vs Imp should be all ties: {r1}"


class TestKnownMatchups:
    """Battle results against known-correct values (precomputed from
    a verified ICWS'94 implementation with deterministic -f positioning)."""

    def test_imp_vs_dwarf(self):
        r1, r2 = run_candidate(wp("imp"), wp("dwarf"))
        assert r1 == (0, 31, 69), f"imp: expected (0,31,69), got {r1}"
        assert r2 == (31, 0, 69), f"dwarf: expected (31,0,69), got {r2}"

    def test_dwarf_vs_stone(self):
        r1, r2 = run_candidate(wp("dwarf"), wp("stone"))
        assert r1 == (72, 21, 7), f"dwarf: expected (72,21,7), got {r1}"
        assert r2 == (21, 72, 7), f"stone: expected (21,72,7), got {r2}"

    def test_stone_vs_scanner(self):
        r1, r2 = run_candidate(wp("stone"), wp("scanner"))
        assert r1 == (100, 0, 0), f"stone: expected (100,0,0), got {r1}"
        assert r2 == (0, 100, 0), f"scanner: expected (0,100,0), got {r2}"

    def test_scanner_vs_imp(self):
        r1, r2 = run_candidate(wp("scanner"), wp("imp"))
        assert r1 == (0, 100, 0), f"scanner: expected (0,100,0), got {r1}"
        assert r2 == (100, 0, 0), f"imp: expected (100,0,0), got {r2}"

    def test_impring_vs_dwarf(self):
        """ImpRing uses SPL — sensitive to process scheduling order."""
        r1, r2 = run_candidate(wp("impring"), wp("dwarf"))
        assert r1 == (0, 24, 76), f"impring: expected (0,24,76), got {r1}"
        assert r2 == (24, 0, 76), f"dwarf: expected (24,0,76), got {r2}"

    def test_splbomb_vs_stone(self):
        """SplBomb uses SPL heavily — very sensitive to queue ordering."""
        r1, r2 = run_candidate(wp("splbomb"), wp("stone"))
        assert r1 == (75, 22, 3), f"splbomb: expected (75,22,3), got {r1}"
        assert r2 == (22, 75, 3), f"stone: expected (22,75,3), got {r2}"

    def test_postinc_vs_dwarf(self):
        """PostInc warrior uses B-postincrement — sensitive to timing."""
        r1, r2 = run_candidate(wp("postinc"), wp("dwarf"))
        assert r1 == (3, 97, 0), f"postinc: expected (3,97,0), got {r1}"
        assert r2 == (97, 3, 0), f"dwarf: expected (97,3,0), got {r2}"

    def test_postinc_vs_imp(self):
        r1, r2 = run_candidate(wp("postinc"), wp("imp"))
        assert r1 == (2, 94, 4), f"postinc: expected (2,94,4), got {r1}"
        assert r2 == (94, 2, 4), f"imp: expected (94,2,4), got {r2}"

    def test_scanner_vs_dwarf(self):
        """Scanner uses SEQ.I — sensitive to instruction comparison semantics."""
        r1, r2 = run_candidate(wp("scanner"), wp("dwarf"))
        assert r1 == (0, 100, 0), f"scanner: expected (0,100,0), got {r1}"
        assert r2 == (100, 0, 0), f"dwarf: expected (100,0,0), got {r2}"


class TestSmallCore:
    def test_imp_dwarf_core800(self):
        r1, r2 = run_candidate(wp("imp"), wp("dwarf"), rounds=50,
                               coresize=800, cycles=8000, procs=800, length=20, distance=20)
        assert r1 == (0, 14, 36), f"imp (800): expected (0,14,36), got {r1}"
        assert r2 == (14, 0, 36), f"dwarf (800): expected (14,0,36), got {r2}"


class TestConsistency:
    def test_wlt_sum_equals_rounds(self):
        r1, r2 = run_candidate(wp("dwarf"), wp("stone"), rounds=37)
        assert r1[0] + r1[1] + r1[2] == 37, f"W+L+T != 37: {r1}"
        assert r2[0] + r2[1] + r2[2] == 37, f"W+L+T != 37: {r2}"

    def test_symmetry(self):
        r1, r2 = run_candidate(wp("dwarf"), wp("stone"), rounds=50)
        assert r1[0] == r2[1], f"dwarf wins {r1[0]} != stone losses {r2[1]}"
        assert r1[1] == r2[0], f"dwarf losses {r1[1]} != stone wins {r2[0]}"
        assert r1[2] == r2[2], f"ties don't match: {r1[2]} vs {r2[2]}"

    def test_deterministic(self):
        r1a, r2a = run_candidate(wp("stone"), wp("dwarf"), rounds=50)
        r1b, r2b = run_candidate(wp("stone"), wp("dwarf"), rounds=50)
        assert r1a == r1b, f"Non-deterministic: {r1a} vs {r1b}"
        assert r2a == r2b, f"Non-deterministic: {r2a} vs {r2b}"
