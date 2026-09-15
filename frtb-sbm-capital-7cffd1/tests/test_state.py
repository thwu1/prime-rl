"""
FRTB SBM Capital Calculator - Verification Tests

"""

import json
import math
import os
import sqlite3
import subprocess
import pytest

REPORT_PATH = "/app/output/capital_report.json"
DB_PATH = "/app/parameters.db"
TOLERANCE = 0.5
TOTAL_TOLERANCE = 1.5


def load_report():
    assert os.path.exists(REPORT_PATH), (
        f"Output file {REPORT_PATH} does not exist. "
        "Did you create and run /app/run.sh?"
    )
    with open(REPORT_PATH) as f:
        return json.load(f)


# ---------- Reference computation for golden values ----------
# All reference data is loaded from the same JSON portfolio and TSV files
# that the solver must use, ensuring test parity.

def _load_portfolio():
    """Load portfolio from JSON file."""
    with open("/app/portfolio.json") as f:
        return json.load(f)


def _load_tsv(path):
    """Load TSV file, return list of dicts."""
    rows = []
    with open(path) as f:
        header = f.readline().strip().split("\t")
        for line in f:
            vals = line.strip().split("\t")
            rows.append(dict(zip(header, vals)))
    return rows


def _apply_scenario(rho, scenario):
    if scenario == "medium":
        return rho
    elif scenario == "high":
        return min(rho * 1.25, 1.0)
    elif scenario == "low":
        return max(2.0 * rho - 1.0, 0.75 * rho)


def _within_bucket(ws_list, corr_fn):
    n = len(ws_list)
    total = 0.0
    for k in range(n):
        total += ws_list[k] ** 2
        for l in range(n):
            if k != l:
                total += corr_fn(k, l) * ws_list[k] * ws_list[l]
    return math.sqrt(max(0.0, total))


def _across_bucket(K_list, S_list, gamma_fn):
    n = len(K_list)
    total = sum(k ** 2 for k in K_list)
    for b in range(n):
        for c in range(n):
            if b != c:
                total += gamma_fn(b, c) * S_list[b] * S_list[c]
    if total < 0:
        S_capped = [max(min(S_list[i], K_list[i]), -K_list[i]) for i in range(n)]
        total = sum(k ** 2 for k in K_list)
        for b in range(n):
            for c in range(n):
                if b != c:
                    total += gamma_fn(b, c) * S_capped[b] * S_capped[c]
    return math.sqrt(max(0.0, total))


def _ref_equity_delta(portfolio, scenario):
    positions = portfolio["equity_delta"]
    eq_rw = {}
    for r in _load_tsv("/app/reg_tables/equity_risk_weights.tsv"):
        eq_rw[int(r["bucket"])] = float(r["risk_weight"])

    eq_intra = {}
    for r in _load_tsv("/app/reg_tables/equity_intra_corr.tsv"):
        b = int(r["bucket"])
        val = r["intra_bucket_correlation"]
        if val != "N/A":
            eq_intra[b] = float(val)

    cross_rows = _load_tsv("/app/reg_tables/equity_cross_corr.tsv")
    cross_rules = {r["rule"]: r["correlation"] for r in cross_rows}
    other_bucket = int(cross_rules["other_sector_bucket"])

    buckets = {}
    for p in positions:
        b = p["bucket"]
        buckets.setdefault(b, []).append(p["sensitivity"])

    ws_by_bucket = {}
    for b, senss in buckets.items():
        rw = eq_rw[b]
        ws_by_bucket[b] = [s * rw for s in senss]

    K_values = {}
    S_values = {}
    for b, ws_list in ws_by_bucket.items():
        if b == other_bucket:
            K_values[b] = sum(abs(ws) for ws in ws_list)
            S_values[b] = sum(ws_list)
        else:
            rho = _apply_scenario(eq_intra.get(b, 0.0), scenario)
            K_values[b] = _within_bucket(ws_list, lambda k, l, _r=rho: _r)
            S_values[b] = sum(ws_list)

    bucket_ids = sorted(K_values.keys())

    def gamma_fn(bi_idx, bj_idx):
        bi, bj = bucket_ids[bi_idx], bucket_ids[bj_idx]
        if bi == other_bucket or bj == other_bucket:
            base = 0.0
        elif 1 <= bi <= 10 and 1 <= bj <= 10:
            base = float(cross_rules["both_in_1_to_10"])
        elif {bi, bj} == {12, 13}:
            base = float(cross_rules["between_12_and_13"])
        else:
            base = float(cross_rules.get("index_to_sector", "0.45"))
        return _apply_scenario(base, scenario) if base > 0 else 0.0

    K_list = [K_values[b] for b in bucket_ids]
    S_list = [S_values[b] for b in bucket_ids]
    return _across_bucket(K_list, S_list, gamma_fn)


