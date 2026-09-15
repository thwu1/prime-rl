"""
DGSEM framework for 1D compressible Euler equations.

Provides LGL quadrature, Euler equation routines, mesh handling,
split-form DG spatial discretization, and SSP-RK3 time integration.
"""
import numpy as np
from numpy.polynomial import legendre

GAMMA = 1.4


def lgl_nodes_weights(N):
    """Compute N+1 Legendre-Gauss-Lobatto nodes and weights on [-1,1]."""
    if N == 0:
        return np.array([0.0]), np.array([2.0])
    if N == 1:
        return np.array([-1.0, 1.0]), np.array([1.0, 1.0])
    c = np.zeros(N + 1)
    c[N] = 1.0
    dc = legendre.legder(c)
    interior = np.sort(np.real(legendre.legroots(dc)))
    nodes = np.concatenate([[-1.0], interior, [1.0]])
    weights = np.zeros(N + 1)
    for j in range(N + 1):
        Pn = legendre.legval(nodes[j], c)
        weights[j] = 2.0 / (N * (N + 1) * Pn**2)
    return nodes, weights


def derivative_matrix(nodes):
    """Polynomial derivative matrix D[i,j] = l'_j(x_i)."""
    n = len(nodes)
    bw = np.ones(n)
    for j in range(n):
        for k in range(n):
            if k != j:
                bw[j] /= (nodes[j] - nodes[k])
    D = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i != j:
                D[i, j] = bw[j] / bw[i] / (nodes[i] - nodes[j])
        D[i, i] = -np.sum(D[i, :])
    return D


def cons2prim(u):
    """Conservative [rho, rho*v, E] -> primitive (rho, v, p)."""
    rho = u[0]
    v = u[1] / rho
    p = (GAMMA - 1.0) * (u[2] - 0.5 * rho * v**2)
    return rho, v, p


def prim2cons(rho, v, p):
    """Primitive (rho, v, p) -> conservative [rho, rho*v, E]."""
    return np.array([rho, rho * v, p / (GAMMA - 1.0) + 0.5 * rho * v**2])


def euler_flux(u):
    """Physical flux for 1D Euler equations."""
    rho, v, p = cons2prim(u)
    return np.array([rho * v, rho * v**2 + p, (u[2] + p) * v])


def max_wavespeed(u):
    """Maximum absolute eigenvalue |v| + a."""
    rho, v, p = cons2prim(u)
    return abs(v) + np.sqrt(GAMMA * p / rho)


def euler_entropy(u):
    """Mathematical entropy S = -rho*s/(gamma-1), s = ln(p) - gamma*ln(rho)."""
    rho, v, p = cons2prim(u)
    s = np.log(p) - GAMMA * np.log(rho)
    return -rho * s / (GAMMA - 1.0)


class Mesh1D:
    """Uniform 1D mesh on [xmin, xmax] with K elements."""

    def __init__(self, xmin, xmax, K):
        self.xmin, self.xmax, self.K = xmin, xmax, K
        self.dx = (xmax - xmin) / K
        self.edges = np.linspace(xmin, xmax, K + 1)

    def jacobian(self):
        return 0.5 * self.dx

    def physical_coords(self, k, xi):
        xl, xr = self.edges[k], self.edges[k + 1]
        return 0.5 * (xl + xr) + 0.5 * (xr - xl) * xi


