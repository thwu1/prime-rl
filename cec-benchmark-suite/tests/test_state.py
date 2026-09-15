
import pytest
import numpy as np
import json
import sys
import os

sys.path.insert(0, '/app')

D = 10


class TestResultsStructure:
    """Verify results.json exists and has correct structure."""

    def test_results_file_exists(self):
        assert os.path.isfile('/app/results.json'), "results.json not found"

    def test_results_structure(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        for i in range(1, 13):
            fname = f'F{i}'
            assert fname in results, f"{fname} missing from results"
            assert 'optimum' in results[fname], f"{fname} missing 'optimum'"
            assert 'test_points' in results[fname], f"{fname} missing 'test_points'"
            assert len(results[fname]['test_points']) == 5, \
                f"{fname} should have 5 test points"
        assert 'constraints' in results, "constraints missing"
        for fname in ['F1', 'F3', 'F9']:
            assert fname in results['constraints'], f"constraint {fname} missing"
            assert 'violations' in results['constraints'][fname]
            assert len(results['constraints'][fname]['violations']) == 5


class TestOptimumValues:
    """F(optimum) should equal the bias for all 12 functions."""

    def test_F1_to_F8_optima(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        biases = [100, 200, 300, 400, 500, 600, 700, 800]
        for i in range(8):
            fname = f'F{i+1}'
            val = results[fname]['optimum']
            assert abs(val - biases[i]) < 1e-6, \
                f"{fname} optimum should be {biases[i]}, got {val}"

    def test_F9_optimum(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert abs(results['F9']['optimum'] - 900) < 1e-6

    def test_F10_optimum(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert abs(results['F10']['optimum'] - 1000) < 1e-6

    def test_F11_optimum(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert abs(results['F11']['optimum'] - 1100) < 1e-6

    def test_F12_optimum(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert abs(results['F12']['optimum'] - 1200) < 1e-6


class TestValuesAboveBias:
    """All function values at test points must be >= bias."""

    def test_all_above_bias(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        biases = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200]
        for i in range(12):
            fname = f'F{i+1}'
            for j, v in enumerate(results[fname]['test_points']):
                assert v >= biases[i] - 1e-6, \
                    f"{fname} test point {j}: value {v} below bias {biases[i]}"


class TestAnalyticalValues:
    """Verify function values at analytically known points."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        import benchmark as bm
        self.bm = bm
        self.shifts = np.load('/app/data/shifts.npy')
        self.rotations = np.load('/app/data/rotations.npy')

    def _unit_vec(self, idx):
        e = np.zeros(D)
        e[idx] = 1.0
        return e

    def test_sphere_unit_displacement(self):
        """F1 at optimum + M^T @ e_0: sphere(e_0) = 1, so F1 = 101."""
        e0 = self._unit_vec(0)
        x = self.shifts[0] + self.rotations[0].T @ e0
        val = self.bm.F1(x)
        assert abs(val - 101.0) < 1e-6, f"Expected 101, got {val}"

    def test_sphere_scaled_displacement(self):
        """F1 at optimum + 2*M^T @ e_0: sphere(2*e_0) = 4, so F1 = 104."""
        e0 = self._unit_vec(0)
        x = self.shifts[0] + 2.0 * self.rotations[0].T @ e0
        val = self.bm.F1(x)
        assert abs(val - 104.0) < 1e-6, f"Expected 104, got {val}"

    def test_elliptic_first_component(self):
        """F2 at opt + M^T @ e_0: elliptic(e_0) = 10^0 = 1, so F2 = 201."""
        e0 = self._unit_vec(0)
        x = self.shifts[1] + self.rotations[1].T @ e0
        val = self.bm.F2(x)
        assert abs(val - 201.0) < 1e-6, f"Expected 201, got {val}"

    def test_elliptic_last_component(self):
        """F2 at opt + M^T @ e_{D-1}: elliptic(e_{D-1}) = 10^6, so F2 = 200 + 1e6."""
        eD = self._unit_vec(D - 1)
        x = self.shifts[1] + self.rotations[1].T @ eD
        val = self.bm.F2(x)
        expected = 200.0 + 1e6
        assert abs(val - expected) < 1.0, f"Expected {expected}, got {val}"

    def test_bent_cigar_first_component(self):
        """F3 at opt + M^T @ e_0: bent_cigar(e_0) = 1, so F3 = 301."""
        e0 = self._unit_vec(0)
        x = self.shifts[2] + self.rotations[2].T @ e0
        val = self.bm.F3(x)
        assert abs(val - 301.0) < 1e-6, f"Expected 301, got {val}"

    def test_bent_cigar_second_component(self):
        """F3 at opt + M^T @ e_1: bent_cigar(e_1) = 10^6, so F3 = 300 + 1e6."""
        e1 = self._unit_vec(1)
        x = self.shifts[2] + self.rotations[2].T @ e1
        val = self.bm.F3(x)
        expected = 300.0 + 1e6
        assert abs(val - expected) < 1.0, f"Expected {expected}, got {val}"

    def test_discus_first_component(self):
        """F4 at opt + M^T @ e_0: discus(e_0) = 10^6, so F4 = 400 + 1e6."""
        e0 = self._unit_vec(0)
        x = self.shifts[3] + self.rotations[3].T @ e0
        val = self.bm.F4(x)
        expected = 400.0 + 1e6
        assert abs(val - expected) < 1.0, f"Expected {expected}, got {val}"

    def test_discus_second_component(self):
        """F4 at opt + M^T @ e_1: discus(e_1) = 1, so F4 = 401."""
        e1 = self._unit_vec(1)
        x = self.shifts[3] + self.rotations[3].T @ e1
        val = self.bm.F4(x)
        assert abs(val - 401.0) < 1e-6, f"Expected 401, got {val}"

    def test_rosenbrock_unit_displacement(self):
        """F5 at opt + M^T @ e_0: z=e_0, z_hat=[2,1,...,1],
        rosenbrock = 100*(4-1)^2 + 1 = 901, F5 = 1401."""
        e0 = self._unit_vec(0)
        x = self.shifts[4] + self.rotations[4].T @ e0
        val = self.bm.F5(x)
        assert abs(val - 1401.0) < 1e-4, f"Expected 1401, got {val}"

    def test_ackley_at_optimum(self):
        """F6 at optimum should be 600."""
        val = self.bm.F6(self.shifts[5])
        assert abs(val - 600.0) < 1e-6, f"Expected 600, got {val}"

    def test_ackley_unit_displacement(self):
        """F6 at opt + M^T @ e_0: ackley(e_0) = 20*(1-exp(-0.2*sqrt(0.1)))."""
        e0 = self._unit_vec(0)
        x = self.shifts[5] + self.rotations[5].T @ e0
        val = self.bm.F6(x)
        expected_ackley = 20.0 * (1.0 - np.exp(-0.2 * np.sqrt(1.0 / D)))
        expected = expected_ackley + 600.0
        assert abs(val - expected) < 1e-6, f"Expected {expected}, got {val}"

    def test_rastrigin_unit_displacement(self):
        """F7 at opt + M^T @ e_0: rastrigin(e_0) = 1, F7 = 701."""
        e0 = self._unit_vec(0)
        x = self.shifts[6] + self.rotations[6].T @ e0
        val = self.bm.F7(x)
        assert abs(val - 701.0) < 1e-6, f"Expected 701, got {val}"

    def test_griewank_unit_displacement(self):
        """F8 at opt + M^T @ e_0: griewank(e_0) = 1/4000 - cos(1) + 1."""
        e0 = self._unit_vec(0)
        x = self.shifts[7] + self.rotations[7].T @ e0
        val = self.bm.F8(x)
        expected_griewank = 1.0 / 4000.0 - np.cos(1.0) + 1.0
        expected = expected_griewank + 800.0
        assert abs(val - expected) < 1e-6, f"Expected {expected}, got {val}"


class TestEllipticConditionNumber:
    """Verify elliptic function has correct 10^6 condition number,
    distinguishing the (n-1) denominator from the wrong n denominator."""

    def test_condition_ratio(self):
        """Ratio of F2 values at e_{D-1} vs e_0 displacement must be 10^6."""
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        rotations = np.load('/app/data/rotations.npy')

        e0 = np.zeros(D)
        e0[0] = 1.0
        eD = np.zeros(D)
        eD[D - 1] = 1.0

        x0 = shifts[1] + rotations[1].T @ e0
        xD = shifts[1] + rotations[1].T @ eD

        v0 = bm.F2(x0) - 200.0
        vD = bm.F2(xD) - 200.0

        ratio = vD / v0
        assert abs(ratio - 1e6) < 10.0, \
            f"Elliptic condition ratio should be 10^6, got {ratio}"

    def test_middle_component_coefficient(self):
        """F2 at opt + M^T @ e_4: coefficient should be 10^(6*4/9)."""
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        rotations = np.load('/app/data/rotations.npy')

        e4 = np.zeros(D)
        e4[4] = 1.0
        x = shifts[1] + rotations[1].T @ e4

        val = bm.F2(x) - 200.0
        expected = 10.0 ** (6.0 * 4 / (D - 1))
        assert abs(val - expected) < 0.01, \
            f"Elliptic middle coefficient: expected {expected:.4f}, got {val:.4f}"


class TestSphereScaling:
    """Sphere function should scale quadratically."""

    def test_quadratic_scaling(self):
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        rotations = np.load('/app/data/rotations.npy')
        e0 = np.zeros(D)
        e0[0] = 1.0

        for scale in [0.5, 1.0, 2.0, 5.0, 10.0]:
            x = shifts[0] + scale * rotations[0].T @ e0
            val = bm.F1(x) - 100.0
            expected = scale ** 2
            assert abs(val - expected) < 1e-6, \
                f"scale={scale}: expected {expected}, got {val}"


class TestRotationOrthogonality:
    """All rotation matrices must be orthogonal."""

    def test_rotations_orthogonal(self):
        rotations = np.load('/app/data/rotations.npy')
        for i in range(10):
            M = rotations[i]
            product = M @ M.T
            assert np.allclose(product, np.eye(D), atol=1e-10), \
                f"Rotation {i} is not orthogonal"

    def test_comp_rotations_11_orthogonal(self):
        rots = np.load('/app/data/comp_rotations_11.npy')
        for i in range(3):
            product = rots[i] @ rots[i].T
            assert np.allclose(product, np.eye(D), atol=1e-10)

    def test_comp_rotations_12_orthogonal(self):
        rots = np.load('/app/data/comp_rotations_12.npy')
        for i in range(5):
            product = rots[i] @ rots[i].T
            assert np.allclose(product, np.eye(D), atol=1e-10)


class TestBenchmarkImportable:
    """The benchmark module must be importable with all functions callable."""

    def test_all_functions_callable(self):
        import benchmark as bm
        funcs = [bm.F1, bm.F2, bm.F3, bm.F4, bm.F5, bm.F6,
                 bm.F7, bm.F8, bm.F9, bm.F10, bm.F11, bm.F12]
        for f in funcs:
            assert callable(f), f"{f.__name__} is not callable"

    def test_constraint_functions_callable(self):
        import benchmark as bm
        for name in ['constraint_violation_F1', 'constraint_violation_F3',
                      'constraint_violation_F9']:
            func = getattr(bm, name, None)
            assert func is not None and callable(func), f"{name} not callable"


class TestCompositionDominance:
    """At each component optimum, the composition function should be
    dominated by that component."""

    def test_F11_at_first_optimum(self):
        import benchmark as bm
        comp_optima_11 = np.load('/app/data/comp_optima_11.npy')
        val = bm.F11(comp_optima_11[0])
        assert abs(val - 1100.0) < 1e-6, \
            f"F11 at first optimum: expected 1100, got {val}"

    def test_F11_near_second_optimum(self):
        import benchmark as bm
        comp_optima_11 = np.load('/app/data/comp_optima_11.npy')
        x = comp_optima_11[1] + 1e-10 * np.ones(D)
        val = bm.F11(x)
        assert abs(val - 1200.0) < 0.1, \
            f"F11 near second optimum: expected ~1200, got {val}"

    def test_F11_near_third_optimum(self):
        import benchmark as bm
        comp_optima_11 = np.load('/app/data/comp_optima_11.npy')
        x = comp_optima_11[2] + 1e-10 * np.ones(D)
        val = bm.F11(x)
        assert abs(val - 1300.0) < 0.1, \
            f"F11 near third optimum: expected ~1300, got {val}"

    def test_F12_at_first_optimum(self):
        import benchmark as bm
        comp_optima_12 = np.load('/app/data/comp_optima_12.npy')
        val = bm.F12(comp_optima_12[0])
        assert abs(val - 1200.0) < 1e-6, \
            f"F12 at first optimum: expected 1200, got {val}"

    def test_F12_near_second_optimum(self):
        import benchmark as bm
        comp_optima_12 = np.load('/app/data/comp_optima_12.npy')
        x = comp_optima_12[1] + 1e-10 * np.ones(D)
        val = bm.F12(x)
        assert abs(val - 1300.0) < 0.1, \
            f"F12 near second optimum: expected ~1300, got {val}"

    def test_F12_near_third_optimum(self):
        """Third component (discus, lambda=10, bias=200): F12 ~ 1400."""
        import benchmark as bm
        comp_optima_12 = np.load('/app/data/comp_optima_12.npy')
        x = comp_optima_12[2] + 1e-10 * np.ones(D)
        val = bm.F12(x)
        assert abs(val - 1400.0) < 0.1, \
            f"F12 near third optimum: expected ~1400, got {val}"

    def test_F12_near_fourth_optimum(self):
        """Fourth component (sphere, lambda=1, bias=300): F12 ~ 1500."""
        import benchmark as bm
        comp_optima_12 = np.load('/app/data/comp_optima_12.npy')
        x = comp_optima_12[3] + 1e-10 * np.ones(D)
        val = bm.F12(x)
        assert abs(val - 1500.0) < 0.1, \
            f"F12 near fourth optimum: expected ~1500, got {val}"

    def test_F12_near_fifth_optimum(self):
        """Fifth component (griewank, lambda=1, bias=400): F12 ~ 1600."""
        import benchmark as bm
        comp_optima_12 = np.load('/app/data/comp_optima_12.npy')
        x = comp_optima_12[4] + 1e-10 * np.ones(D)
        val = bm.F12(x)
        assert abs(val - 1600.0) < 0.1, \
            f"F12 near fifth optimum: expected ~1600, got {val}"


class TestHybridFunctions:
    """Verify hybrid function properties."""

    def test_F9_at_optimum_via_module(self):
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        val = bm.F9(shifts[8])
        assert abs(val - 900.0) < 1e-6, \
            f"F9 at optimum: expected 900, got {val}"

    def test_F10_at_optimum_via_module(self):
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        val = bm.F10(shifts[9])
        assert abs(val - 1000.0) < 1e-6, \
            f"F10 at optimum: expected 1000, got {val}"

    def test_F9_bent_cigar_group_contribution(self):
        """Construct x so F9's first group (bent_cigar) gets a non-leading
        dimension input, verifying the 10^6 coefficient within the hybrid."""
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        rotations = np.load('/app/data/rotations.npy')
        shuffle_f9 = np.load('/app/data/shuffle_f9.npy')

        # Place 1.0 in the second shuffled dimension (first group, non-leading)
        z = np.zeros(D)
        z[shuffle_f9[1]] = 1.0
        x = shifts[8] + rotations[8].T @ z
        # Group 1 (bent_cigar, [z_s[0], z_s[1], z_s[2]] = [0, 1, 0]):
        #   bent_cigar = 0 + 10^6 * (1 + 0) = 10^6
        # Other groups all zero
        val = bm.F9(x)
        expected = 1e6 + 900.0
        assert abs(val - expected) < 1.0, f"Expected {expected}, got {val}"


class TestConstraints:
    """Verify constraint violation computation."""

    def test_violations_non_negative(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        for fname in ['F1', 'F3', 'F9']:
            for j, v in enumerate(results['constraints'][fname]['violations']):
                assert v >= -1e-10, \
                    f"Constraint {fname} point {j}: violation {v} should be >= 0"

    def test_F1_constraint_at_optimum(self):
        """At F1 optimum, constraint g=(0-5000) is satisfied: violation=0."""
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        v = bm.constraint_violation_F1(shifts[0])
        assert v < 1e-10, f"F1 constraint at optimum should be 0, got {v}"

    def test_F3_constraint_at_optimum(self):
        """At F3 optimum (shifts[2] in [-80,80]), max(|x|)<=80: violation=0."""
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        v = bm.constraint_violation_F3(shifts[2])
        assert v < 1e-10, f"F3 constraint at optimum should be 0, got {v}"

    def test_F9_constraint_at_optimum(self):
        """At F9 optimum, max(|x-o|)=0: violation=0."""
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        v = bm.constraint_violation_F9(shifts[8])
        assert v < 1e-10, f"F9 constraint at optimum should be 0, got {v}"

    def test_F3_constraint_known_violation(self):
        """At x = 90*ones, max(|x|)=90, g=90-80=10, violation=10."""
        import benchmark as bm
        x = np.ones(D) * 90.0
        v = bm.constraint_violation_F3(x)
        assert abs(v - 10.0) < 1e-10, f"Expected violation 10, got {v}"

    def test_F1_constraint_known_violation(self):
        """At x = optimum + 100*ones, ||x-o||^2/D = 10000, g=10000-5000=5000."""
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        x = shifts[0] + 100.0 * np.ones(D)
        v = bm.constraint_violation_F1(x)
        assert abs(v - 5000.0) < 1e-6, f"Expected violation 5000, got {v}"

    def test_F9_constraint_known_violation(self):
        """At x = optimum + 60*e_0, max(|x-o|)=60, g=60-50=10, violation=10."""
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        e0 = np.zeros(D)
        e0[0] = 60.0
        x = shifts[8] + e0
        v = bm.constraint_violation_F9(x)
        assert abs(v - 10.0) < 1e-10, f"Expected violation 10, got {v}"


class TestRosenbrockSpecialCases:
    """Additional Rosenbrock verification."""

    def test_rosenbrock_optimum(self):
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        val = bm.F5(shifts[4])
        assert abs(val - 500.0) < 1e-6, \
            f"F5 at optimum: expected 500, got {val}"

    def test_rosenbrock_all_ones_displacement(self):
        """At z = ones (z_hat = 2*ones): each term = 100*(4-2)^2 + 1 = 401.
        Total = 401*(D-1) = 3609. F5 = 3609 + 500 = 4109."""
        import benchmark as bm
        shifts = np.load('/app/data/shifts.npy')
        rotations = np.load('/app/data/rotations.npy')
        ones = np.ones(D)
        x = shifts[4] + rotations[4].T @ ones
        val = bm.F5(x)
        expected = 3609.0 + 500.0
        assert abs(val - expected) < 1e-3, f"Expected {expected}, got {val}"


class TestDataIntegrity:
    """Verify exported data files match the SQLite database parameter tables."""

    def test_shuffles_are_valid_permutations(self):
        """Each shuffle must be a valid permutation of 0..D-1."""
        for path in ['/app/data/shuffle_f9.npy', '/app/data/shuffle_f10.npy']:
            shuffle = np.load(path)
            assert len(shuffle) == D, f"Shuffle length mismatch in {path}"
            assert sorted(shuffle.tolist()) == list(range(D)), \
                f"{path} is not a valid permutation: {shuffle.tolist()}"

    def test_rotations_match_database(self):
        """All rotation matrices in .npy must match the SQLite database."""
        import sqlite3
        conn = sqlite3.connect('/app/benchmark.db')
        npy_rots = np.load('/app/data/rotations.npy')
        for i in range(10):
            row = conn.execute(
                'SELECT data FROM rotations WHERE idx=?', (i,)
            ).fetchone()
            db_rot = np.frombuffer(row[0], dtype=np.float64).reshape(D, D)
            assert np.allclose(db_rot, npy_rots[i], atol=1e-15), \
                f"Rotation {i}: .npy file does not match database"
        conn.close()

    def test_shuffles_match_database(self):
        """Shuffle permutations in .npy must match the SQLite database."""
        import sqlite3
        conn = sqlite3.connect('/app/benchmark.db')
        for name, path in [('f9', '/app/data/shuffle_f9.npy'),
                           ('f10', '/app/data/shuffle_f10.npy')]:
            row = conn.execute(
                'SELECT data FROM shuffles WHERE name=?', (name,)
            ).fetchone()
            db_shuffle = np.frombuffer(row[0], dtype=np.int64)
            npy_shuffle = np.load(path)
            assert np.array_equal(db_shuffle, npy_shuffle), \
                f"Shuffle {name}: .npy file does not match database"
        conn.close()
