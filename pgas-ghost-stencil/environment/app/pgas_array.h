/*
 * pgas_array.h — API for a PGAS distributed 2D array library
 *
 * Inspired by the Global Arrays (GA) toolkit from Pacific Northwest
 * National Laboratory.  The library distributes a 2D array of doubles
 * across MPI processes in a 2D block decomposition, with configurable
 * ghost (halo) cells for stencil computations.
 *
 * The implementation MUST use MPI-3 RMA (one-sided) operations
 * (MPI_Win, MPI_Get/Put, MPI_Win_fence or lock/unlock) for the
 * ghost-cell exchange.
 *
 */

#ifndef PGAS_ARRAY_H
#define PGAS_ARRAY_H

#include <mpi.h>

typedef int pgas_handle_t;

/* ------------------------------------------------------------------ */
/* Initialization / finalization                                       */
/* ------------------------------------------------------------------ */

/* Initialize the PGAS runtime.  Calls MPI_Init internally.            */
int pgas_init(int *argc, char ***argv);

/* Finalize the PGAS runtime.  Calls MPI_Finalize internally.          */
int pgas_finalize(void);

/* Return the total number of MPI processes.                           */
int pgas_nprocs(void);

/* Return the rank of the calling process.                             */
int pgas_myproc(void);

/* ------------------------------------------------------------------ */
/* Distributed array creation / destruction                            */
/* ------------------------------------------------------------------ */

/*
 * Create a 2D distributed array of doubles.
 *
 *   nrows, ncols  — global dimensions of the array
 *   ghost_width   — number of ghost cells on EACH side of the local
 *                   portion (same in both dimensions)
 *
 * The global array is partitioned across processes using a 2D block
 * decomposition.  Each process stores its local block plus surrounding
 * ghost cells in a contiguous row-major buffer.
 *
 * Returns a non-negative handle on success, -1 on failure.
 */
pgas_handle_t pgas_create_2d(int nrows, int ncols, int ghost_width);

/* Free all resources associated with the distributed array.           */
void pgas_destroy(pgas_handle_t h);

/* ------------------------------------------------------------------ */
/* Query / access                                                      */
/* ------------------------------------------------------------------ */

/*
 * Return the global index range owned by process `proc`.
 *
 * On output:
 *   lo[0], hi[0]  — first and last global ROW indices (inclusive, 0-based)
 *   lo[1], hi[1]  — first and last global COLUMN indices (inclusive, 0-based)
 */
void pgas_distribution(pgas_handle_t h, int proc, int lo[2], int hi[2]);

/*
 * Access the local data buffer (including ghost cells).
 *
 * On output:
 *   *ptr  — pointer to the beginning of the local buffer
 *   *ld   — leading dimension = total number of columns in the local
 *           buffer (local_ncols + 2 * ghost_width)
 *
 * Element at LOCAL row i, LOCAL column j (where (0,0) is the first
 * REAL / non-ghost cell) is located at:
 *
 *     (*ptr)[ (i + ghost_width) * (*ld) + (j + ghost_width) ]
 */
void pgas_access_local(pgas_handle_t h, double **ptr, int *ld);

/* ------------------------------------------------------------------ */
/* Communication                                                       */
/* ------------------------------------------------------------------ */

/*
 * Update ghost cells from neighbouring processes.
 *
 * After this collective call returns, every process's ghost cells
 * contain up-to-date copies of the corresponding boundary data from
 * its neighbours.  Processes at the edge of the global array that have
 * no neighbour in a given direction leave those ghost cells unchanged.
 *
 * MUST use MPI-3 RMA (MPI_Win + MPI_Get or MPI_Put with fence or
 * lock/unlock synchronisation).
 */
void pgas_update_ghosts(pgas_handle_t h);

/* ------------------------------------------------------------------ */
/* Utility                                                             */
/* ------------------------------------------------------------------ */

/* Fill every REAL (non-ghost) cell with `value`.                      */
void pgas_fill(pgas_handle_t h, double value);

/* Global barrier.                                                     */
void pgas_sync(void);

/* Global sum-reduction of a single double.                            */
double pgas_dgop_sum(double val);

#endif /* PGAS_ARRAY_H */
