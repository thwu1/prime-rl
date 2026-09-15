/*
 * pgas_array.c — PGAS distributed 2D array library using MPI-3 RMA
 *
 * Reference implementation for this task.
 *
 */

#include "pgas_array.h"
#include <stdlib.h>
#include <string.h>

#define MAX_ARRAYS 16

typedef struct {
    int      valid;
    int      nrows, ncols, ghost_width;
    int      prows, pcols;                 /* process-grid dims        */
    int      my_prow, my_pcol;             /* my position in the grid  */
    int      lo[2], hi[2];                 /* global index range I own */
    int      local_nrows, local_ncols;     /* owned block size         */
    int      alloc_nrows, alloc_ncols;     /* block + ghost padding    */
    double  *data;                         /* row-major local buffer   */
    MPI_Win  win;
} arr_t;

static int   g_rank  = -1;
static int   g_nproc = -1;
static arr_t g_arr[MAX_ARRAYS];

/* ------------------------------------------------------------------ */
/* helpers                                                              */
/* ------------------------------------------------------------------ */

/* Factor np into pr x pc as close to square as possible. */
static void factor_grid(int np, int *pr, int *pc)
{
    *pr = 1;
    *pc = np;
    for (int r = 1; r * r <= np; r++)
        if (np % r == 0) { *pr = r; *pc = np / r; }
}

/* Block-distribute 'total' items across 'nblk' blocks; return the
   range [*lo, *hi] (inclusive) for block 'bid'. */
static void block_dist(int total, int nblk, int bid, int *lo, int *hi)
{
    int per = total / nblk;
    int rem = total % nblk;
    if (bid < rem) {
        *lo = bid * (per + 1);
        *hi = *lo + per;
    } else {
        *lo = rem * (per + 1) + (bid - rem) * per;
        *hi = *lo + per - 1;
    }
}

/* ------------------------------------------------------------------ */
/* init / finalize                                                      */
/* ------------------------------------------------------------------ */

int pgas_init(int *argc, char ***argv)
{
    MPI_Init(argc, argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &g_rank);
    MPI_Comm_size(MPI_COMM_WORLD, &g_nproc);
    memset(g_arr, 0, sizeof(g_arr));
    return 0;
}

int pgas_finalize(void)
{
    MPI_Finalize();
    return 0;
}

int pgas_nprocs(void) { return g_nproc; }
int pgas_myproc(void) { return g_rank;  }

/* ------------------------------------------------------------------ */
/* create / destroy                                                     */
/* ------------------------------------------------------------------ */

pgas_handle_t pgas_create_2d(int nrows, int ncols, int ghost_width)
{
    int slot = -1;
    for (int i = 0; i < MAX_ARRAYS; i++)
        if (!g_arr[i].valid) { slot = i; break; }
    if (slot < 0) return -1;

    arr_t *a = &g_arr[slot];
    a->valid       = 1;
    a->nrows       = nrows;
    a->ncols       = ncols;
    a->ghost_width = ghost_width;

    factor_grid(g_nproc, &a->prows, &a->pcols);
    a->my_prow = g_rank / a->pcols;
    a->my_pcol = g_rank % a->pcols;

    block_dist(nrows, a->prows, a->my_prow, &a->lo[0], &a->hi[0]);
    block_dist(ncols, a->pcols, a->my_pcol, &a->lo[1], &a->hi[1]);

    a->local_nrows = a->hi[0] - a->lo[0] + 1;
    a->local_ncols = a->hi[1] - a->lo[1] + 1;
    a->alloc_nrows = a->local_nrows + 2 * ghost_width;
    a->alloc_ncols = a->local_ncols + 2 * ghost_width;

    int total = a->alloc_nrows * a->alloc_ncols;
    a->data = (double *)calloc((size_t)total, sizeof(double));

    MPI_Win_create(a->data,
                   (MPI_Aint)total * (MPI_Aint)sizeof(double),
                   (int)sizeof(double),
                   MPI_INFO_NULL, MPI_COMM_WORLD, &a->win);
    return slot;
}

void pgas_destroy(pgas_handle_t h)
{
    arr_t *a = &g_arr[h];
    if (!a->valid) return;
    MPI_Win_free(&a->win);
    free(a->data);
    a->valid = 0;
}

/* ------------------------------------------------------------------ */
/* query / access                                                       */
/* ------------------------------------------------------------------ */

void pgas_distribution(pgas_handle_t h, int proc, int lo[2], int hi[2])
{
    arr_t *a  = &g_arr[h];
    int pr = proc / a->pcols;
    int pc = proc % a->pcols;
    block_dist(a->nrows, a->prows, pr, &lo[0], &hi[0]);
    block_dist(a->ncols, a->pcols, pc, &lo[1], &hi[1]);
}

void pgas_access_local(pgas_handle_t h, double **ptr, int *ld)
{
    arr_t *a = &g_arr[h];
    *ptr = a->data;
    *ld  = a->alloc_ncols;
}

