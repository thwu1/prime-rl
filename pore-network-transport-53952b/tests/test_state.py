"""Tests for pore network transport simulator."""


import sys
sys.path.insert(0, '/app')

import numpy as np
from numpy.testing import assert_allclose
import pytest

from pnm_solver import (
    build_cubic_network,
    assemble_coefficient_matrix,
    apply_value_bc,
    solve_diffusion,
    solve_reactive_transport,
    solve_transient_diffusion,
    compute_rate,
    compute_effective_diffusivity,
)


# ---------------------------------------------------------------------------
# Network construction
# ---------------------------------------------------------------------------

class TestCubicNetwork:
    def test_pore_count_3d(self):
        net = build_cubic_network([4, 3, 2])
        assert net['Np'] == 24

    def test_pore_count_flat(self):
        net = build_cubic_network([4, 3, 1])
        assert net['Np'] == 12

    def test_throat_count(self):
        net = build_cubic_network([4, 3, 2])
        assert net['Nt'] == 46

    def test_throat_count_1d(self):
        net = build_cubic_network([7, 1, 1])
        assert net['Nt'] == 6

    def test_face_label_counts(self):
        net = build_cubic_network([4, 3, 2])
        assert np.sum(net['left']) == 6
        assert np.sum(net['right']) == 6
        assert np.sum(net['front']) == 8
        assert np.sum(net['back']) == 8
        assert np.sum(net['bottom']) == 12
        assert np.sum(net['top']) == 12

    def test_face_labels_flat_network(self):
        net = build_cubic_network([4, 3, 1])
        assert np.sum(net['bottom']) == 12
        assert np.sum(net['top']) == 12
        assert np.sum(net['left']) == 3
        assert np.sum(net['right']) == 3

    def test_no_duplicate_connections(self):
        net = build_cubic_network([3, 3, 3])
        conns = net['conns']
        sorted_conns = np.sort(conns, axis=1)
        unique_conns = np.unique(sorted_conns, axis=0)
        assert len(unique_conns) == len(conns)

    def test_no_self_connections(self):
        net = build_cubic_network([4, 4, 4])
        assert np.all(net['conns'][:, 0] != net['conns'][:, 1])

    def test_coords_shape(self):
        net = build_cubic_network([3, 4, 5], spacing=2.0)
        assert net['coords'].shape == (60, 3)
        assert net['coords'].max() == 2.0 * 4

    def test_c_order_raveling(self):
        """Pore 0 at (0,0,0), pore 1 at (0,0,1) in C-order."""
        net = build_cubic_network([3, 4, 5], spacing=1.0)
        assert_allclose(net['coords'][0], [0, 0, 0])
        assert_allclose(net['coords'][1], [0, 0, 1])


# ---------------------------------------------------------------------------
# Coefficient matrix
# ---------------------------------------------------------------------------

class TestCoefficientMatrix:
    def test_row_sum_zero(self):
        net = build_cubic_network([5, 5, 5])
        A = assemble_coefficient_matrix(net['Np'], net['conns'], 1.0)
        row_sums = np.asarray(A.sum(axis=1)).ravel()
        assert_allclose(row_sums, 0, atol=1e-14)

    def test_symmetry(self):
        net = build_cubic_network([4, 4, 4])
        rng = np.random.RandomState(42)
        g = rng.rand(net['Nt']) + 0.1
        A = assemble_coefficient_matrix(net['Np'], net['conns'], g)
        diff = A - A.T
        assert_allclose(diff.toarray(), 0, atol=1e-14)

    def test_diagonal_positive(self):
        net = build_cubic_network([3, 3, 3])
        A = assemble_coefficient_matrix(net['Np'], net['conns'], 2.5)
        assert np.all(A.diagonal() > 0)

    def test_shape(self):
        net = build_cubic_network([4, 4, 4])
        A = assemble_coefficient_matrix(net['Np'], net['conns'], 1.0)
        assert A.shape == (64, 64)

    def test_scalar_vs_array_conductance(self):
        net = build_cubic_network([3, 3, 3])
        A_scalar = assemble_coefficient_matrix(net['Np'], net['conns'], 3.0)
        A_array = assemble_coefficient_matrix(
            net['Np'], net['conns'], np.full(net['Nt'], 3.0)
        )
        assert_allclose(A_scalar.toarray(), A_array.toarray())


# ---------------------------------------------------------------------------
# Steady-state Fickian diffusion
# ---------------------------------------------------------------------------

