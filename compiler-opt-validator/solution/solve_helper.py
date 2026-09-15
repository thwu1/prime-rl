#!/usr/bin/env python3
"""Generate C test programs for all 5 categories.

Produces self-checking C programs that exit 0 on pass, non-zero on failure.
Expected values are pre-computed in Python to ensure correctness.
"""
import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


# ============================================================
# irr_flow: Irreducible control flow with goto-based CFGs
# ============================================================

def gen_irr_flow(base_dir, start_idx, count):
    """Generate irreducible control flow tests."""
    for idx in range(start_idx, start_idx + count):
        # Vary parameters for each test
        seed_a = 3 + idx * 2
        seed_b = 7 + idx
        n_val = 6 + idx

        # Simulate the irreducible flow in Python to get expected value
        def simulate(n, sa, sb):
            r = 0
            i = 0
            at_A = True if (n % 2 == 0) else False
            if not at_A:
                # goto B
                r += i * sb
                i += 1
                if i >= n:
                    return r
                at_A = True
            while True:
                if at_A:
                    r += i * sa
                    i += 1
                    if i >= n:
                        return r
                    at_A = False
                else:
                    r += i * sb
                    i += 1
                    if i >= n:
                        return r
                    at_A = True

        expected = simulate(n_val, seed_a, seed_b)

        code = f"""#include <stdio.h>

int test_irr_{idx:02d}(int n) {{
    int r = 0, i = 0;
    int sa = {seed_a}, sb = {seed_b};

    if (n % 2 != 0)
        goto B;

A:
    r += i * sa;
    i++;
    if (i >= n) goto done;
    goto B;

B:
    r += i * sb;
    i++;
    if (i >= n) goto done;
    goto A;

done:
    return r;
}}

int main(void) {{
    int r = test_irr_{idx:02d}({n_val});
    if (r != {expected}) {{
        printf("FAIL: got %d expected {expected}\\n", r);
        return 1;
    }}
    return 0;
}}
"""
        write_file(os.path.join(base_dir, f'test_{idx:02d}.c'), code)


# ============================================================
# alias: Pointer aliasing tests
# ============================================================

def gen_alias(base_dir, start_idx, count):
    """Generate pointer aliasing tests."""
    for idx in range(start_idx, start_idx + count):
        offset = (idx % 3) + 1
        init_vals = [i + idx * 10 for i in range(8)]

        # Simulate aliased copy: dst[i] = src[i] for overlapping regions
        data = list(init_vals)
        for i in range(4):
            data[i] = data[i] + data[i + offset]

        init_str = ', '.join(str(v) for v in init_vals)
        checks = []
        for i in range(4):
            checks.append(f'    if (data[{i}] != {data[i]}) return {i+1};')
        checks_str = '\n'.join(checks)

        code = f"""#include <stdio.h>

void add_offset(int *dst, int *src, int n) {{
    for (int i = 0; i < n; i++)
        dst[i] = dst[i] + src[i];
}}

int main(void) {{
    int data[8] = {{{init_str}}};
    /* dst and src overlap by offset {offset} */
    add_offset(data, data + {offset}, 4);
{checks_str}
    return 0;
}}
"""
        write_file(os.path.join(base_dir, f'test_{idx:02d}.c'), code)


# ============================================================
# volatile_opt: Volatile semantics tests
# ============================================================

def gen_volatile(base_dir, start_idx, count):
    """Generate volatile semantics tests."""
    for idx in range(start_idx, start_idx + count):
        init_val = 100 + idx * 7
        incr = 3 + idx
        n_iters = 5 + (idx % 4)
        expected = init_val + incr * n_iters

        code = f"""#include <stdio.h>

int main(void) {{
    volatile int counter = {init_val};
    volatile int step = {incr};

    /* Optimizer must not eliminate volatile reads/writes */
    for (int i = 0; i < {n_iters}; i++) {{
        int s = step;   /* volatile read */
        counter += s;   /* volatile read + write */
    }}

    int result = counter;  /* volatile read */
    if (result != {expected}) {{
        printf("FAIL: got %d expected {expected}\\n", result);
        return 1;
    }}

    /* Verify volatile pointer semantics */
    volatile int flag = 0;
    int observed = 0;
    flag = 1;
    observed = flag;
    if (observed != 1) return 2;

    flag = 0;
    observed = flag;
    if (observed != 0) return 3;

    return 0;
}}
"""
        write_file(os.path.join(base_dir, f'test_{idx:02d}.c'), code)


# ============================================================
# int_promo: Integer promotion edge cases
# ============================================================

