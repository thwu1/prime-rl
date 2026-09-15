
"""Tests for SysY→LLVM IR codegen: generate IR, compile with clang, verify output."""

import os
import subprocess
import tempfile
import pytest

CODEGEN = '/app/codegen.py'
RUNTIME = '/app/lib/sysy_runtime.c'


def compile_and_run(source, stdin_data='', timeout=30):
    """Generate LLVM IR from SysY source, compile with clang, execute, return output."""
    with tempfile.TemporaryDirectory(dir='/tmp') as td:
        sy = os.path.join(td, 'prog.sy')
        ll = os.path.join(td, 'prog.ll')
        exe = os.path.join(td, 'prog')

        with open(sy, 'w') as f:
            f.write(source)

        # Step 1: Generate LLVM IR
        rc = subprocess.run(
            ['python3', CODEGEN, sy, '-o', ll],
            capture_output=True, text=True, timeout=timeout,
        )
        assert rc.returncode == 0, \
            f"Codegen failed (exit {rc.returncode}):\n{rc.stderr}\n{rc.stdout}"
        assert os.path.exists(ll), "Codegen produced no output file"

        # Step 2: Validate IR with llvm-as
        rc_as = subprocess.run(
            ['llvm-as', ll, '-o', '/dev/null'],
            capture_output=True, text=True, timeout=timeout,
        )
        assert rc_as.returncode == 0, \
            f"LLVM IR validation failed (llvm-as):\n{rc_as.stderr}"

        # Step 3: Compile with clang + runtime
        rc_cc = subprocess.run(
            ['clang', ll, RUNTIME, '-o', exe, '-lm'],
            capture_output=True, text=True, timeout=timeout,
        )
        assert rc_cc.returncode == 0, \
            f"clang compilation failed:\n{rc_cc.stderr}"

        # Step 4: Execute
        rv = subprocess.run(
            [exe],
            input=stdin_data,
            capture_output=True, text=True, timeout=timeout,
        )
        return rv.stdout, rv.returncode


# ---------------------------------------------------------------------------
# Public tests: programs from /app/programs/
# ---------------------------------------------------------------------------

PUBLIC_TESTS = [
    ('01_basic_return',    '', '',                       42),
    ('02_arithmetic',      '', '11 14 3 1\n',            0),
    ('03_if_else',         '', '1 0 1\n',                0),
    ('04_while_loop',      '', '45\n',                   0),
    ('05_fibonacci',       '', '55\n',                   0),
    ('06_arrays_1d',       '', '150\n',                  0),
    ('07_void_func',       '', '7\n30\n',                0),
    ('08_neg_division',    '', '-3 -3 -3 -3\n',          0),
    ('09_neg_modulo',      '', '-1 1 -3 -1\n',           0),
    ('10_short_circuit',   '', '0\n0\n1\n2\n',           0),
    ('11_array_modify',    '', '30\n',                   0),
    ('12_scoping_blocks',  '', '20 30 20 10 200\n',      0),
    ('13_break_continue',  '', '37\n',                   0),
    ('14_multi_dim_array', '', '1 3 5\n',                0),
    ('15_const_decl',      '', '15 60\n',                0),
    ('16_complex_init',    '', '1 3 4 6\n',              0),
    ('17_nested_calls',    '', '120\n',                  0),
    ('18_global_array',    '', '0 1 4 9 16\n',           0),
]


@pytest.mark.parametrize('dirname,stdin_data,exp_out,exp_exit', PUBLIC_TESTS,
                         ids=[t[0] for t in PUBLIC_TESTS])
def test_public(dirname, stdin_data, exp_out, exp_exit):
    prog_path = f'/app/programs/{dirname}/program.sy'
    assert os.path.exists(prog_path), f"Missing: {prog_path}"
    with open(prog_path) as f:
        source = f.read()
    stdout, exitcode = compile_and_run(source, stdin_data)
    assert stdout == exp_out, \
        f"[{dirname}] stdout mismatch:\n  got:      {stdout!r}\n  expected: {exp_out!r}"
    assert exitcode == exp_exit, \
        f"[{dirname}] exit mismatch: got {exitcode}, expected {exp_exit}"


# ---------------------------------------------------------------------------
# Hidden tests: programs embedded here for defense-in-depth
# ---------------------------------------------------------------------------

