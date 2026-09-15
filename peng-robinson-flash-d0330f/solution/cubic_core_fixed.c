
#include <math.h>

double eos_pressure(double V, double T, double n, double a_mix, double b_mix,
                    double delta1, double delta2, double R) {
    double nb = n * b_mix;
    double rep = n * R * T / (V - nb);
    double denom = (V + nb * delta1) * (V + nb * delta2);
    double att = n * n * a_mix / denom;
    return rep - att;
}

int eos_solve_Z(double A, double B, double delta1, double delta2,
                double *roots) {
    double sigma = delta1 + delta2;
    double eps = delta1 * delta2;

    double c2 = B * (sigma - 1.0) - 1.0;
    double c1 = A + B * B * eps - B * B * sigma - B * sigma;
    double c0 = -A * B - B * B * eps * (1.0 + B);

    double p = c1 - c2 * c2 / 3.0;
    double q = c0 - c1 * c2 / 3.0 + 2.0 * c2 * c2 * c2 / 27.0;
    double disc = q * q / 4.0 + p * p * p / 27.0;

    double all[3];
    int nall = 0;

    if (disc > 1e-15) {
        double sq = sqrt(disc);
        double u = -q / 2.0 + sq;
        double v = -q / 2.0 - sq;
        u = copysign(pow(fabs(u), 1.0 / 3.0), u);
        v = copysign(pow(fabs(v), 1.0 / 3.0), v);
        all[0] = u + v - c2 / 3.0;
        nall = 1;
    } else {
        if (fabs(p) < 1e-30) {
            all[0] = -c2 / 3.0;
            nall = 1;
        } else {
            double r = sqrt(fmax(0.0, -p * p * p / 27.0));
            double carg = fmax(-1.0, fmin(1.0, -q / (2.0 * r)));
            double theta = acos(carg);
            double m = 2.0 * sqrt(fmax(0.0, -p / 3.0));
            for (int k = 0; k < 3; k++) {
                all[k] = m * cos((theta + 2.0 * M_PI * k) / 3.0) - c2 / 3.0;
            }
            nall = 3;
        }
    }

    int nr = 0;
    for (int i = 0; i < nall; i++) {
        if (all[i] > B) roots[nr++] = all[i];
    }
    for (int i = 0; i < nr - 1; i++) {
        for (int j = 0; j < nr - i - 1; j++) {
            if (roots[j] > roots[j + 1]) {
                double tmp = roots[j];
                roots[j] = roots[j + 1];
                roots[j + 1] = tmp;
            }
        }
    }
    return nr;
}