class TestSteadyDiffusion:
    def test_linear_profile_9x9x9(self):
        """Uniform conductance, opposing Dirichlet BCs -> exact linear profile."""
        net = build_cubic_network([9, 9, 9])
        bc_specs = [
            (np.where(net['bottom'])[0], 0.0),
            (np.where(net['top'])[0], 1.0),
        ]
        c = solve_diffusion(net, np.ones(net['Nt']), bc_specs)
        expected = [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0]
        actual = np.unique(np.round(c, decimals=3))
        assert_allclose(actual, expected, atol=1e-3)

    def test_per_pore_values_5x5x5(self):
        """Each pore concentration equals k / (Nz - 1)."""
        shape = [5, 5, 5]
        net = build_cubic_network(shape)
        bc_specs = [
            (np.where(net['bottom'])[0], 0.0),
            (np.where(net['top'])[0], 1.0),
        ]
        c = solve_diffusion(net, np.ones(net['Nt']), bc_specs)
        ijk = np.array(np.unravel_index(np.arange(net['Np']), shape)).T
        expected = ijk[:, 2] / (shape[2] - 1)
        assert_allclose(c, expected, atol=1e-10)

    def test_mean_is_half(self):
        """Symmetric BCs 0 and 1 -> mean = 0.5."""
        net = build_cubic_network([9, 9, 9])
        bc_specs = [
            (np.where(net['bottom'])[0], 0.0),
            (np.where(net['top'])[0], 1.0),
        ]
        c = solve_diffusion(net, np.ones(net['Nt']), bc_specs)
        assert_allclose(c.mean(), 0.5, atol=1e-10)

    def test_single_bc_uniform(self):
        """Single Dirichlet BC, no sources -> uniform concentration."""
        net = build_cubic_network([4, 4, 4])
        bc_specs = [(np.where(net['top'])[0], 3.14)]
        c = solve_diffusion(net, np.full(net['Nt'], 1e-15), bc_specs)
        assert_allclose(c, 3.14, atol=1e-10)

    def test_gradient_along_x_axis(self):
        """BCs on left/right -> linear gradient along axis 0."""
        shape = [6, 4, 3]
        net = build_cubic_network(shape)
        bc_specs = [
            (np.where(net['left'])[0], 2.0),
            (np.where(net['right'])[0], 8.0),
        ]
        c = solve_diffusion(net, np.ones(net['Nt']), bc_specs)
        ijk = np.array(np.unravel_index(np.arange(net['Np']), shape)).T
        expected = 2.0 + 6.0 * ijk[:, 0] / (shape[0] - 1)
        assert_allclose(c, expected, atol=1e-9)


# ---------------------------------------------------------------------------
# Mass balance / rate computation
# ---------------------------------------------------------------------------

class TestMassBalance:
    def test_net_rate_zero(self):
        """Total outward flux summed over all pores must be zero."""
        net = build_cubic_network([9, 9, 9])
        g = np.ones(net['Nt'])
        bc_specs = [
            (np.where(net['bottom'])[0], 0.0),
            (np.where(net['top'])[0], 1.0),
        ]
        c = solve_diffusion(net, g, bc_specs)
        total = compute_rate(net, g, c, np.arange(net['Np']))
        assert_allclose(total, 0.0, atol=1e-10)

    def test_inlet_outlet_balance(self):
        """Rate at inlet + rate at outlet = 0."""
        net = build_cubic_network([9, 9, 9])
        g = np.ones(net['Nt'])
        bc_specs = [
            (np.where(net['bottom'])[0], 0.0),
            (np.where(net['top'])[0], 1.0),
        ]
        c = solve_diffusion(net, g, bc_specs)
        r_bot = compute_rate(net, g, c, np.where(net['bottom'])[0])
        r_top = compute_rate(net, g, c, np.where(net['top'])[0])
        assert_allclose(r_bot + r_top, 0.0, atol=1e-10)

    def test_rate_magnitude(self):
        """Check specific rate value for 9x9x9 with g=1, bottom=0, top=1."""
        net = build_cubic_network([9, 9, 9])
        g = np.ones(net['Nt'])
        bc_specs = [
            (np.where(net['bottom'])[0], 0.0),
            (np.where(net['top'])[0], 1.0),
        ]
        c = solve_diffusion(net, g, bc_specs)
        r_bot = compute_rate(net, g, c, np.where(net['bottom'])[0])
        assert_allclose(r_bot, -81 * 0.125, atol=1e-9)


# ---------------------------------------------------------------------------
# Nonlinear reactive transport
# ---------------------------------------------------------------------------

