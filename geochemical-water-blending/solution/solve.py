#!/usr/bin/env python3
"""
Geochemical pipeline: charge balance audit, speciation, dual-system CCPP,
water blending, and evaporative concentration modeling via PHREEQC.

Uses phreeqpython for speciation/blending/closed-CCPP (high-level API) and
the IPhreeqc COM interface for open-CCPP and evaporation (raw PHREEQC input).
"""

import json
import os
import csv

# Equivalent weights (molecular_weight / abs(charge)) for CBE calculation
EQ_CATION = {
    'Ca': 40.078 / 2,
    'Mg': 24.305 / 2,
    'Na': 22.990 / 1,
    'K':  39.098 / 1,
    'Fe': 55.845 / 2,
}
EQ_ANION = {
    'Cl': 35.453 / 1,
    'F':  18.998 / 1,
}


def compute_cbe(water):
    """Compute charge balance error (%) from raw water analysis in ppm."""
    cat = sum(water.get(e, 0) / w for e, w in EQ_CATION.items()
              if water.get(e, 0) > 0)

    an = sum(water.get(e, 0) / w for e, w in EQ_ANION.items()
             if water.get(e, 0) > 0)

    so4 = water.get('S(6)', 0)
    if so4 and so4 > 0:
        an += so4 / (96.06 / 2)

    alk = water.get('Alkalinity', 0)
    alk_u = water.get('Alkalinity_units', '')
    if alk and alk > 0:
        if 'CaCO3' in alk_u:
            an += alk / 50.044
        elif 'HCO3' in alk_u:
            an += alk / 61.017

    total = cat + an
    return (cat - an) / total * 100.0 if total > 0 else 0.0


def make_pp_params(water, charge_on_cl=False):
    """Build parameter dict for phreeqpython add_solution."""
    p = {'units': water.get('units', 'ppm'),
         'pH': water['pH'], 'temp': water['temp']}
    if 'pe' in water:
        p['pe'] = water['pe']
    if 'density' in water:
        p['density'] = water['density']

    for e in ['Ca', 'Mg', 'Na', 'K', 'Si', 'Fe', 'F']:
        v = water.get(e, 0)
        if v and v > 0:
            p[e] = v

    if water.get('S(6)', 0) > 0:
        p['S(6)'] = water['S(6)']

    cl = water.get('Cl', 0)
    if charge_on_cl and cl > 0:
        p['Cl'] = f'{cl} charge'
    elif cl and cl > 0:
        p['Cl'] = cl

    alk = water.get('Alkalinity', 0)
    alk_u = water.get('Alkalinity_units', '')
    if alk and alk > 0:
        p['Alkalinity'] = f'{alk} {alk_u}' if alk_u else str(alk)

    return p


def solution_text(water, num, charge_on_cl=False):
    """Generate raw PHREEQC SOLUTION text block."""
    lines = [f'SOLUTION {num}',
             f'    units    {water.get("units", "ppm")}',
             f'    pH       {water["pH"]}',
             f'    temp     {water["temp"]}']
    if 'pe' in water:
        lines.append(f'    pe       {water["pe"]}')
    if 'density' in water:
        lines.append(f'    density  {water["density"]}')

    for e in ['Ca', 'Mg', 'Na', 'K', 'Si', 'Fe', 'F']:
        v = water.get(e, 0)
        if v and v > 0:
            lines.append(f'    {e:12s}{v}')
    if water.get('S(6)', 0) > 0:
        lines.append(f'    {"S(6)":12s}{water["S(6)"]}')

    cl = water.get('Cl', 0)
    if charge_on_cl and cl > 0:
        lines.append(f'    {"Cl":12s}{cl} charge')
    elif cl and cl > 0:
        lines.append(f'    {"Cl":12s}{cl}')

    alk = water.get('Alkalinity', 0)
    alk_u = water.get('Alkalinity_units', '')
    if alk and alk > 0:
        lines.append(f'    {"Alkalinity":12s}{alk} {alk_u}' if alk_u
                     else f'    {"Alkalinity":12s}{alk}')

    return '\n'.join(lines)


