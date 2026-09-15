
import pytest
import numpy as np
import sys
import subprocess

# Generate FRF data before importing the module
subprocess.run([sys.executable, '/app/generate_frf.py'], check=True)

sys.path.insert(0, '/app')
import modal_analysis


@pytest.fixture(scope='session')
def frf_data():
    data = np.load('/app/data/frf_data.npz', allow_pickle=True)
    return {
        'freq': data['freq'],
        'frf': data['frf'],
        'nat_freq_true': data['nat_freq_true'],
        'damping_true': data['damping_true'],
        'mode_shapes_true': data['mode_shapes_true'],
    }


@pytest.fixture(scope='session')
def pole_result(frf_data):
    result = modal_analysis.identify_poles(
        frf=frf_data['frf'],
        freq=frf_data['freq'],
        lower=frf_data['freq'][0],
        upper=frf_data['freq'][-1],
        pol_order_high=60,
    )
    return result


@pytest.fixture(scope='session')
def selected(pole_result, frf_data):
    result = modal_analysis.select_stable_poles(
        all_poles=pole_result['all_poles'],
        pole_freq=pole_result['pole_freq'],
        pole_xi=pole_result['pole_xi'],
        approx_nat_freq=frf_data['nat_freq_true'].tolist(),
    )
    return result


@pytest.fixture(scope='session')
def modal_result(selected, frf_data):
    result = modal_analysis.identify_modal_constants(
        poles=selected['selected_poles'],
        frf=frf_data['frf'],
        freq=frf_data['freq'],
        frf_type='accelerance',
    )
    return result


# ── identify_poles output structure ──────────────────────────────────

class TestIdentifyPoles:
    def test_returns_required_keys(self, pole_result):
        for key in ('all_poles', 'pole_freq', 'pole_xi'):
            assert key in pole_result, f"Missing key '{key}'"

    def test_lists_same_length(self, pole_result):
        n = len(pole_result['all_poles'])
        assert n > 0, "all_poles is empty"
        assert len(pole_result['pole_freq']) == n
        assert len(pole_result['pole_xi']) == n

    def test_poles_are_complex(self, pole_result):
        for poles in pole_result['all_poles']:
            assert np.iscomplexobj(poles), "Poles must be complex"

    def test_some_positive_frequencies(self, pole_result):
        has_positive = any(
            np.any(np.asarray(f) > 0) for f in pole_result['pole_freq']
        )
        assert has_positive, "No positive frequencies found across any order"


# ── select_stable_poles ──────────────────────────────────────────────

class TestSelectStablePoles:
    def test_returns_required_keys(self, selected):
        for key in ('nat_freq', 'nat_xi', 'selected_poles'):
            assert key in selected, f"Missing key '{key}'"

    def test_correct_count(self, selected, frf_data):
        n_modes = len(frf_data['nat_freq_true'])
        assert len(selected['nat_freq']) == n_modes
        assert len(selected['nat_xi']) == n_modes
        assert len(selected['selected_poles']) == n_modes

    def test_natural_frequencies(self, selected, frf_data):
        nat_freq = np.array(selected['nat_freq'])
        truth = frf_data['nat_freq_true']
        close_abs = np.allclose(nat_freq, truth, atol=1.0, rtol=0)
        close_rel = np.allclose(nat_freq, truth, atol=0, rtol=2e-2)
        assert close_abs or close_rel, (
            f"Identified frequencies {nat_freq} do not match truth {truth}"
        )

    def test_damping_ratios(self, selected, frf_data):
        nat_xi = np.array(selected['nat_xi'])
        truth = frf_data['damping_true']
        assert np.allclose(nat_xi, truth, rtol=5e-2), (
            f"Identified damping {nat_xi} do not match truth {truth}"
        )

    def test_positive_values(self, selected):
        assert np.all(np.array(selected['nat_freq']) > 0), "Frequencies must be positive"
        assert np.all(np.array(selected['nat_xi']) > 0), "Damping ratios must be positive"


# ── identify_modal_constants ─────────────────────────────────────────

