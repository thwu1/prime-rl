#!/usr/bin/env python3
"""
fix_codec.py - Fix TAG_BLOB decoder bug, implement TAG_PACKED format,
               and add auto-format-selection to ppn_encode().

"""

import os

# ---------- Update ppn_codec.h with encoding-type constants ----------

HEADER = r'''/*
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

/* TAG_PACKED per-node encoding types */
#define PACKED_CONTIGUOUS 0x00
#define PACKED_STRIDED    0x01
#define PACKED_EXPLICIT   0x02

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
 * The encoder selects the format that produces the smallest output.
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
'''

# ---------- Write complete fixed ppn_codec.c ----------

CODEC = r'''/*
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
 * ---------------------------------------------------------------- */

static char *serialize_rank_list(ppn_map_t *map, size_t *out_len)
{
    size_t needed = 0;
    for (int n = 0; n < map->nnodes; n++) {
        for (int r = 0; r < map->nodes[n].nranks; r++) {
            char tmp[16];
            needed += (size_t)snprintf(tmp, sizeof(tmp), "%d",
                                       map->nodes[n].ranks[r]);
            if (r < map->nodes[n].nranks - 1) needed++;
        }
        if (n < map->nnodes - 1) needed++;
    }

    char *buf = malloc(needed + 1);
    if (!buf) return NULL;

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

    char *copy = malloc(len + 1);
    if (!copy) return NULL;
    memcpy(copy, str, len);
    copy[len] = '\0';

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

        int nranks = 1;
        for (char *c = node_tok; *c; c++) {
            if (*c == ',') nranks++;
        }

        map->nodes[n].nranks = nranks;
        map->nodes[n].ranks  = calloc(nranks, sizeof(int));

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
 * ---------------------------------------------------------------- */

static bool zlib_compress_block(const uint8_t *input, size_t inlen,
                                uint8_t **output, size_t *outlen)
{
    z_stream strm;
    memset(&strm, 0, sizeof(strm));

    if (deflateInit(&strm, Z_DEFAULT_COMPRESSION) != Z_OK)
        return false;

    size_t bound = deflateBound(&strm, inlen);

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

    size_t total = compressed_len + sizeof(uint32_t);

    if (total >= inlen) {
        free(tmp);
        return false;
    }

    *output = malloc(total);
    if (!*output) {
        free(tmp);
        return false;
    }

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
 * TAG_PACKED binary format encoder/decoder
 * ---------------------------------------------------------------- */

static void write_u16_le(uint8_t *buf, uint16_t val) {
    buf[0] = val & 0xFF;
    buf[1] = (val >> 8) & 0xFF;
}

static void write_u32_le(uint8_t *buf, uint32_t val) {
    buf[0] = val & 0xFF;
    buf[1] = (val >> 8) & 0xFF;
    buf[2] = (val >> 16) & 0xFF;
    buf[3] = (val >> 24) & 0xFF;
}

static void write_i16_le(uint8_t *buf, int16_t val) {
    write_u16_le(buf, (uint16_t)val);
}

static uint16_t read_u16_le(const uint8_t *buf) {
    return (uint16_t)buf[0] | ((uint16_t)buf[1] << 8);
}

static uint32_t read_u32_le(const uint8_t *buf) {
    return (uint32_t)buf[0] | ((uint32_t)buf[1] << 8) |
           ((uint32_t)buf[2] << 16) | ((uint32_t)buf[3] << 24);
}

static int16_t read_i16_le(const uint8_t *buf) {
    return (int16_t)read_u16_le(buf);
}

/* Classify a node's rank pattern for encoding type selection */
static int classify_node_ranks(node_map_t *node)
{
    if (node->nranks <= 1) return PACKED_CONTIGUOUS;

    /* Check contiguous (stride 1) */
    int contiguous = 1;
    for (int r = 1; r < node->nranks; r++) {
        if (node->ranks[r] != node->ranks[0] + r) {
            contiguous = 0;
            break;
        }
    }
    if (contiguous) return PACKED_CONTIGUOUS;

    /* Check constant stride */
    int stride = node->ranks[1] - node->ranks[0];
    int strided = 1;
    for (int r = 2; r < node->nranks; r++) {
        if (node->ranks[r] - node->ranks[r - 1] != stride) {
            strided = 0;
            break;
        }
    }
    if (strided) return PACKED_STRIDED;

    return PACKED_EXPLICIT;
}

/* Compute TAG_PACKED wire size without encoding */
static size_t compute_packed_size(ppn_map_t *map)
{
    size_t sz = 1 + 2;  /* tag + nnodes */
    for (int n = 0; n < map->nnodes; n++) {
        sz += 2 + 1;    /* nranks + enc_type */
        int enc = classify_node_ranks(&map->nodes[n]);
        switch (enc) {
            case PACKED_CONTIGUOUS: sz += 4; break;
            case PACKED_STRIDED:    sz += 6; break;
            case PACKED_EXPLICIT:   sz += 4 * (size_t)map->nodes[n].nranks; break;
        }
    }
    return sz;
}

/* Encode a map in TAG_PACKED format */
static int encode_packed(ppn_map_t *map, uint8_t **out_data, size_t *out_len)
{
    size_t sz = compute_packed_size(map);
    uint8_t *buf = malloc(sz);
    if (!buf) return -1;

    uint8_t *p = buf;
    *p++ = TAG_PACKED;
    write_u16_le(p, (uint16_t)map->nnodes); p += 2;

    for (int n = 0; n < map->nnodes; n++) {
        write_u16_le(p, (uint16_t)map->nodes[n].nranks); p += 2;
        int enc = classify_node_ranks(&map->nodes[n]);
        *p++ = (uint8_t)enc;

        switch (enc) {
            case PACKED_CONTIGUOUS:
                write_u32_le(p, (uint32_t)(map->nodes[n].nranks > 0
                    ? map->nodes[n].ranks[0] : 0));
                p += 4;
                break;
            case PACKED_STRIDED:
                write_u32_le(p, (uint32_t)map->nodes[n].ranks[0]);
                p += 4;
                write_i16_le(p, (int16_t)(map->nodes[n].ranks[1] -
                                          map->nodes[n].ranks[0]));
                p += 2;
                break;
            case PACKED_EXPLICIT:
                for (int r = 0; r < map->nodes[n].nranks; r++) {
                    write_u32_le(p, (uint32_t)map->nodes[n].ranks[r]);
                    p += 4;
                }
                break;
        }
    }

    *out_data = buf;
    *out_len  = sz;
    return 0;
}

/* Decode a TAG_PACKED buffer (data points past the tag byte) */
static ppn_map_t *decode_packed(const uint8_t *data, size_t len)
{
    if (len < 2) return NULL;

    uint16_t nnodes = read_u16_le(data); data += 2; len -= 2;
    ppn_map_t *map = ppn_map_alloc(nnodes);
    if (!map) return NULL;

    for (int n = 0; n < nnodes; n++) {
        if (len < 3) goto err;
        uint16_t nranks = read_u16_le(data); data += 2; len -= 2;
        uint8_t enc_type = *data++; len--;

        map->nodes[n].node_id = n;
        map->nodes[n].nranks  = nranks;
        map->nodes[n].ranks   = calloc(nranks, sizeof(int));
        if (nranks > 0 && !map->nodes[n].ranks) goto err;

        switch (enc_type) {
            case PACKED_CONTIGUOUS: {
                if (len < 4) goto err;
                uint32_t first = read_u32_le(data); data += 4; len -= 4;
                for (int r = 0; r < nranks; r++)
                    map->nodes[n].ranks[r] = (int)(first + (uint32_t)r);
                break;
            }
            case PACKED_STRIDED: {
                if (len < 6) goto err;
                uint32_t first = read_u32_le(data); data += 4; len -= 4;
                int16_t stride = read_i16_le(data); data += 2; len -= 2;
                for (int r = 0; r < nranks; r++)
                    map->nodes[n].ranks[r] = (int)first + r * (int)stride;
                break;
            }
            case PACKED_EXPLICIT: {
                size_t need = 4 * (size_t)nranks;
                if (len < need) goto err;
                for (int r = 0; r < nranks; r++) {
                    map->nodes[n].ranks[r] = (int)read_u32_le(data);
                    data += 4; len -= 4;
                }
                break;
            }
            default:
                goto err;
        }
        map->total_procs += nranks;
    }

    return map;

err:
    ppn_map_free(map);
    return NULL;
}

/* ----------------------------------------------------------------
 * Codec entry points
 * ---------------------------------------------------------------- */

int ppn_encode(ppn_map_t *map, uint8_t **out_data, size_t *out_len)
{
    if (!map || !out_data || !out_len) return -1;

    /* Serialize rank-list to text (needed for RAW and BLOB) */
    size_t raw_text_len;
    char *raw_text = serialize_rank_list(map, &raw_text_len);
    if (!raw_text) return -1;

    /* Compute all candidate sizes */
    size_t raw_total = 1 + raw_text_len;

    /* TAG_BLOB: only attempt if text is large enough */
    uint8_t *blob_cdata = NULL;
    size_t blob_clen = 0;
    size_t blob_total = (size_t)-1;  /* effectively infinity */
    if (raw_text_len >= COMPRESS_LIMIT) {
        if (zlib_compress_block((uint8_t *)raw_text, raw_text_len,
                                &blob_cdata, &blob_clen)) {
            blob_total = 1 + blob_clen;
        }
    }

    /* TAG_PACKED */
    size_t packed_total = compute_packed_size(map);

    /* Select smallest format.  Tie-breaking: PACKED > BLOB > RAW */
    uint8_t best = TAG_RAW;
    size_t best_size = raw_total;

    if (blob_cdata && blob_total <= best_size) {
        best = TAG_BLOB;
        best_size = blob_total;
    }

    if (packed_total <= best_size) {
        best = TAG_PACKED;
        best_size = packed_total;
    }

    int result = -1;

    switch (best) {
        case TAG_PACKED:
            free(blob_cdata);
            free(raw_text);
            return encode_packed(map, out_data, out_len);

        case TAG_BLOB:
            *out_len  = 1 + blob_clen;
            *out_data = malloc(*out_len);
            if (*out_data) {
                (*out_data)[0] = TAG_BLOB;
                memcpy(*out_data + 1, blob_cdata, blob_clen);
                result = 0;
            }
            free(blob_cdata);
            free(raw_text);
            return result;

        default: /* TAG_RAW */
            free(blob_cdata);
            *out_len  = 1 + raw_text_len;
            *out_data = malloc(*out_len);
            if (*out_data) {
                (*out_data)[0] = TAG_RAW;
                memcpy(*out_data + 1, raw_text, raw_text_len);
                result = 0;
            }
            free(raw_text);
            return result;
    }
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
         * FIX: decompressed payload is raw rank-list text (no format tag).
         * Call the text parser directly instead of re-entering ppn_decode,
         * which would mis-interpret the first text byte as a format tag.
         */
        ppn_map_t *result = deserialize_rank_list(
            (const char *)decompressed, decomp_len);
        free(decompressed);
        return result;
    }

    /* --- Raw text format --- */
    if (tag == TAG_RAW) {
        return deserialize_rank_list((const char *)(data + 1), len - 1);
    }

    /* --- Packed binary format --- */
    if (tag == TAG_PACKED) {
        return decode_packed(data + 1, len - 1);
    }

    /*
     * Fallback: unrecognized format tag.
     * Best-effort topology extraction for forward compatibility.
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
'''


def main():
    with open("/app/ppn_codec.h", "w") as f:
        f.write(HEADER)
    print("Updated /app/ppn_codec.h")

    with open("/app/ppn_codec.c", "w") as f:
        f.write(CODEC)
    print("Updated /app/ppn_codec.c")


if __name__ == "__main__":
    main()
