/*
 * pic_kernels.c - Performance-critical PIC kernels for 1D electrostatic simulation
 *
 * Cloud-in-Cell (CIC) charge deposition and field interpolation routines.
 * Compile into shared library: gcc -O2 -fPIC -shared -lm -o libpic_kernels.so pic_kernels.c
 */
#include <math.h>

/*
 * CIC charge deposition.
 * Deposits particle charges onto grid using linear (CIC) interpolation.
 * n_e[j] = (1/dx) * sum_i wp * W(x_i, j)
 *
 * Parameters:
 *   n_e         - output electron density array (size N_grid)
 *   x           - particle positions (size N_particles)
 *   N_particles - number of particles
 *   N_grid      - number of grid points
 *   dx          - grid spacing
 *   L           - domain length
 *   wp          - particle weight
 */
void cic_deposit(double *n_e, const double *x, int N_particles,
                 int N_grid, double dx, double L, double wp) {
    int i, j_left, j_right;
    double cell_pos, frac;

    for (i = 0; i < N_grid; i++) n_e[i] = 0.0;

    for (i = 0; i < N_particles; i++) {
        cell_pos = x[i] / dx;
        j_left = ((int)floor(cell_pos)) % N_grid;
        if (j_left < 0) j_left += N_grid;
        frac = cell_pos - floor(cell_pos);
        j_right = j_left + 1;

        n_e[j_left] += wp * (1.0 - frac) / dx;
        n_e[j_right] += wp * frac / dx;
    }
}

/*
 * CIC field interpolation.
 * Interpolates grid field values to particle positions using linear weighting.
 *
 * Parameters:
 *   E_particles - output field at particle positions (size N_particles)
 *   E_grid      - input field on grid (size N_grid)
 *   x           - particle positions (size N_particles)
 *   N_particles - number of particles
 *   N_grid      - number of grid points
 *   dx          - grid spacing
 */
void cic_interpolate(double *E_particles, const double *E_grid,
                     const double *x, int N_particles,
                     int N_grid, double dx) {
    int i, j_left, j_right;
    double cell_pos, frac;

    for (i = 0; i < N_particles; i++) {
        cell_pos = x[i] / dx;
        j_left = ((int)floor(cell_pos)) % N_grid;
        if (j_left < 0) j_left += N_grid;
        frac = cell_pos - floor(cell_pos);
        j_right = (j_left + 1) % N_grid;

        E_particles[i] = (1.0 - frac) * E_grid[j_left] + frac * E_grid[j_right];
    }
}
