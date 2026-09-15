
import json
import os
import pytest
import math


# ---------------------------------------------------------------------------
# Reference implementations — translated directly from the SystemVerilog
# ---------------------------------------------------------------------------

def ref_divu_int(a, b, width):
    """Bit-accurate reference for divu_int.sv."""
    mask_w = (1 << width) - 1
    mask_wp1 = (1 << (width + 1)) - 1
    mask_comb = (1 << (2 * width + 1)) - 1

    if b == 0:
        return {"quotient": 0, "remainder": 0, "dbz": True}

    a = a & mask_w
    b1 = b & mask_w

    # {acc, quo} <= {{WIDTH{1'b0}}, a, 1'b0}
    init = (a << 1) & mask_comb
    acc = (init >> width) & mask_wp1
    quo = init & mask_w

    for i in range(width):
        # combinational: compute acc_next, quo_next
        if acc >= b1:
            acc_sub = (acc - b1) & mask_wp1
            concat = ((acc_sub & mask_w) << (width + 1)) | (quo << 1) | 1
            concat &= mask_comb
        else:
            concat = ((acc << width) | quo) << 1
            concat &= mask_comb

        acc_next = (concat >> width) & mask_wp1
        quo_next = concat & mask_w

        if i == width - 1:
            return {
                "quotient": quo_next & mask_w,
                "remainder": (acc_next >> 1) & mask_w,
                "dbz": False,
            }
        acc, quo = acc_next, quo_next

    raise RuntimeError("unreachable")


def ref_sqrt_int(rad, width):
    """Bit-accurate reference for sqrt_int.sv."""
    mask_w = (1 << width) - 1
    mask_wp2 = (1 << (width + 2)) - 1
    iterations = width >> 1

    q = 0
    init_val = (rad & mask_w) << 2
    ac = (init_val >> width) & mask_wp2
    x = init_val & mask_w

    for i in range(iterations):
        # test_res = ac - {q, 2'b01}
        q_cat = ((q & mask_w) << 2) | 1
        test_res = (ac - q_cat) & mask_wp2

        if (test_res >> (width + 1)) == 0:  # MSB == 0 → non-negative
            tr_low = test_res & mask_w
            concat = (tr_low << (width + 2)) | (x << 2)
            ac_next = (concat >> width) & mask_wp2
            x_next = concat & mask_w
            q_next = ((q << 1) | 1) & mask_w
        else:
            ac_low = ac & mask_w
            concat = (ac_low << (width + 2)) | (x << 2)
            ac_next = (concat >> width) & mask_wp2
            x_next = concat & mask_w
            q_next = (q << 1) & mask_w

        if i == iterations - 1:
            return {
                "root": q_next & mask_w,
                "remainder": (ac_next >> 2) & mask_w,
            }
        ac, x, q = ac_next, x_next, q_next

    raise RuntimeError("unreachable")


def ref_divu_fp(a, b, width, fbits):
    """Bit-accurate reference for divu.sv."""
    mask_w = (1 << width) - 1
    mask_wp1 = (1 << (width + 1)) - 1
    mask_comb = (1 << (2 * width + 1)) - 1
    iterations = width + fbits
    fbitsw = max(fbits, 1)

    if b == 0:
        return {"quotient": 0, "dbz": True, "ovf": False}

    a = a & mask_w
    b1 = b & mask_w

    init = (a << 1) & mask_comb
    acc = (init >> width) & mask_wp1
    quo = init & mask_w

    for i in range(iterations):
        if acc >= b1:
            acc_sub = (acc - b1) & mask_wp1
            concat = ((acc_sub & mask_w) << (width + 1)) | (quo << 1) | 1
            concat &= mask_comb
        else:
            concat = ((acc << width) | quo) << 1
            concat &= mask_comb

        acc_next = (concat >> width) & mask_wp1
        quo_next = concat & mask_w

        if i == iterations - 1:
            return {"quotient": quo_next & mask_w, "dbz": False, "ovf": False}
        elif i == width - 1:
            if (quo_next >> (width - fbitsw)) != 0:
                return {"quotient": 0, "dbz": False, "ovf": True}

        acc, quo = acc_next, quo_next

    raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# Fixed-point helpers for Mandelbrot
# ---------------------------------------------------------------------------

FP_WIDTH = 25
FP_FBITS = 21
FP_MASK = (1 << FP_WIDTH) - 1
FP_FOUR = 4 << FP_FBITS  # 8388608


def fp_to_signed(v):
    v = v & FP_MASK
    if v >= (1 << (FP_WIDTH - 1)):
        return v - (1 << FP_WIDTH)
    return v


def fp_from_float(f):
    return int(f * (1 << FP_FBITS)) & FP_MASK


