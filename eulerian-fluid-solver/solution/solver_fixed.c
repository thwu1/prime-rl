
#include <math.h>

void solve_incompressibility(double* u, double* v, double* p, double* s,
                              int numX, int numY, double h, double density,
                              double dt, double over_relaxation, int num_iters) {
    double cp = density * h / dt;
    int n = numY;

    for (int iter = 0; iter < num_iters; iter++) {
        for (int i = 1; i < numX - 1; i++) {
            for (int j = 1; j < n - 1; j++) {
                if (s[i * n + j] == 0.0)
                    continue;

                double sx0 = s[(i - 1) * n + j];
                double sx1 = s[(i + 1) * n + j];
                double sy0 = s[i * n + j - 1];
                double sy1 = s[i * n + j + 1];
                double s_total = sx0 + sx1 + sy0 + sy1;
                if (s_total == 0.0)
                    continue;

                double div = u[(i + 1) * n + j] - u[i * n + j]
                           + v[i * n + j + 1] - v[i * n + j];

                double p_corr = -over_relaxation * div / s_total;
                p[i * n + j] += cp * p_corr;

                u[i * n + j]       -= sx0 * p_corr;
                u[(i + 1) * n + j] += sx1 * p_corr;
                v[i * n + j]       -= sy0 * p_corr;
                v[i * n + j + 1]   += sy1 * p_corr;
            }
        }
    }
}

double sample_field(double* field, int numX, int numY, double h,
                    double x, double y, int field_type) {
    int n = numY;
    double h1 = 1.0 / h;
    double h2 = 0.5 * h;

    x = fmax(fmin(x, numX * h), h);
    y = fmax(fmin(y, numY * h), h);

    double dx = 0.0, dy = 0.0;

    if (field_type == 0) {
        dy = h2;
    } else if (field_type == 1) {
        dx = h2;
        dy = 0.0;
    } else {
        dx = h2;
        dy = h2;
    }

    int x0 = (int)fmin(floor((x - dx) * h1), numX - 1);
    double tx = ((x - dx) - x0 * h) * h1;
    int x1 = (int)fmin(x0 + 1, numX - 1);

    int y0 = (int)fmin(floor((y - dy) * h1), numY - 1);
    double ty = ((y - dy) - y0 * h) * h1;
    int y1 = (int)fmin(y0 + 1, numY - 1);

    double sx = 1.0 - tx;
    double sy = 1.0 - ty;

    double val = sx * sy * field[x0 * n + y0]
               + tx * sy * field[x1 * n + y0]
               + tx * ty * field[x1 * n + y1]
               + sx * ty * field[x0 * n + y1];

    return val;
}
