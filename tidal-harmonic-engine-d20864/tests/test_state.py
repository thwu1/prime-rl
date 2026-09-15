
"""
Tests for the tidal harmonic analysis and prediction engine.
Verifies C library, astronomical computations, Doodson numbers, nodal
corrections, harmonic analysis (round-trip), and tidal prediction accuracy.
"""
import ctypes
import os
import sys
import json
import numpy as np
import pytest

sys.path.insert(0, "/app")


@pytest.fixture
def engine():
    import importlib
    import tidal_engine
    importlib.reload(tidal_engine)
    return tidal_engine


@pytest.fixture
def doodson_coefs():
    with open("/app/doodson_coefficients.json") as f:
        return json.load(f)


# ── Test 0: C shared library ──────────────────────────────────────────

class TestCLibrary:
    """Verify the C shared library builds and produces correct results."""

    LIB_PATH = "/app/libastro/libastro.so"

    def _call_c(self, mjd_val):
        """Call compute_mean_longitudes in the C library directly."""
        lib = ctypes.CDLL(self.LIB_PATH)
        DPTR = ctypes.POINTER(ctypes.c_double)
        lib.compute_mean_longitudes.argtypes = [
            DPTR, ctypes.c_int, DPTR, DPTR, DPTR, DPTR, DPTR
        ]
        lib.compute_mean_longitudes.restype = None

        mjd = (ctypes.c_double * 1)(mjd_val)
        s = (ctypes.c_double * 1)()
        h = (ctypes.c_double * 1)()
        p = (ctypes.c_double * 1)()
        n = (ctypes.c_double * 1)()
        pp = (ctypes.c_double * 1)()

        lib.compute_mean_longitudes(
            ctypes.cast(mjd, DPTR), 1,
            ctypes.cast(s, DPTR), ctypes.cast(h, DPTR),
            ctypes.cast(p, DPTR), ctypes.cast(n, DPTR),
            ctypes.cast(pp, DPTR),
        )
        return s[0], h[0], p[0], n[0], pp[0]

    def test_libastro_exists(self):
        """The shared library must be built and loadable."""
        assert os.path.isfile(self.LIB_PATH), "libastro.so not found"
        lib = ctypes.CDLL(self.LIB_PATH)
        assert lib is not None

    def test_c_longitudes_reference_epoch(self):
        """C library at MJD 55414.0 must match expected values."""
        s, h, p, n, pp = self._call_c(55414.0)
        assert abs(s - 84.38) < 0.5, f"C s = {s}, expected ~84.38"
        assert abs(h - 134.43) < 0.5, f"C h = {h}, expected ~134.43"
        assert abs(p - 154.43) < 0.5, f"C p = {p}, expected ~154.43"
        assert abs(n - 280.14) < 0.5, f"C n = {n}, expected ~280.14"
        assert abs(pp - 282.8) < 1.0, f"C pp = {pp}, expected ~282.8"

    def test_c_longitudes_range(self):
        """All C library outputs must be in [0, 360) across epochs."""
        for mjd_val in [40000.0, 48622.0, 51544.5, 55414.0, 60000.0]:
            s, h, p, n, pp = self._call_c(mjd_val)
            for val, name in [(s, "s"), (h, "h"), (p, "p"),
                              (n, "n"), (pp, "pp")]:
                assert 0.0 <= val < 360.0, (
                    f"C {name} = {val} out of [0, 360) at MJD {mjd_val}"
                )

    def test_c_array_consistency(self):
        """C library must handle array of MJDs and match scalar calls."""
        lib = ctypes.CDLL(self.LIB_PATH)
        DPTR = ctypes.POINTER(ctypes.c_double)
        lib.compute_mean_longitudes.argtypes = [
            DPTR, ctypes.c_int, DPTR, DPTR, DPTR, DPTR, DPTR
        ]
        lib.compute_mean_longitudes.restype = None

        mjds = [51544.5, 55414.0]
        mjd_arr = (ctypes.c_double * 2)(*mjds)
        s = (ctypes.c_double * 2)()
        h = (ctypes.c_double * 2)()
        p = (ctypes.c_double * 2)()
        n = (ctypes.c_double * 2)()
        pp = (ctypes.c_double * 2)()

        lib.compute_mean_longitudes(
            ctypes.cast(mjd_arr, DPTR), 2,
            ctypes.cast(s, DPTR), ctypes.cast(h, DPTR),
            ctypes.cast(p, DPTR), ctypes.cast(n, DPTR),
            ctypes.cast(pp, DPTR),
        )

        # Compare with scalar calls
        for idx, mjd_val in enumerate(mjds):
            s1, h1, p1, n1, pp1 = self._call_c(mjd_val)
            assert abs(s[idx] - s1) < 1e-10
            assert abs(n[idx] - n1) < 1e-10


