/*
 *
 * Matrix generator for the 2D Poisson equation.
 *
 * Usage: poisson_gen [grid_size] [output_directory]
 *   grid_size        - interior grid points per direction (default: 63)
 *   output_directory - where to write A.mtx and b.mtx (default: /app)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "stencil.h"

int main(int argc, char** argv)
{
    int n = 63;
    const char* outdir = "/app";

    if (argc > 1)
        n = atoi(argv[1]);
    if (argc > 2)
        outdir = argv[2];

    if (n < 3 || n > 1023) {
        fprintf(stderr, "Error: grid_size must be in [3, 1023], got %d\n", n);
        return 1;
    }

    char matrix_path[512], rhs_path[512];
    snprintf(matrix_path, sizeof(matrix_path), "%s/A.mtx", outdir);
    snprintf(rhs_path, sizeof(rhs_path), "%s/b.mtx", outdir);

    printf("Generating 2D Poisson system...\n");
    printf("  Grid:   %d x %d  (%d unknowns)\n", n, n, n * n);
    printf("  Matrix: %s\n", matrix_path);
    printf("  RHS:    %s\n", rhs_path);

    generate_poisson_2d(n, matrix_path, rhs_path);

    printf("Done.\n");
    return 0;
}
