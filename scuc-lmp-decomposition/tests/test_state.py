"""Tests for SCUC solver with LMP decomposition, reserve, and N-1 contingency screening."""

import json
import csv
import re
import os
import sys
import pytest
import numpy as np

# ============ Data Loading Helpers ============

def parse_matpower(filepath):
    with open(filepath, 'r') as f:
        content = f.read()
    content = re.sub(r'%.*', '', content)
    match = re.search(r'mpc\.baseMVA\s*=\s*(\d+)', content)
    baseMVA = int(match.group(1))

    def extract_matrix(name):
        pattern = r'mpc\.' + name + r'\s*=\s*\[(.*?)\]'
        m = re.search(pattern, content, re.DOTALL)
        if not m:
            return []
        data = m.group(1).strip()
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


def load_test_data():
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
                    load_profile.setdefault(col, {})[h] = float(row[col])
    hours.sort()
    with open('/app/data/reserve_req.json', 'r') as f:
        reserve_data = json.load(f)
    reserve_req = reserve_data['min_reserve_mw']
    return case, gen_config, load_profile, hours, reserve_req


def load_solution():
    with open('/app/results/solution.json', 'r') as f:
        return json.load(f)


# ============ Fixtures ============

@pytest.fixture(scope="module")
def data():
    return load_test_data()


@pytest.fixture(scope="module")
def solution():
    return load_solution()


@pytest.fixture(scope="module")
def system_info(data):
    case, gen_config, load_profile, hours, reserve_req = data
    n_gens = len(case['gen'])
    n_buses = len(case['bus'])
    n_lines = len(case['branch'])
    bus_ids = [int(b[0]) for b in case['bus']]
    gen_names = [f"G{i+1}" for i in range(n_gens)]
    baseMVA = case['baseMVA']

    ref_bus = None
    for b in case['bus']:
        if int(b[1]) == 3:
            ref_bus = int(b[0])
            break

    gen_bus = {gen_names[i]: int(case['gen'][i][0]) for i in range(n_gens)}
    gen_pmax = {gen_names[i]: case['gen'][i][8] for i in range(n_gens)}
    gen_pmin = {gen_names[i]: case['gen'][i][9] for i in range(n_gens)}
    gen_ramp = {}
    for i in range(n_gens):
        g = gen_names[i]
        r = case['gen'][i][17]
        gen_ramp[g] = r if r > 0 else gen_pmax[g]

    gen_c1 = {gen_names[i]: case['gencost'][i][4] for i in range(n_gens)}
    gen_c0 = {gen_names[i]: case['gencost'][i][5] for i in range(n_gens)}
    gen_startup_cost = {gen_names[i]: case['gencost'][i][1] for i in range(n_gens)}

    line_from = {i: int(case['branch'][i][0]) for i in range(n_lines)}
    line_to = {i: int(case['branch'][i][1]) for i in range(n_lines)}
    line_x = {i: case['branch'][i][3] for i in range(n_lines)}
    line_limit = {i: case['branch'][i][5] for i in range(n_lines)}
    line_b = {i: baseMVA / line_x[i] for i in range(n_lines)}

    gens_at_bus = {b: [] for b in bus_ids}
    for g in gen_names:
        gens_at_bus[gen_bus[g]].append(g)

    bus_load = {}
    for b in bus_ids:
        bkey = f"Bus{b}"
        for t in hours:
            bus_load[(b, t)] = load_profile.get(bkey, {}).get(t, 0.0)

    return {
        'bus_ids': bus_ids, 'gen_names': gen_names, 'n_lines': n_lines,
        'ref_bus': ref_bus, 'gen_bus': gen_bus, 'gen_pmax': gen_pmax,
        'gen_pmin': gen_pmin, 'gen_ramp': gen_ramp, 'gen_c1': gen_c1,
        'gen_c0': gen_c0, 'gen_startup_cost': gen_startup_cost,
        'line_from': line_from, 'line_to': line_to, 'line_b': line_b,
        'line_limit': line_limit, 'gens_at_bus': gens_at_bus,
        'bus_load': bus_load, 'hours': hours, 'baseMVA': baseMVA,
        'gen_config': gen_config, 'reserve_req': reserve_req,
    }


# ============ Schema Tests ============