def gen_int_promo(base_dir, start_idx, count):
    """Generate integer promotion tests."""
    tests = []

    # Test: unsigned char promotion
    tests.append("""#include <stdio.h>

int main(void) {
    unsigned char a = 200;
    unsigned char b = 100;
    /* Both promoted to int before addition */
    int result = a + b;
    if (result != 300) return 1;

    /* Verify promotion in comparison */
    short s = -1;
    unsigned short us = 1;
    /* Both promoted to int: -1 < 1 is true */
    if (!(s < us)) return 2;

    return 0;
}
""")

    # Test: signed/unsigned comparison
    tests.append("""#include <stdio.h>
#include <limits.h>

int main(void) {
    /* Unsigned/signed comparison after promotion */
    unsigned int u = UINT_MAX;
    int s = -1;
    /* In C, s is converted to unsigned for comparison */
    /* (unsigned)-1 == UINT_MAX, so u == (unsigned)s */
    if (u != (unsigned int)s) return 1;

    /* Narrowing: result of int arithmetic assigned to char */
    char c = (char)(200 + 200);
    /* 400 truncated to char: 400 - 256 = 144, or platform dependent signed */
    /* Use unsigned char for well-defined behavior */
    unsigned char uc = (unsigned char)(200 + 200);
    if (uc != 144) return 2;

    return 0;
}
""")

    # Test: long/int mixed arithmetic
    tests.append("""#include <stdio.h>
#include <limits.h>

int main(void) {
    long la = (long)INT_MAX + 1L;
    int ib = 1;
    /* int promoted to long */
    long result = la + ib;
    if (result != (long)INT_MAX + 2L) return 1;

    /* unsigned long with signed int */
    unsigned long ul = 10UL;
    int neg = -3;
    /* neg converted to unsigned long */
    unsigned long sum = ul + (unsigned long)neg;
    if (sum != 10UL + (unsigned long)neg) return 2;

    return 0;
}
""")

    # Test: char arithmetic sign extension
    tests.append("""#include <stdio.h>

int main(void) {
    signed char sc = -128;
    unsigned char uc = 128;
    /* Both promoted to int */
    int sum = sc + uc;
    /* -128 + 128 = 0 */
    if (sum != 0) return 1;

    /* Widening from short to long */
    short s = -1;
    long l = s;  /* sign-extended */
    if (l != -1L) return 2;

    unsigned short us2 = 65535;
    long l2 = us2;  /* zero-extended */
    if (l2 != 65535L) return 3;

    return 0;
}
""")

    # Test: integer promotion in bitwise ops
    tests.append("""#include <stdio.h>

int main(void) {
    unsigned char mask = 0xFF;
    /* ~ promotes to int first, then inverts all bits */
    int inv = ~mask;
    /* inv should have all bits set except lowest 8 */
    if ((inv & 0xFF) != 0) return 1;
    if (inv == 0) return 2;  /* Must not be zero since upper bits are set */

    /* Shift promotion */
    unsigned short val = 1;
    long shifted = (long)val << 20;
    if (shifted != (1L << 20)) return 3;

    return 0;
}
""")

    # Test: mixed signedness in ternary
    tests.append("""#include <stdio.h>

int main(void) {
    int a = -5;
    unsigned int b = 10;
    /* In ternary, both branches converted to common type (unsigned int) */
    unsigned int result = (a > 0) ? (unsigned int)a : b;
    if (result != 10) return 1;

    /* size_t is unsigned */
    short neg = -1;
    long widened = (long)neg;
    if (widened != -1L) return 2;

    return 0;
}
""")

    # Generate parameterized tests for remaining slots
    for extra in range(count - len(tests)):
        base_val = 50 + extra * 13
        tests.append(f"""#include <stdio.h>
#include <stdint.h>

int main(void) {{
    /* Cross-width arithmetic */
    int8_t a = {(base_val % 120) + 1};
    int16_t b = {base_val * 3};
    int32_t c = (int32_t)a * (int32_t)b;
    if (c != {((base_val % 120) + 1) * base_val * 3}) return 1;

    /* Unsigned narrowing */
    uint32_t wide = {base_val * 1000};
    uint16_t narrow = (uint16_t)wide;
    if (narrow != (uint16_t){base_val * 1000}U) return 2;

    /* Signed/unsigned comparison */
    int32_t sv = -1;
    uint16_t uv = 65535;
    /* sv promoted, uv promoted: -1 as int32 < 65535 as int32 */
    if (!(sv < (int32_t)uv)) return 3;

    return 0;
}}
""")

    for i, code in enumerate(tests):
        idx = start_idx + i
        write_file(os.path.join(base_dir, f'test_{idx:02d}.c'), code)


# ============================================================
# call_conv: Calling convention with separate compilation
# ============================================================