class TestIdentifyModalConstants:
    def test_returns_required_keys(self, modal_result):
        for key in ('modal_constants', 'reconstructed_frf', 'LR', 'UR'):
            assert key in modal_result, f"Missing key '{key}'"

    def test_modal_constants_shape(self, modal_result, frf_data):
        A = modal_result['modal_constants']
        n_loc = frf_data['frf'].shape[0]
        n_modes = len(frf_data['nat_freq_true'])
        assert A.shape == (n_loc, n_modes), (
            f"Shape {A.shape} != expected ({n_loc}, {n_modes})"
        )

    def test_reconstructed_frf_shape(self, modal_result, frf_data):
        H_rec = modal_result['reconstructed_frf']
        assert H_rec.shape == frf_data['frf'].shape, (
            f"Shape {H_rec.shape} != original {frf_data['frf'].shape}"
        )

    def test_frf_reconstruction_near_resonances(self, modal_result, frf_data):
        H_rec = modal_result['reconstructed_frf']
        H_orig = frf_data['frf']
        freq = frf_data['freq']
        nat_freq = frf_data['nat_freq_true']
        global_peak = np.max(np.abs(H_orig))

        for fn in nat_freq:
            mask = np.abs(freq - fn) < 20.0
            if not np.any(mask):
                continue
            for loc in range(H_orig.shape[0]):
                orig_mag = np.abs(H_orig[loc, mask])
                rec_mag = np.abs(H_rec[loc, mask])
                peak = np.max(orig_mag)
                # Skip DOFs near mode shape nodes (insignificant response)
                if peak < global_peak * 0.01:
                    continue
                rel_err = np.max(np.abs(orig_mag - rec_mag)) / peak
                assert rel_err < 0.3, (
                    f"Reconstruction error {rel_err:.3f} > 0.3 near "
                    f"{fn:.1f} Hz at location {loc}"
                )


# ── mac ──────────────────────────────────────────────────────────────

class TestMAC:
    def test_automac_diagonal(self, modal_result):
        A = modal_result['modal_constants']
        mac_mat = modal_analysis.mac(A, A)
        assert np.allclose(np.diag(mac_mat), 1.0, atol=1e-10), (
            f"AutoMAC diagonal {np.diag(mac_mat)} not 1.0"
        )

    def test_automac_shape(self, modal_result, frf_data):
        A = modal_result['modal_constants']
        mac_mat = modal_analysis.mac(A, A)
        n = len(frf_data['nat_freq_true'])
        assert mac_mat.shape == (n, n)

    def test_mac_symmetry(self, modal_result):
        A = modal_result['modal_constants']
        mac_mat = modal_analysis.mac(A, A)
        assert np.allclose(mac_mat, mac_mat.T, atol=1e-10)

    def test_mac_range(self, modal_result):
        A = modal_result['modal_constants']
        mac_mat = modal_analysis.mac(A, A)
        assert np.all(mac_mat >= -1e-10), "MAC values must be >= 0"
        assert np.all(mac_mat <= 1.0 + 1e-10), "MAC values must be <= 1"

    def test_mac_1d_input(self, modal_result):
        A = modal_result['modal_constants']
        val = modal_analysis.mac(A[:, 0], A[:, 0])
        assert np.isscalar(val) or val.shape == (1, 1)
        assert np.isclose(np.asarray(val).flat[0], 1.0, atol=1e-10)


# ── complex_to_normal_mode ───────────────────────────────────────────

class TestComplexToNormal:
    def test_output_real(self, modal_result):
        A = modal_result['modal_constants']
        normal = modal_analysis.complex_to_normal_mode(A)
        assert np.allclose(normal.imag, 0, atol=1e-10), (
            "Normal mode must be real-valued"
        )

    def test_output_shape(self, modal_result, frf_data):
        A = modal_result['modal_constants']
        normal = modal_analysis.complex_to_normal_mode(A)
        n_loc = frf_data['frf'].shape[0]
        n_modes = len(frf_data['nat_freq_true'])
        assert normal.shape == (n_loc, n_modes)

    def test_mac_with_complex(self, modal_result):
        A = modal_result['modal_constants']
        normal = modal_analysis.complex_to_normal_mode(A)
        mac_mat = modal_analysis.mac(normal, A)
        for i in range(A.shape[1]):
            assert mac_mat[i, i] > 0.85, (
                f"MAC normal vs complex mode {i} = {mac_mat[i,i]:.3f} < 0.85"
            )