def safe_si(sol, phase):
    try:
        return round(sol.si(phase), 4)
    except Exception:
        return None


def parse_sel_file(filepath):
    """Parse a PHREEQC SELECTED_OUTPUT TSV file."""
    if not os.path.exists(filepath):
        return [], []
    with open(filepath) as f:
        reader = csv.reader(f, delimiter='\t')
        raw_headers = next(reader, [])
        headers = [h.strip() for h in raw_headers]
        rows = []
        for row in reader:
            parsed = []
            for v in row:
                v = v.strip()
                try:
                    parsed.append(float(v))
                except ValueError:
                    parsed.append(0.0)
            if parsed:
                rows.append(parsed)
    return headers, rows


def col_idx(headers, name):
    """Find column index by exact or prefix match (case-insensitive)."""
    nl = name.lower()
    for i, h in enumerate(headers):
        hl = h.lower().strip()
        if hl == nl or hl.startswith(nl):
            return i
    return None


def run_raw_phreeqc(input_text, sel_file=None):
    """Run raw PHREEQC input via a fresh IPhreeqc COM instance.

    Creates an independent PhreeqPython instance (with its own IPhreeqc and
    phreeqc.dat database) to avoid solution-number conflicts with the main
    high-level API instance. Returns (headers, rows) from SELECTED_OUTPUT.
    """
    from phreeqpython import PhreeqPython
    pp_raw = PhreeqPython()
    pp_raw.ip.run_string(input_text)

    # Primary path: read SELECTED_OUTPUT file written by IPhreeqc
    if sel_file and os.path.exists(sel_file):
        return parse_sel_file(sel_file)

    # Fallback: try the programmatic selected-output array interface
    for method_name in ['get_selected_output_array', 'GetSelectedOutputArray']:
        fn = getattr(pp_raw.ip, method_name, None)
        if fn is None:
            continue
        try:
            arr = fn()
            if arr and len(arr) > 1:
                headers = [str(h).strip() for h in arr[0]]
                rows = []
                for row in arr[1:]:
                    parsed = []
                    for v in row:
                        try:
                            parsed.append(float(v))
                        except (ValueError, TypeError):
                            parsed.append(0.0)
                    rows.append(parsed)
                return headers, rows
        except Exception:
            continue

    return [], []


