"""Test suite for Mini-ML type inference system.

Tests cover three layers:
- Parser: source code -> AST correctness
- Inference: AST -> type correctness (unit tests)
- CLI: end-to-end source file -> type output (integration tests)
"""

import os
import subprocess
import sys
import pytest

sys.path.insert(0, "/app")

from ml_ast import (
    IntLit, BoolLit, Unit, Var, BinOp, Not, Neg, If,
    Lam, App, Let, LetRec, MkPair, Fst, Snd, Nil, Cons, MatchList,
)
from ml_types import TInt, TBool, TUnit, TVar, TArrow, TPair, TList, Scheme
from ml_infer import infer_program


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(t):
    """Canonicalize type variable names by left-to-right traversal order."""
    mapping = {}
    counter = [0]

    def go(ty):
        if isinstance(ty, (TInt, TBool, TUnit)):
            return ty
        if isinstance(ty, TVar):
            if ty.name not in mapping:
                mapping[ty.name] = chr(ord("a") + counter[0])
                counter[0] += 1
            return TVar(mapping[ty.name])
        if isinstance(ty, TArrow):
            return TArrow(go(ty.arg), go(ty.ret))
        if isinstance(ty, TPair):
            return TPair(go(ty.fst), go(ty.snd))
        if isinstance(ty, TList):
            return TList(go(ty.elem))
        raise ValueError(f"Unknown type node: {type(ty)}")

    return go(t)


def assert_type(expr, expected):
    """Assert inferred type equals expected up to alpha-renaming."""
    actual = infer_program(expr)
    na = _normalize(actual)
    ne = _normalize(expected)
    assert na == ne, f"Expected {ne}, got {na} (raw actual: {actual})"


def assert_type_error(expr):
    """Assert that type inference raises an exception."""
    succeeded = False
    result = None
    try:
        result = infer_program(expr)
        succeeded = True
    except Exception:
        pass
    assert not succeeded, f"Expected type error, got: {result}"


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParser:
    def test_parse_int(self):
        from ml_parser import parse
        assert parse("42") == IntLit(42)

    def test_parse_true(self):
        from ml_parser import parse
        assert parse("true") == BoolLit(True)

    def test_parse_false(self):
        from ml_parser import parse
        assert parse("false") == BoolLit(False)

    def test_parse_unit(self):
        from ml_parser import parse
        assert parse("()") == Unit()

    def test_parse_var(self):
        from ml_parser import parse
        assert parse("x") == Var("x")

    def test_parse_add(self):
        from ml_parser import parse
        assert parse("1 + 2") == BinOp("+", IntLit(1), IntLit(2))

    def test_parse_sub(self):
        from ml_parser import parse
        assert parse("3 - 1") == BinOp("-", IntLit(3), IntLit(1))

    def test_parse_precedence_mul_add(self):
        from ml_parser import parse
        # 1 + 2 * 3 should be 1 + (2 * 3)
        assert parse("1 + 2 * 3") == BinOp("+", IntLit(1), BinOp("*", IntLit(2), IntLit(3)))

    def test_parse_precedence_add_left_assoc(self):
        from ml_parser import parse
        # 1 + 2 + 3 should be (1 + 2) + 3
        assert parse("1 + 2 + 3") == BinOp("+", BinOp("+", IntLit(1), IntLit(2)), IntLit(3))

    def test_parse_comparison(self):
        from ml_parser import parse
        assert parse("1 < 2") == BinOp("<", IntLit(1), IntLit(2))

    def test_parse_eq(self):
        from ml_parser import parse
        assert parse("x == 0") == BinOp("==", Var("x"), IntLit(0))

    def test_parse_logical_and(self):
        from ml_parser import parse
        assert parse("true && false") == BinOp("&&", BoolLit(True), BoolLit(False))

    def test_parse_logical_or(self):
        from ml_parser import parse
        assert parse("true || false") == BinOp("||", BoolLit(True), BoolLit(False))

    def test_parse_neg(self):
        from ml_parser import parse
        assert parse("-5") == Neg(IntLit(5))

    def test_parse_not(self):
        from ml_parser import parse
        assert parse("not true") == Not(BoolLit(True))

    def test_parse_lambda(self):
        from ml_parser import parse
        assert parse("fun x -> x") == Lam("x", Var("x"))

    def test_parse_application(self):
        from ml_parser import parse
        assert parse("f x") == App(Var("f"), Var("x"))

    def test_parse_application_left_assoc(self):
        from ml_parser import parse
        # f x y should be (f x) y
        assert parse("f x y") == App(App(Var("f"), Var("x")), Var("y"))

    def test_parse_let(self):
        from ml_parser import parse
        assert parse("let x = 1 in x") == Let("x", IntLit(1), Var("x"))

    def test_parse_letrec(self):
        from ml_parser import parse
        result = parse("let rec f = fun x -> f x in f")
        expected = LetRec("f", Lam("x", App(Var("f"), Var("x"))), Var("f"))
        assert result == expected

    def test_parse_if(self):
        from ml_parser import parse
        result = parse("if true then 1 else 2")
        assert result == If(BoolLit(True), IntLit(1), IntLit(2))

    def test_parse_pair(self):
        from ml_parser import parse
        assert parse("(1, 2)") == MkPair(IntLit(1), IntLit(2))

    def test_parse_fst(self):
        from ml_parser import parse
        assert parse("fst (1, 2)") == Fst(MkPair(IntLit(1), IntLit(2)))

    def test_parse_snd(self):
        from ml_parser import parse
        assert parse("snd (1, 2)") == Snd(MkPair(IntLit(1), IntLit(2)))

    def test_parse_nil(self):
        from ml_parser import parse
        assert parse("[]") == Nil()

    def test_parse_cons(self):
        from ml_parser import parse
        assert parse("1 :: []") == Cons(IntLit(1), Nil())

    def test_parse_cons_right_assoc(self):
        from ml_parser import parse
        # 1 :: 2 :: [] should be 1 :: (2 :: [])
        assert parse("1 :: 2 :: []") == Cons(IntLit(1), Cons(IntLit(2), Nil()))

    def test_parse_match(self):
        from ml_parser import parse
        result = parse("match xs with [] -> 0 | h :: t -> h")
        expected = MatchList(Var("xs"), IntLit(0), "h", "t", Var("h"))
        assert result == expected

    def test_parse_keyword_prefix_is_ident(self):
        from ml_parser import parse
        # 'letting' should be a valid identifier (not confused with 'let')
        assert parse("letting") == Var("letting")

    def test_parse_parens_grouping(self):
        from ml_parser import parse
        # (1 + 2) * 3 should override precedence
        assert parse("(1 + 2) * 3") == BinOp("*", BinOp("+", IntLit(1), IntLit(2)), IntLit(3))


