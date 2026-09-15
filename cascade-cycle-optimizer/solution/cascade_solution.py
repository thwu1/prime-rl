#!/usr/bin/env python3

"""Cascade refrigeration system analyzer using CoolProp."""

import argparse
import json
import sys

import numpy as np
from CoolProp.CoolProp import PropsSI


class _Enc(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def single_cycle(fluid, T_evap, T_cond, eta_isen, superheat, subcool):
    """Analyze a single-stage vapor-compression refrigeration cycle."""
    P_evap = float(PropsSI('P', 'T', T_evap, 'Q', 1.0, fluid))
    P_cond = float(PropsSI('P', 'T', T_cond, 'Q', 0.0, fluid))

    # State 1: compressor inlet (superheated vapor)
    T1 = T_evap + superheat
    H1 = float(PropsSI('H', 'T', T1, 'P', P_evap, fluid))
    S1 = float(PropsSI('S', 'T', T1, 'P', P_evap, fluid))

    # State 2: compressor outlet (isentropic + efficiency correction)
    H2s = float(PropsSI('H', 'P', P_cond, 'S', S1, fluid))
    H2 = H1 + (H2s - H1) / eta_isen
    T2 = float(PropsSI('T', 'P', P_cond, 'H', H2, fluid))
    S2 = float(PropsSI('S', 'P', P_cond, 'H', H2, fluid))

    # State 3: condenser outlet (subcooled liquid)
    T3 = T_cond - subcool
    H3 = float(PropsSI('H', 'T', T3, 'P|liquid', P_cond, fluid))
    S3 = float(PropsSI('S', 'T', T3, 'P|liquid', P_cond, fluid))

    # State 4: expansion valve outlet (isenthalpic)
    H4 = H3
    T4 = float(PropsSI('T', 'P', P_evap, 'H', H4, fluid))
    S4 = float(PropsSI('S', 'P', P_evap, 'H', H4, fluid))

    q_evap = H1 - H4
    w_comp = H2 - H1
    q_cond = H2 - H3

    return {
        'COP': q_evap / w_comp,
        'w_comp': w_comp,
        'q_evap': q_evap,
        'q_cond': q_cond,
        'T_discharge_K': T2,
        'pressure_ratio': P_cond / P_evap,
        'states': [
            {'T': T1, 'P': P_evap, 'H': H1, 'S': S1},
            {'T': T2, 'P': P_cond, 'H': H2, 'S': S2},
            {'T': T3, 'P': P_cond, 'H': H3, 'S': S3},
            {'T': T4, 'P': P_evap, 'H': H4, 'S': S4},
        ],
    }


def _resolve_temps(plant):
    """Determine evap/cond saturation temperatures for each stage."""
    stages = plant['stages']
    hxs = plant['cascade_heat_exchangers']
    ct = plant['cascade_temperatures_K']

    st = {}
    for s in stages:
        st[s['id']] = [
            s['evaporator'].get('saturation_temperature_K'),
            s['condenser'].get('saturation_temperature_K'),
        ]
    for i, hx in enumerate(hxs):
        dT = hx['approach_temperature_K']
        st[hx['hot_stage']][1] = ct[i] + dT / 2.0
        st[hx['cold_stage']][0] = ct[i] - dT / 2.0
    return st


def analyze_plant(plant):
    """Analyze a cascade refrigeration system."""
    stages = plant['stages']
    st = _resolve_temps(plant)

    sr = {}
    for s in stages:
        sid = s['id']
        sr[sid] = single_cycle(
            s['refrigerant'], st[sid][0], st[sid][1],
            s['compressor']['isentropic_efficiency'],
            s['evaporator']['superheat_K'],
            s['condenser']['subcool_K'],
        )

    Q_cool = plant['cooling_capacity_W']
    mf = {stages[0]['id']: Q_cool / sr[stages[0]['id']]['q_evap']}

    duties = []
    for hx in plant['cascade_heat_exchangers']:
        Q = mf[hx['hot_stage']] * sr[hx['hot_stage']]['q_cond']
        duties.append(Q)
        mf[hx['cold_stage']] = Q / sr[hx['cold_stage']]['q_evap']

    for sid, m in mf.items():
        sr[sid]['mass_flow_kg_s'] = m

    W = sum(mf[s['id']] * sr[s['id']]['w_comp'] for s in stages)

    return {
        'system_COP': Q_cool / W,
        'total_power_W': W,
        'stages': sr,
        'cascade_hx_duties_W': duties,
    }


def optimize_plant(plant):
    """Find cascade temperatures that maximize system COP."""
    from scipy.optimize import minimize_scalar, minimize, brute

    n = len(plant['cascade_heat_exchangers'])
    stages = plant['stages']
    stage_map = {s['id']: s for s in stages}

    def cop_at(temps_list):
        try:
            p = dict(plant)
            p['cascade_temperatures_K'] = [float(t) for t in temps_list]
            return analyze_plant(p)['system_COP']
        except Exception:
            return -1e10

    if n == 1:
        hx = plant['cascade_heat_exchangers'][0]
        hot_s = stage_map[hx['hot_stage']]
        cold_s = stage_map[hx['cold_stage']]
        dT = hx['approach_temperature_K']

        T_evap_low = hot_s['evaporator']['saturation_temperature_K']
        T_cond_hi = cold_s['condenser']['saturation_temperature_K']

        lo = T_evap_low + dT / 2 + hot_s['condenser']['subcool_K'] + 2
        hi = T_cond_hi - dT / 2 - cold_s['evaporator']['superheat_K'] - 2

        result = minimize_scalar(
            lambda T: -cop_at([T]),
            bounds=(lo, hi), method='bounded',
            options={'xatol': 0.001},
        )
        T_opt = [float(result.x)]
    else:
        # Compute feasible bounds for each cascade temperature
        bounds = []
        for i, hx in enumerate(hxs := plant['cascade_heat_exchangers']):
            hot_s = stage_map[hx['hot_stage']]
            cold_s = stage_map[hx['cold_stage']]
            dT = hx['approach_temperature_K']

            if i == 0:
                lo = hot_s['evaporator']['saturation_temperature_K'] + dT / 2 + 5
            else:
                lo = plant['cascade_temperatures_K'][i - 1] + 10

            if i == n - 1:
                hi = cold_s['condenser']['saturation_temperature_K'] - dT / 2 - 5
            else:
                hi = plant['cascade_temperatures_K'][i + 1] - 10

            bounds.append((lo, hi))

        # Grid search for robust initialization
        def neg_cop_brute(x):
            temps = [float(t) for t in x]
            for j in range(len(temps) - 1):
                if temps[j] >= temps[j + 1] - 5:
                    return 1e10
            return -cop_at(temps)

        ranges = [slice(b[0], b[1], (b[1] - b[0]) / 15) for b in bounds]
        x0 = brute(neg_cop_brute, ranges, finish=None)

        # Refine with Nelder-Mead
        def neg_cop(x):
            temps = [float(t) for t in x]
            for j in range(len(temps) - 1):
                if temps[j] >= temps[j + 1] - 3:
                    return 1e10
            return -cop_at(temps)

        result = minimize(
            neg_cop, x0, method='Nelder-Mead',
            options={'xatol': 0.001, 'fatol': 1e-8,
                     'maxiter': 5000, 'adaptive': True},
        )
        T_opt = sorted([float(t) for t in result.x])

    p = dict(plant)
    p['cascade_temperatures_K'] = T_opt
    system = analyze_plant(p)

    return {
        'optimal_cascade_temperatures_K': T_opt,
        'maximum_COP': system['system_COP'],
        'system': system,
    }


def diagnose_plant(plant, measured):
    """Back-calculate compressor isentropic efficiencies from measured data."""
    st = _resolve_temps(plant)

    actual = {}
    devs = {}
    for s in plant['stages']:
        sid = s['id']
        fluid = s['refrigerant']
        T_evap = st[sid][0]
        T_cond = st[sid][1]
        sh = s['evaporator']['superheat_K']

        P_evap = float(PropsSI('P', 'T', T_evap, 'Q', 1.0, fluid))
        P_cond = float(PropsSI('P', 'T', T_cond, 'Q', 0.0, fluid))

        T1 = T_evap + sh
        H1 = float(PropsSI('H', 'T', T1, 'P', P_evap, fluid))
        S1 = float(PropsSI('S', 'T', T1, 'P', P_evap, fluid))
        H2s = float(PropsSI('H', 'P', P_cond, 'S', S1, fluid))

        T_m = measured['measured_discharge_temperatures_K'][sid]
        H2a = float(PropsSI('H', 'T', T_m, 'P', P_cond, fluid))

        eta = (H2s - H1) / (H2a - H1)
        eta_design = s['compressor']['isentropic_efficiency']

        actual[sid] = float(eta)
        devs[sid] = float(eta - eta_design)

    return {
        'actual_efficiencies': actual,
        'efficiency_deviations': devs,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Cascade refrigeration system analyzer')
    parser.add_argument('command', choices=['analyze', 'optimize', 'diagnose'])
    parser.add_argument('plant_file')
    parser.add_argument('measured_file', nargs='?')
    args = parser.parse_args()

    with open(args.plant_file) as f:
        plant = json.load(f)

    if args.command == 'analyze':
        result = analyze_plant(plant)
    elif args.command == 'optimize':
        result = optimize_plant(plant)
    elif args.command == 'diagnose':
        with open(args.measured_file) as f:
            measured = json.load(f)
        result = diagnose_plant(plant, measured)

    print(json.dumps(result, indent=2, cls=_Enc))


if __name__ == '__main__':
    main()
