#!/usr/bin/env python3
"""
x86-64 System V ABI Calling Convention Validator
Generates, compiles, and runs cross-compiler calling convention tests.
"""

import os
import json
import subprocess
import sys
from pathlib import Path

# --- Paths ---
APP = Path("/app")
GEN = APP / "generated"
HDR = GEN / "headers"
BLD = APP / "build"
RES = APP / "results"

COMBOS = [("gcc", "gcc"), ("clang", "clang"), ("gcc", "clang"), ("clang", "gcc")]


# --- Test representation ---
class Test:
    def __init__(self, num, scenario, desc, caller, callee, header=None):
        self.num = num
        self.test_id = f"{scenario}_{num:03d}"
        self.scenario = scenario
        self.desc = desc
        self.caller = caller
        self.callee = callee
        self.header = header


# --- Helpers to build test code ---

def scalar_test(num, scenario, desc, params):
    """
    Generate a scalar-parameter test.
    params: list of (c_type, value_literal) tuples.
    """
    fn = f"callee_{num:03d}"
    pdecl = ", ".join(f"{t} p{i}" for i, (t, _) in enumerate(params))
    ptypes = ", ".join(t for t, _ in params)
    pvals = ", ".join(v for _, v in params)
    checks = "\n".join(
        f"    if (p{i} != {v}) errors++;" for i, (_, v) in enumerate(params)
    )

    callee = (
        f"#include <stdio.h>\n#include <stdint.h>\n\n"
        f"int {fn}({pdecl}) {{\n    int errors = 0;\n{checks}\n    return errors;\n}}\n"
    )
    caller = (
        f"#include <stdio.h>\n#include <stdint.h>\n\n"
        f"extern int {fn}({ptypes});\n\n"
        f"int main(void) {{\n"
        f"    int r = {fn}({pvals});\n"
        f"    if (r != 0) {{ fprintf(stderr, \"FAIL {fn}: %d errors\\n\", r); return 1; }}\n"
        f"    printf(\"PASS {fn}\\n\");\n    return 0;\n}}\n"
    )
    return Test(num, scenario, desc, caller, callee)


def struct_param_test(num, scenario, desc, sname, sdef, sinit, schecks):
    """Generate a struct-parameter test with a shared header."""
    fn = f"callee_{num:03d}"
    hname = f"types_{num:03d}.h"
    guard = f"TYPES_{num:03d}_H"

    header = f"#ifndef {guard}\n#define {guard}\n#include <stdint.h>\n{sdef}\n#endif\n"
    checks_str = "\n".join(f"    {c}" for c in schecks)

    callee = (
        f"#include <stdio.h>\n#include <stdint.h>\n#include \"{hname}\"\n\n"
        f"int {fn}({sname} s) {{\n    int errors = 0;\n{checks_str}\n    return errors;\n}}\n"
    )
    caller = (
        f"#include <stdio.h>\n#include <stdint.h>\n#include \"{hname}\"\n\n"
        f"extern int {fn}({sname} s);\n\n"
        f"int main(void) {{\n"
        f"    {sname} s = {sinit};\n"
        f"    int r = {fn}(s);\n"
        f"    if (r != 0) {{ fprintf(stderr, \"FAIL {fn}: %d errors\\n\", r); return 1; }}\n"
        f"    printf(\"PASS {fn}\\n\");\n    return 0;\n}}\n"
    )
    return Test(num, scenario, desc, caller, callee, header)


def struct_return_test(num, scenario, desc, sname, sdef, callee_body, caller_checks):
    """Generate a struct-return-value test."""
    fn = f"callee_{num:03d}"
    hname = f"types_{num:03d}.h"
    guard = f"TYPES_{num:03d}_H"

    header = f"#ifndef {guard}\n#define {guard}\n#include <stdint.h>\n{sdef}\n#endif\n"

    callee = (
        f"#include <stdio.h>\n#include <stdint.h>\n#include \"{hname}\"\n\n"
        f"{sname} {fn}(void) {{\n{callee_body}\n}}\n"
    )
    caller = (
        f"#include <stdio.h>\n#include <stdint.h>\n#include \"{hname}\"\n\n"
        f"extern {sname} {fn}(void);\n\n"
        f"int main(void) {{\n"
        f"    {sname} rv = {fn}();\n"
        f"    int errors = 0;\n{caller_checks}\n"
        f"    if (errors != 0) {{ fprintf(stderr, \"FAIL {fn}: %d errors\\n\", errors); return 1; }}\n"
        f"    printf(\"PASS {fn}\\n\");\n    return 0;\n}}\n"
    )
    return Test(num, scenario, desc, caller, callee, header)


