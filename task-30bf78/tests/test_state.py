
import subprocess
import tempfile
import os
import pytest


def run_interpreter(code):
    """Run Lox code through the reference interpreter."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".lox", delete=False, dir="/tmp") as f:
        f.write(code)
        fname = f.name
    try:
        result = subprocess.run(
            ["python3", "/app/run_lox.py", "run", fname],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout, result.stderr, result.returncode
    finally:
        os.unlink(fname)


def transpile_and_run(code):
    """Transpile Lox code to Python and execute the generated Python."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".lox", delete=False, dir="/tmp") as f:
        f.write(code)
        lox_fname = f.name
    try:
        t_result = subprocess.run(
            ["python3", "/app/transpile.py", lox_fname],
            capture_output=True, text=True, timeout=15,
        )
        if t_result.returncode != 0:
            pytest.fail(
                f"Transpiler failed (exit {t_result.returncode}): {t_result.stderr}"
            )
        py_code = t_result.stdout
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir="/tmp"
        ) as pyf:
            pyf.write(py_code)
            py_fname = pyf.name
        try:
            r_result = subprocess.run(
                ["python3", py_fname],
                capture_output=True, text=True, timeout=15,
            )
            return r_result.stdout, r_result.stderr, r_result.returncode
        finally:
            os.unlink(py_fname)
    finally:
        os.unlink(lox_fname)


def assert_transpile_matches(code, expected_lines):
    """Verify transpiled output matches expected lines AND reference interpreter."""
    ref_out, ref_err, ref_rc = run_interpreter(code)
    assert ref_rc == 0, f"Reference interpreter failed: {ref_err}"
    ref_lines = ref_out.strip().split("\n") if ref_out.strip() else []
    assert ref_lines == expected_lines, (
        f"Reference output {ref_lines} != expected {expected_lines}"
    )

    trans_out, trans_err, trans_rc = transpile_and_run(code)
    assert trans_rc == 0, f"Transpiled code failed (exit {trans_rc}): {trans_err}"
    trans_lines = trans_out.strip().split("\n") if trans_out.strip() else []
    assert trans_lines == expected_lines, (
        f"Transpiler output {trans_lines} != expected {expected_lines}"
    )


# ── Arithmetic ──


class TestArithmetic:
    def test_basic_ops(self):
        assert_transpile_matches(
            "print 1 + 2;\nprint 10 - 3;\nprint 2 * 4;\nprint 6 / 2;\n",
            ["3", "7", "8", "3"],
        )

    def test_negation(self):
        assert_transpile_matches("print -5;\nprint -(3 + 2);\n", ["-5", "-5"])

    def test_precedence(self):
        assert_transpile_matches(
            "print 2 + 3 * 4;\nprint (2 + 3) * 4;\n", ["14", "20"]
        )

    def test_float_formatting(self):
        assert_transpile_matches("print 1.5 + 2.5;\nprint 3.0;\n", ["4", "3"])


# ── Strings ──


class TestStrings:
    def test_concatenation(self):
        assert_transpile_matches(
            'print "hello" + " " + "world";\n', ["hello world"]
        )

    def test_string_literal(self):
        assert_transpile_matches('print "test string";\n', ["test string"])


# ── Comparisons ──


class TestComparison:
    def test_comparison_ops(self):
        assert_transpile_matches(
            "print 1 < 2;\nprint 3 >= 3;\nprint 5 > 5;\nprint 2 <= 1;\n",
            ["true", "true", "false", "false"],
        )

    def test_equality(self):
        assert_transpile_matches(
            "print 1 == 1;\nprint 1 != 2;\nprint nil == nil;\nprint 1 == true;\n",
            ["true", "true", "true", "false"],
        )

    def test_not_operator(self):
        assert_transpile_matches(
            "print !true;\nprint !false;\nprint !nil;\nprint !0;\n",
            ["false", "true", "true", "false"],
        )


# ── Variables and Scoping ──


