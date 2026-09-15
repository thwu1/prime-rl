"""
Tests for the geochemical pipeline.
Verifies charge balance audit, speciation, dual-system CCPP, blend analysis,
and evaporative concentration against PHREEQC reference values and
independent calculations.
"""

import json
import os
import math
import pytest

RESULTS_PATH = '/app/results.json'


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found: {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


# -- Schema validation --------------------------------------------------------

class TestSchema:

    def test_top_level_keys(self, results):
        required = {'charge_balance', 'speciation', 'ccpp',
                     'blend_analysis', 'evaporation'}
        assert required.issubset(set(results.keys())), \
            f"Missing top-level keys: {required - set(results.keys())}"

    def test_charge_balance_water_ids(self, results):
        expected = {'groundwater_carbonate', 'surface_water',
                    'seawater_nordstrom', 'brackish_well'}
        actual = set(results['charge_balance'].keys())
        assert expected == actual, f"Expected water IDs {expected}, got {actual}"

    def test_charge_balance_fields(self, results):
        for wid, cb in results['charge_balance'].items():
            assert 'cbe_pct' in cb, f"{wid} missing cbe_pct"
            assert 'adjusted' in cb, f"{wid} missing adjusted"
            assert isinstance(cb['cbe_pct'], (int, float)), \
                f"{wid} cbe_pct not numeric"
            assert isinstance(cb['adjusted'], bool), \
                f"{wid} adjusted not boolean"

    def test_speciation_water_ids(self, results):
        expected = {'groundwater_carbonate', 'surface_water',
                    'seawater_nordstrom', 'brackish_well'}
        actual = set(results['speciation'].keys())
        assert expected == actual, f"Expected water IDs {expected}, got {actual}"

    def test_speciation_fields(self, results):
        required = {'pH', 'pe', 'ionic_strength', 'SI_Calcite',
                    'SI_Dolomite', 'SI_Gypsum', 'SI_Fluorite', 'SI_SiO2_a'}
        for wid, spec in results['speciation'].items():
            missing = required - set(spec.keys())
            assert not missing, f"Water '{wid}' missing fields: {missing}"

    def test_speciation_numeric(self, results):
        for wid, spec in results['speciation'].items():
            for key in ['pH', 'pe', 'ionic_strength', 'SI_Calcite']:
                val = spec[key]
                assert val is not None, f"{wid}.{key} is None"
                assert isinstance(val, (int, float)), \
                    f"{wid}.{key} is not numeric: {val}"

    def test_ccpp_fields(self, results):
        ccpp = results['ccpp']
        for key in ['water_id', 'CCPP_closed_mmol_kgw', 'CCPP_open_mmol_kgw',
                     'final_pH_closed', 'final_pH_open']:
            assert key in ccpp, f"CCPP missing field: {key}"

    def test_blend_fields(self, results):
        blend = results['blend_analysis']
        for key in ['ratio_a', 'SI_Calcite', 'pH', 'ionic_strength',
                     'optimal_ratio_min_abs_SI_Calcite']:
            assert key in blend, f"Blend analysis missing field: {key}"
        assert len(blend['ratio_a']) == 11
        assert len(blend['SI_Calcite']) == 11
        assert len(blend['pH']) == 11
        assert len(blend['ionic_strength']) == 11

    def test_evaporation_fields(self, results):
        ev = results['evaporation']
        for key in ['concentration_factors', 'pH', 'ionic_strength',
                     'minerals_precipitated', 'first_precip_factor']:
            assert key in ev, f"Evaporation missing field: {key}"
        assert len(ev['concentration_factors']) == 6
        assert len(ev['pH']) == 6
        assert len(ev['ionic_strength']) == 6

    def test_evaporation_mineral_fields(self, results):
        ev = results['evaporation']
        for phase in ['Calcite', 'Gypsum', 'Halite']:
            assert phase in ev['minerals_precipitated'], \
                f"minerals_precipitated missing {phase}"
            assert len(ev['minerals_precipitated'][phase]) == 6, \
                f"minerals_precipitated[{phase}] should have 6 entries"
            assert phase in ev['first_precip_factor'], \
                f"first_precip_factor missing {phase}"


# -- Charge balance checks ----------------------------------------------------

class TestChargeBalance:

    def test_groundwater_not_adjusted(self, results):
        cb = results['charge_balance']['groundwater_carbonate']
        assert not cb['adjusted'], "Groundwater should not be adjusted"
        assert abs(cb['cbe_pct']) < 5.0, \
            f"Groundwater CBE {cb['cbe_pct']}% should be < 5%"

    def test_surface_water_not_adjusted(self, results):
        cb = results['charge_balance']['surface_water']
        assert not cb['adjusted'], "Surface water should not be adjusted"
        assert abs(cb['cbe_pct']) < 5.0, \
            f"Surface water CBE {cb['cbe_pct']}% should be < 5%"

    def test_seawater_not_adjusted(self, results):
        cb = results['charge_balance']['seawater_nordstrom']
        assert not cb['adjusted'], "Seawater should not be adjusted"
        assert abs(cb['cbe_pct']) < 5.0, \
            f"Seawater CBE {cb['cbe_pct']}% should be < 5%"

    def test_brackish_adjusted(self, results):
        cb = results['charge_balance']['brackish_well']
        assert cb['adjusted'], "Brackish well should be adjusted (CBE > 5%)"
        assert cb['cbe_pct'] > 5.0, \
            f"Brackish CBE {cb['cbe_pct']}% should be > 5%"

    def test_cbe_values_reasonable(self, results):
        """All CBE values should be in a physically plausible range."""
        for wid, cb in results['charge_balance'].items():
            assert -30 < cb['cbe_pct'] < 30, \
                f"{wid} CBE {cb['cbe_pct']}% outside reasonable range"


# -- Speciation golden values --------------------------------------------------

class TestSpeciationGoldenValues:

    def test_seawater_ph(self, results):
        """Seawater pH should be preserved from input (8.22)."""
        ph = results['speciation']['seawater_nordstrom']['pH']
        assert abs(ph - 8.22) < 0.05, f"Seawater pH = {ph}, expected ~8.22"

    def test_seawater_si_calcite(self, results):
        """Known from PHREEQC ex1: SI_Calcite approx 0.76."""
        si = results['speciation']['seawater_nordstrom']['SI_Calcite']
        assert 0.55 < si < 1.0, f"Seawater SI_Calcite = {si}, expected ~0.76"

    def test_seawater_ionic_strength(self, results):
        """Known from PHREEQC ex1: mu approx 0.674."""
        mu = results['speciation']['seawater_nordstrom']['ionic_strength']
        assert 0.55 < mu < 0.80, \
            f"Seawater ionic_strength = {mu}, expected ~0.674"

    def test_seawater_si_gypsum_negative(self, results):
        """Seawater is undersaturated w.r.t. gypsum."""
        si = results['speciation']['seawater_nordstrom']['SI_Gypsum']
        assert si < 0, f"Seawater SI_Gypsum = {si}, expected < 0"

    def test_seawater_fluorite_null(self, results):
        """Seawater analysis has no F, so SI_Fluorite should be null."""
        val = results['speciation']['seawater_nordstrom']['SI_Fluorite']
        assert val is None, f"Seawater SI_Fluorite should be null, got {val}"

    def test_surface_water_undersaturated(self, results):
        """Dilute mountain stream should be undersaturated w.r.t. calcite."""
        si = results['speciation']['surface_water']['SI_Calcite']
        assert si < -0.5, f"Surface water SI_Calcite = {si}, expected < -0.5"

    def test_groundwater_moderate_si(self, results):
        """Carbonate groundwater SI_Calcite in reasonable range."""
        si = results['speciation']['groundwater_carbonate']['SI_Calcite']
        assert -3.0 < si < 2.0, \
            f"Groundwater SI_Calcite = {si}, expected between -3 and 2"

    def test_brackish_has_fluorite(self, results):
        """Brackish well has F, so SI_Fluorite should be numeric."""
        val = results['speciation']['brackish_well']['SI_Fluorite']
        assert val is not None and isinstance(val, (int, float)), \
            f"Brackish SI_Fluorite should be numeric, got {val}"

    def test_brackish_has_sio2a(self, results):
        """Brackish well has Si, so SI_SiO2_a should be numeric."""
        val = results['speciation']['brackish_well']['SI_SiO2_a']
        assert val is not None and isinstance(val, (int, float)), \
            f"Brackish SI_SiO2_a should be numeric, got {val}"

    def test_ionic_strength_ordering(self, results):
        """Seawater >> brackish >> groundwater >> surface water ionic strength."""
        spec = results['speciation']
        mu_sea = spec['seawater_nordstrom']['ionic_strength']
        mu_bw = spec['brackish_well']['ionic_strength']
        mu_gw = spec['groundwater_carbonate']['ionic_strength']
        mu_sw = spec['surface_water']['ionic_strength']
        assert mu_sea > mu_bw > mu_gw > mu_sw, \
            f"Ionic strength order wrong: sea={mu_sea}, bw={mu_bw}, gw={mu_gw}, sw={mu_sw}"

    def test_pe_reasonable(self, results):
        """pe values should be within physically meaningful range."""
        for wid, spec in results['speciation'].items():
            pe = spec['pe']
            assert -15 < pe < 20, f"{wid} pe = {pe} outside reasonable range"


# -- CCPP checks ---------------------------------------------------------------

class TestCCPP:

    def test_ccpp_water_id(self, results):
        assert results['ccpp']['water_id'] == 'seawater_nordstrom'

    def test_ccpp_closed_positive(self, results):
        """Supersaturated seawater should have positive CCPP (calcite precipitates)."""
        ccpp = results['ccpp']['CCPP_closed_mmol_kgw']
        assert ccpp > 0.05, f"Closed CCPP = {ccpp}, expected positive"

    def test_ccpp_closed_magnitude(self, results):
        """CCPP closed approx 0.1-0.5 mmol/kgw for seawater."""
        ccpp = results['ccpp']['CCPP_closed_mmol_kgw']
        assert 0.05 < ccpp < 0.60, \
            f"Closed CCPP = {ccpp}, expected ~0.15-0.35 mmol/kgw"

    def test_ccpp_open_positive(self, results):
        """Open system CCPP should also be positive for supersaturated seawater."""
        ccpp = results['ccpp']['CCPP_open_mmol_kgw']
        assert ccpp > 0.0, f"Open CCPP = {ccpp}, expected positive"

    def test_ccpp_open_differs_from_closed(self, results):
        """Open and closed CCPP should differ (CO2 exchange changes the result)."""
        closed = results['ccpp']['CCPP_closed_mmol_kgw']
        opened = results['ccpp']['CCPP_open_mmol_kgw']
        assert abs(closed - opened) > 0.01, \
            f"Open ({opened}) and closed ({closed}) CCPP should differ"

    def test_final_ph_closed_reasonable(self, results):
        ph = results['ccpp']['final_pH_closed']
        assert 7.0 < ph < 9.0, f"Final pH closed = {ph}, outside reasonable range"

    def test_final_ph_open_reasonable(self, results):
        ph = results['ccpp']['final_pH_open']
        assert 7.0 < ph < 9.5, f"Final pH open = {ph}, outside reasonable range"

    def test_final_ph_open_differs_from_closed(self, results):
        """Open system pH should differ from closed system pH."""
        ph_c = results['ccpp']['final_pH_closed']
        ph_o = results['ccpp']['final_pH_open']
        assert abs(ph_c - ph_o) > 0.01, \
            f"Open pH ({ph_o}) and closed pH ({ph_c}) should differ"


# -- Blend analysis checks -----------------------------------------------------

class TestBlendAnalysis:

    def test_ratios_correct(self, results):
        ratios = results['blend_analysis']['ratio_a']
        expected = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        for r, e in zip(ratios, expected):
            assert abs(r - e) < 1e-9, f"Ratio mismatch: {r} vs {e}"

    def test_endpoint_ratio_0(self, results):
        """Blend at ratio_a=0 should approximate pure surface water."""
        blend_si = results['blend_analysis']['SI_Calcite'][0]
        sw_si = results['speciation']['surface_water']['SI_Calcite']
        assert abs(blend_si - sw_si) < 0.5, \
            f"Blend(0.0) SI={blend_si}, surface water SI={sw_si}"

    def test_endpoint_ratio_1(self, results):
        """Blend at ratio_a=1 should approximate pure groundwater."""
        blend_si = results['blend_analysis']['SI_Calcite'][-1]
        gw_si = results['speciation']['groundwater_carbonate']['SI_Calcite']
        assert abs(blend_si - gw_si) < 0.5, \
            f"Blend(1.0) SI={blend_si}, groundwater SI={gw_si}"

    def test_si_varies(self, results):
        """SI_Calcite should change across blend ratios."""
        si = results['blend_analysis']['SI_Calcite']
        assert si[0] != si[-1], "SI should differ between endpoints"

    def test_si_monotonic_trend(self, results):
        """SI should generally increase from surface water to groundwater."""
        si = results['blend_analysis']['SI_Calcite']
        assert si[-1] > si[0], \
            f"SI at ratio=1 ({si[-1]}) should exceed SI at ratio=0 ({si[0]})"

    def test_optimal_ratio_in_range(self, results):
        opt = results['blend_analysis']['optimal_ratio_min_abs_SI_Calcite']
        assert 0.0 <= opt <= 1.0, f"Optimal ratio {opt} out of [0, 1] range"

    def test_optimal_ratio_minimal(self, results):
        """Optimal ratio should actually minimize |SI_Calcite|."""
        blend = results['blend_analysis']
        opt = blend['optimal_ratio_min_abs_SI_Calcite']
        idx = blend['ratio_a'].index(opt)
        abs_si_opt = abs(blend['SI_Calcite'][idx])
        for i, si in enumerate(blend['SI_Calcite']):
            assert abs(si) >= abs_si_opt - 1e-6, \
                f"|SI| at ratio {blend['ratio_a'][i]} ({abs(si)}) < optimum ({abs_si_opt})"

    def test_ph_varies(self, results):
        ph = results['blend_analysis']['pH']
        assert max(ph) - min(ph) > 0.05, "pH should vary across blend ratios"

    def test_ionic_strength_varies(self, results):
        mu = results['blend_analysis']['ionic_strength']
        assert max(mu) - min(mu) > 0.0001, \
            "Ionic strength should vary across blend ratios"


# -- Evaporation checks -------------------------------------------------------

class TestEvaporation:

    def test_concentration_factors(self, results):
        ev = results['evaporation']
        assert ev['concentration_factors'] == [1, 2, 5, 10, 20, 50]

    def test_ph_list_length(self, results):
        assert len(results['evaporation']['pH']) == 6

    def test_ionic_strength_increases(self, results):
        """Ionic strength must increase with concentration factor."""
        mu = results['evaporation']['ionic_strength']
        for i in range(len(mu) - 1):
            assert mu[i + 1] > mu[i], \
                f"Ionic strength should increase: CF={results['evaporation']['concentration_factors'][i+1]} " \
                f"mu={mu[i+1]} <= CF={results['evaporation']['concentration_factors'][i]} mu={mu[i]}"

    def test_calcite_precipitates_first(self, results):
        """Seawater is already supersaturated w.r.t. calcite - should precipitate at CF=1."""
        fp = results['evaporation']['first_precip_factor']['Calcite']
        assert fp is not None, "Calcite should precipitate"
        assert fp == 1, f"Calcite first_precip_factor = {fp}, expected 1"

    def test_gypsum_precipitates_at_intermediate_cf(self, results):
        """Gypsum should start precipitating at an intermediate concentration factor."""
        fp = results['evaporation']['first_precip_factor']['Gypsum']
        assert fp is not None, "Gypsum should precipitate within CF 1-50"
        assert 1 <= fp <= 10, \
            f"Gypsum first_precip_factor = {fp}, expected between 1 and 10"

    def test_halite_precipitates_late_or_not(self, results):
        """Halite should precipitate at high CF or not at all within range."""
        fp = results['evaporation']['first_precip_factor']['Halite']
        if fp is not None:
            assert fp >= 5, \
                f"Halite first_precip_factor = {fp}, expected >= 5"

    def test_calcite_before_gypsum(self, results):
        """Calcite should precipitate before or at same CF as gypsum."""
        fp_calc = results['evaporation']['first_precip_factor']['Calcite']
        fp_gyps = results['evaporation']['first_precip_factor']['Gypsum']
        if fp_calc is not None and fp_gyps is not None:
            assert fp_calc <= fp_gyps, \
                f"Calcite ({fp_calc}) should precipitate before gypsum ({fp_gyps})"

    def test_mineral_amounts_nonnegative(self, results):
        """All mineral precipitation amounts should be >= 0."""
        for phase, amounts in results['evaporation']['minerals_precipitated'].items():
            for i, amt in enumerate(amounts):
                assert amt >= -1e-10, \
                    f"{phase} at CF={results['evaporation']['concentration_factors'][i]} " \
                    f"has negative amount: {amt}"

    def test_mineral_amounts_nondecreasing(self, results):
        """Cumulative precipitation should be non-decreasing."""
        for phase, amounts in results['evaporation']['minerals_precipitated'].items():
            for i in range(len(amounts) - 1):
                assert amounts[i + 1] >= amounts[i] - 1e-10, \
                    f"{phase} cumulative precipitation decreased from " \
                    f"CF={results['evaporation']['concentration_factors'][i]} " \
                    f"to CF={results['evaporation']['concentration_factors'][i+1]}"

    def test_calcite_amount_positive(self, results):
        """Calcite should have positive precipitation amount at CF=1."""
        calc_amt = results['evaporation']['minerals_precipitated']['Calcite'][0]
        assert calc_amt > 1e-6, \
            f"Calcite precipitation at CF=1 should be positive, got {calc_amt}"

    def test_first_precip_consistent_with_amounts(self, results):
        """first_precip_factor should match where minerals_precipitated first becomes positive."""
        ev = results['evaporation']
        for phase in ['Calcite', 'Gypsum', 'Halite']:
            fp = ev['first_precip_factor'][phase]
            amounts = ev['minerals_precipitated'][phase]
            cfs = ev['concentration_factors']

            if fp is None:
                # All amounts should be zero or near-zero
                for amt in amounts:
                    assert amt < 1e-8, \
                        f"{phase} first_precip is null but has positive amount {amt}"
            else:
                # Find first CF with positive amount
                first_positive_cf = None
                for j, amt in enumerate(amounts):
                    if amt > 1e-10:
                        first_positive_cf = cfs[j]
                        break
                assert first_positive_cf == fp, \
                    f"{phase} first_precip_factor={fp} but first positive " \
                    f"amount at CF={first_positive_cf}"


# -- Cross-verification with phreeqpython -------------------------------------

class TestCrossVerification:

    def _make_seawater(self, pp):
        return pp.add_solution({
            'units': 'ppm',
            'pH': 8.22,
            'pe': 8.451,
            'temp': 25.0,
            'density': 1.023,
            'Ca': 412.3,
            'Mg': 1291.8,
            'Na': 10768.0,
            'K': 399.1,
            'Cl': 19353.0,
            'Alkalinity': '141.682 as HCO3',
            'S(6)': 2712.0,
        })

    def test_independent_seawater_si(self, results):
        """Cross-check seawater SI_Calcite with independent calculation."""
        try:
            from phreeqpython import PhreeqPython
            pp = PhreeqPython()
            sol = self._make_seawater(pp)
            expected_si = sol.si('Calcite')
            actual_si = results['speciation']['seawater_nordstrom']['SI_Calcite']
            assert abs(actual_si - expected_si) < 0.1, \
                f"SI_Calcite mismatch: solver={actual_si}, independent={expected_si}"
        except ImportError:
            pytest.skip("phreeqpython not installed")

    def test_independent_seawater_ph(self, results):
        """Cross-check seawater pH with independent calculation."""
        try:
            from phreeqpython import PhreeqPython
            pp = PhreeqPython()
            sol = self._make_seawater(pp)
            expected_ph = sol.pH
            actual_ph = results['speciation']['seawater_nordstrom']['pH']
            assert abs(actual_ph - expected_ph) < 0.1, \
                f"pH mismatch: solver={actual_ph}, independent={expected_ph}"
        except ImportError:
            pytest.skip("phreeqpython not installed")

    def test_independent_seawater_ionic_strength(self, results):
        """Cross-check seawater ionic strength."""
        try:
            from phreeqpython import PhreeqPython
            pp = PhreeqPython()
            sol = self._make_seawater(pp)
            expected_mu = sol.I
            actual_mu = results['speciation']['seawater_nordstrom']['ionic_strength']
            assert abs(actual_mu - expected_mu) < 0.05, \
                f"Ionic strength mismatch: solver={actual_mu}, independent={expected_mu}"
        except ImportError:
            pytest.skip("phreeqpython not installed")

    def test_independent_ccpp_closed(self, results):
        """Cross-check closed CCPP with independent calculation."""
        try:
            from phreeqpython import PhreeqPython
            pp = PhreeqPython()
            sol = self._make_seawater(pp)
            copy = sol * 1.0
            initial_ca = copy.total('Ca', 'mol')
            copy.desaturate('Calcite')
            final_ca = copy.total('Ca', 'mol')
            expected_ccpp = (initial_ca - final_ca) * 1000
            actual_ccpp = results['ccpp']['CCPP_closed_mmol_kgw']
            assert abs(actual_ccpp - expected_ccpp) < 0.1, \
                f"Closed CCPP mismatch: solver={actual_ccpp}, independent={expected_ccpp}"
        except ImportError:
            pytest.skip("phreeqpython not installed")
        except (AttributeError, Exception) as e:
            actual_ccpp = results['ccpp']['CCPP_closed_mmol_kgw']
            assert 0.05 < actual_ccpp < 0.60, \
                f"CCPP = {actual_ccpp}, expected ~0.2 mmol/kgw (fallback check, error: {e})"

    def test_independent_groundwater_si(self, results):
        """Cross-check groundwater speciation."""
        try:
            from phreeqpython import PhreeqPython
            pp = PhreeqPython()
            sol = pp.add_solution({
                'units': 'ppm',
                'pH': 7.3,
                'temp': 15.0,
                'Ca': 80.0,
                'Mg': 32.0,
                'Na': 18.0,
                'K': 4.0,
                'Cl': 40.0,
                'Alkalinity': '260.0 as CaCO3',
                'S(6)': 30.0,
                'Si': 12.0,
            })
            expected_si = sol.si('Calcite')
            actual_si = results['speciation']['groundwater_carbonate']['SI_Calcite']
            assert abs(actual_si - expected_si) < 0.15, \
                f"Groundwater SI mismatch: solver={actual_si}, independent={expected_si}"
        except ImportError:
            pytest.skip("phreeqpython not installed")

    def test_independent_blend_midpoint(self, results):
        """Cross-check the 50/50 blend with independent calculation."""
        try:
            from phreeqpython import PhreeqPython
            pp = PhreeqPython()

            sol_a = pp.add_solution({
                'units': 'ppm', 'pH': 7.3, 'temp': 15.0,
                'Ca': 80.0, 'Mg': 32.0, 'Na': 18.0, 'K': 4.0,
                'Cl': 40.0, 'Alkalinity': '260.0 as CaCO3',
                'S(6)': 30.0, 'Si': 12.0,
            })
            sol_b = pp.add_solution({
                'units': 'ppm', 'pH': 6.8, 'temp': 10.0,
                'Ca': 15.0, 'Mg': 3.5, 'Na': 6.0, 'K': 1.2,
                'Cl': 12.0, 'Alkalinity': '35.0 as CaCO3',
                'S(6)': 12.0, 'Si': 4.0,
            })

            blend = sol_a * 0.5 + sol_b * 0.5
            expected_si = blend.si('Calcite')

            # ratio_a = 0.5 is index 5
            actual_si = results['blend_analysis']['SI_Calcite'][5]
            assert abs(actual_si - expected_si) < 0.2, \
                f"50/50 blend SI mismatch: solver={actual_si}, independent={expected_si}"
        except ImportError:
            pytest.skip("phreeqpython not installed")

    def test_independent_brackish_charge_adjusted(self, results):
        """Cross-check that brackish well with charge balance produces valid speciation."""
        try:
            from phreeqpython import PhreeqPython
            pp = PhreeqPython()
            sol = pp.add_solution({
                'units': 'ppm',
                'pH': 7.4,
                'temp': 22.0,
                'Ca': 250.0,
                'Mg': 90.0,
                'Na': 400.0,
                'K': 12.0,
                'Cl': '650.0 charge',
                'Alkalinity': '220.0 as CaCO3',
                'S(6)': 400.0,
                'F': 2.0,
                'Si': 15.0,
            })
            expected_si = sol.si('Calcite')
            actual_si = results['speciation']['brackish_well']['SI_Calcite']
            assert abs(actual_si - expected_si) < 0.2, \
                f"Brackish SI mismatch: solver={actual_si}, independent={expected_si}"
        except ImportError:
            pytest.skip("phreeqpython not installed")
