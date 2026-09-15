#include "fdtd3d.h"
#include <stdlib.h>
#include <stdio.h>

bool fdtd_stencil(float *output, const float *input, const float *coeff,
                  int dimx, int dimy, int dimz, int radius, int timesteps)
{
    const int outerDimx  = dimx + 2 * radius;
    const int outerDimy  = dimy + 2 * radius;
    const int outerDimz  = dimz + 2 * radius;
    const size_t volumeSize = (size_t)outerDimx * outerDimy * outerDimz;
    const int stride_y   = outerDimx;
    const int stride_z   = stride_y * outerDimx;

    float *intermediate = (float *)calloc(volumeSize, sizeof(float));
    if (!intermediate) {
        fprintf(stderr, "Failed to allocate intermediate buffer\n");
        return false;
    }

    const float *bufsrc;
    float *bufdst, *bufdstnext;

    /* Arrange buffers so that after all timesteps the final result
     * resides in the caller-provided output buffer.  For an even
     * number of timesteps the first write goes to intermediate,
     * the last to output; for odd, the opposite. */
    if ((timesteps % 2) != 0) {
        bufsrc     = input;
        bufdst     = intermediate;
        bufdstnext = output;
    } else {
        bufsrc     = input;
        bufdst     = output;
        bufdstnext = intermediate;
    }

    for (int it = 0; it < timesteps; it++) {
        printf("  timestep %d/%d\n", it + 1, timesteps);
        const float *src = bufsrc;
        float       *dst = bufdst;

        for (int iz = -radius; iz < dimz + radius; iz++) {
            for (int iy = -radius; iy < dimy + radius; iy++) {
                for (int ix = -radius; ix < dimx + radius; ix++) {
                    int idx = (iz + radius) * stride_z
                            + (iy + radius) * stride_y
                            + (ix + radius);

                    if (ix >= 0 && ix < dimx &&
                        iy >= 0 && iy < dimy &&
                        iz >= 0 && iz < dimz) {
                        float value = src[idx] * coeff[0];

                        for (int ir = 0; ir <= radius; ir++) {
                            value += coeff[ir] * (src[idx + ir]            + src[idx - ir]);
                            value += coeff[ir] * (src[idx + ir * stride_y] + src[idx - ir * stride_y]);
                            value += coeff[ir] * (src[idx + ir * stride_z] + src[idx - ir * stride_z]);
                        }

                        dst[idx] = value;
                    } else {
                        dst[idx] = src[idx];
                    }
                }
            }
        }

        /* Rotate buffers: what we just wrote becomes the next source,
         * and we swap the destination pair. */
        float *tmp = bufdst;
        bufdst     = bufdstnext;
        bufdstnext = tmp;
        bufsrc     = (const float *)tmp;
    }

    free(intermediate);
    return true;
}
