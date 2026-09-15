"""
Test ISDA SIMM v2.6 IR Margin Calculator (Delta + Curvature + Total).

Verifies the Java implementation against a Python reference implementation
for delta margin, curvature margin, and total IR margin across five portfolios.

"""

import json
import math
import csv
import subprocess
import os
import pytest

TENORS = ["2W", "1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y", "15Y", "20Y", "30Y"]
TENOR_YEARS = [2.0/52.0, 1.0/12.0, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 15.0, 20.0, 30.0]
DATA_DIR = "/app/data"
PORTFOLIO_DIR = "/app/portfolios"
TOLERANCE = 0.01


def load_risk_weights():
    weights = {}
    with open(os.path.join(DATA_DIR, "risk_weights.csv")) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if not row or not row[0].strip():
                continue
            group = row[0].strip()
            vals = [float(v.strip()) for v in row[1:]]
            weights[group] = vals
    return weights


def load_currency_groups():
    groups = {}
    with open(os.path.join(DATA_DIR, "currency_groups.csv")) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if not row or not row[0].strip():
                continue
            groups[row[0].strip()] = row[1].strip()
    return groups


def load_thresholds():
    thresholds = {}
    with open(os.path.join(DATA_DIR, "concentration_thresholds.csv")) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if not row or not row[0].strip():
                continue
            thresholds[row[0].strip()] = float(row[1].strip())
    return thresholds


def load_params():
    params = {}
    with open(os.path.join(DATA_DIR, "simm_params.csv")) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if not row or not row[0].strip():
                continue
            params[row[0].strip()] = float(row[1].strip())
    return params


def load_curvature_params():
    params = {}
    with open(os.path.join(DATA_DIR, "curvature_params.csv")) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if not row or not row[0].strip():
                continue
            params[row[0].strip()] = float(row[1].strip())
    return params


def load_portfolio(path):
    portfolio = []
    with open(path) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if not row or not row[0].strip():
                continue
            portfolio.append({
                "riskType": row[0].strip(),
                "currency": row[1].strip(),
                "subCurve": row[2].strip(),
                "tenor": row[3].strip(),
                "value": float(row[4].strip())
            })
    return portfolio


def tenor_index(tenor):
    return TENORS.index(tenor)


def tenor_correlation(k, l, theta, rho_min):
    if k == l:
        return 1.0
    tk = TENOR_YEARS[k]
    tl = TENOR_YEARS[l]
    return max(math.exp(-theta * abs(tk - tl) / min(tk, tl)), rho_min)


def compute_delta_reference(delta_sens, risk_weights, currency_groups, thresholds, params):
    theta = params["theta"]
    rho_min = params["rho_min"]
    phi = params["phi"]
    gamma_param = params["gamma"]

    if not delta_sens:
        return {}, 0.0

    buckets = {}
    for s in delta_sens:
        ccy = s["currency"]
        if ccy not in buckets:
            buckets[ccy] = []
        buckets[ccy].append(s)

    bucket_results = {}

    for ccy, sens_list in buckets.items():
        group = currency_groups.get(ccy, "HighVol")
        rw = risk_weights[group]
        threshold = thresholds[group]

        net_sens = sum(s["value"] for s in sens_list)
        cr = max(1.0, math.sqrt(abs(net_sens) / threshold))

        n = len(sens_list)
        ws = []
        t_idx = []
        sc = []
        for s in sens_list:
            ti = tenor_index(s["tenor"])
            t_idx.append(ti)
            sc.append(s["subCurve"])
            ws.append(rw[ti] * s["value"] * cr)

        k_sq = 0.0
        for i in range(n):
            for j in range(n):
                rho = tenor_correlation(t_idx[i], t_idx[j], theta, rho_min)
                phi_f = 1.0 if sc[i] == sc[j] else phi
                k_sq += rho * phi_f * ws[i] * ws[j]

        K = math.sqrt(max(0.0, k_sq))
        S = sum(ws)

        bucket_results[ccy] = {"K": K, "S": S, "CR": cr}

    ccys = sorted(bucket_results.keys())

    if len(ccys) == 1:
        delta_margin = bucket_results[ccys[0]]["K"]
    else:
        total = sum(bucket_results[c]["K"] ** 2 for c in ccys)
        for i in range(len(ccys)):
            for j in range(i + 1, len(ccys)):
                total += 2 * gamma_param * bucket_results[ccys[i]]["S"] * bucket_results[ccys[j]]["S"]

        if total < 0:
            total = sum(bucket_results[c]["K"] ** 2 for c in ccys)
            for i in range(len(ccys)):
                for j in range(i + 1, len(ccys)):
                    ki = bucket_results[ccys[i]]["K"]
                    si = max(-ki, min(bucket_results[ccys[i]]["S"], ki))
                    kj = bucket_results[ccys[j]]["K"]
                    sj = max(-kj, min(bucket_results[ccys[j]]["S"], kj))
                    total += 2 * gamma_param * si * sj

        delta_margin = math.sqrt(max(0.0, total))

    return bucket_results, delta_margin


