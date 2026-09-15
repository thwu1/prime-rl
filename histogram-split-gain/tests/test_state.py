
import json
import math
import subprocess
import pytest

EPSILON = 1e-15


def sign(x):
    if x > 0:
        return 1.0
    elif x < 0:
        return -1.0
    return 0.0


def threshold_l1(s, l1):
    reg_s = max(0.0, abs(s) - l1)
    return sign(s) * reg_s


def calc_leaf_output(sum_grad, sum_hess, l1, l2, max_delta,
                     c_min, c_max, use_mc, smooth, num_data, parent_out):
    sg = threshold_l1(sum_grad, l1)
    output = -sg / (sum_hess + l2)
    if max_delta > 0 and abs(output) > max_delta:
        output = sign(output) * max_delta
    if smooth > EPSILON:
        ratio = num_data / smooth
        output = output * ratio / (ratio + 1) + parent_out / (ratio + 1)
    if use_mc:
        output = max(c_min, min(c_max, output))
    return output


def get_leaf_gain(sum_grad, sum_hess, l1, l2, max_delta,
                  c_min, c_max, use_mc, smooth, num_data, parent_out):
    if max_delta <= 0 and not use_mc and smooth <= EPSILON:
        sg = threshold_l1(sum_grad, l1)
        return (sg * sg) / (sum_hess + l2)
    else:
        output = calc_leaf_output(sum_grad, sum_hess, l1, l2, max_delta,
                                  c_min, c_max, use_mc, smooth, num_data,
                                  parent_out)
        sg = threshold_l1(sum_grad, l1)
        return -(2.0 * sg * output + (sum_hess + l2) * output * output)


def get_leaf_gain_given_output(sum_grad, sum_hess, l1, l2, output):
    sg = threshold_l1(sum_grad, l1)
    return -(2.0 * sg * output + (sum_hess + l2) * output * output)


def no_split_result(default_left):
    return {"best_threshold": -1, "best_gain": 0.0,
            "left_output": 0.0, "right_output": 0.0,
            "left_count": 0, "right_count": 0,
            "default_left": default_left}


def reference_find_split_forward(config):
    bins = config["bins"]
    num_bins = len(bins)
    if num_bins <= 1:
        return no_split_result(False)

    tg = config["total_gradient"]
    th = config["total_hessian"]
    tc = config["total_count"]
    l1 = config["lambda_l1"]
    l2 = config["lambda_l2"]
    min_data = config["min_data_in_leaf"]
    min_hess = config["min_sum_hessian_in_leaf"]
    min_gain = config["min_gain_to_split"]
    max_delta = config["max_delta_step"]
    mono = config["monotone_type"]
    c_min = config.get("constraint_min", -1e300)
    c_max = config.get("constraint_max", 1e300)
    parent_out = config.get("parent_output", 0.0)
    smooth = config.get("path_smooth", 0.0)

    use_mc = (mono != 0)

    parent_gain = get_leaf_gain(tg, th + 2 * EPSILON, l1, l2, max_delta,
                                c_min, c_max, use_mc, smooth, tc, parent_out)
    min_gain_shift = parent_gain + min_gain

    cnt_factor = tc / th
    sum_left_grad = 0.0
    sum_left_hess = EPSILON
    left_count = 0

    best_gain = -math.inf
    best_result = None

    for t in range(num_bins - 1):
        bin_idx = t + 1
        if bin_idx >= num_bins:
            break
        sum_left_grad += bins[bin_idx]["grad"]
        sum_left_hess += bins[bin_idx]["hess"]
        left_count += round(bins[bin_idx]["hess"] * cnt_factor)

        if left_count < min_data:
            continue
        if sum_left_hess < min_hess:
            continue

        right_count = tc - left_count
        if right_count < min_data:
            break

        sum_right_grad = tg - sum_left_grad
        sum_right_hess = th - sum_left_hess
        if sum_right_hess < min_hess:
            break

        if use_mc:
            left_out = calc_leaf_output(sum_left_grad, sum_left_hess, l1, l2,
                                        max_delta, c_min, c_max, True,
                                        smooth, left_count, parent_out)
            right_out = calc_leaf_output(sum_right_grad, sum_right_hess, l1, l2,
                                         max_delta, c_min, c_max, True,
                                         smooth, right_count, parent_out)
            if mono > 0 and left_out > right_out:
                continue
            if mono < 0 and left_out < right_out:
                continue
            current_gain = (get_leaf_gain_given_output(sum_left_grad, sum_left_hess,
                                                       l1, l2, left_out) +
                            get_leaf_gain_given_output(sum_right_grad, sum_right_hess,
                                                       l1, l2, right_out))
        else:
            current_gain = (get_leaf_gain(sum_left_grad, sum_left_hess, l1, l2,
                                          max_delta, c_min, c_max, False,
                                          smooth, left_count, parent_out) +
                            get_leaf_gain(sum_right_grad, sum_right_hess, l1, l2,
                                          max_delta, c_min, c_max, False,
                                          smooth, right_count, parent_out))

        if current_gain <= min_gain_shift:
            continue

        if current_gain > best_gain:
            best_gain = current_gain
            net_gain = current_gain - min_gain_shift
            l_out = calc_leaf_output(sum_left_grad, sum_left_hess, l1, l2,
                                     max_delta, c_min, c_max, use_mc,
                                     smooth, left_count, parent_out)
            r_out = calc_leaf_output(sum_right_grad, sum_right_hess, l1, l2,
                                     max_delta, c_min, c_max, use_mc,
                                     smooth, right_count, parent_out)
            best_result = {
                "best_threshold": t,
                "best_gain": net_gain,
                "left_output": l_out,
                "right_output": r_out,
                "left_count": left_count,
                "right_count": right_count,
                "default_left": False,
            }

    if best_result is None:
        return no_split_result(False)
    return best_result


