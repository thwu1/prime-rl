/*
 * edge_detect_optimized.c -- Optimized multi-stage edge detection pipeline.
 *
 * Key optimizations:
 *   1. Float precision throughout — halves memory bandwidth, enables
 *      wider SIMD auto-vectorization under -O3.
 *   2. Loop interchange in blur_vertical — row-major (y-outer, x-inner)
 *      access eliminates stride-N cache misses on the 32 MB working set.
 *   3. Border/interior split in blur passes — removes per-pixel boundary
 *      checks and kernel renormalization division from the interior loop,
 *      enabling better compiler auto-vectorization.
 *   4. Eliminated atan2/cos/sin round-trip — compute_gradients stores raw
 *      gx, gy arrays instead of direction. non_max_suppress uses gx, gy
 *      directly, avoiding 3 expensive transcendental functions per pixel.
 *   5. Reduced branch depth in NMS — normalizes direction to the upper
 *      half-plane (flip when gy < 0) reducing 8-way nested branches to
 *      a 2-way split on |gx| vs |gy| plus sign-based offset selection.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define KERNEL_SIZE   5
#define KERNEL_RADIUS 2

static const float g_kernel[KERNEL_SIZE] = {
    0.06136f, 0.24477f, 0.38774f, 0.24477f, 0.06136f
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
/*  Stage 1a: Horizontal blur — border/interior split                  */
/* ------------------------------------------------------------------ */

static void blur_horizontal(const float *src, float *dst, int w, int h) {
    for (int y = 0; y < h; y++) {
        const float *row = src + y * w;
        float       *out = dst + y * w;

        /* Left border */
        for (int x = 0; x < KERNEL_RADIUS && x < w; x++) {
            float val = 0.0f, wt = 0.0f;
            for (int k = -KERNEL_RADIUS; k <= KERNEL_RADIUS; k++) {
                int sx = x + k;
                if (sx >= 0 && sx < w) {
                    val += row[sx] * g_kernel[k + KERNEL_RADIUS];
                    wt  += g_kernel[k + KERNEL_RADIUS];
                }
            }
            out[x] = val / wt;
        }

        /* Interior — full kernel, no branches, kernel sums to 1.0 */
        for (int x = KERNEL_RADIUS; x < w - KERNEL_RADIUS; x++) {
            float val = 0.0f;
            for (int k = 0; k < KERNEL_SIZE; k++)
                val += row[x - KERNEL_RADIUS + k] * g_kernel[k];
            out[x] = val;
        }

        /* Right border */
        int rb = w - KERNEL_RADIUS;
        if (rb < KERNEL_RADIUS) rb = KERNEL_RADIUS;
        for (int x = rb; x < w; x++) {
            float val = 0.0f, wt = 0.0f;
            for (int k = -KERNEL_RADIUS; k <= KERNEL_RADIUS; k++) {
                int sx = x + k;
                if (sx >= 0 && sx < w) {
                    val += row[sx] * g_kernel[k + KERNEL_RADIUS];
                    wt  += g_kernel[k + KERNEL_RADIUS];
                }
            }
            out[x] = val / wt;
        }
    }
}

/* ------------------------------------------------------------------ */
/*  Stage 1b: Vertical blur — row-major via loop interchange +         */
/*  border/interior split                                              */
/* ------------------------------------------------------------------ */

static void blur_vertical(const float *src, float *dst, int w, int h) {
    /* Top border rows */
    for (int y = 0; y < KERNEL_RADIUS && y < h; y++) {
        for (int x = 0; x < w; x++) {
            float val = 0.0f, wt = 0.0f;
            for (int k = -KERNEL_RADIUS; k <= KERNEL_RADIUS; k++) {
                int sy = y + k;
                if (sy >= 0 && sy < h) {
                    val += src[sy * w + x] * g_kernel[k + KERNEL_RADIUS];
                    wt  += g_kernel[k + KERNEL_RADIUS];
                }
            }
            dst[y * w + x] = val / wt;
        }
    }

    /* Interior rows — y-outer, x-inner (row-major), no boundary checks */
    for (int y = KERNEL_RADIUS; y < h - KERNEL_RADIUS; y++) {
        for (int x = 0; x < w; x++) {
            float val = 0.0f;
            for (int k = 0; k < KERNEL_SIZE; k++)
                val += src[(y - KERNEL_RADIUS + k) * w + x] * g_kernel[k];
            dst[y * w + x] = val;
        }
    }

    /* Bottom border rows */
    int bb = h - KERNEL_RADIUS;
    if (bb < KERNEL_RADIUS) bb = KERNEL_RADIUS;
    for (int y = bb; y < h; y++) {
        for (int x = 0; x < w; x++) {
            float val = 0.0f, wt = 0.0f;
            for (int k = -KERNEL_RADIUS; k <= KERNEL_RADIUS; k++) {
                int sy = y + k;
                if (sy >= 0 && sy < h) {
                    val += src[sy * w + x] * g_kernel[k + KERNEL_RADIUS];
                    wt  += g_kernel[k + KERNEL_RADIUS];
                }
            }
            dst[y * w + x] = val / wt;
        }
    }
}

