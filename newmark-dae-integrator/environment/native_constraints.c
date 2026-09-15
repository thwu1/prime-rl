/*
 * Native C implementation of the constraint Jacobian for the spatial
 * double pendulum simulation.
 *
 *
 * This library computes the 6x12 constraint Jacobian matrix Phi_v
 * for a two-link spatial pendulum with spherical joints.
 *
 * Velocity ordering: v = [v1(3), omega1(3), v2(3), omega2(3)]
 * Constraint ordering: C1(3) = joint1 (link1 top = pivot),
 *                      C2(3) = joint2 (link1 bot = link2 top)
 *
 * Build: make (produces libconstraints.so)
 */

#include <string.h>

/* Compute skew-symmetric matrix from 3-vector: S = skew(v)
 * Output is 3x3 in row-major order. */
static void skew3(const double *v, double *S)
{
    S[0] =  0.0;   S[1] = -v[2];  S[2] =  v[1];
    S[3] =  v[2];  S[4] =  0.0;   S[5] = -v[0];
    S[6] = -v[1];  S[7] =  v[0];  S[8] =  0.0;
}

/* 3x3 matrix multiply: C = A * B, all row-major */
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

/*
 * Compute the 6x12 constraint Jacobian for the spatial double pendulum.
 *
 * Parameters (all arrays row-major, doubles):
 *   R1      - rotation matrix of body 1 (9 elements, 3x3)
 *   R2      - rotation matrix of body 2 (9 elements, 3x3)
 *   s1_top  - body-local top attachment point, body 1 (3 elements)
 *   s1_bot  - body-local bottom attachment point, body 1 (3 elements)
 *   s2_top  - body-local top attachment point, body 2 (3 elements)
 *   Phi_v   - output Jacobian matrix (72 elements, 6 rows x 12 cols)
 *
 * For a spherical joint constraining body-local point s_i on body i:
 *   dC/dt = v_i - R_i * skew(s_i) * omega_i
 * So:
 *   dC/dv_i     = I_3
 *   dC/domega_i = -R_i * skew(s_i)
 *
 * For joint 2 connecting two bodies (link1 bot = link2 top):
 *   C2 = (r1 + R1*s1_bot) - (r2 + R2*s2_top)
 *   dC2/dv1     =  I_3
 *   dC2/domega1 = -R1 * skew(s1_bot)
 *   dC2/dv2     = -I_3
 *   dC2/domega2 =  R2 * skew(s2_top)
 */
void compute_jacobian_native(
    const double *R1, const double *R2,
    const double *s1_top, const double *s1_bot, const double *s2_top,
    double *Phi_v)
{
    double S[9], RS[9];
    int i, j;

    memset(Phi_v, 0, 72 * sizeof(double));

    /* --- Joint 1 (rows 0-2): link1 top = pivot --- */

    /* dC1/dv1 = I_3 (columns 0-2) */
    Phi_v[0*12 + 0] = 1.0;
    Phi_v[1*12 + 1] = 1.0;
    Phi_v[2*12 + 2] = 1.0;

    /* dC1/domega1 = -R1 * skew(s1_top) (columns 3-5) */
    skew3(s1_top, S);
    mat3_mul(R1, S, RS);
    for (i = 0; i < 3; i++)
        for (j = 0; j < 3; j++)
            Phi_v[i*12 + (3+j)] = -RS[i*3 + j];

    /* --- Joint 2 (rows 3-5): link1 bottom = link2 top --- */

    /* dC2/dv1 = I_3 (columns 0-2) */
    Phi_v[3*12 + 0] = 1.0;
    Phi_v[4*12 + 1] = 1.0;
    Phi_v[5*12 + 2] = 1.0;

    /* dC2/domega1 = -R1 * skew(s1_bot) (columns 3-5) */
    skew3(s1_bot, S);
    mat3_mul(R1, S, RS);
    for (i = 0; i < 3; i++)
        for (j = 0; j < 3; j++)
            Phi_v[(3+i)*12 + (3+j)] = -RS[i*3 + j];

    /* dC2/dv2 = -I_3 (columns 6-8) */
    Phi_v[3*12 + 6] = -1.0;
    Phi_v[4*12 + 7] = -1.0;
    Phi_v[5*12 + 8] = -1.0;

    /* dC2/domega2 = R2 * skew(s2_top) (columns 9-11) */
    skew3(s2_top, S);
    mat3_mul(R2, S, RS);
    for (i = 0; i < 3; i++)
        for (j = 0; j < 3; j++)
            Phi_v[(3+i)*12 + (9+j)] = -RS[i*3 + j];
}