def compute_cvr(vega, risk_weight, sigma):
    shift = sigma * risk_weight * 0.01
    return vega * (math.exp(shift) + math.exp(-shift) - 2.0) / 2.0


def compute_curvature_reference(curv_sens, risk_weights, currency_groups, params, curv_params):
    theta = params["theta"]
    rho_min = params["rho_min"]
    phi = params["phi"]
    gamma_param = params["gamma"]
    sigma = curv_params["sigma"]

    if not curv_sens:
        return {}, 0.0

    buckets = {}
    for s in curv_sens:
        ccy = s["currency"]
        if ccy not in buckets:
            buckets[ccy] = []
        buckets[ccy].append(s)

    bucket_results = {}

    for ccy, sens_list in buckets.items():
        group = currency_groups.get(ccy, "HighVol")
        rw = risk_weights[group]

        n = len(sens_list)
        cvr = []
        t_idx = []
        sc = []

        for s in sens_list:
            ti = tenor_index(s["tenor"])
            t_idx.append(ti)
            sc.append(s["subCurve"])
            cvr.append(compute_cvr(s["value"], rw[ti], sigma))

        sum_cvr = sum(cvr)
        sum_abs_cvr = sum(abs(c) for c in cvr)
        lam = sum_cvr / sum_abs_cvr if sum_abs_cvr > 0 else 0.0

        k_sq = 0.0
        for i in range(n):
            for j in range(n):
                rho = tenor_correlation(t_idx[i], t_idx[j], theta, rho_min)
                rho_sq = rho * rho
                phi_f = 1.0 if sc[i] == sc[j] else phi
                k_sq += rho_sq * phi_f * cvr[i] * cvr[j]

        K = math.sqrt(max(0.0, k_sq))
        margin = max(sum_cvr + lam * K, 0.0)

        bucket_results[ccy] = {"K": K, "sumCVR": sum_cvr, "lambda": lam, "margin": margin}

    ccys = sorted(bucket_results.keys())

    if len(ccys) == 1:
        curv_margin = bucket_results[ccys[0]]["margin"]
    else:
        total = 0.0
        for c in ccys:
            m = bucket_results[c]["margin"]
            total += m * m

        for i in range(len(ccys)):
            for j in range(i + 1, len(ccys)):
                mi = bucket_results[ccys[i]]["margin"]
                mj = bucket_results[ccys[j]]["margin"]
                si = max(-mi, min(bucket_results[ccys[i]]["sumCVR"], mi)) if mi > 0 else 0.0
                sj = max(-mj, min(bucket_results[ccys[j]]["sumCVR"], mj)) if mj > 0 else 0.0
                total += 2 * gamma_param * gamma_param * si * sj

        curv_margin = math.sqrt(max(0.0, total))

    return bucket_results, curv_margin


def compute_total_margin(delta_margin, curvature_margin, rho_dc):
    return math.sqrt(
        delta_margin ** 2 + curvature_margin ** 2
        + 2 * rho_dc * delta_margin * curvature_margin
    )


def compute_all_reference(portfolio_path):
    risk_weights = load_risk_weights()
    currency_groups = load_currency_groups()
    thresholds = load_thresholds()
    params = load_params()
    curv_params = load_curvature_params()

    portfolio = load_portfolio(portfolio_path)
    delta_sens = [s for s in portfolio if s["riskType"] == "Delta"]
    curv_sens = [s for s in portfolio if s["riskType"] == "Curvature"]

    delta_buckets, delta_margin = compute_delta_reference(
        delta_sens, risk_weights, currency_groups, thresholds, params
    )
    curv_buckets, curv_margin = compute_curvature_reference(
        curv_sens, risk_weights, currency_groups, params, curv_params
    )
    total_margin = compute_total_margin(
        delta_margin, curv_margin, curv_params["rho_delta_curvature"]
    )

    return delta_buckets, delta_margin, curv_buckets, curv_margin, total_margin


