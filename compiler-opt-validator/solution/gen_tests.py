#!/usr/bin/env python3
"""
Generate self-checking C test programs for compiler optimization validation.

Five categories of optimization-sensitive patterns:
  irr_flow    - Irreducible control flow graphs
  alias       - Pointer aliasing challenges
  volatile_opt - Volatile variable semantics
  int_promo   - Integer promotion edge cases
  call_conv   - Calling convention verification (separate compilation)
"""
import os

OUT = "/app/tests"


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


# ===================================================================
# Irreducible Control Flow
# ===================================================================

def sim_irr_basic(j, k, va, vb):
    """Simulate the two-entry irreducible CFG to get expected result."""
    x, result = 0, 0
    pc = "bb2"
    for _ in range(500):
        if pc == "bb2":
            if j == 0:
                x = 1
                pc = "bb12"
            else:
                pc = "bb4"
        elif pc == "bb4":
            if k == 0:
                return result
            else:
                k = 0
                pc = "bb12"
        elif pc == "bb12":
            if x == 0:
                result = va
                pc = "bb2"
            else:
                result = vb
                pc = "bb4"
    raise RuntimeError("irr_basic did not terminate")


def sim_irr_three(a, b, c):
    """Simulate three-way irreducible CFG."""
    r = 0
    pc = "L1"
    for _ in range(2000):
        if pc == "L1":
            if a > 0:
                a -= 1
                r += 1
                pc = "L2"
            else:
                return r
        elif pc == "L2":
            if b > 0:
                b -= 1
                r += 10
                pc = "L3"
            else:
                pc = "L1"
        elif pc == "L3":
            if c > 0:
                c -= 1
                r += 100
                pc = "L1"
            else:
                pc = "L2"
    raise RuntimeError("irr_three did not terminate")


def gen_irr_flow():
    d = os.path.join(OUT, "irr_flow")

    # --- Basic two-entry irreducible pattern (inspired by SuperTest TSPR4541) ---
    basic_cfgs = [
        (1, 1, 20, 10),
        (0, 1, 20, 10),
        (0, 0, 20, 10),
        (1, 0, 20, 10),
        (1, 1, 42, 17),
        (0, 1, 55, 77),
        (1, 1, 999, 111),
        (0, 1, -5, -10),
    ]
    for i, (j, k, va, vb) in enumerate(basic_cfgs):
        exp = sim_irr_basic(j, k, va, vb)
        code = f"""\
/* Irreducible CFG test {i}: two-entry loop */
#include <stdio.h>

__attribute__((noinline))
int test_func(int j, int k) {{
    int x = 0;
    int result = 0;

    bb2:
    if (j == 0) {{
        x = 1;
        goto bb12;
    }} else {{
        bb4:
        if (k == 0) {{
            goto bb13;
        }} else {{
            k = 0;
            goto bb12;
        }}
    }}

    bb12:
    if (x == 0) {{
        result = {va};
        goto bb2;
    }} else {{
        result = {vb};
        goto bb4;
    }}

    bb13:
    return result;
}}

int main(void) {{
    int r = test_func({j}, {k});
    if (r != {exp}) {{
        fprintf(stderr, "FAIL irr_{i:02d}: got %d expected {exp}\\n", r);
        return 1;
    }}
    return 0;
}}
"""
        w(os.path.join(d, f"test_{i:02d}.c"), code)

    # --- Three-way irreducible cycle L1->L2->L3->L1 ---
    three_cfgs = [
        (2, 2, 2),
        (3, 1, 2),
        (1, 3, 1),
        (5, 0, 3),
    ]
    for idx, (a, b, c) in enumerate(three_cfgs):
        i = len(basic_cfgs) + idx
        exp = sim_irr_three(a, b, c)
        code = f"""\
/* Irreducible CFG test {i}: three-way cycle */
#include <stdio.h>

__attribute__((noinline))
int test_func(int a, int b, int c) {{
    int r = 0;

    L1:
    if (a > 0) {{ a--; r += 1; goto L2; }}
    else {{ goto L_exit; }}

    L2:
    if (b > 0) {{ b--; r += 10; goto L3; }}
    else {{ goto L1; }}

    L3:
    if (c > 0) {{ c--; r += 100; goto L1; }}
    else {{ goto L2; }}

    L_exit:
    return r;
}}

int main(void) {{
    int r = test_func({a}, {b}, {c});
    if (r != {exp}) {{
        fprintf(stderr, "FAIL irr_{i:02d}: got %d expected {exp}\\n", r);
        return 1;
    }}
    return 0;
}}
"""
        w(os.path.join(d, f"test_{i:02d}.c"), code)


