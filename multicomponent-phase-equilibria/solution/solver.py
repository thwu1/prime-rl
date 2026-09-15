#!/usr/bin/env python3

"""
Multi-component phase equilibrium solver using Peng-Robinson EOS.
Reads /app/systems.json, performs flash/bubble/dew calculations,
writes results to /app/results.json.
"""

import json
import sys

from thermo import ChemicalConstantsPackage, PropertyCorrelationsPackage
from thermo.heat_capacity import HeatCapacityGas
from thermo.phases import CEOSGas, CEOSLiquid
from thermo.eos_mix import PRMIX
from thermo.flash import FlashVL, FlashVLN


def build_system(sys_spec):
    """Build thermo objects for a system specification."""
    comps = sys_spec['components']
    N = len(comps['CASs'])

    constants = ChemicalConstantsPackage(
        Tcs=comps['Tcs'],
        Pcs=comps['Pcs'],
        omegas=comps['omegas'],
        MWs=comps['MWs'],
        CASs=comps['CASs'],
    )

    cp_gases = []
    for fit in comps['Cp_poly_fits']:
        cp_gases.append(HeatCapacityGas(
            poly_fit=(fit['T_min'], fit['T_max'], fit['coefficients'])
        ))

    correlations = PropertyCorrelationsPackage(
        constants=constants,
        HeatCapacityGases=cp_gases,
        skip_missing=True,
    )

    kijs = sys_spec['kijs']
    eos_kwargs = dict(
        Tcs=comps['Tcs'],
        Pcs=comps['Pcs'],
        omegas=comps['omegas'],
        kijs=kijs,
    )

    zs_ref = [1.0 / N] * N
    T_ref, P_ref = 300.0, 101325.0

    gas = CEOSGas(PRMIX, eos_kwargs, HeatCapacityGases=cp_gases,
                  T=T_ref, P=P_ref, zs=zs_ref)
    liq = CEOSLiquid(PRMIX, eos_kwargs, HeatCapacityGases=cp_gases,
                     T=T_ref, P=P_ref, zs=zs_ref)

    return constants, correlations, gas, liq


def normalize(zs):
    """Normalize mole fractions to sum to 1."""
    s = sum(zs)
    return [z / s for z in zs]


def run_flash_pt(constants, correlations, gas, liq, calc):
    """Run a PT flash calculation."""
    T = calc['T']
    P = calc['P']
    zs = normalize(calc['zs'])
    allow_VLL = calc.get('allow_VLL', False)

    if allow_VLL:
        flasher = FlashVLN(constants, correlations,
                           liquids=[liq, liq], gas=gas)
    else:
        flasher = FlashVL(constants, correlations,
                          liquid=liq, gas=gas)

    res = flasher.flash(T=T, P=P, zs=zs)

    phase_count = res.phase_count
    betas = list(res.betas)

    compositions = []
    if res.gas is not None:
        compositions.append(list(res.gas.zs))
    for liq_phase in res.liquids:
        compositions.append(list(liq_phase.zs))

    # Single phase edge case
    if phase_count == 1:
        if res.gas is not None:
            compositions = [list(res.gas.zs)]
        elif len(res.liquids) > 0:
            compositions = [list(res.liquids[0].zs)]
        else:
            compositions = [zs]
        betas = [1.0]

    return {
        'type': 'flash_PT',
        'phase_count': phase_count,
        'betas': betas,
        'compositions': compositions,
    }


def run_bubble_pressure(constants, correlations, gas, liq, calc):
    """Compute bubble-point pressure."""
    T = calc['T']
    zs = normalize(calc['zs'])

    flasher = FlashVLN(constants, correlations, liquids=[liq], gas=gas)
    res = flasher.flash(T=T, VF=0, zs=zs)

    return {
        'type': 'bubble_pressure',
        'pressure': res.P,
    }


def run_dew_pressure(constants, correlations, gas, liq, calc):
    """Compute dew-point pressure."""
    T = calc['T']
    zs = normalize(calc['zs'])

    flasher = FlashVLN(constants, correlations, liquids=[liq], gas=gas)
    res = flasher.flash(T=T, VF=1, zs=zs)

    return {
        'type': 'dew_pressure',
        'pressure': res.P,
    }


def process_system(sys_spec):
    """Process all calculations for one system."""
    constants, correlations, gas, liq = build_system(sys_spec)

    calc_results = []
    for calc in sys_spec['calculations']:
        calc_type = calc['type']

        if calc_type == 'flash_PT':
            result = run_flash_pt(constants, correlations, gas, liq, calc)
        elif calc_type == 'bubble_pressure':
            result = run_bubble_pressure(constants, correlations, gas, liq, calc)
        elif calc_type == 'dew_pressure':
            result = run_dew_pressure(constants, correlations, gas, liq, calc)
        else:
            raise ValueError(f"Unknown calculation type: {calc_type}")

        calc_results.append(result)

    return {'calculations': calc_results}


def main():
    with open('/app/systems.json') as f:
        data = json.load(f)

    results = {}
    for sys_spec in data['systems']:
        sys_id = sys_spec['id']
        print(f"Processing system: {sys_id}")
        results[sys_id] = process_system(sys_spec)
        print(f"  Done: {len(sys_spec['calculations'])} calculations")

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Results written to /app/results.json")


if __name__ == '__main__':
    main()