# ---------------------------------------------------------------------------
# Basic literal and operator inference tests
# ---------------------------------------------------------------------------

class TestBasics:
    def test_int_literal(self):
        assert_type(IntLit(42), TInt())

    def test_bool_literal(self):
        assert_type(BoolLit(True), TBool())

    def test_unit_literal(self):
        assert_type(Unit(), TUnit())

    def test_arithmetic_add(self):
        assert_type(BinOp("+", IntLit(1), IntLit(2)), TInt())

    def test_arithmetic_mul(self):
        assert_type(BinOp("*", IntLit(3), IntLit(4)), TInt())

    def test_comparison_lt(self):
        assert_type(BinOp("<", IntLit(1), IntLit(2)), TBool())

    def test_comparison_eq(self):
        assert_type(BinOp("==", IntLit(1), IntLit(2)), TBool())

    def test_logical_and(self):
        assert_type(BinOp("&&", BoolLit(True), BoolLit(False)), TBool())

    def test_logical_or(self):
        assert_type(BinOp("||", BoolLit(True), BoolLit(False)), TBool())

    def test_negation(self):
        assert_type(Neg(IntLit(5)), TInt())

    def test_not(self):
        assert_type(Not(BoolLit(True)), TBool())


# ---------------------------------------------------------------------------
# Lambda and application tests
# ---------------------------------------------------------------------------

class TestFunctions:
    def test_identity(self):
        # fun x -> x : 'a -> 'a
        assert_type(
            Lam("x", Var("x")),
            TArrow(TVar("a"), TVar("a")),
        )

    def test_const(self):
        # fun x -> fun y -> x : 'a -> 'b -> 'a
        assert_type(
            Lam("x", Lam("y", Var("x"))),
            TArrow(TVar("a"), TArrow(TVar("b"), TVar("a"))),
        )

    def test_simple_application(self):
        # (fun x -> x + 1) 5 : int
        assert_type(
            App(Lam("x", BinOp("+", Var("x"), IntLit(1))), IntLit(5)),
            TInt(),
        )

    def test_higher_order_apply(self):
        assert_type(
            Let("apply", Lam("f", Lam("x", App(Var("f"), Var("x")))),
                App(App(Var("apply"), Lam("n", BinOp("+", Var("n"), Var("n")))),
                    IntLit(5))),
            TInt(),
        )

    def test_compose_type(self):
        assert_type(
            Let("compose",
                Lam("f", Lam("g", Lam("x",
                    App(Var("f"), App(Var("g"), Var("x")))))),
                Var("compose")),
            TArrow(
                TArrow(TVar("a"), TVar("b")),
                TArrow(
                    TArrow(TVar("c"), TVar("a")),
                    TArrow(TVar("c"), TVar("b")))),
        )