# ===================================================================
# Pointer Aliasing
# ===================================================================

def gen_alias():
    d = os.path.join(OUT, "alias")

    # --- Basic pointer aliasing: write-through-p, read-back-through-q ---
    for i in range(4):
        v1 = 10 + i * 7
        v2 = 20 + i * 13
        code = f"""\
/* Alias test {i}: basic pointer aliasing */
#include <stdio.h>

__attribute__((noinline))
int alias_test(int *p, int *q) {{
    *p = {v1};
    *q = {v2};
    return *p;
}}

int main(void) {{
    int a, b;
    /* Non-aliasing: p!=q, so *p unchanged after *q write */
    int r1 = alias_test(&a, &b);
    if (r1 != {v1}) {{
        fprintf(stderr, "FAIL alias_{i:02d} non-alias: got %d expected {v1}\\n", r1);
        return 1;
    }}
    /* Aliasing: p==q, so *q write overwrites *p */
    int r2 = alias_test(&a, &a);
    if (r2 != {v2}) {{
        fprintf(stderr, "FAIL alias_{i:02d} alias: got %d expected {v2}\\n", r2);
        return 1;
    }}
    return 0;
}}
"""
        w(os.path.join(d, f"test_{i:02d}.c"), code)

    # --- Struct member aliasing ---
    for i in range(4):
        member = ["a", "b", "c"][i % 3]
        idx = i % 3
        vals = [100, 200, 300]
        vals[idx] = 999
        exp_sum = sum(vals)
        code = f"""\
/* Alias test {4+i}: struct member aliasing via pointer */
#include <stdio.h>

struct S {{ int a; int b; int c; }};

__attribute__((noinline))
int struct_alias(struct S *s, int *p) {{
    s->a = 100;
    s->b = 200;
    s->c = 300;
    *p = 999;
    return s->a + s->b + s->c;
}}

int main(void) {{
    struct S s;
    int *p = &s.{member};
    int r = struct_alias(&s, p);
    if (r != {exp_sum}) {{
        fprintf(stderr, "FAIL alias_{4+i:02d}: got %d expected {exp_sum}\\n", r);
        return 1;
    }}
    return 0;
}}
"""
        w(os.path.join(d, f"test_{4+i:02d}.c"), code)

    # --- Array overlap aliasing ---
    for i in range(4):
        n = 4 + i
        no_overlap_sum = sum(j + 1 for j in range(n))
        overlap_sum = sum((j + 1) * 10 for j in range(n))
        code = f"""\
/* Alias test {8+i}: array overlap aliasing */
#include <stdio.h>

__attribute__((noinline))
int array_alias(int *a, int *b, int n) {{
    int sum = 0;
    for (int i = 0; i < n; i++) {{
        a[i] = i + 1;
        b[i] = (i + 1) * 10;
        sum += a[i];
    }}
    return sum;
}}

int main(void) {{
    int x[20], y[20];
    /* Non-overlapping */
    int r1 = array_alias(x, y, {n});
    if (r1 != {no_overlap_sum}) {{
        fprintf(stderr, "FAIL alias_{8+i:02d} no-overlap: got %d expected {no_overlap_sum}\\n", r1);
        return 1;
    }}
    /* Same array: b[i] write overwrites a[i], so sum reads back (i+1)*10 */
    int z[20];
    int r2 = array_alias(z, z, {n});
    if (r2 != {overlap_sum}) {{
        fprintf(stderr, "FAIL alias_{8+i:02d} overlap: got %d expected {overlap_sum}\\n", r2);
        return 1;
    }}
    return 0;
}}
"""
        w(os.path.join(d, f"test_{8+i:02d}.c"), code)


# ===================================================================
# Volatile Semantics
# ===================================================================

