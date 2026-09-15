
"""Tests for the stack-safe evaluator with native operator library."""

import sys
import os
import ctypes

if '/app' not in sys.path:
    sys.path.insert(0, '/app')
os.chdir('/app')

from lang import (
    PROGRAMS, eval_direct,
    Var, IntLit, BoolLit, BinOp, If, Lam, App, Let, LetRec,
    VClosure, VRecClosure,
)
import pipeline


class TestCorrectness:
    """Pipeline must produce identical results to eval_direct on all programs."""

    def test_all_programs(self):
        for name, prog, expected in PROGRAMS:
            result = pipeline.run(prog)
            assert result == expected, (
                f"Program '{name}': expected {expected}, got {result}"
            )

    def test_matches_direct_eval(self):
        for name, prog, expected in PROGRAMS:
            direct = eval_direct(prog)
            piped = pipeline.run(prog)
            assert direct == piped, (
                f"Program '{name}': direct={direct}, pipeline={piped}"
            )


class TestBoundedStack:
    """Pipeline must use constant stack — works under sys.setrecursionlimit(500)."""

    def test_deep_linear_recursion(self):
        """sum(1..50000) via recursion."""
        prog = LetRec('sum', 'n',
                       If(BinOp('==', Var('n'), IntLit(0)),
                          IntLit(0),
                          BinOp('+', Var('n'),
                                App(Var('sum'),
                                    BinOp('-', Var('n'), IntLit(1))))),
                       App(Var('sum'), IntLit(50000)))
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(500)
        try:
            result = pipeline.run(prog)
            assert result == 1250025000, f"Expected 1250025000, got {result}"
        finally:
            sys.setrecursionlimit(old)

    def test_deep_tail_recursion(self):
        """Countdown from 100000."""
        prog = LetRec('loop', 'n',
                       If(BinOp('==', Var('n'), IntLit(0)),
                          IntLit(42),
                          App(Var('loop'),
                              BinOp('-', Var('n'), IntLit(1)))),
                       App(Var('loop'), IntLit(100000)))
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(500)
        try:
            result = pipeline.run(prog)
            assert result == 42, f"Expected 42, got {result}"
        finally:
            sys.setrecursionlimit(old)

    def test_deep_curried_recursion(self):
        """Curried accumulator: sum_acc(10000)(0)."""
        prog = LetRec('sum_acc', 'n',
                       Lam('acc',
                           If(BinOp('==', Var('n'), IntLit(0)),
                              Var('acc'),
                              App(App(Var('sum_acc'),
                                      BinOp('-', Var('n'), IntLit(1))),
                                  BinOp('+', Var('acc'), Var('n'))))),
                       App(App(Var('sum_acc'), IntLit(10000)), IntLit(0)))
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(500)
        try:
            result = pipeline.run(prog)
            assert result == 50005000, f"Expected 50005000, got {result}"
        finally:
            sys.setrecursionlimit(old)

    def test_deep_higher_order(self):
        """iterate inc 20000 0 = 20000."""
        prog = LetRec('iterate', 'f',
                       Lam('n', Lam('x',
                           If(BinOp('==', Var('n'), IntLit(0)),
                              Var('x'),
                              App(App(App(Var('iterate'), Var('f')),
                                      BinOp('-', Var('n'), IntLit(1))),
                                  App(Var('f'), Var('x')))))),
                       App(App(App(Var('iterate'),
                                   Lam('x', BinOp('+', Var('x'), IntLit(1)))),
                               IntLit(20000)),
                           IntLit(0)))
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(500)
        try:
            result = pipeline.run(prog)
            assert result == 20000, f"Expected 20000, got {result}"
        finally:
            sys.setrecursionlimit(old)


class TestEdgeCases:
    """Various edge cases and tricky scenarios."""

    def test_zero_factorial(self):
        prog = LetRec('fact', 'n',
                       If(BinOp('==', Var('n'), IntLit(0)),
                          IntLit(1),
                          BinOp('*', Var('n'),
                                App(Var('fact'),
                                    BinOp('-', Var('n'), IntLit(1))))),
                       App(Var('fact'), IntLit(0)))
        assert pipeline.run(prog) == 1

    def test_boolean_operations(self):
        prog = If(BinOp('>', IntLit(5), IntLit(3)),
                  BinOp('<=', IntLit(2), IntLit(2)),
                  BoolLit(False))
        assert pipeline.run(prog) is True

    def test_nested_applications(self):
        """f(g(h(x))): h(10)=7, g(7)=14, f(14)=15."""
        prog = Let('f', Lam('x', BinOp('+', Var('x'), IntLit(1))),
                   Let('g', Lam('x', BinOp('*', Var('x'), IntLit(2))),
                       Let('h', Lam('x', BinOp('-', Var('x'), IntLit(3))),
                           App(Var('f'),
                               App(Var('g'),
                                   App(Var('h'), IntLit(10)))))))
        assert pipeline.run(prog) == 15

    def test_closure_identity(self):
        """Two closures from the same lambda, different captures."""
        prog = Let('make', Lam('x', Lam('y', BinOp('+', Var('x'), Var('y')))),
                   BinOp('-',
                         App(App(Var('make'), IntLit(100)), IntLit(1)),
                         App(App(Var('make'), IntLit(50)), IntLit(2))))
        # 101 - 52 = 49
        assert pipeline.run(prog) == 49

    def test_recursive_closure_builder(self):
        """Recursive function that builds and returns closures."""
        prog = LetRec('build', 'n',
                       If(BinOp('==', Var('n'), IntLit(0)),
                          Lam('x', Var('x')),
                          Let('inner',
                              App(Var('build'),
                                  BinOp('-', Var('n'), IntLit(1))),
                              Lam('x', BinOp('+',
                                             App(Var('inner'), Var('x')),
                                             Var('n'))))),
                       App(App(Var('build'), IntLit(5)), IntLit(100)))
        # build(5)(100) = 100 + 1 + 2 + 3 + 4 + 5 = 115
        assert pipeline.run(prog) == 115

    def test_integer_division_and_modulo(self):
        prog = BinOp('+',
                     BinOp('//', IntLit(17), IntLit(5)),
                     BinOp('%', IntLit(17), IntLit(5)))
        # 3 + 2 = 5
        assert pipeline.run(prog) == 5