class TestSchema:
    def test_solution_file_exists(self):
        assert os.path.exists('/app/results/solution.json'), \
            "solution.json not found"

    def test_top_level_keys(self, solution):
        required = ['unit_commitment', 'dispatch_mw', 'line_flow_mw',
                     'lmp', 'lmp_energy', 'lmp_congestion',
                     'reserve_mw', 'contingency_results',
                     'total_production_cost', 'total_startup_cost', 'total_cost']
        for k in required:
            assert k in solution, f"Missing key: {k}"

    def test_generator_keys(self, solution, system_info):
        for section in ['unit_commitment', 'dispatch_mw']:
            for g in system_info['gen_names']:
                assert g in solution[section], \
                    f"Missing {g} in {section}"

    def test_bus_keys(self, solution, system_info):
        for section in ['lmp', 'lmp_energy', 'lmp_congestion']:
            for b in system_info['bus_ids']:
                bkey = f"Bus{b}"
                assert bkey in solution[section], \
                    f"Missing {bkey} in {section}"

    def test_line_keys(self, solution, system_info):
        for l in range(system_info['n_lines']):
            key = f"{system_info['line_from'][l]}_{system_info['line_to'][l]}"
            assert key in solution['line_flow_mw'], \
                f"Missing line {key} in line_flow_mw"

    def test_array_lengths(self, solution, system_info):
        n = len(system_info['hours'])
        for g in system_info['gen_names']:
            assert len(solution['unit_commitment'][g]) == n
            assert len(solution['dispatch_mw'][g]) == n
        for b in system_info['bus_ids']:
            bkey = f"Bus{b}"
            assert len(solution['lmp'][bkey]) == n
            assert len(solution['lmp_energy'][bkey]) == n
            assert len(solution['lmp_congestion'][bkey]) == n

    def test_reserve_array_length(self, solution, system_info):
        assert len(solution['reserve_mw']) == len(system_info['hours'])

    def test_contingency_keys(self, solution, system_info):
        for l in range(system_info['n_lines']):
            key = f"{system_info['line_from'][l]}_{system_info['line_to'][l]}"
            assert key in solution['contingency_results'], \
                f"Missing contingency key {key}"
            cr = solution['contingency_results'][key]
            assert 'max_overload_pct' in cr, f"Missing max_overload_pct in {key}"
            assert 'violations' in cr, f"Missing violations in {key}"


# ============ Feasibility Tests ============

