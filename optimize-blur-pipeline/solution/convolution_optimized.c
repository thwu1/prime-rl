/*
 * convolution_optimized.c -- Optimized multi-pass Gaussian blur + gradient.
 *
 * Key optimizations applied:
 *   1. Loop interchange in blur_vertical: row-major access eliminates
 *      cache thrashing (primary bottleneck, ~3-5x speedup alone).
 *   2. Float precision throughout: halves memory bandwidth (~1.3x).
 *   3. Border/interior split: eliminates per-pixel boundary branches
 *      and unnecessary kernel renormalization division for interior pixels.
 *   4. sqrtf instead of sqrt in gradient computation.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define KERNEL_SIZE   5
#define KERNEL_RADIUS 2

/* Kernel in float precision */
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
    *w = dims[0];
    *h = dims[1];
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
/*  Processing stages                                                  */
/* ------------------------------------------------------------------ */

/*
 * Horizontal blur: split border / interior.
 * Interior pixels skip boundary checks and kernel renormalization.
 */
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

        /* Interior: full kernel, no branches, kernel sums to 1.0 */
        for (int x = KERNEL_RADIUS; x < w - KERNEL_RADIUS; x++) {
            float val = 0.0f;
            for (int k = 0; k < KERNEL_SIZE; k++)
                val += row[x - KERNEL_RADIUS + k] * g_kernel[k];
            out[x] = val;
        }

        /* Right border */
        int rb_start = w - KERNEL_RADIUS;
        if (rb_start < KERNEL_RADIUS) rb_start = KERNEL_RADIUS;
        for (int x = rb_start; x < w; x++) {
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

/*
 * Vertical blur: ROW-MAJOR access (loop interchange).
 * Outer y / inner x eliminates stride-N cache misses.
 */
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

    /* Interior rows: no boundary checks, kernel normalized */
    for (int y = KERNEL_RADIUS; y < h - KERNEL_RADIUS; y++) {
        for (int x = 0; x < w; x++) {
            float val = 0.0f;
            for (int k = 0; k < KERNEL_SIZE; k++)
                val += src[(y - KERNEL_RADIUS + k) * w + x] * g_kernel[k];
            dst[y * w + x] = val;
        }
    }

    /* Bottom border rows */
    int bb_start = h - KERNEL_RADIUS;
    if (bb_start < KERNEL_RADIUS) bb_start = KERNEL_RADIUS;
    for (int y = bb_start; y < h; y++) {
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

/*
 * Sobel gradient magnitude (float precision, sqrtf).
 */
static void gradient_magnitude(const float *src, float *dst, int w, int h) {
    memset(dst, 0, (size_t)w * h * sizeof(float));
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
            dst[y * w + x] = sqrtf(gx * gx + gy * gy);
        }
    }
}

/* ------------------------------------------------------------------ */
/*  Main                                                               */
/* ------------------------------------------------------------------ */

int main(int argc, char *argv[]) {
    if (argc != 4) {
        fprintf(stderr,
                "Usage: %s input.bin output.bin num_iterations\n", argv[0]);
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
    float *a    = (float *)malloc(n * sizeof(float));
    float *b    = (float *)malloc(n * sizeof(float));
    float *grad = (float *)malloc(n * sizeof(float));

    memcpy(a, raw, n * sizeof(float));
    free(raw);

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    for (int it = 0; it < niters; it++) {
        blur_horizontal(a, b, width, height);
        blur_vertical(b, a, width, height);
    }
    gradient_magnitude(a, grad, width, height);

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double elapsed = (t1.tv_sec - t0.tv_sec)
                   + (t1.tv_nsec - t0.tv_nsec) / 1e9;
    fprintf(stderr, "TIME: %.4f\n", elapsed);

    write_image(out_path, grad, width, height);

    free(a);
    free(b);
    free(grad);
    return 0;
}
