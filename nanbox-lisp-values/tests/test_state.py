
import subprocess
import os
import pytest

BINARY = "/app/lisp"

# Compile the project at module load time
_build = subprocess.run(
    ["make", "-C", "/app", "clean", "all"],
    capture_output=True, text=True, timeout=60,
)
if _build.returncode != 0:
    raise RuntimeError(f"Build failed:\n{_build.stderr}")


def run_eval(expr):
    """Evaluate a Lisp expression and return (stdout, stderr, returncode)."""
    r = subprocess.run(
        [BINARY, "--eval", expr],
        capture_output=True, text=True, timeout=10,
    )
    return r.stdout.strip(), r.stderr.strip(), r.returncode


# ---- sizeof checks ----

def test_sizeof_flag():
    """sizeof(Value) must be 8 via --sizeof flag."""
    r = subprocess.run([BINARY, "--sizeof"], capture_output=True, text=True)
    assert r.stdout.strip() == "8", (
        f"sizeof(Value) = {r.stdout.strip()}, expected 8"
    )


def test_sizeof_builtin():
    """sizeof(Value) must be 8 via the sizeof-value Lisp builtin."""
    out, _, _ = run_eval("(sizeof-value)")
    assert out == "8", f"sizeof-value returned {out}, expected 8"


# ---- basic types ----

def test_nil():
    out, _, _ = run_eval("nil")
    assert out == "nil"


def test_bool_true():
    out, _, _ = run_eval("#t")
    assert out == "#t"


def test_bool_false():
    out, _, _ = run_eval("#f")
    assert out == "#f"


def test_integer_positive():
    out, _, _ = run_eval("42")
    assert out == "42"


def test_integer_negative():
    out, _, _ = run_eval("-1")
    assert out == "-1"


def test_integer_zero():
    out, _, _ = run_eval("0")
    assert out == "0"


def test_integer_max32():
    out, _, _ = run_eval("2147483647")
    assert out == "2147483647"


def test_integer_min32():
    out, _, _ = run_eval("-2147483648")
    assert out == "-2147483648"


def test_float_pi():
    out, _, _ = run_eval("3.14")
    assert out.startswith("3.14")


def test_float_zero():
    out, _, _ = run_eval("0.0")
    assert "0" in out


def test_float_infinity():
    out, _, _ = run_eval("(/ 1.0 0.0)")
    assert "inf" in out.lower()


def test_float_neg_infinity():
    out, _, _ = run_eval("(/ -1.0 0.0)")
    assert "inf" in out.lower()


def test_string_simple():
    out, _, _ = run_eval('"hello"')
    assert out == '"hello"'


def test_string_with_space():
    out, _, _ = run_eval('"hello world"')
    assert out == '"hello world"'


# ---- arithmetic ----

def test_add_integers():
    out, _, _ = run_eval("(+ 1 2 3)")
    assert out == "6"


def test_sub():
    out, _, _ = run_eval("(- 10 3)")
    assert out == "7"


def test_mul():
    out, _, _ = run_eval("(* 4 5)")
    assert out == "20"


def test_div_float():
    out, _, _ = run_eval("(/ 10.0 3.0)")
    assert out.startswith("3.333")


def test_negate():
    out, _, _ = run_eval("(- 7)")
    assert out == "-7"


def test_add_floats():
    out, _, _ = run_eval("(+ 1.5 2.5)")
    assert float(out) == 4.0


def test_mul_floats():
    out, _, _ = run_eval("(* 2.0 3.0)")
    assert float(out) == 6.0


def test_mixed_int_float():
    out, _, _ = run_eval("(+ 1 2.0)")
    assert float(out) == 3.0


def test_mixed_mul():
    out, _, _ = run_eval("(* 3 1.5)")
    assert float(out) == 4.5


def test_modulo():
    out, _, _ = run_eval("(% 10 3)")
    assert out == "1"


def test_modulo2():
    out, _, _ = run_eval("(% 15 4)")
    assert out == "3"


def test_abs_negative():
    out, _, _ = run_eval("(abs -5)")
    assert out == "5"


def test_abs_positive():
    out, _, _ = run_eval("(abs 5)")
    assert out == "5"


# ---- comparisons ----

def test_lt_true():
    out, _, _ = run_eval("(< 1 2)")
    assert out == "#t"


def test_gt_false():
    out, _, _ = run_eval("(> 1 2)")
    assert out == "#f"


def test_eq_true():
    out, _, _ = run_eval("(= 42 42)")
    assert out == "#t"