def custom_test(num, scenario, desc, caller, callee):
    return Test(num, scenario, desc, caller, callee)


# --- Generate all tests ---

def gen_all():
    tests = []
    n = 0

    # ================================================================
    # INTEGER REGISTER TESTS
    # ================================================================
    for np in [1, 2, 3, 4, 5, 6]:
        n += 1
        params = [("int64_t", f"{i + 1}LL") for i in range(np)]
        tests.append(scalar_test(n, "integer_regs",
                                 f"{np} int64 params in registers", params))

    # Stack overflow: 7, 8, 10 params
    for np in [7, 8, 10]:
        n += 1
        params = [("int64_t", f"{(i + 1) * 11}LL") for i in range(np)]
        tests.append(scalar_test(n, "integer_regs",
                                 f"{np} int64 params (regs + stack)", params))

    # Mixed integer widths
    n += 1
    tests.append(scalar_test(n, "integer_regs", "mixed integer sizes", [
        ("int8_t", "(int8_t)17"), ("int16_t", "(int16_t)8738"),
        ("int32_t", "(int32_t)858993459"), ("int64_t", "4919131752989213764LL"),
        ("uint8_t", "(uint8_t)170"), ("uint32_t", "(uint32_t)3149642683U"),
    ]))

    # ================================================================
    # SSE REGISTER TESTS
    # ================================================================
    for np in [1, 4, 8]:
        n += 1
        params = [("float", f"{i + 1}.0f") for i in range(np)]
        tests.append(scalar_test(n, "sse_regs", f"{np} float params", params))

    for np in [1, 4, 8]:
        n += 1
        params = [("double", f"{i + 1}.0") for i in range(np)]
        tests.append(scalar_test(n, "sse_regs", f"{np} double params", params))

    # Stack overflow
    n += 1
    tests.append(scalar_test(n, "sse_regs", "10 doubles (regs + stack)",
                             [("double", f"{i + 1}.0") for i in range(10)]))
    n += 1
    tests.append(scalar_test(n, "sse_regs", "12 floats (regs + stack)",
                             [("float", f"{i + 1}.0f") for i in range(12)]))

    # ================================================================
    # MIXED PARAMS
    # ================================================================
    n += 1
    tests.append(scalar_test(n, "mixed_params", "alternating int/float", [
        ("int64_t", "1LL"), ("double", "2.0"), ("int32_t", "(int32_t)3"),
        ("float", "4.0f"), ("int64_t", "5LL"), ("double", "6.0"),
    ]))
    n += 1
    tests.append(scalar_test(n, "mixed_params", "6 ints + 8 doubles",
        [("int64_t", f"{i + 1}LL") for i in range(6)] +
        [("double", f"{i + 7}.0") for i in range(8)]
    ))
    n += 1
    tests.append(scalar_test(n, "mixed_params", "8 ints + 10 doubles overflow",
        [("int64_t", f"{i + 1}LL") for i in range(8)] +
        [("double", f"{i + 9}.0") for i in range(10)]
    ))
    n += 1
    tests.append(scalar_test(n, "mixed_params", "varied types interleaved", [
        ("int32_t", "(int32_t)1"), ("float", "2.0f"), ("int64_t", "3LL"),
        ("double", "4.0"), ("int16_t", "(int16_t)5"), ("float", "6.0f"),
        ("int64_t", "7LL"), ("double", "8.0"),
    ]))

    # ================================================================
    # STRUCT SMALL (<= 8 bytes)
    # ================================================================
    small = [
        ("SmallS1", "typedef struct { char a; } SmallS1;",
         "{ .a = 'X' }", ["if (s.a != 'X') errors++;"],
         "1-byte char struct"),
        ("SmallS2", "typedef struct { int32_t a; } SmallS2;",
         "{ .a = 42 }", ["if (s.a != 42) errors++;"],
         "4-byte int struct"),
        ("SmallS3", "typedef struct { int64_t a; } SmallS3;",
         "{ .a = 0x123456789ABCDEFLL }",
         ["if (s.a != 0x123456789ABCDEFLL) errors++;"],
         "8-byte int64 struct"),
        ("SmallS4", "typedef struct { char a; short b; int c; } SmallS4;",
         "{ .a = 11, .b = 2222, .c = 333333 }",
         ["if (s.a != 11) errors++;", "if (s.b != 2222) errors++;",
          "if (s.c != 333333) errors++;"],
         "padded struct 8 bytes"),
        ("SmallS5", "typedef struct { float a; } SmallS5;",
         "{ .a = 3.0f }", ["if (s.a != 3.0f) errors++;"],
         "float struct SSE class"),
    ]
    for sn, sd, si, sc, sdesc in small:
        n += 1
        tests.append(struct_param_test(n, "struct_small", sdesc, sn, sd, si, sc))

    # ================================================================
    # STRUCT MEDIUM (9-16 bytes)
    # ================================================================
    medium = [
        ("MedS1", "typedef struct { int64_t a; int64_t b; } MedS1;",
         "{ .a = 0x1111111111111111LL, .b = 0x2222222222222222LL }",
         ["if (s.a != 0x1111111111111111LL) errors++;",
          "if (s.b != 0x2222222222222222LL) errors++;"],
         "16-byte two INTEGER regs"),
        ("MedS2", "typedef struct { int64_t a; double b; } MedS2;",
         "{ .a = 0x0ABCDEF012345678LL, .b = 99.0 }",
         ["if (s.a != 0x0ABCDEF012345678LL) errors++;",
          "if (s.b != 99.0) errors++;"],
         "16-byte INTEGER + SSE"),
        ("MedS3", "typedef struct { double a; double b; } MedS3;",
         "{ .a = 1.5, .b = 2.5 }",
         ["if (s.a != 1.5) errors++;", "if (s.b != 2.5) errors++;"],
         "16-byte two SSE regs"),
        ("MedS4", "typedef struct { int32_t a; int32_t b; int32_t c; } MedS4;",
         "{ .a = 111, .b = 222, .c = 333 }",
         ["if (s.a != 111) errors++;", "if (s.b != 222) errors++;",
          "if (s.c != 333) errors++;"],
         "12-byte padded two INTEGER"),
        ("MedS5", "typedef struct { char a[16]; } MedS5;",
         "{ .a = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16} }",
         ["for (int i = 0; i < 16; i++) if (s.a[i] != i + 1) errors++;"],
         "16-byte char array"),
    ]
    for sn, sd, si, sc, sdesc in medium:
        n += 1
        tests.append(struct_param_test(n, "struct_medium", sdesc, sn, sd, si, sc))

    # ================================================================
    # STRUCT LARGE (> 16 bytes -> MEMORY class)
    # ================================================================
    large = [
        ("LargeS1", "typedef struct { int64_t a; int64_t b; int64_t c; } LargeS1;",
         "{ .a = 1LL, .b = 2LL, .c = 3LL }",
         ["if (s.a != 1) errors++;", "if (s.b != 2) errors++;",
          "if (s.c != 3) errors++;"],
         "24-byte MEMORY class"),
        ("LargeS2", "typedef struct { char a[32]; } LargeS2;",
         "{ .a = {[0]=1, [15]=16, [31]=32} }",
         ["if (s.a[0] != 1) errors++;", "if (s.a[15] != 16) errors++;",
          "if (s.a[31] != 32) errors++;"],
         "32-byte char array MEMORY"),
        ("LargeS3", "typedef struct { int64_t a[4]; } LargeS3;",
         "{ .a = {10, 20, 30, 40} }",
         ["if (s.a[0] != 10) errors++;", "if (s.a[1] != 20) errors++;",
          "if (s.a[2] != 30) errors++;", "if (s.a[3] != 40) errors++;"],
         "32-byte int64 array MEMORY"),
        ("LargeS4", "typedef struct { double d[4]; } LargeS4;",
         "{ .d = {1.0, 2.0, 3.0, 4.0} }",
         ["if (s.d[0] != 1.0) errors++;", "if (s.d[1] != 2.0) errors++;",
          "if (s.d[2] != 3.0) errors++;", "if (s.d[3] != 4.0) errors++;"],
         "32-byte double array MEMORY"),
    ]
    for sn, sd, si, sc, sdesc in large:
        n += 1
        tests.append(struct_param_test(n, "struct_large", sdesc, sn, sd, si, sc))

    # ================================================================
    # STRUCT MIXED FIELDS
    # ================================================================
    mixed = [
        ("MixS1", "typedef struct { int32_t a; float b; } MixS1;",
         "{ .a = 42, .b = 3.0f }",
         ["if (s.a != 42) errors++;", "if (s.b != 3.0f) errors++;"],
         "int+float same eightbyte"),
        ("MixS2", "typedef struct { double a; int32_t b; } MixS2;",
         "{ .a = 7.0, .b = 99 }",
         ["if (s.a != 7.0) errors++;", "if (s.b != 99) errors++;"],
         "SSE+INTEGER eightbytes"),
        ("MixS3",
         "typedef struct { float a; float b; int32_t c; int32_t d; } MixS3;",
         "{ .a = 1.0f, .b = 2.0f, .c = 3, .d = 4 }",
         ["if (s.a != 1.0f) errors++;", "if (s.b != 2.0f) errors++;",
          "if (s.c != 3) errors++;", "if (s.d != 4) errors++;"],
         "mixed float/int 16-byte"),
        ("MixS4",
         "typedef struct { char x; } MixInner;\n"
         "typedef struct { MixInner i; double d; } MixS4;",
         "{ .i = { .x = 'A' }, .d = 5.0 }",
         ["if (s.i.x != 'A') errors++;", "if (s.d != 5.0) errors++;"],
         "nested struct mixed types"),
    ]
    for sn, sd, si, sc, sdesc in mixed:
        n += 1
        tests.append(struct_param_test(n, "struct_mixed_fields", sdesc,
                                       sn, sd, si, sc))

    # ================================================================
    # RETURN VALUE TESTS
    # ================================================================
    n += 1
    tests.append(struct_return_test(
        n, "return_values", "return 8-byte struct in rax",
        "RetS1", "typedef struct { int64_t a; } RetS1;",
        "    RetS1 r; r.a = 0x0DEADBEEFCAFE123LL; return r;",
        "    if (rv.a != 0x0DEADBEEFCAFE123LL) errors++;",
    ))

    n += 1
    tests.append(struct_return_test(
        n, "return_values", "return 16-byte struct in rax+rdx",
        "RetS2", "typedef struct { int64_t a; int64_t b; } RetS2;",
        "    RetS2 r; r.a = 111LL; r.b = 222LL; return r;",
        "    if (rv.a != 111LL) errors++;\n    if (rv.b != 222LL) errors++;",
    ))

    n += 1
    tests.append(struct_return_test(
        n, "return_values", "return struct in rax+xmm0",
        "RetS3", "typedef struct { int64_t a; double b; } RetS3;",
        "    RetS3 r; r.a = 42LL; r.b = 3.5; return r;",
        "    if (rv.a != 42LL) errors++;\n    if (rv.b != 3.5) errors++;",
    ))

    n += 1
    tests.append(struct_return_test(
        n, "return_values", "return large struct via hidden pointer",
        "RetS4", "typedef struct { int64_t a; int64_t b; int64_t c; } RetS4;",
        "    RetS4 r; r.a = 10; r.b = 20; r.c = 30; return r;",
        "    if (rv.a != 10) errors++;\n    if (rv.b != 20) errors++;\n"
        "    if (rv.c != 30) errors++;",
    ))

    n += 1
    tests.append(struct_return_test(
        n, "return_values", "return struct with doubles in xmm0+xmm1",
        "RetS5", "typedef struct { double a; double b; } RetS5;",
        "    RetS5 r; r.a = 1.5; r.b = 2.5; return r;",
        "    if (rv.a != 1.5) errors++;\n    if (rv.b != 2.5) errors++;",
    ))

    # ================================================================
    # VARIADIC TESTS
    # ================================================================
    n += 1
    fn = f"callee_{n:03d}"
    tests.append(custom_test(n, "variadic", "variadic int64 args",
        caller=(
            f"#include <stdio.h>\n#include <stdint.h>\n\n"
            f"extern int {fn}(int count, ...);\n\n"
            f"int main(void) {{\n"
            f"    int r = {fn}(5, (int64_t)10, (int64_t)20, (int64_t)30,"
            f" (int64_t)40, (int64_t)50);\n"
            f"    if (r != 0) {{ fprintf(stderr, \"FAIL {fn}\\n\"); return 1; }}\n"
            f"    printf(\"PASS {fn}\\n\");\n    return 0;\n}}\n"
        ),
        callee=(
            f"#include <stdio.h>\n#include <stdarg.h>\n#include <stdint.h>\n\n"
            f"int {fn}(int count, ...) {{\n"
            f"    va_list ap;\n    va_start(ap, count);\n    int errors = 0;\n"
            f"    for (int i = 0; i < count; i++) {{\n"
            f"        int64_t v = va_arg(ap, int64_t);\n"
            f"        if (v != (i + 1) * 10) errors++;\n"
            f"    }}\n    va_end(ap);\n    return errors;\n}}\n"
        ),
    ))

    n += 1
    fn = f"callee_{n:03d}"
    tests.append(custom_test(n, "variadic", "variadic mixed int/double",
        caller=(
            f"#include <stdio.h>\n#include <stdint.h>\n\n"
            f"extern int {fn}(int count, ...);\n\n"
            f"int main(void) {{\n"
            f"    int r = {fn}(4, (int64_t)42, 3.5, (int64_t)99, 2.75);\n"
            f"    if (r != 0) {{ fprintf(stderr, \"FAIL {fn}\\n\"); return 1; }}\n"
            f"    printf(\"PASS {fn}\\n\");\n    return 0;\n}}\n"
        ),
        callee=(
            f"#include <stdio.h>\n#include <stdarg.h>\n#include <stdint.h>\n\n"
            f"int {fn}(int count, ...) {{\n"
            f"    va_list ap;\n    va_start(ap, count);\n    int errors = 0;\n"
            f"    int64_t v1 = va_arg(ap, int64_t);\n"
            f"    if (v1 != 42) errors++;\n"
            f"    double v2 = va_arg(ap, double);\n"
            f"    if (v2 != 3.5) errors++;\n"
            f"    int64_t v3 = va_arg(ap, int64_t);\n"
            f"    if (v3 != 99) errors++;\n"
            f"    double v4 = va_arg(ap, double);\n"
            f"    if (v4 != 2.75) errors++;\n"
            f"    va_end(ap);\n    return errors;\n}}\n"
        ),
    ))

    n += 1
    fn = f"callee_{n:03d}"
    tests.append(custom_test(n, "variadic", "printf-style variadic",
        caller=(
            f"#include <stdio.h>\n#include <stdint.h>\n\n"
            f"extern int {fn}(const char *fmt, ...);\n\n"
            f"int main(void) {{\n"
            f"    int r = {fn}(\"test\", 100, 200.0, 300L);\n"
            f"    if (r != 0) {{ fprintf(stderr, \"FAIL {fn}\\n\"); return 1; }}\n"
            f"    printf(\"PASS {fn}\\n\");\n    return 0;\n}}\n"
        ),
        callee=(
            f"#include <stdio.h>\n#include <stdarg.h>\n#include <stdint.h>\n\n"
            f"int {fn}(const char *fmt, ...) {{\n"
            f"    va_list ap;\n    va_start(ap, fmt);\n    int errors = 0;\n"
            f"    int v1 = va_arg(ap, int);\n"
            f"    if (v1 != 100) errors++;\n"
            f"    double v2 = va_arg(ap, double);\n"
            f"    if (v2 != 200.0) errors++;\n"
            f"    long v3 = va_arg(ap, long);\n"
            f"    if (v3 != 300L) errors++;\n"
            f"    va_end(ap);\n    return errors;\n}}\n"
        ),
    ))

    n += 1
    fn = f"callee_{n:03d}"
    tests.append(custom_test(n, "variadic", "many variadic doubles",
        caller=(
            f"#include <stdio.h>\n#include <stdint.h>\n\n"
            f"extern int {fn}(int count, ...);\n\n"
            f"int main(void) {{\n"
            f"    int r = {fn}(10, 1.0, 2.0, 3.0, 4.0, 5.0,"
            f" 6.0, 7.0, 8.0, 9.0, 10.0);\n"
            f"    if (r != 0) {{ fprintf(stderr, \"FAIL {fn}\\n\"); return 1; }}\n"
            f"    printf(\"PASS {fn}\\n\");\n    return 0;\n}}\n"
        ),
        callee=(
            f"#include <stdio.h>\n#include <stdarg.h>\n#include <stdint.h>\n\n"
            f"int {fn}(int count, ...) {{\n"
            f"    va_list ap;\n    va_start(ap, count);\n    int errors = 0;\n"
            f"    for (int i = 0; i < count; i++) {{\n"
            f"        double v = va_arg(ap, double);\n"
            f"        if (v != (double)(i + 1)) errors++;\n"
            f"    }}\n    va_end(ap);\n    return errors;\n}}\n"
        ),
    ))

    # ================================================================
    # SPECIAL TYPE TESTS
    # ================================================================

    # __int128 parameter
    n += 1
    fn = f"callee_{n:03d}"
    tests.append(custom_test(n, "special_types", "__int128 parameter",
        caller=(
            f"#include <stdio.h>\n#include <stdint.h>\n\n"
            f"extern int {fn}(__int128 a);\n\n"
            f"int main(void) {{\n"
            f"    __int128 val = ((__int128)(uint64_t)0x123456789ABCDEF0ULL << 64)\n"
            f"                | (uint64_t)0xFEDCBA9876543210ULL;\n"
            f"    int r = {fn}(val);\n"
            f"    if (r != 0) {{ fprintf(stderr, \"FAIL {fn}\\n\"); return 1; }}\n"
            f"    printf(\"PASS {fn}\\n\");\n    return 0;\n}}\n"
        ),
        callee=(
            f"#include <stdio.h>\n#include <stdint.h>\n\n"
            f"int {fn}(__int128 a) {{\n"
            f"    int errors = 0;\n"
            f"    __int128 expected = ((__int128)(uint64_t)0x123456789ABCDEF0ULL << 64)\n"
            f"                      | (uint64_t)0xFEDCBA9876543210ULL;\n"
            f"    if (a != expected) errors++;\n"
            f"    return errors;\n}}\n"
        ),
    ))

    # _Complex float
    n += 1
    fn = f"callee_{n:03d}"
    tests.append(custom_test(n, "special_types", "_Complex float parameter",
        caller=(
            f"#include <stdio.h>\n#include <complex.h>\n\n"
            f"extern int {fn}(float _Complex a);\n\n"
            f"int main(void) {{\n"
            f"    float _Complex val = 1.0f + 2.0f * I;\n"
            f"    int r = {fn}(val);\n"
            f"    if (r != 0) {{ fprintf(stderr, \"FAIL {fn}\\n\"); return 1; }}\n"
            f"    printf(\"PASS {fn}\\n\");\n    return 0;\n}}\n"
        ),
        callee=(
            f"#include <stdio.h>\n#include <complex.h>\n\n"
            f"int {fn}(float _Complex a) {{\n"
            f"    int errors = 0;\n"
            f"    if (crealf(a) != 1.0f) errors++;\n"
            f"    if (cimagf(a) != 2.0f) errors++;\n"
            f"    return errors;\n}}\n"
        ),
    ))

    # _Complex double
    n += 1
    fn = f"callee_{n:03d}"
    tests.append(custom_test(n, "special_types", "_Complex double parameter",
        caller=(
            f"#include <stdio.h>\n#include <complex.h>\n\n"
            f"extern int {fn}(double _Complex a);\n\n"
            f"int main(void) {{\n"
            f"    double _Complex val = 3.0 + 4.0 * I;\n"
            f"    int r = {fn}(val);\n"
            f"    if (r != 0) {{ fprintf(stderr, \"FAIL {fn}\\n\"); return 1; }}\n"
            f"    printf(\"PASS {fn}\\n\");\n    return 0;\n}}\n"
        ),
        callee=(
            f"#include <stdio.h>\n#include <complex.h>\n\n"
            f"int {fn}(double _Complex a) {{\n"
            f"    int errors = 0;\n"
            f"    if (creal(a) != 3.0) errors++;\n"
            f"    if (cimag(a) != 4.0) errors++;\n"
            f"    return errors;\n}}\n"
        ),
    ))

    # long double (X87 class)
    n += 1
    fn = f"callee_{n:03d}"
    tests.append(custom_test(n, "special_types", "long double parameter",
        caller=(
            f"#include <stdio.h>\n\n"
            f"extern int {fn}(long double a);\n\n"
            f"int main(void) {{\n"
            f"    int r = {fn}(1.5L);\n"
            f"    if (r != 0) {{ fprintf(stderr, \"FAIL {fn}\\n\"); return 1; }}\n"
            f"    printf(\"PASS {fn}\\n\");\n    return 0;\n}}\n"
        ),
        callee=(
            f"#include <stdio.h>\n\n"
            f"int {fn}(long double a) {{\n"
            f"    int errors = 0;\n"
            f"    if (a != 1.5L) errors++;\n"
            f"    return errors;\n}}\n"
        ),
    ))

    # __int128 return value
    n += 1
    fn = f"callee_{n:03d}"
    tests.append(custom_test(n, "special_types", "__int128 return value",
        caller=(
            f"#include <stdio.h>\n#include <stdint.h>\n\n"
            f"extern __int128 {fn}(void);\n\n"
            f"int main(void) {{\n"
            f"    __int128 r = {fn}();\n"
            f"    __int128 expected = ((__int128)(uint64_t)0xAAAAAAAABBBBBBBBULL << 64)\n"
            f"                      | (uint64_t)0xCCCCCCCCDDDDDDDDULL;\n"
            f"    if (r != expected) {{ fprintf(stderr, \"FAIL {fn}\\n\"); return 1; }}\n"
            f"    printf(\"PASS {fn}\\n\");\n    return 0;\n}}\n"
        ),
        callee=(
            f"#include <stdio.h>\n#include <stdint.h>\n\n"
            f"__int128 {fn}(void) {{\n"
            f"    __int128 r = ((__int128)(uint64_t)0xAAAAAAAABBBBBBBBULL << 64)\n"
            f"              | (uint64_t)0xCCCCCCCCDDDDDDDDULL;\n"
            f"    return r;\n}}\n"
        ),
    ))

    print(f"Total tests generated: {n}")
    return tests