class TestReactiveTransport:
    def test_convergence_and_mean_4x4x4(self):
        """Standard kinetics r = -1e-15 * X^2 -> c_mean ~ 0.717129."""
        net = build_cubic_network([4, 4, 4])
        g = np.full(net['Nt'], 1e-15)
        bc_specs = [(np.where(net['top'])[0], 1.0)]
        src = np.where(net['bottom'])[0]
        result = solve_reactive_transport(
            net, g, bc_specs,
            source_pores=src, prefactor=-1e-15, exponent=2,
        )
        assert result['converged'] is True
        assert_allclose(result['concentration'].mean(), 0.717129, rtol=1e-4)

    def test_no_negative_concentrations(self):
        """Converged solution should be non-negative."""
        net = build_cubic_network([4, 4, 4])
        g = np.full(net['Nt'], 1e-15)
        bc_specs = [(np.where(net['top'])[0], 1.0)]
        src = np.where(net['bottom'])[0]
        result = solve_reactive_transport(
            net, g, bc_specs,
            source_pores=src, prefactor=-1e-15, exponent=2,
        )
        assert np.all(result['concentration'] >= -1e-8)

    def test_bc_satisfied(self):
        """BC pores must have the prescribed value after convergence."""
        net = build_cubic_network([4, 4, 4])
        g = np.full(net['Nt'], 1e-15)
        top = np.where(net['top'])[0]
        bc_specs = [(top, 1.0)]
        src = np.where(net['bottom'])[0]
        result = solve_reactive_transport(
            net, g, bc_specs,
            source_pores=src, prefactor=-1e-15, exponent=2,
        )
        assert_allclose(result['concentration'][top], 1.0, atol=1e-12)

    def test_stronger_reaction_lowers_mean(self):
        """Doubling the prefactor magnitude increases consumption -> lower mean."""
        net = build_cubic_network([4, 4, 4])
        g = np.full(net['Nt'], 1e-15)
        bc_specs = [(np.where(net['right'])[0], 1.0)]
        src = np.where(net['left'])[0]

        r1 = solve_reactive_transport(
            net, g, bc_specs, source_pores=src,
            prefactor=-1e-15, exponent=2,
        )
        r2 = solve_reactive_transport(
            net, g, bc_specs, source_pores=src,
            prefactor=-2e-15, exponent=2,
        )
        assert r1['converged'] and r2['converged']
        assert r2['concentration'].mean() < r1['concentration'].mean()

    def test_zero_source_matches_diffusion(self):
        """With prefactor=0, reactive transport degenerates to diffusion."""
        net = build_cubic_network([4, 4, 4])
        g = np.full(net['Nt'], 1e-15)
        bc_specs = [
            (np.where(net['bottom'])[0], 0.0),
            (np.where(net['top'])[0], 1.0),
        ]
        src = np.where(net['bottom'])[0]
        result = solve_reactive_transport(
            net, g, bc_specs,
            source_pores=src, prefactor=0.0, exponent=2,
        )
        c_diff = solve_diffusion(net, g, bc_specs)
        assert_allclose(result['concentration'], c_diff, atol=1e-10)


# ---------------------------------------------------------------------------
# Transient Fickian diffusion
# ---------------------------------------------------------------------------

class TestTransientDiffusion:
    def test_intermediate_time(self):
        """At t=10, mean concentration ~ 0.40803 (partially developed)."""
        net = build_cubic_network([4, 3, 1])
        g = np.full(net['Nt'], 1e-15)
        V = np.full(net['Np'], 1e-14)
        bc_specs = [
            (np.where(net['left'])[0], 0.0),
            (np.where(net['right'])[0], 1.0),
        ]
        c = solve_transient_diffusion(net, g, V, bc_specs,
                                       x0=np.zeros(net['Np']),
                                       tspan=(0, 10))
        assert_allclose(c.mean(), 0.40803, rtol=1e-3)

    def test_steady_state_limit(self):
        """At large t, transient -> steady state (mean ~ 0.5)."""
        net = build_cubic_network([4, 3, 1])
        g = np.full(net['Nt'], 1e-15)
        V = np.full(net['Np'], 1e-14)
        bc_specs = [
            (np.where(net['left'])[0], 0.0),
            (np.where(net['right'])[0], 1.0),
        ]
        c = solve_transient_diffusion(net, g, V, bc_specs,
                                       x0=np.zeros(net['Np']),
                                       tspan=(0, 200))
        assert_allclose(c.mean(), 0.5, rtol=1e-3)

    def test_bc_held_constant(self):
        """BC pore values must remain fixed throughout integration."""
        net = build_cubic_network([4, 3, 1])
        g = np.full(net['Nt'], 1e-15)
        V = np.full(net['Np'], 1e-14)
        left = np.where(net['left'])[0]
        right = np.where(net['right'])[0]
        bc_specs = [(left, 0.0), (right, 1.0)]
        c = solve_transient_diffusion(net, g, V, bc_specs,
                                       x0=np.zeros(net['Np']),
                                       tspan=(0, 50))
        assert_allclose(c[left], 0.0, atol=1e-10)
        assert_allclose(c[right], 1.0, atol=1e-10)

    def test_monotonic_approach(self):
        """Mean concentration increases monotonically from 0 toward 0.5."""
        net = build_cubic_network([4, 3, 1])
        g = np.full(net['Nt'], 1e-15)
        V = np.full(net['Np'], 1e-14)
        bc_specs = [
            (np.where(net['left'])[0], 0.0),
            (np.where(net['right'])[0], 1.0),
        ]
        c5 = solve_transient_diffusion(net, g, V, bc_specs,
                                        x0=np.zeros(net['Np']),
                                        tspan=(0, 5))
        c20 = solve_transient_diffusion(net, g, V, bc_specs,
                                         x0=np.zeros(net['Np']),
                                         tspan=(0, 20))
        assert c5.mean() < c20.mean()
        assert c20.mean() < 0.51