def gen_volatile_opt():
    d = os.path.join(OUT, "volatile_opt")

    tests = []

    # Test 0: volatile read ordering
    tests.append("""\
/* Volatile test 0: read ordering */
#include <stdio.h>
int main(void) {
    volatile int v = 0;
    v = 10;
    int a = v;
    v = 20;
    int b = v;
    if (a != 10 || b != 20) {
        fprintf(stderr, "FAIL vol_00: a=%d b=%d\\n", a, b);
        return 1;
    }
    return 0;
}
""")

    # Test 1: volatile loop counter
    tests.append("""\
/* Volatile test 1: loop counter */
#include <stdio.h>
int main(void) {
    volatile int count = 0;
    int sum = 0;
    while (count < 10) {
        sum += count;
        count = count + 1;
    }
    if (sum != 45) {
        fprintf(stderr, "FAIL vol_01: sum=%d expected 45\\n", sum);
        return 1;
    }
    return 0;
}
""")

    # Test 2: volatile counter with noinline function
    tests.append("""\
/* Volatile test 2: volatile counter via function */
#include <stdio.h>
volatile int g_counter = 0;
__attribute__((noinline))
void inc(void) { g_counter++; }
int main(void) {
    for (int i = 0; i < 50; i++) inc();
    if (g_counter != 50) {
        fprintf(stderr, "FAIL vol_02: counter=%d expected 50\\n", g_counter);
        return 1;
    }
    return 0;
}
""")

    # Test 3: volatile preventing strength reduction
    tests.append("""\
/* Volatile test 3: loop with volatile bound */
#include <stdio.h>
int main(void) {
    volatile int n = 10;
    int sum = 0;
    for (int i = 0; i < n; i++) {
        sum += i * i;
    }
    if (sum != 285) {
        fprintf(stderr, "FAIL vol_03: sum=%d expected 285\\n", sum);
        return 1;
    }
    return 0;
}
""")

    # Test 4: multiple volatile variables
    tests.append("""\
/* Volatile test 4: multiple volatiles */
#include <stdio.h>
int main(void) {
    volatile int a = 3, b = 7;
    int r1 = a + b;
    int r2 = a * b;
    if (r1 != 10 || r2 != 21) {
        fprintf(stderr, "FAIL vol_04: r1=%d r2=%d\\n", r1, r2);
        return 1;
    }
    return 0;
}
""")

    # Test 5: volatile pointer
    tests.append("""\
/* Volatile test 5: volatile pointer */
#include <stdio.h>
int main(void) {
    int storage = 42;
    int * volatile vp = &storage;
    int r = *vp;
    if (r != 42) {
        fprintf(stderr, "FAIL vol_05: r=%d expected 42\\n", r);
        return 1;
    }
    return 0;
}
""")

    # Test 6: pointer to volatile
    tests.append("""\
/* Volatile test 6: pointer to volatile */
#include <stdio.h>
int main(void) {
    volatile int vol = 200;
    volatile int *pv = &vol;
    int r = *pv;
    *pv = 300;
    int r2 = *pv;
    if (r != 200 || r2 != 300) {
        fprintf(stderr, "FAIL vol_06: r=%d r2=%d\\n", r, r2);
        return 1;
    }
    return 0;
}
""")

    # Test 7: volatile preventing dead code elimination in loop
    tests.append("""\
/* Volatile test 7: volatile sink prevents loop elimination */
#include <stdio.h>
volatile int sink;
int main(void) {
    int sum = 0;
    for (int i = 0; i < 100; i++) {
        sink = i;
        sum += i;
    }
    if (sum != 4950) {
        fprintf(stderr, "FAIL vol_07: sum=%d expected 4950\\n", sum);
        return 1;
    }
    return 0;
}
""")

    # Test 8: volatile struct member
    tests.append("""\
/* Volatile test 8: volatile struct member */
#include <stdio.h>
struct VS { volatile int x; int y; };
int main(void) {
    struct VS s;
    s.x = 10;
    s.y = 20;
    s.x = 30;
    int r = s.x + s.y;
    if (r != 50) {
        fprintf(stderr, "FAIL vol_08: r=%d expected 50\\n", r);
        return 1;
    }
    return 0;
}
""")

    # Test 9: volatile array element
    tests.append("""\
/* Volatile test 9: volatile array */
#include <stdio.h>
volatile int arr[5];
int main(void) {
    for (int i = 0; i < 5; i++) arr[i] = i * i;
    int sum = 0;
    for (int i = 0; i < 5; i++) sum += arr[i];
    /* 0 + 1 + 4 + 9 + 16 = 30 */
    if (sum != 30) {
        fprintf(stderr, "FAIL vol_09: sum=%d expected 30\\n", sum);
        return 1;
    }
    return 0;
}
""")

    for i, code in enumerate(tests):
        w(os.path.join(d, f"test_{i:02d}.c"), code)