class TestFeasibility:
    def test_power_balance(self, solution, system_info):
        """Verify nodal power balance at every bus, every hour."""
        hours = system_info['hours']
        tol = 1.0

        for t_idx, t in enumerate(hours):
            for b in system_info['bus_ids']:
                gen_power = sum(
                    solution['dispatch_mw'][g][t_idx]
                    for g in system_info['gens_at_bus'].get(b, [])
                )
                inflow = 0.0
                outflow = 0.0
                for l in range(system_info['n_lines']):
                    key = f"{system_info['line_from'][l]}_{system_info['line_to'][l]}"
                    flow = solution['line_flow_mw'][key][t_idx]
                    if system_info['line_to'][l] == b:
                        inflow += flow
                    if system_info['line_from'][l] == b:
                        outflow += flow

                load = system_info['bus_load'].get((b, t), 0.0)
                balance = gen_power + inflow - outflow - load
                assert abs(balance) < tol, \
                    f"Power imbalance at Bus{b}, hour {t}: {balance:.2f} MW"

    def test_dc_flow_consistency(self, solution, system_info):
        """Verify line flows are consistent with DC power flow (B*theta model)."""
        hours = system_info['hours']
        tol = 2.0
        bus_ids = system_info['bus_ids']
        n_buses = len(bus_ids)
        n_lines = system_info['n_lines']
        bus_idx = {b: i for i, b in enumerate(bus_ids)}
        ref_bus = system_info['ref_bus']
        ref_idx = bus_idx[ref_bus]
        mask = [i for i in range(n_buses) if i != ref_idx]

        for t_idx, t in enumerate(hours):
            P_inj = np.zeros(n_buses)
            for b in bus_ids:
                bi = bus_idx[b]
                gen_power = sum(
                    solution['dispatch_mw'][g][t_idx]
                    for g in system_info['gens_at_bus'].get(b, [])
                )
                P_inj[bi] = gen_power - system_info['bus_load'].get((b, t), 0.0)

            B = np.zeros((n_buses, n_buses))
            for l in range(n_lines):
                fi = bus_idx[system_info['line_from'][l]]
                ti = bus_idx[system_info['line_to'][l]]
                bl = system_info['line_b'][l]
                B[fi, fi] += bl
                B[ti, ti] += bl
                B[fi, ti] -= bl
                B[ti, fi] -= bl

            B_red = B[np.ix_(mask, mask)]
            P_red = P_inj[mask]
            theta_red = np.linalg.solve(B_red, P_red)

            theta = np.zeros(n_buses)
            j = 0
            for i in range(n_buses):
                if i != ref_idx:
                    theta[i] = theta_red[j]
                    j += 1

            for l in range(n_lines):
                key = f"{system_info['line_from'][l]}_{system_info['line_to'][l]}"
                expected = system_info['line_b'][l] * (
                    theta[bus_idx[system_info['line_from'][l]]] -
                    theta[bus_idx[system_info['line_to'][l]]]
                )
                actual = solution['line_flow_mw'][key][t_idx]
                assert abs(actual - expected) < tol, \
                    f"DC flow mismatch on line {key} hour {t}: {actual:.2f} vs {expected:.2f}"

    def test_line_thermal_limits(self, solution, system_info):
        """Verify line flows respect thermal limits."""
        hours = system_info['hours']
        tol = 1.0

        for l in range(system_info['n_lines']):
            limit = system_info['line_limit'][l]
            if limit <= 0:
                continue
            key = f"{system_info['line_from'][l]}_{system_info['line_to'][l]}"
            for t_idx, t in enumerate(hours):
                flow = solution['line_flow_mw'][key][t_idx]
                assert abs(flow) <= limit + tol, \
                    f"Line {key} flow {flow:.2f} exceeds limit {limit} at hour {t}"

    def test_generator_output_limits(self, solution, system_info):
        """Verify generator outputs respect Pmax when committed."""
        hours = system_info['hours']
        tol = 1.0

        for g in system_info['gen_names']:
            pmax = system_info['gen_pmax'][g]
            for t_idx in range(len(hours)):
                uc = solution['unit_commitment'][g][t_idx]
                p = solution['dispatch_mw'][g][t_idx]
                if uc == 0:
                    assert abs(p) < tol, \
                        f"{g} generating {p:.2f} MW while decommitted at hour {hours[t_idx]}"
                else:
                    assert p <= pmax + tol, \
                        f"{g} output {p:.2f} exceeds Pmax={pmax} at hour {hours[t_idx]}"
                    assert p >= -tol, \
                        f"{g} output {p:.2f} negative at hour {hours[t_idx]}"

    def test_ramp_constraints(self, solution, system_info):
        """Verify inter-temporal ramp rate constraints."""
        hours = system_info['hours']
        gen_config = system_info['gen_config']
        tol = 2.0

        for g in system_info['gen_names']:
            ramp = system_info['gen_ramp'][g]
            su_ramp = gen_config[g]['startup_ramp']
            sd_ramp = gen_config[g]['shutdown_ramp']
            init_power = gen_config[g]['initial_power']
            init_on = 1 if gen_config[g]['initial_status'] > 0 else 0

            for t_idx in range(len(hours)):
                p_now = solution['dispatch_mw'][g][t_idx]
                uc_now = solution['unit_commitment'][g][t_idx]

                if t_idx == 0:
                    p_prev = init_power
                    uc_prev = init_on
                else:
                    p_prev = solution['dispatch_mw'][g][t_idx - 1]
                    uc_prev = solution['unit_commitment'][g][t_idx - 1]

                startup = (uc_now == 1 and uc_prev == 0)
                shutdown = (uc_now == 0 and uc_prev == 1)

                if startup:
                    assert p_now <= su_ramp + tol, \
                        f"{g} startup output {p_now:.2f} > startup_ramp {su_ramp} at hour {hours[t_idx]}"
                elif shutdown:
                    assert p_prev <= sd_ramp + tol, \
                        f"{g} pre-shutdown output {p_prev:.2f} > shutdown_ramp {sd_ramp} at hour {hours[t_idx]}"
                elif uc_now == 1 and uc_prev == 1:
                    delta = p_now - p_prev
                    assert delta <= ramp + tol, \
                        f"{g} ramp up {delta:.2f} > ramp_limit {ramp} at hour {hours[t_idx]}"
                    assert -delta <= ramp + tol, \
                        f"{g} ramp down {-delta:.2f} > ramp_limit {ramp} at hour {hours[t_idx]}"

    def test_min_up_time(self, solution, system_info):
        """Verify minimum up time constraints."""
        hours = system_info['hours']
        gen_config = system_info['gen_config']

        for g in system_info['gen_names']:
            ut = gen_config[g]['min_up_time']
            uc = solution['unit_commitment'][g]
            init_on = 1 if gen_config[g]['initial_status'] > 0 else 0

            full_uc = [init_on] + uc
            for i in range(1, len(full_uc)):
                if full_uc[i] == 1 and full_uc[i - 1] == 0:
                    for j in range(i, min(i + ut, len(full_uc))):
                        assert full_uc[j] == 1, \
                            f"{g} violates min_up_time={ut}: started at step {i-1}, off at step {j-1}"

    def test_min_down_time(self, solution, system_info):
        """Verify minimum down time constraints."""
        hours = system_info['hours']
        gen_config = system_info['gen_config']

        for g in system_info['gen_names']:
            dt = gen_config[g]['min_down_time']
            uc = solution['unit_commitment'][g]
            init_on = 1 if gen_config[g]['initial_status'] > 0 else 0

            full_uc = [init_on] + uc
            for i in range(1, len(full_uc)):
                if full_uc[i] == 0 and full_uc[i - 1] == 1:
                    for j in range(i, min(i + dt, len(full_uc))):
                        assert full_uc[j] == 0, \
                            f"{g} violates min_down_time={dt}: shut down at step {i-1}, on at step {j-1}"

    def test_total_demand_met(self, solution, system_info):
        """Verify total generation equals total demand each hour."""
        hours = system_info['hours']
        tol = 1.0

        for t_idx, t in enumerate(hours):
            total_gen = sum(
                solution['dispatch_mw'][g][t_idx]
                for g in system_info['gen_names']
            )
            total_load = sum(
                system_info['bus_load'].get((b, t), 0.0)
                for b in system_info['bus_ids']
            )
            assert abs(total_gen - total_load) < tol, \
                f"Total gen {total_gen:.2f} != total load {total_load:.2f} at hour {t}"


