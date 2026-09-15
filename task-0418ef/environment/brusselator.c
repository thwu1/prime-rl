/*
 * C implementation of the 1D Brusselator reaction-diffusion RHS.
 * Compile into a shared library: see accompanying Makefile.
 *
 * Function signatures:
 *   void brusselator_rhs(const double *y, double t, double *dydt);
 *   int  get_n_total(void);
 *   int  get_n_grid(void);
 */
#include <math.h>

#define A_PARAM 1.0
#define B_PARAM 3.0
#define ALPHA   0.02
#define N_GRID  40
#define N_TOTAL 80

static const double DX = 1.0 / N_GRID;

void brusselator_rhs(const double *y, double t, double *dydt) {
    const double *u = y;
    const double *v = y + N_GRID;
    double *du = dydt;
    double *dv = dydt + N_GRID;
    double inv_dx2 = 1.0 / (DX * DX);

    for (int i = 0; i < N_GRID; i++) {
        int im = (i - 1 + N_GRID) % N_GRID;
        int ip = (i + 1) % N_GRID;

        double lap_u = (u[im] - 2.0 * u[i] + u[ip]) * inv_dx2;
        double lap_v = (v[im] - 2.0 * v[i] + v[ip]) * inv_dx2;

        du[i] = A_PARAM + u[i] * u[i] * v[i]
                - (B_PARAM + 1.0) * u[i] + ALPHA * lap_u;
        dv[i] = B_PARAM * u[i] - u[i] * u[i] * v[i] + ALPHA * lap_v;
    }
}

int get_n_total(void) { return N_TOTAL; }
int get_n_grid(void)  { return N_GRID; }
