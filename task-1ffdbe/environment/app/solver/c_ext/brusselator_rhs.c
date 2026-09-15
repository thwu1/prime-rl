/*
 * C implementation of the 1D Brusselator reaction-diffusion RHS.
 *
 * State vector layout: interleaved [u_0, v_0, u_1, v_1, ..., u_{N-1}, v_{N-1}]
 * Dirichlet boundary conditions: u_boundary = A, v_boundary = B/A
 *
 * Compile as shared library:
 *   gcc -shared -fPIC -O2 -o librhs.so brusselator_rhs.c -lm
 */

void brusselator_rhs(const double *y, double *dydt, int N,
                     double Du, double Dv, double A, double B)
{
    double dx = 1.0 / (N + 1);
    double inv_dx2 = 1.0 / (dx * dx);

    double u_bc = A;
    double v_bc = B / A;

    int i;
    for (i = 0; i < N; i++) {
        double u_i = y[2 * i];
        double v_i = y[2 * i + 1];

        double u_left  = (i > 0)     ? y[2 * (i - 1)]     : u_bc;
        double u_right = (i < N - 1) ? y[2 * (i + 1)]     : u_bc;
        double v_left  = (i > 0)     ? y[2 * (i - 1) + 1] : v_bc;
        double v_right = (i < N - 1) ? y[2 * (i + 1) + 1] : v_bc;

        /* Diffusion + reaction for u */
        dydt[2 * i] = Du * (u_left - 2.0 * u_i + u_right) * inv_dx2
                      + A - (B + 1.0) * u_i + u_i * u_i * v_i;

        /* Diffusion + reaction for v */
        dydt[2 * i + 1] = Dv * (v_left - 2.0 * v_i + v_right) * inv_dx2
                          + B * u_i - u_i * u_i * v_i;
    }
}
