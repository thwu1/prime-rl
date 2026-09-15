"""
Solution: Apply all fixes to the spatial double pendulum simulation.


This script patches:
1. Makefile: build shared library (.so) with -fPIC instead of static (.a)
2. C code: fix sign error in constraint Jacobian (dC2/domega2 block)
3. config.py: set Baumgarte stabilization parameters for critical damping
4. integrator.py: complete all TODO methods
"""

# ============================================================
# 1. Fix the Makefile — build shared library with -fPIC
# ============================================================
makefile_content = "CC = gcc\nCFLAGS = -O2 -Wall -fPIC\n\nall: libconstraints.so\n\nlibconstraints.so: constraints_native.o\n\t$(CC) -shared -o $@ $^\n\nconstraints_native.o: constraints_native.c\n\t$(CC) $(CFLAGS) -c $< -o $@\n\nclean:\n\trm -f *.o *.so\n"

with open('/app/native/Makefile', 'w') as f:
    f.write(makefile_content)

# ============================================================
# 2. Fix the C code — correct sign error in dC2/domega2
# ============================================================
c_code = r'''/*
 * Native C implementation of the constraint Jacobian for the spatial
 * double pendulum simulation.
 *
 */

#include <string.h>

static void skew3(const double *v, double *S)
{
    S[0] =  0.0;   S[1] = -v[2];  S[2] =  v[1];
    S[3] =  v[2];  S[4] =  0.0;   S[5] = -v[0];
    S[6] = -v[1];  S[7] =  v[0];  S[8] =  0.0;
}

static void mat3_mul(const double *A, const double *B, double *C)
{
    int i, j, k;
    for (i = 0; i < 3; i++)
        for (j = 0; j < 3; j++) {
            double sum = 0.0;
            for (k = 0; k < 3; k++)
                sum += A[i*3 + k] * B[k*3 + j];
            C[i*3 + j] = sum;
        }
}

void compute_jacobian_native(
    const double *R1, const double *R2,
    const double *s1_top, const double *s1_bot, const double *s2_top,
    double *Phi_v)
{
    double S[9], RS[9];
    int i, j;

    memset(Phi_v, 0, 72 * sizeof(double));

    /* Joint 1 (rows 0-2): link1 top = pivot */
    Phi_v[0*12 + 0] = 1.0;
    Phi_v[1*12 + 1] = 1.0;
    Phi_v[2*12 + 2] = 1.0;

    /* dC1/domega1 = -R1 * skew(s1_top) */
    skew3(s1_top, S);
    mat3_mul(R1, S, RS);
    for (i = 0; i < 3; i++)
        for (j = 0; j < 3; j++)
            Phi_v[i*12 + (3+j)] = -RS[i*3 + j];

    /* Joint 2 (rows 3-5): link1 bottom = link2 top */
    Phi_v[3*12 + 0] = 1.0;
    Phi_v[4*12 + 1] = 1.0;
    Phi_v[5*12 + 2] = 1.0;

    /* dC2/domega1 = -R1 * skew(s1_bot) */
    skew3(s1_bot, S);
    mat3_mul(R1, S, RS);
    for (i = 0; i < 3; i++)
        for (j = 0; j < 3; j++)
            Phi_v[(3+i)*12 + (3+j)] = -RS[i*3 + j];

    /* dC2/dv2 = -I_3 */
    Phi_v[3*12 + 6] = -1.0;
    Phi_v[4*12 + 7] = -1.0;
    Phi_v[5*12 + 8] = -1.0;

    /* dC2/domega2 = R2 * skew(s2_top) — FIXED: positive sign */
    skew3(s2_top, S);
    mat3_mul(R2, S, RS);
    for (i = 0; i < 3; i++)
        for (j = 0; j < 3; j++)
            Phi_v[(3+i)*12 + (9+j)] = RS[i*3 + j];
}
'''

with open('/app/native/constraints_native.c', 'w') as f:
    f.write(c_code)

# ============================================================
# 3. Fix config.py — set Baumgarte stabilization parameters
# ============================================================
config_content = '''"""
Configuration parameters for the double pendulum DAE simulation.

"""

import numpy as np

GRAVITY = np.array([0.0, 0.0, -9.81])

LINK1_LENGTH = 1.0
LINK1_MASS = 2.0
LINK1_RADIUS = 0.02
LINK1_INERTIA = np.diag([0.5 * 2.0 * 0.02**2, 2.0 * 1.0**2 / 12.0, 2.0 * 1.0**2 / 12.0])

LINK2_LENGTH = 0.8
LINK2_MASS = 1.5
LINK2_RADIUS = 0.02
LINK2_INERTIA = np.diag([0.5 * 1.5 * 0.02**2, 1.5 * 0.8**2 / 12.0, 1.5 * 0.8**2 / 12.0])

PIVOT_POINT = np.array([0.0, 0.0, 0.0])

TIMESTEP = 0.001
T_FINAL = 10.0
NEWMARK_BETA = 0.25
NEWMARK_GAMMA = 0.5

NEWTON_MAX_ITER = 50
NEWTON_TOL = 1e-10

# Baumgarte stabilization: critically damped
BAUMGARTE_ALPHA = 5.0
BAUMGARTE_BETA = 5.0
'''