def _ref_fx_delta(portfolio, scenario):
    positions = portfolio["fx_delta"]
    fx_rows = _load_tsv("/app/reg_tables/fx_params.tsv")
    fx_params = {r["parameter"]: r["value"] for r in fx_rows}
    rw = float(fx_params["risk_weight"])
    gamma_base = float(fx_params["cross_bucket_correlation"])

    ws = {p["currency"]: p["sensitivity"] * rw for p in positions}
    currencies = sorted(ws.keys())
    K_list = [abs(ws[c]) for c in currencies]
    S_list = [ws[c] for c in currencies]
    gamma = _apply_scenario(gamma_base, scenario)
    return _across_bucket(K_list, S_list, lambda b, c: gamma)


def _ref_girr_delta(portfolio, scenario):
    positions = portfolio["girr_delta"]
    config = portfolio["config"]

    girr_rw_rows = _load_tsv("/app/reg_tables/girr_risk_weights.tsv")
    rw_map = {}
    for r in girr_rw_rows:
        rw_map[r["tenor"]] = float(r["risk_weight"])

    corr_rows = _load_tsv("/app/reg_tables/girr_correlation.tsv")
    corr_params = {r["parameter"]: r["value"] for r in corr_rows}

    theta = float(corr_params["theta"])
    floor = float(corr_params["floor"])
    same_tenor_diff = float(corr_params["same_tenor_different_curve"])
    diff_tenor_diff = float(corr_params["different_tenor_different_curve_factor"])
    inf_to_yield = float(corr_params["inflation_to_yield_curve"])
    xccy_to_any = float(corr_params["xccy_basis_to_any"])
    gamma_base = float(corr_params["cross_bucket_correlation"])
    spec_currencies = set(corr_params["specified_currencies"].split(","))
    divisor = float(corr_params["specified_currency_rw_divisor"])

    use_reduction = config.get("girr_specified_currency_reduction", "false") == "true"

    by_currency = {}
    for p in positions:
        ccy = p["currency"]
        by_currency.setdefault(ccy, []).append(p)

    K_values = {}
    S_values = {}

    for ccy, poss in by_currency.items():
        is_specified = ccy in spec_currencies
        div = divisor if (is_specified and use_reduction) else 1.0

        ws_list = []
        factor_types = []
        tenors = []
        curves = []

        for p in poss:
            v = p["vertex"]
            if v == "inflation":
                rw = rw_map["inflation"] / div
                ws_list.append(p["sensitivity"] * rw)
                factor_types.append("inflation")
                tenors.append(None)
                curves.append(None)
            elif v == "xccy_basis":
                rw = rw_map["xccy_basis"] / div
                ws_list.append(p["sensitivity"] * rw)
                factor_types.append("xccy_basis")
                tenors.append(None)
                curves.append(None)
            else:
                tenor_str = v.replace("Y", "")
                tenor_val = float(tenor_str)
                tenor_key = str(int(tenor_val)) if tenor_val == int(tenor_val) else tenor_str
                rw = rw_map[tenor_key] / div
                ws_list.append(p["sensitivity"] * rw)
                factor_types.append("tenor")
                tenors.append(tenor_val)
                curves.append(p["curve"])

        def corr_fn(k, l, _ft=factor_types, _t=tenors, _c=curves):
            fk, fl = _ft[k], _ft[l]
            if fk == "xccy_basis" or fl == "xccy_basis":
                base_rho = xccy_to_any
            elif fk == "inflation" or fl == "inflation":
                base_rho = inf_to_yield
            else:
                tk, tl = _t[k], _t[l]
                same_curve = (_c[k] == _c[l])
                tenor_corr = max(math.exp(-theta * abs(tk - tl) / min(tk, tl)), floor)
                if same_curve:
                    base_rho = tenor_corr
                elif tk == tl:
                    base_rho = same_tenor_diff
                else:
                    base_rho = tenor_corr * diff_tenor_diff
            return _apply_scenario(base_rho, scenario)

        K_values[ccy] = _within_bucket(ws_list, corr_fn)
        S_values[ccy] = sum(ws_list)

    currencies = sorted(K_values.keys())
    if len(currencies) == 1:
        return K_values[currencies[0]]

    gamma = _apply_scenario(gamma_base, scenario)
    K_list = [K_values[c] for c in currencies]
    S_list = [S_values[c] for c in currencies]
    return _across_bucket(K_list, S_list, lambda b, c: gamma)


