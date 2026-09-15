
import sys
import json
import os
import subprocess

sys.path.insert(0, '/app')


def validate_placement(n, queens):
    """Check that queens form a valid non-attacking placement on an n x n board."""
    rows = set()
    cols = set()
    diags = set()
    antis = set()
    for r, c in queens:
        assert 0 <= r < n and 0 <= c < n, f"Queen ({r},{c}) out of bounds for n={n}"
        assert r not in rows, f"Duplicate row {r}"
        assert c not in cols, f"Duplicate col {c}"
        assert (r + c) not in diags, f"Diagonal conflict at ({r},{c})"
        assert (r - c) not in antis, f"Anti-diagonal conflict at ({r},{c})"
        rows.add(r)
        cols.add(c)
        diags.add(r + c)
        antis.add(r - c)


class TestGenerator:
    def test_generates_valid_instance(self):
        from generator import generate
        inst = generate(8, 3, seed=42)
        assert inst["n"] == 8
        assert len(inst["queens"]) == 3
        validate_placement(8, inst["queens"])

    def test_deterministic(self):
        from generator import generate
        a = generate(10, 5, seed=123)
        b = generate(10, 5, seed=123)
        assert a == b

    def test_different_seeds_differ(self):
        from generator import generate
        a = generate(10, 5, seed=0)
        b = generate(10, 5, seed=1)
        assert a["queens"] != b["queens"]

    def test_zero_queens(self):
        from generator import generate
        inst = generate(8, 0, seed=0)
        assert inst["n"] == 8
        assert len(inst["queens"]) == 0

    def test_max_queens(self):
        from generator import generate
        for seed in range(20):
            inst = generate(8, 8, seed=seed)
            if len(inst["queens"]) == 8:
                validate_placement(8, inst["queens"])
                return
        assert False, "Generator could not place 8 queens on 8x8 board with any of 20 seeds"


class TestEncoder:
    def test_valid_dimacs_format(self):
        from encoder import encode
        inst = {"n": 4, "queens": [[0, 1]]}
        cnf = encode(inst)
        lines = cnf.strip().split('\n')
        assert lines[0].startswith('p cnf')
        parts = lines[0].split()
        num_vars = int(parts[2])
        num_clauses = int(parts[3])
        assert num_vars >= 16, f"Expected at least n*n=16 vars, got {num_vars}"
        assert num_clauses == len(lines) - 1, "Clause count mismatch"
        for line in lines[1:]:
            tokens = line.strip().split()
            assert tokens[-1] == '0', f"Clause must end with 0: {line}"

    def test_encoding_efficiency(self):
        """Encoding must introduce auxiliary variables beyond n*n primary vars."""
        from encoder import encode
        inst = {"n": 10, "queens": []}
        cnf = encode(inst)
        header = cnf.split('\n')[0]
        num_vars = int(header.split()[2])
        assert num_vars > 100, (
            f"Only {num_vars} variables for 10x10 board. "
            "An efficient at-most-one encoding uses auxiliary variables "
            "beyond the 100 primary variables."
        )

    def test_clause_count_bound(self):
        """Encoding must stay under the benchmark clause count threshold for n=20."""
        from encoder import encode
        inst = {"n": 20, "queens": []}
        cnf = encode(inst)
        num_clauses = int(cnf.split('\n')[0].split()[3])
        assert num_clauses < 9000, (
            f"Clause count {num_clauses} for n=20 exceeds the "
            "performance threshold of 9000 clauses."
        )

    def test_pre_placed_unit_clauses(self):
        from encoder import encode
        inst = {"n": 5, "queens": [[0, 0], [1, 2]]}
        cnf = encode(inst)
        lines = cnf.strip().split('\n')[1:]
        unit_clauses = [line.strip() for line in lines if len(line.strip().split()) == 2]
        assert "1 0" in unit_clauses, "Missing unit clause for pre-placed queen at (0,0)"
        assert "8 0" in unit_clauses, "Missing unit clause for pre-placed queen at (1,2)"


