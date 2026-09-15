
import sys
sys.path.insert(0, '/app')

import numpy as np
import pytest
from toric_decoder import (
    build_z_matching, build_x_matching,
    z_syndrome, x_syndrome,
    actual_x_observables, actual_z_observables,
    logical_error_rate, estimate_threshold,
)


# ---------------------------------------------------------------------------
# Matching graph structure
# ---------------------------------------------------------------------------

class TestZMatchingStructure:
    def test_d3(self):
        m = build_z_matching(3, 0.1)
        assert m.num_nodes == 9
        assert m.num_edges == 18
        assert m.num_fault_ids == 2
        assert len(m.boundary) == 0

    def test_d5(self):
        m = build_z_matching(5, 0.1)
        assert m.num_nodes == 25
        assert m.num_edges == 50
        assert m.num_fault_ids == 2
        assert len(m.boundary) == 0


class TestXMatchingStructure:
    def test_d3(self):
        m = build_x_matching(3, 0.1)
        assert m.num_nodes == 9
        assert m.num_edges == 18
        assert m.num_fault_ids == 2
        assert len(m.boundary) == 0

    def test_d5(self):
        m = build_x_matching(5, 0.1)
        assert m.num_nodes == 25
        assert m.num_edges == 50
        assert m.num_fault_ids == 2
        assert len(m.boundary) == 0


# ---------------------------------------------------------------------------
# Z-syndrome computation
# ---------------------------------------------------------------------------

class TestZSyndrome:
    def test_single_horizontal_error_d3(self):
        """h(1,1)=qubit 4 flips vertices (1,1)=4 and (1,2)=5."""
        d = 3
        x = np.zeros((1, 2 * d * d), dtype=np.uint8)
        x[0, 4] = 1
        syn = z_syndrome(d, x)
        expected = np.zeros((1, d * d), dtype=np.uint8)
        expected[0, 4] = 1
        expected[0, 5] = 1
        np.testing.assert_array_equal(syn, expected)

    def test_single_vertical_error_d3(self):
        """v(1,0)=qubit 12 flips vertices (1,0)=3 and (2,0)=6."""
        d = 3
        x = np.zeros((1, 2 * d * d), dtype=np.uint8)
        x[0, 12] = 1
        syn = z_syndrome(d, x)
        expected = np.zeros((1, d * d), dtype=np.uint8)
        expected[0, 3] = 1
        expected[0, 6] = 1
        np.testing.assert_array_equal(syn, expected)

    def test_wraparound_horizontal_d3(self):
        """h(0,2)=qubit 2 wraps: flips vertices (0,2)=2 and (0,0)=0."""
        d = 3
        x = np.zeros((1, 2 * d * d), dtype=np.uint8)
        x[0, 2] = 1
        syn = z_syndrome(d, x)
        expected = np.zeros((1, d * d), dtype=np.uint8)
        expected[0, 2] = 1
        expected[0, 0] = 1
        np.testing.assert_array_equal(syn, expected)

    def test_even_parity_all_single_errors_d5(self):
        """Every single-qubit X error must create exactly 2 syndrome flips."""
        d = 5
        for q in range(2 * d * d):
            x = np.zeros((1, 2 * d * d), dtype=np.uint8)
            x[0, q] = 1
            syn = z_syndrome(d, x)
            assert np.sum(syn) == 2, f"qubit {q}: expected 2 syndrome bits"


# ---------------------------------------------------------------------------
# X-syndrome computation
# ---------------------------------------------------------------------------

class TestXSyndrome:
    def test_single_horizontal_error_d3(self):
        """h(1,1)=qubit 4 flips faces (1,1)=4 and (0,1)=1."""
        d = 3
        z = np.zeros((1, 2 * d * d), dtype=np.uint8)
        z[0, 4] = 1
        syn = x_syndrome(d, z)
        expected = np.zeros((1, d * d), dtype=np.uint8)
        expected[0, 4] = 1   # face(1,1)
        expected[0, 1] = 1   # face(0,1)
        np.testing.assert_array_equal(syn, expected)

    def test_single_vertical_error_d3(self):
        """v(1,0)=qubit 12 flips faces (1,0)=3 and (1,2)=5."""
        d = 3
        z = np.zeros((1, 2 * d * d), dtype=np.uint8)
        z[0, 12] = 1
        syn = x_syndrome(d, z)
        expected = np.zeros((1, d * d), dtype=np.uint8)
        expected[0, 3] = 1   # face(1,0)
        expected[0, 5] = 1   # face(1,2)
        np.testing.assert_array_equal(syn, expected)

    def test_even_parity_all_single_errors_d5(self):
        """Every single-qubit Z error must create exactly 2 syndrome flips."""
        d = 5
        for q in range(2 * d * d):
            z = np.zeros((1, 2 * d * d), dtype=np.uint8)
            z[0, q] = 1
            syn = x_syndrome(d, z)
            assert np.sum(syn) == 2, f"qubit {q}: expected 2 syndrome bits"


# ---------------------------------------------------------------------------
# Observable computation
# ---------------------------------------------------------------------------