/* ------------------------------------------------------------------ */
/*  Stage 2: Gradient — outputs raw gx, gy arrays + magnitude.        */
/*  No atan2 computation; NMS will use gx/gy directly.                 */
/* ------------------------------------------------------------------ */

static void compute_gradients(const float *src,
                              float *gx_out, float *gy_out, float *mag,
                              int w, int h) {
    memset(gx_out, 0, (size_t)w * h * sizeof(float));
    memset(gy_out, 0, (size_t)w * h * sizeof(float));
    memset(mag, 0, (size_t)w * h * sizeof(float));
    for (int y = 1; y < h - 1; y++) {
        for (int x = 1; x < w - 1; x++) {
            float gx =
                -src[(y-1)*w+(x-1)] + src[(y-1)*w+(x+1)]
              - 2.0f*src[y*w+(x-1)] + 2.0f*src[y*w+(x+1)]
                -src[(y+1)*w+(x-1)] + src[(y+1)*w+(x+1)];
            float gy =
                -src[(y-1)*w+(x-1)] - 2.0f*src[(y-1)*w+x]
                - src[(y-1)*w+(x+1)]
                +src[(y+1)*w+(x-1)] + 2.0f*src[(y+1)*w+x]
                + src[(y+1)*w+(x+1)];
            gx_out[y * w + x] = gx;
            gy_out[y * w + x] = gy;
            mag[y * w + x] = sqrtf(gx * gx + gy * gy);
        }
    }
}

/* ------------------------------------------------------------------ */
/*  Stage 3: NMS using raw gradient components.                        */
/*  Normalize direction to upper half-plane (flip when gy < 0),        */
/*  then use |gx| vs gy to select octant with minimal branching.       */
/* ------------------------------------------------------------------ */

static void non_max_suppress(const float *mag,
                             const float *gx_arr, const float *gy_arr,
                             float *nms, int w, int h) {
    memset(nms, 0, (size_t)w * h * sizeof(float));
    for (int y = 1; y < h - 1; y++) {
        for (int x = 1; x < w - 1; x++) {
            float m = mag[y * w + x];
            if (m == 0.0f) continue;

            float dx = gx_arr[y * w + x];
            float dy = gy_arr[y * w + x];

            /* Normalize to upper half-plane (gy >= 0) */
            if (dy < 0.0f) { dx = -dx; dy = -dy; }

            float adx = fabsf(dx);
            float m1, m2;

            if (adx > dy) {
                /* More horizontal */
                float r = dy / adx;
                int sx = (dx > 0.0f) ? 1 : -1;
                m1 = (1.0f - r) * mag[y*w+(x+sx)]
                   + r * mag[(y+1)*w+(x+sx)];
                m2 = (1.0f - r) * mag[y*w+(x-sx)]
                   + r * mag[(y-1)*w+(x-sx)];
            } else {
                /* More vertical (dy >= adx, dy > 0 since m > 0) */
                float r = (dy > 0.0f) ? adx / dy : 0.0f;
                int sx = (dx >= 0.0f) ? 1 : -1;
                m1 = (1.0f - r) * mag[(y+1)*w+x]
                   + r * mag[(y+1)*w+(x+sx)];
                m2 = (1.0f - r) * mag[(y-1)*w+x]
                   + r * mag[(y-1)*w+(x-sx)];
            }

            nms[y * w + x] = (m >= m1 && m >= m2) ? m : 0.0f;
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

    /* Float-precision working buffers */
    float *a      = (float *)malloc(n * sizeof(float));
    float *b      = (float *)malloc(n * sizeof(float));
    float *gx_arr = (float *)malloc(n * sizeof(float));
    float *gy_arr = (float *)malloc(n * sizeof(float));
    float *mag    = (float *)malloc(n * sizeof(float));
    float *nms    = (float *)malloc(n * sizeof(float));

    memcpy(a, raw, n * sizeof(float));
    free(raw);

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    /* Stage 1: Iterative Gaussian smoothing */
    for (int it = 0; it < niters; it++) {
        blur_horizontal(a, b, width, height);
        blur_vertical(b, a, width, height);
    }

    /* Stage 2: Gradient (raw gx, gy + magnitude) */
    compute_gradients(a, gx_arr, gy_arr, mag, width, height);

    /* Stage 3: Non-maximum suppression */
    non_max_suppress(mag, gx_arr, gy_arr, nms, width, height);

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double elapsed = (t1.tv_sec - t0.tv_sec)
                   + (t1.tv_nsec - t0.tv_nsec) / 1e9;
    fprintf(stderr, "TIME: %.4f\n", elapsed);

    write_image(out_path, nms, width, height);

    free(a); free(b); free(gx_arr); free(gy_arr); free(mag); free(nms);
    return 0;
}
