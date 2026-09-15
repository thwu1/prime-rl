
import os
import subprocess
import tempfile

import pytest

BUILD_DIR = "/app/build"
GRAMMAR_DIR = "/app/grammars"

GRAMMARS = ["g1_arith", "g2_epsilon", "g3_lvalue", "g4_decls"]


def run_parser(parser_stem, tokens):
    """Run a compiled parser binary on a token string.

    Creates a temp file with the tokens, invokes the parser, and returns
    the stripped stdout. Asserts exit code 0.
    """
    parser_path = os.path.join(BUILD_DIR, f"parser-{parser_stem}")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tokens", delete=False) as f:
        f.write(tokens)
        input_path = f.name
    try:
        result = subprocess.run(
            [parser_path, input_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Parser exited with code {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        return result.stdout.strip()
    finally:
        os.unlink(input_path)


# ---------------------------------------------------------------------------
# Build pipeline verification
# ---------------------------------------------------------------------------
class TestBuildPipeline:

    def test_01_parser_binaries_exist(self):
        """All parser binaries must exist and be executable after make all."""
        for g in GRAMMARS:
            path = os.path.join(BUILD_DIR, f"parser-{g}")
            assert os.path.isfile(path), f"Missing binary: {path}"
            assert os.access(path, os.X_OK), f"Not executable: {path}"

    def test_02_generated_c_files_exist(self):
        """Generated C source files must be present in build/."""
        for g in GRAMMARS:
            path = os.path.join(BUILD_DIR, f"{g}.c")
            assert os.path.isfile(path), f"Missing C file: {path}"

    def test_03_c_compiles_with_strict_flags(self):
        """Generated C must compile with -Wall -Werror -pedantic."""
        for g in GRAMMARS:
            c_file = os.path.join(BUILD_DIR, f"{g}.c")
            result = subprocess.run(
                [
                    "gcc", "-std=c99", "-O2", "-Wall", "-Werror", "-pedantic",
                    "-fsyntax-only", c_file,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, (
                f"{g}.c has warnings/errors under strict flags:\n{result.stderr}"
            )

    def test_04_make_clean_and_rebuild(self):
        """make clean must remove build dir; make all must rebuild."""
        subprocess.run(
            ["make", "-C", "/app", "clean"],
            capture_output=True, timeout=30,
        )
        assert not os.path.exists(BUILD_DIR), "clean did not remove build dir"
        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, f"Rebuild after clean failed:\n{result.stderr}"
        for g in GRAMMARS:
            path = os.path.join(BUILD_DIR, f"parser-{g}")
            assert os.path.isfile(path), f"Missing after rebuild: {path}"


# ---------------------------------------------------------------------------
# Grammar 1: Arithmetic expressions
#   S -> BOF E EOF
#   E -> E + T | T
#   T -> T * F | F
#   F -> ( E ) | id
# ---------------------------------------------------------------------------
class TestArithGrammar:
    G = "g1_arith"

    def test_single_id(self):
        assert run_parser(self.G, "BOF id EOF") == "accept"

    def test_addition(self):
        assert run_parser(self.G, "BOF id + id EOF") == "accept"

    def test_mult_then_add(self):
        assert run_parser(self.G, "BOF id * id + id EOF") == "accept"

    def test_parenthesized(self):
        assert run_parser(self.G, "BOF ( id + id ) * id EOF") == "accept"

    def test_nested_parens(self):
        assert run_parser(self.G, "BOF id * ( id + id * ( id + id ) ) EOF") == "accept"

    def test_long_chain(self):
        assert run_parser(self.G, "BOF id + id + id + id + id EOF") == "accept"

    def test_trailing_op_reject(self):
        assert run_parser(self.G, "BOF id + EOF") == "reject"

    def test_leading_op_reject(self):
        assert run_parser(self.G, "BOF + id EOF") == "reject"

    def test_unclosed_paren_reject(self):
        assert run_parser(self.G, "BOF ( id + id EOF") == "reject"

    def test_empty_expr_reject(self):
        assert run_parser(self.G, "BOF EOF") == "reject"

    def test_adjacent_ids_reject(self):
        assert run_parser(self.G, "BOF id id EOF") == "reject"

    def test_double_op_reject(self):
        assert run_parser(self.G, "BOF id + * id EOF") == "reject"


# ---------------------------------------------------------------------------
# Grammar 2: Epsilon productions
#   S -> BOF A EOF
#   A -> X Y
#   X -> a | (epsilon)
#   Y -> b | (epsilon)
# ---------------------------------------------------------------------------
class TestEpsilonGrammar:
    G = "g2_epsilon"

    def test_both_present(self):
        assert run_parser(self.G, "BOF a b EOF") == "accept"

    def test_only_a(self):
        assert run_parser(self.G, "BOF a EOF") == "accept"

    def test_only_b(self):
        assert run_parser(self.G, "BOF b EOF") == "accept"

    def test_empty_both_epsilon(self):
        assert run_parser(self.G, "BOF EOF") == "accept"

    def test_wrong_order_reject(self):
        assert run_parser(self.G, "BOF b a EOF") == "reject"

    def test_duplicate_a_reject(self):
        assert run_parser(self.G, "BOF a a EOF") == "reject"

    def test_extra_after_reject(self):
        assert run_parser(self.G, "BOF a b a EOF") == "reject"


# ---------------------------------------------------------------------------
# Grammar 3: L-value assignments — LALR(1) but NOT SLR(1)
#   GOAL -> BOF S EOF
#   S -> L = R | R
#   L -> * R | id
#   R -> L
#
# SLR(1) has a shift/reduce conflict on '=' in state {S -> L .= R, R -> L.}
# because FOLLOW(R) includes '='. LALR(1) resolves it with per-item
# lookaheads: R -> L. gets lookahead {EOF} only, not FOLLOW(R).
# ---------------------------------------------------------------------------
class TestLvalueGrammar:
    G = "g3_lvalue"

    def test_simple_id(self):
        assert run_parser(self.G, "BOF id EOF") == "accept"

    def test_simple_assign(self):
        assert run_parser(self.G, "BOF id = id EOF") == "accept"

    def test_deref(self):
        assert run_parser(self.G, "BOF * id EOF") == "accept"

    def test_deref_assign(self):
        assert run_parser(self.G, "BOF * id = id EOF") == "accept"

    def test_nested_deref_assign(self):
        assert run_parser(self.G, "BOF * * id = * id EOF") == "accept"

    def test_deep_deref(self):
        assert run_parser(self.G, "BOF * * * id EOF") == "accept"

    def test_leading_eq_reject(self):
        assert run_parser(self.G, "BOF = id EOF") == "reject"

    def test_double_eq_reject(self):
        assert run_parser(self.G, "BOF id = = id EOF") == "reject"

    def test_adjacent_ids_reject(self):
        assert run_parser(self.G, "BOF id id EOF") == "reject"

    def test_trailing_star_reject(self):
        assert run_parser(self.G, "BOF id * EOF") == "reject"


# ---------------------------------------------------------------------------
# Grammar 4: Declaration lists
#   Program   -> BOF DeclList EOF
#   DeclList  -> DeclList Decl | Decl
#   Decl      -> VarDecl | FuncDecl
#   VarDecl   -> type id ;
#   FuncDecl  -> type id ( ParamList ) { } | type id ( ) { }
#   ParamList -> ParamList , Param | Param
#   Param     -> type id
# ---------------------------------------------------------------------------
class TestDeclGrammar:
    G = "g4_decls"

    def test_var_decl(self):
        assert run_parser(self.G, "BOF type id ; EOF") == "accept"

    def test_func_no_params(self):
        assert run_parser(self.G, "BOF type id ( ) { } EOF") == "accept"

    def test_func_one_param(self):
        assert run_parser(self.G, "BOF type id ( type id ) { } EOF") == "accept"

    def test_func_two_params(self):
        assert run_parser(self.G, "BOF type id ( type id , type id ) { } EOF") == "accept"

    def test_var_and_func(self):
        assert run_parser(self.G, "BOF type id ; type id ( type id ) { } EOF") == "accept"

    def test_three_var_decls(self):
        assert run_parser(self.G, "BOF type id ; type id ; type id ; EOF") == "accept"

    def test_three_params(self):
        tokens = "BOF type id ( type id , type id , type id ) { } EOF"
        assert run_parser(self.G, tokens) == "accept"

    def test_empty_program_reject(self):
        assert run_parser(self.G, "BOF EOF") == "reject"

    def test_trailing_comma_reject(self):
        assert run_parser(self.G, "BOF type id ( type id , ) { } EOF") == "reject"

    def test_missing_id_reject(self):
        assert run_parser(self.G, "BOF type ( ) { } EOF") == "reject"

    def test_missing_semi_reject(self):
        assert run_parser(self.G, "BOF type id EOF") == "reject"

    def test_extra_brace_reject(self):
        assert run_parser(self.G, "BOF type id ( ) { } } EOF") == "reject"