def _ref_csr_nonsec_delta(portfolio, scenario):
    positions = portfolio["csr_nonsec_delta"]
    rw_rows = _load_tsv("/app/reg_tables/csr_nonsec_risk_weights.tsv")
    rw_map = {int(r["bucket"]): float(r["risk_weight"]) for r in rw_rows}

    intra_rows = _load_tsv("/app/reg_tables/csr_nonsec_intra_corr.tsv")
    intra_defs = {}
    for r in intra_rows:
        br = r["bucket_range"]
        if r["rho_name_same"] == "sum_of_absolute_values":
            intra_defs[br] = "sum_abs"
        else:
            intra_defs[br] = {
                "rho_name_same": float(r["rho_name_same"]),
                "rho_name_diff": float(r["rho_name_diff"]),
                "rho_tenor_same": float(r["rho_tenor_same"]),
                "rho_tenor_diff": float(r["rho_tenor_diff"]),
                "rho_basis_same": float(r["rho_basis_same"]),
                "rho_basis_diff": float(r["rho_basis_diff"]),
            }

    cross_rows = _load_tsv("/app/reg_tables/csr_nonsec_cross_corr.tsv")
    ig_set = set()
    hy_set = set()
    sector_map = {}
    sector_corr = {}
    cross_special = {}
    for r in cross_rows:
        t = r["type"]
        if t == "ig_buckets":
            ig_set = {int(x) for x in r["value"].split(",")}
        elif t == "hy_buckets":
            hy_set = {int(x) for x in r["value"].split(",")}
        elif t == "rating_same":
            cross_special["same_rating"] = float(r["value"])
        elif t == "rating_different":
            cross_special["diff_rating"] = float(r["value"])
        elif t == "sector_map":
            sector_map[int(r["key"])] = int(r["value"])
        elif t == "sector_corr":
            parts = r["key"].split("|")
            sector_corr[(int(parts[0]), int(parts[1]))] = float(r["value"])
        elif t == "bucket_16_to_any":
            cross_special["bucket_16"] = float(r["value"])
        elif t == "between_17_and_18":
            cross_special["17_18"] = float(r["value"])
        elif t == "index_to_sector":
            cross_special["idx_sector"] = float(r["value"])

    by_bucket = {}
    for p in positions:
        b = p["bucket"]
        by_bucket.setdefault(b, []).append(p)

    K_values = {}
    S_values = {}

    for b, poss in by_bucket.items():
        rw = rw_map[b]
        ws_list = [p["sensitivity"] * rw for p in poss]

        is_sum_abs = False
        if b == 16:
            is_sum_abs = True
        else:
            for br_key, br_def in intra_defs.items():
                if br_def == "sum_abs":
                    if str(b) == br_key:
                        is_sum_abs = True
                        break

        if is_sum_abs:
            K_values[b] = sum(abs(ws) for ws in ws_list)
            S_values[b] = sum(ws_list)
        else:
            if b in (17, 18):
                corr_def = intra_defs["17-18"]
            else:
                corr_def = intra_defs["1-15"]

            def corr_fn(k, l, _p=poss, _cd=corr_def):
                pk, pl = _p[k], _p[l]
                rn = _cd["rho_name_same"] if pk["issuer"] == pl["issuer"] else _cd["rho_name_diff"]
                rt = _cd["rho_tenor_same"] if pk["tenor"] == pl["tenor"] else _cd["rho_tenor_diff"]
                rb = _cd["rho_basis_same"] if pk["curve"] == pl["curve"] else _cd["rho_basis_diff"]
                return _apply_scenario(rn * rt * rb, scenario)

            K_values[b] = _within_bucket(ws_list, corr_fn)
            S_values[b] = sum(ws_list)

    bucket_ids = sorted(K_values.keys())
    if len(bucket_ids) == 1:
        return K_values[bucket_ids[0]]

    def gamma_fn(bi_idx, bj_idx):
        bi, bj = bucket_ids[bi_idx], bucket_ids[bj_idx]
        if bi == 16 or bj == 16:
            return 0.0
        bi_ig = bi in ig_set
        bj_ig = bj in ig_set
        if (bi_ig and bj_ig) or (not bi_ig and not bj_ig):
            g_rating = cross_special["same_rating"]
        else:
            g_rating = cross_special["diff_rating"]
        si = sector_map.get(bi, 0)
        sj = sector_map.get(bj, 0)
        if si == sj:
            g_sector = 1.0
        else:
            key = (min(si, sj), max(si, sj))
            g_sector = sector_corr.get(key, 0.0)
        base_gamma = g_rating * g_sector
        return _apply_scenario(base_gamma, scenario) if base_gamma > 0 else 0.0

    K_list = [K_values[b] for b in bucket_ids]
    S_list = [S_values[b] for b in bucket_ids]
    return _across_bucket(K_list, S_list, gamma_fn)


