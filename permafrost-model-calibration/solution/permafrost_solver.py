#!/usr/bin/env python3
"""

Kudryavtsev permafrost model pipeline:
  forward     - compute TTOP and ALT for all sites
  calibrate   - inverse calibration of soil composition
  sensitivity - critical warming thresholds
  project     - parse borehole observations, compute warming trends, project permafrost loss
  uncertainty - Jacobian-based first-order uncertainty propagation
"""

import csv
import json
import math
import os
import re
import sys
import numpy as np
from scipy.optimize import minimize, brentq


def read_thermal_params(filepath):
    params = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            params[row['Texture']] = {
                'BD': float(row['Bulk_Density']),
                'HC': float(row['Heat_Capacity']),
                'TCT': float(row['Thermal_Conductivity_Thawed']),
                'TCF': float(row['Thermal_Conductivity_Frozen']),
            }
    return params


def read_csv(filepath):
    rows = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = {}
            for k, v in row.items():
                if k == 'name':
                    parsed[k] = v
                else:
                    parsed[k] = float(v)
            rows.append(parsed)
    return rows


class KudryavtsevModel:
    def __init__(self, params):
        self.params = params

    def compute(self, Ta, Aa, Hsn, rho_sn, vwc, p_clay, p_sand, p_silt, p_peat,
                Hvgf, Hvgt, Dvf, Dvt):
        P = self.params

        # Step 1: Snow thermal properties
        Ksn = (rho_sn / 1000.0) ** 2 * 3.233 - 1.01 * (rho_sn / 1000.0) + 0.138
        Csn = 2090.0

        # Step 2: Soil thermal properties
        BD = P['Silt']['BD'] * p_silt + P['Sand']['BD'] * p_sand + \
             P['Clay']['BD'] * p_clay + P['Peat']['BD'] * p_peat
        HC = P['Silt']['HC'] * p_silt + P['Sand']['HC'] * p_sand + \
             P['Clay']['HC'] * p_clay + P['Peat']['HC'] * p_peat
        Ct = HC * BD + 4190.0 * vwc
        Cf = HC * BD + 2025.0 * vwc

        Kt_soil = P['Silt']['TCT'] ** p_silt * P['Sand']['TCT'] ** p_sand * \
                  P['Clay']['TCT'] ** p_clay * P['Peat']['TCT'] ** p_peat
        Kf_soil = P['Silt']['TCF'] ** p_silt * P['Sand']['TCF'] ** p_sand * \
                  P['Clay']['TCF'] ** p_clay * P['Peat']['TCF'] ** p_peat
        Kt = Kt_soil ** (1.0 - vwc) * 0.54 ** vwc
        Kf = Kf_soil ** (1.0 - vwc) * 2.35 ** vwc

        # Step 3: Season lengths (clamp ratio for arcsin domain)
        tau = 365.0 * 24.0 * 3600.0
        ta_ratio = max(-1.0 + 1e-12, min(1.0 - 1e-12, Ta / Aa))
        tau1 = tau * (0.5 - math.asin(ta_ratio) / math.pi)
        tau2 = tau - tau1

        # Step 4: Latent heat
        L = 3.34e8 * vwc

        # Step 5: Snow effect
        alpha_sn = Ksn / (rho_sn * Csn)
        dTsn = Aa * (1.0 - math.exp(-Hsn * math.sqrt(math.pi / (tau * alpha_sn))))
        dAsn = 2.0 / math.pi * dTsn
        Tvg = Ta + dTsn
        Avg = Aa - dAsn

        # Step 6: Vegetation effect
        dA1 = 0.0
        if Hvgf > 0 and tau1 > 0:
            dA1 = (Avg - Tvg) * (1.0 - math.exp(
                -Hvgf * math.sqrt(math.pi / (Dvf * 2.0 * tau1))))
        dA2 = 0.0
        if Hvgt > 0 and tau2 > 0:
            dA2 = (Avg + Tvg) * (1.0 - math.exp(
                -Hvgt * math.sqrt(math.pi / (Dvt * 2.0 * tau2))))
        dAv = (dA1 * tau1 + dA2 * tau2) / tau
        dTv = (dA1 * tau1 - dA2 * tau2) / tau * (2.0 / math.pi)
        Tgs = Tvg + dTv
        Ags = Avg - dAv

        # Step 7: TTOP (clamp r for arcsin domain)
        if Ags <= 0:
            Ags = 1e-12
        r = Tgs / Ags
        r_c = max(-1.0 + 1e-12, min(1.0 - 1e-12, r))
        N = 0.5 * Tgs * (Kf + Kt) + \
            Ags * (Kt - Kf) / math.pi * (r_c * math.asin(r_c) + math.sqrt(1.0 - r_c * r_c))
        K_star = Kf if N <= 0 else Kt
        Tps = N / K_star

        # Step 8: ALT
        if N > 0:
            return Tps, None, N

        C, K = Cf, Kf
        abs_Tps = abs(Tps)
        if Ags <= abs_Tps:
            return Tps, 0.0, N

        L_2C = L / (2.0 * C)
        Aps = (Ags - abs_Tps) / math.log((Ags + L_2C) / (abs_Tps + L_2C)) - L_2C
        s1 = math.sqrt(K * tau * C / math.pi)
        s2 = math.sqrt(K * tau / (math.pi * C))
        Zn = 2.0 * (Ags - abs_Tps) * s1
        Zd = 2.0 * Aps * C + L
        Zc = Zn / Zd
        inn = (2.0 * Aps * C * Zc + L * Zc) * L * s2
        ind = 2.0 * Ags * C * Zc + L * Zc + Zd * s2
        Zal = (Zn + inn / ind) / Zd

        return Tps, Zal, N


