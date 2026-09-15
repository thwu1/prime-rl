
"""
Tests for the SGWT pipeline.  Compares solver output against PyGSP
reference values computed from the same graph specification.
"""

import ctypes
import json
import os
import subprocess
import numpy as np
import pytest
from pygsp import graphs, filters, utils
from pygsp.filters import approximations


# --------------- helpers ---------------

def _build_graph_and_signal():
    """Build the reference graph and signal from graph_spec.json."""
    with open("/app/graph_spec.json") as f:
        spec = json.load(f)

    N = spec["n_nodes"]
    W = np.zeros((N, N))
    for edge in spec["edges"]:
        i, j, w = int(edge[0]), int(edge[1]), float(edge[2])
        W[i, j] = w
        W[j, i] = w

    G = graphs.Graph(W)
    G.compute_fourier_basis()
    signal = np.array(spec["signal"])
    return G, signal, spec


def _load_results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ref():
    G, signal, spec = _build_graph_and_signal()
    results = _load_results()
    return G, signal, spec, results


# --------------- test classes ---------------

class TestNativeLibrary:
    """Verify the native C shared library is built and functional."""

    def test_shared_library_exists(self):
        assert os.path.exists("/app/libsgwt_native.so"), \
            "C shared library /app/libsgwt_native.so not found — run 'make' in /app/"

    def test_library_loadable(self):
        lib = ctypes.CDLL("/app/libsgwt_native.so")
        assert lib is not None

    def test_cheby_op_exported(self):
        lib = ctypes.CDLL("/app/libsgwt_native.so")
        fn = getattr(lib, "cheby_op_c", None)
        assert fn is not None, "cheby_op_c not exported from shared library"

    def test_filtering_uses_native(self):
        """Verify filtering.py uses ctypes to call the native library."""
        with open("/app/sgwt_lib/filtering.py") as f:
            code = f.read()
        assert "ctypes" in code, "filtering.py must use ctypes for native ops"
        assert "cheby_op_c" in code, "filtering.py must call cheby_op_c"


class TestNoGSPLibraries:
    """Verify the solver did not use any graph signal processing library."""

    def test_no_pygsp_import(self):
        for pattern in [
            "import pygsp", "from pygsp",
            "import PyGSP", "from PyGSP",
            "import gspbox", "from gspbox",
            "import sgwt_toolbox", "from sgwt_toolbox",
        ]:
            result = subprocess.run(
                ["grep", "-ri", pattern, "/app/"],
                capture_output=True, text=True,
            )
            assert result.returncode != 0, (
                f"Solver must not use GSP libraries. Found: {pattern}"
            )


class TestEigenvalues:
    def test_eigenvalue_count(self, ref):
        _, _, spec, results = ref
        eigs = np.array(results["eigenvalues"])
        assert len(eigs) == spec["n_nodes"]

    def test_eigenvalues_match(self, ref):
        G, _, _, results = ref
        ref_eigs = np.sort(np.linalg.eigvalsh(G.L.toarray()))
        solver_eigs = np.array(results["eigenvalues"])
        assert solver_eigs.shape == ref_eigs.shape
        np.testing.assert_allclose(solver_eigs, ref_eigs, atol=1e-10)

    def test_first_eigenvalue_near_zero(self, ref):
        _, _, _, results = ref
        eigs = np.array(results["eigenvalues"])
        assert abs(eigs[0]) < 1e-10

    def test_eigenvalues_sorted(self, ref):
        _, _, _, results = ref
        eigs = np.array(results["eigenvalues"])
        assert np.all(np.diff(eigs) >= -1e-14)


class TestLogScales:
    def test_log_scales_match(self, ref):
        G, _, spec, results = ref
        lmin = G.lmax / spec["mexicanhat_lpfactor"]
        ref_scales = utils.compute_log_scales(
            lmin, G.lmax, spec["mexicanhat_nf"] - 1
        )
        solver_scales = np.array(results["log_scales"])
        assert solver_scales.shape == ref_scales.shape
        np.testing.assert_allclose(solver_scales, ref_scales, atol=1e-10)

    def test_log_scales_descending(self, ref):
        _, _, _, results = ref
        scales = np.array(results["log_scales"])
        assert np.all(np.diff(scales) < 0), "Log scales should be descending"

    def test_log_scales_positive(self, ref):
        _, _, _, results = ref
        scales = np.array(results["log_scales"])
        assert np.all(scales > 0)

    def test_log_scales_count(self, ref):
        _, _, spec, results = ref
        scales = np.array(results["log_scales"])
        assert len(scales) == spec["mexicanhat_nf"] - 1


class TestMeyerExact:
    def test_meyer_analysis_shape(self, ref):
        G, _, spec, results = ref
        coeffs = np.array(results["meyer_analysis_exact"])
        assert coeffs.shape == (G.N, spec["meyer_nf"])

    def test_meyer_analysis_values(self, ref):
        G, signal, spec, results = ref
        g = filters.Meyer(G, Nf=spec["meyer_nf"])
        ref_coeffs = g.filter(signal, method="exact")
        solver_coeffs = np.array(results["meyer_analysis_exact"])
        np.testing.assert_allclose(solver_coeffs, ref_coeffs, atol=1e-8)