# ---------------------------------------------------------------------------
# Let-polymorphism (the critical tests)
# ---------------------------------------------------------------------------

class TestLetPolymorphism:
    def test_let_poly_id(self):
        # let id = fun x -> x in (id 1, id true) : (int, bool)
        assert_type(
            Let("id", Lam("x", Var("x")),
                MkPair(App(Var("id"), IntLit(1)),
                       App(Var("id"), BoolLit(True)))),
            TPair(TInt(), TBool()),
        )

    def test_monomorphic_lambda_rejects(self):
        # (fun id -> (id 1, id true)) (fun x -> x) : TYPE ERROR
        assert_type_error(
            App(Lam("id",
                     MkPair(App(Var("id"), IntLit(1)),
                            App(Var("id"), BoolLit(True)))),
                Lam("x", Var("x"))),
        )

    def test_nested_let_poly(self):
        assert_type(
            Let("id", Lam("x", Var("x")),
                Let("f", App(Var("id"), Lam("y", Var("y"))),
                    MkPair(App(Var("f"), IntLit(1)),
                           App(Var("f"), BoolLit(True))))),
            TPair(TInt(), TBool()),
        )

    def test_let_poly_with_binop(self):
        assert_type(
            Let("double", Lam("x", BinOp("+", Var("x"), Var("x"))),
                App(Var("double"), IntLit(5))),
            TInt(),
        )


# ---------------------------------------------------------------------------
# Recursive definitions
# ---------------------------------------------------------------------------

class TestRecursion:
    def test_factorial(self):
        assert_type(
            LetRec("fact",
                Lam("n", If(BinOp("==", Var("n"), IntLit(0)),
                            IntLit(1),
                            BinOp("*", Var("n"),
                                  App(Var("fact"),
                                      BinOp("-", Var("n"), IntLit(1)))))),
                App(Var("fact"), IntLit(5))),
            TInt(),
        )

    def test_polymorphic_letrec_length(self):
        assert_type(
            LetRec("length",
                Lam("l", MatchList(Var("l"),
                    IntLit(0),
                    "h", "t",
                    BinOp("+", IntLit(1), App(Var("length"), Var("t"))))),
                MkPair(
                    App(Var("length"), Cons(IntLit(1), Nil())),
                    App(Var("length"), Cons(BoolLit(True), Nil())))),
            TPair(TInt(), TInt()),
        )


# ---------------------------------------------------------------------------
# Pairs
# ---------------------------------------------------------------------------

class TestPairs:
    def test_pair_creation(self):
        assert_type(MkPair(IntLit(42), BoolLit(True)), TPair(TInt(), TBool()))

    def test_fst(self):
        assert_type(
            Let("p", MkPair(IntLit(1), BoolLit(True)), Fst(Var("p"))),
            TInt(),
        )

    def test_snd(self):
        assert_type(
            Let("p", MkPair(IntLit(1), BoolLit(True)), Snd(Var("p"))),
            TBool(),
        )

    def test_fst_snd_round_trip(self):
        assert_type(
            Let("p", MkPair(IntLit(1), BoolLit(True)),
                MkPair(Fst(Var("p")), Snd(Var("p")))),
            TPair(TInt(), TBool()),
        )


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------