# ── Test 1: Doodson number computation ──────────────────────────────────

class TestDoodsonNumbers:
    """Verify Doodson numbers for standard tidal constituents."""

    EXPECTED = {
        "m2": 255.555,
        "s2": 273.555,
        "n2": 245.655,
        "nu2": 247.455,
        "mu2": 237.555,
        "2n2": 235.755,
        "l2": 265.455,
        "k2": 275.555,
        "o1": 145.555,
        "k1": 165.555,
        "q1": 135.655,
        "p1": 163.555,
        "2q1": 125.755,
        "oo1": 185.555,
        "mm": 65.455,
        "ssa": 57.555,
        "mf": 75.555,
        "m3": 355.555,
        "m4": 455.555,
        "m6": 655.555,
        "m8": 855.555,
    }

    def test_doodson_numbers(self, engine):
        for name, expected in self.EXPECTED.items():
            result = engine.doodson_number(name)
            assert abs(result - expected) < 0.0005, (
                f"Doodson number for {name}: got {result}, expected {expected}"
            )


# ── Test 2: Mean longitudes ─────────────────────────────────────────────

class TestMeanLongitudes:
    """Verify mean longitudes at MJD 55414.0 against ASTRO5 reference."""

    def test_mean_longitudes_at_reference_epoch(self, engine):
        mjd = 55414.0
        s, h, p, n, pp = engine.mean_longitudes(mjd)

        assert abs(s - 84.38) < 0.5, f"Moon longitude: got {s}"
        assert abs(h - 134.43) < 0.5, f"Sun longitude: got {h}"
        assert abs(p - 154.43) < 0.5, f"Lunar perigee: got {p}"
        assert abs(n - 280.14) < 0.5, f"Lunar node: got {n}"
        assert abs(pp - 282.8) < 1.0, f"Solar perigee: got {pp}"

    def test_mean_longitudes_range(self, engine):
        """All longitudes must be in [0, 360)."""
        for mjd in [40000.0, 51544.5, 55414.0, 60000.0]:
            s, h, p, n, pp = engine.mean_longitudes(mjd)
            for val, name in [(s, "s"), (h, "h"), (p, "p"),
                              (n, "n"), (pp, "pp")]:
                assert 0.0 <= val < 360.0, (
                    f"Longitude {name} = {val} out of range at MJD {mjd}"
                )

    def test_mean_longitudes_array_input(self, engine):
        """Must handle numpy array input."""
        mjds = np.array([51544.5, 55414.0])
        result = engine.mean_longitudes(mjds)
        assert len(result) == 5
        for arr in result:
            assert hasattr(arr, "__len__") and len(arr) == 2


# ── Test 3: Angular frequencies ─────────────────────────────────────────

class TestAngularFrequency:
    """Verify angular frequencies against tabulated values."""

    EXPECTED = {
        "m2": 1.405189e-04,
        "s2": 1.454441e-04,
        "k1": 7.292117e-05,
        "o1": 6.759774e-05,
        "n2": 1.378797e-04,
        "p1": 7.252295e-05,
        "k2": 1.458423e-04,
        "q1": 6.495854e-05,
        "mf": 0.053234e-04,
        "mm": 0.026392e-04,
    }

    def test_angular_frequencies(self, engine):
        names = list(self.EXPECTED.keys())
        omega = engine.angular_frequency(names)
        assert len(omega) == len(names)
        for i, name in enumerate(names):
            expected = self.EXPECTED[name]
            assert abs(omega[i] - expected) / expected < 1e-3, (
                f"Frequency for {name}: got {omega[i]:.6e}, "
                f"expected {expected:.6e}"
            )

    def test_frequencies_are_positive(self, engine):
        omega = engine.angular_frequency(["m2", "s2", "k1", "o1"])
        assert np.all(omega > 0)

    def test_frequency_ordering(self, engine):
        """Semi-diurnal constituents should have ~2x diurnal frequency."""
        omega = engine.angular_frequency(["o1", "m2"])
        ratio = omega[1] / omega[0]
        assert 1.8 < ratio < 2.2, f"M2/O1 frequency ratio: {ratio}"


# ── Test 4: Nodal corrections ───────────────────────────────────────────

