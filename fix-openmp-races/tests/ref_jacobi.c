/* Sequential reference for Jacobi relaxation with correct double buffering */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

#define GRID_SIZE 200
#define MAX_ITER 100

static double grid[GRID_SIZE][GRID_SIZE];
static double grid_new[GRID_SIZE][GRID_SIZE];

void init_grid(void) {
    for (int i = 0; i < GRID_SIZE; i++) {
        for (int j = 0; j < GRID_SIZE; j++) {
            if (i == 0)
                grid[i][j] = 100.0 * sin(M_PI * j / (GRID_SIZE - 1));
            else if (i == GRID_SIZE - 1)
                grid[i][j] = 100.0 * sin(M_PI * j / (GRID_SIZE - 1)) * exp(-M_PI);
            else
                grid[i][j] = 0.0;
        }
    }
}

double jacobi_step(void) {
    double max_diff = 0.0;
    for (int i = 1; i < GRID_SIZE - 1; i++) {
        for (int j = 1; j < GRID_SIZE - 1; j++) {
            grid_new[i][j] = 0.25 * (grid[i-1][j] + grid[i+1][j] +
                                      grid[i][j-1] + grid[i][j+1]);
            double diff = fabs(grid_new[i][j] - grid[i][j]);
            if (diff > max_diff) max_diff = diff;
        }
    }
    for (int i = 1; i < GRID_SIZE - 1; i++) {
        for (int j = 1; j < GRID_SIZE - 1; j++) {
            grid[i][j] = grid_new[i][j];
        }
    }
    return max_diff;
}

int main(void) {
    init_grid();

    int iter;
    double diff = 0.0;
    for (iter = 0; iter < MAX_ITER; iter++) {
        diff = jacobi_step();
    }

    double checksum = 0.0;
    for (int i = 0; i < GRID_SIZE; i++) {
        for (int j = 0; j < GRID_SIZE; j++) {
            checksum += grid[i][j];
        }
    }

    printf("iterations=%d\n", iter);
    printf("final_diff=%.10e\n", diff);
    printf("checksum=%.6f\n", checksum);

    return 0;
}
