"""
Tests for SP2 density matrix solver.

"""
import sys
import json
import numpy as np
from scipy.sparse import diags as spdiags
from scipy.sparse.linalg import norm as spnorm

sys.path.insert(0, '/app')
from hamiltonian import generate_hamiltonian
from baseline_dense import dense_sp2, gershgorin_bounds_dense
import sp2_solver


def load_config():
    with open('/app/config.json') as f:
        return json.load(f)


def _make_hamiltonian(cfg):
    return generate_hamiltonian(
        cfg['n_atoms'], seed=cfg['seed'],
        n_chains=cfg['n_chains'], chain_coupling=cfg['chain_coupling']
    )


class TestGershgorinBounds:
    def test_bounds_contain_eigenvalues(self):
        """Gershgorin bounds must contain all eigenvalues."""
        cfg = load_config()
        H = _make_hamiltonian(cfg)
        emin, emax = sp2_solver.gershgorin_bounds(H)

        actual_evals = np.linalg.eigvalsh(H.toarray())

        assert emin <= actual_evals[0] + 1e-10, \
            f"Lower bound {emin} exceeds smallest eigenvalue {actual_evals[0]}"
        assert emax >= actual_evals[-1] - 1e-10, \
            f"Upper bound {emax} below largest eigenvalue {actual_evals[-1]}"

    def test_bounds_match_dense(self):
        """Sparse Gershgorin bounds must match dense computation."""
        cfg = load_config()
        H = _make_hamiltonian(cfg)
        emin_sp, emax_sp = sp2_solver.gershgorin_bounds(H)
        emin_dn, emax_dn = gershgorin_bounds_dense(H.toarray())

        assert abs(emin_sp - emin_dn) < 1e-10, \
            f"Lower bound mismatch: sparse={emin_sp}, dense={emin_dn}"
        assert abs(emax_sp - emax_dn) < 1e-10, \
            f"Upper bound mismatch: sparse={emax_sp}, dense={emax_dn}"


class TestSparseSP2:
    def test_idempotency(self):
        """Density matrix must be idempotent: ||D^2 - D||_F < 1e-8."""
        cfg = load_config()
        H = _make_hamiltonian(cfg)
        D, n_iter, idem_err = sp2_solver.sparse_sp2(
            H, cfg['n_occupied'],
            tol=cfg['tolerance'],
            trunc_thresh=cfg['truncation_threshold']
        )

        D2 = D @ D
        actual_err = spnorm(D2 - D, 'fro')
        assert actual_err < 1e-8, \
            f"Idempotency error {actual_err} exceeds threshold 1e-8"

    def test_trace(self):
        """trace(D) must equal number of occupied states."""
        cfg = load_config()
        H = _make_hamiltonian(cfg)
        D, n_iter, idem_err = sp2_solver.sparse_sp2(
            H, cfg['n_occupied'],
            tol=cfg['tolerance'],
            trunc_thresh=cfg['truncation_threshold']
        )

        tr = D.diagonal().sum()
        assert abs(tr - cfg['n_occupied']) < 0.05, \
            f"trace(D) = {tr}, expected {cfg['n_occupied']}"

    def test_symmetry(self):
        """Density matrix must be symmetric."""
        cfg = load_config()
        H = _make_hamiltonian(cfg)
        D, _, _ = sp2_solver.sparse_sp2(
            H, cfg['n_occupied'],
            tol=cfg['tolerance'],
            trunc_thresh=cfg['truncation_threshold']
        )

        diff = D - D.T
        asym_err = spnorm(diff, 'fro')
        assert asym_err < 1e-10, \
            f"Symmetry error {asym_err} exceeds threshold"

    def test_convergence(self):
        """SP2 must converge within reasonable iterations."""
        cfg = load_config()
        H = _make_hamiltonian(cfg)
        D, n_iter, idem_err = sp2_solver.sparse_sp2(
            H, cfg['n_occupied'],
            tol=cfg['tolerance'],
            trunc_thresh=cfg['truncation_threshold']
        )

        assert n_iter < 100, f"SP2 did not converge: {n_iter} iterations"
        assert idem_err < cfg['tolerance'], \
            f"Final idempotency error {idem_err} exceeds tolerance"

    def test_matches_dense_reference(self):
        """Sparse SP2 result must approximate dense reference."""
        n_small = 150
        n_occ_small = 38
        H = generate_hamiltonian(n_small, seed=99, n_chains=3,
                                 chain_coupling=0.15)

        D_sparse, _, _ = sp2_solver.sparse_sp2(
            H, n_occ_small, tol=1e-10, trunc_thresh=1e-8
        )
        D_dense = dense_sp2(H.toarray(), n_occ_small, tol=1e-10)

        diff = np.linalg.norm(D_sparse.toarray() - D_dense, 'fro')
        assert diff < 1.0, \
            f"Sparse-dense Frobenius norm difference {diff} too large"

    def test_eigenvalue_spectrum(self):
        """Density matrix eigenvalues must cluster near 0 or 1."""
        n_small = 150
        n_occ_small = 38
        H = generate_hamiltonian(n_small, seed=99, n_chains=3,
                                 chain_coupling=0.15)

        D, _, _ = sp2_solver.sparse_sp2(
            H, n_occ_small, tol=1e-10, trunc_thresh=1e-8
        )

        evals = np.linalg.eigvalsh(D.toarray())
        dist_to_01 = np.minimum(np.abs(evals), np.abs(evals - 1))
        max_dist = np.max(dist_to_01)
        assert max_dist < 1e-4, \
            f"Max eigenvalue distance from {{0,1}} is {max_dist}"