class DGSolver:
    """Split-form DGSEM solver for 1D systems of conservation laws.

    Uses flux differencing in the volume integral with a two-point volume flux,
    and a separate numerical flux for inter-element surfaces. The strong-form
    DG scheme reads:

        du_i/dt = -(2/J) sum_j D_{ij} f_vol(u_i, u_j)
                  + (1/(J w_N)) [f(u_N) - f_num_R] delta_{i,N}
                  - (1/(J w_0)) [f(u_0) - f_num_L] delta_{i,0}
    """

    def __init__(self, mesh, N, volume_flux, surface_flux, bc='periodic'):
        self.mesh = mesh
        self.N = N
        self.Np = N + 1
        self.K = mesh.K
        self.bc = bc
        self.volume_flux_func = volume_flux
        self.surface_flux_func = surface_flux

        self.nodes, self.weights = lgl_nodes_weights(N)
        self.D = derivative_matrix(self.nodes)

        self.u = np.zeros((self.K, self.Np, 3))
        self.x = np.zeros((self.K, self.Np))
        for k in range(self.K):
            self.x[k] = mesh.physical_coords(k, self.nodes)

    def initialize(self, ic_func):
        """Set initial condition from ic_func(x) -> [rho, rho*v, E]."""
        for k in range(self.K):
            for i in range(self.Np):
                self.u[k, i] = ic_func(self.x[k, i])

    def _neighbor_state(self, k, side):
        """Return the solution value at the neighbor's interface node."""
        if side == 'left':
            kn = k - 1
            if kn < 0:
                if self.bc == 'periodic':
                    return self.u[self.K - 1, -1]
                else:
                    return self.u[k, 0].copy()
            return self.u[kn, -1]
        else:
            kn = k + 1
            if kn >= self.K:
                if self.bc == 'periodic':
                    return self.u[0, 0]
                else:
                    return self.u[k, -1].copy()
            return self.u[kn, 0]

    def compute_rhs(self):
        """Compute du/dt using split-form DG with surface corrections."""
        K, Np = self.K, self.Np
        J = self.mesh.jacobian()
        rhs = np.zeros_like(self.u)

        for k in range(K):
            # Volume integral (flux differencing)
            for i in range(Np):
                vol = np.zeros(3)
                for j in range(Np):
                    vol += self.D[i, j] * self.volume_flux_func(
                        self.u[k, i], self.u[k, j])
                rhs[k, i] = -2.0 * vol / J

            # Surface corrections
            u_ext_L = self._neighbor_state(k, 'left')
            u_ext_R = self._neighbor_state(k, 'right')
            f_num_L = self.surface_flux_func(u_ext_L, self.u[k, 0])
            f_num_R = self.surface_flux_func(self.u[k, -1], u_ext_R)

            # Left face (i=0): subtract (f(u_0) - f_num_L) / (J * w_0)
            rhs[k, 0] -= (euler_flux(self.u[k, 0]) - f_num_L) / \
                (J * self.weights[0])
            # Right face (i=N): add (f(u_N) - f_num_R) / (J * w_N)
            rhs[k, -1] += (euler_flux(self.u[k, -1]) - f_num_R) / \
                (J * self.weights[-1])

        return rhs

    def compute_dt(self, cfl):
        """Estimate stable time step based on CFL condition."""
        max_speed = 0.0
        for k in range(self.K):
            for i in range(self.Np):
                max_speed = max(max_speed, max_wavespeed(self.u[k, i]))
        dx_eff = self.mesh.dx / (2 * self.N + 1)
        return cfl * dx_eff / max_speed if max_speed > 0 else 1e-6

    def ssp_rk3_step(self, dt):
        """Third-order strong-stability-preserving Runge-Kutta."""
        u0 = self.u.copy()
        self.u = u0 + dt * self.compute_rhs()
        u1 = self.u.copy()
        self.u = 0.75 * u0 + 0.25 * (u1 + dt * self.compute_rhs())
        u2 = self.u.copy()
        self.u = (1.0 / 3.0) * u0 + (2.0 / 3.0) * (u2 + dt * self.compute_rhs())

    def run(self, t_final, cfl=0.1):
        """Advance solution to t_final."""
        t = 0.0
        step = 0
        while t < t_final - 1e-14:
            dt = min(self.compute_dt(cfl), t_final - t)
            self.ssp_rk3_step(dt)
            t += dt
            step += 1
        return t

    def get_solution_arrays(self):
        """Return sorted (x, u) arrays flattened across elements."""
        x_flat = self.x.flatten()
        u_flat = self.u.reshape(-1, 3)
        idx = np.argsort(x_flat)
        return x_flat[idx], u_flat[idx]


def ic_smooth_wave(x):
    """Smooth density wave: rho=1+0.2*sin(2*pi*x), v=1, p=1."""
    return prim2cons(1.0 + 0.2 * np.sin(2 * np.pi * x), 1.0, 1.0)


def exact_smooth_wave(x, t):
    """Exact solution of smooth density wave at time t (advects at v=1)."""
    return prim2cons(1.0 + 0.2 * np.sin(2 * np.pi * (x - t)), 1.0, 1.0)


def ic_sod(x):
    """Sod shock tube: left=(1,0,1), right=(0.125,0,0.1) at x=0.5."""
    if x < 0.5:
        return prim2cons(1.0, 0.0, 1.0)
    else:
        return prim2cons(0.125, 0.0, 0.1)