class TestLists:
    def test_nil(self):
        assert_type(Nil(), TList(TVar("a")))

    def test_cons_int(self):
        assert_type(Cons(IntLit(1), Nil()), TList(TInt()))

    def test_cons_nested(self):
        assert_type(
            Cons(IntLit(1), Cons(IntLit(2), Cons(IntLit(3), Nil()))),
            TList(TInt()),
        )

    def test_list_sum(self):
        assert_type(
            LetRec("sum",
                Lam("l", MatchList(Var("l"),
                    IntLit(0),
                    "h", "t",
                    BinOp("+", Var("h"), App(Var("sum"), Var("t"))))),
                Var("sum")),
            TArrow(TList(TInt()), TInt()),
        )

    def test_map(self):
        assert_type(
            LetRec("map",
                Lam("f", Lam("l",
                    MatchList(Var("l"),
                        Nil(),
                        "h", "t",
                        Cons(App(Var("f"), Var("h")),
                             App(App(Var("map"), Var("f")), Var("t")))))),
                Var("map")),
            TArrow(
                TArrow(TVar("a"), TVar("b")),
                TArrow(TList(TVar("a")), TList(TVar("b")))),
        )

    def test_foldr(self):
        assert_type(
            LetRec("foldr",
                Lam("f", Lam("z", Lam("l",
                    MatchList(Var("l"),
                        Var("z"),
                        "h", "t",
                        App(App(Var("f"), Var("h")),
                            App(App(App(Var("foldr"), Var("f")), Var("z")),
                                Var("t"))))))),
                Var("foldr")),
            TArrow(
                TArrow(TVar("a"), TArrow(TVar("b"), TVar("b"))),
                TArrow(TVar("b"), TArrow(TList(TVar("a")), TVar("b")))),
        )


# ---------------------------------------------------------------------------
# Type errors
# ---------------------------------------------------------------------------

class TestTypeErrors:
    def test_int_plus_bool(self):
        assert_type_error(BinOp("+", IntLit(1), BoolLit(True)))

    def test_bool_plus_bool(self):
        assert_type_error(BinOp("+", BoolLit(True), BoolLit(False)))

    def test_occurs_check(self):
        # fun x -> x x : infinite type (self-application)
        assert_type_error(Lam("x", App(Var("x"), Var("x"))))

    def test_if_branch_mismatch(self):
        assert_type_error(If(BoolLit(True), IntLit(1), BoolLit(False)))

    def test_non_function_application(self):
        assert_type_error(App(IntLit(42), IntLit(99)))

    def test_unbound_variable(self):
        assert_type_error(Var("undefined_var"))

    def test_cons_type_mismatch(self):
        assert_type_error(Cons(IntLit(1), Cons(BoolLit(True), Nil())))

    def test_fst_of_non_pair(self):
        assert_type_error(Fst(IntLit(42)))

    def test_match_non_list(self):
        assert_type_error(
            MatchList(IntLit(42), IntLit(0), "h", "t", Var("h"))
        )


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestCLI:
    def _run_cli(self, source, tmp_path):
        f = tmp_path / "test.ml"
        f.write_text(source)
        return subprocess.run(
            ["python3", "/app/ml_cli.py", str(f)],
            capture_output=True, text=True, timeout=10,
        )

    def test_cli_int(self, tmp_path):
        result = self._run_cli("42", tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == "int"

    def test_cli_bool(self, tmp_path):
        result = self._run_cli("true", tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == "bool"

    def test_cli_unit(self, tmp_path):
        result = self._run_cli("()", tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == "unit"

    def test_cli_arithmetic(self, tmp_path):
        result = self._run_cli("1 + 2 * 3", tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == "int"

    def test_cli_function(self, tmp_path):
        result = self._run_cli("fun x -> x + 1", tmp_path)
        assert result.returncode == 0
        out = result.stdout.strip()
        assert "int" in out and "->" in out

    def test_cli_let_poly(self, tmp_path):
        result = self._run_cli("let id = fun x -> x in id 42", tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == "int"

    def test_cli_pair(self, tmp_path):
        result = self._run_cli("(1, true)", tmp_path)
        assert result.returncode == 0
        out = result.stdout.strip()
        assert "int" in out and "bool" in out

    def test_cli_list(self, tmp_path):
        result = self._run_cli("1 :: 2 :: []", tmp_path)
        assert result.returncode == 0
        out = result.stdout.strip()
        assert "int" in out and "list" in out

    def test_cli_type_error(self, tmp_path):
        result = self._run_cli("1 + true", tmp_path)
        assert result.returncode != 0

    def test_cli_factorial(self, tmp_path):
        source = "let rec fact = fun n -> if n == 0 then 1 else n * fact (n - 1) in fact 5"
        result = self._run_cli(source, tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == "int"

    def test_cli_match(self, tmp_path):
        source = "let rec sum = fun l -> match l with [] -> 0 | h :: t -> h + sum t in sum (1 :: 2 :: [])"
        result = self._run_cli(source, tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == "int"
