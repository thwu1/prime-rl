/*
 * solver_serial.c — Serial reference 2D Poisson solver
 *
 * Solves the same problem as solver_parallel.c but without MPI,
 * serving as a correctness reference.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define GRID_N    32
#define MAX_ITER  10000
#define TOL       1e-6
#define NQUERY    5

int main(void)
{
    double h  = 1.0 / (GRID_N + 1);
    double h2 = h * h;
    double pi = acos(-1.0);

    int stride = GRID_N + 2;
    int total  = stride * stride;

    double *u    = (double *)calloc(total, sizeof(double));
    double *unew = (double *)calloc(total, sizeof(double));
    double *f    = (double *)calloc(total, sizeof(double));

    for (int j = 1; j <= GRID_N; j++)
        for (int i = 1; i <= GRID_N; i++) {
            double x = i * h, y = j * h;
            f[j * stride + i] = 2.0 * pi * pi * sin(pi * x) * sin(pi * y);
        }

    double maxd = 0.0;
    int iters = 0;
    for (int it = 0; it < MAX_ITER; it++) {
        iters++;
        maxd = 0.0;
        for (int j = 1; j <= GRID_N; j++)
            for (int i = 1; i <= GRID_N; i++) {
                int c = j * stride + i;
                unew[c] = 0.25 * (u[(j-1)*stride+i] + u[(j+1)*stride+i]
                                + u[j*stride+(i-1)] + u[j*stride+(i+1)]
                                + h2 * f[c]);
                double d = fabs(unew[c] - u[c]);
                if (d > maxd) maxd = d;
            }
        double *tmp = u; u = unew; unew = tmp;
        if (maxd < TOL) break;
    }

    int qi[NQUERY] = { 8, 16, 24,  8, 24};
    int qj[NQUERY] = { 8, 16, 24, 24,  8};

    FILE *fp = fopen("/app/serial_results.json", "w");
    if (!fp) { perror("fopen"); return 1; }
    fprintf(fp, "{\n  \"grid_size\": %d,\n  \"iterations\": %d,\n"
                "  \"residual\": %.15e,\n  \"points\": [\n",
            GRID_N, iters, maxd);
    for (int q = 0; q < NQUERY; q++) {
        double comp = u[qj[q] * stride + qi[q]];
        double xq = qi[q] * h, yq = qj[q] * h;
        double ex = sin(pi * xq) * sin(pi * yq);
        fprintf(fp, "    {\"i\": %d, \"j\": %d, \"computed\": %.15e, "
                    "\"exact\": %.15e}%s\n",
                qi[q], qj[q], comp, ex, q < NQUERY-1 ? "," : "");
    }
    fprintf(fp, "  ]\n}\n");
    fclose(fp);

    printf("Serial: %d iters, residual %.6e\n", iters, maxd);
    free(u); free(unew); free(f);
    return 0;
}
