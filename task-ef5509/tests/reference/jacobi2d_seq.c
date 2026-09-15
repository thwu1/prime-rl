/*
 * Sequential reference: 2D Jacobi stencil with proper double-buffering.
 */
#include <stdio.h>
#include <stdlib.h>

#define GRID_SIZE 100
#define NUM_ITER 50

int main() {
    double (*grid)[GRID_SIZE] = malloc(GRID_SIZE * sizeof(*grid));
    double (*grid_new)[GRID_SIZE] = malloc(GRID_SIZE * sizeof(*grid_new));

    for (int i = 0; i < GRID_SIZE; i++)
        for (int j = 0; j < GRID_SIZE; j++) {
            grid[i][j] = (i == 0 || i == GRID_SIZE - 1 ||
                          j == 0 || j == GRID_SIZE - 1) ? 1.0 : 0.0;
            grid_new[i][j] = grid[i][j];
        }

    for (int iter = 0; iter < NUM_ITER; iter++) {
        for (int i = 1; i < GRID_SIZE - 1; i++)
            for (int j = 1; j < GRID_SIZE - 1; j++)
                grid_new[i][j] = 0.25 * (grid[i - 1][j] + grid[i + 1][j] +
                                          grid[i][j - 1] + grid[i][j + 1]);
        double (*tmp)[GRID_SIZE] = grid;
        grid = grid_new;
        grid_new = tmp;
    }

    double checksum = 0.0;
    for (int i = 0; i < GRID_SIZE; i++)
        for (int j = 0; j < GRID_SIZE; j++)
            checksum += grid[i][j];
    printf("%.10f\n", checksum);

    free(grid);
    free(grid_new);
    return 0;
}
