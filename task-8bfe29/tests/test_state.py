
import sys
import pytest

sys.path.insert(0, "/app")


class TestAutocorrelation:
    """Verify individual autocorrelation coefficients C_k."""

    def test_autocorrelation_values(self):
        from labs.energy import autocorrelation

        s = [1, -1, -1, 1, -1]
        # C_1 = 1*(-1) + (-1)*(-1) + (-1)*1 + 1*(-1) = -1+1-1-1 = -2
        assert autocorrelation(s, 1) == -2
        # C_2 = 1*(-1) + (-1)*1 + (-1)*(-1) = -1-1+1 = -1
        assert autocorrelation(s, 2) == -1
        # C_3 = 1*1 + (-1)*(-1) = 1+1 = 2
        assert autocorrelation(s, 3) == 2
        # C_4 = 1*(-1) = -1
        assert autocorrelation(s, 4) == -1

    def test_autocorrelation_all_same(self):
        from labs.energy import autocorrelation

        s = [1, 1, 1, 1, 1]
        for k in range(1, 5):
            assert autocorrelation(s, k) == 5 - k


class TestEnergy:
    """Verify LABS energy computation on known sequences."""

    def test_energy_n3_optimal(self):
        from labs.energy import energy

        assert energy([1, -1, -1]) == 1

    def test_energy_n5_optimal(self):
        from labs.energy import energy

        assert energy([1, -1, 1, 1, 1]) == 2

    def test_energy_n7_optimal(self):
        from labs.energy import energy

        assert energy([1, -1, 1, 1, -1, -1, -1]) == 3

    def test_energy_non_optimal(self):
        from labs.energy import energy

        assert energy([1, 1, 1]) == 5
        assert energy([1, 1, -1, -1]) == 6

    def test_energy_n4_optimal(self):
        from labs.energy import energy

        assert energy([1, 1, 1, -1]) == 2

    def test_energy_n11_optimal(self):
        from labs.energy import energy

        assert energy([1, -1, 1, 1, -1, 1, 1, 1, -1, -1, -1]) == 5


class TestMeritFactor:
    """Verify merit factor computation."""

    def test_merit_factor_n3(self):
        from labs.energy import merit_factor

        assert abs(merit_factor([1, -1, -1]) - 4.5) < 1e-10

    def test_merit_factor_n5(self):
        from labs.energy import merit_factor

        assert abs(merit_factor([1, -1, 1, 1, 1]) - 6.25) < 1e-10

    def test_merit_factor_n7(self):
        from labs.energy import merit_factor

        # N=7, E=3, F = 49/6 = 8.1667
        f = merit_factor([1, -1, 1, 1, -1, -1, -1])
        assert abs(f - 49.0 / 6.0) < 1e-10


class TestInteractionsG2:
    """Verify 2-body interaction index sets."""

    def test_g2_n5(self):
        from labs.interactions import get_interactions

        G2, _ = get_interactions(5)
        expected = {(0, 1), (0, 2), (1, 2), (2, 3)}
        actual = {tuple(sorted(g)) for g in G2}
        assert actual == expected

    def test_g2_n6(self):
        from labs.interactions import get_interactions

        G2, _ = get_interactions(6)
        expected = {(0, 1), (0, 2), (1, 2), (1, 3), (2, 3), (3, 4)}
        actual = {tuple(sorted(g)) for g in G2}
        assert actual == expected

    def test_g2_size_n7(self):
        from labs.interactions import get_interactions

        G2, _ = get_interactions(7)
        assert len(G2) == 9

    def test_g2_size_n10(self):
        from labs.interactions import get_interactions

        G2, _ = get_interactions(10)
        assert len(G2) == 20


class TestInteractionsG4:
    """Verify 4-body interaction index sets."""

    def test_g4_n5(self):
        from labs.interactions import get_interactions

        _, G4 = get_interactions(5)
        expected = {(0, 1, 2, 3), (0, 1, 3, 4), (1, 2, 3, 4)}
        actual = {tuple(sorted(g)) for g in G4}
        assert actual == expected

    def test_g4_n6(self):
        from labs.interactions import get_interactions

        _, G4 = get_interactions(6)
        expected = {
            (0, 1, 2, 3),
            (0, 1, 3, 4),
            (0, 1, 4, 5),
            (0, 2, 3, 5),
            (1, 2, 3, 4),
            (1, 2, 4, 5),
            (2, 3, 4, 5),
        }
        actual = {tuple(sorted(g)) for g in G4}
        assert actual == expected

    def test_g4_size_n7(self):
        from labs.interactions import get_interactions

        _, G4 = get_interactions(7)
        assert len(G4) == 13

    def test_g4_size_n10(self):
        from labs.interactions import get_interactions

        _, G4 = get_interactions(10)
        assert len(G4) == 50

    def test_g4_n4(self):
        from labs.interactions import get_interactions

        _, G4 = get_interactions(4)
        expected = {(0, 1, 2, 3)}
        actual = {tuple(sorted(g)) for g in G4}
        assert actual == expected


