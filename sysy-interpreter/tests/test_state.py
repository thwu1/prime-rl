
import subprocess
import os
import pytest

COMPILER = "/app/sysy_compiler"
RUNTIME_C = "/app/runtime/sylib.c"
RUNTIME_SO = "/app/runtime/sylib.so"

# ---------------------------------------------------------------------------
# Test programs with expected output and return code
# ---------------------------------------------------------------------------
TESTS = [
    {
        "name": "basic_return",
        "code": "int main() { return 42; }",
        "input": "",
        "expected_output": "",
        "expected_return": 42,
    },
    {
        "name": "arithmetic",
        "code": """\
int main() {
    int a = 3 + 4 * 2;
    int b = (3 + 4) * 2;
    int c = 10 / 3;
    int d = 10 % 3;
    int e = 7 - 3 - 2;
    putint(a); putch(10);
    putint(b); putch(10);
    putint(c); putch(10);
    putint(d); putch(10);
    putint(e); putch(10);
    return 0;
}
""",
        "input": "",
        "expected_output": "11\n14\n3\n1\n2\n",
        "expected_return": 0,
    },
    {
        "name": "if_else",
        "code": """\
int main() {
    int a = 5;
    if (a > 3) { putint(1); } else { putint(0); }
    putch(10);
    if (a > 10) { putint(1); } else { putint(0); }
    putch(10);
    if (a == 5) {
        if (a < 10) {
            putint(99);
        }
    }
    putch(10);
    return 0;
}
""",
        "input": "",
        "expected_output": "1\n0\n99\n",
        "expected_return": 0,
    },
    {
        "name": "while_break_continue",
        "code": """\
int main() {
    int i = 0;
    int sum = 0;
    while (i < 10) {
        i = i + 1;
        if (i == 5) continue;
        if (i == 8) break;
        sum = sum + i;
    }
    putint(sum); putch(10);
    return 0;
}
""",
        "input": "",
        "expected_output": "23\n",
        "expected_return": 0,
    },
    {
        "name": "fibonacci",
        "code": """\
int fibonacci(int n) {
    if (n <= 1) return n;
    return fibonacci(n - 1) + fibonacci(n - 2);
}
int main() {
    int i = 0;
    while (i < 10) {
        putint(fibonacci(i));
        putch(32);
        i = i + 1;
    }
    putch(10);
    return 0;
}
""",
        "input": "",
        "expected_output": "0 1 1 2 3 5 8 13 21 34 \n",
        "expected_return": 0,
    },
    {
        "name": "array_init_braces",
        "code": """\
int main() {
    int a[3][2] = {{1, 2}, {3, 4}, {5, 6}};
    int c[3][2] = {{1}, {3, 4}, {5}};
    int i = 0;
    while (i < 3) {
        int j = 0;
        while (j < 2) {
            putint(a[i][j]); putch(32);
            j = j + 1;
        }
        i = i + 1;
    }
    putch(10);
    i = 0;
    while (i < 3) {
        int j = 0;
        while (j < 2) {
            putint(c[i][j]); putch(32);
            j = j + 1;
        }
        i = i + 1;
    }
    putch(10);
    return 0;
}
""",
        "input": "",
        "expected_output": "1 2 3 4 5 6 \n1 0 3 4 5 0 \n",
        "expected_return": 0,
    },
    {
        "name": "scoping",
        "code": """\
int a = 1;
int main() {
    putint(a); putch(10);
    int a = 2;
    putint(a); putch(10);
    {
        int a = 3;
        putint(a); putch(10);
    }
    putint(a); putch(10);
    {
        a = 99;
    }
    putint(a); putch(10);
    return 0;
}
""",
        "input": "",
        "expected_output": "1\n2\n3\n2\n99\n",
        "expected_return": 0,
    },
    {
        "name": "short_circuit",
        "code": """\
int counter = 0;
int inc() {
    counter = counter + 1;
    return counter;
}
int main() {
    int x = 0 && inc();
    putint(counter); putch(10);
    int y = 1 || inc();
    putint(counter); putch(10);
    int z = 1 && inc();
    putint(counter); putch(10);
    int w = 0 || inc();
    putint(counter); putch(10);
    return 0;
}
""",
        "input": "",
        "expected_output": "0\n0\n1\n2\n",
        "expected_return": 0,
    },
    {
        "name": "array_param",
        "code": """\
void fill(int arr[], int n) {
    int i = 0;
    while (i < n) {
        arr[i] = i * i;
        i = i + 1;
    }
}
int sum(int arr[], int n) {
    int s = 0;
    int i = 0;
    while (i < n) {
        s = s + arr[i];
        i = i + 1;
    }
    return s;
}
int main() {
    int a[5];
    fill(a, 5);
    putint(sum(a, 5)); putch(10);
    return 0;
}
""",
        "input": "",
        "expected_output": "30\n",
        "expected_return": 0,
    },
    {
        "name": "literals_and_unary",
        "code": """\
int main() {
    const int a = 10;
    const int b = 0xa;
    const int c = 012;
    putint(a + b + c); putch(10);
    int d = 5;
    putint(-d); putch(32);
    putint(+d); putch(32);
    putint(!d); putch(32);
    putint(!0); putch(10);
    return 0;
}
""",
        "input": "",
        "expected_output": "30\n-5 5 0 1\n",
        "expected_return": 0,
    },
    {
        "name": "gcd",
        "code": """\
int gcd(int a, int b) {
    if (b == 0) return a;
    return gcd(b, a % b);
}
int main() {
    putint(gcd(12, 8)); putch(10);
    putint(gcd(100, 75)); putch(10);
    putint(gcd(17, 13)); putch(10);
    return 0;
}
""",
        "input": "",
        "expected_output": "4\n25\n1\n",
        "expected_return": 0,
    },
    {
        "name": "const_array_brace_elision",
        "code": """\
int main() {
    const int a[4][2] = {1, 2, {3}, {5}, 7, 8};
    int i = 0;
    while (i < 4) {
        int j = 0;
        while (j < 2) {
            putint(a[i][j]); putch(32);
            j = j + 1;
        }
        i = i + 1;
    }
    putch(10);
    return 0;
}
""",
        "input": "",
        "expected_output": "1 2 3 0 5 0 7 8 \n",
        "expected_return": 0,
    },
    {
        "name": "global_array_putarray",
        "code": """\
int arr[10];
void init() {
    int i = 0;
    while (i < 10) {
        arr[i] = (i + 1) * (i + 1);
        i = i + 1;
    }
}
int main() {
    init();
    putarray(10, arr);
    return 0;
}
""",
        "input": "",
        "expected_output": "10: 1 4 9 16 25 36 49 64 81 100\n",
        "expected_return": 0,
    },
    {
        "name": "bubble_sort",
        "code": """\
void swap(int a[], int i, int j) {
    int t = a[i];
    a[i] = a[j];
    a[j] = t;
}
void bubble_sort(int a[], int n) {
    int i = 0;
    while (i < n - 1) {
        int j = 0;
        while (j < n - 1 - i) {
            if (a[j] > a[j + 1]) {
                swap(a, j, j + 1);
            }
            j = j + 1;
        }
        i = i + 1;
    }
}
int main() {
    int arr[8] = {64, 34, 25, 12, 22, 11, 90, 1};
    bubble_sort(arr, 8);
    putarray(8, arr);
    return 0;
}
""",
        "input": "",
        "expected_output": "8: 1 11 12 22 25 34 64 90\n",
        "expected_return": 0,
    },
    {
        "name": "input_sum",
        "code": """\
int main() {
    int n = getint();
    int sum = 0;
    int i = 0;
    while (i < n) {
        sum = sum + getint();
        i = i + 1;
    }
    putint(sum); putch(10);
    return 0;
}
""",
        "input": "3\n10 20 30\n",
        "expected_output": "60\n",
        "expected_return": 0,
    },
]