HIDDEN_TESTS = [
    {
        'id': 'h01_nested_break',
        'source': r'''int main() {
    int total = 0;
    int i = 0;
    while (i < 5) {
        int j = 0;
        while (j < 5) {
            if (j == 3) break;
            total = total + 1;
            j = j + 1;
        }
        i = i + 1;
    }
    putint(total); putch(10);
    return 0;
}
''',
        'stdin': '',
        'exp_out': '15\n',
        'exp_exit': 0,
    },
    {
        'id': 'h02_2d_array_pass',
        'source': r'''void sum_row(int row[], int n, int out[], int idx) {
    int s = 0;
    int i = 0;
    while (i < n) {
        s = s + row[i];
        i = i + 1;
    }
    out[idx] = s;
}

int main() {
    int a[3][4] = {{1,2,3,4},{5,6,7,8},{9,10,11,12}};
    int sums[3] = {0, 0, 0};
    sum_row(a[0], 4, sums, 0);
    sum_row(a[1], 4, sums, 1);
    sum_row(a[2], 4, sums, 2);
    putint(sums[0]); putch(32);
    putint(sums[1]); putch(32);
    putint(sums[2]); putch(10);
    return 0;
}
''',
        'stdin': '',
        'exp_out': '10 26 42\n',
        'exp_exit': 0,
    },
    {
        'id': 'h03_short_circuit_chain',
        'source': r'''int g = 0;
int bump() { g = g + 10; return 1; }

int main() {
    if (0 && bump() && bump()) {}
    putint(g); putch(10);
    if (1 || bump()) {}
    putint(g); putch(10);
    if (1 && 1 && bump()) {}
    putint(g); putch(10);
    return 0;
}
''',
        'stdin': '',
        'exp_out': '0\n0\n10\n',
        'exp_exit': 0,
    },
    {
        'id': 'h04_unary_chain',
        'source': r'''int main() {
    int a = -(-5);
    int b = !0;
    int c = !!1;
    int d = !!!0;
    int e = -(3 + 4);
    putint(a); putch(32);
    putint(b); putch(32);
    putint(c); putch(32);
    putint(d); putch(32);
    putint(e); putch(10);
    return 0;
}
''',
        'stdin': '',
        'exp_out': '5 1 1 1 -7\n',
        'exp_exit': 0,
    },
    {
        'id': 'h05_scope_shadow_deep',
        'source': r'''int main() {
    int a = 1;
    {
        int a = 2;
        {
            int a = 3;
            {
                int a = 4;
                putint(a); putch(32);
            }
            putint(a); putch(32);
        }
        putint(a); putch(32);
    }
    putint(a); putch(10);
    return 0;
}
''',
        'stdin': '',
        'exp_out': '4 3 2 1\n',
        'exp_exit': 0,
    },
    {
        'id': 'h06_div_mod_identity',
        'source': r'''int main() {
    int a = -17;
    int b = 5;
    int q = a / b;
    int r = a % b;
    int check = q * b + r;
    putint(q); putch(32);
    putint(r); putch(32);
    putint(check); putch(10);
    return 0;
}
''',
        'stdin': '',
        'exp_out': '-3 -2 -17\n',
        'exp_exit': 0,
    },
    {
        'id': 'h07_gcd_const_array',
        'source': r'''const int N = 4;

int gcd(int a, int b) {
    while (b != 0) {
        int t = b;
        b = a % b;
        a = t;
    }
    return a;
}

int main() {
    int vals[4] = {12, 18, 24, 36};
    int result = vals[0];
    int i = 1;
    while (i < N) {
        result = gcd(result, vals[i]);
        i = i + 1;
    }
    putint(result); putch(10);
    return 0;
}
''',
        'stdin': '',
        'exp_out': '6\n',
        'exp_exit': 0,
    },
    {
        'id': 'h08_partial_brace_init',
        'source': r'''int main() {
    int a[4][2] = {1, 2, {3}, {5}, 7, 8};
    putint(a[0][0]); putch(32);
    putint(a[0][1]); putch(32);
    putint(a[1][0]); putch(32);
    putint(a[1][1]); putch(32);
    putint(a[2][0]); putch(32);
    putint(a[2][1]); putch(32);
    putint(a[3][0]); putch(32);
    putint(a[3][1]); putch(10);
    return 0;
}
''',
        'stdin': '',
        'exp_out': '1 2 3 0 5 0 7 8\n',
        'exp_exit': 0,
    },
]


@pytest.mark.parametrize('tc', HIDDEN_TESTS, ids=[t['id'] for t in HIDDEN_TESTS])
def test_hidden(tc):
    stdout, exitcode = compile_and_run(tc['source'], tc.get('stdin', ''))
    assert stdout == tc['exp_out'], \
        f"[{tc['id']}] stdout mismatch:\n  got:      {stdout!r}\n  expected: {tc['exp_out']!r}"
    assert exitcode == tc['exp_exit'], \
        f"[{tc['id']}] exit mismatch: got {exitcode}, expected {tc['exp_exit']}"