class TestTopologyOverlaps:
    """Verify topology overlap invariants."""

    def test_overlaps_n7(self):
        from labs.interactions import get_interactions, topology_overlaps

        G2, G4 = get_interactions(7)
        I = topology_overlaps(G2, G4)
        assert I["22"] == 9
        assert I["44"] == 13
        assert I["24"] == 0

    def test_overlaps_n10(self):
        from labs.interactions import get_interactions, topology_overlaps

        G2, G4 = get_interactions(10)
        I = topology_overlaps(G2, G4)
        assert I["22"] == 20
        assert I["44"] == 50
        assert I["24"] == 0


class TestGamma1:
    """Verify Gamma1 computation."""

    def test_gamma1_n5(self):
        from labs.interactions import get_interactions
        from labs.theta import compute_gamma1

        G2, G4 = get_interactions(5)
        assert compute_gamma1(G2, G4) == 896

    def test_gamma1_n10(self):
        from labs.interactions import get_interactions
        from labs.theta import compute_gamma1

        G2, G4 = get_interactions(10)
        assert compute_gamma1(G2, G4) == 13440

    def test_gamma1_n7(self):
        from labs.interactions import get_interactions
        from labs.theta import compute_gamma1

        G2, G4 = get_interactions(7)
        # 32*9 + 256*13 = 288 + 3328 = 3616
        assert compute_gamma1(G2, G4) == 3616


class TestTheta:
    """Verify counterdiabatic theta parameter computation."""

    def test_theta_n5_step1(self):
        from labs.interactions import get_interactions
        from labs.theta import compute_theta

        G2, G4 = get_interactions(5)
        theta = compute_theta(1.0 / 3.0, 1.0 / 3.0, 1.0, 5, G2, G4)
        assert abs(theta - 0.0199632005) < 1e-8

    def test_theta_n5_step2(self):
        from labs.interactions import get_interactions
        from labs.theta import compute_theta

        G2, G4 = get_interactions(5)
        theta = compute_theta(2.0 / 3.0, 1.0 / 3.0, 1.0, 5, G2, G4)
        assert abs(theta - 0.0067391696) < 1e-8

    def test_theta_n5_step3_zero(self):
        from labs.interactions import get_interactions
        from labs.theta import compute_theta

        G2, G4 = get_interactions(5)
        theta = compute_theta(1.0, 1.0 / 3.0, 1.0, 5, G2, G4)
        assert abs(theta) < 1e-12

    def test_theta_n7(self):
        from labs.interactions import get_interactions
        from labs.theta import compute_theta

        G2, G4 = get_interactions(7)
        theta = compute_theta(1.0 / 3.0, 1.0 / 3.0, 1.0, 7, G2, G4)
        assert abs(theta - 0.0187622966) < 1e-8

    def test_theta_zero_time(self):
        from labs.interactions import get_interactions
        from labs.theta import compute_theta

        G2, G4 = get_interactions(5)
        theta = compute_theta(0.0, 0.1, 0.0, 5, G2, G4)
        assert theta == 0.0


class TestGamma2:
    """Verify Gamma2 computation at specific lambda values."""

    def test_gamma2_n5_lam_quarter(self):
        from labs.interactions import get_interactions, topology_overlaps
        from labs.theta import compute_gamma2

        G2, G4 = get_interactions(5)
        I_vals = topology_overlaps(G2, G4)
        lam = 0.25
        gamma2 = compute_gamma2(lam, G2, G4, I_vals)
        # Manual: topology = 4*(1/16)*(0+4) + 64*(1/16)*3 = 1 + 12 = 13
        # sum_G2 = 4 * 2 * (1/16) = 0.5
        # sum_G4 = 4*3*(16/16 + 8*9/16) = 12*(1+4.5) = 66
        # Gamma2 = -256*(13 + 0.5 + 66) = -256*79.5 = -20352
        assert abs(gamma2 - (-20352.0)) < 1e-6


class TestSymmetryNegation:
    """Verify energy invariance under negation."""

    def test_negation_preserves_energy(self):
        from labs.energy import energy
        from labs.symmetry import negate

        sequences = [
            [1, -1, 1, 1, -1],
            [1, 1, 1, -1, -1, 1, -1],
            [1, -1, -1, 1, 1, -1, -1, 1, -1],
        ]
        for s in sequences:
            assert energy(s) == energy(negate(s))

    def test_negate_values(self):
        from labs.symmetry import negate

        assert negate([1, -1, 1]) == [-1, 1, -1]