def test_le():
    out, _, _ = run_eval("(<= 3 3)")
    assert out == "#t"


def test_ge():
    out, _, _ = run_eval("(>= 5 3)")
    assert out == "#t"


# ---- list operations ----

def test_cons_car():
    out, _, _ = run_eval("(car (cons 1 2))")
    assert out == "1"


def test_cons_cdr():
    out, _, _ = run_eval("(cdr (cons 1 2))")
    assert out == "2"


def test_list_car():
    out, _, _ = run_eval("(car (list 1 2 3))")
    assert out == "1"


def test_list_length():
    out, _, _ = run_eval("(length (list 1 2 3))")
    assert out == "3"


def test_cadr():
    out, _, _ = run_eval("(car (cdr (list 1 2 3)))")
    assert out == "2"


def test_caddr():
    out, _, _ = run_eval("(car (cdr (cdr (list 1 2 3))))")
    assert out == "3"


def test_dotted_pair_car():
    out, _, _ = run_eval("(car '(1 . 2))")
    assert out == "1"


def test_dotted_pair_cdr():
    out, _, _ = run_eval("(cdr '(1 . 2))")
    assert out == "2"


# ---- conditionals ----

def test_if_true():
    out, _, _ = run_eval("(if #t 1 2)")
    assert out == "1"


def test_if_false():
    out, _, _ = run_eval("(if #f 1 2)")
    assert out == "2"


def test_if_expr():
    out, _, _ = run_eval("(if (> 3 2) 42 0)")
    assert out == "42"


def test_cond():
    expr = '(cond ((= 1 2) "no") ((= 1 1) "yes") (else "default"))'
    out, _, _ = run_eval(expr)
    assert out == '"yes"'


# ---- let bindings ----

def test_let_simple():
    out, _, _ = run_eval("(let ((x 10) (y 20)) (+ x y))")
    assert out == "30"


def test_let_nested():
    out, _, _ = run_eval("(let ((x 5)) (let ((y (* x 2))) (+ x y)))")
    assert out == "15"


# ---- boolean logic ----

def test_and_tt():
    out, _, _ = run_eval("(and #t #t)")
    assert out == "#t"


def test_and_tf():
    out, _, _ = run_eval("(and #t #f)")
    assert out == "#f"


def test_or_ft():
    out, _, _ = run_eval("(or #f #t)")
    assert out == "#t"


def test_not():
    out, _, _ = run_eval("(not #t)")
    assert out == "#f"


# ---- type predicates ----

def test_is_nil():
    out, _, _ = run_eval("(nil? nil)")
    assert out == "#t"


def test_is_number():
    out, _, _ = run_eval("(number? 42)")
    assert out == "#t"


def test_is_string():
    out, _, _ = run_eval('(string? "hello")')
    assert out == "#t"


def test_is_bool():
    out, _, _ = run_eval("(boolean? #t)")
    assert out == "#t"


def test_is_list():
    out, _, _ = run_eval("(list? (list 1 2))")
    assert out == "#t"


def test_is_symbol():
    out, _, _ = run_eval("(symbol? 'foo)")
    assert out == "#t"


# ---- type-of ----

def test_type_of_integer():
    out, _, _ = run_eval("(type-of 42)")
    assert out == "integer"


def test_type_of_float():
    out, _, _ = run_eval("(type-of 3.14)")
    assert out == "float"


def test_type_of_nil():
    out, _, _ = run_eval("(type-of nil)")
    assert out == "nil"


def test_type_of_boolean():
    out, _, _ = run_eval("(type-of #t)")
    assert out == "boolean"


def test_type_of_string():
    out, _, _ = run_eval('(type-of "hello")')
    assert out == "string"


def test_type_of_cons():
    out, _, _ = run_eval("(type-of '(1 2))")
    assert out == "cons"


def test_type_of_symbol():
    out, _, _ = run_eval("(type-of 'foo)")
    assert out == "symbol"


# ---- string ops ----

def test_string_append():
    out, _, _ = run_eval('(string-append "hello" " " "world")')
    assert out == '"hello world"'


def test_string_length():
    out, _, _ = run_eval('(length "hello")')
    assert out == "5"


def test_number_to_string():
    out, _, _ = run_eval("(number->string 42)")
    assert out == '"42"'


# ---- quote ----

def test_quote_symbol():
    out, _, _ = run_eval("'hello")
    assert out == "hello"


def test_quote_list():
    out, _, _ = run_eval("(car '(a b c))")
    assert out == "a"


