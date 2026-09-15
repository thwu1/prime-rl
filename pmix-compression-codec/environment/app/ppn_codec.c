/*
 * ppn_codec.c - Process-Per-Node map codec implementation
 *
 */

#include "ppn_codec.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>

/* ----------------------------------------------------------------
 * Map allocation helpers
 * ---------------------------------------------------------------- */

ppn_map_t *ppn_map_alloc(int nnodes)
{
    ppn_map_t *map = calloc(1, sizeof(ppn_map_t));
    if (!map) return NULL;
    map->nnodes = nnodes;
    map->nodes  = calloc(nnodes, sizeof(node_map_t));
    if (!map->nodes) { free(map); return NULL; }
    return map;
}

void ppn_map_free(ppn_map_t *map)
{
    if (!map) return;
    for (int i = 0; i < map->nnodes; i++)
        free(map->nodes[i].ranks);
    free(map->nodes);
    free(map);
}

ppn_map_t *ppn_map_generate(int total_procs, int nnodes)
{
    ppn_map_t *map = ppn_map_alloc(nnodes);
    if (!map) return NULL;

    int base  = total_procs / nnodes;
    int extra = total_procs % nnodes;
    int rank  = 0;

    for (int n = 0; n < nnodes; n++) {
        int nr = base + (n < extra ? 1 : 0);
        map->nodes[n].node_id = n;
        map->nodes[n].nranks  = nr;
        map->nodes[n].ranks   = calloc(nr, sizeof(int));
        for (int r = 0; r < nr; r++)
            map->nodes[n].ranks[r] = rank++;
    }
    map->total_procs = total_procs;
    return map;
}

/* ----------------------------------------------------------------
 * Rank-list text serialization
 *
 * Format: "r0,r1,...,rK;rK+1,...,r2K;..."
 *   Commas separate ranks within a node.
 *   Semicolons separate nodes.
 * ---------------------------------------------------------------- */

static char *serialize_rank_list(ppn_map_t *map, size_t *out_len)
{
    /* First pass: compute required buffer size */
    size_t needed = 0;
    for (int n = 0; n < map->nnodes; n++) {
        for (int r = 0; r < map->nodes[n].nranks; r++) {
            char tmp[16];
            needed += (size_t)snprintf(tmp, sizeof(tmp), "%d",
                                       map->nodes[n].ranks[r]);
            if (r < map->nodes[n].nranks - 1) needed++; /* comma */
        }
        if (n < map->nnodes - 1) needed++; /* semicolon */
    }

    char *buf = malloc(needed + 1);
    if (!buf) return NULL;

    /* Second pass: write the string */
    char *p = buf;
    for (int n = 0; n < map->nnodes; n++) {
        for (int r = 0; r < map->nodes[n].nranks; r++) {
            p += sprintf(p, "%d", map->nodes[n].ranks[r]);
            if (r < map->nodes[n].nranks - 1) *p++ = ',';
        }
        if (n < map->nnodes - 1) *p++ = ';';
    }
    *p = '\0';

    if (out_len) *out_len = (size_t)(p - buf);
    return buf;
}

static ppn_map_t *deserialize_rank_list(const char *str, size_t len)
{
    if (!str || len == 0) return NULL;

    /* Work on a null-terminated copy */
    char *copy = malloc(len + 1);
    if (!copy) return NULL;
    memcpy(copy, str, len);
    copy[len] = '\0';

    /* Count nodes (number of semicolons + 1) */
    int nnodes = 1;
    for (size_t i = 0; i < len; i++) {
        if (copy[i] == ';') nnodes++;
    }

    ppn_map_t *map = ppn_map_alloc(nnodes);
    if (!map) { free(copy); return NULL; }

    char *saveptr_node = NULL;
    char *node_tok = strtok_r(copy, ";", &saveptr_node);

    for (int n = 0; n < nnodes && node_tok; n++) {
        map->nodes[n].node_id = n;

        /* Count ranks in this node group */
        int nranks = 1;
        for (char *c = node_tok; *c; c++) {
            if (*c == ',') nranks++;
        }

        map->nodes[n].nranks = nranks;
        map->nodes[n].ranks  = calloc(nranks, sizeof(int));

        /* Parse individual rank numbers */
        char *saveptr_rank = NULL;
        char *rank_tok = strtok_r(node_tok, ",", &saveptr_rank);
        for (int r = 0; r < nranks && rank_tok; r++) {
            map->nodes[n].ranks[r] = atoi(rank_tok);
            map->total_procs++;
            rank_tok = strtok_r(NULL, ",", &saveptr_rank);
        }

        node_tok = strtok_r(NULL, ";", &saveptr_node);
    }

    free(copy);
    return map;
}

/* ----------------------------------------------------------------
 * zlib compression module
 *
 * Compressed block format:
 *   [uint32_t original_size][deflated_data]
 * ---------------------------------------------------------------- */