# ============ Reserve Tests ============

class TestReserve:
    def test_reserve_computation(self, solution, system_info):
        """Verify reserve_mw matches committed capacity minus dispatch."""
        hours = system_info['hours']
        tol = 1.0

        for t_idx in range(len(hours)):
            computed = sum(
                system_info['gen_pmax'][g] * solution['unit_commitment'][g][t_idx]
                - solution['dispatch_mw'][g][t_idx]
                for g in system_info['gen_names']
            )
            reported = solution['reserve_mw'][t_idx]
            assert abs(computed - reported) < tol, \
                f"Reserve mismatch at hour {hours[t_idx]}: computed {computed:.2f} vs reported {reported:.2f}"

    def test_reserve_meets_requirement(self, solution, system_info):
        """Verify spinning reserve meets hourly requirement."""
        hours = system_info['hours']
        reserve_req = system_info['reserve_req']
        tol = 1.0

        for t_idx in range(len(hours)):
            reserve = solution['reserve_mw'][t_idx]
            req = reserve_req[t_idx]
            assert reserve >= req - tol, \
                f"Reserve {reserve:.2f} < requirement {req:.2f} at hour {hours[t_idx]}"

    def test_reserve_forces_commitment(self, solution, system_info):
        """Verify that reserve requirements force additional commitment beyond
        what is needed for energy alone at peak hours."""
        hours = system_info['hours']
        reserve_req = system_info['reserve_req']

        for t_idx in range(len(hours)):
            total_load = sum(
                system_info['bus_load'].get((b, hours[t_idx]), 0.0)
                for b in system_info['bus_ids']
            )
            total_committed_cap = sum(
                system_info['gen_pmax'][g] * solution['unit_commitment'][g][t_idx]
                for g in system_info['gen_names']
            )
            assert total_committed_cap >= total_load + reserve_req[t_idx] - 1.0, \
                f"Hour {hours[t_idx]}: committed capacity {total_committed_cap:.0f} " \
                f"< load {total_load:.0f} + reserve {reserve_req[t_idx]}"


# ============ LMP Decomposition Tests ============

