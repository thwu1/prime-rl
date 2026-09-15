#!/usr/bin/env python3
"""Derive and generate a correctly-rounded cbrtf implementation.

Computes algorithm parameters from IEEE 754 first principles:
1. The bit-level initial approximation constant for cube root
2. The required number of Newton-Raphson refinement iterations
3. The subnormal normalization compensation factor

Then generates the complete C implementation and verifies it.

"""

import struct
import subprocess
import sys


def compute_bithack_constant():
    """Compute the additive constant for the cube root bit-hack.

    For IEEE 754 double: bits(x) = (biased_exp) * 2^52 + mantissa_bits
    Since cbrt(2^e * m) = 2^(e/3) * cbrt(m), we have approximately:
        bits(cbrt(x)) ~ bits(x) / 3 + C
    where C = 2 * bias * 2^52 / 3, with bias = 1023 for double.
    """
    bias = 1023
    C = (2 * bias * (1 << 52)) // 3
    return C


def verify_bithack(C):
    """Verify the bit-hack constant produces reasonable initial approximations."""
    test_cases = [
        (1.0, 1.0, 0.1),
        (8.0, 2.0, 0.2),
        (27.0, 3.0, 0.3),
    ]
    for x_val, expected, tol in test_cases:
        bits_x = struct.unpack('Q', struct.pack('d', x_val))[0]
        approx_bits = bits_x // 3 + C
        approx = struct.unpack('d', struct.pack('Q', approx_bits))[0]
        assert abs(approx - expected) < tol, (
            f"cbrt({x_val}) approx = {approx}, expected ~{expected}"
        )
    return True


def determine_iterations():
    """Determine minimum Newton-Raphson iterations for correct float rounding.

    The bit-hack yields ~5 bits of accuracy. Each Newton-Raphson iteration
    for cube root (y = (2y + x/y^2)/3) roughly doubles the number of
    correct bits (quadratic convergence).

    For correct rounding of binary32 (24-bit mantissa), we need the double
    result accurate to ~53 bits, because the worst-case hardness for cbrt
    of binary32 values can require up to ~29 extra bits beyond the mantissa.
    """
    accuracy_bits = 5   # from bit hack
    target_bits = 53    # full double precision
    iters = 0
    progression = [accuracy_bits]
    while accuracy_bits < target_bits:
        accuracy_bits = min(accuracy_bits * 2, target_bits)
        iters += 1
        progression.append(accuracy_bits)
    return iters, progression


def subnormal_params():
    """Compute subnormal normalization parameters.

    IEEE 754 binary32 subnormals have biased exponent 0 and mantissa
    bits [22:0]. The mantissa has 23 bits, so multiplying by 2^24
    shifts any subnormal into the normal range (the smallest subnormal
    2^-149 becomes 2^-149 * 2^24 = 2^-125, which has biased exponent 2).

    The exponent adjustment must exactly cancel the scaling: -24.
    """
    scale_exp = 24
    adj = -scale_exp
    return scale_exp, adj