class TestVariables:
    def test_var_declaration(self):
        assert_transpile_matches("var x = 10;\nprint x;\n", ["10"])

    def test_var_reassign(self):
        assert_transpile_matches("var x = 1;\nx = 2;\nprint x;\n", ["2"])

    def test_uninitialized_var(self):
        assert_transpile_matches("var x;\nprint x;\n", ["nil"])

    def test_block_scoping(self):
        code = """
var a = 1;
{
    var a = 10;
    print a;
}
print a;
"""
        assert_transpile_matches(code, ["10", "1"])

    def test_nested_block_scoping(self):
        code = """
var x = "outer";
{
    var x = "middle";
    {
        var x = "inner";
        print x;
    }
    print x;
}
print x;
"""
        assert_transpile_matches(code, ["inner", "middle", "outer"])

    def test_block_scope_assignment(self):
        code = """
var x = 1;
{
    x = 2;
    print x;
}
print x;
"""
        assert_transpile_matches(code, ["2", "2"])


# ── Control Flow ──


class TestControlFlow:
    def test_if_else(self):
        code = """
if (false) {
    print "yes";
} else {
    print "no";
}
"""
        assert_transpile_matches(code, ["no"])

    def test_while_loop(self):
        code = """
var i = 0;
while (i < 3) {
    print i;
    i = i + 1;
}
"""
        assert_transpile_matches(code, ["0", "1", "2"])

    def test_for_loop(self):
        code = "for (var i = 0; i < 5; i = i + 1) {\n    print i;\n}\n"
        assert_transpile_matches(code, ["0", "1", "2", "3", "4"])

    def test_for_loop_accumulator(self):
        code = "var sum = 0;\nfor (var i = 1; i <= 4; i = i + 1) {\n    sum = sum + i;\n}\nprint sum;\n"
        assert_transpile_matches(code, ["10"])


# ── Functions ──


class TestFunctions:
    def test_basic_function(self):
        code = """
fun add(a, b) {
    return a + b;
}
print add(3, 4);
"""
        assert_transpile_matches(code, ["7"])

    def test_function_no_return(self):
        code = """
fun greet(name) {
    print "hello " + name;
}
greet("world");
"""
        assert_transpile_matches(code, ["hello world"])

    def test_early_return(self):
        code = """
fun check(n) {
    if (n > 0) return "positive";
    return "non-positive";
}
print check(5);
print check(-1);
"""
        assert_transpile_matches(code, ["positive", "non-positive"])

    def test_recursion(self):
        code = """
fun fib(n) {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}
print fib(10);
"""
        assert_transpile_matches(code, ["55"])


# ── Closures ──


class TestClosures:
    def test_basic_closure(self):
        code = """
fun makeCounter() {
    var count = 0;
    fun increment() {
        count = count + 1;
        return count;
    }
    return increment;
}
var counter = makeCounter();
print counter();
print counter();
print counter();
"""
        assert_transpile_matches(code, ["1", "2", "3"])

    def test_closure_captures_correct_scope(self):
        code = """
var x = "global";
fun outer() {
    var x = "outer";
    fun inner() {
        print x;
    }
    inner();
}
outer();
"""
        assert_transpile_matches(code, ["outer"])

    def test_closure_in_loop(self):
        code = """
fun makePair(a) {
    fun getA() { return a; }
    return getA;
}
var f1 = makePair("first");
var f2 = makePair("second");
print f1();
print f2();
"""
        assert_transpile_matches(code, ["first", "second"])


# ── Classes ──


class TestClasses:
    def test_simple_class(self):
        code = """
class Greeter {
    greet(name) {
        return "Hello, " + name + "!";
    }
}
var g = Greeter();
print g.greet("Alice");
"""
        assert_transpile_matches(code, ["Hello, Alice!"])

    def test_class_fields(self):
        code = """
class Point {
    init(x, y) {
        this.x = x;
        this.y = y;
    }
}
var p = Point(3, 4);
print p.x;
print p.y;
"""
        assert_transpile_matches(code, ["3", "4"])

    def test_init_returns_instance(self):
        code = """
class Foo {
    init() {
        this.value = 42;
        return;
    }
}
var foo = Foo();
var result = foo.init();
print result;
"""
        assert_transpile_matches(code, ["Foo instance"])

    def test_method_with_fields(self):
        code = """
class Rect {
    init(w, h) {
        this.w = w;
        this.h = h;
    }
    area() { return this.w * this.h; }
    perimeter() { return 2 * (this.w + this.h); }
}
var r = Rect(3, 4);
print r.area();
print r.perimeter();
"""
        assert_transpile_matches(code, ["12", "14"])


