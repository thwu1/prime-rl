#!/usr/bin/env python3
"""
Tests for tidal harmonic prediction engine.
Verifies astronomical mean longitudes, equilibrium arguments,
nodal corrections, harmonic prediction, and minor constituent inference.
"""

import sys
import numpy as np
import pytest

sys.path.insert(0, '/app')
import tidal_engine


class TestDependency:
    """Verify the module is standalone and has the required API."""

    def test_no_pytmd_import(self):
        """tidal_engine.py must not import or wrap pyTMD."""
        with open('/app/tidal_engine.py', 'r') as f:
            source = f.read()
        assert 'import pyTMD' not in source, "Must not import pyTMD"
        assert 'from pyTMD' not in source, "Must not import from pyTMD"

    def test_module_functions_exist(self):
        """All five required functions must exist and be callable."""
        assert callable(getattr(tidal_engine, 'mean_longitudes', None))
        assert callable(getattr(tidal_engine, 'equilibrium_arguments', None))
        assert callable(getattr(tidal_engine, 'nodal_corrections', None))
        assert callable(getattr(tidal_engine, 'predict_tide', None))
        assert callable(getattr(tidal_engine, 'infer_minor', None))


class TestMeanLongitudes:
    """Test astronomical mean longitude computation."""

    def test_cartwright_epoch(self):
        """At the reference epoch T=0, values match known constant terms."""
        mjd = np.array([51544.4993])
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        assert np.allclose(s, 218.3164, atol=0.01)
        assert np.allclose(h, 280.4661, atol=0.01)
        assert np.allclose(p, 83.3535, atol=0.01)
        assert np.allclose(n, 125.0445, atol=0.01)
        assert np.allclose(ps, 282.8, atol=0.2)

    def test_normalization(self):
        """All angles must be in [0, 360)."""
        mjd = np.array([58000.0, 59000.0, 60000.0, 61000.0])
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        for angle in [s, h, p, n, ps]:
            assert np.all(angle >= 0), f"Angle below 0: {angle}"
            assert np.all(angle < 360), f"Angle >= 360: {angle}"

    def test_lunar_rate(self):
        """Mean lunar longitude rate ~13.176 deg/day."""
        mjd1 = np.array([59000.0])
        mjd2 = np.array([59001.0])
        s1, _, _, _, _ = tidal_engine.mean_longitudes(mjd1)
        s2, _, _, _, _ = tidal_engine.mean_longitudes(mjd2)
        rate = (s2 - s1) % 360
        if rate > 180:
            rate -= 360
        assert abs(rate - 13.17639648) < 0.001

    def test_solar_rate(self):
        """Mean solar longitude rate ~0.986 deg/day."""
        mjd1 = np.array([59000.0])
        mjd2 = np.array([59001.0])
        _, h1, _, _, _ = tidal_engine.mean_longitudes(mjd1)
        _, h2, _, _, _ = tidal_engine.mean_longitudes(mjd2)
        rate = (h2 - h1) % 360
        if rate > 180:
            rate -= 360
        assert abs(rate - 0.98564736) < 0.001

    def test_perigee_rate(self):
        """Lunar perigee rate ~0.111 deg/day."""
        mjd1 = np.array([59000.0])
        mjd2 = np.array([59001.0])
        _, _, p1, _, _ = tidal_engine.mean_longitudes(mjd1)
        _, _, p2, _, _ = tidal_engine.mean_longitudes(mjd2)
        rate = (p2 - p1) % 360
        if rate > 180:
            rate -= 360
        assert abs(rate - 0.11140353) < 0.001

    def test_node_rate(self):
        """Ascending lunar node rate ~-0.053 deg/day (retrograde)."""
        mjd1 = np.array([59000.0])
        mjd2 = np.array([59001.0])
        _, _, _, n1, _ = tidal_engine.mean_longitudes(mjd1)
        _, _, _, n2, _ = tidal_engine.mean_longitudes(mjd2)
        rate = (n2 - n1)
        if rate > 180:
            rate -= 360
        if rate < -180:
            rate += 360
        assert abs(rate - (-0.05295377)) < 0.001

    def test_array_input(self):
        """Must handle array inputs and return arrays."""
        mjd = np.array([59000.0, 59000.5, 59001.0])
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        assert len(s) == 3
        assert len(h) == 3
        assert len(p) == 3
        assert len(n) == 3
        assert len(ps) == 3

    def test_scalar_input(self):
        """Must handle scalar MJD input."""
        s, h, p, n, ps = tidal_engine.mean_longitudes(59000.0)
        assert np.isfinite(s).all()
        assert np.isfinite(h).all()