class TestSolver:
    def test_sat_instance_5x5(self):
        from solver import solve
        inst = {"n": 5, "queens": [[0, 0], [1, 2]]}
        result = solve(inst)
        assert result["satisfiable"] is True
        assert result["solution"] is not None
        assert len(result["solution"]) == 5
        validate_placement(5, result["solution"])
        assert [0, 0] in result["solution"]
        assert [1, 2] in result["solution"]

    def test_unsat_instance_4x4(self):
        from solver import solve
        inst = {"n": 4, "queens": [[0, 0], [1, 2]]}
        result = solve(inst)
        assert result["satisfiable"] is False
        assert result["solution"] is None

    def test_sat_instance_8x8(self):
        from solver import solve
        inst = {"n": 8, "queens": [[0, 3], [1, 6], [2, 4]]}
        result = solve(inst)
        assert result["satisfiable"] is True
        assert result["solution"] is not None
        assert len(result["solution"]) == 8
        validate_placement(8, result["solution"])
        for q in [[0, 3], [1, 6], [2, 4]]:
            assert q in result["solution"], f"Pre-placed queen {q} missing from solution"

    def test_empty_board_sat(self):
        from solver import solve
        inst = {"n": 5, "queens": []}
        result = solve(inst)
        assert result["satisfiable"] is True
        assert len(result["solution"]) == 5
        validate_placement(5, result["solution"])

    def test_loaded_sat_instance(self):
        from solver import solve
        with open('/app/instances/sat_5_2.json') as f:
            inst = json.load(f)
        result = solve(inst)
        assert result["satisfiable"] is True
        validate_placement(inst["n"], result["solution"])

    def test_loaded_unsat_instance(self):
        from solver import solve
        with open('/app/instances/unsat_4_2.json') as f:
            inst = json.load(f)
        result = solve(inst)
        assert result["satisfiable"] is False


class TestCounter:
    def test_4queens_full(self):
        from counter import count
        assert count({"n": 4, "queens": []}) == 2

    def test_5queens_full(self):
        from counter import count
        assert count({"n": 5, "queens": []}) == 10

    def test_6queens_full(self):
        from counter import count
        assert count({"n": 6, "queens": []}) == 4

    def test_8queens_full(self):
        from counter import count
        assert count({"n": 8, "queens": []}) == 92

    def test_5queens_one_placed(self):
        from counter import count
        assert count({"n": 5, "queens": [[0, 0]]}) == 2

    def test_5queens_two_placed(self):
        from counter import count
        assert count({"n": 5, "queens": [[0, 0], [1, 2]]}) == 1

    def test_unsat_count_zero(self):
        from counter import count
        assert count({"n": 4, "queens": [[0, 0], [1, 2]]}) == 0

    def test_counter_matches_solver(self):
        """Counter should agree with solver on satisfiability."""
        from counter import count
        from solver import solve
        inst = {"n": 6, "queens": [[0, 1]]}
        c = count(inst)
        r = solve(inst)
        assert (c > 0) == r["satisfiable"]


class TestPhaseTransition:
    def _ensure_phase_data(self):
        """Run phase_transition.py if CSV doesn't exist yet."""
        csv_path = '/app/results/phase_transition.csv'
        if not os.path.exists(csv_path):
            result = subprocess.run(
                ['python3', '/app/phase_transition.py'],
                capture_output=True, text=True, timeout=240
            )
            assert result.returncode == 0, (
                f"phase_transition.py failed: {result.stderr[:500]}"
            )
        return csv_path

    def test_output_exists_and_format(self):
        csv_path = self._ensure_phase_data()
        assert os.path.exists(csv_path), "phase_transition.csv not found"
        with open(csv_path) as f:
            lines = f.readlines()
        assert lines[0].strip() == 'm,sat_fraction', f"Bad header: {lines[0]}"
        assert len(lines) >= 14, f"Expected header + 13 data rows, got {len(lines)} lines"
        for line in lines[1:14]:
            parts = line.strip().split(',')
            assert len(parts) == 2, f"Bad data row: {line}"
            m = int(parts[0])
            frac = float(parts[1])
            assert 1 <= m <= 13, f"m={m} out of range"
            assert 0.0 <= frac <= 1.0, f"sat_fraction={frac} out of [0,1]"

    def test_phase_transition_trend(self):
        """Satisfiability must decrease as number of pre-placed queens increases."""
        csv_path = self._ensure_phase_data()
        with open(csv_path) as f:
            lines = f.readlines()
        data = {}
        for line in lines[1:14]:
            m, frac = line.strip().split(',')
            data[int(m)] = float(frac)
        assert data[1] >= 0.8, f"m=1 sat_fraction={data[1]}, expected >= 0.8"
        assert data[13] <= 0.5, f"m=13 sat_fraction={data[13]}, expected <= 0.5"
        assert data[1] > data[13], (
            f"No decreasing trend: m=1 has {data[1]}, m=13 has {data[13]}"
        )
