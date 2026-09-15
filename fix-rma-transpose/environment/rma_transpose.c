/*
 * Distributed Block Matrix Transpose using MPI RMA
 *
 * Transposes an NxN matrix distributed in block-row fashion across
 * processes using MPI one-sided communication (RMA) with derived
 * datatypes and fence synchronization.
 *
 * Each process owns BLOCK_SIZE rows of the NxN matrix (N = nprocs * BLOCK_SIZE).
 * Global matrix A is initialized as A[r][c] = r * N + c.
 * After transposition, B[r][c] should equal A[c][r] = c * N + r.
 *
 * Algorithm:
 *   For each pair of processes (i, j), process i extracts the BS x BS
 *   sub-block at block-column j from its local rows, transposes it,
 *   and puts it into process j's window at the corresponding position.
 */

#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef BLOCK_SIZE
#define BLOCK_SIZE 4
#endif

int main(int argc, char **argv)
{
    int rank, nprocs, errs = 0;

    MPI_Init(&argc, &argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &nprocs);

    if (nprocs != 4) {
        if (rank == 0)
            fprintf(stderr, "This program requires exactly 4 processes\n");
        MPI_Abort(MPI_COMM_WORLD, 1);
    }

    const int BS = BLOCK_SIZE;
    const int N  = nprocs * BS;

    /* Each process owns BS rows of the NxN matrix, stored in row-major order */
    double *local_A = (double *)calloc(BS * N, sizeof(double));
    double *local_B = (double *)calloc(BS * N, sizeof(double));

    if (!local_A || !local_B) {
        fprintf(stderr, "Rank %d: allocation failed\n", rank);
        MPI_Abort(MPI_COMM_WORLD, 1);
    }

    /* Initialize: global A[r][c] = r * N + c */
    for (int r = 0; r < BS; r++) {
        int global_row = rank * BS + r;
        for (int c = 0; c < N; c++) {
            local_A[r * N + c] = (double)(global_row * N + c);
        }
    }

    memset(local_B, 0, BS * N * sizeof(double));

    /* Create RMA window exposing local_B for one-sided access */
    MPI_Win win;
    MPI_Win_create(local_B, BS * N * sizeof(double),
                   1,   /* displacement unit */
                   MPI_INFO_NULL, MPI_COMM_WORLD, &win);

    /*
     * Define derived type for a BS x BS block within a BS x N matrix.
     * Each block consists of BS groups of BS contiguous doubles.
     */
    MPI_Datatype target_blk_type;
    MPI_Type_vector(BS, BS, BS, MPI_DOUBLE, &target_blk_type);
    MPI_Type_commit(&target_blk_type);

    /* Temporary buffer for block extraction */
    double *tmp = (double *)malloc(BS * BS * sizeof(double));

    /* Begin RMA access epoch */
    MPI_Win_fence(0, win);

    for (int j = 0; j < nprocs; j++) {
        /* Extract block (rank, j) from local_A into tmp for transfer */
        for (int r = 0; r < BS; r++) {
            for (int c = 0; c < BS; c++) {
                tmp[r * BS + c] = local_A[r * N + j * BS + c];
            }
        }

        /* Transfer block to process j's window at the correct position */
        MPI_Put(tmp, BS * BS, MPI_DOUBLE,
                j, j * BS, 1, target_blk_type, win);
    }

    /* Complete RMA access epoch */
    MPI_Win_fence(0, win);

    /* Verify: B[global_row][c] should equal c * N + global_row */
    for (int r = 0; r < BS; r++) {
        int global_row = rank * BS + r;
        for (int c = 0; c < N; c++) {
            double expected = (double)(c * N + global_row);
            if (local_B[r * N + c] != expected) {
                if (errs < 10) {
                    fprintf(stderr, "Rank %d: B[%d][%d] = %.1f, expected %.1f\n",
                            rank, global_row, c, local_B[r * N + c], expected);
                }
                errs++;
            }
        }
    }

    int total_errs;
    MPI_Allreduce(&errs, &total_errs, 1, MPI_INT, MPI_SUM, MPI_COMM_WORLD);

    if (rank == 0) {
        if (total_errs == 0) {
            printf(" No Errors\n");
        } else {
            printf(" Found %d errors\n", total_errs);
        }
    }

    free(tmp);
    MPI_Type_free(&target_blk_type);
    MPI_Win_free(&win);
    free(local_A);
    free(local_B);
    MPI_Finalize();
    return (total_errs != 0);
}