# --- File I/O ---

def write_tests(tests):
    for d in [GEN, HDR, BLD, RES]:
        d.mkdir(parents=True, exist_ok=True)
    for t in tests:
        (GEN / f"caller_{t.num:03d}.c").write_text(t.caller)
        (GEN / f"callee_{t.num:03d}.c").write_text(t.callee)
        if t.header:
            (HDR / f"types_{t.num:03d}.h").write_text(t.header)


# --- Compilation and execution ---

def compile_and_run(tests):
    results = []
    for t in tests:
        r = {
            "test_id": t.test_id,
            "scenario": t.scenario,
            "description": t.desc,
        }
        for cc_caller, cc_callee in COMBOS:
            combo = f"{cc_caller}_{cc_callee}"
            bd = BLD / combo / f"test_{t.num:03d}"
            bd.mkdir(parents=True, exist_ok=True)

            caller_src = str(GEN / f"caller_{t.num:03d}.c")
            callee_src = str(GEN / f"callee_{t.num:03d}.c")
            caller_obj = str(bd / "caller.o")
            callee_obj = str(bd / "callee.o")
            binary = str(bd / "test")

            inc = ["-I", str(HDR)]

            # Compile caller
            p1 = subprocess.run(
                [cc_caller, "-c", "-Wall", "-Wno-unused-parameter"] + inc +
                [caller_src, "-o", caller_obj],
                capture_output=True, timeout=30,
            )
            if p1.returncode != 0:
                print(f"  COMPILE ERROR {combo} caller {t.test_id}: "
                      f"{p1.stderr.decode()[:200]}", file=sys.stderr)
                r[combo] = "error"
                continue

            # Compile callee
            p2 = subprocess.run(
                [cc_callee, "-c", "-Wall", "-Wno-unused-parameter"] + inc +
                [callee_src, "-o", callee_obj],
                capture_output=True, timeout=30,
            )
            if p2.returncode != 0:
                print(f"  COMPILE ERROR {combo} callee {t.test_id}: "
                      f"{p2.stderr.decode()[:200]}", file=sys.stderr)
                r[combo] = "error"
                continue

            # Link
            p3 = subprocess.run(
                [cc_caller, caller_obj, callee_obj, "-o", binary, "-lm"],
                capture_output=True, timeout=30,
            )
            if p3.returncode != 0:
                print(f"  LINK ERROR {combo} {t.test_id}: "
                      f"{p3.stderr.decode()[:200]}", file=sys.stderr)
                r[combo] = "error"
                continue

            # Run
            try:
                p4 = subprocess.run(
                    [binary], capture_output=True, timeout=10,
                )
                if p4.returncode == 0:
                    r[combo] = "pass"
                else:
                    print(f"  FAIL {combo} {t.test_id}: "
                          f"{p4.stderr.decode()[:200]}", file=sys.stderr)
                    r[combo] = "fail"
            except subprocess.TimeoutExpired:
                r[combo] = "error"

        results.append(r)
    return results


