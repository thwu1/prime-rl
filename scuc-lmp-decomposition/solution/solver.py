#!/usr/bin/env python3
"""Reference SCUC solver with LMP decomposition, reserve, and N-1 contingency screening."""

import json
import re
import csv
import os
import numpy as np


def parse_matpower(filepath):
    """Parse a MATPOWER .m case file."""
    with open(filepath, 'r') as f:
        content = f.read()

    content_no_comments = re.sub(r'%.*', '', content)

    match = re.search(r'mpc\.baseMVA\s*=\s*(\d+)', content_no_comments)
    baseMVA = int(match.group(1))

    def extract_matrix(name):
        pattern = r'mpc\.' + name + r'\s*=\s*\[(.*?)\]'
        match = re.search(pattern, content_no_comments, re.DOTALL)
        if not match:
            return []
        data = match.group(1).strip()
        rows = []
        for line in data.split(';'):
            line = line.strip()
            if line:
                rows.append([float(x) for x in line.split()])
        return rows

    return {
        'baseMVA': baseMVA,
        'bus': extract_matrix('bus'),
        'gen': extract_matrix('gen'),
        'branch': extract_matrix('branch'),
        'gencost': extract_matrix('gencost'),
    }


def load_all_data():
    """Load all input data files."""
    case = parse_matpower('/app/data/network.m')

    with open('/app/data/gen_config.json', 'r') as f:
        gen_config = json.load(f)

    load_profile = {}
    hours = []
    with open('/app/data/load_profile.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            h = int(row['hour'])
            hours.append(h)
            for col in row:
                if col != 'hour':
                    if col not in load_profile:
                        load_profile[col] = {}
                    load_profile[col][h] = float(row[col])
    hours.sort()

    with open('/app/data/reserve_req.json', 'r') as f:
        reserve_data = json.load(f)
    reserve_req = reserve_data['min_reserve_mw']

    return case, gen_config, load_profile, hours, reserve_req


def contingency_screening(bus_ids, n_lines, line_from, line_to, line_b, line_limit,
                           dispatch, bus_load, gens_at_bus, ref_bus, hours, baseMVA):
    """Perform N-1 contingency screening for all single-line outages."""
    n_buses = len(bus_ids)
    bus_idx = {b: i for i, b in enumerate(bus_ids)}
    ref_idx = bus_idx[ref_bus]
    mask = [i for i in range(n_buses) if i != ref_idx]

    results = {}

    for k in range(n_lines):
        key_k = f"{line_from[k]}_{line_to[k]}"
        max_overload_pct = 0.0
        violations = []

        # Build B matrix without line k
        B = np.zeros((n_buses, n_buses))
        for l in range(n_lines):
            if l == k:
                continue
            fi = bus_idx[line_from[l]]
            ti = bus_idx[line_to[l]]
            bl = line_b[l]
            B[fi, fi] += bl
            B[ti, ti] += bl
            B[fi, ti] -= bl
            B[ti, fi] -= bl

        B_red = B[np.ix_(mask, mask)]

        if abs(np.linalg.det(B_red)) < 1e-10:
            results[key_k] = {"max_overload_pct": 0.0, "violations": []}
            continue

        for t_idx, t in enumerate(hours):
            P_inj = np.zeros(n_buses)
            for b in bus_ids:
                bi = bus_idx[b]
                gen_power = sum(dispatch[g][t_idx] for g in gens_at_bus.get(b, []))
                P_inj[bi] = gen_power - bus_load.get((b, t), 0.0)

            P_red = P_inj[mask]
            theta_red = np.linalg.solve(B_red, P_red)

            theta = np.zeros(n_buses)
            j = 0
            for i in range(n_buses):
                if i != ref_idx:
                    theta[i] = theta_red[j]
                    j += 1

            for l in range(n_lines):
                if l == k:
                    continue
                limit = line_limit[l]
                if limit <= 0:
                    continue
                flow = line_b[l] * (theta[bus_idx[line_from[l]]] - theta[bus_idx[line_to[l]]])
                pct = abs(flow) / limit * 100
                max_overload_pct = max(max_overload_pct, pct)

                emergency = 1.3 * limit
                if abs(flow) > emergency:
                    key_l = f"{line_from[l]}_{line_to[l]}"
                    violations.append({
                        "line": key_l,
                        "hour": t,
                        "flow_mw": round(abs(flow), 2),
                        "limit_mw": round(limit, 2)
                    })

        results[key_k] = {
            "max_overload_pct": round(max_overload_pct, 1),
            "violations": violations
        }

    return results


def build_and_solve():
    """Build and solve the SCUC model."""
    from pyomo.environ import (
        ConcreteModel, Set, Var, Objective, Constraint, Suffix,
        Binary, NonNegativeReals, Reals, SolverFactory, value, minimize
    )

    case, gen_config, load_profile, hours, reserve_req = load_all_data()

    baseMVA = case['baseMVA']
    bus_data = case['bus']
    gen_data = case['gen']
    branch_data = case['branch']
    gencost_data = case['gencost']

    n_buses = len(bus_data)
    n_gens = len(gen_data)
    n_lines = len(branch_data)

    bus_ids = [int(b[0]) for b in bus_data]
    gen_names = [f"G{i+1}" for i in range(n_gens)]

    ref_bus = None
    for b in bus_data:
        if int(b[1]) == 3:
            ref_bus = int(b[0])
            break

    # Generator parameters from MATPOWER
    gen_bus = {}
    gen_pmax = {}
    gen_pmin = {}
    gen_ramp = {}
    for i in range(n_gens):
        g = gen_names[i]
        gen_bus[g] = int(gen_data[i][0])
        gen_pmax[g] = gen_data[i][8]
        gen_pmin[g] = gen_data[i][9]
        ramp_val = gen_data[i][17]
        gen_ramp[g] = ramp_val if ramp_val > 0 else gen_pmax[g]

    # Cost parameters
    gen_c1 = {}
    gen_c0 = {}
    gen_startup_cost = {}
    for i in range(n_gens):
        g = gen_names[i]
        gen_c1[g] = gencost_data[i][4]
        gen_c0[g] = gencost_data[i][5]
        gen_startup_cost[g] = gencost_data[i][1]

    # Additional generator parameters
    gen_min_up = {}
    gen_min_down = {}
    gen_su_ramp = {}
    gen_sd_ramp = {}
    gen_init_status = {}
    gen_init_power = {}
    for g in gen_names:
        cfg = gen_config[g]
        gen_min_up[g] = cfg['min_up_time']
        gen_min_down[g] = cfg['min_down_time']
        gen_su_ramp[g] = cfg['startup_ramp']
        gen_sd_ramp[g] = cfg['shutdown_ramp']
        gen_init_status[g] = cfg['initial_status']
        gen_init_power[g] = cfg['initial_power']

    # Branch parameters
    line_from = {}
    line_to = {}
    line_b = {}
    line_limit = {}
    for i in range(n_lines):
        line_from[i] = int(branch_data[i][0])
        line_to[i] = int(branch_data[i][1])
        x = branch_data[i][3]
        line_b[i] = baseMVA / x
        line_limit[i] = branch_data[i][5]

    # Generators at each bus
    gens_at_bus = {b: [] for b in bus_ids}
    for g in gen_names:
        gens_at_bus[gen_bus[g]].append(g)

    # Load data
    bus_load = {}
    for b in bus_ids:
        bkey = f"Bus{b}"
        for t in hours:
            bus_load[(b, t)] = load_profile.get(bkey, {}).get(t, 0.0)

    # Initial on/off
    init_on = {}
    for g in gen_names:
        init_on[g] = 1 if gen_init_status[g] > 0 else 0

    # ===== Build Pyomo Model =====
    m = ConcreteModel()
    m.BUSES = Set(initialize=bus_ids)
    m.GENS = Set(initialize=gen_names)
    m.LINES = Set(initialize=list(range(n_lines)))
    m.HOURS = Set(initialize=hours, ordered=True)

    # Variables
    m.u = Var(m.GENS, m.HOURS, within=Binary, initialize=0)
    m.v = Var(m.GENS, m.HOURS, within=Binary, initialize=0)  # startup
    m.w = Var(m.GENS, m.HOURS, within=Binary, initialize=0)  # shutdown
    m.p = Var(m.GENS, m.HOURS, within=NonNegativeReals)
    m.theta = Var(m.BUSES, m.HOURS, within=Reals, bounds=(-3.14159, 3.14159))
    m.f = Var(m.LINES, m.HOURS, within=Reals)

    # Reference bus angle
    def ref_angle_rule(mod, t):
        return mod.theta[ref_bus, t] == 0.0
    m.RefAngle = Constraint(m.HOURS, rule=ref_angle_rule)

    # Power balance at each bus
    def power_balance_rule(mod, b, t):
        gen_sum = sum(mod.p[g, t] for g in gens_at_bus.get(b, []))
        inflow = sum(mod.f[l, t] for l in range(n_lines) if line_to[l] == b)
        outflow = sum(mod.f[l, t] for l in range(n_lines) if line_from[l] == b)
        return gen_sum + inflow - outflow == bus_load.get((b, t), 0.0)
    m.PowerBalance = Constraint(m.BUSES, m.HOURS, rule=power_balance_rule)

    # DC power flow
    def dc_flow_rule(mod, l, t):
        return mod.f[l, t] == line_b[l] * (mod.theta[line_from[l], t] - mod.theta[line_to[l], t])
    m.DCFlow = Constraint(m.LINES, m.HOURS, rule=dc_flow_rule)

    # Line thermal limits (bidirectional)
    def line_upper_rule(mod, l, t):
        if line_limit[l] > 0:
            return mod.f[l, t] <= line_limit[l]
        return Constraint.Skip
    m.LineUpper = Constraint(m.LINES, m.HOURS, rule=line_upper_rule)

    def line_lower_rule(mod, l, t):
        if line_limit[l] > 0:
            return mod.f[l, t] >= -line_limit[l]
        return Constraint.Skip
    m.LineLower = Constraint(m.LINES, m.HOURS, rule=line_lower_rule)

    # Generator output limits
    def gen_upper_rule(mod, g, t):
        return mod.p[g, t] <= gen_pmax[g] * mod.u[g, t]
    m.GenUpper = Constraint(m.GENS, m.HOURS, rule=gen_upper_rule)

    def gen_lower_rule(mod, g, t):
        return mod.p[g, t] >= gen_pmin[g] * mod.u[g, t]
    m.GenLower = Constraint(m.GENS, m.HOURS, rule=gen_lower_rule)

    # Startup/shutdown linking: u[t] - u[t-1] = v[t] - w[t]
    def link_rule(mod, g, t):
        t_idx = hours.index(t)
        if t_idx == 0:
            return mod.u[g, t] - init_on[g] == mod.v[g, t] - mod.w[g, t]
        else:
            return mod.u[g, t] - mod.u[g, hours[t_idx - 1]] == mod.v[g, t] - mod.w[g, t]
    m.LinkUVW = Constraint(m.GENS, m.HOURS, rule=link_rule)

    def exclusive_rule(mod, g, t):
        return mod.v[g, t] + mod.w[g, t] <= 1
    m.Exclusive = Constraint(m.GENS, m.HOURS, rule=exclusive_rule)

    # Ramp up
    def ramp_up_rule(mod, g, t):
        t_idx = hours.index(t)
        if t_idx == 0:
            return mod.p[g, t] - gen_init_power[g] <= gen_ramp[g] * init_on[g] + gen_su_ramp[g] * mod.v[g, t]
        else:
            tp = hours[t_idx - 1]
            return mod.p[g, t] - mod.p[g, tp] <= gen_ramp[g] * mod.u[g, tp] + gen_su_ramp[g] * mod.v[g, t]
    m.RampUp = Constraint(m.GENS, m.HOURS, rule=ramp_up_rule)

    # Ramp down
    def ramp_down_rule(mod, g, t):
        t_idx = hours.index(t)
        if t_idx == 0:
            return gen_init_power[g] - mod.p[g, t] <= gen_ramp[g] * mod.u[g, t] + gen_sd_ramp[g] * mod.w[g, t]
        else:
            tp = hours[t_idx - 1]
            return mod.p[g, tp] - mod.p[g, t] <= gen_ramp[g] * mod.u[g, t] + gen_sd_ramp[g] * mod.w[g, t]
    m.RampDown = Constraint(m.GENS, m.HOURS, rule=ramp_down_rule)

    # Startup ramp limit
    def su_ramp_limit_rule(mod, g, t):
        pmax_diff = gen_pmax[g] - gen_su_ramp[g]
        if pmax_diff <= 0:
            return Constraint.Skip
        return mod.p[g, t] <= gen_pmax[g] * mod.u[g, t] - pmax_diff * mod.v[g, t]
    m.SURampLimit = Constraint(m.GENS, m.HOURS, rule=su_ramp_limit_rule)

    # Shutdown ramp limit
    def sd_ramp_limit_rule(mod, g, t):
        t_idx = hours.index(t)
        pmax_diff = gen_pmax[g] - gen_sd_ramp[g]
        if pmax_diff <= 0:
            return Constraint.Skip
        if t_idx == 0:
            return Constraint.Skip
        else:
            tp = hours[t_idx - 1]
            return mod.p[g, tp] <= gen_pmax[g] * mod.u[g, tp] - pmax_diff * mod.w[g, t]
    m.SDRampLimit = Constraint(m.GENS, m.HOURS, rule=sd_ramp_limit_rule)

    # Minimum up time
    def min_up_rule(mod, g, t):
        t_idx = hours.index(t)
        ut = gen_min_up[g]
        if ut <= 0:
            return Constraint.Skip
        start = max(0, t_idx - ut + 1)
        window = [hours[k] for k in range(start, t_idx + 1)]
        return sum(mod.v[g, h] for h in window) <= mod.u[g, t]
    m.MinUp = Constraint(m.GENS, m.HOURS, rule=min_up_rule)

    # Minimum down time
    def min_down_rule(mod, g, t):
        t_idx = hours.index(t)
        dt = gen_min_down[g]
        if dt <= 0:
            return Constraint.Skip
        start = max(0, t_idx - dt + 1)
        window = [hours[k] for k in range(start, t_idx + 1)]
        return sum(mod.w[g, h] for h in window) <= 1 - mod.u[g, t]
    m.MinDown = Constraint(m.GENS, m.HOURS, rule=min_down_rule)

    # Spinning reserve constraint
    def reserve_rule(mod, t):
        t_idx = hours.index(t)
        return sum(gen_pmax[g] * mod.u[g, t] - mod.p[g, t]
                   for g in gen_names) >= reserve_req[t_idx]
    m.Reserve = Constraint(m.HOURS, rule=reserve_rule)

    # Initial condition constraints for min up/down
    for g in gen_names:
        if gen_init_status[g] > 0:
            remaining = max(0, gen_min_up[g] - gen_init_status[g])
            for t_idx in range(min(remaining, len(hours))):
                m.u[g, hours[t_idx]].fix(1)
        elif gen_init_status[g] < 0:
            remaining = max(0, gen_min_down[g] + gen_init_status[g])
            for t_idx in range(min(remaining, len(hours))):
                m.u[g, hours[t_idx]].fix(0)

    # Objective
    def obj_rule(mod):
        prod = sum(gen_c1[g] * mod.p[g, t] + gen_c0[g] * mod.u[g, t]
                   for g in gen_names for t in hours)
        startup = sum(gen_startup_cost[g] * mod.v[g, t]
                      for g in gen_names for t in hours)
        return prod + startup
    m.TotalCost = Objective(rule=obj_rule, sense=minimize)

    # Dual suffix
    m.dual = Suffix(direction=Suffix.IMPORT)

    # ===== Solve MILP =====
    solver = SolverFactory('cbc')
    solver.options['ratioGap'] = 0.005
    solver.options['seconds'] = 120
    result = solver.solve(m, tee=True, keepfiles=False)
    print(f"MILP solve status: {result.solver.termination_condition}")

    # ===== Extract commitment decisions =====
    uc = {}
    dispatch = {}
    for g in gen_names:
        uc[g] = [int(round(value(m.u[g, t]))) for t in hours]
        dispatch[g] = [round(value(m.p[g, t]), 4) for t in hours]

    # ===== Fix binaries and re-solve LP for duals =====
    for g in gen_names:
        for t in hours:
            m.u[g, t].fixed = True
            m.v[g, t].fixed = True
            m.w[g, t].fixed = True

    result_lp = solver.solve(m, tee=False, keepfiles=False)
    print(f"LP solve status: {result_lp.solver.termination_condition}")

    # ===== Extract LMPs =====
    lmp = {f"Bus{b}": [] for b in bus_ids}
    lmp_energy = {f"Bus{b}": [] for b in bus_ids}
    lmp_congestion = {f"Bus{b}": [] for b in bus_ids}

    for t in hours:
        lmp_vals = {}
        for b in bus_ids:
            d = m.dual.get(m.PowerBalance[b, t])
            lmp_vals[b] = d if d is not None else 0.0

        energy = lmp_vals[ref_bus]

        for b in bus_ids:
            bkey = f"Bus{b}"
            lmp[bkey].append(round(lmp_vals[b], 4))
            lmp_energy[bkey].append(round(energy, 4))
            lmp_congestion[bkey].append(round(lmp_vals[b] - energy, 4))

    # ===== Extract line flows =====
    line_flows = {}
    for l in range(n_lines):
        key = f"{line_from[l]}_{line_to[l]}"
        line_flows[key] = [round(value(m.f[l, t]), 4) for t in hours]

    # ===== Compute reserve =====
    reserve_mw = []
    for t_idx, t in enumerate(hours):
        r = sum(gen_pmax[g] * uc[g][t_idx] - dispatch[g][t_idx]
                for g in gen_names)
        reserve_mw.append(round(r, 4))

    # ===== Compute costs =====
    prod_cost = sum(gen_c1[g] * value(m.p[g, t]) + gen_c0[g] * uc[g][hours.index(t)]
                    for g in gen_names for t in hours)
    startup_cost = sum(gen_startup_cost[g] * int(round(value(m.v[g, t])))
                       for g in gen_names for t in hours)

    # ===== Contingency screening =====
    cont_results = contingency_screening(
        bus_ids, n_lines, line_from, line_to, line_b, line_limit,
        dispatch, bus_load, gens_at_bus, ref_bus, hours, baseMVA
    )

    results = {
        'unit_commitment': uc,
        'dispatch_mw': dispatch,
        'line_flow_mw': line_flows,
        'lmp': lmp,
        'lmp_energy': lmp_energy,
        'lmp_congestion': lmp_congestion,
        'reserve_mw': reserve_mw,
        'contingency_results': cont_results,
        'total_production_cost': round(prod_cost, 2),
        'total_startup_cost': round(startup_cost, 2),
        'total_cost': round(prod_cost + startup_cost, 2),
    }

    return results


def main():
    os.makedirs('/app/results', exist_ok=True)
    results = build_and_solve()
    with open('/app/results/solution.json', 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Solution written to /app/results/solution.json")
    print(f"Total cost: ${results['total_cost']:.2f}")
    print(f"  Production cost: ${results['total_production_cost']:.2f}")
    print(f"  Startup cost: ${results['total_startup_cost']:.2f}")


if __name__ == '__main__':
    main()