class TestNodalCorrections:
    """Verify nodal correction factors and angles."""

    def test_s2_no_correction(self, engine):
        """S2 should have f~1 and u~0 (nearly no nodal modulation)."""
        mjd = np.array([55414.0])
        u, f = engine.nodal_corrections(mjd, ["s2"])
        assert abs(f[0, 0] - 1.0) < 0.01
        assert abs(u[0, 0]) < 0.05

    def test_p1_no_correction(self, engine):
        """P1 should have f~1 and u~0."""
        mjd = np.array([55414.0])
        u, f = engine.nodal_corrections(mjd, ["p1"])
        assert abs(f[0, 0] - 1.0) < 0.02
        assert abs(u[0, 0]) < 0.05

    def test_m2_nodal_factor_range(self, engine):
        """M2 nodal factor should be near 1 (within ~5%)."""
        mjds = np.array([51544.5, 53000.0, 55414.0, 57000.0])
        u, f = engine.nodal_corrections(mjds, ["m2"])
        assert np.all(f[:, 0] > 0.9)
        assert np.all(f[:, 0] < 1.1)

    def test_k1_nodal_factor_range(self, engine):
        """K1 nodal factor varies more, but should be in (0.85, 1.15)."""
        mjds = np.array([51544.5, 53000.0, 55414.0, 57000.0])
        u, f = engine.nodal_corrections(mjds, ["k1"])
        assert np.all(f[:, 0] > 0.85)
        assert np.all(f[:, 0] < 1.15)

    def test_output_shapes(self, engine):
        """Output arrays must have shape (nt, nc)."""
        mjds = np.array([55000.0, 55100.0, 55200.0])
        constituents = ["m2", "s2", "k1", "o1"]
        u, f = engine.nodal_corrections(mjds, constituents)
        assert u.shape == (3, 4)
        assert f.shape == (3, 4)

    def test_o1_nodal_varies(self, engine):
        """O1 should show non-trivial nodal variation over 18.6-year cycle."""
        mjd1 = np.array([51544.5])
        mjd2 = np.array([54832.0])
        _, f1 = engine.nodal_corrections(mjd1, ["o1"])
        _, f2 = engine.nodal_corrections(mjd2, ["o1"])
        assert abs(f1[0, 0] - f2[0, 0]) > 0.01, (
            f"O1 nodal factor not varying: {f1[0,0]:.4f} vs {f2[0,0]:.4f}"
        )


# ── Test 5: Constituent parameters table ────────────────────────────────

class TestConstituentParameters:
    """Verify the embedded constituent parameter lookup table."""

    PARAMS = {
        "m2": {"amplitude": 0.2441, "omega": 1.405189e-04, "species": 2},
        "s2": {"amplitude": 0.112743, "omega": 1.454441e-04, "species": 2},
        "k1": {"amplitude": 0.141565, "omega": 7.292117e-05, "species": 1},
        "o1": {"amplitude": 0.100661, "omega": 6.759774e-05, "species": 1},
        "n2": {"amplitude": 0.046397, "omega": 1.378797e-04, "species": 2},
        "p1": {"amplitude": 0.046848, "omega": 7.252295e-05, "species": 1},
        "k2": {"amplitude": 0.030684, "omega": 1.458423e-04, "species": 2},
        "q1": {"amplitude": 0.019273, "omega": 6.495854e-05, "species": 1},
        "mf": {"amplitude": 0.042041, "omega": 0.053234e-04, "species": 0},
        "mm": {"amplitude": 0.022191, "omega": 0.026392e-04, "species": 0},
    }

    def test_constituent_parameters(self, engine):
        for name, expected in self.PARAMS.items():
            amp, phase, omega, alpha, species = engine._constituent_parameters(name)
            assert abs(amp - expected["amplitude"]) < 1e-4, (
                f"{name} amplitude: {amp} vs {expected['amplitude']}"
            )
            assert abs(omega - expected["omega"]) / expected["omega"] < 1e-3, (
                f"{name} omega: {omega} vs {expected['omega']}"
            )
            assert species == expected["species"], (
                f"{name} species: {species} vs {expected['species']}"
            )


# ── Test 6: Round-trip harmonic analysis ────────────────────────────────

