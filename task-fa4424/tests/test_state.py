"""Tests for the Lox-to-JavaScript transpiler at /app/lox2js.py.

Each test runs a Lox program through both:
  1. The reference interpreter: python3 /app/lox.py <script>
  2. The transpiler pipeline:  python3 /app/lox2js.py <script> > out.js && node out.js
Then compares stdout, stderr, and exit code.
"""
import subprocess
import os
import tempfile
import pytest


def _run_reference(lox_path, timeout=10):
    """Run Lox code through the reference interpreter."""
    try:
        return subprocess.run(
            ['python3', '/app/lox.py', lox_path],
            capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args=[], returncode=-1, stdout='', stderr='TIMEOUT')


def _run_transpiled(lox_path, timeout=10):
    """Transpile Lox to JS then run with node."""
    try:
        trans = subprocess.run(
            ['python3', '/app/lox2js.py', lox_path],
            capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args=[], returncode=-1, stdout='', stderr='TIMEOUT')

    if trans.returncode != 0:
        # Transpilation error (parse/resolve) — return as-is
        return trans

    js_fd, js_path = tempfile.mkstemp(suffix='.js')
    try:
        with os.fdopen(js_fd, 'w') as jf:
            jf.write(trans.stdout)
        try:
            return subprocess.run(
                ['node', js_path],
                capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args=[], returncode=-1, stdout='', stderr='TIMEOUT')
    finally:
        os.unlink(js_path)


def assert_match(code, timeout=10):
    """Run through both pipelines and assert identical behavior."""
    fd, lox_path = tempfile.mkstemp(suffix='.lox')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(code)
        ref = _run_reference(lox_path, timeout)
        actual = _run_transpiled(lox_path, timeout)
    finally:
        os.unlink(lox_path)

    assert ref.returncode == actual.returncode, (
        f"Exit code mismatch: ref={ref.returncode} actual={actual.returncode}\n"
        f"Ref stdout: {ref.stdout!r}\nActual stdout: {actual.stdout!r}\n"
        f"Ref stderr: {ref.stderr!r}\nActual stderr: {actual.stderr!r}"
    )
    assert ref.stdout == actual.stdout, (
        f"Stdout mismatch:\nRef:    {ref.stdout!r}\nActual: {actual.stdout!r}"
    )
    if ref.returncode != 0:
        assert ref.stderr.strip() == actual.stderr.strip(), (
            f"Stderr mismatch:\nRef:    {ref.stderr!r}\nActual: {actual.stderr!r}"
        )


# ========== Arithmetic & Operators ==========

def test_basic_arithmetic():
    assert_match('print 1 + 2 * 3;\nprint 10 - 4 / 2;')


def test_string_concatenation():
    assert_match('print "hello" + " " + "world";')


def test_comparison_operators():
    assert_match('print 1 < 2;\nprint 2 > 1;\nprint 1 <= 1;\nprint 2 <= 1;\nprint 5 >= 3;\nprint 3 >= 3;\nprint 2 >= 3;')


def test_precedence_chain():
    assert_match('print 2 + 3 * 4;\nprint (2 + 3) * 4;\nprint !false == true;\nprint -3 + 5;\nprint 1 == 2 < 3;')


def test_number_formatting():
    assert_match('print 3;\nprint 3.14;\nprint 0;\nprint -1;')


# ========== Variables & Scoping ==========

def test_variables():
    assert_match('var a = 1;\nvar b = 2;\nprint a + b;')


def test_block_scoping():
    assert_match('var a = "global";\n{\n  var a = "block";\n  print a;\n}\nprint a;')


def test_variable_assignment():
    assert_match('var a = 1;\nprint a;\na = 2;\nprint a;')


# ========== Control Flow ==========

def test_if_else():
    assert_match('if (true) print "yes"; else print "no";\nif (false) print "yes"; else print "no";')


def test_while_loop():
    assert_match('var i = 0;\nwhile (i < 3) {\n  print i;\n  i = i + 1;\n}')


def test_for_loop():
    assert_match('for (var i = 0; i < 5; i = i + 1) {\n  print i;\n}')


def test_for_loop_sum():
    assert_match('var sum = 0;\nfor (var i = 1; i <= 5; i = i + 1) {\n  sum = sum + i;\n}\nprint sum;')


# ========== Functions & Closures ==========

def test_functions():
    assert_match('fun add(a, b) { return a + b; }\nprint add(1, 2);')


def test_closures():
    assert_match('''\
fun makeCounter() {
  var i = 0;
  fun count() {
    i = i + 1;
    print i;
  }
  return count;
}
var counter = makeCounter();
counter();
counter();
counter();
''')


def test_recursive_fibonacci():
    assert_match('''\
fun fib(n) {
  if (n <= 1) return n;
  return fib(n - 2) + fib(n - 1);
}
print fib(10);
''')


def test_higher_order_functions():
    assert_match('''\
fun apply(f, x) { return f(x); }
fun double(x) { return x * 2; }
print apply(double, 21);
''')


def test_nested_closures():
    assert_match('''\
fun outer() {
  var x = "outside";
  fun inner() { print x; }
  inner();
}
outer();
''')


# ========== Truthiness & Equality ==========

def test_truthiness():
    assert_match('print !nil;\nprint !false;\nprint !true;\nprint !0;\nprint !"";\nprint !1;')


def test_equality_and_nil():
    assert_match('''\
print nil == nil;
print nil == false;
print nil == 0;
print nil != nil;
print 1 == 1;
print 1 == "1";
print true == true;
print false == false;
''')


def test_logical_operators():
    assert_match('''\
print "hi" or 2;
print nil or "yes";
print false and 1;
print "yes" and 2;
''')


# ========== Classes ==========

def test_classes_and_methods():
    assert_match('''\
class Greeter {
  greet(name) {
    print "Hello, " + name + "!";
  }
}
Greeter().greet("World");
''')


def test_this_keyword():
    assert_match('''\
class Cake {
  init() {
    this.flavor = "chocolate";
  }
  taste() {
    print "The " + this.flavor + " cake is delicious!";
  }
}
Cake().taste();
''')


def test_inheritance():
    assert_match('''\
class Animal {
  speak() { print "..."; }
}
class Dog < Animal {
  speak() { print "Woof!"; }
}
class Cat < Animal {}
Dog().speak();
Cat().speak();
''')


def test_super_method():
    assert_match('''\
class A {
  method() { print "A"; }
}
class B < A {
  method() { print "B"; }
  test() { super.method(); }
}
B().test();
''')


def test_super_constructor():
    assert_match('''\
class Base {
  init() { this.x = 10; }
  describe() { print this.x; }
}
class Derived < Base {
  init() {
    super.init();
    this.y = 20;
  }
  describe() {
    super.describe();
    print this.y;
  }
}
Derived().describe();
''')


def test_this_in_nested_function():
    assert_match('''\
class Foo {
  init() { this.val = 99; }
  method() {
    fun helper() {
      print this.val;
    }
    helper();
  }
}
Foo().method();
''')


# ========== Error Cases ==========

def test_runtime_error_type_mismatch():
    assert_match('print 1 + "two";')


def test_runtime_error_unary():
    assert_match('print -"hello";')


def test_top_level_return():
    assert_match('return 1;')


def test_self_referencing_initializer():
    assert_match('{\n  var a = a;\n}')


def test_return_value_from_init():
    assert_match('class Foo {\n  init() { return 42; }\n}')


# ========== Native Functions ==========

def test_clock_native():
    assert_match('var t = clock();\nprint t > 0;')
