
import json
import os
import pytest


def load_results():
    path = '/app/results.json'
    assert os.path.exists(path), f"Results file not found at {path}"
    with open(path) as f:
        return json.load(f)


def assert_close(a, b, rtol=5e-3, atol=1e-8, msg=""):
    """Assert two values are close with informative message."""
    if abs(b) < 1e-10:
        assert abs(a - b) <= atol, (
            f"Expected ~{b}, got {a} (abs diff {abs(a-b)}, atol={atol}) {msg}"
        )
    else:
        rel = abs(a - b) / abs(b)
        assert rel <= rtol, (
            f"Expected ~{b}, got {a} (rel diff {rel:.6e}, rtol={rtol}) {msg}"
        )


def find_phase_by_dominant_component(compositions, component_index):
    """Find index of the phase with highest fraction of the given component."""
    best_idx = 0
    best_val = -1.0
    for i, comp in enumerate(compositions):
        if comp[component_index] > best_val:
            best_val = comp[component_index]
            best_idx = i
    return best_idx


def find_phase_closest(compositions, target):
    """Find index of the phase whose composition is closest to target (L2 norm)."""
    best_idx = 0
    best_dist = float('inf')
    for i, comp in enumerate(compositions):
        dist = sum((a - b) ** 2 for a, b in zip(comp, target)) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best_idx = i
    return best_idx


# ============================================================
# System: binary_vle (ethane / n-pentane)
# ============================================================
class TestBinaryVLE:
    """Binary ethane/pentane VLE flash at T=360K, P=3MPa.

    Expected two phases:
      - Ethane-rich phase: zs ~ [0.8179, 0.1821], beta ~ 0.7512
      - Pentane-rich phase: zs ~ [0.3677, 0.6323], beta ~ 0.2488
    Phase ordering in output may vary.
    """

    def test_results_exist(self):
        results = load_results()
        assert 'binary_vle' in results

    def test_phase_count(self):
        results = load_results()
        calc = results['binary_vle']['calculations'][0]
        assert calc['phase_count'] == 2

    def test_betas_sum(self):
        results = load_results()
        calc = results['binary_vle']['calculations'][0]
        assert_close(sum(calc['betas']), 1.0, rtol=1e-6, msg="betas sum")

    def test_ethane_rich_phase(self):
        results = load_results()
        calc = results['binary_vle']['calculations'][0]
        comps = calc['compositions']
        betas = calc['betas']

        # Ethane-rich phase: highest ethane (component 0) fraction
        idx = find_phase_by_dominant_component(comps, 0)
        assert_close(comps[idx][0], 0.8178671482462099, rtol=5e-3,
                     msg="ethane-rich phase z_ethane")
        assert_close(comps[idx][1], 0.18213285175379013, rtol=5e-3,
                     msg="ethane-rich phase z_pentane")
        assert_close(betas[idx], 0.7511539791450637, rtol=5e-3,
                     msg="ethane-rich phase beta")

    def test_pentane_rich_phase(self):
        results = load_results()
        calc = results['binary_vle']['calculations'][0]
        comps = calc['compositions']
        betas = calc['betas']

        # Pentane-rich phase: highest pentane (component 1) fraction
        idx = find_phase_by_dominant_component(comps, 1)
        assert_close(comps[idx][0], 0.3676551321096354, rtol=5e-3,
                     msg="pentane-rich phase z_ethane")
        assert_close(comps[idx][1], 0.6323448678903647, rtol=5e-3,
                     msg="pentane-rich phase z_pentane")
        assert_close(betas[idx], 0.24884602085493626, rtol=5e-3,
                     msg="pentane-rich phase beta")


