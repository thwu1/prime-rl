import pytest
import numpy as np
import json
import os
import sqlite3


RESULTS_DIR = '/app/results'


def load_density_matrix(state_dir):
    real_part = np.loadtxt(os.path.join(state_dir, 'density_matrix_real.csv'), delimiter=',')
    imag_part = np.loadtxt(os.path.join(state_dir, 'density_matrix_imag.csv'), delimiter=',')
    return real_part + 1j * imag_part


def load_properties(state_dir):
    with open(os.path.join(state_dir, 'properties.json')) as f:
        return json.load(f)


# ---- Output existence ----

class TestOutputExists:
    @pytest.mark.parametrize("state", ["state_A", "state_B", "state_C"])
    def test_output_directory_exists(self, state):
        assert os.path.isdir(os.path.join(RESULTS_DIR, state)), \
            f"Output directory for {state} not found"

    @pytest.mark.parametrize("state", ["state_A", "state_B", "state_C"])
    def test_density_matrix_files(self, state):
        d = os.path.join(RESULTS_DIR, state)
        assert os.path.isfile(os.path.join(d, 'density_matrix_real.csv')), \
            "density_matrix_real.csv missing"
        assert os.path.isfile(os.path.join(d, 'density_matrix_imag.csv')), \
            "density_matrix_imag.csv missing"

    @pytest.mark.parametrize("state", ["state_A", "state_B", "state_C"])
    def test_properties_file(self, state):
        assert os.path.isfile(os.path.join(RESULTS_DIR, state, 'properties.json')), \
            "properties.json missing"


# ---- Visualization PNGs ----

class TestVisualization:
    @pytest.mark.parametrize("state", ["state_A", "state_B", "state_C"])
    def test_png_exists(self, state):
        png_path = os.path.join(RESULTS_DIR, state, 'density_matrix.png')
        assert os.path.isfile(png_path), f"Visualization PNG missing for {state}"

    @pytest.mark.parametrize("state", ["state_A", "state_B", "state_C"])
    def test_png_not_empty(self, state):
        png_path = os.path.join(RESULTS_DIR, state, 'density_matrix.png')
        size = os.path.getsize(png_path)
        assert size > 1000, f"PNG file too small ({size} bytes), likely empty or corrupt"


# ---- Summary SQLite database ----

class TestSummaryDB:
    SUMMARY_DB = '/app/results/summary.db'

    def test_db_exists(self):
        assert os.path.isfile(self.SUMMARY_DB), "Summary database missing"

    def test_table_exists(self):
        conn = sqlite3.connect(self.SUMMARY_DB)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='state_results'")
        assert cursor.fetchone() is not None, "state_results table missing"
        conn.close()

    def test_all_states_present(self):
        conn = sqlite3.connect(self.SUMMARY_DB)
        cursor = conn.execute("SELECT state_name FROM state_results ORDER BY state_name")
        names = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert names == ['state_A', 'state_B', 'state_C']

    def test_n_qubits_correct(self):
        conn = sqlite3.connect(self.SUMMARY_DB)
        expected = {'state_A': 2, 'state_B': 2, 'state_C': 3}
        for state, exp_nq in expected.items():
            cursor = conn.execute(
                "SELECT n_qubits FROM state_results WHERE state_name=?", (state,))
            nq = cursor.fetchone()[0]
            assert nq == exp_nq, f"Expected {exp_nq} qubits for {state}, got {nq}"
        conn.close()

    def test_purity_values_match_files(self):
        conn = sqlite3.connect(self.SUMMARY_DB)
        for state in ['state_A', 'state_B', 'state_C']:
            cursor = conn.execute(
                "SELECT purity FROM state_results WHERE state_name=?", (state,))
            db_purity = cursor.fetchone()[0]
            props = load_properties(os.path.join(RESULTS_DIR, state))
            assert abs(db_purity - props['purity']) < 0.001, \
                f"DB purity {db_purity} != file purity {props['purity']} for {state}"
        conn.close()

    def test_is_entangled_consistent(self):
        conn = sqlite3.connect(self.SUMMARY_DB)
        for state in ['state_A', 'state_B', 'state_C']:
            cursor = conn.execute(
                "SELECT is_entangled FROM state_results WHERE state_name=?", (state,))
            db_ent = cursor.fetchone()[0]
            props = load_properties(os.path.join(RESULTS_DIR, state))
            expected = 1 if props.get('is_entangled', False) else 0
            assert db_ent == expected, \
                f"DB is_entangled {db_ent} != file {expected} for {state}"
        conn.close()

    def test_extra_json_valid(self):
        conn = sqlite3.connect(self.SUMMARY_DB)
        for state in ['state_A', 'state_B', 'state_C']:
            cursor = conn.execute(
                "SELECT extra_json FROM state_results WHERE state_name=?", (state,))
            extra = cursor.fetchone()[0]
            parsed = json.loads(extra)
            assert isinstance(parsed, dict), "extra_json is not a dict"
        conn.close()


