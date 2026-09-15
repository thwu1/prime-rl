#include "fdtd3d.h"
#include <stdio.h>
#include <stdlib.h>

void generate_input(float *data)
{
    for (int iz = 0; iz < OUTER_DIMZ; iz++) {
        for (int iy = 0; iy < OUTER_DIMY; iy++) {
            for (int ix = 0; ix < OUTER_DIMX; ix++) {
                int idx = iz * OUTER_DIMY * OUTER_DIMX + iy * OUTER_DIMX + ix;
                int val = ((ix * 7 + iy * 13 + iz * 29 + 5) % 256);
                data[idx] = (float)val / 256.0f;
            }
        }
    }
}

int write_output(const char *filename, const float *data, size_t count)
{
    FILE *f = fopen(filename, "wb");
    if (!f) {
        fprintf(stderr, "Error: cannot open %s for writing\n", filename);
        return -1;
    }
    size_t written = fwrite(data, sizeof(float), count, f);
    fclose(f);
    if (written != count) {
        fprintf(stderr, "Error: wrote %zu of %zu elements\n", written, count);
        return -1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    (void)argc;
    (void)argv;

    printf("3D FDTD Stencil Benchmark\n");
    printf("Grid: %d x %d x %d (interior)\n", DIMX, DIMY, DIMZ);
    printf("Outer: %d x %d x %d (with halo)\n", OUTER_DIMX, OUTER_DIMY, OUTER_DIMZ);
    printf("Radius: %d, Timesteps: %d\n", RADIUS, TIMESTEPS);
    printf("Volume: %d elements (%zu bytes)\n\n", VOLUME_SIZE,
           (size_t)VOLUME_SIZE * sizeof(float));

    float *input = (float *)malloc((size_t)VOLUME_SIZE * sizeof(float));
    float *output_naive = (float *)calloc((size_t)VOLUME_SIZE, sizeof(float));
    float *output_tiled = (float *)calloc((size_t)VOLUME_SIZE, sizeof(float));
    float coeff[RADIUS + 1];

    if (!input || !output_naive || !output_tiled) {
        fprintf(stderr, "Error: memory allocation failed\n");
        return 1;
    }

    for (int i = 0; i <= RADIUS; i++)
        coeff[i] = COEFF_VAL;

    printf("Generating input data...\n");
    generate_input(input);

    /* Run naive solver */
    printf("\n=== Naive solver ===\n");
    if (!fdtd_naive(output_naive, input, coeff, DIMX, DIMY, DIMZ, RADIUS, TIMESTEPS)) {
        fprintf(stderr, "Naive solver failed\n");
        free(input); free(output_naive); free(output_tiled);
        return 1;
    }
    if (write_output("output_naive.bin", output_naive, VOLUME_SIZE) != 0) {
        free(input); free(output_naive); free(output_tiled);
        return 1;
    }
    printf("Wrote output_naive.bin\n");

    /* Run tiled solver */
    printf("\n=== Tiled solver ===\n");
    if (!fdtd_tiled(output_tiled, input, coeff, DIMX, DIMY, DIMZ, RADIUS, TIMESTEPS)) {
        fprintf(stderr, "Tiled solver failed\n");
        free(input); free(output_naive); free(output_tiled);
        return 1;
    }
    if (write_output("output_tiled.bin", output_tiled, VOLUME_SIZE) != 0) {
        free(input); free(output_naive); free(output_tiled);
        return 1;
    }
    printf("Wrote output_tiled.bin\n");

    /* Analyze and compare */
    printf("\n=== Analysis ===\n");
    int rc = analyze_outputs("output_naive.bin", "output_tiled.bin",
                             "results.json",
                             OUTER_DIMX, OUTER_DIMY, OUTER_DIMZ, RADIUS);
    if (rc != 0) {
        fprintf(stderr, "Analysis failed\n");
        free(input); free(output_naive); free(output_tiled);
        return 1;
    }

    free(input);
    free(output_naive);
    free(output_tiled);
    printf("\nDone. Results written to results.json\n");
    return 0;
}