class TestLMPDecomposition:
    def test_decomposition_identity(self, solution, system_info):
        """Verify LMP = energy + congestion at every bus, every hour."""
        tol = 0.1
        hours = system_info['hours']

        for b in system_info['bus_ids']:
            bkey = f"Bus{b}"
            for t_idx in range(len(hours)):
                total = solution['lmp'][bkey][t_idx]
                energy = solution['lmp_energy'][bkey][t_idx]
                congestion = solution['lmp_congestion'][bkey][t_idx]
                assert abs(total - (energy + congestion)) < tol, \
                    f"LMP decomposition mismatch at {bkey}, hour {hours[t_idx]}: " \
                    f"{total} != {energy} + {congestion}"

    def test_energy_component_uniform(self, solution, system_info):
        """Verify energy component is the same at all buses for each hour."""
        tol = 0.1
        hours = system_info['hours']

        for t_idx in range(len(hours)):
            energies = []
            for b in system_info['bus_ids']:
                bkey = f"Bus{b}"
                energies.append(solution['lmp_energy'][bkey][t_idx])
            assert max(energies) - min(energies) < tol, \
                f"Energy component not uniform at hour {hours[t_idx]}: {energies}"

    def test_congestion_zero_at_ref_bus(self, solution, system_info):
        """Verify congestion component is zero at reference bus."""
        tol = 0.1
        ref_key = f"Bus{system_info['ref_bus']}"
        hours = system_info['hours']

        for t_idx in range(len(hours)):
            cong = solution['lmp_congestion'][ref_key][t_idx]
            assert abs(cong) < tol, \
                f"Congestion at ref bus nonzero at hour {hours[t_idx]}: {cong}"

    def test_lmps_are_reasonable(self, solution, system_info):
        """Verify LMPs are within a reasonable range."""
        hours = system_info['hours']
        for b in system_info['bus_ids']:
            bkey = f"Bus{b}"
            for t_idx in range(len(hours)):
                lmp_val = solution['lmp'][bkey][t_idx]
                assert -10 <= lmp_val <= 200, \
                    f"LMP at {bkey}, hour {hours[t_idx]} = {lmp_val} outside reasonable range"


# ============ Cost Consistency Tests ============

class TestCostConsistency:
    def test_total_cost_sum(self, solution):
        """Verify total_cost = production + startup."""
        tol = 1.0
        assert abs(solution['total_cost'] -
                   (solution['total_production_cost'] + solution['total_startup_cost'])) < tol, \
            "total_cost != production + startup"

    def test_production_cost_matches_dispatch(self, solution, system_info):
        """Verify production cost matches sum of c1*P + c0*u."""
        hours = system_info['hours']
        tol = 10.0

        computed = 0.0
        for g in system_info['gen_names']:
            c1 = system_info['gen_c1'][g]
            c0 = system_info['gen_c0'][g]
            for t_idx in range(len(hours)):
                p = solution['dispatch_mw'][g][t_idx]
                u = solution['unit_commitment'][g][t_idx]
                computed += c1 * p + c0 * u

        assert abs(computed - solution['total_production_cost']) < tol, \
            f"Production cost mismatch: computed {computed:.2f} vs reported {solution['total_production_cost']:.2f}"

    def test_startup_cost_matches_commitment(self, solution, system_info):
        """Verify startup cost matches startup events."""
        gen_config = system_info['gen_config']
        hours = system_info['hours']
        tol = 1.0

        computed = 0.0
        for g in system_info['gen_names']:
            uc = solution['unit_commitment'][g]
            init_on = 1 if gen_config[g]['initial_status'] > 0 else 0
            su_cost = system_info['gen_startup_cost'][g]

            full_uc = [init_on] + uc
            for i in range(1, len(full_uc)):
                if full_uc[i] == 1 and full_uc[i - 1] == 0:
                    computed += su_cost

        assert abs(computed - solution['total_startup_cost']) < tol, \
            f"Startup cost mismatch: computed {computed:.2f} vs reported {solution['total_startup_cost']:.2f}"


# ============ Contingency Tests ============

