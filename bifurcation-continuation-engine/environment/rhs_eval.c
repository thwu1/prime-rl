/*
 * rhs_eval.c — C implementations of ODE system RHS and Jacobian functions.
 *
 * Calling conventions:
 *   void <prefix>_rhs(int n, const double *x, double param, double *f_out);
 *   void <prefix>_jac(int n, const double *x, double param, double *J_out);
 *
 * J_out is stored in row-major order (n x n).
 * Prefixes: cusp, brusselator, abc.
 *
 * Also provides: int get_system_count(void) — returns 3.
 *
 * Compile: gcc -shared -fPIC -o librhs.so rhs_eval.c -lm
 */


#include <math.h>

int get_system_count(void) {
    return 3;
}

/* ------------------------------------------------------------------ */
/* Cusp normal form (dim=1): dx/dt = mu + x - x^3                    */
/* ------------------------------------------------------------------ */

void cusp_rhs(int n, const double *x, double mu, double *out) {
    (void)n;
    out[0] = mu + x[0] - x[0] * x[0] * x[0];
}

void cusp_jac(int n, const double *x, double mu, double *out) {
    (void)n;
    (void)mu;
    out[0] = 1.0 - 3.0 * x[0] * x[0];
}

/* ------------------------------------------------------------------ */
/* Brusselator (dim=2, A=1.5 fixed, free parameter B)                */
/*   dx/dt = A - (B+1)*x + x^2*y                                     */
/*   dy/dt = B*x - x^2*y                                             */
/* ------------------------------------------------------------------ */

void brusselator_rhs(int n, const double *x, double B, double *out) {
    (void)n;
    double A = 1.5;
    out[0] = A - (B + 1.0) * x[0] + x[0] * x[0] * x[1];
    out[1] = B * x[0] - x[0] * x[0] * x[1];
}

void brusselator_jac(int n, const double *x, double B, double *out) {
    (void)n;
    /* Row-major 2x2 */
    out[0] = -(B + 1.0) + 2.0 * x[0] * x[1];
    out[1] = x[0] * x[0];
    out[2] = B - 2.0 * x[0] * x[1];
    out[3] = -x[0] * x[0];
}

/* ------------------------------------------------------------------ */
/* ABC Reaction (dim=3, p2=1, p3=1.5, p4=8, p5=0.04, free param p1) */
/*   du1/dt = -u1 + p1*(1-u1)*exp(u3)                                */
/*   du2/dt = -u2 + p1*exp(u3)*(1-u1-p5*u2)                         */
/*   du3/dt = -u3 - p3*u3 + p1*p4*exp(u3)*(1-u1+p2*p5*u2)          */
/* ------------------------------------------------------------------ */

void abc_rhs(int n, const double *x, double p1, double *out) {
    (void)n;
    double p3 = 1.5, p4 = 8.0, p5 = 0.04;
    double u1 = x[0], u2 = x[1], u3 = x[2];
    double e = exp(u3);
    out[0] = -u1 + p1 * (1.0 - u1) * e;
    out[1] = -u2 + p1 * e * (1.0 - u1 - p5 * u2);
    out[2] = -u3 - p3 * u3 + p1 * p4 * e * (1.0 - u1 + p5 * u2);
}

void abc_jac(int n, const double *x, double p1, double *out) {
    (void)n;
    double p3 = 1.5, p4 = 8.0, p5 = 0.04;
    double u1 = x[0], u2 = x[1], u3 = x[2];
    double e = exp(u3);
    /* Row-major 3x3 */
    out[0] = -1.0 - p1 * e;
    out[1] = 0.0;
    out[2] = p1 * (1.0 - u1) * e;
    out[3] = -p1 * e;
    out[4] = -1.0 - p1 * p5 * e;
    out[5] = p1 * e * (1.0 - u1 - p5 * u2);
    out[6] = -p1 * p4 * e;
    out[7] = p1 * p4 * p5 * e;
    out[8] = -(1.0 + p3) + p1 * p4 * e * (1.0 - u1 + p5 * u2);
}
