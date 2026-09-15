"""
Tests for exact model counter (/app/mc).
Verifies binary format, arbitrary precision, and correctness on analytically
computed instances for both mc and wmc tracks.

"""

import subprocess
import os
import tempfile
import pytest
from fractions import Fraction

COUNTER = "/app/mc"


def write_instance(content, directory, name):
    """Write a DIMACS instance to a file and return its path."""
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write(content)
    return path


def run_counter(instance_path, timeout=120):
    """Run the model counter and return stdout."""
    result = subprocess.run(
        [COUNTER, instance_path],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"Counter exited with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return result.stdout


def parse_mc_count(output):
    """Extract the exact integer count from mc output."""
    for line in output.strip().split("\n"):
        line = line.strip()
        if "exact arb int" in line:
            parts = line.split()
            return int(parts[-1])
    raise ValueError(f"Could not find 'c s exact arb int' in output:\n{output}")


def parse_wmc_rational(output):
    """Extract the exact rational count from wmc output."""
    for line in output.strip().split("\n"):
        line = line.strip()
        if "exact rational" in line:
            parts = line.split()
            val = parts[-1]
            if "/" in val:
                num, den = val.split("/")
                return Fraction(int(num), int(den))
            else:
                return Fraction(val)
    raise ValueError(f"Could not find 'c s exact rational' in output:\n{output}")


@pytest.fixture
def inst_dir():
    """Create a temporary directory for instance files."""
    d = tempfile.mkdtemp(prefix="mc_test_")
    yield d


class TestBinaryRequirements:
    """Verify that /app/mc is a compiled native binary."""

    def test_compiled_binary(self):
        """mc must be a compiled ELF binary, not an interpreted script."""
        assert os.path.isfile(COUNTER), f"{COUNTER} does not exist"
        result = subprocess.run(
            ["file", COUNTER], capture_output=True, text=True
        )
        assert "ELF" in result.stdout, (
            f"Expected compiled ELF binary, got: {result.stdout.strip()}"
        )


class TestBasicMC:
    """Test basic unweighted model counting."""

    def test_basic_3var(self, inst_dir):
        """3 vars, 2 clauses: (x1 v x2) ^ (~x1 v x3). Count = 4."""
        content = "c t mc\np cnf 3 2\n1 2 0\n-1 3 0\n"
        path = write_instance(content, inst_dir, "basic.cnf")
        output = run_counter(path)
        assert parse_mc_count(output) == 4

    def test_unsat(self, inst_dir):
        """UNSAT: x1 ^ ~x1. Count = 0."""
        content = "c t mc\np cnf 2 2\n1 0\n-1 0\n"
        path = write_instance(content, inst_dir, "unsat.cnf")
        output = run_counter(path)
        assert parse_mc_count(output) == 0
        assert "UNSATISFIABLE" in output

    def test_chain4(self, inst_dir):
        """4-var implication chain: (x1 v x2) ^ (~x2 v x3) ^ (~x3 v x4). Count = 5."""
        content = "c t mc\np cnf 4 3\n1 2 0\n-2 3 0\n-3 4 0\n"
        path = write_instance(content, inst_dir, "chain4.cnf")
        output = run_counter(path)
        assert parse_mc_count(output) == 5

    def test_single_var(self, inst_dir):
        """Single variable, single clause: x1. Count = 1."""
        content = "c t mc\np cnf 1 1\n1 0\n"
        path = write_instance(content, inst_dir, "single.cnf")
        output = run_counter(path)
        assert parse_mc_count(output) == 1

    def test_no_clauses(self, inst_dir):
        """3 vars, 0 clauses. Count = 2^3 = 8."""
        content = "c t mc\np cnf 3 0\n"
        path = write_instance(content, inst_dir, "noclauses.cnf")
        output = run_counter(path)
        assert parse_mc_count(output) == 8

    def test_bigint_70var(self, inst_dir):
        """70 vars, 0 clauses. Count = 2^70 (exceeds 2^64, requires arb precision)."""
        content = "c t mc\np cnf 70 0\n"
        path = write_instance(content, inst_dir, "big70.cnf")
        output = run_counter(path)
        expected = 2**70  # 1180591620717411303424
        assert parse_mc_count(output) == expected


class TestComponentsMC:
    """Test model counting with component structure."""

    def test_components_15var(self, inst_dir):
        """15 vars, 3 independent components + 6 free vars.
        Component 1: {1,2}, clauses (x1 v x2)(~x1 v ~x2) -> XOR -> 2 solutions
        Component 2: {3,4,5}, clauses (x3 v x4)(~x4 v x5) -> 4 solutions
        Component 3: {6,7,8,9}, clauses (x6 v x7)(~x7 v x8)(~x8 v x9) -> 5 solutions
        Free: {10..15} -> 2^6 = 64
        Total: 2 * 4 * 5 * 64 = 2560
        """
        content = (
            "c t mc\n"
            "p cnf 15 7\n"
            "1 2 0\n"
            "-1 -2 0\n"
            "3 4 0\n"
            "-4 5 0\n"
            "6 7 0\n"
            "-7 8 0\n"
            "-8 9 0\n"
        )
        path = write_instance(content, inst_dir, "components.cnf")
        output = run_counter(path)
        assert parse_mc_count(output) == 2560

    def test_xor40(self, inst_dir):
        """40 vars, 20 independent XOR pairs.
        Each pair (x_{2i-1} v x_{2i}) ^ (~x_{2i-1} v ~x_{2i}) has 2 solutions.
        Total: 2^20 = 1048576.
        This REQUIRES component decomposition to solve efficiently.
        """
        lines = ["c t mc\n", "p cnf 40 40\n"]
        for i in range(20):
            v1 = 2 * i + 1
            v2 = 2 * i + 2
            lines.append(f"{v1} {v2} 0\n")
            lines.append(f"-{v1} -{v2} 0\n")
        content = "".join(lines)
        path = write_instance(content, inst_dir, "xor40.cnf")
        output = run_counter(path, timeout=60)
        assert parse_mc_count(output) == 1048576


class TestChainMC:
    """Test model counting on chain/path structures."""

    def test_chain20(self, inst_dir):
        """20-var chain: (x1 v x2) ^ (~x2 v x3) ^ ... ^ (~x19 v x20). Count = 21."""
        lines = ["c t mc\n", "p cnf 20 19\n"]
        lines.append("1 2 0\n")
        for i in range(2, 20):
            lines.append(f"-{i} {i + 1} 0\n")
        content = "".join(lines)
        path = write_instance(content, inst_dir, "chain20.cnf")
        output = run_counter(path)
        assert parse_mc_count(output) == 21

    def test_path25(self, inst_dir):
        """25-var path: (xi v x_{i+1}) for i=1..24.
        Count = number of binary strings of length 25 with no two consecutive 0s.
        This equals Fibonacci(27) = 196418.
        """
        lines = ["c t mc\n", "p cnf 25 24\n"]
        for i in range(1, 25):
            lines.append(f"{i} {i + 1} 0\n")
        content = "".join(lines)
        path = write_instance(content, inst_dir, "path25.cnf")
        output = run_counter(path)
        assert parse_mc_count(output) == 196418


class TestWeightedMC:
    """Test weighted model counting."""

    def test_weighted_fraction(self, inst_dir):
        """3 vars, 2 clauses, wmc with fraction weights.
        Clauses: (x1 v x2) ^ (~x1 v x3)
        Weights: w(1)=1/2, w(-1)=1/2, w(2)=1/3, w(-2)=2/3, w(3)=1/4, w(-3)=3/4
        Satisfying assignments and weights:
          (F,T,F): 1/2 * 1/3 * 3/4 = 3/24
          (F,T,T): 1/2 * 1/3 * 1/4 = 1/24
          (T,F,T): 1/2 * 2/3 * 1/4 = 2/24
          (T,T,T): 1/2 * 1/3 * 1/4 = 1/24
        Total: 7/24
        """
        content = (
            "c t wmc\n"
            "p cnf 3 2\n"
            "c p weight 1 1/2 0\n"
            "c p weight -1 1/2 0\n"
            "c p weight 2 1/3 0\n"
            "c p weight -2 2/3 0\n"
            "c p weight 3 1/4 0\n"
            "c p weight -3 3/4 0\n"
            "1 2 0\n"
            "-1 3 0\n"
        )
        path = write_instance(content, inst_dir, "weighted_frac.cnf")
        output = run_counter(path)
        result = parse_wmc_rational(output)
        assert result == Fraction(7, 24), f"Expected 7/24, got {result}"

    def test_weighted_decimal(self, inst_dir):
        """2 vars, 1 clause, wmc with decimal weights.
        Clause: (x1 v x2)
        Weights: w(1)=0.3, w(-1)=0.7, w(2)=0.4, w(-2)=0.6
        Satisfying assignments:
          (T,T): 0.3*0.4 = 6/50
          (T,F): 0.3*0.6 = 9/50
          (F,T): 0.7*0.4 = 14/50
        Total: 29/50
        """
        content = (
            "c t wmc\n"
            "p cnf 2 1\n"
            "c p weight 1 0.3 0\n"
            "c p weight -1 0.7 0\n"
            "c p weight 2 0.4 0\n"
            "c p weight -2 0.6 0\n"
            "1 2 0\n"
        )
        path = write_instance(content, inst_dir, "weighted_dec.cnf")
        output = run_counter(path)
        result = parse_wmc_rational(output)
        assert result == Fraction(29, 50), f"Expected 29/50, got {result}"

    def test_weighted_scientific(self, inst_dir):
        """2 vars, 1 clause, wmc with scientific notation weights.
        Clause: (x1)
        Weights: w(1)=3e-1, w(-1)=7e-1, w(2)=2e-1, w(-2)=8e-1
        x1 must be T, x2 is free.
        Weight: 3e-1 * (2e-1 + 8e-1) = 0.3 * 1.0 = 3/10
        """
        content = (
            "c t wmc\n"
            "p cnf 2 1\n"
            "c p weight 1 3e-1 0\n"
            "c p weight -1 7e-1 0\n"
            "c p weight 2 2e-1 0\n"
            "c p weight -2 8e-1 0\n"
            "1 0\n"
        )
        path = write_instance(content, inst_dir, "weighted_sci.cnf")
        output = run_counter(path)
        result = parse_wmc_rational(output)
        assert result == Fraction(3, 10), f"Expected 3/10, got {result}"

    def test_weighted_unit_weights(self, inst_dir):
        """wmc with all weights=1 should equal unweighted count.
        Same formula as basic_3var: count should be 4/1.
        """
        content = (
            "c t wmc\n"
            "p cnf 3 2\n"
            "c p weight 1 1 0\n"
            "c p weight -1 1 0\n"
            "c p weight 2 1 0\n"
            "c p weight -2 1 0\n"
            "c p weight 3 1 0\n"
            "c p weight -3 1 0\n"
            "1 2 0\n"
            "-1 3 0\n"
        )
        path = write_instance(content, inst_dir, "weighted_unit.cnf")
        output = run_counter(path)
        result = parse_wmc_rational(output)
        assert result == Fraction(4, 1), f"Expected 4/1, got {result}"