def _ref_drc(portfolio):
    positions = portfolio["equity_drc"]
    drc_rows = _load_tsv("/app/reg_tables/drc_equity_risk_weights.tsv")
    rw_map = {r["rating"]: float(r["risk_weight"]) for r in drc_rows}

    sum_long = 0.0
    sum_short_abs = 0.0
    rw_long = 0.0
    rw_short = 0.0

    for p in positions:
        jtd = p["jtd"]
        rw = rw_map[p["rating"]]
        if jtd >= 0:
            sum_long += jtd
            rw_long += rw * jtd
        else:
            sum_short_abs += abs(jtd)
            rw_short += rw * abs(jtd)

    hbr = sum_long / (sum_long + sum_short_abs) if (sum_long + sum_short_abs) > 0 else 1.0
    return max(0.0, rw_long - hbr * rw_short)


# Precompute all reference values
_PORTFOLIO = _load_portfolio()
_REF = {}
for _s in ["medium", "high", "low"]:
    _REF[("equity", _s)] = _ref_equity_delta(_PORTFOLIO, _s)
    _REF[("fx", _s)] = _ref_fx_delta(_PORTFOLIO, _s)
    _REF[("girr", _s)] = _ref_girr_delta(_PORTFOLIO, _s)
    _REF[("csr_nonsec", _s)] = _ref_csr_nonsec_delta(_PORTFOLIO, _s)

_REF["drc_equity"] = _ref_drc(_PORTFOLIO)

_REF_TOTALS = {}
for _s in ["medium", "high", "low"]:
    _REF_TOTALS[_s] = sum(
        _REF[(rc, _s)] for rc in ["equity", "fx", "girr", "csr_nonsec"]
    )

_REF_SBM_DELTA = max(_REF_TOTALS.values())
_REF_TOTAL = _REF_SBM_DELTA + _REF["drc_equity"]


# ---------- Structural tests ----------

class TestOutputStructure:
    def test_output_file_exists(self):
        assert os.path.exists(REPORT_PATH), f"{REPORT_PATH} not found"

    def test_valid_json(self):
        report = load_report()
        assert isinstance(report, dict)

    def test_has_required_top_level_keys(self):
        report = load_report()
        for key in ["delta", "drc", "scenario_totals", "sbm_delta_capital", "total_capital"]:
            assert key in report, f"Missing top-level key: {key}"

    def test_delta_has_all_risk_classes(self):
        report = load_report()
        for rc in ["equity", "fx", "girr", "csr_nonsec"]:
            assert rc in report["delta"], f"Missing risk class: {rc}"

    def test_delta_has_all_scenarios(self):
        report = load_report()
        for rc in ["equity", "fx", "girr", "csr_nonsec"]:
            for s in ["medium", "high", "low"]:
                assert s in report["delta"][rc], (
                    f"Missing scenario {s} for {rc}"
                )

    def test_drc_has_equity(self):
        report = load_report()
        assert "equity" in report["drc"]

    def test_scenario_totals_has_all_scenarios(self):
        report = load_report()
        for s in ["medium", "high", "low"]:
            assert s in report["scenario_totals"], f"Missing scenario_totals.{s}"


# ---------- Consistency tests ----------

class TestConsistency:
    def test_scenario_totals_equal_sum_of_deltas(self):
        report = load_report()
        for s in ["medium", "high", "low"]:
            expected = sum(
                report["delta"][rc][s]
                for rc in ["equity", "fx", "girr", "csr_nonsec"]
            )
            assert abs(report["scenario_totals"][s] - expected) < 0.01, (
                f"scenario_totals.{s} ({report['scenario_totals'][s]}) != "
                f"sum of deltas ({expected})"
            )

    def test_sbm_delta_is_max_scenario(self):
        report = load_report()
        max_total = max(
            report["scenario_totals"][s] for s in ["medium", "high", "low"]
        )
        assert abs(report["sbm_delta_capital"] - max_total) < 0.01, (
            f"sbm_delta_capital ({report['sbm_delta_capital']}) != "
            f"max scenario ({max_total})"
        )

    def test_total_capital_is_sum(self):
        report = load_report()
        expected = report["sbm_delta_capital"] + report["drc"]["equity"]
        assert abs(report["total_capital"] - expected) < 0.01, (
            f"total_capital ({report['total_capital']}) != "
            f"sbm_delta + drc ({expected})"
        )

    def test_all_values_positive(self):
        report = load_report()
        for rc in ["equity", "fx", "girr", "csr_nonsec"]:
            for s in ["medium", "high", "low"]:
                assert report["delta"][rc][s] >= 0, (
                    f"delta.{rc}.{s} is negative"
                )
        assert report["drc"]["equity"] >= 0
        assert report["sbm_delta_capital"] >= 0
        assert report["total_capital"] >= 0

    def test_low_scenario_produces_max_total(self):
        """For this portfolio, the low correlation scenario should produce the highest total."""
        report = load_report()
        assert report["scenario_totals"]["low"] >= report["scenario_totals"]["medium"] - TOTAL_TOLERANCE
        assert report["scenario_totals"]["low"] >= report["scenario_totals"]["high"] - TOTAL_TOLERANCE


