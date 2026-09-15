/* QCM-D transfer matrix forward computation - C shared library */

#include <complex.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* Power-law |G*|rho at overtone n */
static double _grho(int n, double grho3, double phi) {
    return grho3 * pow((double)n / 3.0, phi / 90.0);
}

/* Complex acoustic impedance = sqrt(G* * rho) */
static double complex _zstar(int n, double grho3, double phi) {
    double grho_n = _grho(n, grho3, phi);
    double complex gstar = grho_n * cexp(I * M_PI * phi / 180.0);
    return csqrt(gstar);
}

/* D = 2*pi*n*f1*drho / Z* (complex wavenumber times thickness) */
static double complex _calc_D(int n, double grho3, double phi,
                               double drho, double f1) {
    double complex z = _zstar(n, grho3, phi);
    return 2.0 * M_PI * (double)n * f1 * drho / z;
}

/*
 * Compute complex frequency shift for a multi-layer stack on a
 * quartz crystal resonator using the acoustic impedance transfer-matrix
 * formalism with the small-load approximation (SLA).
 *
 * n        - harmonic number (1, 3, 5, 7, ...)
 * nlayers  - number of layers
 * grho3    - array[nlayers]: |G*|rho at n=3 for each layer
 * phi_deg  - array[nlayers]: loss angle in degrees for each layer
 * drho     - array[nlayers]: mass thickness (kg/m^2); >1e100 = semi-infinite
 * f1       - fundamental resonant frequency (Hz)
 * zq       - shear acoustic impedance of quartz (Pa*s/m)
 * out_delf - output: frequency shift Delta f (Hz)
 * out_delg - output: bandwidth shift Delta Gamma (Hz)
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
        /* Semi-infinite: for lossy medium, tan(D)->-j as D->inf,
           so j*Z*tan(D) -> j*Z*(-j) = Z */
        Zf = _zstar(n, grho3[last], phi_deg[last]);
    } else {
        double complex D_last = _calc_D(n, grho3[last], phi_deg[last],
                                         drho[last], f1);
        double complex z_last = _zstar(n, grho3[last], phi_deg[last]);
        Zf = I * z_last * csin(D_last) / ccos(D_last);
    }

    /* Single layer: ZL = Zf */
    if (nlayers == 1) {
        double complex dfs = f1 * I * Zf / (M_PI * zq);
        *out_delf = creal(dfs);
        *out_delg = cimag(dfs);
        return;
    }

    /* Multi-layer: transfer matrix propagation */
    /* Compute Z, D, L for inner layers (0..last-1) */
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
    double complex u0 = Lp[last - 1] * (1.0 + Zf / Z[last - 1]);
    double complex u1 = Lm[last - 1] * (1.0 - Zf / Z[last - 1]);

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

    /* Small-load approximation: delfstar = f1 * j * ZL / (pi * Zq) */
    double complex dfs = f1 * I * ZL / (M_PI * zq);
    *out_delf = creal(dfs);
    *out_delg = cimag(dfs);
}
