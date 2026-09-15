
"""Tests for e-graph equality saturation Rust implementation."""

import pytest
import json
import os
import subprocess
import random
import shutil


def _env():
    """Return environment dict with cargo on PATH."""
    env = os.environ.copy()
    cargo_bin = "/usr/local/cargo/bin"
    if cargo_bin not in env.get("PATH", ""):
        env["PATH"] = cargo_bin + ":" + env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["CARGO_HOME"] = "/usr/local/cargo"
    return env


# ---------------------------------------------------------------------------
# S-expression helpers
# ---------------------------------------------------------------------------

def parse_sexp(s):
    """Parse an S-expression string into a nested tuple/int/str tree."""
    s = s.strip()
    if not s.startswith("("):
        try:
            return int(s)
        except ValueError:
            return s
    tokens = s.replace("(", " ( ").replace(")", " ) ").split()
    pos = [0]

    def _parse():
        tok = tokens[pos[0]]
        pos[0] += 1
        if tok == "(":
            op = tokens[pos[0]]
            pos[0] += 1
            children = []
            while tokens[pos[0]] != ")":
                children.append(_parse())
            pos[0] += 1
            return (op, children)
        else:
            try:
                return int(tok)
            except ValueError:
                return tok

    return _parse()


def evaluate(tree, env):
    """Evaluate a parsed S-expression with variable bindings."""
    if isinstance(tree, int):
        return tree
    if isinstance(tree, str):
        return env[tree]
    op, children = tree
    if op == "+":
        return evaluate(children[0], env) + evaluate(children[1], env)
    if op == "*":
        return evaluate(children[0], env) * evaluate(children[1], env)
    raise ValueError(f"Unknown operator: {op}")


def get_vars(tree):
    """Collect all variable names from a parsed S-expression."""
    if isinstance(tree, int):
        return set()
    if isinstance(tree, str):
        return {tree}
    _, children = tree
    result = set()
    for child in children:
        result |= get_vars(child)
    return result


def ast_cost(tree):
    """Count AST nodes in a parsed S-expression."""
    if isinstance(tree, int) or isinstance(tree, str):
        return 1
    _, children = tree
    return 1 + sum(ast_cost(c) for c in children)


def check_equiv(expr1_str, expr2_str, n=50):
    """Probabilistically verify two S-expressions are semantically equivalent."""
    t1 = parse_sexp(expr1_str)
    t2 = parse_sexp(expr2_str)
    vs = sorted(get_vars(t1) | get_vars(t2))
    if not vs:
        return evaluate(t1, {}) == evaluate(t2, {})
    rng = random.Random(42)
    for _ in range(n):
        env = {v: rng.randint(1, 100) for v in vs}
        if evaluate(t1, env) != evaluate(t2, env):
            return False
    return True


# ---------------------------------------------------------------------------
# Build and binary tests
# ---------------------------------------------------------------------------

class TestBuild:
    def test_project_compiles(self):
        """The Cargo project must compile in release mode."""
        result = subprocess.run(
            ["cargo", "build", "--release", "--manifest-path", "/app/Cargo.toml"],
            capture_output=True, text=True, timeout=300, env=_env(),
        )
        assert result.returncode == 0, (
            f"cargo build --release failed:\n{result.stderr[-3000:]}"
        )

    def test_binary_exists(self):
        """The compiled binary must exist at the expected path."""
        assert os.path.exists("/app/target/release/egraph-optimizer"), (
            "Binary /app/target/release/egraph-optimizer not found"
        )


class TestExecution:
    def test_binary_runs(self):
        """The binary must run without error."""
        if not os.path.exists("/app/target/release/egraph-optimizer"):
            pytest.skip("binary not built")
        result = subprocess.run(
            ["/app/target/release/egraph-optimizer"],
            capture_output=True, text=True, timeout=60, cwd="/app", env=_env(),
        )
        assert result.returncode == 0, (
            f"Binary execution failed:\n{result.stderr[-3000:]}"
        )

    def test_results_json_exists(self):
        """results.json must be created after running the binary."""
        assert os.path.exists("/app/results.json"), "results.json not created"


# ---------------------------------------------------------------------------
# Output format tests
# ---------------------------------------------------------------------------

