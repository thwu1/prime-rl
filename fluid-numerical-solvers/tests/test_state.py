"""
Tests for numerical solver implementations.

"""

import sys
import math
import pytest

sys.path.insert(0, '/app')

from sparse_matrix import SparseMatrix
from cg_solver import cg, pcg
from preconditioner import NullPreconditioner, DiagonalPreconditioner, ICPreconditioner
from fmm_solver import reinitialize_sdf
from poisson import build_laplacian_2d


# --------------- Helper ---------------

class DenseMatrix:
    """Simple dense matrix wrapper for small test systems."""
    def __init__(self, data):
        self.data = data
        self.n = len(data)

    def matvec(self, x):
        n = self.n
        return [sum(self.data[i][j] * x[j] for j in range(n)) for i in range(n)]


def _build_weighted_tridiag(n):
    """Build a tridiagonal SPD matrix with varying diagonal."""
    entries = []
    for i in range(n):
        scale = 1.0 + 40.0 * (float(i) / n) ** 2
        entries.append((i, i, 2.0 * scale))
        if i > 0:
            entries.append((i, i - 1, -1.0))
        if i < n - 1:
            entries.append((i, i + 1, -1.0))
    return SparseMatrix.from_entries(n, entries)


# ==================== LAPLACIAN ASSEMBLY ====================

class TestLaplacian:

    def test_dimension(self):
        A = build_laplacian_2d(10, 8, 1.0)
        assert A.n == 80

    def test_diagonal_values(self):
        nx, ny, dx = 5, 5, 0.5
        A = build_laplacian_2d(nx, ny, dx)
        expected = 4.0 / (dx * dx)
        for i in range(nx * ny):
            assert A.get(i, i) == pytest.approx(expected, rel=1e-12)

    def test_off_diagonal_interior(self):
        nx, ny, dx = 6, 6, 1.0
        A = build_laplacian_2d(nx, ny, dx)
        row = 3 * nx + 3
        assert A.get(row, row) == pytest.approx(4.0, rel=1e-12)
        assert A.get(row, row - 1) == pytest.approx(-1.0, rel=1e-12)
        assert A.get(row, row + 1) == pytest.approx(-1.0, rel=1e-12)
        assert A.get(row, row - nx) == pytest.approx(-1.0, rel=1e-12)
        assert A.get(row, row + nx) == pytest.approx(-1.0, rel=1e-12)

    def test_symmetry(self):
        nx, ny = 7, 5
        A = build_laplacian_2d(nx, ny, 1.0)
        n = nx * ny
        for i in range(n):
            for idx in range(A.row_ptr[i], A.row_ptr[i + 1]):
                j = A.col_idx[idx]
                v = A.values[idx]
                assert A.get(j, i) == pytest.approx(v, rel=1e-12), \
                    f"A[{i}][{j}]={v} != A[{j}][{i}]={A.get(j, i)}"

    def test_corner_nnz(self):
        nx, ny = 4, 4
        A = build_laplacian_2d(nx, ny, 1.0)
        nnz_row0 = A.row_ptr[1] - A.row_ptr[0]
        assert nnz_row0 == 3  # diagonal + right + up


# ==================== CG SOLVER ====================

class TestCG:

    def test_zero_iterations(self):
        """Zero iterations: return x0 with correct initial residual."""
        A = DenseMatrix([[4.0, 1.0], [1.0, 3.0]])
        b = [1.0, 2.0]
        x0 = [0.0, 0.0]
        x, iters, res = cg(A, b, x0, 0, 0.0)
        assert x[0] == pytest.approx(0.0, abs=1e-15)
        assert x[1] == pytest.approx(0.0, abs=1e-15)
        assert res == pytest.approx(math.sqrt(5.0), rel=1e-12)
        assert iters == 0

    def test_2x2_exact(self):
        """CG solves 2x2 SPD system in at most 2 iterations."""
        A = DenseMatrix([[4.0, 1.0], [1.0, 3.0]])
        b = [1.0, 2.0]
        x0 = [0.0, 0.0]
        x, iters, res = cg(A, b, x0, 10, 0.0)
        assert x[0] == pytest.approx(1.0 / 11.0, rel=1e-10)
        assert x[1] == pytest.approx(7.0 / 11.0, rel=1e-10)
        assert res < 1e-12
        assert iters <= 3

    def test_laplacian_system(self):
        """CG converges on an 8x8 Laplacian with known solution."""
        nx, ny = 8, 8
        A = build_laplacian_2d(nx, ny, 1.0)
        n = nx * ny
        u_true = [0.0] * n
        for j in range(ny):
            for i in range(nx):
                u_true[j * nx + i] = (i + 1) * (nx - i) * (j + 1) * (ny - j) / (nx * ny)
        b = A.matvec(u_true)
        x0 = [0.0] * n
        x, iters, res = cg(A, b, x0, 500, 1e-10)
        error = math.sqrt(sum((x[k] - u_true[k]) ** 2 for k in range(n)))
        assert error < 1e-6
        assert res < 1e-8

    def test_single_iteration_reduces_residual(self):
        """One CG iteration must reduce the residual from initial."""
        A = DenseMatrix([[4.0, 1.0], [1.0, 3.0]])
        b = [1.0, 2.0]
        x0 = [0.0, 0.0]
        _, _, res0 = cg(A, b, x0, 0, 0.0)
        _, _, res1 = cg(A, b, x0, 1, 0.0)
        assert res1 < res0