# ---------- Numerical accuracy: Equity Delta ----------

class TestEquityDelta:
    def test_medium(self):
        report = load_report()
        assert abs(report["delta"]["equity"]["medium"] - _REF[("equity", "medium")]) < TOLERANCE

    def test_high(self):
        report = load_report()
        assert abs(report["delta"]["equity"]["high"] - _REF[("equity", "high")]) < TOLERANCE

    def test_low(self):
        report = load_report()
        assert abs(report["delta"]["equity"]["low"] - _REF[("equity", "low")]) < TOLERANCE

    def test_low_is_max_equity_scenario(self):
        report = load_report()
        eq = report["delta"]["equity"]
        assert eq["low"] >= eq["medium"] - TOLERANCE
        assert eq["low"] >= eq["high"] - TOLERANCE


# ---------- Numerical accuracy: FX Delta ----------

class TestFxDelta:
    def test_medium(self):
        report = load_report()
        assert abs(report["delta"]["fx"]["medium"] - _REF[("fx", "medium")]) < TOLERANCE

    def test_high(self):
        report = load_report()
        assert abs(report["delta"]["fx"]["high"] - _REF[("fx", "high")]) < TOLERANCE

    def test_low(self):
        report = load_report()
        assert abs(report["delta"]["fx"]["low"] - _REF[("fx", "low")]) < TOLERANCE


# ---------- Numerical accuracy: GIRR Delta ----------

class TestGirrDelta:
    def test_medium(self):
        report = load_report()
        assert abs(report["delta"]["girr"]["medium"] - _REF[("girr", "medium")]) < TOLERANCE

    def test_high(self):
        report = load_report()
        assert abs(report["delta"]["girr"]["high"] - _REF[("girr", "high")]) < TOLERANCE

    def test_low(self):
        report = load_report()
        assert abs(report["delta"]["girr"]["low"] - _REF[("girr", "low")]) < TOLERANCE

    def test_multi_currency_girr_exceeds_single(self):
        """With two currencies, GIRR capital should be > max single-currency K_b."""
        report = load_report()
        assert report["delta"]["girr"]["medium"] > 100.0, (
            "GIRR capital suspiciously low; multi-currency aggregation may be wrong"
        )


# ---------- Numerical accuracy: CSR Non-Sec Delta ----------

class TestCsrNonsecDelta:
    def test_medium(self):
        report = load_report()
        assert abs(report["delta"]["csr_nonsec"]["medium"] - _REF[("csr_nonsec", "medium")]) < TOLERANCE

    def test_high(self):
        report = load_report()
        assert abs(report["delta"]["csr_nonsec"]["high"] - _REF[("csr_nonsec", "high")]) < TOLERANCE

    def test_low(self):
        report = load_report()
        assert abs(report["delta"]["csr_nonsec"]["low"] - _REF[("csr_nonsec", "low")]) < TOLERANCE

    def test_csr_includes_residual_bucket(self):
        """CSR should include bucket 16 (residual) contribution; capital > bucket 3 alone."""
        report = load_report()
        assert report["delta"]["csr_nonsec"]["medium"] > 55.0, (
            "CSR capital too low; residual bucket may be missing"
        )


# ---------- Numerical accuracy: DRC ----------

class TestDrc:
    def test_equity_drc(self):
        report = load_report()
        assert abs(report["drc"]["equity"] - _REF["drc_equity"]) < TOLERANCE

    def test_drc_positive(self):
        report = load_report()
        assert report["drc"]["equity"] > 0, "DRC should be positive for this portfolio"


# ---------- Numerical accuracy: Totals ----------