class TestContingency:
    def _compute_contingency(self, system_info, solution):
        """Independently compute post-contingency flows."""
        bus_ids = system_info['bus_ids']
        n_buses = len(bus_ids)
        n_lines = system_info['n_lines']
        bus_idx = {b: i for i, b in enumerate(bus_ids)}
        ref_bus = system_info['ref_bus']
        ref_idx = bus_idx[ref_bus]
        mask = [i for i in range(n_buses) if i != ref_idx]
        hours = system_info['hours']

        results = {}

        for k in range(n_lines):
            key_k = f"{system_info['line_from'][k]}_{system_info['line_to'][k]}"
            max_overload_pct = 0.0
            violations = []

            B = np.zeros((n_buses, n_buses))
            for l in range(n_lines):
                if l == k:
                    continue
                fi = bus_idx[system_info['line_from'][l]]
                ti = bus_idx[system_info['line_to'][l]]
                bl = system_info['line_b'][l]
                B[fi, fi] += bl
                B[ti, ti] += bl
                B[fi, ti] -= bl
                B[ti, fi] -= bl

            B_red = B[np.ix_(mask, mask)]

            # Check if B_red is singular (islanding)
            if abs(np.linalg.det(B_red)) < 1e-10:
                results[key_k] = {"max_overload_pct": 0.0, "violations": []}
                continue

            for t_idx, t in enumerate(hours):
                P_inj = np.zeros(n_buses)
                for b in bus_ids:
                    bi = bus_idx[b]
                    gen_power = sum(
                        solution['dispatch_mw'][g][t_idx]
                        for g in system_info['gens_at_bus'].get(b, [])
                    )
                    P_inj[bi] = gen_power - system_info['bus_load'].get((b, t), 0.0)

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
                    limit = system_info['line_limit'][l]
                    if limit <= 0:
                        continue
                    flow = system_info['line_b'][l] * (
                        theta[bus_idx[system_info['line_from'][l]]] -
                        theta[bus_idx[system_info['line_to'][l]]]
                    )
                    pct = abs(flow) / limit * 100
                    max_overload_pct = max(max_overload_pct, pct)

                    emergency = 1.3 * limit
                    if abs(flow) > emergency:
                        key_l = f"{system_info['line_from'][l]}_{system_info['line_to'][l]}"
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

    def test_contingency_max_overload(self, solution, system_info):
        """Verify max_overload_pct matches independently computed values."""
        ref = self._compute_contingency(system_info, solution)
        tol = 5.0  # percentage point tolerance

        for key in ref:
            assert key in solution['contingency_results'], \
                f"Missing contingency key: {key}"
            ref_pct = ref[key]['max_overload_pct']
            agent_pct = solution['contingency_results'][key]['max_overload_pct']
            assert abs(ref_pct - agent_pct) < tol, \
                f"Contingency {key}: max_overload_pct {agent_pct} vs expected {ref_pct}"

    def test_contingency_violations_consistent(self, solution, system_info):
        """Verify reported violations match independently computed ones."""
        ref = self._compute_contingency(system_info, solution)

        for key in ref:
            ref_violations = ref[key]['violations']
            agent_violations = solution['contingency_results'][key]['violations']

            # Same number of violations
            assert len(agent_violations) == len(ref_violations), \
                f"Contingency {key}: {len(agent_violations)} violations vs expected {len(ref_violations)}"

            # Check each violation (order-independent)
            ref_set = {(v['line'], v['hour']) for v in ref_violations}
            agent_set = {(v['line'], v['hour']) for v in agent_violations}
            assert ref_set == agent_set, \
                f"Contingency {key}: violation mismatch. Expected {ref_set}, got {agent_set}"

    def test_contingency_violation_flows(self, solution, system_info):
        """Verify reported violation flow magnitudes are accurate."""
        ref = self._compute_contingency(system_info, solution)
        tol = 5.0  # MW

        for key in ref:
            ref_violations = {(v['line'], v['hour']): v['flow_mw'] for v in ref[key]['violations']}
            for v in solution['contingency_results'][key].get('violations', []):
                vkey = (v['line'], v['hour'])
                if vkey in ref_violations:
                    assert abs(v['flow_mw'] - ref_violations[vkey]) < tol, \
                        f"Contingency {key}, violation {vkey}: flow {v['flow_mw']} vs expected {ref_violations[vkey]}"


# ============ Optimality Test ============

