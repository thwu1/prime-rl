#!/usr/bin/env python3
"""
Pharmacokinetic Simulation Engine with MAP Bayes Estimation.
Two-compartment model with first-order absorption and allometric scaling.

"""

import sys
import json
import csv
import heapq
from collections import OrderedDict

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import minimize


# ── Model loading ──

def load_model(path="/app/model.json"):
    with open(path) as f:
        return json.load(f)


def get_params(model, etas=None, covariates=None):
    """Compute individual PK parameters from population + ETAs + covariates."""
    th = model["theta"]
    if etas is None:
        etas = {}

    # Weight covariate with default from model
    wt = 70.0
    if covariates and "WT" in covariates:
        wt = covariates["WT"]
    elif "covariates" in model and "WT" in model["covariates"]:
        wt = model["covariates"]["WT"]["default"]

    return {
        "CL": th["TVCL"] * np.exp(etas.get("ETA_CL", 0.0)) * (wt / 70.0) ** 0.75,
        "V1": th["TVV1"] * np.exp(etas.get("ETA_V1", 0.0)) * (wt / 70.0),
        "V2": th["TVV2"],
        "Q":  th["TVQ"],
        "KA": th["TVKA"] * np.exp(etas.get("ETA_KA", 0.0)),
    }


# ── ODE system ──

def ode_rhs(t, y, p, rates):
    """Two-compartment first-order absorption ODE."""
    A1, A2, A3 = y
    KA  = p["KA"]
    k10 = p["CL"] / p["V1"]
    k12 = p["Q"]  / p["V1"]
    k21 = p["Q"]  / p["V2"]
    dA1 = -KA * A1 + rates.get(0, 0.0)
    dA2 = KA * A1 - (k10 + k12) * A2 + k21 * A3 + rates.get(1, 0.0)
    dA3 = k12 * A2 - k21 * A3 + rates.get(2, 0.0)
    return [dA1, dA2, dA3]


def integrate(y0, dt, params, rates):
    """Integrate ODE from current state for dt time units."""
    if dt < 1e-14:
        return np.array(y0, dtype=float)
    frozen_rates = dict(rates)
    sol = solve_ivp(
        lambda t, y: ode_rhs(t, y, params, frozen_rates),
        [0.0, dt],
        y0,
        method="LSODA",
        rtol=1e-10,
        atol=1e-12,
    )
    return sol.y[:, -1].copy()


# ── Data parsing ──

def _pf(val, default=0.0):
    if val is None or val == "" or val == "NA" or val == ".":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _pi(val, default=0):
    return int(_pf(val, float(default)))


def parse_data(path):
    records = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rec = {
                "ID":    _pi(row.get("ID"), 1),
                "TIME":  _pf(row.get("TIME")),
                "EVID":  _pi(row.get("EVID")),
                "AMT":   _pf(row.get("AMT")),
                "CMT":   _pi(row.get("CMT")),
                "II":    _pf(row.get("II")),
                "ADDL":  _pi(row.get("ADDL")),
                "SS":    _pi(row.get("SS")),
                "RATE":  _pf(row.get("RATE")),
                "DV":    _pf(row.get("DV")),
                "MDV":   _pi(row.get("MDV")),
                "F1":    _pf(row.get("F1")),
                "ALAG1": _pf(row.get("ALAG1")),
            }
            # ETA columns
            for eta in ("ETA_CL", "ETA_V1", "ETA_KA"):
                if eta in row and row[eta] not in ("", "NA", ".", None):
                    rec[eta] = float(row[eta])
            # Weight covariate
            if "WT" in row and row["WT"] not in ("", "NA", ".", None):
                rec["WT"] = float(row["WT"])
            records.append(rec)
    return records


def group_by_id(records):
    g = OrderedDict()
    for r in records:
        g.setdefault(r["ID"], []).append(r)
    return g


def _extract_covariates(records):
    """Extract covariates from records for an individual."""
    covariates = {}
    for rec in records:
        if "WT" in rec:
            covariates["WT"] = rec["WT"]
            break
    return covariates


def _extract_etas(records):
    """Extract user-provided ETAs from records for an individual."""
    etas = {}
    for rec in records:
        for name in ("ETA_CL", "ETA_V1", "ETA_KA"):
            if name in rec:
                etas[name] = rec[name]
        if etas:
            break
    return etas


# ── Steady-state advancement ──