def reference_find_split_reverse(config):
    bins = config["bins"]
    num_bins = len(bins)
    has_na = config.get("has_na_bin", False)
    if num_bins <= 1:
        return no_split_result(True)

    tg = config["total_gradient"]
    th = config["total_hessian"]
    tc = config["total_count"]
    l1 = config["lambda_l1"]
    l2 = config["lambda_l2"]
    min_data = config["min_data_in_leaf"]
    min_hess = config["min_sum_hessian_in_leaf"]
    min_gain = config["min_gain_to_split"]
    max_delta = config["max_delta_step"]
    mono = config["monotone_type"]
    c_min = config.get("constraint_min", -1e300)
    c_max = config.get("constraint_max", 1e300)
    parent_out = config.get("parent_output", 0.0)
    smooth = config.get("path_smooth", 0.0)

    use_mc = (mono != 0)

    parent_gain = get_leaf_gain(tg, th + 2 * EPSILON, l1, l2, max_delta,
                                c_min, c_max, use_mc, smooth, tc, parent_out)
    min_gain_shift = parent_gain + min_gain

    cnt_factor = tc / th
    sum_right_grad = 0.0
    sum_right_hess = EPSILON
    right_count = 0

    best_gain = -math.inf
    best_result = None

    t_start = num_bins - 1
    if has_na:
        t_start -= 1

    for t in range(t_start, 0, -1):
        sum_right_grad += bins[t]["grad"]
        sum_right_hess += bins[t]["hess"]
        right_count += round(bins[t]["hess"] * cnt_factor)

        if right_count < min_data:
            continue
        if sum_right_hess < min_hess:
            continue

        left_count = tc - right_count
        if left_count < min_data:
            break

        sum_left_grad = tg - sum_right_grad
        sum_left_hess = th - sum_right_hess
        if sum_left_hess < min_hess:
            break

        if use_mc:
            left_out = calc_leaf_output(sum_left_grad, sum_left_hess, l1, l2,
                                        max_delta, c_min, c_max, True,
                                        smooth, left_count, parent_out)
            right_out = calc_leaf_output(sum_right_grad, sum_right_hess, l1, l2,
                                         max_delta, c_min, c_max, True,
                                         smooth, right_count, parent_out)
            if mono > 0 and left_out > right_out:
                continue
            if mono < 0 and left_out < right_out:
                continue
            current_gain = (get_leaf_gain_given_output(sum_left_grad, sum_left_hess,
                                                       l1, l2, left_out) +
                            get_leaf_gain_given_output(sum_right_grad, sum_right_hess,
                                                       l1, l2, right_out))
        else:
            current_gain = (get_leaf_gain(sum_left_grad, sum_left_hess, l1, l2,
                                          max_delta, c_min, c_max, False,
                                          smooth, left_count, parent_out) +
                            get_leaf_gain(sum_right_grad, sum_right_hess, l1, l2,
                                          max_delta, c_min, c_max, False,
                                          smooth, right_count, parent_out))

        if current_gain <= min_gain_shift:
            continue

        if current_gain > best_gain:
            best_gain = current_gain
            net_gain = current_gain - min_gain_shift
            l_out = calc_leaf_output(sum_left_grad, sum_left_hess, l1, l2,
                                     max_delta, c_min, c_max, use_mc,
                                     smooth, left_count, parent_out)
            r_out = calc_leaf_output(sum_right_grad, sum_right_hess, l1, l2,
                                     max_delta, c_min, c_max, use_mc,
                                     smooth, right_count, parent_out)
            best_result = {
                "best_threshold": t - 1,
                "best_gain": net_gain,
                "left_output": l_out,
                "right_output": r_out,
                "left_count": left_count,
                "right_count": right_count,
                "default_left": True,
            }

    if best_result is None:
        return no_split_result(True)
    return best_result


