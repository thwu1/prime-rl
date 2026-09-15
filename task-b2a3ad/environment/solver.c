#include "fdtd3d.h"
#include <stdlib.h>
#include <stdio.h>

/*
 * Optimized 3D FDTD stencil solver.
 * Must produce results numerically identical to fdtd_naive()
 * (within float32 precision).
 */

bool fdtd_tiled(float *output, const float *input, const float *coeff,
                int dimx, int dimy, int dimz, int radius, int timesteps)
{
    (void)output; (void)input; (void)coeff;
    (void)dimx; (void)dimy; (void)dimz;
    (void)radius; (void)timesteps;

    fprintf(stderr, "fdtd_tiled: NOT IMPLEMENTED\n");
    return false;
}
