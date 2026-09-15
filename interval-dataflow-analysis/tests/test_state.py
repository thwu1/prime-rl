
import subprocess
import json
import os
import tempfile
import pytest


def run_analysis(cfg_file):
    """Run the interval analysis on the given CFG file (text output only)."""
    result = subprocess.run(
        ["java", "-cp", "/app/target/classes:/app/target/lib/*",
         "dataflow.Main", cfg_file],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"Analysis failed on {cfg_file}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return parse_output(result.stdout)


def run_analysis_with_json(cfg_file, json_path):
    """Run the interval analysis with JSON output."""
    result = subprocess.run(
        ["java", "-cp", "/app/target/classes:/app/target/lib/*",
         "dataflow.Main", cfg_file, json_path],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"Analysis failed on {cfg_file}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    text_data = parse_output(result.stdout)
    json_data = None
    if os.path.exists(json_path):
        with open(json_path) as f:
            json_data = json.load(f)
    return text_data, json_data


def parse_output(stdout):
    """Parse analysis output into a dict: (block, position, var) -> interval_str."""
    result = {}
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 4:
            block = parts[0]
            pos = parts[1]  # "entry" or "exit"
            var = parts[2]
            interval = " ".join(parts[3:])
            result[(block, pos, var)] = interval
    return result


def check(data, block, pos, var, expected):
    key = (block, pos, var)
    actual = data.get(key)
    assert actual is not None, f"Missing output for {block} {pos} {var}"
    assert actual == expected, (
        f"Wrong interval for {block} {pos} {var}: expected {expected}, got {actual}"
    )


class TestConstantArithmetic:
    """Test 1: Pure constant folding through arithmetic operations."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_analysis("/app/inputs/test1.cfg")

    def test_entry_all_bot(self):
        for v in ["a", "b", "c", "d", "e"]:
            check(self.data, "B0", "entry", v, "bot")

    def test_constants(self):
        check(self.data, "B0", "exit", "a", "[3,3]")
        check(self.data, "B0", "exit", "b", "[7,7]")

    def test_multiplication(self):
        check(self.data, "B0", "exit", "c", "[21,21]")

    def test_division(self):
        check(self.data, "B0", "exit", "d", "[7,7]")

    def test_subtraction(self):
        check(self.data, "B0", "exit", "e", "[4,4]")


class TestBranchRefinement:
    """Test 2: Branches with interval refinement and merging."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_analysis("/app/inputs/test2.cfg")

    def test_unknown_input(self):
        check(self.data, "B0", "exit", "x", "[-inf,inf]")

    def test_branch_refine_ge(self):
        check(self.data, "B1", "entry", "x", "[0,inf]")

    def test_branch_refine_le(self):
        check(self.data, "B3", "entry", "x", "[0,100]")

    def test_multiplication_bounded(self):
        check(self.data, "B3", "exit", "y", "[0,200]")

    def test_merge_at_b2(self):
        check(self.data, "B2", "entry", "x", "[-inf,inf]")

    def test_merge_at_exit(self):
        check(self.data, "B4", "entry", "y", "[0,200]")


class TestSimpleLoop:
    """Test 3: Simple loop requiring convergence and precision."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_analysis("/app/inputs/test3.cfg")

    def test_init(self):
        check(self.data, "B0", "exit", "i", "[0,0]")

    def test_loop_header(self):
        check(self.data, "B1", "entry", "i", "[0,10]")

    def test_loop_body_entry(self):
        check(self.data, "B2", "entry", "i", "[0,9]")

    def test_loop_body_exit(self):
        check(self.data, "B2", "exit", "i", "[1,10]")

    def test_after_loop(self):
        check(self.data, "B3", "entry", "i", "[10,10]")


class TestDivisionBounded:
    """Test 4: Division with bounded non-zero divisor."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_analysis("/app/inputs/test4.cfg")

    def test_bounded_divisor(self):
        check(self.data, "B3", "entry", "a", "[1,10]")
        check(self.data, "B3", "exit", "b", "[10,100]")

    def test_chained_arithmetic(self):
        check(self.data, "B3", "exit", "c", "[11,101]")
        check(self.data, "B3", "exit", "d", "[22,202]")

    def test_merge_d(self):
        check(self.data, "B4", "entry", "d", "[0,202]")

    def test_merge_b(self):
        check(self.data, "B4", "entry", "b", "[10,100]")


class TestNegativeMultiplication:
    """Test 5: Multiplication with intervals spanning zero."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_analysis("/app/inputs/test5.cfg")

    def test_refined_range(self):
        check(self.data, "B2", "entry", "x", "[-5,5]")

    def test_multiplication_spanning_zero(self):
        check(self.data, "B2", "exit", "y", "[-25,25]")

    def test_addition_after_mul(self):
        check(self.data, "B2", "exit", "z", "[-24,26]")

    def test_merge_at_exit(self):
        check(self.data, "B4", "entry", "y", "[-25,25]")
        check(self.data, "B4", "entry", "z", "[-24,26]")


class TestVariableComparison:
    """Test 6: Variable-to-variable comparison and unreachable code."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_analysis("/app/inputs/test6.cfg")

    def test_constants_set(self):
        check(self.data, "B0", "exit", "x", "[5,5]")
        check(self.data, "B0", "exit", "y", "[10,10]")

    def test_true_branch_reachable(self):
        check(self.data, "B1", "entry", "x", "[5,5]")
        check(self.data, "B1", "entry", "y", "[10,10]")
        check(self.data, "B1", "exit", "z", "[5,5]")

    def test_false_branch_unreachable(self):
        check(self.data, "B2", "entry", "x", "bot")
        check(self.data, "B2", "entry", "y", "bot")
        check(self.data, "B2", "entry", "z", "bot")
        check(self.data, "B2", "exit", "z", "bot")

    def test_merge_at_exit(self):
        check(self.data, "B3", "entry", "z", "[5,5]")


class TestDivisionByZero:
    """Test 7: Division by interval containing zero produces [-inf,inf]."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.cfg_content = """# Division by zero test
ENTRY B0
VARS p q r

BLOCK B0
  p = 10
  q = ?
  r = p / q
  RETURN
"""
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.cfg', delete=False, dir='/tmp'
        )
        self.tmpfile.write(self.cfg_content)
        self.tmpfile.close()
        self.data = run_analysis(self.tmpfile.name)

    def teardown_method(self, method):
        if hasattr(self, 'tmpfile'):
            os.unlink(self.tmpfile.name)

    def test_div_by_zero_gives_top(self):
        check(self.data, "B0", "exit", "r", "[-inf,inf]")

    def test_p_unchanged(self):
        check(self.data, "B0", "exit", "p", "[10,10]")

    def test_q_unknown(self):
        check(self.data, "B0", "exit", "q", "[-inf,inf]")


class TestJsonOutput:
    """Test 8: Validate JSON output format and consistency with text output."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.json_path = os.path.join(tempfile.mkdtemp(), "result.json")
        self.text_data, self.json_data = run_analysis_with_json(
            "/app/inputs/test1.cfg", self.json_path
        )

    def teardown_method(self, method):
        if hasattr(self, 'json_path') and os.path.exists(self.json_path):
            os.unlink(self.json_path)

    def test_json_file_created(self):
        assert self.json_data is not None, "JSON output file was not created"

    def test_json_has_analysis_key(self):
        assert "analysis" in self.json_data, "JSON missing 'analysis' key"

    def test_json_block_present(self):
        analysis = self.json_data["analysis"]
        assert "B0" in analysis, "JSON missing block B0"

    def test_json_entry_exit_present(self):
        b0 = self.json_data["analysis"]["B0"]
        assert "entry" in b0, "JSON missing 'entry' in B0"
        assert "exit" in b0, "JSON missing 'exit' in B0"

    def test_json_values_correct(self):
        analysis = self.json_data["analysis"]
        assert analysis["B0"]["exit"]["a"] == "[3,3]"
        assert analysis["B0"]["exit"]["c"] == "[21,21]"
        assert analysis["B0"]["entry"]["a"] == "bot"

    def test_json_matches_stdout(self):
        """Verify every entry in JSON matches the corresponding text output."""
        analysis = self.json_data["analysis"]
        for block_id, block_data in analysis.items():
            for pos in ["entry", "exit"]:
                if pos not in block_data:
                    continue
                for var, interval in block_data[pos].items():
                    key = (block_id, pos, var)
                    assert key in self.text_data, (
                        f"JSON has {key} but text output doesn't"
                    )
                    assert self.text_data[key] == interval, (
                        f"Mismatch at {key}: text={self.text_data[key]}, json={interval}"
                    )


class TestJsonBranchAnalysis:
    """Test 9: JSON output for a branching program."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.json_path = os.path.join(tempfile.mkdtemp(), "result2.json")
        self.text_data, self.json_data = run_analysis_with_json(
            "/app/inputs/test2.cfg", self.json_path
        )

    def teardown_method(self, method):
        if hasattr(self, 'json_path') and os.path.exists(self.json_path):
            os.unlink(self.json_path)

    def test_json_branch_refinement(self):
        analysis = self.json_data["analysis"]
        assert analysis["B1"]["entry"]["x"] == "[0,inf]"
        assert analysis["B3"]["entry"]["x"] == "[0,100]"

    def test_json_all_blocks_present(self):
        analysis = self.json_data["analysis"]
        for bid in ["B0", "B1", "B2", "B3", "B4"]:
            assert bid in analysis, f"JSON missing block {bid}"