/* ------------------------------------------------------------------ */
/* ghost exchange (MPI-3 RMA)                                           */
/* ------------------------------------------------------------------ */

void pgas_update_ghosts(pgas_handle_t h)
{
    arr_t *a  = &g_arr[h];
    int    gw = a->ghost_width;
    int    pr = a->my_prow;
    int    pc = a->my_pcol;

    /* neighbour ranks (-1 = no neighbour) */
    int north = (pr > 0)              ? (pr - 1) * a->pcols + pc : -1;
    int south = (pr < a->prows - 1)   ? (pr + 1) * a->pcols + pc : -1;
    int west  = (pc > 0)              ? pr * a->pcols + (pc - 1) : -1;
    int east  = (pc < a->pcols - 1)   ? pr * a->pcols + (pc + 1) : -1;

    /* open access epoch */
    MPI_Win_fence(0, a->win);

    /* ---- north ghost: get bottom gw real rows from north neighbour ---- */
    if (north >= 0) {
        int nlo[2], nhi[2];
        pgas_distribution(h, north, nlo, nhi);
        int nbr_lr = nhi[0] - nlo[0] + 1;          /* neighbour local rows */
        int nbr_lc = nhi[1] - nlo[1] + 1;          /* neighbour local cols */
        int nbr_ac = nbr_lc + 2 * gw;              /* neighbour alloc cols */

        for (int g = 0; g < gw; g++) {
            int src_row = nbr_lr - gw + g;          /* real row in neighbour */
            MPI_Aint disp = (MPI_Aint)(src_row + gw) * nbr_ac + gw;
            int      dst  = g * a->alloc_ncols + gw;
            MPI_Get(&a->data[dst], a->local_ncols, MPI_DOUBLE,
                    north, disp, a->local_ncols, MPI_DOUBLE, a->win);
        }
    }

    /* ---- south ghost: get top gw real rows from south neighbour ---- */
    if (south >= 0) {
        int nlo[2], nhi[2];
        pgas_distribution(h, south, nlo, nhi);
        int nbr_lc = nhi[1] - nlo[1] + 1;
        int nbr_ac = nbr_lc + 2 * gw;

        for (int g = 0; g < gw; g++) {
            MPI_Aint disp = (MPI_Aint)(g + gw) * nbr_ac + gw;
            int      dst  = (gw + a->local_nrows + g) * a->alloc_ncols + gw;
            MPI_Get(&a->data[dst], a->local_ncols, MPI_DOUBLE,
                    south, disp, a->local_ncols, MPI_DOUBLE, a->win);
        }
    }

    /* ---- west ghost: get rightmost gw cols from west neighbour ---- */
    if (west >= 0) {
        int nlo[2], nhi[2];
        pgas_distribution(h, west, nlo, nhi);
        int nbr_lc = nhi[1] - nlo[1] + 1;
        int nbr_ac = nbr_lc + 2 * gw;

        for (int r = 0; r < a->local_nrows; r++) {
            for (int g = 0; g < gw; g++) {
                int src_col = nbr_lc - gw + g;
                MPI_Aint disp = (MPI_Aint)(r + gw) * nbr_ac + (src_col + gw);
                int      dst  = (r + gw) * a->alloc_ncols + g;
                MPI_Get(&a->data[dst], 1, MPI_DOUBLE,
                        west, disp, 1, MPI_DOUBLE, a->win);
            }
        }
    }

    /* ---- east ghost: get leftmost gw cols from east neighbour ---- */
    if (east >= 0) {
        int nlo[2], nhi[2];
        pgas_distribution(h, east, nlo, nhi);
        int nbr_lc = nhi[1] - nlo[1] + 1;
        int nbr_ac = nbr_lc + 2 * gw;

        for (int r = 0; r < a->local_nrows; r++) {
            for (int g = 0; g < gw; g++) {
                MPI_Aint disp = (MPI_Aint)(r + gw) * nbr_ac + (g + gw);
                int      dst  = (r + gw) * a->alloc_ncols
                                + (gw + a->local_ncols + g);
                MPI_Get(&a->data[dst], 1, MPI_DOUBLE,
                        east, disp, 1, MPI_DOUBLE, a->win);
            }
        }
    }

    /* close access epoch — all Gets are complete after this */
    MPI_Win_fence(0, a->win);
}

/* ------------------------------------------------------------------ */
/* utility                                                              */
/* ------------------------------------------------------------------ */

void pgas_fill(pgas_handle_t h, double value)
{
    arr_t *a  = &g_arr[h];
    int    gw = a->ghost_width;
    for (int i = 0; i < a->local_nrows; i++)
        for (int j = 0; j < a->local_ncols; j++)
            a->data[(i + gw) * a->alloc_ncols + (j + gw)] = value;
}

void pgas_sync(void)
{
    MPI_Barrier(MPI_COMM_WORLD);
}

double pgas_dgop_sum(double val)
{
    double result;
    MPI_Allreduce(&val, &result, 1, MPI_DOUBLE, MPI_SUM, MPI_COMM_WORLD);
    return result;
}
