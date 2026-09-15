"""
Tests for the fixed-point signal processing pipeline.
Verifies basic Q15/Q31 operations and pipeline output against
precomputed reference values.

"""

import subprocess
import os
import tempfile
import textwrap
import pytest

# ---------------------------------------------------------------------------
# Python reference for Q15/Q31 basic operations (ITU-T specification values)
# ---------------------------------------------------------------------------

MAX_16 = 32767
MIN_16 = -32768
MAX_32 = 2147483647
MIN_32 = -2147483648

M_LPC = 10


def _to_w16(val):
    val = int(val) & 0xFFFF
    return val - 0x10000 if val >= 0x8000 else val


def _saturate(L_var1):
    if L_var1 > 0x7FFF:
        return MAX_16
    elif L_var1 < -32768:
        return MIN_16
    v = int(L_var1) & 0xFFFF
    return v - 0x10000 if v >= 0x8000 else v


def ref_add(var1, var2):
    return _saturate(var1 + var2)


def ref_sub(var1, var2):
    return _saturate(var1 - var2)


def ref_abs_s(var1):
    if var1 == MIN_16:
        return MAX_16
    return abs(var1)


def ref_extract_h(L_var1):
    v = (L_var1 >> 16) & 0xFFFF
    return v - 0x10000 if v >= 0x8000 else v


def ref_extract_l(L_var1):
    v = L_var1 & 0xFFFF
    return v - 0x10000 if v >= 0x8000 else v


def ref_L_deposit_h(var1):
    r = (var1 & 0xFFFF) << 16
    if r >= 0x80000000:
        r -= 0x100000000
    return r


def ref_L_deposit_l(var1):
    if var1 < 0:
        return var1
    return var1


def ref_L_add(L_var1, L_var2):
    s = L_var1 + L_var2
    if s > MAX_32:
        return MAX_32
    if s < MIN_32:
        return MIN_32
    return s


def ref_L_sub(L_var1, L_var2):
    s = L_var1 - L_var2
    if s > MAX_32:
        return MAX_32
    if s < MIN_32:
        return MIN_32
    return s


def ref_L_negate(L_var1):
    if L_var1 == MIN_32:
        return MAX_32
    return -L_var1


def ref_L_abs(L_var1):
    if L_var1 == MIN_32:
        return MAX_32
    return abs(L_var1)


def ref_mult(var1, var2):
    p = var1 * var2
    r = p >> 15
    return _saturate(r)


def ref_L_mult(var1, var2):
    p = var1 * var2
    if p == 0x40000000:
        return MAX_32
    r = p * 2
    if r > MAX_32:
        return MAX_32
    if r < MIN_32:
        return MIN_32
    return r


def ref_L_mac(L_var3, var1, var2):
    return ref_L_add(L_var3, ref_L_mult(var1, var2))


def ref_L_msu(L_var3, var1, var2):
    return ref_L_sub(L_var3, ref_L_mult(var1, var2))


def ref_round_fx(L_var1):
    r = ref_L_add(L_var1, 0x00008000)
    return ref_extract_h(r)


def ref_shr(var1, var2):
    if var2 < 0:
        return ref_shl(var1, -var2)
    if var2 >= 15:
        return -1 if var1 < 0 else 0
    if var1 < 0:
        return ~((~var1) >> var2)
    return var1 >> var2


def ref_shl(var1, var2):
    if var2 < 0:
        return ref_shr(var1, -var2)
    result = var1 * (1 << var2)
    if (var2 > 15 and var1 != 0) or result != _to_w16(result):
        return MAX_16 if var1 > 0 else MIN_16
    return _to_w16(result)


def ref_L_shr(L_var1, var2):
    if var2 < 0:
        return ref_L_shl(L_var1, -var2)
    if var2 >= 31:
        return -1 if L_var1 < 0 else 0
    if L_var1 < 0:
        return ~((~L_var1) >> var2)
    return L_var1 >> var2


def ref_L_shl(L_var1, var2):
    if var2 <= 0:
        return ref_L_shr(L_var1, -var2)
    for _ in range(var2):
        if L_var1 > 0x3FFFFFFF:
            return MAX_32
        if L_var1 < -0x40000000:
            return MIN_32
        L_var1 *= 2
    return L_var1


def ref_norm_l(L_var1):
    if L_var1 == 0:
        return 0
    if L_var1 == -1:
        return 31
    v = L_var1
    if v < 0:
        v = ~v
    out = 0
    while v < 0x40000000:
        v <<= 1
        out += 1
    return out


def ref_Mpy_32(hi1, lo1, hi2, lo2):
    L_32 = ref_L_mult(hi1, hi2)
    L_32 = ref_L_mac(L_32, ref_mult(hi1, lo2), 1)
    L_32 = ref_L_mac(L_32, ref_mult(lo1, hi2), 1)
    return L_32


# ---------------------------------------------------------------------------
# Precomputed expected pipeline outputs (verified from reference)
# ---------------------------------------------------------------------------