def run_java(portfolio_path):
    result = subprocess.run(
        ["java", "-cp", "/app/out", "Main", portfolio_path],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        pytest.fail(
            f"Java execution failed for {portfolio_path}:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    output = result.stdout.strip()
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        pytest.fail(f"Invalid JSON output for {portfolio_path}: {output}")


def assert_close(expected, actual, label, tol=TOLERANCE):
    assert abs(expected - actual) < tol, (
        f"[{label}] expected {expected:.6f}, got {actual}"
    )


class TestSimmMarginCalculator:

    def test_portfolio_1_delta_only_single_currency(self):
        """Portfolio 1: USD OIS delta only. Tests basic delta intra-bucket."""
        path = os.path.join(PORTFOLIO_DIR, "portfolio_1.csv")
        db, dm, cb, cm, tm = compute_all_reference(path)
        actual = run_java(path)

        assert_close(dm, actual["deltaMargin"], "p1 deltaMargin")
        assert_close(cm, actual["curvatureMargin"], "p1 curvatureMargin")
        assert_close(tm, actual["totalMargin"], "p1 totalMargin")

        for ccy in db:
            assert ccy in actual["deltaBuckets"], f"p1 missing delta bucket {ccy}"
            for key in ["K", "S", "CR"]:
                assert_close(db[ccy][key], actual["deltaBuckets"][ccy][key], f"p1 {ccy}.{key}")

    def test_portfolio_2_delta_multi_subcurve(self):
        """Portfolio 2: EUR with OIS + LIBOR6M. Tests phi correlation factor."""
        path = os.path.join(PORTFOLIO_DIR, "portfolio_2.csv")
        db, dm, cb, cm, tm = compute_all_reference(path)
        actual = run_java(path)

        assert_close(dm, actual["deltaMargin"], "p2 deltaMargin")
        assert_close(cm, actual["curvatureMargin"], "p2 curvatureMargin")
        assert_close(tm, actual["totalMargin"], "p2 totalMargin")

        for ccy in db:
            for key in ["K", "S", "CR"]:
                assert_close(db[ccy][key], actual["deltaBuckets"][ccy][key], f"p2 {ccy}.{key}")

    def test_portfolio_3_delta_multi_currency(self):
        """Portfolio 3: USD + JPY + BRL. Tests inter-bucket delta, concentration risk."""
        path = os.path.join(PORTFOLIO_DIR, "portfolio_3.csv")
        db, dm, cb, cm, tm = compute_all_reference(path)
        actual = run_java(path)

        assert_close(dm, actual["deltaMargin"], "p3 deltaMargin")
        assert_close(cm, actual["curvatureMargin"], "p3 curvatureMargin")
        assert_close(tm, actual["totalMargin"], "p3 totalMargin")

        for ccy in db:
            assert ccy in actual["deltaBuckets"], f"p3 missing delta bucket {ccy}"
            for key in ["K", "S", "CR"]:
                assert_close(db[ccy][key], actual["deltaBuckets"][ccy][key], f"p3 {ccy}.{key}")

    def test_portfolio_4_delta_and_curvature(self):
        """Portfolio 4: USD delta + curvature. Tests curvature implementation."""
        path = os.path.join(PORTFOLIO_DIR, "portfolio_4.csv")
        db, dm, cb, cm, tm = compute_all_reference(path)
        actual = run_java(path)

        assert_close(dm, actual["deltaMargin"], "p4 deltaMargin")
        assert_close(cm, actual["curvatureMargin"], "p4 curvatureMargin")
        assert_close(tm, actual["totalMargin"], "p4 totalMargin")

        for ccy in db:
            for key in ["K", "S", "CR"]:
                assert_close(db[ccy][key], actual["deltaBuckets"][ccy][key], f"p4 delta {ccy}.{key}")

        for ccy in cb:
            assert ccy in actual["curvatureBuckets"], f"p4 missing curvature bucket {ccy}"
            for key in ["K", "sumCVR", "lambda", "margin"]:
                assert_close(cb[ccy][key], actual["curvatureBuckets"][ccy][key], f"p4 curv {ccy}.{key}")

    def test_portfolio_5_complex_mixed(self):
        """Portfolio 5: Multi-ccy, multi-subcurve delta+curvature. Full integration test."""
        path = os.path.join(PORTFOLIO_DIR, "portfolio_5.csv")
        db, dm, cb, cm, tm = compute_all_reference(path)
        actual = run_java(path)

        assert_close(dm, actual["deltaMargin"], "p5 deltaMargin")
        assert_close(cm, actual["curvatureMargin"], "p5 curvatureMargin")
        assert_close(tm, actual["totalMargin"], "p5 totalMargin")

        for ccy in db:
            assert ccy in actual["deltaBuckets"], f"p5 missing delta bucket {ccy}"
            for key in ["K", "S", "CR"]:
                assert_close(db[ccy][key], actual["deltaBuckets"][ccy][key], f"p5 delta {ccy}.{key}")

        for ccy in cb:
            assert ccy in actual["curvatureBuckets"], f"p5 missing curvature bucket {ccy}"
            for key in ["K", "sumCVR", "lambda", "margin"]:
                assert_close(cb[ccy][key], actual["curvatureBuckets"][ccy][key], f"p5 curv {ccy}.{key}")

    def test_output_json_structure(self):
        """Verify output JSON has all required top-level and nested keys."""
        path = os.path.join(PORTFOLIO_DIR, "portfolio_4.csv")
        actual = run_java(path)

        for key in ["deltaBuckets", "deltaMargin", "curvatureBuckets", "curvatureMargin", "totalMargin"]:
            assert key in actual, f"Missing top-level key: {key}"

        assert isinstance(actual["deltaMargin"], (int, float))
        assert isinstance(actual["curvatureMargin"], (int, float))
        assert isinstance(actual["totalMargin"], (int, float))

        for ccy, bucket in actual["deltaBuckets"].items():
            for key in ["K", "S", "CR"]:
                assert key in bucket, f"Delta bucket {ccy} missing '{key}'"

        for ccy, bucket in actual["curvatureBuckets"].items():
            for key in ["K", "sumCVR", "lambda", "margin"]:
                assert key in bucket, f"Curvature bucket {ccy} missing '{key}'"

    def test_concentration_risk_triggers(self):
        """BRL in portfolio 3 should have CR > 1.0 due to large net sensitivity."""
        path = os.path.join(PORTFOLIO_DIR, "portfolio_3.csv")
        db, _, _, _, _ = compute_all_reference(path)
        actual = run_java(path)

        assert actual["deltaBuckets"]["BRL"]["CR"] > 1.0, (
            f"BRL CR should be > 1.0, got {actual['deltaBuckets']['BRL']['CR']}"
        )
        assert_close(
            db["BRL"]["CR"], actual["deltaBuckets"]["BRL"]["CR"],
            "p3 BRL.CR"
        )

    def test_curvature_margin_nonzero(self):
        """Portfolio 4 must produce nonzero curvature margin."""
        path = os.path.join(PORTFOLIO_DIR, "portfolio_4.csv")
        actual = run_java(path)
        assert actual["curvatureMargin"] > 0.1, (
            f"Curvature margin should be significantly positive, got {actual['curvatureMargin']}"
        )

    def test_total_margin_greater_than_delta_when_curvature_present(self):
        """With curvature present, total margin must exceed delta margin."""
        path = os.path.join(PORTFOLIO_DIR, "portfolio_4.csv")
        actual = run_java(path)
        assert actual["totalMargin"] > actual["deltaMargin"], (
            f"totalMargin ({actual['totalMargin']}) should exceed "
            f"deltaMargin ({actual['deltaMargin']})"
        )

    def test_delta_bucket_keys_sorted(self):
        """Delta bucket keys must be sorted alphabetically."""
        path = os.path.join(PORTFOLIO_DIR, "portfolio_5.csv")
        result = subprocess.run(
            ["java", "-cp", "/app/out", "Main", path],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip()
        data = json.loads(output)
        delta_keys = list(data["deltaBuckets"].keys())
        assert delta_keys == sorted(delta_keys), (
            f"Delta bucket keys not sorted: {delta_keys}"
        )
        curv_keys = list(data["curvatureBuckets"].keys())
        assert curv_keys == sorted(curv_keys), (
            f"Curvature bucket keys not sorted: {curv_keys}"
        )