# ===================================================================
# Integer Promotion
# ===================================================================

def gen_int_promo():
    d = os.path.join(OUT, "int_promo")

    tests = []

    # Test 0: unsigned char multiplication promotes to int
    tests.append("""\
/* Int promotion test 0: unsigned char * unsigned char -> int */
#include <stdio.h>
int main(void) {
    unsigned char a = 200, b = 200;
    int result = a * b;
    if (result != 40000) {
        fprintf(stderr, "FAIL promo_00: %d != 40000\\n", result);
        return 1;
    }
    return 0;
}
""")

    # Test 1: unsigned short addition promotes to int
    tests.append("""\
/* Int promotion test 1: unsigned short + unsigned short -> int */
#include <stdio.h>
int main(void) {
    unsigned short a = 40000, b = 30000;
    int result = a + b;
    if (result != 70000) {
        fprintf(stderr, "FAIL promo_01: %d != 70000\\n", result);
        return 1;
    }
    return 0;
}
""")

    # Test 2: signed char vs unsigned comparison
    tests.append("""\
/* Int promotion test 2: signed char vs unsigned comparison */
#include <stdio.h>
int main(void) {
    signed char a = -1;
    unsigned int b = 0;
    /* char -1 promoted to int, then converts to UINT_MAX, which is > 0 */
    int result = (a > b);
    if (result != 1) {
        fprintf(stderr, "FAIL promo_02: (-1 > 0u) = %d, expected 1\\n", result);
        return 1;
    }
    return 0;
}
""")

    # Test 3: unsigned short subtraction wraparound
    tests.append("""\
/* Int promotion test 3: unsigned short subtraction wrap */
#include <stdio.h>
int main(void) {
    unsigned short a = 5, b = 10;
    unsigned short result = a - b;
    /* Both promoted to int: 5 - 10 = -5, truncated to unsigned short = 65531 */
    if (result != (unsigned short)(-5)) {
        fprintf(stderr, "FAIL promo_03: %u != %u\\n", (unsigned)result, (unsigned)(unsigned short)(-5));
        return 1;
    }
    return 0;
}
""")

    # Test 4: signed char sign extension to long
    tests.append("""\
/* Int promotion test 4: signed char -> long sign extension */
#include <stdio.h>
int main(void) {
    signed char c = -50;
    long result = c;
    if (result != -50) {
        fprintf(stderr, "FAIL promo_04: %ld != -50\\n", result);
        return 1;
    }
    return 0;
}
""")

    # Test 5: unsigned short left shift promotes to int
    tests.append("""\
/* Int promotion test 5: unsigned short shift promotion */
#include <stdio.h>
int main(void) {
    unsigned short s = 0x8000u;
    int result = s << 1;
    /* 0x8000 promoted to int, <<1 = 0x10000 = 65536 */
    if (result != 65536) {
        fprintf(stderr, "FAIL promo_05: %d != 65536\\n", result);
        return 1;
    }
    return 0;
}
""")

    # Test 6: mixed signed/unsigned addition
    tests.append("""\
/* Int promotion test 6: unsigned int + short -> unsigned wrap */
#include <stdio.h>
int main(void) {
    unsigned int a = 10;
    short b = -3;
    /* short -3 promoted to int, then converts to unsigned: UINT_MAX-2 */
    /* 10 + UINT_MAX-2 = UINT_MAX+8 mod (UINT_MAX+1) = 7 */
    unsigned int result = a + b;
    if (result != 7) {
        fprintf(stderr, "FAIL promo_06: %u != 7\\n", result);
        return 1;
    }
    return 0;
}
""")

    # Test 7: ternary with mixed signed/unsigned
    tests.append("""\
/* Int promotion test 7: ternary common type with short */
#include <stdio.h>
int main(void) {
    short a = 1;
    unsigned int b = 2;
    unsigned int result = (a > 0) ? (unsigned int)a : b;
    if (result != 1) {
        fprintf(stderr, "FAIL promo_07: %u != 1\\n", result);
        return 1;
    }
    return 0;
}
""")

    # Test 8: unary minus of unsigned long
    tests.append("""\
/* Int promotion test 8: negation of unsigned long */
#include <stdio.h>
int main(void) {
    unsigned long a = 5;
    unsigned long b = -a;
    /* -5ul = ULONG_MAX - 4, so b + a wraps to 0 */
    unsigned long sum = b + a;
    if (sum != 0) {
        fprintf(stderr, "FAIL promo_08: %lu + %lu = %lu, expected 0\\n", b, a, sum);
        return 1;
    }
    return 0;
}
""")

    # Test 9: sizeof comparison with signed
    tests.append("""\
/* Int promotion test 9: sizeof produces unsigned, comparison with signed */
#include <stdio.h>
#include <stddef.h>
int main(void) {
    /* sizeof returns size_t (unsigned). -1 converts to SIZE_MAX. */
    int result = (-1 > (int)sizeof(int)) ? 0 : 1;
    /* (int)sizeof(int) is typically 4. -1 < 4, so result = 1 */
    if (result != 1) {
        fprintf(stderr, "FAIL promo_09: %d != 1\\n", result);
        return 1;
    }
    return 0;
}
""")

    for i, code in enumerate(tests):
        w(os.path.join(d, f"test_{i:02d}.c"), code)


