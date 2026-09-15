"""Tests for TEMA E shell-and-tube heat exchanger P-NTU solver.

"""
import sys
import math
import pytest

sys.path.insert(0, "/app")

# ============================================================
# Helper
# ============================================================

def assert_close(val, ref, rtol=1e-7):
    """Assert that val is close to ref within relative tolerance."""
    if ref == 0:
        assert abs(val) < 1e-12, f"Expected ~0, got {val}"
    else:
        rel = abs((val - ref) / ref)
        assert rel < rtol, f"val={val}, ref={ref}, rel_err={rel} > {rtol}"


# ============================================================
# temperature_effectiveness_TEMA_E tests
# ============================================================

class TestTemperatureEffectivenessTE:
    """Test the forward temperature effectiveness for TEMA E shells."""

    def _get_fn(self):
        from hx_solver import temperature_effectiveness_TEMA_E
        return temperature_effectiveness_TEMA_E

    # --- 1 tube pass (counterflow) ---
    def test_1pass_basic(self):
        fn = self._get_fn()
        P1 = fn(R1=1/3., NTU1=1., Ntp=1)
        assert_close(P1, 0.5870500654031314)

    def test_1pass_R1_eq_1(self):
        fn = self._get_fn()
        P1 = fn(R1=1., NTU1=7., Ntp=1)
        assert_close(P1, 0.875)

    def test_1pass_high_NTU(self):
        fn = self._get_fn()
        P1 = fn(R1=0.5, NTU1=10., Ntp=1)
        # For counterflow, ε = (1-exp(-NTU*(1-R)))/(1-R*exp(-NTU*(1-R)))
        # With large NTU and R<1, approaches 1.0
        expected = (1 - math.exp(-10 * 0.5)) / (1 - 0.5 * math.exp(-10 * 0.5))
        assert_close(P1, expected)

    # --- 2 tube passes, optimal ---
    def test_2pass_optimal_basic(self):
        fn = self._get_fn()
        P1 = fn(R1=1/3., NTU1=1., Ntp=2, optimal=True)
        assert_close(P1, 0.5689613217664634)

    def test_2pass_optimal_R1_eq_1(self):
        fn = self._get_fn()
        P1 = fn(R1=1., NTU1=7., Ntp=2, optimal=True)
        assert_close(P1, 0.5857620762776082)

    def test_2pass_optimal_high_NTU(self):
        fn = self._get_fn()
        P1 = fn(R1=0.5, NTU1=20., Ntp=2, optimal=True)
        # Should be close to but less than the counterflow limit
        assert 0 < P1 < 1.0

    # --- 2 tube passes, non-optimal ---
    def test_2pass_nonoptimal_basic(self):
        fn = self._get_fn()
        P1 = fn(R1=1/3., NTU1=1., Ntp=2, optimal=False)
        assert_close(P1, 0.5699085193651295)

    def test_2pass_nonoptimal_R1_eq_2(self):
        fn = self._get_fn()
        P1 = fn(R1=2., NTU1=1., Ntp=2, optimal=False)
        assert_close(P1, 0.3580830895954234)

    # --- 3 tube passes, optimal ---
    def test_3pass_optimal_basic(self):
        fn = self._get_fn()
        P1 = fn(R1=1/3., NTU1=1., Ntp=3, optimal=True)
        assert_close(P1, 0.5708624888990603)

    def test_3pass_optimal_R1_eq_1(self):
        fn = self._get_fn()
        P1 = fn(R1=1., NTU1=7., Ntp=3, optimal=True)
        assert_close(P1, 0.6366132064792461)

    # --- 3 tube passes, non-optimal ---
    def test_3pass_nonoptimal(self):
        fn = self._get_fn()
        P1 = fn(R1=3., NTU1=1., Ntp=3, optimal=False)
        assert_close(P1, 0.276815590660033)

    # --- 4 tube passes (even-N general formula) ---
    def test_4pass_basic(self):
        fn = self._get_fn()
        P1 = fn(R1=1/3., NTU1=1., Ntp=4)
        assert_close(P1, 0.56888933865756)

    def test_4pass_R1_eq_1(self):
        fn = self._get_fn()
        P1 = fn(R1=1., NTU1=7., Ntp=4)
        assert_close(P1, 0.5571628802075902)

    # --- 6 tube passes ---
    def test_6pass(self):
        fn = self._get_fn()
        # Use the general even-N formula
        P1 = fn(R1=0.5, NTU1=2., Ntp=6)
        assert 0 < P1 < 1.0
        # Verify it's close to 4-pass (both use even-N formula)
        P1_4 = fn(R1=0.5, NTU1=2., Ntp=4)
        # 6-pass should give slightly different result than 4-pass
        assert P1 != P1_4

    # --- 10 tube passes (used in test_hx.py) ---
    def test_10pass(self):
        fn = self._get_fn()
        # From the P_NTU_method test: E with Ntp=10, UA=300,
        # m1=5.2, m2=1.45, Cp1=1860, Cp2=1900
        # C1=9672, C2=2755, R1=3.5107078039927, NTU1=300/9672=0.031017369727
        R1 = 9672.0 / 2755.0
        NTU1 = 300.0 / 9672.0
        P1 = fn(R1=R1, NTU1=NTU1, Ntp=10)
        # Expected Q=32212.185563086336, so P1 = Q/(C1*|T2i-T1i|) = 32212.185563/(9672*115)
        expected_P1 = 32212.185563086336 / (9672.0 * 115.0)
        assert_close(P1, expected_P1, rtol=1e-6)

    # --- Error on odd Ntp > 3 ---
    def test_odd_ntp_error(self):
        fn = self._get_fn()
        with pytest.raises(ValueError):
            fn(R1=0.5, NTU1=1., Ntp=5)