def fp_mul(a, b):
    sa = fp_to_signed(a)
    sb = fp_to_signed(b)
    product = sa * sb
    return (product >> FP_FBITS) & FP_MASK


def fp_add(a, b):
    return (a + b) & FP_MASK


def fp_sub(a, b):
    return (a - b) & FP_MASK


def ref_mandelbrot(cx, cy, max_iter=255):
    """Reference Mandelbrot using Q4.21 signed fixed-point."""
    x = 0
    y = 0
    x2 = 0
    y2 = 0

    for iteration in range(max_iter):
        sum_sq = fp_add(x2, y2)
        if fp_to_signed(sum_sq) > fp_to_signed(FP_FOUR):
            return iteration

        xy = fp_mul(x, y)
        two_xy = (xy << 1) & FP_MASK
        y_new = fp_add(two_xy, cy)
        x_new = fp_add(fp_sub(x2, y2), cx)

        x = x_new & FP_MASK
        y = y_new & FP_MASK
        x2 = fp_mul(x, x)
        y2 = fp_mul(y, y)

    return max_iter


# ---------------------------------------------------------------------------
# Test vectors (must match spec.md)
# ---------------------------------------------------------------------------

DIV_WIDTH = 32
DIV_TESTS = [
    (100, 7),
    (255, 16),
    (1, 1),
    (0, 42),
    (12345678, 9999),
    (999999999, 7),
    (4294967295, 65536),
    (100, 0),
]

SQRT_WIDTH = 32
SQRT_TESTS = [0, 1, 25, 144, 200, 1000000, 50000000, 4294967295]

DIVFP_WIDTH = 25
DIVFP_FBITS = 21
DIVFP_TESTS_REAL = [
    (7.0, 2.0),
    (10.0, 4.0),
    (15.0, 2.0),
    (1.0, 3.0),
    (1.0, 7.0),
]