def generate_implementation(bithack_const, nr_iters, scale_exp, subnorm_adj):
    """Generate the complete C implementation of cr_cbrtf."""

    nr_block = "\n".join(
        "    y2 = y * y; y = (2.0 * y + mp / y2) / 3.0;"
        for _ in range(nr_iters)
    )

    code = (
        '/* Correctly-rounded cube root for IEEE 754 binary32 (float).\n'
        ' *\n'
        ' * Algorithm:\n'
        ' *   1. Handle special cases (+-0, +-Inf, NaN).\n'
        f' *   2. Normalize subnormal inputs by scaling by 2^{scale_exp}.\n'
        ' *   3. Decompose the exponent e = 3*q + r, r in {0, 1, 2}.\n'
        ' *   4. Reduce to computing cbrt(m * 2^r), m in [1,2), via mantissa extraction.\n'
        ' *   5. Obtain initial estimate using the double-precision bit-hack.\n'
        f' *   6. Refine with {nr_iters} Newton-Raphson iterations in double precision.\n'
        ' *   7. Scale by 2^q and convert to float.\n'
        ' *\n'
        ' */\n'
        '\n'
        '#include <stdint.h>\n'
        '#include "cbrtf.h"\n'
        '\n'
        'typedef union { float f; uint32_t u; } b32u32_u;\n'
        'typedef union { double f; uint64_t u; } b64u64_u;\n'
        '\n'
        'float cr_cbrtf(float x) {\n'
        '    b32u32_u xi = {.f = x};\n'
        '    uint32_t hx = xi.u;\n'
        '    uint32_t sign = hx & 0x80000000u;\n'
        '    hx &= 0x7fffffffu;\n'
        '\n'
        '    /* +-0 -> return with sign preserved */\n'
        '    if (hx == 0u)\n'
        '        return x;\n'
        '\n'
        '    /* NaN or Inf: x + x returns Inf unchanged and quiets sNaN */\n'
        '    if (hx >= 0x7f800000u)\n'
        '        return x + x;\n'
        '\n'
        '    /* Convert |x| to double, handling subnormals */\n'
        '    double xd;\n'
        '    int e_adj = 0;\n'
        '    if (hx < 0x00800000u) {\n'
        f'        /* Subnormal: multiply by 2^{scale_exp} to normalise */\n'
        '        b32u32_u tmp = {.u = hx};\n'
        f'        xd = (double)tmp.f * 0x1p{scale_exp};\n'
        f'        e_adj = {subnorm_adj};\n'
        '    } else {\n'
        '        b32u32_u tmp = {.u = hx};\n'
        '        xd = (double)tmp.f;\n'
        '    }\n'
        '\n'
        '    /* Extract the biased exponent from the double representation */\n'
        '    b64u64_u du = {.f = xd};\n'
        '    int biased = (int)(du.u >> 52);\n'
        '    int e = biased - 1023 + e_adj;\n'
        '\n'
        '    /* Euclidean division: e = 3*q + r, 0 <= r <= 2 */\n'
        '    int q, r;\n'
        '    if (e >= 0) {\n'
        '        q = e / 3;\n'
        '        r = e % 3;\n'
        '    } else {\n'
        '        q = (e - 2) / 3;\n'
        '        r = e - 3 * q;\n'
        '    }\n'
        '\n'
        '    /* Set the double exponent to 1023 + r, keeping the mantissa.\n'
        '     * This yields mp = m * 2^r where m in [1, 2), so mp in [1, 8). */\n'
        '    du.u = (du.u & 0x000fffffffffffffULL) | ((uint64_t)(1023 + r) << 52);\n'
        '    double mp = du.f;\n'
        '\n'
        '    /* Initial approximation via the bit-level identity */\n'
        '    b64u64_u yi = {.f = mp};\n'
        f'    yi.u = yi.u / 3 + 0x{bithack_const:016X}ULL;\n'
        '    double y = yi.f;\n'
        '\n'
        f'    /* {nr_iters} Newton-Raphson iterations:\n'
        '     *   y_{{n+1}} = (2*y_n + mp / y_n^2) / 3 */\n'
        '    double y2;\n'
        f'{nr_block}\n'
        '\n'
        '    /* Scale by 2^q by adding q to the double\'s biased exponent */\n'
        '    b64u64_u res = {.f = y};\n'
        '    res.u += (int64_t)q << 52;\n'
        '\n'
        '    /* Convert to float (round-to-nearest-even) and restore sign */\n'
        '    float rf = (float)res.f;\n'
        '    b32u32_u out = {.f = rf};\n'
        '    out.u |= sign;\n'
        '    return out.f;\n'
        '}\n'
    )
    return code


