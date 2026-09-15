
import subprocess
import os
import tempfile
import pytest

WORKDIR = "/app"
TIMEOUT = 120


def compile_and_run(program_text, stdin_input="0\n" * 100):
    """Compile an R5 program and run the resulting binary, returning stdout."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".scm", dir=WORKDIR, delete=False
    ) as f:
        f.write(program_text)
        prog_path = f.name

    try:
        # Remove old output binary
        output_bin = os.path.join(WORKDIR, "output")
        if os.path.exists(output_bin):
            os.remove(output_bin)

        # Compile with -f to skip per-pass interpretation (much faster)
        result = subprocess.run(
            ["racket", "main.rkt", "-f", prog_path],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=WORKDIR,
        )
        if not os.path.exists(output_bin):
            raise RuntimeError(
                f"Compilation failed.\nstdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
            )

        # Run binary
        run_result = subprocess.run(
            [output_bin],
            input=stdin_input,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=WORKDIR,
        )
        return run_result.stdout.strip()
    finally:
        os.unlink(prog_path)


class TestBasicFunctions:
    """Test basic function definition and application (R4 features)."""

    def test_constant_function(self):
        prog = '(program (define (f x) 1) (f 2))'
        assert compile_and_run(prog) == "1"

    def test_identity_function(self):
        prog = '(program (define (f x) x) (f 42))'
        assert compile_and_run(prog) == "42"

    def test_arithmetic_function(self):
        prog = '(program (define (f x) (+ x 1)) (f 41))'
        assert compile_and_run(prog) == "42"

    def test_two_arg_function(self):
        prog = '(program (define (f x y) (+ x y)) (f 20 22))'
        assert compile_and_run(prog) == "42"

    def test_multiple_functions(self):
        prog = """(program
            (define (f x) x)
            (define (g y) (+ (f y) 1))
            (g 2))"""
        assert compile_and_run(prog) == "3"


class TestRecursion:
    """Test recursive function calls."""

    def test_fibonacci_small(self):
        prog = """(program
            (define (fib x)
              (if (eq? x 0) 1
                (if (eq? x 1) 1
                  (+ (fib (- x 1)) (fib (- x 2))))))
            (fib 2))"""
        assert compile_and_run(prog) == "2"

    def test_fibonacci_medium(self):
        prog = """(program
            (define (fib x)
              (if (eq? x 0) 1
                (if (eq? x 1) 1
                  (+ (fib (- x 1)) (fib (- x 2))))))
            (fib 5))"""
        assert compile_and_run(prog) == "8"

    def test_fibonacci_with_read(self):
        prog = """(program
            (define (fib x)
              (if (eq? x 0) 1
                (if (eq? x 1) 1
                  (+ (fib (- x 1)) (fib (- x 2))))))
            (let ([x (read)])
              (if (< x 8) (fib x) (fib 8))))"""
        assert compile_and_run(prog, "5\n") == "8"


class TestVectorsAndMutation:
    """Test heap-allocated vectors, set!, and while loops."""

    def test_make_pair(self):
        prog = """(program
            (define (make-pair x y)
              (let ([v (make-vector 2)])
                (let ([_ (vector-set! v 0 x)])
                  (let ([_ (vector-set! v 1 y)]) v))))
            (let ([p (make-pair 20 22)])
              (+ (vector-ref p 0) (vector-ref p 1))))"""
        assert compile_and_run(prog) == "42"

    def test_while_sum(self):
        prog = """(program
            (define (count_to n)
              (let ([i 0])
                (let ([sum 0])
                  (begin
                    (while (<= i n)
                      (begin (set! sum (+ sum i)) (set! i (+ i 1))))
                    sum))))
            (count_to 10))"""
        assert compile_and_run(prog) == "55"


class TestLimitFunctions:
    """Test functions with more than 6 arguments (limit-functions pass)."""

    def test_seven_args(self):
        prog = """(program
            (define (weighted7 a b c d e f g)
              (+ (+ (+ a b) (+ c d)) (+ (+ e f) g)))
            (weighted7 1 2 3 4 5 6 7))"""
        assert compile_and_run(prog) == "28"


class TestClosures:
    """Test lambda expressions and closure conversion (R5 features)."""

    def test_basic_closure(self):
        prog = """(program
            (define (f x) (lambda (y) (+ x y)))
            ((f 10) 32))"""
        assert compile_and_run(prog) == "42"

    def test_nested_closure(self):
        prog = """(program
            (define (f a b c)
              (lambda (x y)
                (lambda (z) (+ (+ (+ a b) c) (+ (+ x y) z)))))
            (((f 1 2 3) 4 5) 6))"""
        assert compile_and_run(prog) == "21"

    def test_make_adder(self):
        prog = """(program
            (define (make-adder n)
              (lambda (x) (+ n x)))
            (let ([add5 (make-adder 5)])
              (+ (add5 10) (add5 20))))"""
        assert compile_and_run(prog) == "40"

    def test_closure_with_mutation_and_loop(self):
        """Test r5-2: closure that uses set! and calls top-level functions in a loop."""
        prog = """(program
            (define (is_even n)
              (begin (while (> n 0) (set! n (- n 2)))
                     (eq? n 0)))
            (define (is_odd n) (not (is_even n)))
            (define (count_evens_up_to n)
              (let ([i 0])
                (let ([cnt 0])
                  (let ([loop (void)])
                    (begin
                      (set! loop
                            (lambda ()
                              (if (<= i n)
                                  (begin
                                    (if (is_even i)
                                        (set! cnt (+ cnt 1))
                                        (set! cnt cnt))
                                    (set! i (+ i 1))
                                    (loop))
                                  cnt)))
                      (loop))))))
            (count_evens_up_to (read)))"""
        assert compile_and_run(prog, "2\n") == "2"