class TestHarmonicAnalysis:
    """Generate synthetic tidal data, analyze, and verify amplitude recovery."""

    CONSTITUENTS = ["m2", "s2", "k1", "o1", "n2", "p1"]
    TRUE_AMP = [1.20, 0.45, 0.80, 0.55, 0.25, 0.30]
    TRUE_PHASE = [0.5, 1.2, 2.1, 0.8, 3.5, 5.0]

    def _generate_synthetic(self, engine, t_days):
        """Generate synthetic tidal signal from known constituents."""
        mjd_tide = 48622.0
        mjd = t_days + mjd_tide

        signal = np.zeros_like(t_days)
        for i, c in enumerate(self.CONSTITUENTS):
            amp, phase0, omega, alpha, species = engine._constituent_parameters(c)
            u, f = engine.nodal_corrections(mjd, [c])
            theta = omega * t_days * 86400.0 + phase0 + u[:, 0]
            A = self.TRUE_AMP[i]
            phi = self.TRUE_PHASE[i]
            signal += A * f[:, 0] * np.cos(theta - phi)
        return signal

    def test_amplitude_recovery(self, engine):
        """Recovered amplitudes must match true values within 5%."""
        t_days = np.arange(0, 60, 1.0 / 24.0)
        signal = self._generate_synthetic(engine, t_days)

        hc = engine.harmonic_analysis(t_days, signal, self.CONSTITUENTS)

        for i, c in enumerate(self.CONSTITUENTS):
            if isinstance(hc, dict):
                z = hc[c]
            else:
                z = hc[i]
            recovered_amp = abs(z)
            true_amp = self.TRUE_AMP[i]
            rel_err = abs(recovered_amp - true_amp) / true_amp
            assert rel_err < 0.05, (
                f"{c}: recovered amplitude {recovered_amp:.4f} vs "
                f"true {true_amp:.4f} (rel error {rel_err:.3f})"
            )

    def test_harmonic_analysis_returns_complex(self, engine):
        """harmonic_analysis must return complex values."""
        t_days = np.arange(0, 30, 1.0 / 24.0)
        signal = self._generate_synthetic(engine, t_days)
        hc = engine.harmonic_analysis(t_days, signal, self.CONSTITUENTS)
        if isinstance(hc, dict):
            for c in self.CONSTITUENTS:
                assert np.iscomplex(hc[c]) or isinstance(hc[c], complex), (
                    f"hc[{c}] should be complex"
                )
        else:
            assert np.iscomplexobj(hc), "hc should be complex array"


# ── Test 7: Tidal prediction ───────────────────────────────────────────

class TestTidalPrediction:
    """Verify prediction accuracy using round-trip analysis."""

    CONSTITUENTS = ["m2", "s2", "k1", "o1"]
    TRUE_AMP = [1.50, 0.60, 0.90, 0.65]
    TRUE_PHASE = [0.3, 1.8, 2.5, 0.9]

    def _generate_synthetic(self, engine, t_days):
        mjd_tide = 48622.0
        mjd = t_days + mjd_tide
        signal = np.zeros_like(t_days)
        for i, c in enumerate(self.CONSTITUENTS):
            amp, phase0, omega, alpha, species = engine._constituent_parameters(c)
            u, f = engine.nodal_corrections(mjd, [c])
            theta = omega * t_days * 86400.0 + phase0 + u[:, 0]
            A = self.TRUE_AMP[i]
            phi = self.TRUE_PHASE[i]
            signal += A * f[:, 0] * np.cos(theta - phi)
        return signal

    def test_prediction_round_trip(self, engine):
        """Analyze 90 days of data, predict on same period, verify RMS < 2mm."""
        t_train = np.arange(0, 90, 1.0 / 24.0)
        signal = self._generate_synthetic(engine, t_train)

        hc = engine.harmonic_analysis(t_train, signal, self.CONSTITUENTS)

        if not isinstance(hc, dict):
            hc_dict = {c: hc[i] for i, c in enumerate(self.CONSTITUENTS)}
        else:
            hc_dict = hc

        predicted = engine.predict_tide(t_train, hc_dict, self.CONSTITUENTS)

        residual = signal - predicted
        rms = np.sqrt(np.mean(residual ** 2))
        assert rms < 0.002, f"Prediction RMS = {rms:.4f} m (must be < 0.002)"

    def test_prediction_on_validation_period(self, engine):
        """Train on first 60 days, predict next 30 days, RMS < 5mm."""
        t_train = np.arange(0, 60, 1.0 / 24.0)
        t_valid = np.arange(60, 90, 1.0 / 24.0)

        signal_train = self._generate_synthetic(engine, t_train)
        signal_valid = self._generate_synthetic(engine, t_valid)

        hc = engine.harmonic_analysis(t_train, signal_train, self.CONSTITUENTS)

        if not isinstance(hc, dict):
            hc_dict = {c: hc[i] for i, c in enumerate(self.CONSTITUENTS)}
        else:
            hc_dict = hc

        predicted = engine.predict_tide(t_valid, hc_dict, self.CONSTITUENTS)

        residual = signal_valid - predicted
        rms = np.sqrt(np.mean(residual ** 2))
        assert rms < 0.005, (
            f"Validation RMS = {rms:.4f} m (must be < 0.005)"
        )

    def test_prediction_output_length(self, engine):
        """Predicted output must match input time array length."""
        t = np.arange(0, 10, 1.0 / 24.0)
        hc_dict = {c: complex(1.0, 0.5) for c in self.CONSTITUENTS}
        predicted = engine.predict_tide(t, hc_dict, self.CONSTITUENTS)
        assert len(predicted) == len(t)
