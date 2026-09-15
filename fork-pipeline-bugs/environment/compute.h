/*
 * compute.h — Computation library for parallel coordinator
 *
 * Provides helper functions for reading input data and performing
 * the computations that workers must execute over their data partitions.
 */

#ifndef COMPUTE_H
#define COMPUTE_H

#include <stdio.h>
#include <stdlib.h>

#define PRIME 1000003L
#define HASH_MULT 6364136223846793005ULL
#define MAX_WORKERS 8

/* Read integers from file into a dynamically allocated array.
   Sets *out_count to the number of integers read. */
static int *read_numbers(const char *path, int *out_count)
{
    FILE *f = fopen(path, "r");
    if (!f) {
        perror("fopen input");
        exit(EXIT_FAILURE);
    }
    int capacity = 256, n = 0;
    int *arr = malloc(capacity * sizeof(int));
    if (!arr) { perror("malloc"); exit(EXIT_FAILURE); }
    int v;
    while (fscanf(f, "%d", &v) == 1) {
        if (n >= capacity) {
            capacity *= 2;
            arr = realloc(arr, capacity * sizeof(int));
            if (!arr) { perror("realloc"); exit(EXIT_FAILURE); }
        }
        arr[n++] = v;
    }
    fclose(f);
    *out_count = n;
    return arr;
}

/* Compute partial sum: sum of (x^3 mod PRIME) for data[start..end) */
static long compute_partial_sum(const int *data, int start, int end)
{
    long sum = 0;
    for (int i = start; i < end; i++) {
        long v = (long)data[i];
        sum += (v * v * v) % PRIME;
    }
    return sum;
}

/* Compute 64-bit hash-chain checksum over data[start..end).
   Uses Knuth's MMIX LCG multiplier for mixing. */
static unsigned long long compute_checksum(const int *data, int start, int end)
{
    unsigned long long h = 0;
    for (int i = start; i < end; i++) {
        h = h * HASH_MULT + (unsigned long long)data[i];
    }
    return h;
}

#endif /* COMPUTE_H */
