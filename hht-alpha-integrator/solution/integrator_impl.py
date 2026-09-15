
"""
Complete implementation of the HHT-alpha (Generalized-alpha) integrator
for index-3 DAEs in constrained multibody dynamics.
"""

import numpy as np


class HHTAlphaIntegrator:
    """
    Generalized-alpha integrator for index-3 DAEs.

    Solves:
        M * a + Phi_q(q)^T * lambda = F(t, q, v)
        Phi(q) = 0

    using Newmark-beta time discretization with generalized-alpha weighting.
    """

    def __init__(self, model, rho_inf=0.9, h=0.001,
                 newton_tol=1e-10, newton_max_iter=50):
        self.model = model
        self.h = h
        self.newton_tol = newton_tol
        self.newton_max_iter = newton_max_iter

        # Generalized-alpha parameters (Chung & Hulbert 1993)
        self.alpha_m = (2.0 * rho_inf - 1.0) / (rho_inf + 1.0)
        self.alpha_f = rho_inf / (rho_inf + 1.0)
        self.gamma_N = 0.5 - self.alpha_m + self.alpha_f
        self.beta_N = 0.25 * (self.gamma_N + 0.5) ** 2

    def compute_initial_accelerations(self, q0, v0):
        """
        Compute consistent initial accelerations and Lagrange multipliers.

        Solves the augmented linear system:
            [M,     Phi_q^T] [a0    ]   [F(0, q0, v0)]
            [Phi_q, 0      ] [lambda0] = [-gamma(q0, v0)]
        """
        model = self.model
        n_q = model.n_q
        n_c = model.n_c
        M = model.mass_matrix()
        F = model.forces(0.0, q0, v0)
        Phi_q = model.constraint_jacobian(q0)
        gam = model.gamma(q0, v0)

        A = np.zeros((n_q + n_c, n_q + n_c))
        A[:n_q, :n_q] = M
        A[:n_q, n_q:] = Phi_q.T
        A[n_q:, :n_q] = Phi_q

        rhs = np.zeros(n_q + n_c)
        rhs[:n_q] = F
        rhs[n_q:] = -gam

        sol = np.linalg.solve(A, rhs)
        return sol[:n_q], sol[n_q:]

    def step(self, t, q, v, a, lam):
        """
        Advance the solution by one time step using the generalized-alpha method.

        The constraint Jacobian in the dynamics residual is evaluated at the
        alpha-weighted state q_{n+1-alpha_f} (critical for second-order accuracy
        of the generalized-alpha method applied to index-3 DAEs).  The position
        constraint itself is enforced at q_{n+1}.
        """
        h = self.h
        beta = self.beta_N
        gamma = self.gamma_N
        alpha_m = self.alpha_m
        alpha_f = self.alpha_f
        model = self.model
        n_q = model.n_q
        n_c = model.n_c
        M = model.mass_matrix()

        a_new = a.copy()
        lam_new = lam.copy()

        for k in range(self.newton_max_iter):
            # Newmark updates
            q_new = q + h * v + h**2 * ((0.5 - beta) * a + beta * a_new)
            v_new = v + h * ((1.0 - gamma) * a + gamma * a_new)

            # Alpha-weighted quantities
            a_am = (1.0 - alpha_m) * a_new + alpha_m * a
            q_af = (1.0 - alpha_f) * q_new + alpha_f * q
            v_af = (1.0 - alpha_f) * v_new + alpha_f * v
            t_af = t + (1.0 - alpha_f) * h

            # Evaluate model — Phi_q for dynamics at q_af, constraint at q_new
            Phi = model.constraints(q_new)
            Phi_q_af = model.constraint_jacobian(q_af)
            Phi_q_new = model.constraint_jacobian(q_new)
            F_af = model.forces(t_af, q_af, v_af)

            # Dynamic residual (Phi_q at alpha-weighted state)
            R_dyn = M @ a_am + Phi_q_af.T @ lam_new - F_af
            R_con = Phi

            R = np.concatenate([R_dyn, R_con])

            if np.linalg.norm(R) < self.newton_tol:
                break

            # Tangent matrix
            J = np.zeros((n_q + n_c, n_q + n_c))
            J[:n_q, :n_q] = (1.0 - alpha_m) * M
            J[:n_q, n_q:] = Phi_q_af.T
            J[n_q:, :n_q] = h**2 * beta * Phi_q_new

            delta = np.linalg.solve(J, -R)
            a_new += delta[:n_q]
            lam_new += delta[n_q:]

        # Final updates
        q_new = q + h * v + h**2 * ((0.5 - beta) * a + beta * a_new)
        v_new = v + h * ((1.0 - gamma) * a + gamma * a_new)

        return t + h, q_new, v_new, a_new, lam_new

    def simulate(self, t_end, q0, v0, output_interval=1):
        """Run the simulation from t=0 to t_end."""
        model = self.model
        h = self.h
        n_steps = int(round(t_end / h))

        a0, lam0 = self.compute_initial_accelerations(q0, v0)

        times = [0.0]
        positions = [q0.copy()]
        velocities = [v0.copy()]
        violations = [np.linalg.norm(model.constraints(q0))]

        t = 0.0
        q = q0.copy()
        v = v0.copy()
        a = a0.copy()
        lam = lam0.copy()

        for i in range(1, n_steps + 1):
            t, q, v, a, lam = self.step(t, q, v, a, lam)

            if i % output_interval == 0:
                times.append(t)
                positions.append(q.copy())
                velocities.append(v.copy())
                violations.append(np.linalg.norm(model.constraints(q)))

        return {
            'time': np.array(times),
            'positions': np.array(positions),
            'velocities': np.array(velocities),
            'constraint_violations': np.array(violations),
        }