def cmd_forward(model, sites_file, output_file):
    sites = read_csv(sites_file)
    results = []
    for s in sites:
        Tps, ALT, N = model.compute(
            s['Ta'], s['Aa'], s['Hsn'], s['rho_sn'], s['vwc'],
            s['p_clay'], s['p_sand'], s['p_silt'], s['p_peat'],
            s['Hvgf'], s['Hvgt'], s['Dvf'], s['Dvt'],
        )
        regime = 'permafrost' if N <= 0 else 'seasonal_frost'
        results.append({
            'name': s['name'],
            'Tps': round(Tps, 6),
            'ALT': round(ALT, 6) if ALT is not None else None,
            'regime': regime,
        })
    with open(output_file, 'w') as f:
        json.dump({'sites': results}, f, indent=2)
    return results


def cmd_calibrate(model, targets_file, output_file):
    targets = read_csv(targets_file)
    results = []
    for t in targets:
        observed = t['observed_ALT']

        def objective(x):
            pc, ps, pi_ = x
            pp = 1.0 - pc - ps - pi_
            if pp < -1e-10:
                return 1e10
            pp = max(pp, 0.0)
            try:
                _, ALT, N = model.compute(
                    t['Ta'], t['Aa'], t['Hsn'], t['rho_sn'], t['vwc'],
                    pc, ps, pi_, pp,
                    t['Hvgf'], t['Hvgt'], t['Dvf'], t['Dvt'],
                )
                if ALT is None or ALT <= 0:
                    return 1e10
                return (ALT - observed) ** 2
            except (ValueError, ZeroDivisionError, OverflowError):
                return 1e10

        bounds = [(0.0, 1.0), (0.0, 1.0), (0.0, 1.0)]
        cons = [{'type': 'ineq', 'fun': lambda x: 1.0 - x[0] - x[1] - x[2] - 1e-10}]

        best = None
        inits = [
            [0.25, 0.25, 0.25],
            [0.10, 0.10, 0.70],
            [0.50, 0.30, 0.10],
            [0.05, 0.05, 0.10],
            [0.30, 0.50, 0.15],
            [0.40, 0.20, 0.30],
            [0.15, 0.45, 0.35],
            [0.60, 0.10, 0.20],
            [0.05, 0.80, 0.10],
            [0.70, 0.05, 0.20],
        ]
        for init in inits:
            try:
                result = minimize(
                    objective, init, method='SLSQP',
                    bounds=bounds, constraints=cons,
                    options={'maxiter': 5000, 'ftol': 1e-15},
                )
                if best is None or result.fun < best.fun:
                    best = result
            except Exception:
                continue

        pc, ps, pi_ = best.x
        pp = max(1.0 - pc - ps - pi_, 0.0)
        total = pc + ps + pi_ + pp
        pc, ps, pi_, pp = pc / total, ps / total, pi_ / total, pp / total

        Tps, pred_ALT, N = model.compute(
            t['Ta'], t['Aa'], t['Hsn'], t['rho_sn'], t['vwc'],
            pc, ps, pi_, pp,
            t['Hvgf'], t['Hvgt'], t['Dvf'], t['Dvt'],
        )

        pc_r = round(pc, 8)
        ps_r = round(ps, 8)
        pi_r = round(pi_, 8)
        pp_r = 1.0 - pc_r - ps_r - pi_r

        results.append({
            'name': t['name'],
            'p_clay': pc_r,
            'p_sand': ps_r,
            'p_silt': pi_r,
            'p_peat': pp_r,
            'predicted_ALT': round(pred_ALT, 6),
            'observed_ALT': observed,
            'residual': round(abs(pred_ALT - observed), 6),
        })

    with open(output_file, 'w') as f:
        json.dump({'sites': results}, f, indent=2)