class TestMeyerFrameBounds:
    def test_frame_bounds_match(self, ref):
        G, _, spec, results = ref
        g = filters.Meyer(G, Nf=spec["meyer_nf"])
        A_ref, B_ref = g.estimate_frame_bounds(G.e)
        solver_bounds = results["meyer_frame_bounds"]
        np.testing.assert_allclose(solver_bounds[0], A_ref, atol=1e-10)
        np.testing.assert_allclose(solver_bounds[1], B_ref, atol=1e-10)

    def test_meyer_is_tight_frame(self, ref):
        _, _, _, results = ref
        A, B = results["meyer_frame_bounds"]
        assert abs(A - B) < 0.01, (
            f"Meyer should be a tight frame (A~B), got A={A}, B={B}"
        )

    def test_frame_bounds_near_unity(self, ref):
        """Meyer tight frame has A = B = 1.0."""
        _, _, _, results = ref
        A, B = results["meyer_frame_bounds"]
        np.testing.assert_allclose(A, 1.0, atol=0.02)
        np.testing.assert_allclose(B, 1.0, atol=0.02)


class TestMexicanHatExact:
    def test_mexicanhat_analysis_shape(self, ref):
        G, _, spec, results = ref
        coeffs = np.array(results["mexicanhat_analysis_exact"])
        assert coeffs.shape == (G.N, spec["mexicanhat_nf"])

    def test_mexicanhat_analysis_values(self, ref):
        G, signal, spec, results = ref
        g = filters.MexicanHat(
            G, Nf=spec["mexicanhat_nf"],
            lpfactor=spec["mexicanhat_lpfactor"],
        )
        ref_coeffs = g.filter(signal, method="exact")
        solver_coeffs = np.array(results["mexicanhat_analysis_exact"])
        np.testing.assert_allclose(solver_coeffs, ref_coeffs, atol=1e-8)


class TestChebyshevMeyer:
    def test_chebyshev_analysis_shape(self, ref):
        G, _, spec, results = ref
        coeffs = np.array(results["chebyshev_meyer_analysis"])
        assert coeffs.shape == (G.N, spec["meyer_nf"])

    def test_chebyshev_analysis_values(self, ref):
        G, signal, spec, results = ref
        g = filters.Meyer(G, Nf=spec["meyer_nf"])
        ref_cheby = g.filter(
            signal, method="chebyshev", order=spec["chebyshev_order"]
        )
        solver_cheby = np.array(results["chebyshev_meyer_analysis"])
        np.testing.assert_allclose(solver_cheby, ref_cheby, atol=1e-6)

    def test_chebyshev_close_to_exact(self, ref):
        _, _, _, results = ref
        exact = np.array(results["meyer_analysis_exact"])
        cheby = np.array(results["chebyshev_meyer_analysis"])
        max_err = np.max(np.abs(exact - cheby))
        assert max_err < 0.5, (
            f"Chebyshev should approximate exact; max_err={max_err}"
        )

    def test_chebyshev_max_error_reported(self, ref):
        _, _, _, results = ref
        exact = np.array(results["meyer_analysis_exact"])
        cheby = np.array(results["chebyshev_meyer_analysis"])
        actual_err = float(np.max(np.abs(exact - cheby)))
        reported_err = results["chebyshev_max_error"]
        np.testing.assert_allclose(reported_err, actual_err, rtol=0.01)


class TestMeyerReconstruction:
    def test_reconstruction_error_match(self, ref):
        G, signal, spec, results = ref
        g = filters.Meyer(G, Nf=spec["meyer_nf"])
        analyzed = g.filter(signal, method="exact")
        reconstructed = g.filter(analyzed, method="exact")
        ref_error = float(np.linalg.norm(signal - reconstructed))
        solver_error = results["meyer_reconstruction_error"]
        np.testing.assert_allclose(solver_error, ref_error, atol=1e-6)

    def test_reconstruction_near_perfect(self, ref):
        _, _, _, results = ref
        assert results["meyer_reconstruction_error"] < 1e-6, (
            f"Meyer tight frame should give near-perfect reconstruction, "
            f"got error={results['meyer_reconstruction_error']}"
        )


class TestJacksonChebyshev:
    def test_jackson_chebyshev_length(self, ref):
        _, _, spec, results = ref
        jch = results["jackson_chebyshev_coefficients"]
        assert len(jch) == spec["jackson_m"] + 1

    def test_jackson_chebyshev_values(self, ref):
        G, _, spec, results = ref
        bounds = list(spec["jackson_filter_bounds"])
        m = spec["jackson_m"]
        _, ref_jch = approximations.compute_jackson_cheby_coeff(
            bounds, [0, G.lmax], m
        )
        solver_jch = np.array(results["jackson_chebyshev_coefficients"])
        np.testing.assert_allclose(solver_jch, ref_jch, atol=1e-10)


class TestEnergyConservation:
    def test_meyer_parseval(self, ref):
        """For a tight frame with bound A, sum of squared coefficients = A * ||s||^2."""
        G, signal, spec, results = ref
        g = filters.Meyer(G, Nf=spec["meyer_nf"])
        A_ref, B_ref = g.estimate_frame_bounds(G.e)
        meyer_exact = np.array(results["meyer_analysis_exact"])
        analysis_energy = np.sum(meyer_exact ** 2)
        signal_energy = np.sum(signal ** 2)
        np.testing.assert_allclose(
            analysis_energy / signal_energy, A_ref, rtol=0.01
        )

    def test_chebyshev_error_bounded(self, ref):
        """Chebyshev order-30 approximation error should be small."""
        _, _, _, results = ref
        assert results["chebyshev_max_error"] < 0.1, (
            f"Chebyshev order-30 approximation error too large: "
            f"{results['chebyshev_max_error']}"
        )