class TestSymmetryReversal:
    """Verify energy invariance under reversal."""

    def test_reversal_preserves_energy(self):
        from labs.energy import energy
        from labs.symmetry import reverse_seq

        sequences = [
            [1, -1, 1, 1, -1],
            [1, 1, 1, -1, -1, 1, -1],
            [1, -1, -1, 1, 1, -1, -1, 1, -1],
        ]
        for s in sequences:
            assert energy(s) == energy(reverse_seq(s))

    def test_reverse_values(self):
        from labs.symmetry import reverse_seq

        assert reverse_seq([1, -1, 1, 1]) == [1, 1, -1, 1]


class TestSymmetryAlternating:
    """Verify energy invariance under alternating inversion."""

    def test_alternating_preserves_energy(self):
        from labs.energy import energy
        from labs.symmetry import alternating_inversion

        sequences = [
            [1, -1, 1, 1, -1],
            [1, 1, 1, -1, -1, 1, -1],
            [1, -1, -1, 1, 1, -1, -1, 1, -1],
        ]
        for s in sequences:
            assert energy(s) == energy(alternating_inversion(s))

    def test_alternating_values(self):
        from labs.symmetry import alternating_inversion

        # (-1)^0=1, (-1)^1=-1, (-1)^2=1, (-1)^3=-1
        assert alternating_inversion([1, -1, 1, -1]) == [1, 1, 1, 1]
        assert alternating_inversion([1, 1, 1, 1]) == [1, -1, 1, -1]


class TestCanonicalForm:
    """Verify canonical form consistency under all symmetries."""

    def test_canonical_consistency(self):
        from labs.symmetry import (
            canonical_form,
            negate,
            reverse_seq,
            alternating_inversion,
        )

        s = [1, -1, 1, 1, -1]
        c = canonical_form(s)
        assert c == canonical_form(negate(s))
        assert c == canonical_form(reverse_seq(s))
        assert c == canonical_form(alternating_inversion(s))
        assert c == canonical_form(negate(reverse_seq(s)))
        assert c == canonical_form(reverse_seq(alternating_inversion(s)))
        assert c == canonical_form(negate(alternating_inversion(s)))
        assert c == canonical_form(negate(reverse_seq(alternating_inversion(s))))

    def test_canonical_is_tuple(self):
        from labs.symmetry import canonical_form

        c = canonical_form([1, -1, 1])
        assert isinstance(c, tuple)

    def test_canonical_is_smallest(self):
        from labs.symmetry import canonical_form

        # Canonical form should be lexicographically smallest
        c = canonical_form([1, 1, 1])
        # All-negative is [-1,-1,-1] which is smaller
        assert c == (-1, -1, -1)


class TestEnergyChangeOnFlip:
    """Verify incremental energy update when flipping a single bit."""

    def test_flip_all_positions(self):
        from labs.energy import autocorrelation, energy, energy_change_on_flip

        s = [1, -1, 1, 1, -1, -1, 1]
        N = len(s)
        C = [autocorrelation(s, k) for k in range(1, N)]
        E_orig = energy(s)

        for j in range(N):
            delta_E, new_C = energy_change_on_flip(s, j, C)
            s_flipped = s[:]
            s_flipped[j] *= -1
            E_new = energy(s_flipped)
            assert delta_E == E_new - E_orig, (
                f"flip {j}: delta_E={delta_E}, expected {E_new - E_orig}"
            )
            # Verify new autocorrelation values
            actual_C = [autocorrelation(s_flipped, k) for k in range(1, N)]
            assert new_C == actual_C, f"flip {j}: new_C mismatch"

    def test_flip_specific_case(self):
        from labs.energy import autocorrelation, energy, energy_change_on_flip

        s = [1, -1, -1]
        C = [autocorrelation(s, k) for k in range(1, 3)]
        # C = [0, -1], E = 1
        assert C == [0, -1]

        # Flip j=0: new_s = [-1,-1,-1], new_C = [2, 1], E_new = 5
        delta_E, new_C = energy_change_on_flip(s, 0, C)
        assert delta_E == 4
        assert new_C == [2, 1]


class TestSolverSmall:
    """Verify solver finds known optimal energies for small N."""

    def test_solve_n5(self):
        from labs.solver import solve

        _, E = solve(5)
        assert E == 2

    def test_solve_n7(self):
        from labs.solver import solve

        _, E = solve(7)
        assert E == 3

    def test_solve_n11(self):
        from labs.solver import solve

        _, E = solve(11)
        assert E == 5

    def test_solve_n13(self):
        from labs.solver import solve

        _, E = solve(13)
        assert E == 6


class TestSolverMedium:
    """Verify solver achieves near-optimal for medium N."""

    def test_solve_n21(self):
        from labs.solver import solve

        s, E = solve(21)
        assert len(s) == 21
        assert all(x in (-1, 1) for x in s)
        assert E <= 30

    def test_solve_returns_consistent_energy(self):
        from labs.energy import energy
        from labs.solver import solve

        s, E = solve(7)
        assert energy(s) == E
