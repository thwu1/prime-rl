#ifndef PMIX_PREG_H
#define PMIX_PREG_H

#include <stddef.h>

/*
 * Process-per-node map structures.
 * A pmix_proc_map_t describes how process ranks are distributed
 * across compute nodes in a parallel job.
 */
typedef struct {
    int *ranks;       /* Array of rank IDs assigned to this node */
    int nranks;       /* Number of ranks on this node */
} pmix_node_map_t;

typedef struct {
    pmix_node_map_t *nodes;  /* Array of per-node rank mappings */
    int nnodes;              /* Number of nodes */
    int nprocs;              /* Total number of processes */
} pmix_proc_map_t;

/*
 * PPN Encoding/Decoding
 *
 * Supported wire formats:
 *
 *   "raw:r0,r1,...;r4,r5,..."
 *       Plain text. Ranks within a node are comma-separated;
 *       nodes are semicolon-separated.
 *
 *   "blob:<4-byte header><zlib data>"
 *       v1 compressed binary. The 4-byte header stores the original
 *       uncompressed data length in network byte order, followed
 *       by the zlib-compressed raw rank string.
 *
 *   "blob2:<1-byte algo><4-byte uncomp len><4-byte comp len><data>"
 *       v2 compressed binary with dual-backend support. The 1-byte
 *       algorithm ID selects the compression backend (1=zlib, 2=LZ4).
 *       Both length fields are in network byte order.
 *
 * The encoder tries blob2 format first (dual-backend selection),
 * then blob format, falling back to raw format otherwise.
 */

/* Generate an encoded PPN string from a process map.
 * Returns 0 on success, -1 on failure. Caller must free *output. */
int pmix_preg_generate(const pmix_proc_map_t *map,
                       char **output, size_t *outlen);

/* Parse an encoded PPN string back into a process map.
 * Returns 0 on success, -1 on failure. */
int pmix_preg_parse(const char *input, size_t inlen,
                    pmix_proc_map_t *map);

/* Create a process map with nprocs distributed round-robin across nnodes. */
int pmix_proc_map_create(int nprocs, int nnodes, pmix_proc_map_t *map);

/* Free internal allocations of a process map. */
void pmix_proc_map_free(pmix_proc_map_t *map);

#endif