def main():
    print("=== Deriving correctly-rounded cbrtf implementation ===\n")

    # Step 1: Compute bit-hack constant
    C = compute_bithack_constant()
    print(f"Bit-hack constant: 0x{C:016X}")
    verify_bithack(C)
    print("  Verified: initial approximations are within tolerance\n")

    # Step 2: Determine Newton-Raphson iteration count
    nr_iters, progression = determine_iterations()
    print(f"Newton-Raphson iterations needed: {nr_iters}")
    print(f"  Precision progression: {' -> '.join(str(b) for b in progression)} bits\n")

    # Step 3: Subnormal normalization parameters
    scale_exp, adj = subnormal_params()
    print(f"Subnormal scale: 2^{scale_exp}, exponent adjustment: {adj}\n")

    # Step 4: Generate the implementation
    code = generate_implementation(C, nr_iters, scale_exp, adj)
    with open("/app/cbrtf.c", "w") as f:
        f.write(code)
    print("Written /app/cbrtf.c\n")

    # Step 5: Build and run the spot check
    print("=== Building ===")
    subprocess.run(["make", "clean"], cwd="/app", capture_output=True)
    result = subprocess.run(
        ["make", "spot_check"], cwd="/app", capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Build FAILED:\n{result.stderr}")
        sys.exit(1)
    print("Build OK\n")

    print("=== Running spot check ===")
    result = subprocess.run(
        ["./spot_check"], cwd="/app", capture_output=True, text=True, timeout=180
    )
    print(result.stdout)
    if result.returncode != 0:
        print("Spot check FAILED")
        sys.exit(1)
    print("Spot check PASSED")

    # Step 6: Build and run a subnormal verification
    print("\n=== Verifying subnormals ===")
    subnorm_test = r'''
#include <stdio.h>
#include <stdint.h>
#include <math.h>
#include <mpfr.h>
#include "cbrtf.h"

typedef union { float f; uint32_t u; } fu;

int main(void) {
    mpfr_t mp;
    mpfr_init2(mp, 80);
    int total = 0, fail = 0;
    for (uint32_t bits = 1; bits < 0x00800000u; bits += 31) {
        fu u = {.u = bits};
        float got = cr_cbrtf(u.f);
        mpfr_set_flt(mp, u.f, MPFR_RNDN);
        mpfr_cbrt(mp, mp, MPFR_RNDN);
        float expected = mpfr_get_flt(mp, MPFR_RNDN);
        fu g = {.f = got}, e = {.f = expected};
        total++;
        if (g.u != e.u) {
            fail++;
            if (fail <= 5)
                printf("FAIL subnormal: 0x%08x got 0x%08x expected 0x%08x\n",
                       u.u, g.u, e.u);
        }
        u.u |= 0x80000000u;
        got = cr_cbrtf(u.f);
        mpfr_set_flt(mp, u.f, MPFR_RNDN);
        mpfr_cbrt(mp, mp, MPFR_RNDN);
        expected = mpfr_get_flt(mp, MPFR_RNDN);
        g.f = got; e.f = expected;
        total++;
        if (g.u != e.u) {
            fail++;
            if (fail <= 5)
                printf("FAIL neg subnormal: 0x%08x got 0x%08x expected 0x%08x\n",
                       u.u, g.u, e.u);
        }
    }
    mpfr_clear(mp);
    printf("Subnormal test: %d/%d passed (%d failures)\n",
           total - fail, total, fail);
    return fail > 0 ? 1 : 0;
}
'''
    with open("/tmp/test_subnormals.c", "w") as f:
        f.write(subnorm_test)

    result = subprocess.run(
        ["gcc", "-O2", "-std=c11", "-I/app", "-o", "/tmp/test_subnormals",
         "/tmp/test_subnormals.c", "/app/cbrtf.c", "-lmpfr", "-lgmp", "-lm"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Subnormal test build FAILED:\n{result.stderr}")
        sys.exit(1)

    result = subprocess.run(
        ["/tmp/test_subnormals"], capture_output=True, text=True, timeout=60
    )
    print(result.stdout)
    if result.returncode != 0:
        print("Subnormal test FAILED")
        sys.exit(1)
    print("All verifications PASSED")


if __name__ == "__main__":
    main()
