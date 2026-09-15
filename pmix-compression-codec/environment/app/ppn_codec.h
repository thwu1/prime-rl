/*
 * ppn_codec.h - Process-Per-Node map codec
 *
 * Encodes and decodes rank placement maps for an HPC job launcher.
 * Maps describe which MPI ranks are assigned to which compute nodes.
 *
 * Encoding formats:
 *   TAG_RAW    (0x01): [tag][rank_list_text]
 *   TAG_BLOB   (0x02): [tag][uint32_t orig_size][zlib_compressed_rank_list]
 *   TAG_PACKED (0x03): See SPEC.md for wire format
 *
 * Rank list text format: semicolon-separated node groups of
 * comma-separated rank numbers, e.g. "0,1,2;3,4,5;6,7,8"
 */

#ifndef PPN_CODEC_H
#define PPN_CODEC_H

#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>

/* Format tag bytes */
#define TAG_RAW    0x01
#define TAG_BLOB   0x02
#define TAG_PACKED 0x03

/* Minimum raw string size before compression is attempted (bytes) */
#define COMPRESS_LIMIT 4096

/* Per-node rank assignment */
typedef struct {
    int   node_id;
    int  *ranks;
    int   nranks;
} node_map_t;

/* Full process-to-node placement map */
typedef struct {
    node_map_t *nodes;
    int         nnodes;
    int         total_procs;
} ppn_map_t;

/* Allocate a map with nnodes slots (zeroed) */
ppn_map_t *ppn_map_alloc(int nnodes);

/* Free a map and all its rank arrays */
void ppn_map_free(ppn_map_t *map);

/* Generate a test map: total_procs ranks distributed contiguously
 * across nnodes nodes (extras go to the first nodes) */
ppn_map_t *ppn_map_generate(int total_procs, int nnodes);

/*
 * Encode a PPN map into a tagged binary buffer.
 * The encoder MUST select the format that produces the smallest output.
 * Tie-breaking order: TAG_PACKED > TAG_BLOB > TAG_RAW.
 * Returns 0 on success, -1 on failure.
 */
int ppn_encode(ppn_map_t *map, uint8_t **out_data, size_t *out_len);

/*
 * Decode a tagged binary buffer back into a PPN map.
 * Supports TAG_RAW, TAG_BLOB, and TAG_PACKED formats.
 * Returns NULL on failure.
 */
ppn_map_t *ppn_decode(const uint8_t *data, size_t len);

#endif /* PPN_CODEC_H */