def reference_find_split(config):
    if config.get("scan_reverse", False):
        return reference_find_split_reverse(config)
    return reference_find_split_forward(config)


def run_binary(test_cases):
    input_data = {"test_cases": test_cases}
    with open("/app/input.json", "w") as f:
        json.dump(input_data, f)
    result = subprocess.run(
        ["./histogram_split_finder"],
        cwd="/app",
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"Binary failed: {result.stderr}"
    with open("/app/output.json") as f:
        return json.load(f)


def approx_eq(a, b, rel_tol=1e-6, abs_tol=1e-6):
    if abs(a) < abs_tol and abs(b) < abs_tol:
        return True
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def make_case(bins, total_grad, total_hess, total_count,
              l1=0.0, l2=0.1, min_data=1, min_hess=0.001,
              min_gain=0.0, max_delta=0.0, mono=0,
              c_min=-1e300, c_max=1e300, parent_out=0.0,
              smooth=0.0, reverse=False, has_na=False):
    return {
        "bins": [{"grad": g, "hess": h} for g, h in bins],
        "total_gradient": total_grad,
        "total_hessian": total_hess,
        "total_count": total_count,
        "lambda_l1": l1,
        "lambda_l2": l2,
        "min_data_in_leaf": min_data,
        "min_sum_hessian_in_leaf": min_hess,
        "min_gain_to_split": min_gain,
        "max_delta_step": max_delta,
        "monotone_type": mono,
        "constraint_min": c_min,
        "constraint_max": c_max,
        "parent_output": parent_out,
        "path_smooth": smooth,
        "scan_reverse": reverse,
        "has_na_bin": has_na,
    }


def assert_result(actual, ref, label=""):
    prefix = f"{label}: " if label else ""
    assert actual["best_threshold"] == ref["best_threshold"], \
        f"{prefix}threshold: got {actual['best_threshold']}, want {ref['best_threshold']}"
    assert approx_eq(actual["best_gain"], ref["best_gain"]), \
        f"{prefix}gain: got {actual['best_gain']}, want {ref['best_gain']}"
    if ref["best_threshold"] >= 0:
        assert approx_eq(actual["left_output"], ref["left_output"]), \
            f"{prefix}left_out: got {actual['left_output']}, want {ref['left_output']}"
        assert approx_eq(actual["right_output"], ref["right_output"]), \
            f"{prefix}right_out: got {actual['right_output']}, want {ref['right_output']}"
        assert actual["left_count"] == ref["left_count"], \
            f"{prefix}left_count: got {actual['left_count']}, want {ref['left_count']}"
        assert actual["right_count"] == ref["right_count"], \
            f"{prefix}right_count: got {actual['right_count']}, want {ref['right_count']}"
        assert actual["default_left"] == ref["default_left"], \
            f"{prefix}default_left: got {actual['default_left']}, want {ref['default_left']}"


# --- Test cases ---

def test_basic_l2_forward():
    """Basic forward split with L2 only, 4 bins."""
    bins = [(0, 0), (-2, 5), (1.5, 3), (-0.5, 2)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 100, l2=0.5)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)


def test_basic_l2_reverse():
    """Basic reverse split with L2 only, 4 bins."""
    bins = [(0, 0), (-2, 5), (1.5, 3), (-0.5, 2)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 100, l2=0.5, reverse=True)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)
    assert results[0]["default_left"] is True


def test_l1_l2_forward():
    """L1+L2 regularization, forward scan."""
    bins = [(0, 0), (-3, 8), (2, 4), (-1, 3), (0.5, 2)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 170, l1=0.5, l2=1.0)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)


def test_l1_l2_reverse():
    """L1+L2 regularization, reverse scan."""
    bins = [(0, 0), (-3, 8), (2, 4), (-1, 3), (0.5, 2)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 170, l1=0.5, l2=1.0, reverse=True)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)


