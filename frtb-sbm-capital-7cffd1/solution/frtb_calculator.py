#!/usr/bin/env python3
"""
FRTB Standardised Approach SBM Capital Calculator
Reference implementation for Basel d457 MAR21/MAR22

Reads regulatory parameters from SQLite database (parameters.db)
and portfolio from JSON. Writes audit data back to the database.

"""

import json
import math
import os
import sqlite3


DB_PATH = "/app/parameters.db"
PORTFOLIO_PATH = "/app/portfolio.json"
OUTPUT_DIR = "/app/output"


def load_portfolio(json_path):
    with open(json_path) as f:
        return json.load(f)


def load_params_from_db(db_path):
    """Load all regulatory parameters by querying the SQLite database."""
    conn = sqlite3.connect(db_path)
    params = {}

    # Equity risk weights
    cursor = conn.execute("SELECT bucket, risk_weight FROM equity_risk_weights")
    params["equity_rw"] = {int(row[0]): float(row[1]) for row in cursor}

    # Equity intra-bucket correlations
    cursor = conn.execute(
        "SELECT bucket, intra_bucket_correlation FROM equity_intra_corr"
    )
    eq_intra = {}
    for row in cursor:
        b = int(row[0])
        val = row[1]
        if val != "N/A":
            eq_intra[b] = float(val)
    params["equity_intra_corr"] = eq_intra

    # Equity cross-bucket correlations
    cursor = conn.execute("SELECT rule, correlation FROM equity_cross_corr")
    eq_cross = {row[0]: row[1] for row in cursor}
    params["equity_cross"] = eq_cross
    params["equity_other_bucket"] = int(eq_cross["other_sector_bucket"])

    # FX parameters
    cursor = conn.execute("SELECT parameter, value FROM fx_params")
    fx_p = {row[0]: row[1] for row in cursor}
    params["fx_rw"] = float(fx_p["risk_weight"])
    params["fx_cross_corr"] = float(fx_p["cross_bucket_correlation"])
    params["fx_divisor"] = float(fx_p["specified_pair_rw_divisor"])
    params["fx_specified_pairs"] = fx_p["specified_currency_pairs"].split(",")

    # GIRR risk weights
    cursor = conn.execute("SELECT tenor, risk_weight FROM girr_risk_weights")
    params["girr_rw"] = {row[0]: float(row[1]) for row in cursor}

    # GIRR correlation parameters
    cursor = conn.execute("SELECT parameter, value FROM girr_correlation")
    corr_p = {row[0]: row[1] for row in cursor}
    params["girr_theta"] = float(corr_p["theta"])
    params["girr_floor"] = float(corr_p["floor"])
    params["girr_same_tenor_diff_curve"] = float(
        corr_p["same_tenor_different_curve"]
    )
    params["girr_diff_tenor_diff_curve"] = float(
        corr_p["different_tenor_different_curve_factor"]
    )
    params["girr_inf_to_yield"] = float(corr_p["inflation_to_yield_curve"])
    params["girr_xccy_to_any"] = float(corr_p["xccy_basis_to_any"])
    params["girr_cross_bucket_corr"] = float(
        corr_p["cross_bucket_correlation"]
    )
    params["girr_spec_currencies"] = set(
        corr_p["specified_currencies"].split(",")
    )
    params["girr_divisor"] = float(corr_p["specified_currency_rw_divisor"])

    # CSR non-sec risk weights
    cursor = conn.execute(
        "SELECT bucket, risk_weight FROM csr_nonsec_risk_weights"
    )
    params["csr_rw"] = {int(row[0]): float(row[1]) for row in cursor}

    # CSR non-sec intra-bucket correlations
    cursor = conn.execute("SELECT * FROM csr_nonsec_intra_corr")
    columns = [desc[0] for desc in cursor.description]
    csr_intra = {}
    for row in cursor:
        r = dict(zip(columns, row))
        br = r["bucket_range"]
        if r["rho_name_same"] == "sum_of_absolute_values":
            csr_intra[br] = "sum_abs"
        else:
            csr_intra[br] = {
                "rho_name_same": float(r["rho_name_same"]),
                "rho_name_diff": float(r["rho_name_diff"]),
                "rho_tenor_same": float(r["rho_tenor_same"]),
                "rho_tenor_diff": float(r["rho_tenor_diff"]),
                "rho_basis_same": float(r["rho_basis_same"]),
                "rho_basis_diff": float(r["rho_basis_diff"]),
            }
    params["csr_intra"] = csr_intra

    # CSR non-sec cross-bucket correlations
    cursor = conn.execute("SELECT type, key, value FROM csr_nonsec_cross_corr")
    csr_cross = {
        "ig_set": set(),
        "hy_set": set(),
        "sector_map": {},
        "sector_corr": {},
    }
    for row in cursor:
        t, key, val = row[0], row[1], row[2]
        if t == "ig_buckets":
            csr_cross["ig_set"] = {int(x) for x in val.split(",")}
        elif t == "hy_buckets":
            csr_cross["hy_set"] = {int(x) for x in val.split(",")}
        elif t == "rating_same":
            csr_cross["same_rating"] = float(val)
        elif t == "rating_different":
            csr_cross["diff_rating"] = float(val)
        elif t == "sector_map":
            csr_cross["sector_map"][int(key)] = int(val)
        elif t == "sector_corr":
            parts = key.split("|")
            csr_cross["sector_corr"][
                (int(parts[0]), int(parts[1]))
            ] = float(val)
        elif t == "bucket_16_to_any":
            csr_cross["bucket_16"] = float(val)
        elif t == "between_17_and_18":
            csr_cross["17_18"] = float(val)
        elif t == "index_to_sector":
            csr_cross["idx_sector"] = float(val)
    params["csr_cross"] = csr_cross

    # DRC risk weights
    cursor = conn.execute(
        "SELECT rating, risk_weight FROM drc_equity_risk_weights"
    )
    params["drc_rw"] = {row[0]: float(row[1]) for row in cursor}

    conn.close()
    return params