class TestCommVolume:
    def test_single_block_zero_comm(self):
        """Single block partition should have zero communication."""
        cfg = load_config()
        H = _make_hamiltonian(cfg)

        partition = [0, cfg['n_atoms']]
        vol = sp2_solver.compute_comm_volume(H, partition)
        assert vol == 0, f"Single block should have zero comm, got {vol}"

    def test_diagonal_matrix_zero_comm(self):
        """Diagonal matrix should have zero communication for any partition."""
        H_diag = spdiags([1.0] * 100, 0, format='csr')

        partition = [0, 25, 50, 75, 100]
        vol = sp2_solver.compute_comm_volume(H_diag, partition)
        assert vol == 0, f"Diagonal matrix should have zero comm, got {vol}"

    def test_known_tridiagonal(self):
        """Communication volume for a known tridiagonal case."""
        from scipy.sparse import csr_matrix as csr
        rows = [0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5]
        cols = [0, 1, 0, 1, 2, 1, 2, 3, 2, 3, 4, 3, 4, 5, 4, 5]
        vals = [1.0] * 16
        H = csr((vals, (rows, cols)), shape=(6, 6))

        # Partition [0,2), [2,4), [4,6)
        partition = [0, 2, 4, 6]
        vol = sp2_solver.compute_comm_volume(H, partition)
        # Block 0: non-local cols {2} -> 1
        # Block 1: non-local cols {1, 4} -> 2
        # Block 2: non-local cols {3} -> 1
        assert vol == 4, f"Expected comm volume 4, got {vol}"

    def test_comm_nonnegative(self):
        """Communication volume must be non-negative."""
        cfg = load_config()
        H = _make_hamiltonian(cfg)
        n = cfg['n_atoms']
        nb = cfg['n_blocks']

        partition = [i * n // nb for i in range(nb)] + [n]
        vol = sp2_solver.compute_comm_volume(H, partition)

        assert isinstance(vol, (int, np.integer)), \
            f"Comm volume should be integer, got {type(vol)}"
        assert vol >= 0, "Communication volume cannot be negative"

    def test_comm_increases_with_blocks(self):
        """More blocks should generally not decrease communication."""
        cfg = load_config()
        H = _make_hamiltonian(cfg)
        n = cfg['n_atoms']

        vol_2 = sp2_solver.compute_comm_volume(H, [0, n // 2, n])
        vol_4 = sp2_solver.compute_comm_volume(
            H, [i * n // 4 for i in range(4)] + [n])

        assert vol_4 >= vol_2, \
            f"4-block volume ({vol_4}) should be >= 2-block ({vol_2})"


class TestOptimalPartition:
    def test_partition_validity(self):
        """Optimal partition must be well-formed."""
        cfg = load_config()
        H = _make_hamiltonian(cfg)

        partition = sp2_solver.optimal_partition(H, cfg['n_blocks'])

        assert len(partition) == cfg['n_blocks'] + 1, \
            f"Expected {cfg['n_blocks']+1} boundaries, got {len(partition)}"
        assert partition[0] == 0, \
            f"Partition must start at 0, got {partition[0]}"
        assert partition[-1] == cfg['n_atoms'], \
            f"Partition must end at {cfg['n_atoms']}, got {partition[-1]}"

        for i in range(len(partition) - 1):
            assert partition[i] < partition[i + 1], \
                f"Partition not strictly increasing at index {i}: " \
                f"{partition[i]} >= {partition[i+1]}"

    def test_load_balance(self):
        """Optimal partition must maintain load balance."""
        cfg = load_config()
        H = _make_hamiltonian(cfg)

        partition = sp2_solver.optimal_partition(H, cfg['n_blocks'])

        total_nnz = H.nnz
        max_allowed = 1.5 * total_nnz / cfg['n_blocks']

        for k in range(cfg['n_blocks']):
            start, end = partition[k], partition[k + 1]
            block_nnz = H[start:end, :].nnz
            assert block_nnz <= max_allowed, \
                f"Block {k} has {block_nnz} nnz, max allowed {max_allowed:.0f}"

    def test_improves_over_uniform(self):
        """Optimal partition must not exceed uniform partition comm volume."""
        cfg = load_config()
        H = _make_hamiltonian(cfg)
        n = cfg['n_atoms']
        nb = cfg['n_blocks']

        uniform = [i * n // nb for i in range(nb)] + [n]
        optimal = sp2_solver.optimal_partition(H, nb)

        vol_uniform = sp2_solver.compute_comm_volume(H, uniform)
        vol_optimal = sp2_solver.compute_comm_volume(H, optimal)

        assert vol_optimal <= vol_uniform, \
            f"Optimal ({vol_optimal}) should not exceed uniform ({vol_uniform})"
