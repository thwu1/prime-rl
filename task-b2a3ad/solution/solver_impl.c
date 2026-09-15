#include "fdtd3d.h"
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

bool fdtd_tiled(float *output, const float *input, const float *coeff,
                int dimx, int dimy, int dimz, int radius, int timesteps)
{
    const int outerDimx = dimx + 2 * radius;
    const int outerDimy = dimy + 2 * radius;
    const int outerDimz = dimz + 2 * radius;
    const size_t volumeSize = (size_t)outerDimx * outerDimy * outerDimz;
    const int stride_y = outerDimx;
    const int stride_z = stride_y * outerDimy;

    /* Tile sizes chosen for L1 cache residency (~32KB).
     * Read region per tile: (TX+2R)*(TY+2R)*(TZ+2R)*4 bytes
     * With R=4, TX=TY=12, TZ=8: 20*20*16*4 = 25600 bytes
     * Write region: TX*TY*TZ*4 = 12*12*8*4 = 4608 bytes
     * Total ~30KB, fits in 32KB L1 data cache */
    const int TX = 12;
    const int TY = 12;
    const int TZ = 8;

    float *intermediate = (float *)calloc(volumeSize, sizeof(float));
    if (!intermediate) {
        fprintf(stderr, "Failed to allocate intermediate buffer\n");
        return false;
    }

    const float *bufsrc;
    float *bufdst, *bufdstnext;

    if ((timesteps % 2) == 0) {
        bufsrc     = input;
        bufdst     = intermediate;
        bufdstnext = output;
    } else {
        bufsrc     = input;
        bufdst     = output;
        bufdstnext = intermediate;
    }

    for (int it = 0; it < timesteps; it++) {
        printf("  tiled timestep %d/%d\n", it + 1, timesteps);
        const float *src = bufsrc;
        float       *dst = bufdst;

        /* Copy entire volume: halo values pass through unchanged,
         * interior values will be overwritten by the tiled stencil. */
        memcpy(dst, src, volumeSize * sizeof(float));

        /* Process interior domain in spatial tiles */
        for (int tz = 0; tz < dimz; tz += TZ) {
            int ez = tz + TZ;
            if (ez > dimz) ez = dimz;
            for (int ty = 0; ty < dimy; ty += TY) {
                int ey = ty + TY;
                if (ey > dimy) ey = dimy;
                for (int tx = 0; tx < dimx; tx += TX) {
                    int ex = tx + TX;
                    if (ex > dimx) ex = dimx;

                    /* Compute stencil for this tile's interior points */
                    for (int iz = tz; iz < ez; iz++) {
                        for (int iy = ty; iy < ey; iy++) {
                            for (int ix = tx; ix < ex; ix++) {
                                int idx = (iz + radius) * stride_z
                                        + (iy + radius) * stride_y
                                        + (ix + radius);

                                float value = src[idx] * coeff[0];
                                for (int ir = 1; ir <= radius; ir++) {
                                    value += coeff[ir] * (src[idx + ir] + src[idx - ir]);
                                    value += coeff[ir] * (src[idx + ir * stride_y] + src[idx - ir * stride_y]);
                                    value += coeff[ir] * (src[idx + ir * stride_z] + src[idx - ir * stride_z]);
                                }
                                dst[idx] = value;
                            }
                        }
                    }
                }
            }
        }

        /* Rotate buffers */
        float *tmp = bufdst;
        bufdst     = bufdstnext;
        bufdstnext = tmp;
        bufsrc     = (const float *)tmp;
    }

    free(intermediate);
    return true;
}
