/*
 * edge_detect.c -- Multi-stage edge detection pipeline.
 *
 * Pipeline:
 *   1. Iterative separable Gaussian smooth (N iterations of H + V)
 *   2. Sobel gradient magnitude (sqrt) and direction (atan2)
 *   3. Sub-pixel gradient-interpolated non-maximum suppression
 *
 * Binary image format:
 *   [width:int32][height:int32][pixels:float32[width*height]]
 *
 * Usage: ./edge_detect input.bin output.bin <smooth_iters>
 * Reports wall-clock time to stderr: TIME: X.XXXX
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define KERNEL_SIZE   5
#define KERNEL_RADIUS 2

/* Gaussian kernel (sigma ~ 1.0, sums to ~1.0) */
static const double g_kernel[KERNEL_SIZE] = {
    0.06136, 0.24477, 0.38774, 0.24477, 0.06136
};

/* ------------------------------------------------------------------ */
/*  I/O                                                                */
/* ------------------------------------------------------------------ */

static void read_image(const char *path, int *w, int *h, float **data) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(1); }
    int dims[2];
    if (fread(dims, sizeof(int), 2, f) != 2) {
        fprintf(stderr, "bad header\n"); exit(1);
    }
    *w = dims[0]; *h = dims[1];
    size_t n = (size_t)(*w) * (*h);
    *data = (float *)malloc(n * sizeof(float));
    if (fread(*data, sizeof(float), n, f) != n) {
        fprintf(stderr, "short read\n"); exit(1);
    }
    fclose(f);
}

static void write_image(const char *path, const float *data, int w, int h) {
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); exit(1); }
    int dims[2] = {w, h};
    if (fwrite(dims, sizeof(int), 2, f) != 2 ||
        fwrite(data, sizeof(float), (size_t)w * h, f) != (size_t)w * h) {
        fprintf(stderr, "write error\n"); exit(1);
    }
    fclose(f);
}

/* ------------------------------------------------------------------ */
/*  Stage 1a: Horizontal Gaussian blur                                 */
/*  Row-major access (sequential). Boundary pixels handled by          */
/*  renormalizing kernel weights.                                      */
/* ------------------------------------------------------------------ */

static void blur_horizontal(const double *src, double *dst,
                            int width, int height) {
    for (int y = 0; y < height; y++) {
        for (int x = 0; x < width; x++) {
            double val = 0.0, wt = 0.0;
            for (int k = -KERNEL_RADIUS; k <= KERNEL_RADIUS; k++) {
                int sx = x + k;
                if (sx >= 0 && sx < width) {
                    val += src[y * width + sx] * g_kernel[k + KERNEL_RADIUS];
                    wt  += g_kernel[k + KERNEL_RADIUS];
                }
            }
            dst[y * width + x] = val / wt;
        }
    }
}

/* ------------------------------------------------------------------ */
/*  Stage 1b: Vertical Gaussian blur                                   */
/*  Outer loop iterates over columns, inner loop over rows —           */
/*  strided memory access across image rows.                           */
/* ------------------------------------------------------------------ */

static void blur_vertical(const double *src, double *dst,
                          int width, int height) {
    for (int x = 0; x < width; x++) {
        for (int y = 0; y < height; y++) {
            double val = 0.0, wt = 0.0;
            for (int k = -KERNEL_RADIUS; k <= KERNEL_RADIUS; k++) {
                int sy = y + k;
                if (sy >= 0 && sy < height) {
                    val += src[sy * width + x] * g_kernel[k + KERNEL_RADIUS];
                    wt  += g_kernel[k + KERNEL_RADIUS];
                }
            }
            dst[y * width + x] = val / wt;
        }
    }
}

/* ------------------------------------------------------------------ */
/*  Stage 2: Gradient magnitude and direction                          */
/*  Sobel operator computes gx, gy per pixel. Magnitude via sqrt,     */
/*  direction via atan2. Border pixels set to zero.                    */
/* ------------------------------------------------------------------ */

static void compute_gradients(const double *src,
                              double *mag, double *dir,
                              int width, int height) {
    memset(mag, 0, (size_t)width * height * sizeof(double));
    memset(dir, 0, (size_t)width * height * sizeof(double));
    for (int y = 1; y < height - 1; y++) {
        for (int x = 1; x < width - 1; x++) {
            double gx =
                -src[(y-1)*width+(x-1)] + src[(y-1)*width+(x+1)]
              - 2.0*src[y*width+(x-1)]  + 2.0*src[y*width+(x+1)]
                -src[(y+1)*width+(x-1)] + src[(y+1)*width+(x+1)];
            double gy =
                -src[(y-1)*width+(x-1)] - 2.0*src[(y-1)*width+x]
                - src[(y-1)*width+(x+1)]
                +src[(y+1)*width+(x-1)] + 2.0*src[(y+1)*width+x]
                + src[(y+1)*width+(x+1)];
            mag[y * width + x] = sqrt(gx * gx + gy * gy);
            dir[y * width + x] = atan2(gy, gx);
        }
    }
}

/* ------------------------------------------------------------------ */
/*  Stage 3: Non-maximum suppression                                   */
/*  For each pixel, interpolates gradient magnitude along the          */
/*  gradient direction in forward and backward directions.             */
/*  Pixel is kept only if it is the local maximum along that line.     */
/*                                                                     */
/*  Uses the stored atan2 direction. Recomputes cos/sin of the         */
/*  normalized angle to determine interpolation weights and            */
/*  neighbor offsets via deeply nested conditionals.                    */
/* ------------------------------------------------------------------ */