def apply_scenario(rho, scenario):
    if scenario == "medium":
        return rho
    elif scenario == "high":
        return min(rho * 1.25, 1.0)
    elif scenario == "low":
        return max(2.0 * rho - 1.0, 0.75 * rho)
    raise ValueError(f"Unknown scenario: {scenario}")


def within_bucket_agg(ws_list, corr_fn):
    n = len(ws_list)
    total = 0.0
    for k in range(n):
        total += ws_list[k] ** 2
        for l in range(n):
            if k != l:
                total += corr_fn(k, l) * ws_list[k] * ws_list[l]
    return math.sqrt(max(0.0, total))


def across_bucket_agg(K_list, S_list, gamma_fn):
    n = len(K_list)
    total = sum(k ** 2 for k in K_list)
    cross = 0.0
    for b in range(n):
        for c in range(n):
            if b != c:
                cross += gamma_fn(b, c) * S_list[b] * S_list[c]
    total += cross

    if total < 0:
        S_capped = [
            max(min(S_list[i], K_list[i]), -K_list[i]) for i in range(n)
        ]
        total = sum(k ** 2 for k in K_list)
        cross = 0.0
        for b in range(n):
            for c in range(n):
                if b != c:
                    cross += gamma_fn(b, c) * S_capped[b] * S_capped[c]
        total += cross

    return math.sqrt(max(0.0, total))


def compute_equity_delta(portfolio, params, scenario):
    positions = portfolio["equity_delta"]
    rw_table = params["equity_rw"]
    intra_corr = params["equity_intra_corr"]
    other_bucket = params["equity_other_bucket"]
    cross = params["equity_cross"]

    buckets = {}
    for pos in positions:
        b = pos["bucket"]
        buckets.setdefault(b, []).append(pos)

    ws_by_bucket = {}
    for b, poss in buckets.items():
        rw = rw_table[b]
        ws_by_bucket[b] = [p["sensitivity"] * rw for p in poss]

    K_values = {}
    S_values = {}
    for b, ws_list in ws_by_bucket.items():
        if b == other_bucket:
            K_values[b] = sum(abs(ws) for ws in ws_list)
            S_values[b] = sum(ws_list)
        else:
            base_rho = intra_corr.get(b, 0.0)
            rho = apply_scenario(base_rho, scenario)
            K_values[b] = within_bucket_agg(
                ws_list, lambda k, l, _r=rho: _r
            )
            S_values[b] = sum(ws_list)

    bucket_ids = sorted(K_values.keys())

    def gamma_fn(bi_idx, bj_idx):
        bi = bucket_ids[bi_idx]
        bj = bucket_ids[bj_idx]
        if bi == other_bucket or bj == other_bucket:
            base = 0.0
        elif 1 <= bi <= 10 and 1 <= bj <= 10:
            base = float(cross["both_in_1_to_10"])
        elif {bi, bj} == {12, 13}:
            base = float(cross["between_12_and_13"])
        else:
            base = float(cross.get("index_to_sector", "0.45"))
        return apply_scenario(base, scenario) if base > 0 else 0.0

    K_list = [K_values[b] for b in bucket_ids]
    S_list = [S_values[b] for b in bucket_ids]
    capital = across_bucket_agg(K_list, S_list, gamma_fn)

    audit = [
        (str(b), K_values[b], S_values[b]) for b in bucket_ids
    ]
    return capital, audit