# ============================================================
# System: hydrocarbon_envelope (C5/C6/C7 bubble & dew)
# ============================================================
class TestHydrocarbonEnvelope:
    """Ternary C5/C6/C7 bubble and dew point pressures."""

    def test_results_exist(self):
        results = load_results()
        assert 'hydrocarbon_envelope' in results
        assert len(results['hydrocarbon_envelope']['calculations']) == 6

    def test_bubble_pressure_160K(self):
        results = load_results()
        calc = results['hydrocarbon_envelope']['calculations'][0]
        assert_close(calc['pressure'], 1.6235262252797003, rtol=5e-3,
                     msg="bubble P at 160K")

    def test_bubble_pressure_204K(self):
        results = load_results()
        calc = results['hydrocarbon_envelope']['calculations'][1]
        assert_close(calc['pressure'], 263.46184653114784, rtol=5e-3,
                     msg="bubble P at 204K")

    def test_bubble_pressure_420K(self):
        results = load_results()
        calc = results['hydrocarbon_envelope']['calculations'][2]
        assert_close(calc['pressure'], 1333301.7057641603, rtol=5e-3,
                     msg="bubble P at 420K")

    def test_dew_pressure_160K(self):
        results = load_results()
        calc = results['hydrocarbon_envelope']['calculations'][3]
        assert_close(calc['pressure'], 0.13546631710512694, rtol=5e-3,
                     msg="dew P at 160K")

    def test_dew_pressure_204K(self):
        results = load_results()
        calc = results['hydrocarbon_envelope']['calculations'][4]
        assert_close(calc['pressure'], 77.336111529878, rtol=5e-3,
                     msg="dew P at 204K")

    def test_dew_pressure_420K(self):
        results = load_results()
        calc = results['hydrocarbon_envelope']['calculations'][5]
        assert_close(calc['pressure'], 1212555.0457456997, rtol=5e-3,
                     msg="dew P at 420K")


# ============================================================
# System: water_methane_octane (VLL)
# ============================================================
class TestWaterMethaneOctane:
    """Ternary VLL flash for water/methane/octane.
    Components: 0=water, 1=methane, 2=octane.
    """

    def test_results_exist(self):
        results = load_results()
        assert 'water_methane_octane' in results
        assert len(results['water_methane_octane']['calculations']) == 3

    # --- Calculation 0: T=298.15K, P=101325Pa ---
    def test_vll_phase_count_298K(self):
        results = load_results()
        calc = results['water_methane_octane']['calculations'][0]
        assert calc['phase_count'] == 3

    def test_vll_betas_sum_298K(self):
        results = load_results()
        calc = results['water_methane_octane']['calculations'][0]
        assert_close(sum(calc['betas']), 1.0, rtol=1e-6, msg="betas sum 298K")

    def test_vll_gas_phase_298K(self):
        results = load_results()
        calc = results['water_methane_octane']['calculations'][0]
        comps = calc['compositions']
        betas = calc['betas']

        # Gas: methane-dominant (component 1)
        gas_idx = find_phase_by_dominant_component(comps, 1)
        assert_close(betas[gas_idx], 0.3481686901529188, rtol=5e-3,
                     msg="gas beta 298K")
        assert_close(comps[gas_idx][0], 0.026792655758364814, rtol=1e-2,
                     msg="gas water 298K")
        assert_close(comps[gas_idx][1], 0.9529209534990141, rtol=5e-3,
                     msg="gas methane 298K")
        assert_close(comps[gas_idx][2], 0.020286390742620692, rtol=1e-2,
                     msg="gas octane 298K")

    def test_vll_water_phase_298K(self):
        results = load_results()
        calc = results['water_methane_octane']['calculations'][0]
        comps = calc['compositions']
        betas = calc['betas']

        # Water: water-dominant (component 0)
        water_idx = find_phase_by_dominant_component(comps, 0)
        assert comps[water_idx][0] > 0.9999, (
            f"Water phase should be >0.9999 water, got {comps[water_idx][0]}"
        )
        assert_close(betas[water_idx], 0.3182988549790946, rtol=5e-3,
                     msg="water beta 298K")

    def test_vll_organic_phase_298K(self):
        results = load_results()
        calc = results['water_methane_octane']['calculations'][0]
        comps = calc['compositions']
        betas = calc['betas']

        # Organic: octane-dominant (component 2)
        organic_idx = find_phase_by_dominant_component(comps, 2)
        assert comps[organic_idx][2] > 0.95, (
            f"Organic should be octane-rich, got {comps[organic_idx][2]}"
        )
        assert_close(betas[organic_idx], 0.33353245486798655, rtol=5e-3,
                     msg="organic beta 298K")
        assert_close(comps[organic_idx][2], 0.978226383908336, rtol=1e-2,
                     msg="organic octane 298K")

    # --- Calculation 1: T=307.838K, P=8.191MPa (high pressure) ---
    def test_vll_phase_count_high_P(self):
        results = load_results()
        calc = results['water_methane_octane']['calculations'][1]
        assert calc['phase_count'] == 3

    def test_vll_betas_sum_high_P(self):
        results = load_results()
        calc = results['water_methane_octane']['calculations'][1]
        assert_close(sum(calc['betas']), 1.0, rtol=1e-6, msg="betas sum high P")

    def test_vll_gas_phase_high_P(self):
        results = load_results()
        calc = results['water_methane_octane']['calculations'][1]
        comps = calc['compositions']

        gas_idx = find_phase_by_dominant_component(comps, 1)
        assert_close(comps[gas_idx][1], 0.9952286230641441, rtol=5e-3,
                     msg="gas methane high P")

    def test_vll_water_phase_high_P(self):
        results = load_results()
        calc = results['water_methane_octane']['calculations'][1]
        comps = calc['compositions']

        water_idx = find_phase_by_dominant_component(comps, 0)
        assert comps[water_idx][0] > 0.999, (
            f"Water phase >0.999, got {comps[water_idx][0]}"
        )

    def test_vll_organic_phase_high_P(self):
        results = load_results()
        calc = results['water_methane_octane']['calculations'][1]
        comps = calc['compositions']

        organic_idx = find_phase_by_dominant_component(comps, 2)
        assert_close(comps[organic_idx][2], 0.6740278982814496, rtol=1e-2,
                     msg="organic octane high P")

    # --- Calculation 2: T=500K, P=101325Pa (single phase) ---
    def test_single_phase_500K(self):
        results = load_results()
        calc = results['water_methane_octane']['calculations'][2]
        assert calc['phase_count'] == 1