def test_max_delta_step():
    """max_delta_step clamps leaf outputs."""
    bins = [(0, 0), (-10, 2), (8, 1.5), (-1, 3)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 65, l2=0.1, max_delta=1.0)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)
    if results[0]["best_threshold"] >= 0:
        assert abs(results[0]["left_output"]) <= 1.0 + 1e-9
        assert abs(results[0]["right_output"]) <= 1.0 + 1e-9


def test_l1_max_delta():
    """L1 + max_delta_step combined."""
    bins = [(0, 0), (-5, 3), (4, 2), (-2, 4), (1, 1.5)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 105, l1=1.0, l2=0.5, max_delta=0.8)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)


def test_path_smoothing_forward():
    """Path smoothing blends leaf output with parent, forward scan."""
    bins = [(0, 0), (-4, 6), (3, 5), (-1, 4)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 150, l2=0.5, smooth=10.0, parent_out=0.3)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)


def test_path_smoothing_reverse():
    """Path smoothing with reverse scan and L1."""
    bins = [(0, 0), (-3, 5), (2, 4), (-1, 3), (0.5, 2)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 140, l1=0.3, l2=0.5, smooth=8.0,
                     parent_out=-0.2, reverse=True)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)


def test_monotone_increasing():
    """Monotone increasing: left_output <= right_output."""
    bins = [(0, 0), (-4, 6), (3, 5), (-1, 4)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 150, l2=0.5, mono=1)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)
    if results[0]["best_threshold"] >= 0:
        assert results[0]["left_output"] <= results[0]["right_output"] + 1e-9


def test_monotone_decreasing():
    """Monotone decreasing: left_output >= right_output."""
    bins = [(0, 0), (3, 5), (-4, 6), (1, 4)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 150, l2=0.5, mono=-1)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)
    if results[0]["best_threshold"] >= 0:
        assert results[0]["left_output"] >= results[0]["right_output"] - 1e-9


def test_monotone_with_bounds():
    """Monotone constraint with explicit output bounds."""
    bins = [(0, 0), (-6, 3), (5, 3), (-2, 4)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 100, l2=0.1, mono=1,
                     c_min=-0.5, c_max=0.8)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)
    if results[0]["best_threshold"] >= 0:
        assert results[0]["left_output"] >= -0.5 - 1e-9
        assert results[0]["right_output"] <= 0.8 + 1e-9


def test_monotone_rejection():
    """All candidate splits violate monotone increasing — no valid split."""
    bins = [(0, 0), (-8, 2), (-6, 2), (1, 6)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 90, l2=0.1, mono=1)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert results[0]["best_threshold"] == ref["best_threshold"]


def test_min_data_right_side():
    """Right child has too few data — split must be rejected."""
    bins = [(0, 0), (-0.5, 3), (-0.1, 6.5), (3.0, 0.5)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 100, l2=0.1, min_data=10)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert results[0]["best_threshold"] == ref["best_threshold"], \
        f"threshold: got {results[0]['best_threshold']}, want {ref['best_threshold']}"


def test_min_hess_right_side():
    """Right child sum hessian too small at t=1 — only t=0 is valid."""
    bins = [(0, 0), (-3, 3), (-0.5, 6), (2, 0.005)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 100, l2=0.1, min_hess=1.0)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert results[0]["best_threshold"] == ref["best_threshold"], \
        f"threshold: got {results[0]['best_threshold']}, want {ref['best_threshold']}"
    assert_result(results[0], ref)


def test_min_gain_filter():
    """High min_gain_to_split rejects marginal splits."""
    bins = [(0, 0), (-0.01, 5), (0.01, 5)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 100, l2=0.1, min_gain=10.0)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert results[0]["best_threshold"] == -1


def test_reverse_na_bin():
    """Reverse scan must skip the NaN sentinel bin."""
    bins = [(0, 0), (-1, 3), (2, 4), (-0.5, 3), (10.0, 0.5)]
    tg = sum(g for g, h in bins[:-1])  # NaN bin excluded from totals
    th = sum(h for g, h in bins[:-1])
    case = make_case(bins, tg, th, 100, l2=0.1, reverse=True, has_na=True)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)


def test_reverse_monotone():
    """Reverse scan with monotone constraint."""
    bins = [(0, 0), (3, 5), (-4, 6), (1, 4)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 150, l2=0.5, mono=-1, reverse=True)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)
    if results[0]["best_threshold"] >= 0:
        assert results[0]["left_output"] >= results[0]["right_output"] - 1e-9