static bool zlib_compress_block(const uint8_t *input, size_t inlen,
                                uint8_t **output, size_t *outlen)
{
    z_stream strm;
    memset(&strm, 0, sizeof(strm));

    if (deflateInit(&strm, Z_DEFAULT_COMPRESSION) != Z_OK)
        return false;

    /* Upper bound on compressed output */
    size_t bound = deflateBound(&strm, inlen);

    /*
     * v2.0.x checked (bound >= inlen) here and returned false if the
     * upper-bound estimate indicated compression would not reduce size.
     * This was conservative: deflateBound over-estimates, so borderline
     * inputs (just above COMPRESS_LIMIT) were never compressed.
     *
     * v2.1.0 removes the pre-check and instead verifies the actual
     * compressed output size after deflation (see below).
     */

    uint8_t *tmp = malloc(bound);
    if (!tmp) {
        deflateEnd(&strm);
        return false;
    }

    strm.next_in   = (uint8_t *)input;
    strm.avail_in  = (uInt)inlen;
    strm.next_out  = tmp;
    strm.avail_out = (uInt)bound;

    if (deflate(&strm, Z_FINISH) != Z_STREAM_END) {
        free(tmp);
        deflateEnd(&strm);
        return false;
    }

    size_t compressed_len = bound - strm.avail_out;
    deflateEnd(&strm);

    /* Total output includes the uint32_t original-size header */
    size_t total = compressed_len + sizeof(uint32_t);

    /* v2.1.0: check actual compressed size (replaces the bound check) */
    if (total >= inlen) {
        free(tmp);
        return false;
    }

    *output = malloc(total);
    if (!*output) {
        free(tmp);
        return false;
    }

    /* Pack: [original_size][compressed_data] */
    uint32_t orig_size = (uint32_t)inlen;
    memcpy(*output, &orig_size, sizeof(uint32_t));
    memcpy(*output + sizeof(uint32_t), tmp, compressed_len);
    *outlen = total;

    free(tmp);
    return true;
}

static bool zlib_decompress_block(const uint8_t *input, size_t inlen,
                                  uint8_t **output, size_t *outlen)
{
    if (inlen <= sizeof(uint32_t)) return false;

    uint32_t orig_size;
    memcpy(&orig_size, input, sizeof(uint32_t));

    *output = malloc(orig_size + 1);
    if (!*output) return false;

    z_stream strm;
    memset(&strm, 0, sizeof(strm));

    if (inflateInit(&strm) != Z_OK) {
        free(*output);
        return false;
    }

    strm.next_in   = (uint8_t *)(input + sizeof(uint32_t));
    strm.avail_in  = (uInt)(inlen - sizeof(uint32_t));
    strm.next_out  = *output;
    strm.avail_out = orig_size;

    int ret = inflate(&strm, Z_FINISH);
    inflateEnd(&strm);

    if (ret != Z_STREAM_END) {
        free(*output);
        *output = NULL;
        return false;
    }

    (*output)[orig_size] = '\0';
    *outlen = orig_size;
    return true;
}

/* ----------------------------------------------------------------
 * Codec entry points
 * ---------------------------------------------------------------- */

int ppn_encode(ppn_map_t *map, uint8_t **out_data, size_t *out_len)
{
    if (!map || !out_data || !out_len) return -1;

    /* Serialize the rank-list to text */
    size_t raw_len;
    char *raw = serialize_rank_list(map, &raw_len);
    if (!raw) return -1;

    /* Try compression if above the threshold */
    if (raw_len >= COMPRESS_LIMIT) {
        uint8_t *cdata;
        size_t   clen;
        if (zlib_compress_block((uint8_t *)raw, raw_len, &cdata, &clen)) {
            /* Compressed format: [TAG_BLOB][compressed_block] */
            *out_len  = 1 + clen;
            *out_data = malloc(*out_len);
            if (!*out_data) {
                free(cdata);
                free(raw);
                return -1;
            }
            (*out_data)[0] = TAG_BLOB;
            memcpy(*out_data + 1, cdata, clen);
            free(cdata);
            free(raw);
            return 0;
        }
    }

    /* Raw format: [TAG_RAW][rank_list_text] */
    *out_len  = 1 + raw_len;
    *out_data = malloc(*out_len);
    if (!*out_data) {
        free(raw);
        return -1;
    }
    (*out_data)[0] = TAG_RAW;
    memcpy(*out_data + 1, raw, raw_len);
    free(raw);
    return 0;
}

ppn_map_t *ppn_decode(const uint8_t *data, size_t len)
{
    if (!data || len < 2) return NULL;

    uint8_t tag = data[0];

    /* --- Compressed blob format --- */
    if (tag == TAG_BLOB) {
        uint8_t *decompressed;
        size_t   decomp_len;

        if (!zlib_decompress_block(data + 1, len - 1,
                                   &decompressed, &decomp_len)) {
            return NULL;
        }

        /*
         * Decompressed payload is the rank-list text.
         * Feed it back through the decode pipeline for
         * format-aware parsing.
         *
         * Refactored in v2.1.0: previously called an internal
         * parsing routine directly; now uses the unified decode
         * entry point for consistency across all callers.
         */
        ppn_map_t *result = ppn_decode(decompressed, decomp_len);
        free(decompressed);
        return result;
    }

    /* --- Raw text format --- */
    if (tag == TAG_RAW) {
        return deserialize_rank_list((const char *)(data + 1), len - 1);
    }

    /*
     * Fallback: unrecognized format tag.
     *
     * Attempt best-effort topology extraction for forward compatibility
     * with future native-format encodings.  Count semicolons to determine
     * node count and assign one representative process per node.
     */
    int nnodes = 1;
    for (size_t i = 0; i < len; i++) {
        if (data[i] == ';') nnodes++;
    }

    ppn_map_t *map = ppn_map_alloc(nnodes);
    if (!map) return NULL;

    map->total_procs = nnodes;
    for (int n = 0; n < nnodes; n++) {
        map->nodes[n].node_id  = n;
        map->nodes[n].nranks   = 1;
        map->nodes[n].ranks    = malloc(sizeof(int));
        map->nodes[n].ranks[0] = n;
    }

    return map;
}