def cmd_sensitivity(model, sites_file, forward_file, output_file):
    sites = read_csv(sites_file)
    with open(forward_file) as f:
        forward = json.load(f)

    pf_map = {s['name']: s for s in forward['sites'] if s['regime'] == 'permafrost'}

    results = []
    for s in sites:
        if s['name'] not in pf_map:
            continue

        def ttop_N(delta_Ta):
            _, _, N = model.compute(
                s['Ta'] + delta_Ta, s['Aa'], s['Hsn'], s['rho_sn'], s['vwc'],
                s['p_clay'], s['p_sand'], s['p_silt'], s['p_peat'],
                s['Hvgf'], s['Hvgt'], s['Dvf'], s['Dvt'],
            )
            return N

        hi = 1.0
        max_iter = 20
        for _ in range(max_iter):
            try:
                if ttop_N(hi) > 0:
                    break
            except Exception:
                pass
            hi *= 2.0

        try:
            delta_crit = brentq(ttop_N, 0.0, hi, xtol=1e-6)
        except ValueError:
            delta_crit = hi

        results.append({
            'name': s['name'],
            'delta_Ta_critical': round(delta_crit, 6),
            'current_Tps': pf_map[s['name']]['Tps'],
        })

    with open(output_file, 'w') as f:
        json.dump({'sites': results}, f, indent=2)


def parse_borehole_obs(filepath):
    """Parse PANGAEA tab-delimited borehole observation file."""
    boreholes = {}
    with open(filepath, encoding='utf-8') as f:
        in_comment = False
        header = None
        year_col_indices = []

        for line in f:
            line = line.rstrip('\n')
            if line.startswith('/*'):
                in_comment = True
                continue
            if in_comment:
                if '*/' in line:
                    in_comment = False
                continue

            if header is None:
                header = line.split('\t')
                for i, col_name in enumerate(header):
                    m = re.match(r'MAGT\s*\[.*?\]\s*\((\d{4})\)', col_name)
                    if m:
                        year_col_indices.append((i, int(m.group(1))))
                continue

            fields = line.split('\t')
            if not fields or not fields[0].strip():
                continue

            event = fields[0].strip()
            year_vals = {}
            for col_idx, year in year_col_indices:
                if col_idx < len(fields):
                    val = fields[col_idx].strip()
                    if val != '':
                        try:
                            year_vals[year] = float(val)
                        except ValueError:
                            pass
            boreholes[event] = year_vals

    return boreholes


def ols_slope(year_vals):
    """Compute OLS slope (degC/year) from {year: temp} dict."""
    if len(year_vals) < 5:
        return None

    years = sorted(year_vals.keys())
    n = len(years)
    x = [float(y) for y in years]
    vals = [year_vals[y] for y in years]

    x_mean = sum(x) / n
    y_mean = sum(vals) / n

    ss_xy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, vals))
    ss_xx = sum((xi - x_mean) ** 2 for xi in x)

    if ss_xx == 0:
        return 0.0

    return ss_xy / ss_xx