def advance_to_ss(params, cmt, amt, rate, ii, rtol=1e-8, max_n=500):
    """Advance to pharmacokinetic steady state by repeated dosing."""
    state = np.array([0.0, 0.0, 0.0])
    rates = {}

    for n in range(max_n):
        prev = state.copy()

        if rate > 0:
            dur = amt / rate
            rates_on = dict(rates)
            rates_on[cmt] = rates_on.get(cmt, 0.0) + rate
            state = integrate(state, dur, params, rates_on)
            remaining = ii - dur
            if remaining > 1e-14:
                state = integrate(state, remaining, params, rates)
        else:
            state[cmt] += amt
            state = integrate(state, ii, params, rates)

        if n > 0:
            diffs = np.abs(state - prev)
            tols = np.abs(state) * rtol + 1e-14
            if np.all(diffs <= tols):
                break

    return state


# ── Event-driven simulation ──

_seq_counter = 0


def _next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def simulate_individual(model, records, etas=None, covariates=None):
    """Simulate one individual, returning list of result dicts."""
    global _seq_counter
    _seq_counter = 0

    params = get_params(model, etas, covariates)
    V1 = params["V1"]

    pq = []

    for i, rec in enumerate(records):
        evid = rec["EVID"]
        t = rec["TIME"]

        if evid == 0:
            heapq.heappush(pq, (t, 10, _next_seq(), "obs", rec, i))
            continue

        if evid == 3:
            heapq.heappush(pq, (t, 0, _next_seq(), "reset", None, i))
            continue

        if evid not in (1, 4):
            continue

        cmt = rec["CMT"] - 1
        amt = rec["AMT"]
        rate = rec["RATE"]

        f = rec.get("F1", 0.0)
        eff_amt = amt * f if (cmt == 0 and f > 0) else amt

        alag = rec.get("ALAG1", 0.0)
        t_off = alag if (cmt == 0 and alag > 0) else 0.0

        if evid == 4:
            heapq.heappush(pq, (t, 0, _next_seq(), "reset", None, i))

        base_t = t + t_off
        ss = rec.get("SS", 0)
        ii = rec.get("II", 0.0)
        addl = rec.get("ADDL", 0)

        if ss == 1 and ii > 0:
            heapq.heappush(pq, (base_t, 1, _next_seq(), "ss_dose", {
                "cmt": cmt, "amt": eff_amt, "rate": rate, "ii": ii,
            }, i))
        else:
            if rate > 0:
                dur = eff_amt / rate
                heapq.heappush(pq, (base_t, 2, _next_seq(), "inf_on",
                                    {"cmt": cmt, "rate": rate}, i))
                heapq.heappush(pq, (base_t + dur, 5, _next_seq(), "inf_off",
                                    {"cmt": cmt, "rate": rate}, -1))
            else:
                heapq.heappush(pq, (base_t, 2, _next_seq(), "bolus",
                                    {"cmt": cmt, "amt": eff_amt}, i))

        if addl > 0 and ii > 0:
            for j in range(1, addl + 1):
                addl_t = base_t + j * ii
                if rate > 0:
                    dur = eff_amt / rate
                    heapq.heappush(pq, (addl_t, 2, _next_seq(), "inf_on",
                                        {"cmt": cmt, "rate": rate}, -1))
                    heapq.heappush(pq, (addl_t + dur, 5, _next_seq(), "inf_off",
                                        {"cmt": cmt, "rate": rate}, -1))
                else:
                    heapq.heappush(pq, (addl_t, 2, _next_seq(), "bolus",
                                        {"cmt": cmt, "amt": eff_amt}, -1))

    state = np.array([0.0, 0.0, 0.0])
    inf_rates = {}
    cur_t = 0.0
    results = {}

    while pq:
        evt_time, _, _, evt_type, evt_data, evt_idx = heapq.heappop(pq)

        dt = evt_time - cur_t
        if dt > 1e-14:
            state = integrate(state, dt, params, inf_rates)
            cur_t = evt_time

        if evt_type == "reset":
            state = np.array([0.0, 0.0, 0.0])
            inf_rates = {}

        elif evt_type == "ss_dose":
            cmt = evt_data["cmt"]
            amt = evt_data["amt"]
            rate = evt_data["rate"]
            ii = evt_data["ii"]
            ss_state = advance_to_ss(params, cmt, amt, rate, ii)
            state = ss_state.copy()
            if rate > 0:
                inf_rates[cmt] = inf_rates.get(cmt, 0.0) + rate
                dur = amt / rate
                heapq.heappush(pq, (evt_time + dur, 5, _next_seq(), "inf_off",
                                    {"cmt": cmt, "rate": rate}, -1))
            else:
                state[cmt] += amt

        elif evt_type == "bolus":
            state[evt_data["cmt"]] += evt_data["amt"]

        elif evt_type == "inf_on":
            cmt = evt_data["cmt"]
            inf_rates[cmt] = inf_rates.get(cmt, 0.0) + evt_data["rate"]

        elif evt_type == "inf_off":
            cmt = evt_data["cmt"]
            inf_rates[cmt] = inf_rates.get(cmt, 0.0) - evt_data["rate"]
            if abs(inf_rates.get(cmt, 0.0)) < 1e-14:
                inf_rates.pop(cmt, None)

        if evt_idx >= 0:
            results[evt_idx] = {
                "A1": float(state[0]),
                "A2": float(state[1]),
                "A3": float(state[2]),
                "CP": float(state[1] / V1),
            }

    output = []
    for i, rec in enumerate(records):
        r = results.get(i, {"A1": 0.0, "A2": 0.0, "A3": 0.0, "CP": 0.0})
        output.append({
            "ID":   rec["ID"],
            "TIME": rec["TIME"],
            "A1":   r["A1"],
            "A2":   r["A2"],
            "A3":   r["A3"],
            "CP":   r["CP"],
        })
    return output