# --- Report generation ---

def gen_summary(tests, results):
    scenarios = sorted(set(t.scenario for t in tests))
    totals = {}
    for cc1, cc2 in COMBOS:
        combo = f"{cc1}_{cc2}"
        totals[combo] = {
            "pass": sum(1 for r in results if r.get(combo) == "pass"),
            "fail": sum(1 for r in results if r.get(combo) == "fail"),
            "error": sum(1 for r in results if r.get(combo) == "error"),
        }

    summary = {
        "total_tests": len(tests),
        "scenarios": scenarios,
        "results": totals,
        "test_details": results,
    }
    (RES / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def gen_tap(results):
    lines = ["TAP version 13", f"1..{len(results) * 4}"]
    n = 0
    for r in results:
        for cc1, cc2 in COMBOS:
            combo = f"{cc1}_{cc2}"
            n += 1
            status = r.get(combo, "error")
            prefix = "ok" if status == "pass" else "not ok"
            lines.append(f"{prefix} {n} - {r['test_id']} ({combo})")
    (RES / "report.tap").write_text("\n".join(lines) + "\n")


# --- Main ---

def main():
    tests = gen_all()
    write_tests(tests)

    print("Compiling and running tests...")
    results = compile_and_run(tests)

    summary = gen_summary(tests, results)
    gen_tap(results)

    print("\n=== Summary ===")
    for cc1, cc2 in COMBOS:
        combo = f"{cc1}_{cc2}"
        r = summary["results"][combo]
        print(f"  {combo}: {r['pass']} pass, {r['fail']} fail, {r['error']} error")
    print(f"  Total tests: {summary['total_tests']}")


if __name__ == "__main__":
    main()