# ============================================================
# System: natural_gas (9-component VLL)
# ============================================================
class TestNaturalGas:
    """9-component natural gas mixture VLL flash at T=300K, P=3MPa.
    Components: 0=CH4, 1=C2H6, 2=C3H8, 3=nC4, 4=nC5,
                5=H2O, 6=N2, 7=CO2, 8=H2S.
    """

    def test_results_exist(self):
        results = load_results()
        assert 'natural_gas' in results

    def test_phase_count(self):
        results = load_results()
        calc = results['natural_gas']['calculations'][0]
        assert calc['phase_count'] == 3

    def test_betas_sum(self):
        results = load_results()
        calc = results['natural_gas']['calculations'][0]
        assert_close(sum(calc['betas']), 1.0, rtol=1e-6, msg="betas sum")

    def test_gas_beta(self):
        results = load_results()
        calc = results['natural_gas']['calculations'][0]
        comps = calc['compositions']
        betas = calc['betas']

        # Gas: methane-dominant (component 0)
        gas_idx = find_phase_by_dominant_component(comps, 0)
        assert_close(betas[gas_idx], 0.9254860647854957, rtol=5e-3,
                     msg="gas beta")

    def test_water_phase_present(self):
        results = load_results()
        calc = results['natural_gas']['calculations'][0]
        comps = calc['compositions']

        # Water: H2O-dominant (component 5)
        water_idx = find_phase_by_dominant_component(comps, 5)
        assert comps[water_idx][5] > 0.95, (
            f"Water phase should be >0.95 water, got {comps[water_idx][5]}"
        )

    def test_compositions_valid(self):
        results = load_results()
        calc = results['natural_gas']['calculations'][0]
        for i, comp in enumerate(calc['compositions']):
            assert len(comp) == 9, f"Phase {i}: expected 9 components"
            assert_close(sum(comp), 1.0, rtol=1e-6,
                         msg=f"Phase {i} mole fractions sum")
            for j, z in enumerate(comp):
                assert z >= -1e-12, (
                    f"Phase {i} component {j}: negative mole fraction {z}"
                )

    def test_organic_liquid_present(self):
        results = load_results()
        calc = results['natural_gas']['calculations'][0]
        comps = calc['compositions']
        betas = calc['betas']

        # Organic liquid: not gas, not water
        gas_idx = find_phase_by_dominant_component(comps, 0)
        water_idx = find_phase_by_dominant_component(comps, 5)
        remaining = [i for i in range(3) if i != gas_idx and i != water_idx]
        assert len(remaining) == 1, "Should have exactly one organic phase"
        org_idx = remaining[0]

        # Organic liquid beta should be small (bulk of mixture is gas)
        assert betas[org_idx] < 0.1, (
            f"Organic beta should be small, got {betas[org_idx]}"
        )
        # Organic should contain heavier hydrocarbons
        assert comps[org_idx][4] > 0.1, (
            f"Organic should have significant nC5, got {comps[org_idx][4]}"
        )