class TestTotals:
    def test_sbm_delta_capital(self):
        report = load_report()
        assert abs(report["sbm_delta_capital"] - _REF_SBM_DELTA) < TOTAL_TOLERANCE

    def test_total_capital(self):
        report = load_report()
        assert abs(report["total_capital"] - _REF_TOTAL) < TOTAL_TOLERANCE

    def test_scenario_total_medium(self):
        report = load_report()
        assert abs(report["scenario_totals"]["medium"] - _REF_TOTALS["medium"]) < TOTAL_TOLERANCE

    def test_scenario_total_high(self):
        report = load_report()
        assert abs(report["scenario_totals"]["high"] - _REF_TOTALS["high"]) < TOTAL_TOLERANCE

    def test_scenario_total_low(self):
        report = load_report()
        assert abs(report["scenario_totals"]["low"] - _REF_TOTALS["low"]) < TOTAL_TOLERANCE

    def test_total_capital_range(self):
        """Sanity check: total capital for this portfolio should be in a reasonable range."""
        report = load_report()
        assert 350.0 < report["total_capital"] < 550.0, (
            f"total_capital={report['total_capital']} outside expected range 350-550"
        )


# ---------- Schema validation via jq ----------

class TestSchemaValidation:
    def test_output_parseable_by_jq(self):
        """Verify the output JSON is valid and has expected structure via subprocess."""
        result = subprocess.run(
            ["jq", "-e",
             '.delta.equity.medium and .delta.fx.medium and '
             '.delta.girr.medium and .delta.csr_nonsec.medium and '
             '.drc.equity and .scenario_totals.medium and '
             '.sbm_delta_capital and .total_capital',
             REPORT_PATH],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"jq validation failed: {result.stderr}"
        )


# ---------- SQLite Database: Existence and Structure ----------

class TestSQLiteDatabase:
    def test_database_file_exists(self):
        """The parameters.db file must exist at /app/parameters.db."""
        assert os.path.exists(DB_PATH), (
            f"{DB_PATH} not found. The pipeline must produce a SQLite database."
        )

    def test_database_is_valid_sqlite(self):
        """The file must be a valid SQLite database with tables."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            assert len(tables) > 0, "Database contains no tables"
        finally:
            conn.close()

    def test_all_parameter_tables_exist(self):
        """One table per regulatory TSV file must be present."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()
        expected = {
            "equity_risk_weights",
            "equity_intra_corr",
            "equity_cross_corr",
            "fx_params",
            "girr_risk_weights",
            "girr_correlation",
            "csr_nonsec_risk_weights",
            "csr_nonsec_intra_corr",
            "csr_nonsec_cross_corr",
            "drc_equity_risk_weights",
        }
        missing = expected - tables
        assert not missing, f"Missing parameter tables: {missing}"

    def test_audit_tables_exist(self):
        """audit_buckets and audit_scenarios tables must exist."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()
        assert "audit_buckets" in tables, "Missing table: audit_buckets"
        assert "audit_scenarios" in tables, "Missing table: audit_scenarios"


# ---------- SQLite Database: Parameter Data Integrity ----------

class TestSQLiteParameterData:
    def test_equity_rw_bucket_count(self):
        """equity_risk_weights must have 13 rows (buckets 1-13)."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM equity_risk_weights")
            count = cursor.fetchone()[0]
        finally:
            conn.close()
        assert count == 13, f"Expected 13 equity RW rows, got {count}"

    def test_equity_rw_bucket6_value(self):
        """Spot check: equity bucket 6 risk weight should be 0.35."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT risk_weight FROM equity_risk_weights WHERE bucket = '6'"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None, "No row for equity bucket 6"
        assert abs(float(row[0]) - 0.35) < 0.001, (
            f"Equity bucket 6 RW expected 0.35, got {row[0]}"
        )

    def test_equity_rw_bucket9_value(self):
        """Spot check: equity bucket 9 risk weight should be 0.70."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT risk_weight FROM equity_risk_weights WHERE bucket = '9'"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None, "No row for equity bucket 9"
        assert abs(float(row[0]) - 0.70) < 0.001

    def test_girr_rw_data(self):
        """Spot check: GIRR tenor 1 risk weight should be 0.016."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT risk_weight FROM girr_risk_weights WHERE tenor = '1'"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None, "No row for GIRR tenor 1"
        assert abs(float(row[0]) - 0.016) < 0.001

    def test_girr_rw_row_count(self):
        """GIRR risk weights should have 12 rows (10 tenors + inflation + xccy_basis)."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM girr_risk_weights")
            count = cursor.fetchone()[0]
        finally:
            conn.close()
        assert count == 12, f"Expected 12 GIRR RW rows, got {count}"

    def test_fx_params_risk_weight(self):
        """FX risk weight should be 0.15."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT value FROM fx_params WHERE parameter = 'risk_weight'"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None, "No risk_weight row in fx_params"
        assert abs(float(row[0]) - 0.15) < 0.001

    def test_fx_params_cross_corr(self):
        """FX cross-bucket correlation should be 0.60."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT value FROM fx_params WHERE parameter = 'cross_bucket_correlation'"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None
        assert abs(float(row[0]) - 0.60) < 0.001

    def test_drc_rw_bbb(self):
        """DRC BBB risk weight should be 0.06."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT risk_weight FROM drc_equity_risk_weights WHERE rating = 'BBB'"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None, "No DRC row for rating BBB"
        assert abs(float(row[0]) - 0.06) < 0.001

    def test_drc_rw_row_count(self):
        """DRC risk weights should have 9 rows."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM drc_equity_risk_weights"
            )
            count = cursor.fetchone()[0]
        finally:
            conn.close()
        assert count == 9, f"Expected 9 DRC RW rows, got {count}"

    def test_csr_nonsec_rw_row_count(self):
        """CSR non-sec risk weights should have 18 rows (buckets 1-18)."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM csr_nonsec_risk_weights"
            )
            count = cursor.fetchone()[0]
        finally:
            conn.close()
        assert count == 18, f"Expected 18 CSR RW rows, got {count}"

    def test_csr_nonsec_rw_bucket1_value(self):
        """CSR bucket 1 (sovereign IG) risk weight should be 0.005."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT risk_weight FROM csr_nonsec_risk_weights WHERE bucket = '1'"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None
        assert abs(float(row[0]) - 0.005) < 0.0001

    def test_equity_intra_corr_count(self):
        """Equity intra-bucket correlation table should have 13 rows."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM equity_intra_corr"
            )
            count = cursor.fetchone()[0]
        finally:
            conn.close()
        assert count == 13, f"Expected 13 equity intra-corr rows, got {count}"

    def test_girr_corr_theta(self):
        """GIRR correlation theta should be 0.03."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT value FROM girr_correlation WHERE parameter = 'theta'"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None
        assert abs(float(row[0]) - 0.03) < 0.001