class TestEquilibriumArguments:
    """Test equilibrium argument computation."""

    def test_shape(self):
        """Output shape must be (nt, nc)."""
        mjd = np.array([59000.0, 59000.5])
        constituents = ['m2', 's2', 'o1', 'k1']
        args = tidal_engine.equilibrium_arguments(mjd, constituents)
        assert args.shape == (2, 4)

    def test_s2_equals_30_times_hour(self):
        """S2 argument = 30 * hour (fundamental identity)."""
        mjd = np.array([59000.25, 59000.5, 59000.75])
        args = tidal_engine.equilibrium_arguments(mjd, ['s2'], corrections='OTIS')
        hour = 24.0 * np.mod(mjd, 1)
        t2 = 30.0 * hour
        assert np.allclose(np.mod(args[:, 0], 360), np.mod(t2, 360), atol=0.01)

    def test_m2_equals_2tau(self):
        """M2 argument = 2*tau (fundamental identity)."""
        mjd = np.array([59000.25, 59000.5])
        args = tidal_engine.equilibrium_arguments(mjd, ['m2'], corrections='OTIS')
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        hour = 24.0 * np.mod(mjd, 1)
        tau = 15.0 * hour - s + h
        expected = 2.0 * tau
        assert np.allclose(np.mod(args[:, 0], 360), np.mod(expected, 360), atol=0.01)

    def test_o1_argument(self):
        """O1 argument identity with fundamental variables."""
        mjd = np.array([59000.25])
        args = tidal_engine.equilibrium_arguments(mjd, ['o1'], corrections='OTIS')
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        hour = 24.0 * np.mod(mjd, 1)
        tau = 15.0 * hour - s + h
        expected = tau - s - 90.0
        assert np.allclose(np.mod(args[0, 0], 360), np.mod(expected, 360), atol=0.01)

    def test_k1_argument(self):
        """K1 argument identity with fundamental variables."""
        mjd = np.array([59000.25])
        args = tidal_engine.equilibrium_arguments(mjd, ['k1'], corrections='OTIS')
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        hour = 24.0 * np.mod(mjd, 1)
        tau = 15.0 * hour - s + h
        expected = tau + s + 90.0
        assert np.allclose(np.mod(args[0, 0], 360), np.mod(expected, 360), atol=0.01)

    def test_z0_argument(self):
        """Z0 (mean sea level) argument = 0."""
        mjd = np.array([59000.0])
        args = tidal_engine.equilibrium_arguments(mjd, ['z0'], corrections='OTIS')
        assert np.allclose(np.mod(args[:, 0], 360), 0.0, atol=0.01)

    def test_m4_equals_2_times_m2(self):
        """M4 argument = 2 * M2 (shallow water)."""
        cindex = ['m2', 'm4']
        mjd = np.array([59000.0, 59000.5])
        args = tidal_engine.equilibrium_arguments(mjd, cindex, corrections='OTIS')
        assert np.allclose(
            np.mod(args[:, 1], 360),
            np.mod(2 * args[:, 0], 360),
            atol=0.01
        )

    def test_ms4_equals_m2_plus_s2(self):
        """MS4 argument = M2 + S2 (shallow water)."""
        cindex = ['m2', 's2', 'ms4']
        mjd = np.array([59000.0])
        args = tidal_engine.equilibrium_arguments(mjd, cindex, corrections='OTIS')
        assert np.allclose(
            np.mod(args[0, 2], 360),
            np.mod(args[0, 0] + args[0, 1], 360),
            atol=0.01
        )

    def test_mk3_equals_k1_plus_m2(self):
        """MK3 argument = K1 + M2 (shallow water)."""
        cindex = ['k1', 'm2', 'mk3']
        mjd = np.array([59000.0])
        args = tidal_engine.equilibrium_arguments(mjd, cindex, corrections='OTIS')
        assert np.allclose(
            np.mod(args[0, 2], 360),
            np.mod(args[0, 0] + args[0, 1], 360),
            atol=0.01
        )

    def test_60_constituents(self):
        """All 60 standard constituents must produce finite arguments."""
        cindex = [
            "sa", "ssa", "mm", "msf", "mf", "mt", "alpha1", "2q1", "sigma1",
            "q1", "rho1", "o1", "tau1", "m1", "chi1", "pi1", "p1", "s1", "k1",
            "psi1", "phi1", "theta1", "j1", "oo1", "2n2", "mu2", "n2", "nu2",
            "m2a", "m2", "m2b", "lambda2", "l2", "t2", "s2", "r2", "k2", "eta2",
            "mns2", "2sm2", "m3", "mk3", "s3", "mn4", "m4", "ms4", "mk4", "s4",
            "s5", "m6", "s6", "s7", "s8", "m8", "mks2", "msqm", "mtm", "n4",
            "eps2", "z0",
        ]
        mjd = np.array([59000.0])
        args = tidal_engine.equilibrium_arguments(mjd, cindex, corrections='OTIS')
        assert args.shape == (1, 60)
        assert np.isfinite(args).all()

    def test_minor_constituent_arguments(self):
        """Minor variants m1b and l2b must have valid arguments."""
        mjd = np.array([59000.0])
        minor = ['m1b', 'l2b']
        args = tidal_engine.equilibrium_arguments(mjd, minor, corrections='OTIS')
        assert args.shape == (1, 2)
        assert np.isfinite(args).all()

    def test_case_insensitive(self):
        """Constituent names should be case-insensitive."""
        mjd = np.array([59000.0])
        args_lower = tidal_engine.equilibrium_arguments(mjd, ['m2'], corrections='OTIS')
        args_upper = tidal_engine.equilibrium_arguments(mjd, ['M2'], corrections='OTIS')
        assert np.allclose(args_lower, args_upper)

    def test_mf_equals_2s(self):
        """Mf argument identity with lunar longitude."""
        mjd = np.array([59000.0])
        args = tidal_engine.equilibrium_arguments(mjd, ['mf'], corrections='OTIS')
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        expected = 2.0 * s
        assert np.allclose(np.mod(args[0, 0], 360), np.mod(expected, 360), atol=0.01)

    def test_mm_equals_s_minus_p(self):
        """Mm argument identity with lunar and perigee longitudes."""
        mjd = np.array([59000.0])
        args = tidal_engine.equilibrium_arguments(mjd, ['mm'], corrections='OTIS')
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        expected = s - p
        assert np.allclose(np.mod(args[0, 0], 360), np.mod(expected, 360), atol=0.01)

    def test_m6_equals_3_times_m2(self):
        """M6 = 3 * M2 (shallow water compound)."""
        mjd = np.array([59000.0])
        args = tidal_engine.equilibrium_arguments(mjd, ['m2', 'm6'], corrections='OTIS')
        assert np.allclose(
            np.mod(args[0, 1], 360),
            np.mod(3 * args[0, 0], 360),
            atol=0.01
        )

    def test_m8_equals_4_times_m2(self):
        """M8 = 4 * M2 (shallow water compound)."""
        mjd = np.array([59000.0])
        args = tidal_engine.equilibrium_arguments(mjd, ['m2', 'm8'], corrections='OTIS')
        assert np.allclose(
            np.mod(args[0, 1], 360),
            np.mod(4 * args[0, 0], 360),
            atol=0.01
        )

    def test_n4_equals_2_times_n2(self):
        """N4 = 2 * N2 (shallow water compound)."""
        mjd = np.array([59000.0])
        args = tidal_engine.equilibrium_arguments(mjd, ['n2', 'n4'], corrections='OTIS')
        assert np.allclose(
            np.mod(args[0, 1], 360),
            np.mod(2 * args[0, 0], 360),
            atol=0.01
        )

    def test_mn4_equals_m2_plus_n2(self):
        """MN4 = M2 + N2 (shallow water compound)."""
        mjd = np.array([59000.0])
        args = tidal_engine.equilibrium_arguments(mjd, ['m2', 'n2', 'mn4'], corrections='OTIS')
        assert np.allclose(
            np.mod(args[0, 2], 360),
            np.mod(args[0, 0] + args[0, 1], 360),
            atol=0.01
        )

    def test_sa_daily_rate(self):
        """Sa argument should advance ~0.986 deg/day (annual constituent)."""
        mjd = np.array([59000.0, 59001.0])
        args = tidal_engine.equilibrium_arguments(mjd, ['sa'], corrections='OTIS')
        diff = (args[1, 0] - args[0, 0]) % 360
        if diff > 180:
            diff -= 360
        assert abs(diff - 0.986) < 0.1, f"Sa daily rate {diff} not ~0.986"


