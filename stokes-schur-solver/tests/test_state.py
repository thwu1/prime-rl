
import pytest
import numpy as np
import json
import os

OUTPUT_DIR = '/app/output'
MESH_CONFIG = '/app/config/mesh.json'


@pytest.fixture(scope='module')
def mesh_config():
    with open(MESH_CONFIG) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def fields(mesh_config):
    nx, ny = mesh_config['nx'], mesh_config['ny']
    u = np.loadtxt(os.path.join(OUTPUT_DIR, 'velocity_u.csv'), delimiter=',')
    v = np.loadtxt(os.path.join(OUTPUT_DIR, 'velocity_v.csv'), delimiter=',')
    p = np.loadtxt(os.path.join(OUTPUT_DIR, 'pressure.csv'), delimiter=',')
    div = np.loadtxt(os.path.join(OUTPUT_DIR, 'divergence.csv'), delimiter=',')
    with open(os.path.join(OUTPUT_DIR, 'solver_info.json')) as f:
        info = json.load(f)
    return {'u': u, 'v': v, 'p': p, 'div': div, 'info': info, 'nx': nx, 'ny': ny}


def test_output_files_exist():
    """All required output files must be present."""
    for fname in ['velocity_u.csv', 'velocity_v.csv', 'pressure.csv',
                  'divergence.csv', 'solver_info.json']:
        fpath = os.path.join(OUTPUT_DIR, fname)
        assert os.path.isfile(fpath), f"Missing output file: {fname}"


def test_output_dimensions(fields):
    """Output arrays must match grid dimensions: ny rows x nx columns."""
    nx, ny = fields['nx'], fields['ny']
    for name in ['u', 'v', 'p', 'div']:
        arr = fields[name]
        assert arr.shape == (ny, nx), (
            f"{name} shape {arr.shape} != expected ({ny}, {nx})"
        )


def test_mass_conservation(fields):
    """Discrete divergence (from face velocities) must be near zero everywhere."""
    max_div = np.max(np.abs(fields['div']))
    assert max_div < 1e-4, (
        f"Max absolute divergence {max_div:.2e} exceeds tolerance 1e-4"
    )


def test_u_symmetry(fields):
    """u(x,y) = u(1-x,y): u-velocity must be symmetric about x=0.5."""
    u = fields['u']
    err = np.max(np.abs(u - u[:, ::-1]))
    assert err < 1e-5, f"u symmetry error: {err:.2e}"


def test_v_antisymmetry(fields):
    """v(x,y) = -v(1-x,y): v-velocity must be antisymmetric about x=0.5."""
    v = fields['v']
    err = np.max(np.abs(v + v[:, ::-1]))
    assert err < 1e-5, f"v antisymmetry error: {err:.2e}"


def test_pressure_antisymmetry(fields):
    """p(x,y) = -p(1-x,y): pressure must be antisymmetric about x=0.5."""
    p = fields['p']
    p_sum = p + p[:, ::-1]
    err = np.max(np.abs(p_sum))
    assert err < 1e-3, f"Pressure antisymmetry error: {err:.2e}"


def test_zero_mean_pressure(fields):
    """Pressure field must have zero mean."""
    mean_p = np.mean(fields['p'])
    assert abs(mean_p) < 1e-4, f"Non-zero mean pressure: {mean_p:.2e}"


def test_flow_direction(fields):
    """Flow must show lid-driven circulation: positive u near top, return flow below."""
    u = fields['u']
    nx = fields['nx']
    top_row_mean = np.mean(u[-1, :])
    assert top_row_mean > 0.3, (
        f"Mean u at top row = {top_row_mean:.4f}, expected > 0.3 (lid-driven flow)"
    )
    center_col = nx // 2
    u_centerline = u[:, center_col]
    assert np.any(u_centerline < 0), (
        "No return flow (negative u) detected along vertical centerline"
    )


def test_solver_convergence(fields):
    """Iterative solver must converge within the iteration budget."""
    info = fields['info']
    assert info['converged'] is True, "Solver did not converge"
    iters = info['iterations']
    assert iters > 1, f"Only {iters} iteration(s) — likely not an iterative solve"
    assert iters < 500, f"Too many iterations ({iters}), preconditioner may be wrong"


def test_velocity_bounds(fields):
    """Velocity magnitudes must be physically reasonable."""
    u, v = fields['u'], fields['v']
    speed = np.sqrt(u**2 + v**2)
    max_speed = np.max(speed)
    assert max_speed < 2.0, f"Max speed {max_speed:.2f} exceeds physical bounds"
    assert max_speed > 0.1, f"Max speed {max_speed:.4f} is suspiciously low"