class TestObservables:
    def test_x_obs_fault0_d3(self):
        """X error on h(1,0)=qubit 3 (column j=0) flips X obs 0."""
        d = 3
        x = np.zeros((1, 2 * d * d), dtype=np.uint8)
        x[0, 3] = 1
        obs = actual_x_observables(d, x)
        assert obs[0, 0] == 1
        assert obs[0, 1] == 0

    def test_x_obs_fault1_d3(self):
        """X error on v(0,1)=qubit 10 (row i=0) flips X obs 1."""
        d = 3
        x = np.zeros((1, 2 * d * d), dtype=np.uint8)
        x[0, 10] = 1
        obs = actual_x_observables(d, x)
        assert obs[0, 0] == 0
        assert obs[0, 1] == 1

    def test_x_obs_interior_d5(self):
        """X error on h(2,2)=qubit 12 (no logical support) flips nothing."""
        d = 5
        x = np.zeros((1, 2 * d * d), dtype=np.uint8)
        x[0, 12] = 1
        obs = actual_x_observables(d, x)
        assert obs[0, 0] == 0
        assert obs[0, 1] == 0

    def test_z_obs_fault0_d3(self):
        """Z error on h(0,1)=qubit 1 (row i=0) flips Z obs 0."""
        d = 3
        z = np.zeros((1, 2 * d * d), dtype=np.uint8)
        z[0, 1] = 1
        obs = actual_z_observables(d, z)
        assert obs[0, 0] == 1
        assert obs[0, 1] == 0

    def test_z_obs_fault1_d3(self):
        """Z error on v(1,0)=qubit 12 (column j=0) flips Z obs 1."""
        d = 3
        z = np.zeros((1, 2 * d * d), dtype=np.uint8)
        z[0, 12] = 1
        obs = actual_z_observables(d, z)
        assert obs[0, 0] == 0
        assert obs[0, 1] == 1


# ---------------------------------------------------------------------------
# Decoding correctness
# ---------------------------------------------------------------------------

class TestDecoding:
    def test_z_decode_zero_syndrome_d5(self):
        m = build_z_matching(5, 0.1)
        syn = np.zeros((1, 25), dtype=np.uint8)
        pred = m.decode_batch(syn)
        assert np.all(pred == 0)

    def test_z_decode_single_fault0_d5(self):
        """Single X error on h(2,0)=qubit 10."""
        d = 5
        m = build_z_matching(d, 0.1)
        x = np.zeros((1, 2 * d * d), dtype=np.uint8)
        x[0, 10] = 1
        syn = z_syndrome(d, x)
        actual = actual_x_observables(d, x)
        pred = m.decode_batch(syn)
        np.testing.assert_array_equal(pred, actual)

    def test_z_decode_single_fault1_d5(self):
        """Single X error on v(0,2)=qubit 27."""
        d = 5
        m = build_z_matching(d, 0.1)
        x = np.zeros((1, 2 * d * d), dtype=np.uint8)
        x[0, 27] = 1
        syn = z_syndrome(d, x)
        actual = actual_x_observables(d, x)
        pred = m.decode_batch(syn)
        np.testing.assert_array_equal(pred, actual)

    def test_z_decode_all_single_errors_d5(self):
        """Every single X error on a d=5 toric code must be decoded correctly."""
        d = 5
        m = build_z_matching(d, 0.1)
        for q in range(2 * d * d):
            x = np.zeros((1, 2 * d * d), dtype=np.uint8)
            x[0, q] = 1
            syn = z_syndrome(d, x)
            actual = actual_x_observables(d, x)
            pred = m.decode_batch(syn)
            np.testing.assert_array_equal(
                pred, actual, err_msg=f"failed on qubit {q}"
            )

    def test_x_decode_single_error_d5(self):
        """Single Z error on h(2,2)=qubit 12 decoded via X matching."""
        d = 5
        m = build_x_matching(d, 0.1)
        z = np.zeros((1, 2 * d * d), dtype=np.uint8)
        z[0, 12] = 1
        syn = x_syndrome(d, z)
        actual = actual_z_observables(d, z)
        pred = m.decode_batch(syn)
        np.testing.assert_array_equal(pred, actual)

    def test_x_decode_all_single_errors_d5(self):
        """Every single Z error on a d=5 toric code must be decoded correctly."""
        d = 5
        m = build_x_matching(d, 0.1)
        for q in range(2 * d * d):
            z = np.zeros((1, 2 * d * d), dtype=np.uint8)
            z[0, q] = 1
            syn = x_syndrome(d, z)
            actual = actual_z_observables(d, z)
            pred = m.decode_batch(syn)
            np.testing.assert_array_equal(
                pred, actual, err_msg=f"failed on qubit {q}"
            )


# ---------------------------------------------------------------------------
# Logical error rate and threshold
# ---------------------------------------------------------------------------

class TestLogicalErrorRate:
    def test_zero_noise(self):
        rate = logical_error_rate(3, 0.0, 200, seed=42)
        assert rate == 0.0

    def test_low_noise_d5(self):
        """At p=0.02 well below threshold, d=5 logical error rate < p."""
        rate = logical_error_rate(5, 0.02, 5000, seed=42)
        assert rate < 0.02

    def test_below_threshold_scaling(self):
        """Below threshold, larger d → lower logical error rate."""
        rate3 = logical_error_rate(3, 0.05, 5000, seed=100)
        rate5 = logical_error_rate(5, 0.05, 5000, seed=100)
        assert rate5 < rate3


class TestThreshold:
    def test_crossing_behavior(self):
        """Below threshold d=5 beats d=3; above threshold d=3 beats d=5."""
        distances = [3, 5]
        p_values = [0.05, 0.15]
        results = estimate_threshold(distances, p_values, num_shots=5000, seed=42)
        # Below threshold
        assert results[(5, 0.05)] < results[(3, 0.05)]
        # Above threshold
        assert results[(5, 0.15)] > results[(3, 0.15)]