class TestOptimality:
    def test_cost_near_reference(self, solution, system_info):
        """Verify total cost is near optimal by computing reference solution."""
        try:
            ref_cost = self._compute_reference_cost(system_info)
        except Exception as e:
            pytest.skip(f"Reference solver failed: {e}")
            return

        agent_cost = solution['total_cost']
        assert agent_cost <= ref_cost * 1.01 + 100, \
            f"Agent cost {agent_cost:.2f} significantly exceeds reference {ref_cost:.2f}"
        assert agent_cost >= ref_cost * 0.99 - 100, \
            f"Agent cost {agent_cost:.2f} suspiciously below reference {ref_cost:.2f}"

    def _compute_reference_cost(self, info):
        """Compute reference SCUC cost using Pyomo + CBC."""
        from pyomo.environ import (
            ConcreteModel, Set, Var, Objective, Constraint, Suffix,
            Binary, NonNegativeReals, Reals, SolverFactory, value, minimize
        )

        hours = info['hours']
        bus_ids = info['bus_ids']
        gen_names = info['gen_names']
        n_lines = info['n_lines']
        gen_config = info['gen_config']
        ref_bus = info['ref_bus']
        reserve_req = info['reserve_req']

        init_on = {}
        for g in gen_names:
            init_on[g] = 1 if gen_config[g]['initial_status'] > 0 else 0

        m = ConcreteModel()
        m.B = Set(initialize=bus_ids)
        m.G = Set(initialize=gen_names)
        m.L = Set(initialize=list(range(n_lines)))
        m.T = Set(initialize=hours, ordered=True)

        m.u = Var(m.G, m.T, within=Binary)
        m.v = Var(m.G, m.T, within=Binary)
        m.w = Var(m.G, m.T, within=Binary)
        m.p = Var(m.G, m.T, within=NonNegativeReals)
        m.th = Var(m.B, m.T, within=Reals, bounds=(-3.15, 3.15))
        m.f = Var(m.L, m.T, within=Reals)

        def c_ref(mod, t):
            return mod.th[ref_bus, t] == 0.0
        m.c_ref = Constraint(m.T, rule=c_ref)

        gens_at_bus = info['gens_at_bus']
        bus_load = info['bus_load']
        line_from = info['line_from']
        line_to = info['line_to']
        line_b = info['line_b']
        line_limit = info['line_limit']
        gen_pmax = info['gen_pmax']
        gen_pmin = info['gen_pmin']
        gen_ramp = info['gen_ramp']

        def c_pb(mod, b, t):
            gp = sum(mod.p[g, t] for g in gens_at_bus.get(b, []))
            inf_ = sum(mod.f[l, t] for l in range(n_lines) if line_to[l] == b)
            out_ = sum(mod.f[l, t] for l in range(n_lines) if line_from[l] == b)
            return gp + inf_ - out_ == bus_load.get((b, t), 0.0)
        m.c_pb = Constraint(m.B, m.T, rule=c_pb)

        def c_dc(mod, l, t):
            return mod.f[l, t] == line_b[l] * (mod.th[line_from[l], t] - mod.th[line_to[l], t])
        m.c_dc = Constraint(m.L, m.T, rule=c_dc)

        def c_lu(mod, l, t):
            return mod.f[l, t] <= line_limit[l] if line_limit[l] > 0 else Constraint.Skip
        m.c_lu = Constraint(m.L, m.T, rule=c_lu)

        def c_ll(mod, l, t):
            return mod.f[l, t] >= -line_limit[l] if line_limit[l] > 0 else Constraint.Skip
        m.c_ll = Constraint(m.L, m.T, rule=c_ll)

        def c_gu(mod, g, t):
            return mod.p[g, t] <= gen_pmax[g] * mod.u[g, t]
        m.c_gu = Constraint(m.G, m.T, rule=c_gu)

        def c_gl(mod, g, t):
            return mod.p[g, t] >= gen_pmin[g] * mod.u[g, t]
        m.c_gl = Constraint(m.G, m.T, rule=c_gl)

        def c_link(mod, g, t):
            ti = hours.index(t)
            prev = init_on[g] if ti == 0 else mod.u[g, hours[ti - 1]]
            return mod.u[g, t] - prev == mod.v[g, t] - mod.w[g, t]
        m.c_link = Constraint(m.G, m.T, rule=c_link)

        def c_excl(mod, g, t):
            return mod.v[g, t] + mod.w[g, t] <= 1
        m.c_excl = Constraint(m.G, m.T, rule=c_excl)

        def c_ru(mod, g, t):
            ti = hours.index(t)
            su_r = gen_config[g]['startup_ramp']
            if ti == 0:
                return mod.p[g, t] - gen_config[g]['initial_power'] <= gen_ramp[g] * init_on[g] + su_r * mod.v[g, t]
            tp = hours[ti - 1]
            return mod.p[g, t] - mod.p[g, tp] <= gen_ramp[g] * mod.u[g, tp] + su_r * mod.v[g, t]
        m.c_ru = Constraint(m.G, m.T, rule=c_ru)

        def c_rd(mod, g, t):
            ti = hours.index(t)
            sd_r = gen_config[g]['shutdown_ramp']
            if ti == 0:
                return gen_config[g]['initial_power'] - mod.p[g, t] <= gen_ramp[g] * mod.u[g, t] + sd_r * mod.w[g, t]
            tp = hours[ti - 1]
            return mod.p[g, tp] - mod.p[g, t] <= gen_ramp[g] * mod.u[g, t] + sd_r * mod.w[g, t]
        m.c_rd = Constraint(m.G, m.T, rule=c_rd)

        def c_su_lim(mod, g, t):
            diff = gen_pmax[g] - gen_config[g]['startup_ramp']
            if diff <= 0:
                return Constraint.Skip
            return mod.p[g, t] <= gen_pmax[g] * mod.u[g, t] - diff * mod.v[g, t]
        m.c_su_lim = Constraint(m.G, m.T, rule=c_su_lim)

        def c_sd_lim(mod, g, t):
            ti = hours.index(t)
            diff = gen_pmax[g] - gen_config[g]['shutdown_ramp']
            if diff <= 0 or ti == 0:
                return Constraint.Skip
            tp = hours[ti - 1]
            return mod.p[g, tp] <= gen_pmax[g] * mod.u[g, tp] - diff * mod.w[g, t]
        m.c_sd_lim = Constraint(m.G, m.T, rule=c_sd_lim)

        def c_mu(mod, g, t):
            ti = hours.index(t)
            ut = gen_config[g]['min_up_time']
            if ut <= 0:
                return Constraint.Skip
            start = max(0, ti - ut + 1)
            window = [hours[k] for k in range(start, ti + 1)]
            return sum(mod.v[g, h] for h in window) <= mod.u[g, t]
        m.c_mu = Constraint(m.G, m.T, rule=c_mu)

        def c_md(mod, g, t):
            ti = hours.index(t)
            dt = gen_config[g]['min_down_time']
            if dt <= 0:
                return Constraint.Skip
            start = max(0, ti - dt + 1)
            window = [hours[k] for k in range(start, ti + 1)]
            return sum(mod.w[g, h] for h in window) <= 1 - mod.u[g, t]
        m.c_md = Constraint(m.G, m.T, rule=c_md)

        # Reserve constraint
        def c_reserve(mod, t):
            ti = hours.index(t)
            return sum(gen_pmax[g] * mod.u[g, t] - mod.p[g, t]
                       for g in gen_names) >= reserve_req[ti]
        m.c_reserve = Constraint(m.T, rule=c_reserve)

        # Initial conditions
        for g in gen_names:
            if gen_config[g]['initial_status'] > 0:
                remaining = max(0, gen_config[g]['min_up_time'] - gen_config[g]['initial_status'])
                for ti in range(min(remaining, len(hours))):
                    m.u[g, hours[ti]].fix(1)
            elif gen_config[g]['initial_status'] < 0:
                remaining = max(0, gen_config[g]['min_down_time'] + gen_config[g]['initial_status'])
                for ti in range(min(remaining, len(hours))):
                    m.u[g, hours[ti]].fix(0)

        gen_c1 = info['gen_c1']
        gen_c0 = info['gen_c0']
        gen_startup_cost = info['gen_startup_cost']

        def obj(mod):
            return sum(gen_c1[g] * mod.p[g, t] + gen_c0[g] * mod.u[g, t]
                       for g in gen_names for t in hours) + \
                   sum(gen_startup_cost[g] * mod.v[g, t]
                       for g in gen_names for t in hours)
        m.obj = Objective(rule=obj, sense=minimize)

        solver = SolverFactory('cbc')
        solver.options['ratioGap'] = 0.005
        solver.options['seconds'] = 120
        result = solver.solve(m, tee=False)

        return value(m.obj)
