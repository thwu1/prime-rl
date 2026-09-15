/*
 * convolution.c -- Multi-pass Gaussian blur + gradient magnitude pipeline.
 *
 * Reads a binary grayscale image, applies N iterations of separable
 * Gaussian blur (horizontal + vertical passes), computes the Sobel
 * gradient magnitude, and writes the result.
 *
 * Binary image format:
 *   [width:int32][height:int32][pixels:float32[width*height]]
 *
 * Usage: ./convolution input.bin output.bin <num_iterations>
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define KERNEL_SIZE   5
#define KERNEL_RADIUS 2

/* Gaussian kernel (sigma ~ 1.0, sums to 1.0) */
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
 * Horizontal Gaussian blur.
 * All arithmetic uses double precision.
 * Boundary pixels handled by renormalizing kernel weights per pixel.
 */
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

/*
 * Vertical Gaussian blur.
 * Outer loop iterates over columns, inner loop over rows,
 * producing strided memory access across the image rows.
 */
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

/*
 * Sobel gradient magnitude.
 * Border pixels are set to zero.
 */
static void gradient_magnitude(const double *src, double *dst,
                               int width, int height) {
    memset(dst, 0, (size_t)width * height * sizeof(double));
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
            dst[y * width + x] = sqrt(gx * gx + gy * gy);
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

    /* Working buffers -- double precision */
    double *a    = (double *)malloc(n * sizeof(double));
    double *b    = (double *)malloc(n * sizeof(double));
    double *grad = (double *)malloc(n * sizeof(double));

    for (size_t i = 0; i < n; i++)
        a[i] = (double)raw[i];
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

    /* Write result as float */
    float *out = (float *)malloc(n * sizeof(float));
    for (size_t i = 0; i < n; i++)
        out[i] = (float)grad[i];
    write_image(out_path, out, width, height);

    free(out);
    free(a);
    free(b);
    free(grad);
    return 0;
}