class TestNodalCorrections:
    """Test nodal modulation factors (OTIS corrections)."""

    def test_shape(self):
        """Output shapes must be (nt, nc)."""
        mjd = np.array([59000.0, 59000.5])
        constituents = ['m2', 's2', 'o1', 'k1']
        pu, pf = tidal_engine.nodal_corrections(mjd, constituents, corrections='OTIS')
        assert pu.shape == (2, 4)
        assert pf.shape == (2, 4)

    def test_solar_constituents_trivial(self):
        """Solar constituents must have f=1.0 and u=0.0 exactly."""
        mjd = np.array([59000.0, 59500.0, 60000.0])
        solar = ['s2', 'p1', 't2', 'r2', 's1']
        pu, pf = tidal_engine.nodal_corrections(mjd, solar, corrections='OTIS')
        for i, c in enumerate(solar):
            assert np.allclose(pf[:, i], 1.0, atol=1e-10), f"{c}: f != 1.0"
            assert np.allclose(pu[:, i], 0.0, atol=1e-10), f"{c}: u != 0.0"

    def test_z0_trivial(self):
        """Z0 must have f=1.0 and u=0.0."""
        mjd = np.array([59000.0])
        pu, pf = tidal_engine.nodal_corrections(mjd, ['z0'], corrections='OTIS')
        assert np.allclose(pf, 1.0)
        assert np.allclose(pu, 0.0)

    def test_sa_ssa_trivial(self):
        """Sa and Ssa must have f=1.0 and u=0.0."""
        mjd = np.array([59000.0])
        pu, pf = tidal_engine.nodal_corrections(mjd, ['sa', 'ssa'], corrections='OTIS')
        assert np.allclose(pf, 1.0)
        assert np.allclose(pu, 0.0)

    def test_all_factors_positive(self):
        """All nodal amplitude factors must be positive."""
        cindex = ['q1', 'o1', 'p1', 'k1', 'n2', 'm2', 's2', 'k2',
                  'mf', 'mm', 'm1', 'chi1', 'j1', 'oo1', 'l2', 'eta2']
        mjd = np.array([58500.0, 59000.0, 59500.0, 60000.0, 60500.0])
        pu, pf = tidal_engine.nodal_corrections(mjd, cindex, corrections='OTIS')
        assert np.all(pf > 0), f"Negative nodal factor found: min={pf.min()}"

    def test_m2_factor_range(self):
        """M2 nodal factor should be close to 1 (between 0.95 and 1.05)."""
        mjd = np.arange(58000, 61000, 100, dtype=float)
        pu, pf = tidal_engine.nodal_corrections(mjd, ['m2'], corrections='OTIS')
        assert np.all(pf > 0.95), f"M2 f too low: {pf.min()}"
        assert np.all(pf < 1.05), f"M2 f too high: {pf.max()}"

    def test_nodal_angles_bounded(self):
        """Nodal angles should be small (within ~30 degrees)."""
        cindex = ['m2', 'o1', 'k1', 'k2', 'n2', 'q1']
        mjd = np.array([59000.0, 59500.0, 60000.0])
        pu, pf = tidal_engine.nodal_corrections(mjd, cindex, corrections='OTIS')
        assert np.all(np.abs(np.degrees(pu)) < 30), \
            f"Nodal angle too large: max={np.max(np.abs(np.degrees(pu)))}"

    def test_otis_m2_formula(self):
        """M2 nodal corrections must match the OTIS formula."""
        mjd = np.array([59000.0])
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        dtr = np.pi / 180.0
        cosn = np.cos(n * dtr)
        sinn = np.sin(n * dtr)
        cos2n = np.cos(2.0 * n * dtr)
        sin2n = np.sin(2.0 * n * dtr)
        t1 = (1.0 - 0.03731 * cosn + 0.00052 * cos2n)**2
        t2 = (0.03731 * sinn - 0.00052 * sin2n)**2
        expected_f = np.sqrt(t1 + t2)
        num = (-0.03731 * sinn + 0.00052 * sin2n)
        den = (1.0 - 0.03731 * cosn + 0.00052 * cos2n)
        expected_u = np.arctan(num / den)

        pu, pf = tidal_engine.nodal_corrections(mjd, ['m2'], corrections='OTIS')
        assert np.allclose(pf[0, 0], expected_f, rtol=0.02)
        assert np.allclose(pu[0, 0], expected_u, atol=0.01)

    def test_otis_k1_formula(self):
        """K1 nodal corrections must match the OTIS formula."""
        mjd = np.array([59000.0])
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        dtr = np.pi / 180.0
        cosn = np.cos(n * dtr)
        sinn = np.sin(n * dtr)
        cos2n = np.cos(2.0 * n * dtr)
        sin2n = np.sin(2.0 * n * dtr)
        t1 = (1.0 + 0.1158 * cosn - 0.0029 * cos2n)**2
        t2 = (0.1554 * sinn - 0.0029 * sin2n)**2
        expected_f = np.sqrt(t1 + t2)
        num = (-0.1554 * sinn + 0.0029 * sin2n)
        den = (1.0 + 0.1158 * cosn - 0.0029 * cos2n)
        expected_u = np.arctan(num / den)

        pu, pf = tidal_engine.nodal_corrections(mjd, ['k1'], corrections='OTIS')
        assert np.allclose(pf[0, 0], expected_f, rtol=0.02)
        assert np.allclose(pu[0, 0], expected_u, atol=0.01)

    def test_otis_k2_formula(self):
        """K2 nodal corrections must match the OTIS formula."""
        mjd = np.array([59000.0])
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        dtr = np.pi / 180.0
        cosn = np.cos(n * dtr)
        sinn = np.sin(n * dtr)
        cos2n = np.cos(2.0 * n * dtr)
        sin2n = np.sin(2.0 * n * dtr)
        t1 = (1.0 + 0.2852 * cosn + 0.0324 * cos2n)**2
        t2 = (0.3108 * sinn + 0.0324 * sin2n)**2
        expected_f = np.sqrt(t1 + t2)
        num = -(0.3108 * sinn + 0.0324 * sin2n)
        den = (1.0 + 0.2852 * cosn + 0.0324 * cos2n)
        expected_u = np.arctan(num / den)

        pu, pf = tidal_engine.nodal_corrections(mjd, ['k2'], corrections='OTIS')
        assert np.allclose(pf[0, 0], expected_f, rtol=0.02)
        assert np.allclose(pu[0, 0], expected_u, atol=0.01)

    def test_otis_o1_formula(self):
        """O1 nodal corrections must match the OTIS formula."""
        mjd = np.array([59000.0])
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        dtr = np.pi / 180.0
        cosn = np.cos(n * dtr)
        sinn = np.sin(n * dtr)
        cos2n = np.cos(2.0 * n * dtr)
        sin2n = np.sin(2.0 * n * dtr)
        sin3n = np.sin(3.0 * n * dtr)
        t1 = (1.0 + 0.189 * cosn - 0.0058 * cos2n)**2
        t2 = (0.189 * sinn - 0.0058 * sin2n)**2
        expected_f = np.sqrt(t1 + t2)
        expected_u_deg = 10.8 * sinn - 1.3 * sin2n + 0.2 * sin3n
        expected_u = expected_u_deg * dtr

        pu, pf = tidal_engine.nodal_corrections(mjd, ['o1'], corrections='OTIS')
        assert np.allclose(pf[0, 0], expected_f, rtol=0.02)
        assert np.allclose(pu[0, 0], expected_u, atol=0.02)

    def test_m4_equals_m2_squared(self):
        """M4 nodal factor = M2 nodal factor squared."""
        mjd = np.array([59000.0, 59500.0])
        pu, pf = tidal_engine.nodal_corrections(mjd, ['m2', 'm4'], corrections='OTIS')
        assert np.allclose(pf[:, 1], pf[:, 0]**2, rtol=0.01)

    def test_m4_angle_equals_2_times_m2(self):
        """M4 nodal angle = 2 * M2 nodal angle."""
        mjd = np.array([59000.0, 59500.0])
        pu, pf = tidal_engine.nodal_corrections(mjd, ['m2', 'm4'], corrections='OTIS')
        assert np.allclose(pu[:, 1], 2.0 * pu[:, 0], atol=0.01)

    def test_full_60_constituents(self):
        """All 60 constituents must produce valid corrections."""
        cindex = [
            "sa", "ssa", "mm", "msf", "mf", "mt", "alpha1", "2q1", "sigma1",
            "q1", "rho1", "o1", "tau1", "m1", "chi1", "pi1", "p1", "s1", "k1",
            "psi1", "phi1", "theta1", "j1", "oo1", "2n2", "mu2", "n2", "nu2",
            "m2a", "m2", "m2b", "lambda2", "l2", "t2", "s2", "r2", "k2", "eta2",
            "mns2", "2sm2", "m3", "mk3", "s3", "mn4", "m4", "ms4", "mk4", "s4",
            "s5", "m6", "s6", "s7", "s8", "m8", "mks2", "msqm", "mtm", "n4",
            "eps2", "z0",
        ]
        mjd = np.array([59000.0, 59500.0])
        pu, pf = tidal_engine.nodal_corrections(mjd, cindex, corrections='OTIS')
        assert pu.shape == (2, 60)
        assert pf.shape == (2, 60)
        assert np.isfinite(pu).all()
        assert np.isfinite(pf).all()
        assert np.all(pf > 0)

    def test_m1_nodal_varies_with_perigee(self):
        """M1 nodal factor depends on lunar perigee and varies significantly."""
        mjd = np.arange(58000, 62000, 500, dtype=float)
        pu, pf = tidal_engine.nodal_corrections(mjd, ['m1'], corrections='OTIS')
        frange = pf[:, 0].max() - pf[:, 0].min()
        assert frange > 0.5, \
            f"M1 f range={frange:.3f} too narrow; must depend on perigee"
        assert np.all(pf > 0)

    def test_l2_nodal_formula(self):
        """L2 nodal corrections must match OTIS formula involving 2p and 2p-N."""
        mjd = np.array([59000.0])
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        dtr = np.pi / 180.0
        Ltmp1 = (1.0 - 0.25 * np.cos(2 * p * dtr)
                 - 0.11 * np.cos((2 * p - n) * dtr)
                 - 0.04 * np.cos(n * dtr))
        Ltmp2 = (0.25 * np.sin(2 * p * dtr)
                 + 0.11 * np.sin((2 * p - n) * dtr)
                 + 0.04 * np.sin(n * dtr))
        expected_f = np.sqrt(Ltmp1**2 + Ltmp2**2)
        pu, pf = tidal_engine.nodal_corrections(mjd, ['l2'], corrections='OTIS')
        assert np.allclose(pf[0, 0], expected_f, rtol=0.02)

    def test_mk3_nodal_compound(self):
        """MK3 nodal factor = K1 * M2 factors, angle = K1 + M2 angles."""
        mjd = np.array([59000.0, 59500.0])
        pu, pf = tidal_engine.nodal_corrections(
            mjd, ['k1', 'm2', 'mk3'], corrections='OTIS'
        )
        assert np.allclose(pf[:, 2], pf[:, 0] * pf[:, 1], rtol=0.01)
        assert np.allclose(pu[:, 2], pu[:, 0] + pu[:, 1], atol=0.01)

    def test_ms4_nodal_inherits_m2(self):
        """MS4 nodal factor = M2 factor (S2 is trivial)."""
        mjd = np.array([59000.0, 59500.0])
        pu, pf = tidal_engine.nodal_corrections(
            mjd, ['m2', 'ms4'], corrections='OTIS'
        )
        assert np.allclose(pf[:, 1], pf[:, 0], rtol=0.01)
        assert np.allclose(pu[:, 1], pu[:, 0], atol=0.01)

    def test_m6_nodal_equals_m2_cubed(self):
        """M6 nodal factor = M2^3, angle = 3 * M2 angle."""
        mjd = np.array([59000.0, 59500.0])
        pu, pf = tidal_engine.nodal_corrections(
            mjd, ['m2', 'm6'], corrections='OTIS'
        )
        assert np.allclose(pf[:, 1], pf[:, 0]**3, rtol=0.01)
        assert np.allclose(pu[:, 1], 3.0 * pu[:, 0], atol=0.01)

    def test_m8_nodal_equals_m2_fourth(self):
        """M8 nodal factor = M2^4, angle = 4 * M2 angle."""
        mjd = np.array([59000.0, 59500.0])
        pu, pf = tidal_engine.nodal_corrections(
            mjd, ['m2', 'm8'], corrections='OTIS'
        )
        assert np.allclose(pf[:, 1], pf[:, 0]**4, rtol=0.01)
        assert np.allclose(pu[:, 1], 4.0 * pu[:, 0], atol=0.01)

    def test_mf_nodal_formula(self):
        """Mf nodal corrections must match OTIS long-period formula."""
        mjd = np.array([59000.0])
        s, h, p, n, ps = tidal_engine.mean_longitudes(mjd)
        dtr = np.pi / 180.0
        sinn = np.sin(n * dtr)
        sin2n = np.sin(2.0 * n * dtr)
        sin3n = np.sin(3.0 * n * dtr)
        cosn = np.cos(n * dtr)
        expected_f = 1.043 + 0.414 * cosn
        expected_u = np.radians(-23.7 * sinn + 2.7 * sin2n - 0.4 * sin3n)
        pu, pf = tidal_engine.nodal_corrections(mjd, ['mf'], corrections='OTIS')
        assert np.allclose(pf[0, 0], expected_f, rtol=0.02)
        assert np.allclose(pu[0, 0], expected_u, atol=0.02)