# ==================== PCG SOLVER ====================

class TestPCG:

    def test_null_precond_matches_cg(self):
        A = DenseMatrix([[4.0, 1.0], [1.0, 3.0]])
        b = [1.0, 2.0]
        x0 = [0.0, 0.0]
        precond = NullPreconditioner()
        x, iters, res = pcg(A, b, x0, 10, 0.0, precond)
        assert x[0] == pytest.approx(1.0 / 11.0, rel=1e-10)
        assert x[1] == pytest.approx(7.0 / 11.0, rel=1e-10)

    def test_diagonal_precond_on_weighted_system(self):
        """Diagonal preconditioner should help on systems with varying diagonal."""
        n = 80
        A = _build_weighted_tridiag(n)
        u_true = [math.sin(math.pi * i / n) for i in range(n)]
        b = A.matvec(u_true)
        x0 = [0.0] * n

        _, cg_iters, _ = cg(A, b, x0, 1000, 1e-10)

        dp = DiagonalPreconditioner()
        dp.build(A)
        _, pcg_iters, pcg_res = pcg(A, b, x0, 1000, 1e-10, dp)

        assert pcg_res < 1e-8
        assert pcg_iters < cg_iters

    def test_pcg_converges_on_laplacian(self):
        """PCG with diagonal preconditioner should converge on Laplacian."""
        nx, ny = 10, 10
        A = build_laplacian_2d(nx, ny, 1.0)
        n = nx * ny
        u_true = [0.0] * n
        for j in range(ny):
            for i in range(nx):
                u_true[j * nx + i] = math.sin(math.pi * i / nx) \
                                   * math.sin(math.pi * j / ny)
        b = A.matvec(u_true)
        x0 = [0.0] * n

        dp = DiagonalPreconditioner()
        dp.build(A)
        x, iters, res = pcg(A, b, x0, 500, 1e-10, dp)

        error = math.sqrt(sum((x[k] - u_true[k]) ** 2 for k in range(n)))
        assert error < 1e-6
        assert res < 1e-8


# ==================== IC PRECONDITIONER ====================

class TestIC:

    def test_builds_on_laplacian(self):
        A = build_laplacian_2d(5, 5, 1.0)
        ic = ICPreconditioner()
        ic.build(A)

    def test_diagonal_matrix(self):
        """IC(0) of a diagonal matrix should invert it exactly."""
        n = 4
        entries = [(i, i, float(i + 2)) for i in range(n)]
        A = SparseMatrix.from_entries(n, entries)
        ic = ICPreconditioner()
        ic.build(A)
        r = [1.0, 2.0, 3.0, 4.0]
        s = ic.solve(r)
        for i in range(n):
            assert s[i] == pytest.approx(r[i] / (i + 2), rel=1e-10)

    def test_pcg_with_ic_converges(self):
        """PCG + IC(0) should converge on a 12x12 Laplacian system."""
        nx, ny = 12, 12
        A = build_laplacian_2d(nx, ny, 1.0)
        n = nx * ny
        u_true = [0.0] * n
        for j in range(ny):
            for i in range(nx):
                u_true[j * nx + i] = (i + 1) * (nx - i) * (j + 1) * (ny - j) / 1000.0
        b = A.matvec(u_true)
        x0 = [0.0] * n
        ic = ICPreconditioner()
        ic.build(A)
        x, iters, res = pcg(A, b, x0, 500, 1e-10, ic)
        error = math.sqrt(sum((x[k] - u_true[k]) ** 2 for k in range(n)))
        assert error < 1e-5
        assert res < 1e-8

    def test_ic_fewer_iters_than_cg(self):
        """PCG with IC(0) should converge in fewer iterations than plain CG."""
        nx, ny = 14, 14
        A = build_laplacian_2d(nx, ny, 1.0)
        n = nx * ny
        u_true = [0.0] * n
        for j in range(ny):
            for i in range(nx):
                u_true[j * nx + i] = math.sin(math.pi * i / nx) \
                                   * math.sin(math.pi * j / ny)
        b = A.matvec(u_true)
        x0 = [0.0] * n

        _, cg_iters, _ = cg(A, b, x0, 1000, 1e-10)

        ic_p = ICPreconditioner()
        ic_p.build(A)
        _, ic_iters, ic_res = pcg(A, b, x0, 1000, 1e-10, ic_p)

        assert ic_res < 1e-8
        assert ic_iters < cg_iters


