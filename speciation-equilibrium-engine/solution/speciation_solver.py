#!/usr/bin/env python3
"""
Aqueous Geochemical Speciation Engine — Reference Solution
Solves coupled mass-action / mass-balance equations for aqueous equilibrium
and computes mineral saturation indices.
"""

import json
import re
import sys
import numpy as np
from scipy.optimize import fsolve


def parse_terms(s):
    """Parse '2 Ca+2 + CO3-2 + H+' into [(2.0, 'Ca+2'), (1.0, 'CO3-2'), (1.0, 'H+')]"""
    terms = []
    # Split on ' + ' (with surrounding spaces) to preserve ionic charges like Ca+2, H+
    for part in re.split(r'\s+\+\s+', s.strip()):
        part = part.strip()
        if not part:
            continue
        match = re.match(r'^(\d+(?:\.\d+)?)\s+(.+)$', part)
        if match:
            coeff = float(match.group(1))
            name = match.group(2).strip()
        else:
            coeff = 1.0
            name = part.strip()
        terms.append((coeff, name))
    return terms


def parse_species_db(filename):
    """Parse species.dat to extract components and species definitions."""
    components = []
    species_list = []
    section = None

    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line == 'COMPONENTS':
                section = 'components'
                continue
            elif line == 'SPECIES':
                section = 'species'
                continue
            elif line == 'END':
                section = None
                continue

            if section == 'components':
                components.append(line)
            elif section == 'species':
                parts = line.split('|')
                reaction_str = parts[0].strip()
                log_k = float(parts[1].strip().split('=')[1].strip())

                lhs_str, rhs_str = reaction_str.split('=', 1)
                lhs_terms = parse_terms(lhs_str.strip())
                rhs_terms = parse_terms(rhs_str.strip())

                # Identify the new species: the RHS term that is not a component and not H2O
                species_name = None
                for coeff, name in rhs_terms:
                    if name != 'H2O' and name not in components:
                        species_name = name
                        break

                if species_name is None:
                    continue

                # Build mass-action exponents:
                # positive for LHS components, negative for RHS components
                exponents = {}
                required_components = set()

                for coeff, name in lhs_terms:
                    if name == 'H2O' or name == species_name:
                        continue
                    if name in components:
                        exponents[name] = exponents.get(name, 0) + coeff
                        if name != 'H+':
                            required_components.add(name)

                for coeff, name in rhs_terms:
                    if name == 'H2O' or name == species_name:
                        continue
                    if name in components:
                        exponents[name] = exponents.get(name, 0) - coeff
                        if name != 'H+':
                            required_components.add(name)

                # Mass-balance coefficients: how much of each non-H+ component is consumed
                # For LHS components: positive (consumed)
                # For RHS components: negative (released) — unusual for non-H+ but handle it
                mass_balance = {}
                for coeff, name in lhs_terms:
                    if name == 'H2O' or name == species_name or name == 'H+':
                        continue
                    if name in components:
                        mass_balance[name] = mass_balance.get(name, 0) + coeff

                for coeff, name in rhs_terms:
                    if name == 'H2O' or name == species_name or name == 'H+':
                        continue
                    if name in components:
                        mass_balance[name] = mass_balance.get(name, 0) - coeff

                species_list.append({
                    'name': species_name,
                    'log_k': log_k,
                    'exponents': exponents,
                    'mass_balance': mass_balance,
                    'required_components': required_components,
                })

    return components, species_list


def parse_phases_db(filename, components):
    """Parse phases.dat to extract mineral phase dissolution reactions."""
    phases = []
    section = None

    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line == 'PHASES':
                section = 'phases'
                continue
            elif line == 'END':
                section = None
                continue

            if section == 'phases':
                parts = line.split('|')
                mineral_name = parts[0].strip()
                reaction_str = parts[1].strip()
                log_k = float(parts[2].strip().split('=')[1].strip())

                lhs_str, rhs_str = reaction_str.split('=', 1)
                lhs_terms = parse_terms(lhs_str.strip())
                rhs_terms = parse_terms(rhs_str.strip())

                # IAP exponents: positive for RHS components, negative for LHS components
                # Skip mineral formula and H2O
                iap_exponents = {}
                required_components = set()

                for coeff, name in rhs_terms:
                    if name == 'H2O':
                        continue
                    if name in components:
                        iap_exponents[name] = iap_exponents.get(name, 0) + coeff
                        if name != 'H+':
                            required_components.add(name)

                for coeff, name in lhs_terms:
                    if name == 'H2O':
                        continue
                    if name in components:
                        iap_exponents[name] = iap_exponents.get(name, 0) - coeff
                        if name != 'H+':
                            required_components.add(name)

                phases.append({
                    'name': mineral_name,
                    'log_k': log_k,
                    'iap_exponents': iap_exponents,
                    'required_components': required_components,
                })

    return phases


