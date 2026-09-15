/* QCM-D transfer matrix forward computation - C shared library */

#include <complex.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* |G*|rho at overtone n */
static double _grho(int n, double grho3, double phi) {
    return grho3 * pow((double)n / 3.0, phi / 90.0);
}

/* Complex acoustic impedance */
static double complex _zstar(int n, double grho3, double phi) {
    double grho_n = _grho(n, grho3, phi);
    double complex gstar = grho_n * cexp(I * M_PI * phi / 180.0);
    return csqrt(gstar);
}

/* Complex wavenumber-thickness product */
static double complex _calc_D(int n, double grho3, double phi,
                               double drho, double f1) {
    double complex z = _zstar(n, grho3, phi);
    return 2.0 * M_PI * (double)n * f1 * drho / z;
}

/*
 * Compute complex frequency shift for a layered stack on quartz.
 */
void qcm_delfstar(int n, int nlayers,
                   const double *grho3, const double *phi_deg,
                   const double *drho,
                   double f1, double zq,
                   double *out_delf, double *out_delg) {
    int last = nlayers - 1;

    /* Terminal impedance from outermost layer */
    double complex Zf;
    if (drho[last] > 1e100) {
        Zf = _zstar(n, grho3[last], phi_deg[last]);
    } else {
        double complex D_last = _calc_D(n, grho3[last], phi_deg[last],
                                         drho[last], f1);
        double complex z_last = _zstar(n, grho3[last], phi_deg[last]);
        Zf = I * z_last * csin(D_last) / ccos(D_last);
    }

    /* Single layer */
    if (nlayers == 1) {
        double complex dfs = f1 * I * Zf / (M_PI * zq);
        *out_delf = creal(dfs);
        *out_delg = cimag(dfs);
        return;
    }

    /* Multi-layer: transfer matrix propagation */
    double complex Z[nlayers];
    double complex Lp[nlayers];
    double complex Lm[nlayers];
    int i;

    for (i = 0; i < last; i++) {
        Z[i] = _zstar(n, grho3[i], phi_deg[i]);
        double complex D_i = _calc_D(n, grho3[i], phi_deg[i], drho[i], f1);
        double complex cosD = ccos(D_i);
        double complex sinD = csin(D_i);
        Lp[i] = cosD + I * sinD;
        Lm[i] = cosD - I * sinD;
    }

    /* Terminal vector from outermost interface */
    double complex u0 = Lp[last - 1] * (1.0 + Z[last - 1] / Zf);
    double complex u1 = Lm[last - 1] * (1.0 - Z[last - 1] / Zf);

    /* Propagate inward through remaining layers */
    for (i = last - 2; i >= 0; i--) {
        double complex ratio = Z[i + 1] / Z[i];
        double complex sp = 1.0 + ratio;
        double complex sm = 1.0 - ratio;

        double complex new_u0 = sp * u0 + sm * u1;
        double complex new_u1 = sm * u0 + sp * u1;

        u0 = Lp[i] * new_u0;
        u1 = Lm[i] * new_u1;
    }

    double complex rstar = u1 / u0;
    double complex ZL = Z[0] * (1.0 - rstar) / (1.0 + rstar);

    double complex dfs = f1 * I * ZL / (M_PI * zq);
    *out_delf = creal(dfs);
    *out_delg = cimag(dfs);
}