class TestPredictTide:
    """Test tidal prediction via harmonic superposition."""

    def test_single_constituent_s2(self):
        """S2 prediction must match analytical formula (f=1, u=0)."""
        mjd = np.array([59000.0, 59000.25, 59000.5, 59000.75])
        hc_real = np.array([1.0])
        hc_imag = np.array([0.0])
        pred = tidal_engine.predict_tide(mjd, hc_real, hc_imag, ['s2'], corrections='OTIS')
        assert pred.shape == (4,)

        args = tidal_engine.equilibrium_arguments(mjd, ['s2'], corrections='OTIS')
        pu, pf = tidal_engine.nodal_corrections(mjd, ['s2'], corrections='OTIS')
        theta = np.radians(args[:, 0]) + pu[:, 0]
        expected = pf[:, 0] * np.cos(theta)
        assert np.allclose(pred, expected, atol=1e-6)

    def test_single_constituent_m2(self):
        """M2 prediction must match analytical formula with nodal corrections."""
        mjd = np.array([59000.0, 59000.25, 59000.5, 59000.75])
        hc_real = np.array([0.5])
        hc_imag = np.array([0.1])
        pred = tidal_engine.predict_tide(mjd, hc_real, hc_imag, ['m2'], corrections='OTIS')

        args = tidal_engine.equilibrium_arguments(mjd, ['m2'], corrections='OTIS')
        pu, pf = tidal_engine.nodal_corrections(mjd, ['m2'], corrections='OTIS')
        theta = np.radians(args[:, 0]) + pu[:, 0]
        expected = 0.5 * pf[:, 0] * np.cos(theta) - 0.1 * pf[:, 0] * np.sin(theta)
        assert np.allclose(pred, expected, atol=1e-6)

    def test_linearity(self):
        """Prediction must be linear: pred(M2+S2) = pred(M2) + pred(S2)."""
        mjd = np.array([59000.0, 59000.5])
        hc_real = np.array([0.5, 0.3])
        hc_imag = np.array([0.1, -0.05])
        pred_both = tidal_engine.predict_tide(mjd, hc_real, hc_imag, ['m2', 's2'])
        pred_m2 = tidal_engine.predict_tide(mjd, hc_real[:1], hc_imag[:1], ['m2'])
        pred_s2 = tidal_engine.predict_tide(mjd, hc_real[1:], hc_imag[1:], ['s2'])
        assert np.allclose(pred_both, pred_m2 + pred_s2, atol=1e-10)

    def test_zero_amplitude(self):
        """Zero amplitude must give zero prediction."""
        mjd = np.array([59000.0, 59000.5])
        pred = tidal_engine.predict_tide(mjd, np.array([0.0]), np.array([0.0]), ['m2'])
        assert np.allclose(pred, 0.0)

    def test_prediction_bounded(self):
        """Prediction amplitude must not exceed sum of constituent amplitudes * max f."""
        mjd = np.linspace(59000.0, 59030.0, 1000)
        hc_real = np.array([0.5, 0.3, 0.1])
        hc_imag = np.array([0.0, 0.0, 0.0])
        constituents = ['m2', 's2', 'o1']
        pred = tidal_engine.predict_tide(mjd, hc_real, hc_imag, constituents)
        max_amplitude = np.sum(np.sqrt(hc_real**2 + hc_imag**2))
        assert np.all(np.abs(pred) < max_amplitude * 1.3)

    def test_output_shape(self):
        """Output length must equal number of input times."""
        mjd = np.linspace(59000, 59001, 25)
        pred = tidal_engine.predict_tide(
            mjd, np.array([0.1, 0.2]), np.array([0.0, 0.0]), ['m2', 's2']
        )
        assert pred.shape == (25,)

    def test_complex_amplitude_identity(self):
        """For f=1 u=0 constituents: |pred(real=1)|^2 + |pred(imag=1)|^2 = 1."""
        mjd = np.array([59000.0])
        pred_r = tidal_engine.predict_tide(
            mjd, np.array([1.0]), np.array([0.0]), ['s2']
        )
        pred_i = tidal_engine.predict_tide(
            mjd, np.array([0.0]), np.array([1.0]), ['s2']
        )
        assert np.allclose(pred_r**2 + pred_i**2, 1.0, atol=0.01)

    def test_phase_shift_orthogonality(self):
        """Real and imaginary predictions should be approximately orthogonal."""
        mjd = np.linspace(59000.0, 59001.0, 49)
        pred_cos = tidal_engine.predict_tide(
            mjd, np.array([1.0]), np.array([0.0]), ['s2']
        )
        pred_sin = tidal_engine.predict_tide(
            mjd, np.array([0.0]), np.array([1.0]), ['s2']
        )
        dot = np.mean(pred_cos * pred_sin)
        assert abs(dot) < 0.15, f"cos/sin predictions not orthogonal: dot={dot}"