# ---- Physicality of density matrices ----

class TestPhysicality:
    @pytest.mark.parametrize("state,dim", [("state_A", 4), ("state_B", 4), ("state_C", 8)])
    def test_dimensions(self, state, dim):
        rho = load_density_matrix(os.path.join(RESULTS_DIR, state))
        assert rho.shape == (dim, dim), f"Expected {dim}x{dim}, got {rho.shape}"

    @pytest.mark.parametrize("state", ["state_A", "state_B", "state_C"])
    def test_hermiticity(self, state):
        rho = load_density_matrix(os.path.join(RESULTS_DIR, state))
        assert np.allclose(rho, rho.conj().T, atol=1e-5), \
            "Density matrix is not Hermitian"

    @pytest.mark.parametrize("state", ["state_A", "state_B", "state_C"])
    def test_unit_trace(self, state):
        rho = load_density_matrix(os.path.join(RESULTS_DIR, state))
        tr = np.real(np.trace(rho))
        assert abs(tr - 1.0) < 1e-4, f"Trace = {tr}, expected 1.0"

    @pytest.mark.parametrize("state", ["state_A", "state_B", "state_C"])
    def test_positive_semidefinite(self, state):
        rho = load_density_matrix(os.path.join(RESULTS_DIR, state))
        eigenvalues = np.linalg.eigvalsh(rho)
        min_eig = float(np.min(eigenvalues))
        assert min_eig > -1e-5, \
            f"Not positive semidefinite: min eigenvalue = {min_eig}"


# ---- State A: Bell state |Phi+> ----

class TestStateA:
    def _props(self):
        return load_properties(os.path.join(RESULTS_DIR, 'state_A'))

    def _rho(self):
        return load_density_matrix(os.path.join(RESULTS_DIR, 'state_A'))

    def test_required_keys(self):
        p = self._props()
        for key in ['purity', 'concurrence', 'is_entangled', 'entanglement_type']:
            assert key in p, f"Missing required key: {key}"

    def test_purity_near_one(self):
        p = self._props()
        assert abs(p['purity'] - 1.0) < 0.06, \
            f"Purity {p['purity']} not close to 1.0 for pure Bell state"

    def test_high_concurrence(self):
        p = self._props()
        assert p['concurrence'] > 0.90, \
            f"Concurrence {p['concurrence']} too low for maximally entangled state"

    def test_is_entangled(self):
        assert self._props()['is_entangled'] is True

    def test_maximally_entangled(self):
        assert self._props()['entanglement_type'] == 'maximally_entangled'

    def test_fidelity_with_bell_state(self):
        rho = self._rho()
        bell = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
        fidelity = float(np.real(bell.conj() @ rho @ bell))
        assert fidelity > 0.92, \
            f"Fidelity {fidelity} with |Phi+> too low"


# ---- State B: Werner state (partially entangled mixed state) ----