class TestNativeLibrary:
    """Verify native operator library is compiled, loaded, and used."""

    def test_libops_exists(self):
        """libops.so must be compiled from ops.c."""
        assert os.path.isfile('/app/libops.so'), (
            "libops.so not found at /app/libops.so — ops.c must be compiled"
        )

    def test_pipeline_references_native_lib(self):
        """pipeline.py must use ctypes to load the native operator library."""
        with open('/app/pipeline.py', 'r') as f:
            source = f.read()
        assert 'ctypes' in source, (
            "pipeline.py must use ctypes to interface with the native library"
        )
        assert 'libops' in source, (
            "pipeline.py must reference libops.so"
        )

    def test_native_library_directly(self):
        """Load and call the C library functions directly to verify they work."""
        lib = ctypes.CDLL('/app/libops.so')
        lib.op_from_string.argtypes = [ctypes.c_char_p]
        lib.op_from_string.restype = ctypes.c_int
        lib.eval_binop.argtypes = [
            ctypes.c_int, ctypes.c_longlong, ctypes.c_longlong,
            ctypes.POINTER(ctypes.c_longlong), ctypes.POINTER(ctypes.c_int)
        ]
        lib.eval_binop.restype = ctypes.c_int

        # Test addition: 3 + 4 = 7
        op = lib.op_from_string(b'+')
        assert op >= 0, "op_from_string should recognize '+'"
        out_val = ctypes.c_longlong()
        out_bool = ctypes.c_int()
        rc = lib.eval_binop(op, 3, 4, ctypes.byref(out_val), ctypes.byref(out_bool))
        assert rc == 0, f"eval_binop returned error code {rc}"
        assert out_val.value == 7, f"Expected 7, got {out_val.value}"
        assert out_bool.value == 0, "Addition should not be flagged as boolean"

        # Test comparison: 5 > 3 = True (1, is_bool=1)
        op = lib.op_from_string(b'>')
        rc = lib.eval_binop(op, 5, 3, ctypes.byref(out_val), ctypes.byref(out_bool))
        assert rc == 0
        assert out_val.value == 1
        assert out_bool.value == 1, "Comparison should be flagged as boolean"

        # Test modpow: 2^^10 = 1024
        op = lib.op_from_string(b'^^')
        assert op >= 0, "op_from_string should recognize '^^'"
        rc = lib.eval_binop(op, 2, 10, ctypes.byref(out_val), ctypes.byref(out_bool))
        assert rc == 0
        assert out_val.value == 1024, f"Expected 1024, got {out_val.value}"

    def test_modpow_operator(self):
        """The ^^ operator (modular exponentiation) via pipeline.run."""
        # 2^^10 = 1024 (no modular reduction since 1024 < 10^9+7)
        prog = BinOp('^^', IntLit(2), IntLit(10))
        result = pipeline.run(prog)
        assert result == 1024, f"Expected 1024, got {result}"

    def test_modpow_large(self):
        """Modular exponentiation with reduction: 3^^20 mod (10^9+7) = 486784380."""
        prog = BinOp('^^', IntLit(3), IntLit(20))
        result = pipeline.run(prog)
        assert result == 486784380, f"Expected 486784380, got {result}"

    def test_modpow_in_expression(self):
        """^^ used within a larger expression: let x = 2 in (x ^^ 10) + 1."""
        prog = Let('x', IntLit(2),
                   BinOp('+', BinOp('^^', Var('x'), IntLit(10)), IntLit(1)))
        result = pipeline.run(prog)
        assert result == 1025, f"Expected 1025, got {result}"

    def test_modpow_in_recursive_context(self):
        """^^ used inside a recursive function under stack constraint."""
        # sum of 2^^i for i=1..50 (computed recursively)
        prog = LetRec('sum_pow', 'n',
                       If(BinOp('==', Var('n'), IntLit(0)),
                          IntLit(0),
                          BinOp('+',
                                BinOp('^^', IntLit(2), Var('n')),
                                App(Var('sum_pow'),
                                    BinOp('-', Var('n'), IntLit(1))))),
                       App(Var('sum_pow'), IntLit(50)))
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(500)
        try:
            result = pipeline.run(prog)
            # sum(pow(2, i, 10**9+7) for i in range(1, 51))
            expected = sum(pow(2, i, 10**9 + 7) for i in range(1, 51))
            assert result == expected, f"Expected {expected}, got {result}"
        finally:
            sys.setrecursionlimit(old)