class TestInferMinor:
    """Test minor constituent inference via linear admittance."""

    def test_output_shape(self):
        """Output length must equal number of input times."""
        mjd = np.array([59000.0, 59000.5])
        major = ['q1', 'o1', 'p1', 'k1', 'n2', 'm2', 's2', 'k2']
        hc_real = np.array([0.01, 0.1, 0.05, 0.14, 0.05, 0.24, 0.11, 0.03])
        hc_imag = np.array([0.005, 0.02, -0.01, 0.03, 0.01, 0.05, 0.02, 0.01])
        minor = tidal_engine.infer_minor(mjd, hc_real, hc_imag, major)
        assert minor.shape == (2,)

    def test_zero_major_gives_zero_minor(self):
        """Zero major amplitudes must give zero minor contributions."""
        mjd = np.array([59000.0])
        major = ['q1', 'o1', 'p1', 'k1', 'n2', 'm2', 's2', 'k2']
        hc_real = np.zeros(8)
        hc_imag = np.zeros(8)
        minor = tidal_engine.infer_minor(mjd, hc_real, hc_imag, major)
        assert np.allclose(minor, 0.0, atol=1e-10)

    def test_insufficient_majors_returns_zero(self):
        """Fewer than 6 major constituents must return zeros."""
        mjd = np.array([59000.0, 59000.5])
        major = ['m2', 's2', 'k1']
        hc_real = np.array([0.24, 0.11, 0.14])
        hc_imag = np.array([0.05, 0.02, 0.03])
        minor = tidal_engine.infer_minor(mjd, hc_real, hc_imag, major)
        assert np.allclose(minor, 0.0)

    def test_minor_smaller_than_major(self):
        """Minor contribution RMS must be smaller than major prediction RMS."""
        mjd = np.linspace(59000.0, 59030.0, 500)
        major = ['q1', 'o1', 'p1', 'k1', 'n2', 'm2', 's2', 'k2']
        hc_real = np.array([0.019, 0.101, 0.047, 0.142, 0.046, 0.244, 0.113, 0.031])
        hc_imag = np.array([0.005, 0.020, -0.010, 0.030, 0.010, 0.050, 0.020, 0.010])
        major_pred = tidal_engine.predict_tide(mjd, hc_real, hc_imag, major)
        minor_pred = tidal_engine.infer_minor(mjd, hc_real, hc_imag, major)
        major_rms = np.sqrt(np.mean(major_pred**2))
        minor_rms = np.sqrt(np.mean(minor_pred**2))
        assert minor_rms < 0.3 * major_rms, \
            f"Minor RMS {minor_rms:.6f} too large vs major RMS {major_rms:.6f}"

    def test_nonzero_for_nonzero_input(self):
        """Non-zero major constituents must produce non-zero minor contributions."""
        mjd = np.linspace(59000.0, 59030.0, 200)
        major = ['q1', 'o1', 'p1', 'k1', 'n2', 'm2', 's2', 'k2']
        hc_real = np.array([0.019, 0.101, 0.047, 0.142, 0.046, 0.244, 0.113, 0.031])
        hc_imag = np.array([0.005, 0.020, -0.010, 0.030, 0.010, 0.050, 0.020, 0.010])
        minor_pred = tidal_engine.infer_minor(mjd, hc_real, hc_imag, major)
        assert np.max(np.abs(minor_pred)) > 1e-4, "Minor contribution unexpectedly zero"

    def test_linearity_of_inference(self):
        """Minor inference must scale linearly with major amplitudes."""
        mjd = np.array([59000.0, 59000.5, 59001.0])
        major = ['q1', 'o1', 'p1', 'k1', 'n2', 'm2', 's2', 'k2']
        hc_real = np.array([0.019, 0.101, 0.047, 0.142, 0.046, 0.244, 0.113, 0.031])
        hc_imag = np.array([0.005, 0.020, -0.010, 0.030, 0.010, 0.050, 0.020, 0.010])
        minor_1x = tidal_engine.infer_minor(mjd, hc_real, hc_imag, major)
        minor_2x = tidal_engine.infer_minor(mjd, 2 * hc_real, 2 * hc_imag, major)
        assert np.allclose(minor_2x, 2 * minor_1x, rtol=1e-6)

    def test_skip_existing_major(self):
        """If a minor constituent is already in the major list, it must be skipped."""
        mjd = np.array([59000.0, 59000.5])
        major = ['q1', 'o1', 'p1', 'k1', 'n2', 'm2', 's2', 'k2', '2n2']
        hc_real = np.array([0.019, 0.101, 0.047, 0.142, 0.046, 0.244, 0.113, 0.031, 0.006])
        hc_imag = np.zeros(9)

        major_base = ['q1', 'o1', 'p1', 'k1', 'n2', 'm2', 's2', 'k2']
        hc_real_base = hc_real[:8]
        hc_imag_base = hc_imag[:8]

        minor_with_2n2 = tidal_engine.infer_minor(mjd, hc_real, hc_imag, major)
        minor_without_2n2 = tidal_engine.infer_minor(mjd, hc_real_base, hc_imag_base, major_base)
        assert not np.allclose(minor_with_2n2, minor_without_2n2, atol=1e-6)

    def test_five_majors_returns_zero(self):
        """Exactly 5 required major constituents must return zeros."""
        mjd = np.array([59000.0])
        major = ['q1', 'o1', 'p1', 'k1', 'n2']
        hc_real = np.array([0.019, 0.101, 0.047, 0.142, 0.046])
        hc_imag = np.array([0.005, 0.020, -0.010, 0.030, 0.010])
        minor = tidal_engine.infer_minor(mjd, hc_real, hc_imag, major)
        assert np.allclose(minor, 0.0)