def _compile_to_ll(sy_code, tmp_path):
    """Run the SysY compiler and return the .ll file path and content."""
    sy_file = tmp_path / "test.sy"
    ll_file = tmp_path / "test.ll"
    sy_file.write_text(sy_code)

    result = subprocess.run(
        [COMPILER, str(sy_file)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"Compiler failed (exit {result.returncode}):\n{result.stderr}"
    )

    ll_file.write_text(result.stdout)
    return str(ll_file), result.stdout


def _link_and_run(ll_path, stdin_data="", tmp_path=None):
    """Link .ll with runtime via clang, then run the executable."""
    exe_path = str(tmp_path / "test_exe")

    link = subprocess.run(
        ["clang", "-o", exe_path, ll_path, RUNTIME_C, "-Wno-override-module"],
        capture_output=True, text=True, timeout=30,
    )
    assert link.returncode == 0, f"clang linking failed:\n{link.stderr}"

    run = subprocess.run(
        [exe_path],
        input=stdin_data,
        capture_output=True, text=True, timeout=30,
    )
    return run.stdout, run.returncode


# ===== Functional correctness tests =====

@pytest.mark.parametrize("test", TESTS, ids=lambda t: t["name"])
def test_sysy_programs(test, tmp_path):
    """Compile SysY → LLVM IR → executable, verify output and return code."""
    assert os.path.isfile(COMPILER), f"Compiler not found at {COMPILER}"

    ll_path, _ = _compile_to_ll(test["code"], tmp_path)
    stdout, retcode = _link_and_run(ll_path, test.get("input", ""), tmp_path)

    assert stdout == test["expected_output"], (
        f"Output mismatch for '{test['name']}':\n"
        f"  Expected: {repr(test['expected_output'])}\n"
        f"  Got:      {repr(stdout)}"
    )
    assert retcode == test["expected_return"], (
        f"Return code mismatch for '{test['name']}':\n"
        f"  Expected: {test['expected_return']}\n"
        f"  Got:      {retcode}"
    )


# ===== LLVM tool interoperability tests =====

_TOOL_TEST_CODE = """\
int fact(int n) {
    if (n <= 1) return 1;
    return n * fact(n - 1);
}
int main() {
    putint(fact(6)); putch(10);
    return 0;
}
"""


def test_opt_verify(tmp_path):
    """Generated IR must pass LLVM's verification pass."""
    ll_path, _ = _compile_to_ll(_TOOL_TEST_CODE, tmp_path)
    result = subprocess.run(
        ["opt", "-S", "-passes=verify", ll_path, "-o", "/dev/null"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"opt -passes=verify failed:\n{result.stderr}"
    )


def test_llvm_as(tmp_path):
    """Generated IR must be assemblable by llvm-as into bitcode."""
    ll_path, _ = _compile_to_ll(_TOOL_TEST_CODE, tmp_path)
    bc_path = str(tmp_path / "test.bc")
    result = subprocess.run(
        ["llvm-as", ll_path, "-o", bc_path],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"llvm-as failed:\n{result.stderr}"
    )
    assert os.path.isfile(bc_path), "Bitcode file was not created"


def test_lli_execution(tmp_path):
    """Generated IR must execute correctly under lli JIT with runtime."""
    ll_path, _ = _compile_to_ll(_TOOL_TEST_CODE, tmp_path)
    result = subprocess.run(
        ["lli", "--load=" + RUNTIME_SO, ll_path],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"lli execution failed (exit {result.returncode}):\n{result.stderr}"
    )
    assert result.stdout.strip() == "720", (
        f"lli output mismatch: expected '720', got {repr(result.stdout.strip())}"
    )


def test_opt_mem2reg(tmp_path):
    """Generated IR should survive opt -passes=mem2reg without breaking."""
    code = """\
int main() {
    int x = 10;
    int y = 20;
    int z = x + y;
    putint(z); putch(10);
    return 0;
}
"""
    ll_path, _ = _compile_to_ll(code, tmp_path)
    opt_ll = str(tmp_path / "opt.ll")
    result = subprocess.run(
        ["opt", "-S", "-passes=mem2reg", ll_path, "-o", opt_ll],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"opt mem2reg failed:\n{result.stderr}"

    # Link and run the optimized IR to check it still works
    stdout, retcode = _link_and_run(opt_ll, "", tmp_path)
    assert stdout == "30\n", f"Optimized IR output mismatch: {repr(stdout)}"
    assert retcode == 0


# ===== Additional feature tests =====

def test_subarray_param(tmp_path):
    """Test passing a sub-array (mat[i]) to a function expecting int arr[]."""
    code = """\
void print_row(int row[], int n) {
    int i = 0;
    while (i < n) {
        putint(row[i]); putch(32);
        i = i + 1;
    }
}
int main() {
    int mat[2][3] = {{1, 2, 3}, {4, 5, 6}};
    print_row(mat[0], 3);
    putch(10);
    print_row(mat[1], 3);
    putch(10);
    return 0;
}
"""
    ll_path, _ = _compile_to_ll(code, tmp_path)
    stdout, retcode = _link_and_run(ll_path, "", tmp_path)
    assert stdout == "1 2 3 \n4 5 6 \n", f"Got: {repr(stdout)}"
    assert retcode == 0


def test_empty_array_init(tmp_path):
    """Test that {} initializes all elements to zero."""
    code = """\
int main() {
    int a[2][3] = {};
    int i = 0;
    while (i < 2) {
        int j = 0;
        while (j < 3) {
            putint(a[i][j]); putch(32);
            j = j + 1;
        }
        i = i + 1;
    }
    putch(10);
    return 0;
}
"""
    ll_path, _ = _compile_to_ll(code, tmp_path)
    stdout, retcode = _link_and_run(ll_path, "", tmp_path)
    assert stdout == "0 0 0 0 0 0 \n", f"Got: {repr(stdout)}"
    assert retcode == 0


def test_void_function(tmp_path):
    """Test void function with early return."""
    code = """\
void print_positive(int x) {
    if (x <= 0) return;
    putint(x); putch(10);
}
int main() {
    print_positive(5);
    print_positive(-3);
    print_positive(10);
    return 0;
}
"""
    ll_path, _ = _compile_to_ll(code, tmp_path)
    stdout, retcode = _link_and_run(ll_path, "", tmp_path)
    assert stdout == "5\n10\n", f"Got: {repr(stdout)}"
    assert retcode == 0


def test_multi_var_decl(tmp_path):
    """Test multiple variable declarations in a single statement."""
    code = """\
int main() {
    int a = 1, b = 2, c = 3;
    putint(a + b + c); putch(10);
    return 0;
}
"""
    ll_path, _ = _compile_to_ll(code, tmp_path)
    stdout, retcode = _link_and_run(ll_path, "", tmp_path)
    assert stdout == "6\n", f"Got: {repr(stdout)}"
    assert retcode == 0


def test_nested_loops(tmp_path):
    """Test nested loops with break/continue targeting innermost loop."""
    code = """\
int main() {
    int count = 0;
    int i = 0;
    while (i < 5) {
        int j = 0;
        while (j < 5) {
            if (i == j) { j = j + 1; continue; }
            if (i + j > 6) break;
            count = count + 1;
            j = j + 1;
        }
        i = i + 1;
    }
    putint(count); putch(10);
    return 0;
}
"""
    ll_path, _ = _compile_to_ll(code, tmp_path)
    stdout, retcode = _link_and_run(ll_path, "", tmp_path)
    assert stdout == "18\n", f"Got: {repr(stdout)}"
    assert retcode == 0


def test_random_arithmetic(tmp_path):
    """Generate random arithmetic programs to prevent hardcoded outputs."""
    import random
    rng = random.Random(42)

    ops = ["+", "-", "*"]
    for trial in range(5):
        vals = [rng.randint(1, 50) for _ in range(4)]
        chosen_ops = [rng.choice(ops) for _ in range(3)]
        expr_parts = []
        for k in range(4):
            expr_parts.append(str(vals[k]))
            if k < 3:
                expr_parts.append(chosen_ops[k])
        expr_str = " ".join(expr_parts)
        expected_val = eval(expr_str)

        code = f"int main() {{ putint({expr_str}); putch(10); return 0; }}"
        ll_path, _ = _compile_to_ll(code, tmp_path)
        stdout, retcode = _link_and_run(ll_path, "", tmp_path)

        assert stdout.strip() == str(expected_val), (
            f"Random arithmetic trial {trial}: {expr_str}\n"
            f"  Expected: {expected_val}\n"
            f"  Got:      {stdout.strip()}"
        )
        assert retcode == 0