PIPELINE_VECTORS = {
    "trivial": {
        "Rh": [16384, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "Rl": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "A": [4096, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "rc": [0, 0, 0, 0],
    },
    "single_reflection": {
        "Rh": [16384, 8192, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "Rl": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "A": [4096, -3724, 3351, -2979, 2607, -2234, 1862, -1489, 1117, -745, 372],
        "rc": [-16384, 10923, -8192, 6554],
    },
    "speech_like": {
        "Rh": [16384, 14000, 10000, 6000, 3000, 1500, 800, 400, 150, 40, 8],
        "Rl": [0, 100, 200, 150, 50, 30, 10, 5, 2, 0, 0],
        "A": [4096, -5002, 1505, 289, 452, -809, 141, 191, 88, -221, 80],
        "rc": [-28000, 14548, 1135, -1723],
    },
    "moderate": {
        "Rh": [20000, 12000, 7000, 4000, 2500, 1600, 1000, 600, 350, 180, 80],
        "Rl": [0, 500, 300, 200, 100, 50, 25, 10, 5, 2, 1],
        "A": [4096, -2496, 48, 68, -64, -15, 3, 4, -2, 6, 3],
        "rc": [-19661, 512, 200, -562],
    },
    "high_pitch": {
        "Rh": [18000, 10000, 5000, 3000, 4000, 5500, 4500, 3000, 1500, 600, 200],
        "Rl": [0, 200, 400, 100, 300, 250, 150, 80, 40, 15, 5],
        "A": [4096, -2227, 195, 177, -387, -741, 69, -82, 32, 122, 228],
        "rc": [-18204, 1463, -1437, -5723],
    },
    "near_unstable": {
        "Rh": [16384, 16000, 15500, 15000, 14500, 14000, 13500, 13000, 12500, 12000, 11500],
        "Rl": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "A": [4096, -4657, 720, -111, 17, -3, 0, 0, 2, -11, 72],
        "rc": [-32000, 5397, -242, 639],
    },
    "asymmetric_dpf": {
        "Rh": [16384, 12000, 8000, 4000, 2000, 1000, 500, 250, 125, 60, 30],
        "Rl": [0, 8000, 4000, 6000, 3000, 7000, 2000, 5000, 1000, 3000, 500],
        "A": [4096, -3290, -131, 946, -251, -184, 125, 12, -38, 11, 3],
        "rc": [-24000, 3406, 5327, -2527],
    },
}


# ---------------------------------------------------------------------------
# Helper: compile and run the C pipeline
# ---------------------------------------------------------------------------

def compile_c():
    r = subprocess.run(["make", "-C", "/app", "clean"], capture_output=True)
    r = subprocess.run(["make", "-C", "/app"], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.fail(f"make failed:\nstdout: {r.stdout}\nstderr: {r.stderr}")


def run_pipeline(Rh, Rl):
    """Run /app/pipeline with given autocorrelation DPF values."""
    inp = "\n".join(f"{Rh[i]} {Rl[i]}" for i in range(M_LPC + 1)) + "\n"
    r = subprocess.run(
        ["/app/pipeline"],
        input=inp,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if r.returncode != 0:
        pytest.fail(f"pipeline failed:\nstderr: {r.stderr}")
    lines = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
    if len(lines) != M_LPC + 1 + 4:
        pytest.fail(
            f"Expected {M_LPC + 5} output lines, got {len(lines)}:\n{r.stdout}"
        )
    A = [int(x) for x in lines[: M_LPC + 1]]
    rc = [int(x) for x in lines[M_LPC + 1 :]]
    return A, rc


def compile_and_run_harness(c_code):
    """Compile and run a small C harness linked with basicop + oper_32b."""
    with tempfile.NamedTemporaryFile(
        suffix=".c", dir="/app", delete=False, mode="w"
    ) as f:
        f.write(c_code)
        src = f.name
    try:
        exe = src.replace(".c", "")
        r = subprocess.run(
            [
                "gcc",
                "-Wall",
                "-O0",
                "-o",
                exe,
                src,
                "/app/basicop.c",
                "/app/oper_32b.c",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.fail(f"Harness compile failed:\n{r.stderr}")
        r = subprocess.run([exe], capture_output=True, text=True, timeout=10)
        return r
    finally:
        for f in [src, src.replace(".c", "")]:
            if os.path.exists(f):
                os.unlink(f)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestBuild:
    def test_make_succeeds(self):
        compile_c()
        assert os.path.isfile("/app/pipeline"), "pipeline binary not found"
        assert os.path.isfile("/app/selftest"), "selftest binary not found"

    def test_selftest_passes(self):
        compile_c()
        r = subprocess.run(
            ["/app/selftest"], capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            pytest.fail(
                f"selftest failed (exit {r.returncode}):\n{r.stdout}\n{r.stderr}"
            )


class TestBasicOps:
    """Unit tests for Q15/Q31 basic operations edge cases."""

    def test_basic_ops_edge_cases(self):
        compile_c()
        harness = textwrap.dedent("""\
            #include <stdio.h>
            #include "basicop.h"
            #include "oper_32b.h"

            int main(void) {
                Word32 r32;
                Word16 r16;

                /* L_mult(-32768, -32768) must saturate to MAX_32 */
                r32 = L_mult((Word16)-32768, (Word16)-32768);
                printf("L_mult_mm=%ld\\n", (long)r32);

                /* round_fx edge cases */
                r16 = round_fx((Word32)0x12348000L);
                printf("round_1=%d\\n", (int)r16);

                r16 = round_fx((Word32)0x00018000L);
                printf("round_2=%d\\n", (int)r16);

                /* norm_l edge cases */
                r16 = norm_l((Word32)0x20000000L);
                printf("norm_l_1=%d\\n", (int)r16);

                r16 = norm_l((Word32)0x40000000L);
                printf("norm_l_2=%d\\n", (int)r16);

                r16 = norm_l((Word32)0x10000000L);
                printf("norm_l_3=%d\\n", (int)r16);

                r16 = norm_l((Word32)1);
                printf("norm_l_4=%d\\n", (int)r16);

                /* Mpy_32 cross-term check */
                r32 = Mpy_32((Word16)16384, (Word16)1000,
                             (Word16)16384, (Word16)2000);
                printf("mpy32_1=%ld\\n", (long)r32);

                /* Additional basic op checks */
                r32 = L_mult((Word16)16384, (Word16)16384);
                printf("L_mult_pp=%ld\\n", (long)r32);

                r16 = mult((Word16)16384, (Word16)16384);
                printf("mult_pp=%d\\n", (int)r16);

                r16 = add((Word16)32767, (Word16)1);
                printf("add_sat=%d\\n", (int)r16);

                r16 = sub((Word16)-32768, (Word16)1);
                printf("sub_sat=%d\\n", (int)r16);

                return 0;
            }
        """)
        r = compile_and_run_harness(harness)
        if r.returncode != 0:
            pytest.fail(f"Harness crashed:\nstderr: {r.stderr}")

        results = {}
        for line in r.stdout.strip().split("\n"):
            if "=" in line:
                k, v = line.strip().split("=")
                results[k] = int(v)

        # Verify against reference
        assert results["L_mult_mm"] == MAX_32, \
            f"L_mult(-32768,-32768) = {results['L_mult_mm']}, expected {MAX_32}"

        assert results["round_1"] == ref_round_fx(0x12348000), \
            f"round_fx(0x12348000) = {results['round_1']}, expected {ref_round_fx(0x12348000)}"

        assert results["round_2"] == ref_round_fx(0x00018000), \
            f"round_fx(0x00018000) = {results['round_2']}, expected {ref_round_fx(0x00018000)}"

        assert results["norm_l_1"] == ref_norm_l(0x20000000), \
            f"norm_l(0x20000000) = {results['norm_l_1']}, expected {ref_norm_l(0x20000000)}"

        assert results["norm_l_2"] == ref_norm_l(0x40000000), \
            f"norm_l(0x40000000) = {results['norm_l_2']}, expected {ref_norm_l(0x40000000)}"

        assert results["norm_l_3"] == ref_norm_l(0x10000000), \
            f"norm_l(0x10000000) = {results['norm_l_3']}, expected {ref_norm_l(0x10000000)}"

        assert results["norm_l_4"] == ref_norm_l(1), \
            f"norm_l(1) = {results['norm_l_4']}, expected {ref_norm_l(1)}"

        expected_mpy32 = ref_Mpy_32(16384, 1000, 16384, 2000)
        assert results["mpy32_1"] == expected_mpy32, \
            f"Mpy_32(16384,1000,16384,2000) = {results['mpy32_1']}, expected {expected_mpy32}"

        assert results["L_mult_pp"] == ref_L_mult(16384, 16384), \
            f"L_mult(16384,16384) = {results['L_mult_pp']}, expected {ref_L_mult(16384, 16384)}"

        assert results["mult_pp"] == ref_mult(16384, 16384), \
            f"mult(16384,16384) = {results['mult_pp']}, expected {ref_mult(16384, 16384)}"

        assert results["add_sat"] == MAX_16, \
            f"add(32767,1) = {results['add_sat']}, expected {MAX_16}"

        assert results["sub_sat"] == MIN_16, \
            f"sub(-32768,1) = {results['sub_sat']}, expected {MIN_16}"


class TestPipeline:
    """Integration tests: pipeline output vs precomputed reference values."""

    @pytest.fixture(autouse=True)
    def _compile(self):
        compile_c()

    @pytest.mark.parametrize("name", list(PIPELINE_VECTORS.keys()))
    def test_pipeline_output(self, name):
        vec = PIPELINE_VECTORS[name]
        A, rc = run_pipeline(vec["Rh"], vec["Rl"])
        assert A == vec["A"], \
            f"[{name}] A mismatch:\n  got      {A}\n  expected {vec['A']}"
        assert rc == vec["rc"], \
            f"[{name}] rc mismatch:\n  got      {rc}\n  expected {vec['rc']}"