def gen_call_conv(base_dir, start_idx, count):
    """Generate calling convention test pairs (caller + callee)."""

    # Define various parameter type combinations
    param_configs = [
        # (param_types, param_names, call_args, expected_return, description)
        (['int', 'int', 'int'], ['a', 'b', 'c'], ['10', '20', '30'], '60',
         'three ints'),
        (['double', 'double'], ['a', 'b'], ['3.14', '2.72'], None,
         'two doubles'),
        (['int', 'double', 'int'], ['a', 'b', 'c'], ['5', '1.5', '3'], None,
         'mixed int/double'),
        (['long', 'long', 'long', 'long'],
         ['a', 'b', 'c', 'd'],
         ['100L', '200L', '300L', '400L'], '1000',
         'four longs'),
        (['char', 'short', 'int', 'long'],
         ['a', 'b', 'c', 'd'],
         ['1', '2', '3', '4L'], '10',
         'mixed widths'),
        (['float', 'float', 'float', 'float'],
         ['a', 'b', 'c', 'd'],
         ['1.0f', '2.0f', '3.0f', '4.0f'], None,
         'four floats'),
        (['int', 'int', 'int', 'int', 'int', 'int', 'int'],
         ['a', 'b', 'c', 'd', 'e', 'f', 'g'],
         ['1', '2', '3', '4', '5', '6', '7'], '28',
         'seven ints (stack spill)'),
        (['unsigned long', 'signed char', 'unsigned short'],
         ['a', 'b', 'c'],
         ['1000UL', '-5', '500'], None,
         'mixed sign/width'),
    ]

    # Add struct-based tests
    struct_tests = [
        # small struct passed in registers
        ('small_struct', 'struct small { int x; int y; }',
         'struct small s', 's.x = 10; s.y = 20;', 's', 'return s.x + s.y;',
         '30'),
        # large struct passed on stack
        ('large_struct',
         'struct large { int a; int b; int c; int d; int e; }',
         'struct large s',
         's.a=1; s.b=2; s.c=3; s.d=4; s.e=5;', 's',
         'return s.a + s.b + s.c + s.d + s.e;', '15'),
    ]

    idx = start_idx
    # Generate simple parameter-passing tests
    for params, names, args, expected, desc in param_configs:
        param_list = ', '.join(f'{t} {n}' for t, n in zip(params, names))
        sum_expr = ' + '.join(f'(long long){n}' for n in names)

        if expected is None:
            # Compute at compile time for floating point
            if 'double' in params or 'float' in params:
                sum_expr_int = ' + '.join(
                    f'(int){n}' for n in names
                )
                py_sum = sum(
                    int(float(a.rstrip('fL')))
                    for a in args
                )
                expected = str(py_sum)
                ret_type = 'int'
                ret_expr = sum_expr_int
            else:
                py_sum = sum(int(a.rstrip('ULul')) for a in args)
                expected = str(py_sum)
                ret_type = 'long long'
                ret_expr = sum_expr
        else:
            ret_type = 'long long'
            ret_expr = sum_expr

        call_args_str = ', '.join(args)

        callee_code = f"""/* Callee: {desc} */
{ret_type} callee_func({param_list}) {{
    return {ret_expr};
}}
"""
        caller_code = f"""#include <stdio.h>

extern {ret_type} callee_func({param_list});

int main(void) {{
    {ret_type} result = callee_func({call_args_str});
    if (result != {expected}) {{
        printf("FAIL: got %lld expected {expected}\\n",
               (long long)result);
        return 1;
    }}
    return 0;
}}
"""
        write_file(
            os.path.join(base_dir, f'test_{idx:02d}_callee.c'),
            callee_code
        )
        write_file(
            os.path.join(base_dir, f'test_{idx:02d}_caller.c'),
            caller_code
        )
        idx += 1

    # Generate struct tests
    for name, struct_def, var_decl, var_init, var_pass, ret_expr, expected \
            in struct_tests:
        callee_code = f"""/* Callee: {name} */
{struct_def};

int callee_func({struct_def.split('{')[0].strip()} s) {{
    {ret_expr}
}}
"""
        caller_code = f"""#include <stdio.h>

{struct_def};
extern int callee_func({struct_def.split('{')[0].strip()} s);

int main(void) {{
    {var_decl};
    {var_init}
    int result = callee_func({var_pass});
    if (result != {expected}) {{
        printf("FAIL: got %d expected {expected}\\n", result);
        return 1;
    }}
    return 0;
}}
"""
        write_file(
            os.path.join(base_dir, f'test_{idx:02d}_callee.c'),
            callee_code
        )
        write_file(
            os.path.join(base_dir, f'test_{idx:02d}_caller.c'),
            caller_code
        )
        idx += 1


def main():
    base = '/app/tests'

    # irr_flow: keep existing test_01, fix test_02, keep test_03,
    # generate test_04 through test_10
    gen_irr_flow(os.path.join(base, 'irr_flow'), 4, 7)

    # alias: keep existing test_01, fix test_02,
    # generate test_03 through test_10
    gen_alias(os.path.join(base, 'alias'), 3, 8)

    # volatile_opt: generate test_01 through test_10
    gen_volatile(os.path.join(base, 'volatile_opt'), 1, 10)

    # int_promo: generate test_01 through test_10
    gen_int_promo(os.path.join(base, 'int_promo'), 1, 10)

    # call_conv: generate test_01 through test_10
    gen_call_conv(os.path.join(base, 'call_conv'), 1, 10)

    print("Test generation complete.")


if __name__ == '__main__':
    main()