class TestResultsFormat:
    @pytest.fixture(autouse=True)
    def load_results(self):
        if not os.path.exists("/app/results.json"):
            pytest.skip("results.json does not exist")
        with open("/app/results.json") as f:
            self.results = json.load(f)

    def test_is_list(self):
        assert isinstance(self.results, list), "results.json must be a JSON array"

    def test_has_all_entries(self):
        assert len(self.results) == 10, (
            f"Expected 10 results, got {len(self.results)}"
        )

    def test_entries_have_required_fields(self):
        for r in self.results:
            for field in ("id", "input", "output", "cost"):
                assert field in r, f"Missing '{field}' in result entry {r}"

    def test_all_input_ids_present(self):
        with open("/app/inputs.json") as f:
            inputs = json.load(f)
        input_ids = {i["id"] for i in inputs}
        result_ids = {r["id"] for r in self.results}
        assert result_ids == input_ids, (
            f"ID mismatch: inputs={input_ids}, results={result_ids}"
        )


# ---------------------------------------------------------------------------
# Correctness tests
# ---------------------------------------------------------------------------

class TestCorrectness:
    @pytest.fixture(autouse=True)
    def load_data(self):
        if not os.path.exists("/app/results.json"):
            pytest.skip("results.json does not exist")
        with open("/app/results.json") as f:
            self.results = json.load(f)
        with open("/app/inputs.json") as f:
            self.inputs = {i["id"]: i for i in json.load(f)}

    def test_semantic_equivalence(self):
        """Each output must be semantically equivalent to its input."""
        for r in self.results:
            assert check_equiv(r["input"], r["output"]), (
                f"#{r['id']}: output '{r['output']}' is NOT equivalent "
                f"to input '{r['input']}'"
            )

    def test_cost_targets_met(self):
        """Each output cost must be <= the max_cost from inputs.json."""
        for r in self.results:
            inp = self.inputs[r["id"]]
            actual = ast_cost(parse_sexp(r["output"]))
            assert actual <= inp["max_cost"], (
                f"#{r['id']}: output cost {actual} exceeds "
                f"max_cost {inp['max_cost']} (output: {r['output']})"
            )

    def test_reported_cost_matches_actual(self):
        """The cost field must match the actual AST-node count."""
        for r in self.results:
            actual = ast_cost(parse_sexp(r["output"]))
            assert r["cost"] == actual, (
                f"#{r['id']}: reported cost {r['cost']} != "
                f"actual AST cost {actual} for '{r['output']}'"
            )

    def test_outputs_parseable(self):
        """All output S-expressions must be parseable."""
        for r in self.results:
            tree = parse_sexp(r["output"])
            assert tree is not None, f"Failed to parse: {r['output']}"


# ---------------------------------------------------------------------------
# Anti-hardcoding: novel expressions
# ---------------------------------------------------------------------------

class TestAntiHardcode:
    def test_novel_expressions(self):
        """Optimizer must work on expressions not in the original inputs.json."""
        if not os.path.exists("/app/target/release/egraph-optimizer"):
            pytest.skip("binary not built")

        novel = [
            {"id": 101, "expr": "(+ (* p 7) (* p 3))", "max_cost": 3},
            {"id": 102, "expr": "(* (+ q 0) (+ 0 r))", "max_cost": 3},
            {"id": 103, "expr": "(+ (* 0 (+ a b)) (* 1 c))", "max_cost": 1},
            {"id": 104, "expr": "(+ (* 4 d) (* 4 d))", "max_cost": 3},
            {"id": 105, "expr": "(+ (+ (* w 0) 0) (* 1 w))", "max_cost": 1},
        ]

        shutil.copy("/app/inputs.json", "/tmp/_inputs_backup.json")
        orig_results = None
        if os.path.exists("/app/results.json"):
            shutil.copy("/app/results.json", "/tmp/_results_backup.json")
            orig_results = True

        try:
            with open("/app/inputs.json", "w") as f:
                json.dump(novel, f)

            result = subprocess.run(
                ["/app/target/release/egraph-optimizer"],
                capture_output=True, text=True, timeout=60, cwd="/app", env=_env(),
            )
            assert result.returncode == 0, (
                f"Failed on novel inputs: {result.stderr[-2000:]}"
            )

            with open("/app/results.json") as f:
                results = json.load(f)

            novel_map = {n["id"]: n for n in novel}
            for r in results:
                n = novel_map[r["id"]]
                assert check_equiv(n["expr"], r["output"]), (
                    f"Novel #{r['id']}: '{r['output']}' not equivalent "
                    f"to '{n['expr']}'"
                )
                c = ast_cost(parse_sexp(r["output"]))
                assert c <= n["max_cost"], (
                    f"Novel #{r['id']}: cost {c} > target {n['max_cost']} "
                    f"(output: {r['output']})"
                )
        finally:
            shutil.copy("/tmp/_inputs_backup.json", "/app/inputs.json")
            if orig_results:
                shutil.copy("/tmp/_results_backup.json", "/app/results.json")