def cmd_project(model, sites_file, output_dir):
    """Parse borehole observations, compute warming trends, project permafrost loss."""
    fwd_file = os.path.join(output_dir, 'forward_results.json')
    sens_file = os.path.join(output_dir, 'sensitivity_results.json')

    if not os.path.exists(fwd_file):
        cmd_forward(model, sites_file, fwd_file)
    if not os.path.exists(sens_file):
        cmd_sensitivity(model, sites_file, fwd_file, sens_file)

    with open(fwd_file) as f:
        forward = json.load(f)
    with open(sens_file) as f:
        sensitivity = json.load(f)

    fwd_map = {s['name']: s for s in forward['sites']}
    sens_map = {s['name']: s for s in sensitivity['sites']}

    boreholes = parse_borehole_obs('/app/data/borehole_obs.tsv')

    mapping = {}
    with open('/app/data/site_borehole_map.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            mapping[row['site_name']] = row['borehole_event']

    results = []
    for site_name, bh_event in mapping.items():
        year_vals = boreholes.get(bh_event, {})
        slope = ols_slope(year_vals)

        trend_decade = round(slope * 10.0, 6) if slope is not None else None
        trend_per_year = slope

        fwd_site = fwd_map.get(site_name, {})
        regime = fwd_site.get('regime', 'seasonal_frost')
        sens_site = sens_map.get(site_name)
        delta_crit = sens_site['delta_Ta_critical'] if sens_site else None

        if regime == 'seasonal_frost':
            delta_crit = None

        years_to_loss = None
        if (delta_crit is not None and
                trend_per_year is not None and
                trend_per_year > 0):
            years_to_loss = round(delta_crit / trend_per_year, 6)

        results.append({
            'name': site_name,
            'borehole_id': bh_event,
            'warming_trend_decade': trend_decade,
            'delta_Ta_critical': round(delta_crit, 6) if delta_crit is not None else None,
            'years_to_loss': years_to_loss,
        })

    output_file = os.path.join(output_dir, 'projection_results.json')
    with open(output_file, 'w') as f:
        json.dump({'sites': results}, f, indent=2)


def cmd_uncertainty(model, sites_file, output_dir, uncertainties_file):
    """Compute Jacobian-based first-order uncertainty propagation for permafrost sites."""
    fwd_file = os.path.join(output_dir, 'forward_results.json')
    sens_file = os.path.join(output_dir, 'sensitivity_results.json')

    if not os.path.exists(fwd_file):
        cmd_forward(model, sites_file, fwd_file)
    if not os.path.exists(sens_file):
        cmd_sensitivity(model, sites_file, fwd_file, sens_file)

    with open(fwd_file) as f:
        forward = json.load(f)
    with open(sens_file) as f:
        sensitivity = json.load(f)

    fwd_map = {s['name']: s for s in forward['sites']}
    sens_map = {s['name']: s for s in sensitivity['sites']}

    uncertainties = {}
    with open(uncertainties_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            uncertainties[row['param']] = float(row['abs_std'])

    sites = read_csv(sites_file)
    param_names = sorted(uncertainties.keys())

    results = []
    for s in sites:
        name = s['name']
        if fwd_map[name]['regime'] != 'permafrost':
            continue

        # Base case computation
        base_Tps, base_ALT, base_N = model.compute(
            s['Ta'], s['Aa'], s['Hsn'], s['rho_sn'], s['vwc'],
            s['p_clay'], s['p_sand'], s['p_silt'], s['p_peat'],
            s['Hvgf'], s['Hvgt'], s['Dvf'], s['Dvt'],
        )

        jac_TTOP = {}
        jac_ALT = {}

        for param in param_names:
            p_val = s[param]
            h = max(abs(p_val) * 1e-4, 1e-6)

            # Build perturbed parameter sets
            kw_base = {
                'Ta': s['Ta'], 'Aa': s['Aa'], 'Hsn': s['Hsn'],
                'rho_sn': s['rho_sn'], 'vwc': s['vwc'],
            }

            kw_plus = dict(kw_base)
            kw_plus[param] = p_val + h
            Tps_p, ALT_p, _ = model.compute(
                kw_plus['Ta'], kw_plus['Aa'], kw_plus['Hsn'],
                kw_plus['rho_sn'], kw_plus['vwc'],
                s['p_clay'], s['p_sand'], s['p_silt'], s['p_peat'],
                s['Hvgf'], s['Hvgt'], s['Dvf'], s['Dvt'],
            )

            kw_minus = dict(kw_base)
            kw_minus[param] = p_val - h
            Tps_m, ALT_m, _ = model.compute(
                kw_minus['Ta'], kw_minus['Aa'], kw_minus['Hsn'],
                kw_minus['rho_sn'], kw_minus['vwc'],
                s['p_clay'], s['p_sand'], s['p_silt'], s['p_peat'],
                s['Hvgf'], s['Hvgt'], s['Dvf'], s['Dvt'],
            )

            # TTOP Jacobian (always well-defined since Tps is continuous)
            jac_TTOP[param] = (Tps_p - Tps_m) / (2.0 * h)

            # ALT Jacobian (handle regime transitions with one-sided differences)
            if ALT_p is not None and ALT_m is not None:
                jac_ALT[param] = (ALT_p - ALT_m) / (2.0 * h)
            elif ALT_p is not None and base_ALT is not None:
                jac_ALT[param] = (ALT_p - base_ALT) / h
            elif ALT_m is not None and base_ALT is not None:
                jac_ALT[param] = (base_ALT - ALT_m) / h
            else:
                jac_ALT[param] = 0.0

        # Propagate uncertainties via first-order Taylor expansion
        sigma_TTOP = math.sqrt(sum(
            (jac_TTOP[p] * uncertainties[p]) ** 2 for p in param_names
        ))

        if base_ALT is not None:
            sigma_ALT = math.sqrt(sum(
                (jac_ALT[p] * uncertainties[p]) ** 2 for p in param_names
            ))
        else:
            sigma_ALT = None

        # Identify dominant uncertainty contributor
        contributions = {p: abs(jac_TTOP[p] * uncertainties[p]) for p in param_names}
        dominant = max(contributions, key=contributions.get)

        # Vulnerability index: ratio of uncertainty to critical warming threshold
        delta_crit = sens_map[name]['delta_Ta_critical']
        vulnerability = sigma_TTOP / delta_crit if delta_crit > 0 else float('inf')

        results.append({
            'name': name,
            'sigma_TTOP': round(sigma_TTOP, 6),
            'sigma_ALT': round(sigma_ALT, 6) if sigma_ALT is not None else None,
            'dominant_param': dominant,
            'vulnerability_index': round(vulnerability, 6),
            'jacobian_TTOP': {p: round(jac_TTOP[p], 8) for p in param_names},
            'jacobian_ALT': {p: round(jac_ALT[p], 8) for p in param_names},
        })

    output_file = os.path.join(output_dir, 'uncertainty_results.json')
    with open(output_file, 'w') as f:
        json.dump({'sites': results}, f, indent=2)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in (
            'forward', 'calibrate', 'sensitivity', 'project', 'uncertainty'):
        print("Usage: python3 permafrost_model.py "
              "{forward|calibrate|sensitivity|project|uncertainty}")
        sys.exit(1)

    params = read_thermal_params('/app/data/thermal_params.csv')
    model = KudryavtsevModel(params)
    os.makedirs('/app/output', exist_ok=True)

    cmd = sys.argv[1]
    if cmd == 'forward':
        cmd_forward(model, '/app/data/sites.csv', '/app/output/forward_results.json')
    elif cmd == 'calibrate':
        cmd_calibrate(model, '/app/data/calibration_targets.csv',
                      '/app/output/calibration_results.json')
    elif cmd == 'sensitivity':
        fwd_file = '/app/output/forward_results.json'
        if not os.path.exists(fwd_file):
            cmd_forward(model, '/app/data/sites.csv', fwd_file)
        cmd_sensitivity(model, '/app/data/sites.csv', fwd_file,
                        '/app/output/sensitivity_results.json')
    elif cmd == 'project':
        cmd_project(model, '/app/data/sites.csv', '/app/output')
    elif cmd == 'uncertainty':
        cmd_uncertainty(model, '/app/data/sites.csv', '/app/output',
                        '/app/data/param_uncertainties.csv')


if __name__ == '__main__':
    main()