class TestStateB:
    def _props(self):
        return load_properties(os.path.join(RESULTS_DIR, 'state_B'))

    def test_required_keys(self):
        p = self._props()
        for key in ['purity', 'concurrence', 'is_entangled', 'entanglement_type']:
            assert key in p, f"Missing required key: {key}"

    def test_purity(self):
        p = self._props()
        assert abs(p['purity'] - 0.6175) < 0.07, \
            f"Purity {p['purity']} not close to expected 0.6175"

    def test_concurrence(self):
        p = self._props()
        assert abs(p['concurrence'] - 0.55) < 0.12, \
            f"Concurrence {p['concurrence']} not close to expected 0.55"

    def test_is_entangled(self):
        assert self._props()['is_entangled'] is True

    def test_partially_entangled(self):
        assert self._props()['entanglement_type'] == 'partially_entangled'


# ---- State C: GHZ state (3-qubit genuine multipartite entanglement) ----

class TestStateC:
    def _props(self):
        return load_properties(os.path.join(RESULTS_DIR, 'state_C'))

    def _rho(self):
        return load_density_matrix(os.path.join(RESULTS_DIR, 'state_C'))

    def test_required_keys(self):
        p = self._props()
        for key in ['purity', 'is_entangled', 'is_genuine_multipartite_entangled',
                     'min_bipartite_negativity']:
            assert key in p, f"Missing required key: {key}"

    def test_purity_near_one(self):
        p = self._props()
        assert abs(p['purity'] - 1.0) < 0.08, \
            f"Purity {p['purity']} not close to 1.0 for GHZ state"

    def test_is_entangled(self):
        assert self._props()['is_entangled'] is True

    def test_genuine_multipartite_entanglement(self):
        assert self._props()['is_genuine_multipartite_entangled'] is True

    def test_min_bipartite_negativity(self):
        p = self._props()
        assert p['min_bipartite_negativity'] > 0.3, \
            f"Min negativity {p['min_bipartite_negativity']} too low for GHZ"

    def test_fidelity_with_ghz(self):
        rho = self._rho()
        ghz = np.zeros(8, dtype=complex)
        ghz[0] = 1 / np.sqrt(2)
        ghz[7] = 1 / np.sqrt(2)
        fidelity = float(np.real(ghz.conj() @ rho @ ghz))
        assert fidelity > 0.88, \
            f"Fidelity {fidelity} with GHZ state too low"


# ---- Cross-consistency: reported properties must match density matrix ----

class TestConsistency:
    @pytest.mark.parametrize("state", ["state_A", "state_B"])
    def test_purity_consistent(self, state):
        rho = load_density_matrix(os.path.join(RESULTS_DIR, state))
        props = load_properties(os.path.join(RESULTS_DIR, state))
        computed = float(np.real(np.trace(rho @ rho)))
        assert abs(computed - props['purity']) < 0.01, \
            f"Reported purity {props['purity']} != computed {computed}"

    @pytest.mark.parametrize("state", ["state_A", "state_B"])
    def test_concurrence_consistent(self, state):
        rho = load_density_matrix(os.path.join(RESULTS_DIR, state))
        props = load_properties(os.path.join(RESULTS_DIR, state))
        sigma_y = np.array([[0, -1j], [1j, 0]])
        YY = np.kron(sigma_y, sigma_y)
        rho_tilde = YY @ rho.conj() @ YY
        product = rho @ rho_tilde
        eigenvalues = np.linalg.eigvals(product)
        lambdas = np.sort(np.sqrt(np.maximum(np.real(eigenvalues), 0)))[::-1]
        computed = float(max(0, lambdas[0] - lambdas[1] - lambdas[2] - lambdas[3]))
        assert abs(computed - props['concurrence']) < 0.02, \
            f"Reported concurrence {props['concurrence']} != computed {computed}"

    def test_state_c_purity_consistent(self):
        rho = load_density_matrix(os.path.join(RESULTS_DIR, 'state_C'))
        props = load_properties(os.path.join(RESULTS_DIR, 'state_C'))
        computed = float(np.real(np.trace(rho @ rho)))
        assert abs(computed - props['purity']) < 0.01, \
            f"Reported purity {props['purity']} != computed {computed}"
