/*
 * Velocity motion model for 2D EKF-SLAM.
 *
 * Provides C implementations of the motion update and its Jacobians,
 * callable from Python via ctypes.
 *
 * State vector: [x, y, theta]
 * Control input: [v, omega] (linear velocity, angular velocity)
 *
 */

#include <math.h>
#include <string.h>

/*
 * Apply velocity motion model: update robot state [x, y, theta] in place.
 */
void motion_update(double *state, double v, double omega, double dt) {
    double theta = state[2];
    state[0] += v * dt * sin(theta);
    state[1] += v * dt * cos(theta);
    state[2] += omega * dt;
    /* Normalize angle to [-pi, pi] */
    while (state[2] > M_PI) state[2] -= 2.0 * M_PI;
    while (state[2] < -M_PI) state[2] += 2.0 * M_PI;
}

/*
 * Jacobian of motion model w.r.t. robot state (3x3, row-major).
 * jac[row * 3 + col]
 */
void motion_jacobian(double *jac, double v, double dt, double theta) {
    memset(jac, 0, 9 * sizeof(double));
    jac[0] = 1.0;                    /* d(x')/dx       */
    jac[2] = -v * dt * sin(theta);   /* d(x')/d(theta) */
    jac[4] = 1.0;                    /* d(y')/dy       */
    jac[5] =  v * dt * cos(theta);   /* d(y')/d(theta) */
    jac[8] = 1.0;                    /* d(theta')/d(theta) */
}

/*
 * Jacobian of motion model w.r.t. control noise [eps_v, eps_omega]
 * (3x2, row-major). vt[row * 2 + col]
 */
void noise_jacobian(double *vt, double v, double dt, double theta) {
    memset(vt, 0, 6 * sizeof(double));
    vt[0] = dt * cos(theta);    /* d(x')/d(eps_v)       */
    vt[2] = dt * sin(theta);    /* d(y')/d(eps_v)       */
    vt[5] = dt;                 /* d(theta')/d(eps_omega) */
}