static void non_max_suppress(const double *mag, const double *dir,
                             double *nms, int width, int height) {
    memset(nms, 0, (size_t)width * height * sizeof(double));
    for (int y = 1; y < height - 1; y++) {
        for (int x = 1; x < width - 1; x++) {
            double m = mag[y * width + x];
            if (m == 0.0) {
                nms[y * width + x] = 0.0;
                continue;
            }

            /* Retrieve direction and normalize to [0, PI) */
            double angle = dir[y * width + x];
            if (angle < 0.0) angle += M_PI;

            /* Recompute gradient components from direction */
            double gx = cos(angle);
            double gy = sin(angle);
            double agx = fabs(gx);
            double agy = fabs(gy);

            double m1, m2;

            if (agx > agy) {
                /* Gradient is more horizontal */
                double r = agy / agx;
                if (gx > 0.0) {
                    if (gy >= 0.0) {
                        m1 = (1.0 - r) * mag[y*width+(x+1)]
                           + r * mag[(y+1)*width+(x+1)];
                        m2 = (1.0 - r) * mag[y*width+(x-1)]
                           + r * mag[(y-1)*width+(x-1)];
                    } else {
                        m1 = (1.0 - r) * mag[y*width+(x+1)]
                           + r * mag[(y-1)*width+(x+1)];
                        m2 = (1.0 - r) * mag[y*width+(x-1)]
                           + r * mag[(y+1)*width+(x-1)];
                    }
                } else {
                    if (gy >= 0.0) {
                        m1 = (1.0 - r) * mag[y*width+(x-1)]
                           + r * mag[(y+1)*width+(x-1)];
                        m2 = (1.0 - r) * mag[y*width+(x+1)]
                           + r * mag[(y-1)*width+(x+1)];
                    } else {
                        m1 = (1.0 - r) * mag[y*width+(x-1)]
                           + r * mag[(y-1)*width+(x-1)];
                        m2 = (1.0 - r) * mag[y*width+(x+1)]
                           + r * mag[(y+1)*width+(x+1)];
                    }
                }
            } else {
                /* Gradient is more vertical */
                double r = agx / agy;
                if (gy > 0.0) {
                    if (gx >= 0.0) {
                        m1 = (1.0 - r) * mag[(y+1)*width+x]
                           + r * mag[(y+1)*width+(x+1)];
                        m2 = (1.0 - r) * mag[(y-1)*width+x]
                           + r * mag[(y-1)*width+(x-1)];
                    } else {
                        m1 = (1.0 - r) * mag[(y+1)*width+x]
                           + r * mag[(y+1)*width+(x-1)];
                        m2 = (1.0 - r) * mag[(y-1)*width+x]
                           + r * mag[(y-1)*width+(x+1)];
                    }
                } else {
                    if (gx >= 0.0) {
                        m1 = (1.0 - r) * mag[(y-1)*width+x]
                           + r * mag[(y-1)*width+(x+1)];
                        m2 = (1.0 - r) * mag[(y+1)*width+x]
                           + r * mag[(y+1)*width+(x-1)];
                    } else {
                        m1 = (1.0 - r) * mag[(y-1)*width+x]
                           + r * mag[(y-1)*width+(x-1)];
                        m2 = (1.0 - r) * mag[(y+1)*width+x]
                           + r * mag[(y+1)*width+(x+1)];
                    }
                }
            }

            if (m >= m1 && m >= m2) {
                nms[y * width + x] = m;
            } else {
                nms[y * width + x] = 0.0;
            }
        }
    }
}

/* ------------------------------------------------------------------ */
/*  Main                                                               */
/* ------------------------------------------------------------------ */

int main(int argc, char *argv[]) {
    if (argc != 4) {
        fprintf(stderr,
                "Usage: %s input.bin output.bin smooth_iters\n", argv[0]);
        return 1;
    }

    const char *in_path  = argv[1];
    const char *out_path = argv[2];
    int niters = atoi(argv[3]);

    int width, height;
    float *raw;
    read_image(in_path, &width, &height, &raw);

    size_t n = (size_t)width * height;

    /* Working buffers — double precision */
    double *a   = (double *)malloc(n * sizeof(double));
    double *b   = (double *)malloc(n * sizeof(double));
    double *mag = (double *)malloc(n * sizeof(double));
    double *dir = (double *)malloc(n * sizeof(double));
    double *nms = (double *)malloc(n * sizeof(double));

    for (size_t i = 0; i < n; i++)
        a[i] = (double)raw[i];
    free(raw);

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    /* Stage 1: Iterative Gaussian smoothing */
    for (int it = 0; it < niters; it++) {
        blur_horizontal(a, b, width, height);
        blur_vertical(b, a, width, height);
    }

    /* Stage 2: Gradient magnitude + direction */
    compute_gradients(a, mag, dir, width, height);

    /* Stage 3: Non-maximum suppression */
    non_max_suppress(mag, dir, nms, width, height);

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double elapsed = (t1.tv_sec - t0.tv_sec)
                   + (t1.tv_nsec - t0.tv_nsec) / 1e9;
    fprintf(stderr, "TIME: %.4f\n", elapsed);

    /* Write NMS result as float32 */
    float *out = (float *)malloc(n * sizeof(float));
    for (size_t i = 0; i < n; i++)
        out[i] = (float)nms[i];
    write_image(out_path, out, width, height);

    free(out);
    free(a); free(b); free(mag); free(dir); free(nms);
    return 0;
}