def test_many_bins():
    """8-bin histogram with L1, max_delta, and smoothing."""
    import random
    random.seed(42)
    bins_data = [(0.0, 0.0)]
    for _ in range(7):
        g = random.uniform(-5, 5)
        h = random.uniform(1, 8)
        bins_data.append((round(g, 4), round(h, 4)))
    tg = sum(g for g, h in bins_data)
    th = sum(h for g, h in bins_data)
    case = make_case(bins_data, tg, th, 350, l1=0.3, l2=0.8, min_data=5,
                     min_hess=0.5, max_delta=2.0, smooth=5.0, parent_out=0.1)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)


def test_large_l1_zeroes():
    """Very large L1 zeros all thresholded gradients."""
    bins = [(0, 0), (-1, 5), (0.8, 5)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 100, l1=50.0, l2=0.1)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert results[0]["best_threshold"] == ref["best_threshold"]


def test_parent_gain_subtraction():
    """Verify net gain = split_gain - parent_gain - min_gain_to_split."""
    bins = [(0, 0), (-3, 5), (1, 5)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 100, l2=0.5)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)
    assert results[0]["best_gain"] > 0
    raw_l = threshold_l1(-3.0, 0.0)
    raw_r = threshold_l1(1.0, 0.0)
    raw_gain = (raw_l ** 2 / (5.0 + EPSILON + 0.5)) + (raw_r ** 2 / (5.0 + EPSILON + 0.5))
    assert results[0]["best_gain"] < raw_gain - 0.01, "Gain must have parent subtracted"


def test_batch_mode():
    """Multiple test cases in a single batch."""
    cases = []
    refs = []

    bins1 = [(0, 0), (-3, 4), (2, 3)]
    c1 = make_case(bins1, sum(g for g, h in bins1), sum(h for g, h in bins1), 70, l2=0.2)
    cases.append(c1)
    refs.append(reference_find_split(c1))

    bins2 = [(0, 0), (-2, 5), (3, 4), (-1, 3)]
    c2 = make_case(bins2, sum(g for g, h in bins2), sum(h for g, h in bins2), 120,
                   l1=0.2, l2=0.5, mono=-1)
    cases.append(c2)
    refs.append(reference_find_split(c2))

    bins3 = [(0, 0), (-7, 2), (4, 2.5), (-1, 5)]
    c3 = make_case(bins3, sum(g for g, h in bins3), sum(h for g, h in bins3), 95,
                   l1=0.5, l2=0.3, max_delta=1.5, mono=1, reverse=True)
    cases.append(c3)
    refs.append(reference_find_split(c3))

    results = run_binary(cases)
    assert len(results) == 3
    for i, (actual, ref) in enumerate(zip(results, refs)):
        assert_result(actual, ref, label=f"Case {i}")


def test_full_interaction_forward():
    """All features active: L1+max_delta+mono+smoothing+bounds, forward."""
    bins = [(0, 0), (-6, 4), (4, 3), (-3, 5), (1, 2)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 140, l1=0.8, l2=0.5, max_delta=1.2,
                     mono=-1, c_min=-1.0, c_max=0.5, smooth=6.0,
                     parent_out=0.1)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)
    if results[0]["best_threshold"] >= 0:
        assert results[0]["left_output"] >= results[0]["right_output"] - 1e-9
        assert results[0]["left_output"] >= -1.0 - 1e-9
        assert results[0]["right_output"] <= 0.5 + 1e-9


def test_full_interaction_reverse():
    """All features active: L1+max_delta+mono+smoothing+bounds, reverse."""
    bins = [(0, 0), (-6, 4), (4, 3), (-3, 5), (1, 2)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 140, l1=0.8, l2=0.5, max_delta=1.2,
                     mono=-1, c_min=-1.0, c_max=0.5, smooth=6.0,
                     parent_out=0.1, reverse=True)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)
    assert results[0]["default_left"] is True


def test_smoothing_with_monotone():
    """Smoothing + monotone constraints interact: smoothed outputs must
    still respect constraint bounds and directional ordering."""
    bins = [(0, 0), (-5, 4), (3, 3), (-2, 5)]
    tg = sum(g for g, h in bins)
    th = sum(h for g, h in bins)
    case = make_case(bins, tg, th, 120, l2=0.3, mono=1, smooth=8.0,
                     parent_out=0.2, c_min=-0.5, c_max=1.0)
    ref = reference_find_split(case)
    results = run_binary([case])
    assert_result(results[0], ref)
    if results[0]["best_threshold"] >= 0:
        assert results[0]["left_output"] <= results[0]["right_output"] + 1e-9