def solve_scenario(scenario, components, all_species, all_phases):
    """Solve equilibrium speciation for a single scenario."""
    pH = scenario['pH']
    h_conc = 10.0 ** (-pH)
    total_concs = scenario['total_concentrations']

    # Active components (non-H+ components present in this scenario)
    active_components = [c for c in components if c != 'H+' and c in total_concs]
    n_comp = len(active_components)
    active_set = set(active_components)

    # Filter species relevant to this scenario
    relevant_species = [
        s for s in all_species
        if s['required_components'].issubset(active_set)
    ]

    # Filter phases relevant to this scenario
    relevant_phases = [
        p for p in all_phases
        if p['required_components'].issubset(active_set)
    ]

    def compute_species_concs(p_vec):
        """Given p = -log10(free_conc), compute all species concentrations."""
        log_free = {'H+': -pH}
        for i, comp in enumerate(active_components):
            log_free[comp] = -p_vec[i]

        sp_concs = {}
        for s in relevant_species:
            log_c = s['log_k']
            for comp, exp in s['exponents'].items():
                if comp in log_free:
                    log_c += exp * log_free[comp]
            # Clamp to avoid overflow
            log_c = max(log_c, -300)
            sp_concs[s['name']] = 10.0 ** log_c

        return sp_concs

    def residuals(p_vec):
        """Compute normalized mass-balance residuals."""
        sp_concs = compute_species_concs(p_vec)
        res = np.zeros(n_comp)

        for i, comp in enumerate(active_components):
            free_c = 10.0 ** (-p_vec[i])
            calc_total = free_c
            for s in relevant_species:
                if comp in s['mass_balance']:
                    calc_total += s['mass_balance'][comp] * sp_concs[s['name']]
            # Normalized residual
            res[i] = (calc_total - total_concs[comp]) / total_concs[comp]

        return res

    # Initial guess: p = -log10(total_concentration)
    p0 = np.array([-np.log10(total_concs[c]) for c in active_components])

    # Try multiple starting points
    best_sol = None
    best_max_res = float('inf')

    for offsets in _generate_offsets(n_comp):
        p_try = p0 + np.array(offsets[:n_comp])
        try:
            sol, info, ier, msg = fsolve(residuals, p_try, full_output=True, maxfev=20000)
            if ier == 1:
                res_check = residuals(sol)
                max_res = np.max(np.abs(res_check))
                if max_res < best_max_res:
                    best_max_res = max_res
                    best_sol = sol
                if max_res < 1e-8:
                    break
        except Exception:
            continue

    if best_sol is None or best_max_res > 0.01:
        raise RuntimeError(
            f"Solver failed for scenario '{scenario['name']}': "
            f"best residual = {best_max_res}"
        )

    # Compute final results
    sp_concs = compute_species_concs(best_sol)
    free_concs = {}
    for i, comp in enumerate(active_components):
        free_concs[comp] = 10.0 ** (-best_sol[i])

    # Saturation indices
    sat_indices = {}
    for ph in relevant_phases:
        log_iap = 0.0
        for comp, exp in ph['iap_exponents'].items():
            if comp == 'H+':
                log_iap += exp * (-pH)
            elif comp in free_concs:
                log_iap += exp * np.log10(free_concs[comp])
        sat_indices[ph['name']] = log_iap - ph['log_k']

    # Build output
    result = {
        'name': scenario['name'],
        'free_concentrations': {'H+': h_conc},
        'species_concentrations': {},
        'saturation_indices': {},
    }

    for comp in active_components:
        result['free_concentrations'][comp] = float(free_concs[comp])

    for name, conc in sp_concs.items():
        if conc >= 1e-20:
            result['species_concentrations'][name] = float(conc)

    for name, si in sat_indices.items():
        result['saturation_indices'][name] = float(si)

    return result


def _generate_offsets(n):
    """Generate offset vectors for starting-point search."""
    base_offsets = [0, 1, 2, 3, -1, 4, 5, -2]
    # Uniform offsets
    for o in base_offsets:
        yield [o] * n
    # Mixed offsets for problems where components need different shifts
    if n >= 2:
        for o1 in [0, 2, 4]:
            for o2 in [0, 1, 3]:
                combo = [o1] + [o2] * (n - 1)
                yield combo
                combo2 = [o2] + [o1] * (n - 1)
                yield combo2


def main():
    components, species = parse_species_db('/app/species.dat')
    phases = parse_phases_db('/app/phases.dat', components)

    with open('/app/scenarios.json') as f:
        scenarios = json.load(f)

    results = []
    for scenario in scenarios:
        print(f"Solving scenario: {scenario['name']}...")
        result = solve_scenario(scenario, components, species, phases)
        results.append(result)
        print(f"  Done. Free concentrations: { {k: f'{v:.4e}' for k, v in result['free_concentrations'].items() if k != 'H+'} }")

    with open('/app/results.json', 'w') as f:
        json.dump({'scenarios': results}, f, indent=2)

    print(f"\nAll {len(results)} scenarios solved. Results written to /app/results.json")


if __name__ == '__main__':
    main()