# ============================================================
# NTU_from_P_E tests
# ============================================================

class TestNTUFromPE:
    """Test the inverse NTU computation for TEMA E shells."""

    def _get_fns(self):
        from hx_solver import temperature_effectiveness_TEMA_E, NTU_from_P_E
        return temperature_effectiveness_TEMA_E, NTU_from_P_E

    def test_1pass_roundtrip(self):
        fwd, inv = self._get_fns()
        for R1 in [0.2, 0.5, 1.0, 1.5, 3.0]:
            for NTU1 in [0.5, 1.0, 3.0, 7.0]:
                P1 = fwd(R1=R1, NTU1=NTU1, Ntp=1)
                NTU1_calc = inv(P1=P1, R1=R1, Ntp=1)
                assert_close(NTU1_calc, NTU1, rtol=1e-6)

    def test_2pass_optimal_analytical(self):
        fwd, inv = self._get_fns()
        P1 = fwd(R1=1/3., NTU1=1., Ntp=2, optimal=True)
        NTU1_calc = inv(P1=P1, R1=1/3., Ntp=2, optimal=True)
        assert_close(NTU1_calc, 1.0, rtol=1e-6)

    def test_2pass_optimal_known(self):
        _, inv = self._get_fns()
        NTU1 = inv(P1=0.58, R1=1/3., Ntp=2, optimal=True)
        assert_close(NTU1, 1.0381979240816719, rtol=1e-6)

    def test_2pass_optimal_roundtrip(self):
        fwd, inv = self._get_fns()
        for R1 in [0.1, 0.5, 1.0, 2.0, 5.0]:
            NTU1 = 3.0
            P1 = fwd(R1=R1, NTU1=NTU1, Ntp=2, optimal=True)
            NTU1_calc = inv(P1=P1, R1=R1, Ntp=2, optimal=True)
            assert_close(NTU1_calc, NTU1, rtol=1e-5)

    def test_2pass_nonoptimal_roundtrip(self):
        fwd, inv = self._get_fns()
        for R1 in [0.3, 0.5, 1.0, 2.0]:
            NTU1 = 2.0
            P1 = fwd(R1=R1, NTU1=NTU1, Ntp=2, optimal=False)
            NTU1_calc = inv(P1=P1, R1=R1, Ntp=2, optimal=False)
            assert_close(NTU1_calc, NTU1, rtol=1e-4)

    def test_2pass_optimal_high_R1(self):
        fwd, inv = self._get_fns()
        R1 = 1.1
        NTU1 = 10.0
        P1 = fwd(R1=R1, NTU1=NTU1, Ntp=2, optimal=True)
        assert_close(P1, 0.5576299522073297, rtol=1e-6)
        NTU1_calc = inv(P1=P1, R1=R1, Ntp=2, optimal=True)
        assert_close(NTU1_calc, NTU1, rtol=1e-4)

    def test_3pass_optimal_roundtrip(self):
        fwd, inv = self._get_fns()
        for R1 in [0.3, 0.5, 1.0]:
            NTU1 = 2.0
            P1 = fwd(R1=R1, NTU1=NTU1, Ntp=3, optimal=True)
            NTU1_calc = inv(P1=P1, R1=R1, Ntp=3, optimal=True)
            assert_close(NTU1_calc, NTU1, rtol=1e-3)

    def test_3pass_nonoptimal_roundtrip(self):
        fwd, inv = self._get_fns()
        for R1 in [0.5, 2.0, 3.0]:
            NTU1 = 1.5
            P1 = fwd(R1=R1, NTU1=NTU1, Ntp=3, optimal=False)
            NTU1_calc = inv(P1=P1, R1=R1, Ntp=3, optimal=False)
            assert_close(NTU1_calc, NTU1, rtol=1e-3)

    def test_4pass_roundtrip(self):
        fwd, inv = self._get_fns()
        # Use small NTU1 values to stay on the ascending (monotonic) side
        for R1 in [0.3, 0.5, 1.5, 3.0]:
            NTU1 = 0.5
            P1 = fwd(R1=R1, NTU1=NTU1, Ntp=4)
            NTU1_calc = inv(P1=P1, R1=R1, Ntp=4)
            assert_close(NTU1_calc, NTU1, rtol=1e-3)

    def test_10pass_roundtrip(self):
        fwd, inv = self._get_fns()
        R1 = 9672.0 / 2755.0
        NTU1 = 300.0 / 9672.0
        P1 = fwd(R1=R1, NTU1=NTU1, Ntp=10)
        NTU1_calc = inv(P1=P1, R1=R1, Ntp=10)
        assert_close(NTU1_calc, NTU1, rtol=1e-3)


