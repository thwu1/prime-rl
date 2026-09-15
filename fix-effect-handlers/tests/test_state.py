"""
Verification tests for the Effekt-to-Scheme compiler backend.

Tests that the compiler correctly translates all mini-Effekt AST constructs
to Guile Scheme code, and that the compiled programs produce identical
results to the Python interpreter when run through Guile.

"""

import importlib.util
import os
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, "/app")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_test_module(name):
    """Load a test program module from /app/programs/."""
    filepath = f"/app/programs/{name}.py"
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_compiler():
    """Import and return the compile_program function."""
    spec = importlib.util.spec_from_file_location(
        "effekt_to_scheme", "/app/effekt_to_scheme.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.compile_program


def run_scheme(scheme_code, timeout=30):
    """Write Scheme code to a temp file and run through Guile."""
    fd, tmp = tempfile.mkstemp(suffix=".scm")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(scheme_code)
        result = subprocess.run(
            ["guile", "--no-auto-compile", "-s", tmp],
            capture_output=True, text=True, timeout=timeout,
        )
        return result
    finally:
        os.unlink(tmp)


def parse_scheme_output(stdout):
    """Parse Scheme output into (output_lines, result_str)."""
    lines = stdout.strip().split("\n") if stdout.strip() else []

    marker_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "---RESULT---":
            marker_idx = i
            break

    if marker_idx is None:
        return lines, None

    output_lines = lines[:marker_idx]
    result_str = lines[marker_idx + 1].strip() if marker_idx + 1 < len(lines) else None
    return output_lines, result_str


def compare_result(result_str, expected):
    """Compare a Scheme result string with a Python expected value."""
    from effekt import UNIT
    if result_str is None:
        return False
    if expected is UNIT or (hasattr(expected, '__class__') and
                            expected.__class__.__name__ == 'Unit'):
        return result_str == "()"
    if isinstance(expected, bool):
        return result_str == str(expected)
    if isinstance(expected, int):
        try:
            return int(result_str) == expected
        except (ValueError, TypeError):
            return False
    if isinstance(expected, str):
        return result_str == expected
    return str(expected) == result_str


# ---------------------------------------------------------------------------
# Test: compiler module exists and is importable
# ---------------------------------------------------------------------------

class TestCompilerModule:
    def test_module_exists(self):
        """effekt_to_scheme.py must exist at /app/."""
        assert os.path.isfile("/app/effekt_to_scheme.py"), \
            "Compiler module /app/effekt_to_scheme.py does not exist"

    def test_compile_program_callable(self):
        """Module must export a callable compile_program."""
        compile_fn = get_compiler()
        assert callable(compile_fn)


# ---------------------------------------------------------------------------
# Test: compile_all.py exists and works
# ---------------------------------------------------------------------------

class TestCompileAllScript:
    def test_script_exists(self):
        """compile_all.py must exist at /app/."""
        assert os.path.isfile("/app/compile_all.py"), \
            "Compile-all script /app/compile_all.py does not exist"

    def test_script_passes_all(self):
        """compile_all.py must exit 0 and report 10/10."""
        result = subprocess.run(
            [sys.executable, "/app/compile_all.py"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, \
            f"compile_all.py failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert "10/10" in result.stdout, \
            f"Expected 10/10 passing:\n{result.stdout}"


# ---------------------------------------------------------------------------
# Test: each test program compiles and produces correct results
# ---------------------------------------------------------------------------

PROGRAMS = [
    "basic_handler",
    "deep_accumulate",
    "deep_flip",
    "nested_effects",
    "resume_return",
    "return_clause",
    "recursive_sum",
    "abort_handler",
    "combined_deep_return",
    "multishot_single",
]


class TestIndividualPrograms:
    @pytest.fixture(scope="class")
    def compiler(self):
        return get_compiler()

    @pytest.mark.parametrize("prog_name", PROGRAMS)
    def test_program_compiles_and_matches(self, compiler, prog_name):
        """Each program must compile to valid Scheme and match interpreter output."""
        mod = load_test_module(prog_name)
        ast, expected_result, expected_output = mod.build()

        scheme_code = compiler(ast)
        assert isinstance(scheme_code, str) and len(scheme_code) > 0, \
            f"Compiler returned empty/non-string for {prog_name}"

        result = run_scheme(scheme_code)
        assert result.returncode == 0, \
            f"Guile failed for {prog_name}:\nstderr: {result.stderr}\nstdout: {result.stdout}"

        output_lines, result_str = parse_scheme_output(result.stdout)

        assert output_lines == expected_output, \
            f"{prog_name}: output mismatch: got {output_lines!r}, " \
            f"expected {expected_output!r}"
        assert compare_result(result_str, expected_result), \
            f"{prog_name}: result mismatch: got {result_str!r}, " \
            f"expected {expected_result!r}"


# ---------------------------------------------------------------------------
# Test: deep handler semantics in compiled output
# ---------------------------------------------------------------------------

class TestDeepHandlerSemantics:
    """Verify compiled Scheme correctly implements deep handler reinstallation."""

    @pytest.fixture(scope="class")
    def compiler(self):
        return get_compiler()

    def test_four_ticks_accumulated(self, compiler):
        """4 Tick effects with deep handler: 1+1+1+1+0 = 4."""
        from effekt import (Handle, Do, Seq, IntLit, UnitLit,
                            HandlerClause, BinOp, Var, App)
        prog = Handle(
            body=Seq(Do("Tick"), Do("Tick"), Do("Tick"), Do("Tick"),
                     IntLit(0)),
            handlers=[HandlerClause("Tick", [], "resume",
                                    BinOp("+", IntLit(1),
                                          App(Var("resume"), [UnitLit()])))],
        )
        scheme_code = compiler(prog)
        result = run_scheme(scheme_code)
        assert result.returncode == 0, f"Guile error:\n{result.stderr}"
        _, result_str = parse_scheme_output(result.stdout)
        assert result_str == "4", \
            f"Deep handler accumulation: expected 4, got {result_str}"

    def test_multishot_all_boolean_combos(self, compiler):
        """Deep + multishot Flip produces all 4 boolean combos (8 lines)."""
        from effekt import (Handle, Do, Let, Seq, BoolLit,
                            HandlerClause, Var, App, Print)
        prog = Handle(
            body=Let("a", Do("Flip"),
                     Let("b", Do("Flip"),
                         Seq(Print(Var("a")), Print(Var("b"))))),
            handlers=[HandlerClause("Flip", [], "resume",
                                    Seq(App(Var("resume"), [BoolLit(True)]),
                                        App(Var("resume"), [BoolLit(False)])))],
        )
        scheme_code = compiler(prog)
        result = run_scheme(scheme_code)
        assert result.returncode == 0, f"Guile error:\n{result.stderr}"
        output_lines, _ = parse_scheme_output(result.stdout)
        expected = ["True", "True", "True", "False",
                    "False", "True", "False", "False"]
        assert output_lines == expected, \
            f"Multishot output: got {output_lines!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# Test: effect propagation
# ---------------------------------------------------------------------------

class TestEffectPropagation:
    """Verify unmatched effects propagate correctly in compiled Scheme."""

    @pytest.fixture(scope="class")
    def compiler(self):
        return get_compiler()

    def test_triple_nested_handlers(self, compiler):
        """Three nested handlers: A=2, B=30, C=400 => 2+30+400 = 432."""
        from effekt import (Handle, Do, Let, BinOp, Var, IntLit,
                            HandlerClause, App)
        prog = Handle(
            body=Handle(
                body=Handle(
                    body=Let("a", Do("A"),
                             Let("b", Do("B"),
                                 Let("c", Do("C"),
                                     BinOp("+", Var("a"),
                                           BinOp("+", Var("b"),
                                                 Var("c")))))),
                    handlers=[HandlerClause("C", [], "resume",
                                            App(Var("resume"), [IntLit(400)]))],
                ),
                handlers=[HandlerClause("B", [], "resume",
                                        App(Var("resume"), [IntLit(30)]))],
            ),
            handlers=[HandlerClause("A", [], "resume",
                                    App(Var("resume"), [IntLit(2)]))],
        )
        scheme_code = compiler(prog)
        result = run_scheme(scheme_code)
        assert result.returncode == 0, f"Guile error:\n{result.stderr}"
        _, result_str = parse_scheme_output(result.stdout)
        assert result_str == "432", \
            f"Triple nested: expected 432, got {result_str}"


# ---------------------------------------------------------------------------
# Test: return clause
# ---------------------------------------------------------------------------

class TestReturnClause:
    """Verify return clause compilation."""

    @pytest.fixture(scope="class")
    def compiler(self):
        return get_compiler()

    def test_return_clause_transforms_body(self, compiler):
        """Return clause transforms body return: 21 * 2 = 42."""
        from effekt import Handle, IntLit, BinOp, Var, ReturnClause
        prog = Handle(
            body=IntLit(21),
            handlers=[],
            return_clause=ReturnClause("x", BinOp("*", Var("x"), IntLit(2))),
        )
        scheme_code = compiler(prog)
        result = run_scheme(scheme_code)
        assert result.returncode == 0, f"Guile error:\n{result.stderr}"
        _, result_str = parse_scheme_output(result.stdout)
        assert result_str == "42", \
            f"Return clause: expected 42, got {result_str}"

    def test_handler_body_bypasses_return_clause(self, compiler):
        """Handler body result must NOT be transformed by return clause."""
        from effekt import (Handle, Do, IntLit, BinOp, Var,
                            HandlerClause, ReturnClause)
        prog = Handle(
            body=Do("Fail"),
            handlers=[HandlerClause("Fail", [], "resume", IntLit(50))],
            return_clause=ReturnClause("x",
                                       BinOp("+", Var("x"), IntLit(100))),
        )
        scheme_code = compiler(prog)
        result = run_scheme(scheme_code)
        assert result.returncode == 0, f"Guile error:\n{result.stderr}"
        _, result_str = parse_scheme_output(result.stdout)
        assert result_str == "50", \
            f"Handler bypass: expected 50, got {result_str}"


# ---------------------------------------------------------------------------
# Test: LetRec
# ---------------------------------------------------------------------------

class TestLetRec:
    """Verify recursive binding compilation."""

    @pytest.fixture(scope="class")
    def compiler(self):
        return get_compiler()

    def test_factorial_via_letrec(self, compiler):
        """letrec fact(n) = if n==0 then 1 else n*fact(n-1); fact(5) => 120."""
        from effekt import LetRec, Lam, If, BinOp, Var, IntLit, App
        prog = LetRec(
            "fact",
            Lam(["n"],
                If(BinOp("==", Var("n"), IntLit(0)),
                   IntLit(1),
                   BinOp("*", Var("n"),
                         App(Var("fact"),
                             [BinOp("-", Var("n"), IntLit(1))])))),
            App(Var("fact"), [IntLit(5)]),
        )
        scheme_code = compiler(prog)
        result = run_scheme(scheme_code)
        assert result.returncode == 0, f"Guile error:\n{result.stderr}"
        _, result_str = parse_scheme_output(result.stdout)
        assert result_str == "120", \
            f"Factorial: expected 120, got {result_str}"