# ===================================================================
# Calling Convention (separate compilation)
# ===================================================================

def gen_call_conv():
    d = os.path.join(OUT, "call_conv")

    pairs = []

    # Test 0: 8 int parameters (exhaust integer registers)
    pairs.append((
        """\
/* call_conv callee 0: 8 int params */
long callee_func(int a, int b, int c, int d, int e, int f, int g, int h) {
    return (long)a + b + c + d + e + f + g + h;
}
""",
        """\
/* call_conv caller 0: 8 int params */
#include <stdio.h>
extern long callee_func(int, int, int, int, int, int, int, int);
int main(void) {
    long r = callee_func(1, 2, 3, 4, 5, 6, 7, 8);
    if (r != 36) { fprintf(stderr, "FAIL cc_00: %ld != 36\\n", r); return 1; }
    return 0;
}
"""))

    # Test 1: 8 double parameters (exhaust FP registers)
    pairs.append((
        """\
/* call_conv callee 1: 8 double params */
double callee_func(double a, double b, double c, double d,
                   double e, double f, double g, double h) {
    return a + b + c + d + e + f + g + h;
}
""",
        """\
/* call_conv caller 1: 8 double params */
#include <stdio.h>
extern double callee_func(double, double, double, double,
                          double, double, double, double);
int main(void) {
    double r = callee_func(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0);
    if (r < 35.99 || r > 36.01) { fprintf(stderr, "FAIL cc_01: %f\\n", r); return 1; }
    return 0;
}
"""))

    # Test 2: mixed int/double alternating
    pairs.append((
        """\
/* call_conv callee 2: mixed int/double */
double callee_func(int a, double b, int c, double d) {
    return (double)a + b + (double)c + d;
}
""",
        """\
/* call_conv caller 2: mixed int/double */
#include <stdio.h>
extern double callee_func(int, double, int, double);
int main(void) {
    double r = callee_func(10, 0.5, 20, 0.25);
    if (r < 30.74 || r > 30.76) { fprintf(stderr, "FAIL cc_02: %f\\n", r); return 1; }
    return 0;
}
"""))

    # Test 3: small struct by value (fits in register)
    pairs.append((
        """\
/* call_conv callee 3: small struct */
struct Small { int x; int y; };
int callee_func(struct Small s) {
    return s.x * 100 + s.y;
}
""",
        """\
/* call_conv caller 3: small struct */
#include <stdio.h>
struct Small { int x; int y; };
extern int callee_func(struct Small);
int main(void) {
    struct Small s = {12, 34};
    int r = callee_func(s);
    if (r != 1234) { fprintf(stderr, "FAIL cc_03: %d != 1234\\n", r); return 1; }
    return 0;
}
"""))

    # Test 4: large struct by value (must go on stack)
    pairs.append((
        """\
/* call_conv callee 4: large struct */
struct Big { int data[20]; };
int callee_func(struct Big b) {
    int sum = 0;
    for (int i = 0; i < 20; i++) sum += b.data[i];
    return sum;
}
""",
        """\
/* call_conv caller 4: large struct */
#include <stdio.h>
struct Big { int data[20]; };
extern int callee_func(struct Big);
int main(void) {
    struct Big b;
    for (int i = 0; i < 20; i++) b.data[i] = i + 1;
    int r = callee_func(b);
    /* 1+2+...+20 = 210 */
    if (r != 210) { fprintf(stderr, "FAIL cc_04: %d != 210\\n", r); return 1; }
    return 0;
}
"""))

    # Test 5: return struct
    pairs.append((
        """\
/* call_conv callee 5: return struct */
struct Pair { int a; int b; };
struct Pair callee_func(int x) {
    struct Pair p;
    p.a = x * 2;
    p.b = x * 3;
    return p;
}
""",
        """\
/* call_conv caller 5: return struct */
#include <stdio.h>
struct Pair { int a; int b; };
extern struct Pair callee_func(int);
int main(void) {
    struct Pair p = callee_func(7);
    if (p.a != 14 || p.b != 21) {
        fprintf(stderr, "FAIL cc_05: a=%d b=%d\\n", p.a, p.b);
        return 1;
    }
    return 0;
}
"""))

    # Test 6: varargs (ints)
    pairs.append((
        """\
/* call_conv callee 6: varargs ints */
#include <stdarg.h>
int callee_func(int count, ...) {
    va_list ap;
    va_start(ap, count);
    int sum = 0;
    for (int i = 0; i < count; i++) sum += va_arg(ap, int);
    va_end(ap);
    return sum;
}
""",
        """\
/* call_conv caller 6: varargs ints */
#include <stdio.h>
extern int callee_func(int count, ...);
int main(void) {
    int r = callee_func(5, 10, 20, 30, 40, 50);
    if (r != 150) { fprintf(stderr, "FAIL cc_06: %d != 150\\n", r); return 1; }
    return 0;
}
"""))

    # Test 7: varargs mixed types
    pairs.append((
        """\
/* call_conv callee 7: varargs mixed */
#include <stdarg.h>
double callee_func(int count, ...) {
    va_list ap;
    va_start(ap, count);
    double sum = 0;
    for (int i = 0; i < count; i++) {
        if (i % 2 == 0) sum += va_arg(ap, int);
        else sum += va_arg(ap, double);
    }
    va_end(ap);
    return sum;
}
""",
        """\
/* call_conv caller 7: varargs mixed */
#include <stdio.h>
extern double callee_func(int count, ...);
int main(void) {
    double r = callee_func(4, 10, 1.5, 20, 2.5);
    if (r < 33.99 || r > 34.01) { fprintf(stderr, "FAIL cc_07: %f\\n", r); return 1; }
    return 0;
}
"""))

    # Test 8: nested struct
    pairs.append((
        """\
/* call_conv callee 8: nested struct */
struct Inner { short a; short b; };
struct Outer { struct Inner x; struct Inner y; int z; };
int callee_func(struct Outer o) {
    return o.x.a + o.x.b + o.y.a + o.y.b + o.z;
}
""",
        """\
/* call_conv caller 8: nested struct */
#include <stdio.h>
struct Inner { short a; short b; };
struct Outer { struct Inner x; struct Inner y; int z; };
extern int callee_func(struct Outer);
int main(void) {
    struct Inner x = {1, 2}, y = {3, 4};
    struct Outer o = {x, y, 5};
    int r = callee_func(o);
    if (r != 15) { fprintf(stderr, "FAIL cc_08: %d != 15\\n", r); return 1; }
    return 0;
}
"""))

    # Test 9: function pointer parameter
    pairs.append((
        """\
/* call_conv callee 9: function pointer param */
typedef int (*op_fn)(int, int);
int callee_func(op_fn op, int a, int b) {
    return op(a, b);
}
""",
        """\
/* call_conv caller 9: function pointer param */
#include <stdio.h>
typedef int (*op_fn)(int, int);
extern int callee_func(op_fn, int, int);
static int add(int a, int b) { return a + b; }
int main(void) {
    int r = callee_func(add, 17, 25);
    if (r != 42) { fprintf(stderr, "FAIL cc_09: %d != 42\\n", r); return 1; }
    return 0;
}
"""))

    for i, (callee_code, caller_code) in enumerate(pairs):
        w(os.path.join(d, f"test_{i:02d}_callee.c"), callee_code)
        w(os.path.join(d, f"test_{i:02d}_caller.c"), caller_code)


# ===================================================================

def main():
    gen_irr_flow()
    gen_alias()
    gen_volatile_opt()
    gen_int_promo()
    gen_call_conv()
    total = 12 + 12 + 10 + 10 + 10
    print(f"Generated {total} test programs in {OUT}/")


if __name__ == "__main__":
    main()