def compute_fx_delta(portfolio, params, scenario):
    positions = portfolio["fx_delta"]
    config = portfolio["config"]
    rw = params["fx_rw"]
    use_reduction = (
        config.get("fx_specified_pair_reduction", "false") == "true"
    )

    if use_reduction:
        rw = rw / params["fx_divisor"]

    ws = {}
    for p in positions:
        ws[p["currency"]] = p["sensitivity"] * rw

    currencies = sorted(ws.keys())
    K_list = [abs(ws[c]) for c in currencies]
    S_list = [ws[c] for c in currencies]

    gamma = apply_scenario(params["fx_cross_corr"], scenario)
    capital = across_bucket_agg(K_list, S_list, lambda b, c: gamma)

    audit = [(c, abs(ws[c]), ws[c]) for c in currencies]
    return capital, audit


def compute_girr_delta(portfolio, params, scenario):
    positions = portfolio["girr_delta"]
    config = portfolio["config"]
    rw_map = params["girr_rw"]
    spec_currencies = params["girr_spec_currencies"]
    divisor = params["girr_divisor"]
    use_reduction = (
        config.get("girr_specified_currency_reduction", "false") == "true"
    )
    theta = params["girr_theta"]
    floor = params["girr_floor"]
    same_tenor_diff_curve = params["girr_same_tenor_diff_curve"]
    diff_tenor_diff_curve = params["girr_diff_tenor_diff_curve"]
    inf_to_yield = params["girr_inf_to_yield"]
    xccy_to_any = params["girr_xccy_to_any"]
    gamma_base = params["girr_cross_bucket_corr"]

    by_currency = {}
    for pos in positions:
        ccy = pos["currency"]
        by_currency.setdefault(ccy, []).append(pos)

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
                tenor_key = (
                    str(int(tenor_val))
                    if tenor_val == int(tenor_val)
                    else tenor_str
                )
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
                same_curve = _c[k] == _c[l]
                tenor_corr = max(
                    math.exp(-theta * abs(tk - tl) / min(tk, tl)), floor
                )
                if same_curve:
                    base_rho = tenor_corr
                elif tk == tl:
                    base_rho = same_tenor_diff_curve
                else:
                    base_rho = tenor_corr * diff_tenor_diff_curve
            return apply_scenario(base_rho, scenario)

        K_values[ccy] = within_bucket_agg(ws_list, corr_fn)
        S_values[ccy] = sum(ws_list)

    currencies = sorted(K_values.keys())

    if len(currencies) == 1:
        capital = K_values[currencies[0]]
    else:
        gamma = apply_scenario(gamma_base, scenario)
        K_list = [K_values[c] for c in currencies]
        S_list = [S_values[c] for c in currencies]
        capital = across_bucket_agg(K_list, S_list, lambda b, c: gamma)

    audit = [(c, K_values[c], S_values[c]) for c in currencies]
    return capital, audit


def compute_csr_nonsec_delta(portfolio, params, scenario):
    positions = portfolio["csr_nonsec_delta"]
    rw_table = params["csr_rw"]
    intra_defs = params["csr_intra"]
    cross_p = params["csr_cross"]

    by_bucket = {}
    for pos in positions:
        b = pos["bucket"]
        by_bucket.setdefault(b, []).append(pos)

    K_values = {}
    S_values = {}

    for b, poss in by_bucket.items():
        rw = rw_table[b]
        ws_list = [p["sensitivity"] * rw for p in poss]

        if b == 16:
            K_values[b] = sum(abs(ws) for ws in ws_list)
            S_values[b] = sum(ws_list)
        else:
            if b in (17, 18):
                corr_def = intra_defs["17-18"]
            else:
                corr_def = intra_defs["1-15"]

            def corr_fn(k, l, _p=poss, _cd=corr_def):
                pk, pl = _p[k], _p[l]
                rn = (
                    _cd["rho_name_same"]
                    if pk["issuer"] == pl["issuer"]
                    else _cd["rho_name_diff"]
                )
                rt = (
                    _cd["rho_tenor_same"]
                    if pk["tenor"] == pl["tenor"]
                    else _cd["rho_tenor_diff"]
                )
                rb = (
                    _cd["rho_basis_same"]
                    if pk["curve"] == pl["curve"]
                    else _cd["rho_basis_diff"]
                )
                return apply_scenario(rn * rt * rb, scenario)

            K_values[b] = within_bucket_agg(ws_list, corr_fn)
            S_values[b] = sum(ws_list)

    bucket_ids = sorted(K_values.keys())

    if len(bucket_ids) == 1:
        capital = K_values[bucket_ids[0]]
    else:
        ig_set = cross_p["ig_set"]
        sector_map = cross_p["sector_map"]
        sector_corr = cross_p["sector_corr"]

        def gamma_fn(bi_idx, bj_idx):
            bi = bucket_ids[bi_idx]
            bj = bucket_ids[bj_idx]
            if bi == 16 or bj == 16:
                return 0.0
            bi_ig = bi in ig_set
            bj_ig = bj in ig_set
            if (bi_ig and bj_ig) or (not bi_ig and not bj_ig):
                g_rating = cross_p["same_rating"]
            else:
                g_rating = cross_p["diff_rating"]
            si = sector_map.get(bi, 0)
            sj = sector_map.get(bj, 0)
            if si == sj:
                g_sector = 1.0
            else:
                key = (min(si, sj), max(si, sj))
                g_sector = sector_corr.get(key, 0.0)
            base_gamma = g_rating * g_sector
            return (
                apply_scenario(base_gamma, scenario)
                if base_gamma > 0
                else 0.0
            )

        K_list = [K_values[b] for b in bucket_ids]
        S_list = [S_values[b] for b in bucket_ids]
        capital = across_bucket_agg(K_list, S_list, gamma_fn)

    audit = [(str(b), K_values[b], S_values[b]) for b in bucket_ids]
    return capital, audit


