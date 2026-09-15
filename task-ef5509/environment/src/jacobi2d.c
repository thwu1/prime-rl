/*
 * Parallel 2D Jacobi stencil iteration using OpenMP.
 * Iteratively solves a discrete Laplace equation on a 2D grid.
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

#define GRID_SIZE 100
#define NUM_ITER 50

int main() {
    double (*grid)[GRID_SIZE] = malloc(GRID_SIZE * sizeof(*grid));

    for (int i = 0; i < GRID_SIZE; i++)
        for (int j = 0; j < GRID_SIZE; j++)
            grid[i][j] = (i == 0 || i == GRID_SIZE - 1 ||
                          j == 0 || j == GRID_SIZE - 1) ? 1.0 : 0.0;

    for (int iter = 0; iter < NUM_ITER; iter++) {
        #pragma omp parallel for
        for (int i = 1; i < GRID_SIZE - 1; i++) {
            for (int j = 1; j < GRID_SIZE - 1; j++) {
                grid[i][j] = 0.25 * (grid[i - 1][j] + grid[i + 1][j] +
                                      grid[i][j - 1] + grid[i][j + 1]);
            }
        }
    }

    double checksum = 0.0;
    for (int i = 0; i < GRID_SIZE; i++)
        for (int j = 0; j < GRID_SIZE; j++)
            checksum += grid[i][j];
    printf("%.10f\n", checksum);

    free(grid);
    return 0;
}
