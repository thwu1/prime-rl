
#include <math.h>

#define LANDEN_MAX 50

static double complement_k(double k) {
    return sqrt((1.0 - k) * (1.0 + k));
}

static int landen_descending(double k, double *ks) {
    ks[0] = k;
    double kn = k;
    int n = 0;
    int iter;
    for (iter = 0; iter < LANDEN_MAX - 1; iter++) {
        if (kn < 1e-17) break;
        double kp = complement_k(kn);
        double ratio = kn / (1.0 + kp);
        double kn_next = ratio * ratio;
        n++;
        ks[n] = kn_next;
        kn = kn_next;
    }
    return n;
}

void ellipk_c(double k, double *K_out, double *Kp_out) {
    int i;
    if (k <= 0.0) {
        *K_out = M_PI / 2.0;
        *Kp_out = 1e30;
        return;
    }
    if (k >= 1.0) {
        *K_out = 1e30;
        *Kp_out = M_PI / 2.0;
        return;
    }

    double ks[LANDEN_MAX];
    int n = landen_descending(k, ks);

    double K = M_PI / 2.0;
    for (i = 1; i <= n; i++) {
        K *= (1.0 + ks[i]);
    }
    *K_out = K;

    double kp = complement_k(k);
    if (kp <= 0.0) {
        *Kp_out = 1e30;
        return;
    }

    double ksp[LANDEN_MAX];
    int np = landen_descending(kp, ksp);

    double Kp = M_PI / 2.0;
    for (i = 1; i <= np; i++) {
        Kp *= (1.0 + ksp[i]);
    }
    *Kp_out = Kp;
}

double cd_c(double u, double k) {
    int i;
    if (k <= 0.0) {
        return cos(M_PI / 2.0 * u);
    }

    double ks[LANDEN_MAX];
    int n = landen_descending(k, ks);

    double y = cos(M_PI / 2.0 * u);

    for (i = n - 1; i >= 0; i--) {
        double ki = ks[i + 1];
        y = (1.0 + ki) * y / (1.0 + ki * y * y);
    }

    return y;
}
