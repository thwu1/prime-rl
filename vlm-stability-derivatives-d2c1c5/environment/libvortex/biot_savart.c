
#include <math.h>
#include "vortex.h"

/* ---------- vector helpers ---------- */

static void cross3(const double *a, const double *b, double *out) {
    out[0] = a[1]*b[2] - a[2]*b[1];
    out[1] = a[2]*b[0] - a[0]*b[2];
    out[2] = a[0]*b[1] - a[1]*b[0];
}

static double dot3(const double *a, const double *b) {
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
}

static double norm3(const double *v) {
    return sqrt(dot3(v, v));
}

/* ---------- public API ---------- */

void biot_savart_finite(const double *P, const double *A, const double *B,
                        double *vel) {
    int i;
    double r1[3], r2[3], r0[3], cr[3];

    for (i = 0; i < 3; i++) r1[i] = P[i] - A[i];
    for (i = 0; i < 3; i++) r2[i] = P[i] - B[i];
    for (i = 0; i < 3; i++) r0[i] = B[i] - A[i];

    double r1n = norm3(r1);
    double r2n = norm3(r2);
    if (r1n < 1e-12 || r2n < 1e-12) {
        vel[0] = vel[1] = vel[2] = 0.0;
        return;
    }

    cross3(r1, r2, cr);
    double cr_sq = dot3(cr, cr);
    if (cr_sq < 1e-20) {
        vel[0] = vel[1] = vel[2] = 0.0;
        return;
    }

    double K = 0.0;
    for (i = 0; i < 3; i++) K += r0[i] * (r1[i] / r1n - r2[i] / r2n);

    double c = K / cr_sq;
    for (i = 0; i < 3; i++) vel[i] = c * cr[i];
}


void biot_savart_semi_inf(const double *P, const double *Q, const double *d,
                          double *vel) {
    int i;
    double r[3], cr[3];

    for (i = 0; i < 3; i++) r[i] = P[i] - Q[i];

    double rn = norm3(r);
    if (rn < 1e-12) {
        vel[0] = vel[1] = vel[2] = 0.0;
        return;
    }

    cross3(r, d, cr);

    double cr_sq = dot3(cr, cr);
    if (cr_sq < 1e-20) {
        vel[0] = vel[1] = vel[2] = 0.0;
        return;
    }

    double K = (1.0 + dot3(d, r) / rn) / cr_sq;
    for (i = 0; i < 3; i++) vel[i] = K * cr[i];
}


void horseshoe_velocity(const double *P, const double *A, const double *B,
                        const double *d_inf, double *vel) {
    int i;
    double vb[3], vl[3], vr[3];

    biot_savart_finite(P, A, B, vb);
    biot_savart_semi_inf(P, A, d_inf, vl);
    biot_savart_semi_inf(P, B, d_inf, vr);

    for (i = 0; i < 3; i++) vel[i] = vb[i] - vl[i] + vr[i];
}
