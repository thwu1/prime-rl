/*
 * Parallel histogram computation using OpenMP.
 * This program bins integer data into a histogram.
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

#define DATA_SIZE 100000
#define NUM_BINS 16

int main() {
    int *data = (int *)malloc(DATA_SIZE * sizeof(int));
    int histogram[NUM_BINS];

    for (int i = 0; i < NUM_BINS; i++)
        histogram[i] = 0;

    srand(42);
    for (int i = 0; i < DATA_SIZE; i++)
        data[i] = rand() % NUM_BINS;

    #pragma omp parallel for
    for (int i = 0; i < DATA_SIZE; i++) {
        histogram[data[i]]++;
    }

    for (int i = 0; i < NUM_BINS; i++)
        printf("%d %d\n", i, histogram[i]);

    free(data);
    return 0;
}