# ---------------------------------------------------------------------------
# Effective diffusivity
# ---------------------------------------------------------------------------

class TestEffectiveDiffusivity:
    def test_uniform_d_eff(self):
        """D_eff equals conductance for uniform-g cubic network."""
        net = build_cubic_network([9, 9, 9])
        g_val = 2.5
        g = np.full(net['Nt'], g_val)
        bc_specs = [
            (np.where(net['bottom'])[0], 0.0),
            (np.where(net['top'])[0], 1.0),
        ]
        c = solve_diffusion(net, g, bc_specs)
        D = compute_effective_diffusivity(
            net, g, c,
            inlet_pores=np.where(net['bottom'])[0],
            outlet_pores=np.where(net['top'])[0],
            domain_length=8.0,
            cross_section_area=81.0,
        )
        assert_allclose(D, g_val, rtol=1e-6)

    def test_heterogeneous_d_eff(self):
        """D_eff matches analytical harmonic mean for layered conductances."""
        import json
        with open('/app/networks/heterogeneous_5x5x5.json') as f:
            data = json.load(f)

        shape = data['shape']
        spacing = data['spacing']
        net = build_cubic_network(shape, spacing)

        layer_vals = data['layer_conductances']
        cross_g = data['cross_section_conductance']

        g = np.full(net['Nt'], cross_g)
        coords = net['coords']
        conns = net['conns']
        for t in range(net['Nt']):
            p1, p2 = conns[t]
            if abs(coords[p1, 0] - coords[p2, 0]) > 0.5 * spacing:
                layer = int(min(coords[p1, 0], coords[p2, 0]) / spacing)
                g[t] = layer_vals[layer]

        inlet = np.where(net[data['boundary_conditions']['inlet_face']])[0]
        outlet = np.where(net[data['boundary_conditions']['outlet_face']])[0]

        bc_specs = [
            (inlet, data['boundary_conditions']['inlet_value']),
            (outlet, data['boundary_conditions']['outlet_value']),
        ]
        c = solve_diffusion(net, g, bc_specs)

        D = compute_effective_diffusivity(
            net, g, c, inlet, outlet,
            domain_length=(shape[0] - 1) * spacing,
            cross_section_area=(shape[1] * spacing) * (shape[2] * spacing),
        )
        assert_allclose(D, data['reference']['expected_d_eff'], rtol=1e-3)

    def test_heterogeneous_mean_concentration(self):
        """Mean concentration matches reference for layered-conductance network."""
        import json
        with open('/app/networks/heterogeneous_5x5x5.json') as f:
            data = json.load(f)

        shape = data['shape']
        spacing = data['spacing']
        net = build_cubic_network(shape, spacing)

        layer_vals = data['layer_conductances']
        cross_g = data['cross_section_conductance']

        g = np.full(net['Nt'], cross_g)
        coords = net['coords']
        conns = net['conns']
        for t in range(net['Nt']):
            p1, p2 = conns[t]
            if abs(coords[p1, 0] - coords[p2, 0]) > 0.5 * spacing:
                layer = int(min(coords[p1, 0], coords[p2, 0]) / spacing)
                g[t] = layer_vals[layer]

        inlet = np.where(net[data['boundary_conditions']['inlet_face']])[0]
        outlet = np.where(net[data['boundary_conditions']['outlet_face']])[0]

        bc_specs = [
            (inlet, data['boundary_conditions']['inlet_value']),
            (outlet, data['boundary_conditions']['outlet_value']),
        ]
        c = solve_diffusion(net, g, bc_specs)
        assert_allclose(c.mean(), data['reference']['expected_mean_concentration'],
                        rtol=1e-3)