# ==================== FMM ====================

class TestFMM:

    def test_circle_reinitialization(self):
        """FMM should reinitialize a circular SDF within tolerance."""
        width, height = 40, 30
        cx, cy, radius = 20.0, 15.0, 8.0
        phi = [[0.0] * width for _ in range(height)]
        for j in range(height):
            for i in range(width):
                phi[j][i] = math.sqrt((i - cx) ** 2 + (j - cy) ** 2) - radius

        result = reinitialize_sdf(phi, width, height, dx=1.0)

        max_err = 0.0
        for j in range(2, height - 2):
            for i in range(2, width - 2):
                max_err = max(max_err, abs(result[j][i] - phi[j][i]))
        assert max_err < 1.5, f"Max FMM error {max_err:.4f} exceeds 1.5"

    def test_distorted_sdf_fixed(self):
        """FMM should fix a distorted (non-unit-gradient) SDF."""
        width, height = 30, 30
        cx, cy, radius = 15.0, 15.0, 7.0

        phi_exact = [[0.0] * width for _ in range(height)]
        phi_distorted = [[0.0] * width for _ in range(height)]
        for j in range(height):
            for i in range(width):
                d = math.sqrt((i - cx) ** 2 + (j - cy) ** 2) - radius
                phi_exact[j][i] = d
                phi_distorted[j][i] = 3.0 * d  # gradient magnitude 3

        result = reinitialize_sdf(phi_distorted, width, height, dx=1.0)

        err_distorted = 0.0
        err_reinit = 0.0
        count = 0
        for j in range(3, height - 3):
            for i in range(3, width - 3):
                if abs(phi_exact[j][i]) < 5.0:
                    count += 1
                    err_distorted += abs(phi_distorted[j][i] - phi_exact[j][i])
                    err_reinit += abs(result[j][i] - phi_exact[j][i])

        assert count > 0
        assert err_reinit < err_distorted, \
            "Reinitialized SDF should be closer to exact than the distorted input"

    def test_preserves_sign(self):
        """FMM must preserve the sign of the SDF."""
        width, height = 30, 30
        cx, cy, radius = 15.0, 15.0, 8.0
        phi = [[0.0] * width for _ in range(height)]
        for j in range(height):
            for i in range(width):
                phi[j][i] = math.sqrt((i - cx) ** 2 + (j - cy) ** 2) - radius

        result = reinitialize_sdf(phi, width, height, dx=1.0)

        for j in range(height):
            for i in range(width):
                if abs(phi[j][i]) > 2.0:
                    if phi[j][i] > 0:
                        assert result[j][i] > 0, f"Sign flip at ({i},{j})"
                    else:
                        assert result[j][i] < 0, f"Sign flip at ({i},{j})"

    def test_zero_level_set_near_zero(self):
        """Points near the zero level set should have small distance."""
        width, height = 30, 30
        cx, cy, radius = 15.0, 15.0, 8.0
        phi = [[0.0] * width for _ in range(height)]
        for j in range(height):
            for i in range(width):
                phi[j][i] = math.sqrt((i - cx) ** 2 + (j - cy) ** 2) - radius

        result = reinitialize_sdf(phi, width, height, dx=1.0)

        for j in range(height):
            for i in range(width):
                if abs(phi[j][i]) < 0.5:
                    assert abs(result[j][i]) < 1.5, \
                        f"|result[{j}][{i}]| = {abs(result[j][i]):.3f} near zero level set"