# ============================================================
# P_NTU_method tests
# ============================================================

class TestPNTUMethod:
    """Test the full P-NTU method wrapper."""

    def _get_fn(self):
        from hx_solver import P_NTU_method
        return P_NTU_method

    # --- Forward problem: known UA + T1i + T2i ---
    def test_forward_E_4pass(self):
        fn = self._get_fn()
        ans = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 UA=3041.75, T1i=130, T2i=15, Ntp=4)
        assert_close(ans["Q"], 192514.714242, rtol=1e-4)
        assert_close(ans["T1o"], 110.095666434, rtol=1e-4)
        assert_close(ans["T2o"], 84.878299180, rtol=1e-4)
        assert_close(ans["P1"], 0.173081161436, rtol=1e-4)
        assert_close(ans["R1"], 3.5107078039, rtol=1e-6)
        assert_close(ans["C1"], 9672.0)
        assert_close(ans["C2"], 2755.0)
        assert_close(ans["NTU1"], 0.314490281224, rtol=1e-4)

    def test_forward_E_10pass(self):
        fn = self._get_fn()
        ans = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 UA=300, T1i=130, T2i=15, Ntp=10)
        assert_close(ans["Q"], 32212.185563086336, rtol=1e-4)

    # --- Forward problem: known UA + T1o + T2o ---
    def test_forward_outlet_temps(self):
        fn = self._get_fn()
        # First compute with inlets to get outlet values
        ref = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 UA=3041.75, T1i=130, T2i=15, Ntp=4)
        # Now solve with outlets
        ans = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 UA=3041.75, T1o=ref["T1o"], T2o=ref["T2o"], Ntp=4)
        assert_close(ans["Q"], ref["Q"], rtol=1e-3)
        assert_close(ans["T1i"], 130.0, rtol=1e-3)
        assert_close(ans["T2i"], 15.0, rtol=1e-3)

    # --- Forward problem: known UA + T1o + T2i ---
    def test_forward_mixed_temps(self):
        fn = self._get_fn()
        ref = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 UA=3041.75, T1i=130, T2i=15, Ntp=4)
        ans = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 UA=3041.75, T1o=ref["T1o"], T2i=15, Ntp=4)
        assert_close(ans["Q"], ref["Q"], rtol=1e-3)
        assert_close(ans["T1i"], 130.0, rtol=1e-3)

    # --- Inverse problem: three temperatures, no UA ---
    def test_inverse_three_temps_1(self):
        """Given T1i, T2i, T2o → compute UA."""
        fn = self._get_fn()
        ans = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 T1i=130, T2i=15, T2o=84.87829918042112, Ntp=4)
        assert_close(ans["UA"], 3041.75, rtol=1e-3)
        assert_close(ans["T1o"], 110.095666434, rtol=1e-3)
        assert_close(ans["Q"], 192514.714242, rtol=1e-3)

    def test_inverse_three_temps_2(self):
        """Given T1i, T1o, T2i → compute UA."""
        fn = self._get_fn()
        ans = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 T1i=130, T1o=110.095666434, T2i=15, Ntp=4)
        assert_close(ans["UA"], 3041.75, rtol=1e-3)
        assert_close(ans["T2o"], 84.878299180, rtol=1e-3)

    def test_inverse_three_temps_3(self):
        """Given T1o, T2i, T2o → compute UA."""
        fn = self._get_fn()
        ans = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 T1o=110.095666434, T2i=15, T2o=84.87829918042112, Ntp=4)
        assert_close(ans["UA"], 3041.75, rtol=1e-3)
        assert_close(ans["T1i"], 130.0, rtol=1e-3)

    # --- Basic relationships ---
    def test_P2_equals_P1_times_R1(self):
        fn = self._get_fn()
        ans = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 UA=300, T1i=130, T2i=15, Ntp=10)
        assert_close(ans["P2"], ans["P1"] * ans["R1"], rtol=1e-6)

    def test_NTU2_equals_NTU1_times_R1(self):
        fn = self._get_fn()
        ans = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 UA=300, T1i=130, T2i=15, Ntp=10)
        assert_close(ans["NTU2"], ans["NTU1"] * ans["R1"], rtol=1e-6)

    def test_R1_R2_reciprocal(self):
        fn = self._get_fn()
        ans = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 UA=300, T1i=130, T2i=15, Ntp=10)
        assert_close(ans["R1"] * ans["R2"], 1.0, rtol=1e-10)

    def test_energy_balance(self):
        """Q should equal C1*(T1i-T1o) and C2*(T2o-T2i)."""
        fn = self._get_fn()
        ans = fn(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                 UA=3041.75, T1i=130, T2i=15, Ntp=4)
        Q_side1 = ans["C1"] * (ans["T1i"] - ans["T1o"])
        Q_side2 = ans["C2"] * (ans["T2o"] - ans["T2i"])
        assert_close(ans["Q"], Q_side1, rtol=1e-6)
        assert_close(ans["Q"], Q_side2, rtol=1e-6)