def main():
    from phreeqpython import PhreeqPython

    pp = PhreeqPython()

    with open('/app/waters.json') as f:
        config = json.load(f)

    waters = {w['id']: w for w in config['waters']}
    water_ids = [w['id'] for w in config['waters']]
    threshold = config['charge_balance_threshold_pct']

    results = {}

    # -- Part 1: Charge Balance Audit ------------------------------------------
    results['charge_balance'] = {}
    adjusted_ids = set()

    for wid in water_ids:
        cbe = compute_cbe(waters[wid])
        adj = abs(cbe) > threshold
        results['charge_balance'][wid] = {
            'cbe_pct': round(cbe, 2),
            'adjusted': adj,
        }
        if adj:
            adjusted_ids.add(wid)

    # -- Part 2: Speciation ----------------------------------------------------
    solutions = {}
    results['speciation'] = {}

    for wid in water_ids:
        w = waters[wid]
        params = make_pp_params(w, charge_on_cl=(wid in adjusted_ids))
        sol = pp.add_solution(params)
        solutions[wid] = sol

        results['speciation'][wid] = {
            'pH': round(sol.pH, 4),
            'pe': round(sol.pe, 4),
            'ionic_strength': round(sol.I, 6),
            'SI_Calcite': safe_si(sol, 'Calcite'),
            'SI_Dolomite': safe_si(sol, 'Dolomite'),
            'SI_Gypsum': safe_si(sol, 'Gypsum'),
            'SI_Fluorite': safe_si(sol, 'Fluorite') if w.get('F', 0) > 0 else None,
            'SI_SiO2_a': safe_si(sol, 'SiO2(a)') if w.get('Si', 0) > 0 else None,
        }

    # -- Part 3: CCPP (Closed + Open System) -----------------------------------
    cc = config['ccpp_analysis']
    ccpp_wid = cc['water_id']
    sol_ccpp = solutions[ccpp_wid]
    log_pco2 = cc['open_system_log_pco2']

    # Closed system CCPP (phreeqpython high-level API)
    copy_c = sol_ccpp * 1.0
    ca0 = copy_c.total('Ca', 'mol')
    copy_c.desaturate('Calcite')
    ca_closed = copy_c.total('Ca', 'mol')
    ccpp_closed = (ca0 - ca_closed) * 1000
    ph_closed = copy_c.pH

    # Open system CCPP (raw PHREEQC input via IPhreeqc COM interface)
    w_ccpp = waters[ccpp_wid]
    charge_ccpp = ccpp_wid in adjusted_ids

    sel_ccpp = '/tmp/ccpp_open_sel.tsv'
    if os.path.exists(sel_ccpp):
        os.remove(sel_ccpp)

    ccpp_input = (
        solution_text(w_ccpp, 1, charge_ccpp) + '\n'
        'SAVE solution 1\n'
        'END\n'
        '\n'
        'USE solution 1\n'
        'EQUILIBRIUM_PHASES 1\n'
        '    Calcite 0.0 10.0\n'
        f'    CO2(g) {log_pco2} 10.0\n'
        'SELECTED_OUTPUT 1\n'
        f'    -file {sel_ccpp}\n'
        '    -reset false\n'
        '    -totals Ca\n'
        '    -pH true\n'
        'END\n'
    )

    h_ccpp, r_ccpp = run_raw_phreeqc(ccpp_input, sel_ccpp)

    if r_ccpp:
        last = r_ccpp[-1]
        ci_ca = None
        ci_ph = None
        for j, hdr in enumerate(h_ccpp):
            hl = hdr.lower()
            if 'ca' in hl and ('mol' in hl or j == 0):
                ci_ca = j
            if hl == 'ph':
                ci_ph = j
        if ci_ca is None:
            ci_ca = 0
        if ci_ph is None:
            ci_ph = 1 if len(last) > 1 else 0

        ca_open = last[ci_ca]
        ph_open = last[ci_ph]
        ccpp_open = (ca0 - ca_open) * 1000
    else:
        ccpp_open = ccpp_closed
        ph_open = ph_closed

    results['ccpp'] = {
        'water_id': ccpp_wid,
        'CCPP_closed_mmol_kgw': round(ccpp_closed, 4),
        'CCPP_open_mmol_kgw': round(ccpp_open, 4),
        'final_pH_closed': round(ph_closed, 4),
        'final_pH_open': round(ph_open, 4),
    }

    # -- Part 4: Blend Analysis ------------------------------------------------
    bc = config['blend_analysis']
    sol_a = solutions[bc['source_a']]
    sol_b = solutions[bc['source_b']]
    ratios = bc['ratios_a']

    blend_si, blend_ph, blend_mu = [], [], []
    for ra in ratios:
        rb = round(1.0 - ra, 10)
        if ra == 0.0:
            b = sol_b * 1.0
        elif rb == 0.0:
            b = sol_a * 1.0
        else:
            b = sol_a * ra + sol_b * rb
        blend_si.append(round(b.si('Calcite'), 4))
        blend_ph.append(round(b.pH, 4))
        blend_mu.append(round(b.I, 6))

    abs_si = [abs(s) for s in blend_si]
    opt_idx = abs_si.index(min(abs_si))

    results['blend_analysis'] = {
        'ratio_a': ratios,
        'SI_Calcite': blend_si,
        'pH': blend_ph,
        'ionic_strength': blend_mu,
        'optimal_ratio_min_abs_SI_Calcite': ratios[opt_idx],
    }

    # -- Part 5: Evaporative Concentration (raw PHREEQC via IPhreeqc) ----------
    ev = config['evaporation']
    ev_wid = ev['water_id']
    ev_water = waters[ev_wid]
    cfs = ev['concentration_factors']
    phases = ev['equilibrium_phases']
    charge_ev = ev_wid in adjusted_ids

    sel_evap = '/tmp/evap_sel.tsv'
    if os.path.exists(sel_evap):
        os.remove(sel_evap)

    # Build PHREEQC input for sequential evaporation
    inp = []
    inp.append(solution_text(ev_water, 1, charge_ev))
    inp.append('SAVE solution 1')
    inp.append('END')

    phase_str = ' '.join(phases)

    prev_sol = 1
    for i, cf in enumerate(cfs):
        next_sol = 10 + i

        inp.append(f'USE solution {prev_sol}')

        if i > 0:
            prev_cf = cfs[i - 1]
            moles_remove = 55.506 * (1.0 / prev_cf - 1.0 / cf)
            inp.append(f'REACTION {i}')
            inp.append('    H2O -1.0')
            inp.append(f'    {moles_remove:.6f} moles')

        inp.append(f'EQUILIBRIUM_PHASES {i}')
        for phase in phases:
            inp.append(f'    {phase} 0.0 0.0')

        # Define SELECTED_OUTPUT only in first step; persists for all subsequent
        if i == 0:
            inp.append('SELECTED_OUTPUT 1')
            inp.append(f'    -file {sel_evap}')
            inp.append('    -reset false')
            inp.append('    -pH true')
            inp.append('    -ionic_strength true')
            inp.append(f'    -si {phase_str}')
            inp.append(f'    -equilibrium_phases {phase_str}')

        inp.append(f'SAVE solution {next_sol}')
        inp.append('END')

        prev_sol = next_sol

    h_ev, r_ev = run_raw_phreeqc('\n'.join(inp), sel_evap)

    # Parse evaporation results
    ev_ph = []
    ev_mu = []
    minerals_precip = {p: [] for p in phases}
    cumulative = {p: 0.0 for p in phases}

    if h_ev and r_ev:
        c_ph = col_idx(h_ev, 'pH')
        c_mu = col_idx(h_ev, 'mu')

        c_d = {}
        for phase in phases:
            c_d[phase] = col_idx(h_ev, f'd_{phase}')

        for row in r_ev:
            ev_ph.append(round(row[c_ph], 4) if c_ph is not None and c_ph < len(row) else 0.0)
            ev_mu.append(round(row[c_mu], 6) if c_mu is not None and c_mu < len(row) else 0.0)

            for phase in phases:
                di = c_d.get(phase)
                if di is not None and di < len(row):
                    delta = row[di]
                    if delta > 0:
                        cumulative[phase] += delta
                minerals_precip[phase].append(round(cumulative[phase], 8))

    # Pad if fewer rows than expected
    while len(ev_ph) < len(cfs):
        ev_ph.append(0.0)
        ev_mu.append(0.0)
        for phase in phases:
            minerals_precip[phase].append(0.0)

    # Determine first precipitation factor
    first_precip = {}
    for phase in phases:
        found = None
        for j, cf in enumerate(cfs):
            if j < len(minerals_precip[phase]) and minerals_precip[phase][j] > 1e-10:
                found = cf
                break
        first_precip[phase] = found

    results['evaporation'] = {
        'concentration_factors': cfs,
        'pH': ev_ph,
        'ionic_strength': ev_mu,
        'minerals_precipitated': minerals_precip,
        'first_precip_factor': first_precip,
    }

    # -- Write output ----------------------------------------------------------
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