# ---------- SQLite Database: Audit Tables ----------

class TestAuditBuckets:
    def test_audit_buckets_populated(self):
        """audit_buckets must have rows for all (risk_class, bucket, scenario) triples."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM audit_buckets")
            count = cursor.fetchone()[0]
        finally:
            conn.close()
        # Portfolio has: equity (4 buckets), fx (3 currencies), girr (2 currencies),
        # csr_nonsec (3 buckets) × 3 scenarios = (4+3+2+3)*3 = 36
        assert count >= 36, (
            f"audit_buckets has only {count} rows, expected at least 36"
        )

    def test_audit_buckets_has_all_risk_classes(self):
        """All four risk classes must appear in audit_buckets."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT DISTINCT risk_class FROM audit_buckets"
            )
            classes = {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()
        expected = {"equity", "fx", "girr", "csr_nonsec"}
        missing = expected - classes
        assert not missing, f"Missing risk classes in audit_buckets: {missing}"

    def test_audit_buckets_has_all_scenarios(self):
        """All three scenarios must appear in audit_buckets."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT DISTINCT scenario FROM audit_buckets"
            )
            scenarios = {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()
        expected = {"medium", "high", "low"}
        missing = expected - scenarios
        assert not missing, f"Missing scenarios in audit_buckets: {missing}"

    def test_audit_buckets_kb_nonnegative(self):
        """All within-bucket K_b values must be non-negative."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT risk_class, bucket_id, scenario, kb "
                "FROM audit_buckets WHERE kb < 0"
            )
            negative = cursor.fetchall()
        finally:
            conn.close()
        assert len(negative) == 0, (
            f"Negative K_b values found: {negative}"
        )

    def test_audit_equity_bucket9_medium(self):
        """Equity bucket 9: single position 100, RW=0.70, so K_b=70.0."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT kb, sb FROM audit_buckets "
                "WHERE risk_class = 'equity' AND bucket_id = '9' AND scenario = 'medium'"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None, "No audit row for equity bucket 9 medium"
        assert abs(float(row[0]) - 70.0) < TOLERANCE, (
            f"equity bucket 9 K_b expected ~70.0, got {row[0]}"
        )
        assert abs(float(row[1]) - 70.0) < TOLERANCE, (
            f"equity bucket 9 S_b expected ~70.0, got {row[1]}"
        )

    def test_audit_equity_bucket11_sum_abs(self):
        """Equity bucket 11: single position 80, RW=0.70, sum-of-abs → K_b=56.0."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT kb FROM audit_buckets "
                "WHERE risk_class = 'equity' AND bucket_id = '11' AND scenario = 'medium'"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None, "No audit row for equity bucket 11"
        assert abs(float(row[0]) - 56.0) < TOLERANCE, (
            f"equity bucket 11 K_b expected ~56.0, got {row[0]}"
        )

    def test_audit_fx_eur_medium(self):
        """FX EUR: single position 400, RW=0.15, so K_b=60.0, S_b=60.0."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT kb, sb FROM audit_buckets "
                "WHERE risk_class = 'fx' AND bucket_id = 'EUR' AND scenario = 'medium'"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None, "No audit row for FX EUR medium"
        assert abs(float(row[0]) - 60.0) < TOLERANCE
        assert abs(float(row[1]) - 60.0) < TOLERANCE

    def test_audit_fx_jpy_medium(self):
        """FX JPY: single position -300, RW=0.15, so K_b=45.0, S_b=-45.0."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT kb, sb FROM audit_buckets "
                "WHERE risk_class = 'fx' AND bucket_id = 'JPY' AND scenario = 'medium'"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None, "No audit row for FX JPY medium"
        assert abs(float(row[0]) - 45.0) < TOLERANCE
        assert abs(float(row[1]) - (-45.0)) < TOLERANCE