# ============================================================
# F_LMTD_Fakheri tests
# ============================================================

class TestFLMTDFakheri:
    """Test the LMTD correction factor."""

    def _get_fn(self):
        from f_lmtd import F_LMTD_Fakheri
        return F_LMTD_Fakheri

    def test_basic(self):
        fn = self._get_fn()
        Ft = fn(Tci=15, Tco=85, Thi=130, Tho=110, shells=1)
        assert_close(Ft, 0.9438358829645933)

    def test_R_eq_1(self):
        """R=1 case requires special formula to avoid division by zero."""
        fn = self._get_fn()
        Ft = fn(Tci=15, Tco=35, Thi=130, Tho=110, shells=1)
        assert_close(Ft, 0.9925689447100824)

    def test_symmetric(self):
        """Swapping hot and cold sides should give the same result."""
        fn = self._get_fn()
        Ft1 = fn(Thi=130, Tho=110, Tci=15, Tco=85, shells=1)
        Ft2 = fn(Thi=15, Tho=85, Tci=130, Tco=110, shells=1)
        assert_close(Ft1, Ft2, rtol=1e-10)

    def test_multi_shell(self):
        fn = self._get_fn()
        Ft_1 = fn(Tci=15, Tco=85, Thi=130, Tho=110, shells=1)
        Ft_3 = fn(Tci=15, Tco=85, Thi=130, Tho=110, shells=3)
        # More shells should give a higher correction factor
        assert Ft_3 > Ft_1

    def test_multi_shell_approaches_1(self):
        fn = self._get_fn()
        Ft = fn(Tci=15, Tco=85, Thi=130, Tho=110, shells=9)
        # With many shells, Ft should approach 1.0
        assert Ft > 0.99


# ============================================================
# Integration / cross-consistency tests
# ============================================================

class TestCrossConsistency:
    """Tests that verify consistency between different functions."""

    def test_pntu_energy_conservation_2pass(self):
        from hx_solver import P_NTU_method
        ans = P_NTU_method(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                           UA=500, T1i=150, T2i=20, Ntp=2, optimal=True)
        Q_1 = ans["C1"] * (ans["T1i"] - ans["T1o"])
        Q_2 = ans["C2"] * (ans["T2o"] - ans["T2i"])
        assert_close(Q_1, Q_2, rtol=1e-6)
        assert_close(ans["Q"], Q_1, rtol=1e-6)

    def test_pntu_forward_inverse_consistency(self):
        """Forward then inverse should recover UA."""
        from hx_solver import P_NTU_method
        fwd = P_NTU_method(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                           UA=500, T1i=150, T2i=20, Ntp=2, optimal=True)
        inv = P_NTU_method(m1=5.2, m2=1.45, Cp1=1860., Cp2=1900.,
                           T1i=150, T2i=20, T2o=fwd["T2o"], Ntp=2, optimal=True)
        assert_close(inv["UA"], 500, rtol=1e-3)

    def test_effectiveness_monotonic_in_NTU(self):
        """P1 should increase with NTU1 for fixed R1."""
        from hx_solver import temperature_effectiveness_TEMA_E
        for Ntp in [1, 2, 4]:
            prev = 0
            for ntu in [0.1, 0.5, 1.0, 2.0, 5.0]:
                P1 = temperature_effectiveness_TEMA_E(R1=0.5, NTU1=ntu, Ntp=Ntp)
                assert P1 > prev, f"Not monotonic at Ntp={Ntp}, NTU={ntu}"
                prev = P1