# ── MAP Bayes estimation ──

def mapbayes_ofv(eta_vec, model, records, obs_indices, covariates):
    """MAP Bayes objective function value."""
    etas = {
        "ETA_CL": eta_vec[0],
        "ETA_V1": eta_vec[1],
        "ETA_KA": eta_vec[2],
    }
    sim = simulate_individual(model, records, etas, covariates)

    sigma_prop = model["sigma"]["proportional"]
    omega = np.array(model["omega"]["matrix"])
    omega_inv = np.linalg.inv(omega)

    ofv = 0.0
    for idx in obs_indices:
        fi = sim[idx]["CP"]
        yi = records[idx]["DV"]
        if fi <= 1e-12:
            fi = 1e-12
        var_i = sigma_prop * fi * fi
        ofv += np.log(var_i) + (yi - fi) ** 2 / var_i

    eta_m = np.array(eta_vec).reshape(1, -1)
    ofv += float(eta_m @ omega_inv @ eta_m.T)
    return ofv


# ── CLI subcommands ──

def cmd_simulate(args):
    input_path, output_path = args[0], args[1]
    model = load_model()
    records = parse_data(input_path)
    groups = group_by_id(records)

    all_output = []
    for id_val, id_recs in groups.items():
        etas = _extract_etas(id_recs)
        covariates = _extract_covariates(id_recs)
        sim = simulate_individual(
            model, id_recs,
            etas if etas else None,
            covariates if covariates else None,
        )
        all_output.extend(sim)

    with open(output_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ID", "TIME", "A1", "A2", "A3", "CP"])
        w.writeheader()
        for row in all_output:
            w.writerow(row)


def cmd_mapbayes(args):
    input_path, output_path = args[0], args[1]
    model = load_model()
    records = parse_data(input_path)
    groups = group_by_id(records)

    result = {"individuals": []}

    for id_val, id_recs in groups.items():
        obs_idx = [
            i for i, r in enumerate(id_recs)
            if r["EVID"] == 0 and r["MDV"] == 0
        ]
        if not obs_idx:
            continue

        covariates = _extract_covariates(id_recs)

        eta0 = [0.0, 0.0, 0.0]
        res = minimize(
            mapbayes_ofv,
            eta0,
            args=(model, id_recs, obs_idx, covariates if covariates else None),
            method="Nelder-Mead",
            options={"xatol": 1e-6, "fatol": 1e-8, "maxiter": 10000},
        )
        eta_est = res.x
        etas = {
            "ETA_CL": float(eta_est[0]),
            "ETA_V1": float(eta_est[1]),
            "ETA_KA": float(eta_est[2]),
        }
        sim = simulate_individual(
            model, id_recs, etas,
            covariates if covariates else None,
        )
        ipred = [sim[i]["CP"] for i in obs_idx]

        result["individuals"].append({
            "ID":     id_val,
            "ETA_CL": etas["ETA_CL"],
            "ETA_V1": etas["ETA_V1"],
            "ETA_KA": etas["ETA_KA"],
            "OFV":    float(res.fun),
            "IPRED":  ipred,
        })

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)


def main():
    if len(sys.argv) < 4:
        print("Usage: pk_engine.py <simulate|mapbayes> <input.csv> <output>",
              file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "simulate":
        cmd_simulate(sys.argv[2:])
    elif cmd == "mapbayes":
        cmd_mapbayes(sys.argv[2:])
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