class TestIntegration:
    """Integration tests combining multiple components."""

    def test_full_prediction_pipeline(self):
        """Full prediction pipeline must produce reasonable results."""
        mjd = np.linspace(59000.0, 59030.0, 121)
        constituents = ['m2', 's2', 'n2', 'k1', 'o1', 'p1', 'k2', 'q1']
        hc_real = np.array([0.244, 0.113, 0.046, 0.142, 0.101, 0.047, 0.031, 0.019])
        hc_imag = np.array([0.050, 0.020, 0.010, 0.030, 0.020, -0.010, 0.010, 0.005])

        major_pred = tidal_engine.predict_tide(mjd, hc_real, hc_imag, constituents)
        minor_pred = tidal_engine.infer_minor(mjd, hc_real, hc_imag, constituents)
        total = major_pred + minor_pred

        assert total.shape == (121,)
        assert np.isfinite(total).all()
        assert np.max(np.abs(total)) < 2.0, "Total tide exceeds 2m"
        assert np.max(np.abs(total)) > 0.05, "Total tide too small"

    def test_semidiurnal_dominance(self):
        """With M2 as dominant constituent, signal should show ~12.4h period."""
        mjd = np.linspace(59000.0, 59002.0, 193)
        hc_real = np.array([0.5])
        hc_imag = np.array([0.0])
        pred = tidal_engine.predict_tide(mjd, hc_real, hc_imag, ['m2'])
        signs = np.sign(pred[:-1]) * np.sign(pred[1:])
        crossings = np.sum(signs < 0)
        assert 5 <= crossings <= 12, f"Zero crossings={crossings}, expected 6-10 for M2"

    def test_consistency_args_corrections(self):
        """Arguments and corrections must be mutually consistent."""
        mjd = np.array([59000.0])
        constituents = ['m2', 's2', 'k1', 'o1']
        args = tidal_engine.equilibrium_arguments(mjd, constituents, corrections='OTIS')
        pu, pf = tidal_engine.nodal_corrections(mjd, constituents, corrections='OTIS')
        assert np.all(np.isfinite(args))
        assert np.all(np.isfinite(pu))
        assert np.all(np.isfinite(pf))
        assert np.all(np.abs(np.degrees(pu)) < 30)

    def test_multiple_dates(self):
        """Arguments and corrections must vary smoothly over time."""
        mjd = np.linspace(59000.0, 59010.0, 11)
        pu, pf = tidal_engine.nodal_corrections(mjd, ['m2'], corrections='OTIS')
        df = np.abs(np.diff(pf[:, 0]))
        assert np.all(df < 0.01), f"M2 f changes too fast: max delta={df.max()}"

    def test_long_timeseries_finite(self):
        """Prediction over 1 year must remain finite and bounded."""
        mjd = np.linspace(59000.0, 59365.0, 365)
        hc_real = np.array([0.244, 0.113, 0.142, 0.101])
        hc_imag = np.array([0.050, 0.020, 0.030, 0.020])
        pred = tidal_engine.predict_tide(
            mjd, hc_real, hc_imag, ['m2', 's2', 'k1', 'o1']
        )
        assert np.isfinite(pred).all()
        assert np.max(np.abs(pred)) < 2.0
        assert np.max(np.abs(pred)) > 0.05
