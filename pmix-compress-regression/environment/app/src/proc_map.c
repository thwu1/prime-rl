/*
 * Process map creation and lifecycle utilities.
 */

#include "preg.h"
#include <stdlib.h>

int pmix_proc_map_create(int nprocs, int nnodes, pmix_proc_map_t *map)
{
    if (nprocs <= 0 || nnodes <= 0 || nprocs < nnodes) {
        return -1;
    }

    map->nodes = (pmix_node_map_t *)calloc(nnodes, sizeof(pmix_node_map_t));
    if (!map->nodes) return -1;

    map->nnodes = nnodes;
    map->nprocs = nprocs;

    /* Round-robin distribution: first (nprocs % nnodes) nodes get one extra rank */
    int base = nprocs / nnodes;
    int extra = nprocs % nnodes;
    int rank = 0;

    for (int n = 0; n < nnodes; n++) {
        int nr = base + (n < extra ? 1 : 0);
        map->nodes[n].ranks = (int *)calloc(nr, sizeof(int));
        if (!map->nodes[n].ranks) return -1;
        map->nodes[n].nranks = nr;

        for (int r = 0; r < nr; r++) {
            map->nodes[n].ranks[r] = rank++;
        }
    }

    return 0;
}

void pmix_proc_map_free(pmix_proc_map_t *map)
{
    if (!map) return;
    if (map->nodes) {
        for (int n = 0; n < map->nnodes; n++) {
            free(map->nodes[n].ranks);
        }
        free(map->nodes);
        map->nodes = NULL;
    }
    map->nnodes = 0;
    map->nprocs = 0;
}