with open('/app/simulation/config.py', 'w') as f:
    f.write(config_content)

# ============================================================
# 4. Fix integrator.py — complete all TODO methods
# ============================================================
integrator_content = '''"""
Newmark-Beta integrator for the index-3 DAE system.

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

        self.lam = np.zeros(system.n_constraints)

        self.total_iterations = 0
        self.total_steps = 0

    def _assemble_iteration_matrix(self):
        """Assemble the bordered saddle-point iteration matrix."""
        n_v = self.system.n_vel
        n_c = self.system.n_constraints
        n_total = n_v + n_c

        A = np.zeros((n_total, n_total))

        M = self.system.get_mass_matrix()
        Phi_v = compute_jacobian(self.system)

        A[0:n_v, 0:n_v] = M
        A[0:n_v, n_v:n_total] = Phi_v.T
        A[n_v:n_total, 0:n_v] = Phi_v

        return A

    def _compute_residual(self, q_new, v_new, a_new, lam_new, q_old, v_old, a_old):
        """Compute the combined dynamic and constraint residual."""
        n_v = self.system.n_vel
        n_c = self.system.n_constraints
        r = np.zeros(n_v + n_c)

        self.system.set_all_coords(q_new)
        self.system.set_all_velocities(v_new)
        self.system.set_all_accelerations(a_new)

        M = self.system.get_mass_matrix()
        f = self.system.get_force_vector()
        Phi_v = compute_jacobian(self.system)
        Phi = compute_constraints(self.system)
        gam = compute_gamma(self.system)

        r[0:n_v] = M @ a_new + Phi_v.T @ lam_new - f

        r[n_v:] = (Phi_v @ a_new - gam
                   + 2.0 * self.alpha_b * (Phi_v @ v_new)
                   + self.beta_b**2 * Phi)

        return r

    def _update_state(self, a_new, q_old, v_old, a_old):
        """Apply Newmark update formulas and quaternion renormalization."""
        h = self.h

        v_new = v_old + h * ((1.0 - self.gamma_nm) * a_old + self.gamma_nm * a_new)

        self.system.set_all_coords(q_old)
        L = self.system.get_L_matrix()

        q_new = q_old + h * L @ v_old + h**2 * L @ ((0.5 - self.beta) * a_old + self.beta * a_new)

        # Renormalize quaternions
        q1_quat = q_new[3:7]
        q1_quat /= np.linalg.norm(q1_quat)
        q_new[3:7] = q1_quat

        q2_quat = q_new[10:14]
        q2_quat /= np.linalg.norm(q2_quat)
        q_new[10:14] = q2_quat

        return q_new, v_new

    def step(self):
        """Perform one time step. Returns: (converged, n_iters)."""
        q_old = self.system.get_all_coords()
        v_old = self.system.get_all_velocities()
        a_old = self.system.get_all_accelerations()

        a_new = a_old.copy()
        lam_new = self.lam.copy()

        n_v = self.system.n_vel
        n_c = self.system.n_constraints

        converged = False
        n_iters = 0

        for k in range(self.max_iter):
            n_iters += 1

            q_new, v_new = self._update_state(a_new, q_old, v_old, a_old)

            self.system.set_all_coords(q_new)
            self.system.set_all_velocities(v_new)
            self.system.set_all_accelerations(a_new)

            r = self._compute_residual(q_new, v_new, a_new, lam_new,
                                       q_old, v_old, a_old)

            if np.linalg.norm(r) < self.tol:
                converged = True
                break

            A = self._assemble_iteration_matrix()

            try:
                delta = np.linalg.solve(A, -r)
            except np.linalg.LinAlgError:
                break

            da = delta[0:n_v]
            dlam = delta[n_v:]

            a_new += da
            lam_new += dlam

        q_new, v_new = self._update_state(a_new, q_old, v_old, a_old)
        self.system.set_all_coords(q_new)
        self.system.set_all_velocities(v_new)
        self.system.set_all_accelerations(a_new)
        self.lam = lam_new

        self.total_iterations += n_iters
        self.total_steps += 1

        return converged, n_iters
'''

with open('/app/simulation/integrator.py', 'w') as f:
    f.write(integrator_content)

print("Solution applied successfully.")