# ── Inheritance ──


class TestInheritance:
    def test_method_override(self):
        code = """
class Animal {
    speak() { return "..."; }
}
class Dog < Animal {
    speak() { return "woof"; }
}
print Dog().speak();
"""
        assert_transpile_matches(code, ["woof"])

    def test_inherited_method(self):
        code = """
class Base {
    greet() { return "hello"; }
}
class Child < Base {}
print Child().greet();
"""
        assert_transpile_matches(code, ["hello"])

    def test_super_call(self):
        code = """
class Base {
    identify() { return "base"; }
}
class Derived < Base {
    identify() {
        return "derived(" + super.identify() + ")";
    }
}
print Derived().identify();
"""
        assert_transpile_matches(code, ["derived(base)"])

    def test_super_with_fields(self):
        code = """
class Shape {
    area() { return 0; }
}
class Square < Shape {
    init(side) { this.side = side; }
    area() { return this.side * this.side; }
    parentArea() { return super.area(); }
}
print Square(5).area();
print Square(5).parentArea();
"""
        assert_transpile_matches(code, ["25", "0"])

    def test_variable_after_subclass(self):
        code = """
class Animal {}
class Dog < Animal {
    speak() { return "woof"; }
}
var greeting = "hello";
print greeting;
"""
        assert_transpile_matches(code, ["hello"])


# ── Logical Operators ──


class TestLogical:
    def test_or_values(self):
        code = """
print "hi" or "world";
print nil or "fallback";
print false or true;
"""
        assert_transpile_matches(code, ["hi", "fallback", "true"])

    def test_and_values(self):
        code = """
print 1 and 2;
print true and "hello";
print false and "hello";
"""
        assert_transpile_matches(code, ["2", "hello", "false"])

    def test_and_short_circuit(self):
        code = """
var x = "unchanged";
fun sideEffect() {
    x = "changed";
    return true;
}
var result = nil and sideEffect();
print result;
print x;
"""
        assert_transpile_matches(code, ["nil", "unchanged"])

    def test_or_short_circuit(self):
        code = """
var x = "unchanged";
fun sideEffect() {
    x = "changed";
    return true;
}
var result = "truthy" or sideEffect();
print result;
print x;
"""
        assert_transpile_matches(code, ["truthy", "unchanged"])


# ── Complex Multi-Feature Interactions ──


class TestComplex:
    def test_class_with_closure(self):
        code = """
class Counter {
    init(start) {
        this.count = start;
    }
    makeIncrementer(step) {
        var self_ref = this;
        fun inc() {
            self_ref.count = self_ref.count + step;
            return self_ref.count;
        }
        return inc;
    }
}
var c = Counter(0);
var inc = c.makeIncrementer(3);
print inc();
print inc();
print c.count;
"""
        assert_transpile_matches(code, ["3", "6", "6"])

    def test_multi_level_inheritance(self):
        code = """
class A {
    name() { return "A"; }
}
class B < A {
    name() { return "B>" + super.name(); }
}
class C < B {
    name() { return "C>" + super.name(); }
}
print C().name();
"""
        assert_transpile_matches(code, ["C>B>A"])

    def test_fibonacci_with_class(self):
        code = """
class Fib {
    init() {
        this.a = 0;
        this.b = 1;
    }
    next() {
        var result = this.a;
        var temp = this.a + this.b;
        this.a = this.b;
        this.b = temp;
        return result;
    }
}
var f = Fib();
for (var i = 0; i < 8; i = i + 1) {
    print f.next();
}
"""
        assert_transpile_matches(code, ["0", "1", "1", "2", "3", "5", "8", "13"])

    def test_truthiness_edge_cases(self):
        code = """
print !nil;
print !false;
print !true;
print !0;
print !"";
print !1;
"""
        assert_transpile_matches(code, ["true", "true", "false", "false", "false", "false"])

    def test_init_early_return(self):
        code = """
class Config {
    init(flag) {
        this.flag = flag;
        if (flag) return;
        this.extra = "set";
    }
}
var c = Config(false);
print c.flag;
print c.extra;
var again = c.init(true);
print again;
"""
        assert_transpile_matches(code, ["false", "set", "Config instance"])