MANDEL_X_REALS = [-2.0, -1.75, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5]
MANDEL_Y_REALS = [-1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
MANDEL_MAX_ITER = 255


# ---------------------------------------------------------------------------
# Sanity-check the reference against Python builtins
# ---------------------------------------------------------------------------

def test_reference_div_sanity():
    """Cross-check ref_divu_int against Python integer division."""
    for a, b in DIV_TESTS:
        ref = ref_divu_int(a, b, DIV_WIDTH)
        if b == 0:
            assert ref["dbz"] is True
        else:
            assert ref["quotient"] == a // b, f"div {a}/{b}"
            assert ref["remainder"] == a % b, f"rem {a}%{b}"


def test_reference_sqrt_sanity():
    """Cross-check ref_sqrt_int against math.isqrt."""
    for rad in SQRT_TESTS:
        ref = ref_sqrt_int(rad, SQRT_WIDTH)
        expected_root = math.isqrt(rad)
        assert ref["root"] == expected_root, f"sqrt({rad})"
        assert ref["remainder"] == rad - expected_root * expected_root, f"sqrt_rem({rad})"


def test_reference_divfp_sanity():
    """Cross-check ref_divu_fp for exact cases."""
    # 7.0 / 2.0 = 3.5
    a_fp = int(7.0 * (1 << DIVFP_FBITS))
    b_fp = int(2.0 * (1 << DIVFP_FBITS))
    ref = ref_divu_fp(a_fp, b_fp, DIVFP_WIDTH, DIVFP_FBITS)
    expected = int(3.5 * (1 << DIVFP_FBITS))
    assert ref["quotient"] == expected, f"7/2 fp"
    assert ref["dbz"] is False
    assert ref["ovf"] is False


# ---------------------------------------------------------------------------
# Load and validate agent results
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.isfile(path), f"Missing {path}"
    with open(path) as f:
        data = json.load(f)
    return data


def test_results_structure(results):
    """Check top-level keys exist."""
    for key in ("divu_int", "sqrt_int", "divu_fp", "mandelbrot"):
        assert key in results, f"Missing key: {key}"


def test_divu_int_results(results):
    """Verify unsigned integer division results."""
    section = results["divu_int"]
    assert section["width"] == DIV_WIDTH
    agent = section["results"]
    assert len(agent) == len(DIV_TESTS), "Wrong number of divu_int results"

    for idx, (a, b) in enumerate(DIV_TESTS):
        ref = ref_divu_int(a, b, DIV_WIDTH)
        entry = agent[idx]
        assert entry["a"] == a, f"divu_int[{idx}] a mismatch"
        assert entry["b"] == b, f"divu_int[{idx}] b mismatch"
        assert entry["dbz"] == ref["dbz"], f"divu_int[{idx}] dbz mismatch"
        if not ref["dbz"]:
            assert entry["quotient"] == ref["quotient"], (
                f"divu_int[{idx}] quotient: got {entry['quotient']}, want {ref['quotient']}"
            )
            assert entry["remainder"] == ref["remainder"], (
                f"divu_int[{idx}] remainder: got {entry['remainder']}, want {ref['remainder']}"
            )


def test_sqrt_int_results(results):
    """Verify integer square root results."""
    section = results["sqrt_int"]
    assert section["width"] == SQRT_WIDTH
    agent = section["results"]
    assert len(agent) == len(SQRT_TESTS), "Wrong number of sqrt_int results"

    for idx, rad in enumerate(SQRT_TESTS):
        ref = ref_sqrt_int(rad, SQRT_WIDTH)
        entry = agent[idx]
        assert entry["radicand"] == rad, f"sqrt_int[{idx}] radicand mismatch"
        assert entry["root"] == ref["root"], (
            f"sqrt_int[{idx}] root: got {entry['root']}, want {ref['root']}"
        )
        assert entry["remainder"] == ref["remainder"], (
            f"sqrt_int[{idx}] remainder: got {entry['remainder']}, want {ref['remainder']}"
        )


def test_divu_fp_results(results):
    """Verify unsigned fixed-point division results."""
    section = results["divu_fp"]
    assert section["width"] == DIVFP_WIDTH
    assert section["fbits"] == DIVFP_FBITS
    agent = section["results"]
    assert len(agent) == len(DIVFP_TESTS_REAL), "Wrong number of divu_fp results"

    for idx, (a_real, b_real) in enumerate(DIVFP_TESTS_REAL):
        a_fp = int(a_real * (1 << DIVFP_FBITS))
        b_fp = int(b_real * (1 << DIVFP_FBITS))
        ref = ref_divu_fp(a_fp, b_fp, DIVFP_WIDTH, DIVFP_FBITS)
        entry = agent[idx]
        assert entry["a"] == a_fp, f"divu_fp[{idx}] a mismatch"
        assert entry["b"] == b_fp, f"divu_fp[{idx}] b mismatch"
        assert entry["dbz"] == ref["dbz"], f"divu_fp[{idx}] dbz mismatch"
        assert entry["ovf"] == ref["ovf"], f"divu_fp[{idx}] ovf mismatch"
        if not ref["dbz"] and not ref["ovf"]:
            assert entry["quotient"] == ref["quotient"], (
                f"divu_fp[{idx}] quotient: got {entry['quotient']}, want {ref['quotient']}"
            )


def test_mandelbrot_results(results):
    """Verify Mandelbrot escape iteration results."""
    section = results["mandelbrot"]
    assert section["width"] == FP_WIDTH
    assert section["fbits"] == FP_FBITS
    assert section["max_iter"] == MANDEL_MAX_ITER
    grid = section["grid"]

    expected_count = len(MANDEL_X_REALS) * len(MANDEL_Y_REALS)
    assert len(grid) == expected_count, (
        f"Expected {expected_count} grid entries, got {len(grid)}"
    )

    idx = 0
    for cx_real in MANDEL_X_REALS:
        cx_fp = int(cx_real * (1 << FP_FBITS))
        for cy_real in MANDEL_Y_REALS:
            cy_fp = int(cy_real * (1 << FP_FBITS))
            ref_iter = ref_mandelbrot(
                cx_fp & FP_MASK, cy_fp & FP_MASK, MANDEL_MAX_ITER
            )

            entry = grid[idx]
            assert entry["cx"] == cx_fp, f"mandelbrot[{idx}] cx mismatch"
            assert entry["cy"] == cy_fp, f"mandelbrot[{idx}] cy mismatch"
            assert entry["iterations"] == ref_iter, (
                f"mandelbrot[{idx}] ({cx_real},{cy_real}): "
                f"got {entry['iterations']}, want {ref_iter}"
            )
            idx += 1


def test_mandelbrot_known_points(results):
    """Spot-check a few well-known Mandelbrot points."""
    grid = results["mandelbrot"]["grid"]

    # Build lookup
    lookup = {}
    for entry in grid:
        lookup[(entry["cx"], entry["cy"])] = entry["iterations"]

    fbits = FP_FBITS

    # (0, 0) is in the set
    cx, cy = 0, 0
    assert lookup.get((cx, cy)) == MANDEL_MAX_ITER, "(0,0) should be in set"

    # (-1, 0) is in the set (period-2 cycle)
    cx = int(-1.0 * (1 << fbits))
    cy = 0
    assert lookup.get((cx, cy)) == MANDEL_MAX_ITER, "(-1,0) should be in set"

    # (-0.5, 0) is in the set
    cx = int(-0.5 * (1 << fbits))
    cy = 0
    assert lookup.get((cx, cy)) == MANDEL_MAX_ITER, "(-0.5,0) should be in set"