def compute_equity_drc(portfolio, params):
    positions = portfolio["equity_drc"]
    rw_table = params["drc_rw"]

    sum_long = 0.0
    sum_short_abs = 0.0
    rw_long = 0.0
    rw_short = 0.0

    for pos in positions:
        jtd = pos["jtd"]
        rw = rw_table[pos["rating"]]
        if jtd >= 0:
            sum_long += jtd
            rw_long += rw * jtd
        else:
            sum_short_abs += abs(jtd)
            rw_short += rw * abs(jtd)

    if sum_long + sum_short_abs > 0:
        hbr = sum_long / (sum_long + sum_short_abs)
    else:
        hbr = 1.0

    return max(0.0, rw_long - hbr * rw_short)


def write_audit(db_path, bucket_audit, scenario_audit):
    """Write audit data to the SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO audit_buckets "
        "(risk_class, bucket_id, scenario, kb, sb) "
        "VALUES (?, ?, ?, ?, ?)",
        bucket_audit,
    )
    conn.executemany(
        "INSERT INTO audit_scenarios "
        "(risk_class, scenario, capital) "
        "VALUES (?, ?, ?)",
        scenario_audit,
    )
    conn.commit()
    conn.close()


def main():
    portfolio = load_portfolio(PORTFOLIO_PATH)
    params = load_params_from_db(DB_PATH)

    scenarios = ["medium", "high", "low"]
    risk_classes = ["equity", "fx", "girr", "csr_nonsec"]
    compute_fns = {
        "equity": compute_equity_delta,
        "fx": compute_fx_delta,
        "girr": compute_girr_delta,
        "csr_nonsec": compute_csr_nonsec_delta,
    }

    result = {
        "delta": {rc: {} for rc in risk_classes},
        "drc": {},
        "scenario_totals": {},
        "sbm_delta_capital": 0.0,
        "total_capital": 0.0,
    }

    bucket_audit = []
    scenario_audit = []

    for s in scenarios:
        for rc in risk_classes:
            capital, audit_rows = compute_fns[rc](portfolio, params, s)
            result["delta"][rc][s] = round(capital, 6)
            for bucket_id, kb, sb in audit_rows:
                bucket_audit.append((rc, bucket_id, s, kb, sb))
            scenario_audit.append((rc, s, capital))

        result["scenario_totals"][s] = round(
            sum(result["delta"][rc][s] for rc in risk_classes), 6
        )

    result["sbm_delta_capital"] = round(
        max(result["scenario_totals"][s] for s in scenarios), 6
    )
    result["drc"]["equity"] = round(
        compute_equity_drc(portfolio, params), 6
    )
    result["total_capital"] = round(
        result["sbm_delta_capital"] + result["drc"]["equity"], 6
    )

    # Write audit data to SQLite
    write_audit(DB_PATH, bucket_audit, scenario_audit)

    # Write JSON output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, "capital_report.json")
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print("FRTB SBM Capital Report")
    print("=======================")
    for s in scenarios:
        print(f"\n{s.upper()} scenario:")
        for rc in risk_classes:
            print(f"  {rc:15s}: {result['delta'][rc][s]:10.2f}")
        print(f"  {'TOTAL':15s}: {result['scenario_totals'][s]:10.2f}")
    print(f"\nSBM Delta Capital: {result['sbm_delta_capital']:.2f}")
    print(f"DRC Equity:        {result['drc']['equity']:.2f}")
    print(f"Total Capital:     {result['total_capital']:.2f}")


if __name__ == "__main__":
    main()
