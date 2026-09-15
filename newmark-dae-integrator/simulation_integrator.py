"""
Newmark-Beta integrator for the index-3 DAE system.


The Newmark-beta method for constrained mechanical systems solves:

    M * a + Phi_v^T * lambda = f(t, q, v)
    Phi(q) = 0

Using the Newmark update formulas:
    q_{n+1} = q_n + h * L_n * v_n + h^2 * L_n * ((0.5 - beta) * a_n + beta * a_{n+1})
    v_{n+1} = v_n + h * ((1 - gamma) * a_n + gamma * a_{n+1})

Where:
    - beta, gamma are Newmark parameters
    - L is the velocity transformation matrix (dq/dt = L * v)
    - h is the timestep

With Baumgarte stabilization, the acceleration-level constraint becomes:
    Phi_v * a = gamma_term - 2*alpha*Phi_v*v - beta_b^2*Phi

where alpha, beta_b are the Baumgarte parameters (not the Newmark ones).
"""

import numpy as np
from constraints import compute_constraints, compute_jacobian, compute_gamma


class NewmarkBetaDAE:
    """Newmark-Beta integrator for constrained multibody DAE systems."""

    def __init__(self, system, config):
        self.system = system
        self.config = config
        self.h = config.TIMESTEP
        self.beta = config.NEWMARK_BETA
        self.gamma_nm = config.NEWMARK_GAMMA
        self.alpha_b = config.BAUMGARTE_ALPHA
        self.beta_b = config.BAUMGARTE_BETA
        self.max_iter = config.NEWTON_MAX_ITER
        self.tol = config.NEWTON_TOL

        # Lagrange multipliers
        self.lam = np.zeros(system.n_constraints)

        # Iteration statistics
        self.total_iterations = 0
        self.total_steps = 0

    def _assemble_iteration_matrix(self):
        """
        Assemble the (n_vel + n_constraints) x (n_vel + n_constraints)
        iteration matrix for the Newton-Raphson solve.

        The saddle-point system is:
            [M_eff   Phi_v^T] [da    ]   [-r_dyn ]
            [Phi_v   0      ] [dlambda] = [-r_con ]

        where M_eff is the effective mass matrix. For the standard Newmark
        formulation iterating on accelerations, M_eff = M (the mass matrix).

        TODO: Assemble this matrix. Currently returns zeros.
        """
        n_v = self.system.n_vel
        n_c = self.system.n_constraints
        n_total = n_v + n_c

        A = np.zeros((n_total, n_total))

        # ========================================================
        # TODO: Fill in the iteration matrix
        #
        # Top-left block (n_v x n_v): effective mass matrix M
        # Top-right block (n_v x n_c): Phi_v^T (transpose of constraint Jacobian)
        # Bottom-left block (n_c x n_v): Phi_v (constraint Jacobian)
        # Bottom-right block (n_c x n_c): zeros
        #
        # Use:
        #   self.system.get_mass_matrix()  -> 12x12
        #   compute_jacobian(self.system)  -> 6x12
        # ========================================================

        return A

    def _compute_residual(self, q_new, v_new, a_new, lam_new, q_old, v_old, a_old):
        """
        Compute the residual vector for the Newton iteration.

        The residual has two parts:
        1. Dynamic residual (12-vector):
           r_dyn = M * a_new + Phi_v^T * lam_new - f(q_new, v_new)

        2. Constraint residual with Baumgarte stabilization (6-vector):
           r_con = Phi_v * a_new - gamma + 2*alpha_b*Phi_v*v_new + beta_b^2*Phi(q_new)

        TODO: Compute the full residual. Currently returns zeros.
        """
        n_v = self.system.n_vel
        n_c = self.system.n_constraints
        r = np.zeros(n_v + n_c)

        # ========================================================
        # TODO: Compute residual vector
        #
        # Steps:
        # 1. Set system state to (q_new, v_new, a_new)
        # 2. Get mass matrix M, force vector f, constraint Jacobian Phi_v
        # 3. Evaluate constraints Phi and gamma term
        # 4. r[0:n_v] = M @ a_new + Phi_v.T @ lam_new - f
        # 5. r[n_v:] = Phi_v @ a_new - gamma + 2*alpha_b*(Phi_v @ v_new) + beta_b^2 * Phi
        # ========================================================

        return r

    def _update_state(self, a_new, q_old, v_old, a_old):
        """
        Apply the Newmark-beta update formulas to compute new positions
        and velocities from the new accelerations.

        Newmark velocity update:
            v_{n+1} = v_old + h * ((1 - gamma_nm) * a_old + gamma_nm * a_new)

        Newmark position update (using the velocity transformation L):
            q_{n+1} = q_old + h * L * v_old + h^2 * L * ((0.5 - beta)*a_old + beta*a_new)

        After updating positions, renormalize the quaternions (indices 3:7 and 10:14).

        TODO: Implement the update. Currently returns unchanged values.

        Returns: (q_new, v_new)
        """
        h = self.h

        # ========================================================
        # TODO: Apply Newmark update formulas
        #
        # 1. Compute v_new using the velocity update formula
        # 2. Get the velocity transformation matrix L at the OLD configuration
        #    by calling self.system.set_all_coords(q_old) then self.system.get_L_matrix()
        # 3. Compute q_new using the position update formula
        # 4. Normalize quaternions in q_new (indices 3:7 and 10:14)
        # ========================================================

        q_new = q_old.copy()
        v_new = v_old.copy()

        return q_new, v_new

    def step(self):
        """
        Perform one time step of the Newmark-beta integrator.

        Returns: (converged: bool, n_iters: int)
        """
        # Save old state
        q_old = self.system.get_all_coords()
        v_old = self.system.get_all_velocities()
        a_old = self.system.get_all_accelerations()

        # Initial guess for new accelerations: a_new = a_old
        a_new = a_old.copy()
        lam_new = self.lam.copy()

        n_v = self.system.n_vel
        n_c = self.system.n_constraints

        converged = False
        n_iters = 0

        for k in range(self.max_iter):
            n_iters += 1

            # Update positions and velocities from current acceleration guess
            q_new, v_new = self._update_state(a_new, q_old, v_old, a_old)

            # Set the system state
            self.system.set_all_coords(q_new)
            self.system.set_all_velocities(v_new)
            self.system.set_all_accelerations(a_new)

            # Compute residual
            r = self._compute_residual(q_new, v_new, a_new, lam_new,
                                       q_old, v_old, a_old)

            # Check convergence
            if np.linalg.norm(r) < self.tol:
                converged = True
                break

            # Assemble and solve the linear system
            A = self._assemble_iteration_matrix()

            try:
                delta = np.linalg.solve(A, -r)
            except np.linalg.LinAlgError:
                break

            # Extract corrections
            da = delta[0:n_v]
            dlam = delta[n_v:]

            # Apply corrections
            a_new += da
            lam_new += dlam

        # Final state update
        q_new, v_new = self._update_state(a_new, q_old, v_old, a_old)
        self.system.set_all_coords(q_new)
        self.system.set_all_velocities(v_new)
        self.system.set_all_accelerations(a_new)
        self.lam = lam_new

        self.total_iterations += n_iters
        self.total_steps += 1

        return converged, n_iters
