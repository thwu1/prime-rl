#ifndef FDTD3D_H
#define FDTD3D_H

#include <stdbool.h>
#include <stddef.h>

/* Grid dimensions (interior, excluding halo) */
#define DIMX 48
#define DIMY 32
#define DIMZ 16

/* Stencil radius */
#define RADIUS 4

/* Number of timesteps */
#define TIMESTEPS 10

/* Coefficient value (uniform for all radii) */
#define COEFF_VAL 0.1f

/* Outer dimensions (including halo on each side) */
#define OUTER_DIMX (DIMX + 2 * RADIUS)
#define OUTER_DIMY (DIMY + 2 * RADIUS)
#define OUTER_DIMZ (DIMZ + 2 * RADIUS)

/* Total volume size in elements */
#define VOLUME_SIZE (OUTER_DIMX * OUTER_DIMY * OUTER_DIMZ)

/* Naive reference solver: applies FDTD stencil using a simple triple loop. */
bool fdtd_naive(float *output, const float *input, const float *coeff,
                int dimx, int dimy, int dimz, int radius, int timesteps);

/* Cache-tiled optimized solver: applies FDTD stencil using spatial tiling. */
bool fdtd_tiled(float *output, const float *input, const float *coeff,
                int dimx, int dimy, int dimz, int radius, int timesteps);

/* Generate deterministic input data for the full outer volume. */
void generate_input(float *data);

/* Write float array to binary file. Returns 0 on success. */
int write_output(const char *filename, const float *data, size_t count);

/* Compare two binary output files and write comparison report to JSON.
 * Returns 0 on success, non-zero on failure. */
int analyze_outputs(const char *file_naive, const char *file_tiled,
                    const char *json_out,
                    int outer_dimx, int outer_dimy, int outer_dimz,
                    int radius);

#endif /* FDTD3D_H */