# ---- equality ----

def test_equal_lists():
    out, _, _ = run_eval("(equal? (list 1 2 3) (list 1 2 3))")
    assert out == "#t"


def test_equal_strings():
    out, _, _ = run_eval('(equal? "hello" "hello")')
    assert out == "#t"


def test_equal_numbers():
    out, _, _ = run_eval("(equal? 42 42)")
    assert out == "#t"


# ---- complex expressions ----

def test_complex_nested():
    expr = """(let ((n 10))
                (let ((result (* n (- n 1))))
                  (+ result 1)))"""
    out, _, rc = run_eval(expr)
    assert rc == 0
    assert out == "91"


def test_begin():
    out, _, _ = run_eval("(begin 1 2 3)")
    assert out == "3"


def test_list_of_mixed_types():
    """A list containing different value types should work."""
    out, _, _ = run_eval('(length (list 1 "two" #t nil 5.0))')
    assert out == "5"


# ---- UndefinedBehaviorSanitizer ----

def test_ubsan_clean_build():
    """Code must compile and run without UBSan diagnostics."""
    ubsan_cflags = (
        "-Wall -Wextra -O1 -std=c11 -D_DEFAULT_SOURCE "
        "-Wno-unused-parameter -g "
        "-fsanitize=undefined -fno-sanitize-recover=all"
    )
    ubsan_ldflags = "-lm -fsanitize=undefined"

    build = subprocess.run(
        ["make", "-C", "/app", "clean", "all",
         f"CFLAGS={ubsan_cflags}", f"LDFLAGS={ubsan_ldflags}"],
        capture_output=True, text=True, timeout=60,
    )
    assert build.returncode == 0, f"UBSan build failed:\n{build.stderr}"

    # Run several expressions that exercise different types and operations
    exprs = [
        ("(+ 1 2)", "3"),
        ("(+ 1.5 2.5)", None),  # just check no crash
        ("(car (list 1 2 3))", "1"),
        ("(let ((x 42)) x)", "42"),
        ('(string-append "a" "b")', '"ab"'),
        ("(/ 1.0 0.0)", None),  # infinity
        ("(type-of 42)", "integer"),
        ("(sizeof-value)", "8"),
    ]
    for expr, expected in exprs:
        r = subprocess.run(
            [BINARY, "--eval", expr],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, (
            f"UBSan crash on '{expr}': rc={r.returncode}\n{r.stderr}"
        )
        if expected is not None:
            assert r.stdout.strip() == expected, (
                f"UBSan run '{expr}': got '{r.stdout.strip()}', expected '{expected}'"
            )

    # Rebuild normally for subsequent tests
    subprocess.run(
        ["make", "-C", "/app", "clean", "all"],
        capture_output=True, text=True, timeout=60,
    )


# ---- Valgrind ----

def test_valgrind_no_memory_errors():
    """No invalid reads/writes under Valgrind."""
    # Ensure normal build
    subprocess.run(
        ["make", "-C", "/app", "clean", "all"],
        capture_output=True, text=True, timeout=60,
    )

    # Run a non-trivial expression that exercises heap allocation (cons cells,
    # strings) and multiple value types
    expr = (
        '(begin '
        '  (let ((xs (list 1 2 3 4 5))) '
        '    (let ((s (string-append "hello" " " "world"))) '
        '      (+ (car xs) (length xs) (length s)))) '
        ')'
    )
    r = subprocess.run(
        ["valgrind", "--error-exitcode=42", "--leak-check=no",
         "--errors-for-leak-kinds=none",
         BINARY, "--eval", expr],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode != 42, (
        f"Valgrind detected memory errors:\n{r.stderr}"
    )
    assert r.returncode == 0, (
        f"Unexpected exit code {r.returncode} under Valgrind:\n{r.stderr}"
    )


# ---- pahole struct layout report ----

def test_pahole_report_exists():
    """size_report.txt must exist with struct layout info from pahole."""
    assert os.path.exists("/app/size_report.txt"), (
        "/app/size_report.txt not found — must be generated using pahole"
    )
    with open("/app/size_report.txt") as f:
        content = f.read()
    assert len(content) > 50, (
        "size_report.txt appears too short to contain meaningful pahole output"
    )
    # The report should contain struct analysis (at minimum Cons, Env, Reader
    # are still structs in the modified binary)
    assert "struct" in content.lower() or "Cons" in content or "size:" in content, (
        "size_report.txt does not appear to contain pahole struct layout data"
    )