class TestAuditScenarios:
    def test_audit_scenarios_row_count(self):
        """audit_scenarios must have exactly 12 rows: 4 risk classes × 3 scenarios."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM audit_scenarios")
            count = cursor.fetchone()[0]
        finally:
            conn.close()
        assert count == 12, f"Expected 12 audit_scenarios rows, got {count}"

    def test_audit_scenarios_match_report(self):
        """audit_scenarios capital values must match capital_report.json delta values."""
        report = load_report()
        conn = sqlite3.connect(DB_PATH)
        try:
            for rc in ["equity", "fx", "girr", "csr_nonsec"]:
                for s in ["medium", "high", "low"]:
                    cursor = conn.execute(
                        "SELECT capital FROM audit_scenarios "
                        "WHERE risk_class = ? AND scenario = ?",
                        (rc, s)
                    )
                    row = cursor.fetchone()
                    assert row is not None, (
                        f"No audit_scenarios row for {rc}/{s}"
                    )
                    db_val = float(row[0])
                    report_val = report["delta"][rc][s]
                    assert abs(db_val - report_val) < 0.01, (
                        f"audit_scenarios {rc}/{s}: {db_val} != "
                        f"report {report_val}"
                    )
        finally:
            conn.close()

    def test_audit_scenarios_match_reference(self):
        """audit_scenarios values must match independently computed reference values."""
        conn = sqlite3.connect(DB_PATH)
        try:
            for rc in ["equity", "fx", "girr", "csr_nonsec"]:
                for s in ["medium", "high", "low"]:
                    cursor = conn.execute(
                        "SELECT capital FROM audit_scenarios "
                        "WHERE risk_class = ? AND scenario = ?",
                        (rc, s)
                    )
                    row = cursor.fetchone()
                    assert row is not None
                    db_val = float(row[0])
                    ref_val = _REF[(rc, s)]
                    assert abs(db_val - ref_val) < TOLERANCE, (
                        f"audit_scenarios {rc}/{s}: {db_val} does not match "
                        f"reference {ref_val}"
                    )
        finally:
            conn.close()


# ---------- Cross-artifact consistency: SQLite ↔ jq ↔ JSON ----------

class TestCrossArtifactConsistency:
    def test_jq_extract_matches_sqlite(self):
        """Extract values from JSON via jq and verify they match SQLite audit."""
        result = subprocess.run(
            ["jq", "-r",
             '[.delta.equity.medium, .delta.fx.medium, '
             '.delta.girr.medium, .delta.csr_nonsec.medium] | @tsv',
             REPORT_PATH],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"jq extraction failed: {result.stderr}"
        jq_values = [float(v) for v in result.stdout.strip().split("\t")]

        conn = sqlite3.connect(DB_PATH)
        try:
            for i, rc in enumerate(["equity", "fx", "girr", "csr_nonsec"]):
                cursor = conn.execute(
                    "SELECT capital FROM audit_scenarios "
                    "WHERE risk_class = ? AND scenario = 'medium'",
                    (rc,)
                )
                row = cursor.fetchone()
                assert row is not None
                db_val = float(row[0])
                assert abs(jq_values[i] - db_val) < 0.01, (
                    f"{rc} medium: jq={jq_values[i]}, sqlite={db_val}"
                )
        finally:
            conn.close()

    def test_sqlite_cli_queryable(self):
        """Verify the database is queryable via sqlite3 CLI (not just Python API)."""
        result = subprocess.run(
            ["sqlite3", DB_PATH,
             "SELECT COUNT(*) FROM audit_scenarios WHERE capital > 0;"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"sqlite3 CLI query failed: {result.stderr}"
        )
        count = int(result.stdout.strip())
        assert count >= 8, (
            f"Expected at least 8 positive audit_scenarios, got {count}"
        )
