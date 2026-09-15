#!/usr/bin/env python3
"""
Apply all fixes for the PMIx PPN multi-backend compression task.

"""

import os

# --- Fix 1: preg_compress.c (one-variable fix) ---
preg_compress_path = "/app/src/preg_compress.c"
with open(preg_compress_path, "r") as f:
    content = f.read()

content = content.replace(
    "uint32_t hdr = htonl((uint32_t)len);",
    "uint32_t hdr = htonl((uint32_t)dlen);"
)

with open(preg_compress_path, "w") as f:
    f.write(content)

print("Fix 1: patched preg_compress.c (len -> dlen in blob header)")

# --- Fix 2: compress_lz4.c (full LZ4 implementation) ---
compress_lz4_code = r'''/*
 * LZ4 compression module for PMIx-style data packing.
 *
 * Provides compress/decompress wrappers around liblz4.
 */

#include "compress.h"
#include <lz4.h>
#include <stdlib.h>
#include <string.h>

bool pmix_lz4_compress(const uint8_t *inbuf, size_t inlen,
                       uint8_t **outbuf, size_t *outlen)
{
    if (inlen == 0 || (int)inlen < 0) {
        return false;
    }

    int max_dst = LZ4_compressBound((int)inlen);
    if (max_dst <= 0) return false;

    uint8_t *tmp = (uint8_t *)malloc((size_t)max_dst);
    if (!tmp) return false;

    int compressed = LZ4_compress_default(
        (const char *)inbuf, (char *)tmp, (int)inlen, max_dst);

    if (compressed <= 0) {
        free(tmp);
        return false;
    }

    /* If compression doesn't reduce size, skip it */
    if ((size_t)compressed >= inlen) {
        free(tmp);
        return false;
    }

    *outbuf = tmp;
    *outlen = (size_t)compressed;
    return true;
}

bool pmix_lz4_decompress(const uint8_t *inbuf, size_t inlen,
                         uint8_t **outbuf, size_t *outlen)
{
    size_t expected = *outlen;
    if (expected == 0) return false;

    uint8_t *tmp = (uint8_t *)malloc(expected + 1);
    if (!tmp) return false;

    int result = LZ4_decompress_safe(
        (const char *)inbuf, (char *)tmp, (int)inlen, (int)expected);

    if (result < 0) {
        free(tmp);
        return false;
    }

    *outlen = (size_t)result;
    tmp[*outlen] = '\0';
    *outbuf = tmp;
    return true;
}
'''

with open("/app/src/compress_lz4.c", "w") as f:
    f.write(compress_lz4_code)

print("Fix 2: implemented compress_lz4.c with full LZ4 backend")

# --- Fix 3: preg_compress_v2.c (full v2 encoder/decoder) ---
preg_v2_code = r'''/*
 * v2 Compressed PPN encoding backend.
 *
 * v2 wire format (all multi-byte fields in network byte order):
 *   "blob2:" prefix (6 bytes)
 *   1-byte algorithm identifier (PMIX_COMPRESS_ZLIB=1 or PMIX_COMPRESS_LZ4=2)
 *   4-byte uncompressed data length
 *   4-byte compressed data length
 *   compressed data bytes
 *
 * The v2 encoder tries both zlib and LZ4 compression on the raw rank
 * string, selects whichever produces the smaller output, and packs
 * the result with the v2 header. If neither compression is beneficial,
 * returns -1 to fall through to the next encoding module.
 */

#include "preg.h"
#include "compress.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <arpa/inet.h>

extern int preg_raw_generate(const pmix_proc_map_t *map,
                             char **output, size_t *outlen);
extern int preg_raw_parse(const char *input, size_t inlen,
                          pmix_proc_map_t *map);

int preg_compress_v2_generate(const pmix_proc_map_t *map,
                              char **output, size_t *outlen)
{
    char *raw_out = NULL;
    size_t raw_len = 0;

    /* Step 1: generate the raw text representation */
    if (preg_raw_generate(map, &raw_out, &raw_len) != 0) {
        return -1;
    }

    /* Compress only the data part (skip "raw:" prefix) */
    const uint8_t *raw_data = (const uint8_t *)(raw_out + 4);
    size_t dlen = raw_len - 4;

    /* Only attempt compression for data exceeding the threshold */
    if (dlen < PMIX_COMPRESS_LIMIT) {
        free(raw_out);
        return -1;
    }

    /* Step 2: try both compression backends */
    uint8_t *zlib_buf = NULL, *lz4_buf = NULL;
    size_t zlib_len = 0, lz4_len = 0;
    bool have_zlib = pmix_zlib_compress(raw_data, dlen, &zlib_buf, &zlib_len);
    bool have_lz4 = pmix_lz4_compress(raw_data, dlen, &lz4_buf, &lz4_len);

    /* Step 3: select the best compression backend */
    uint8_t algo;
    uint8_t *cbuf;
    size_t clen;

    if (have_zlib && have_lz4) {
        if (lz4_len <= zlib_len) {
            algo = PMIX_COMPRESS_LZ4;
            cbuf = lz4_buf; clen = lz4_len;
            free(zlib_buf);
        } else {
            algo = PMIX_COMPRESS_ZLIB;
            cbuf = zlib_buf; clen = zlib_len;
            free(lz4_buf);
        }
    } else if (have_zlib) {
        algo = PMIX_COMPRESS_ZLIB;
        cbuf = zlib_buf; clen = zlib_len;
    } else if (have_lz4) {
        algo = PMIX_COMPRESS_LZ4;
        cbuf = lz4_buf; clen = lz4_len;
    } else {
        free(raw_out);
        return -1;  /* neither backend produced beneficial compression */
    }

    /* Step 4: check if v2 encoding is smaller than raw encoding */
    /* v2 total = "blob2:" (6) + algo (1) + uncomp_len (4) + comp_len (4) + data */
    size_t total = 6 + 1 + 4 + 4 + clen;
    if (total >= raw_len) {
        free(cbuf);
        free(raw_out);
        return -1;  /* v2 encoding not smaller than raw */
    }

    /* Step 5: build the v2 blob output buffer */
    char *blob = (char *)malloc(total + 1);
    if (!blob) {
        free(cbuf);
        free(raw_out);
        return -1;
    }

    memcpy(blob, "blob2:", 6);
    blob[6] = (char)algo;

    uint32_t uncomp_hdr = htonl((uint32_t)dlen);
    memcpy(blob + 7, &uncomp_hdr, 4);

    uint32_t comp_hdr = htonl((uint32_t)clen);
    memcpy(blob + 11, &comp_hdr, 4);

    memcpy(blob + 15, cbuf, clen);
    blob[total] = '\0';

    *output = blob;
    *outlen = total;

    free(cbuf);
    free(raw_out);
    return 0;
}

int preg_compress_v2_parse(const char *input, size_t inlen,
                           pmix_proc_map_t *map)
{
    /* Skip "blob2:" prefix */
    const uint8_t *data = (const uint8_t *)(input + 6);
    size_t remaining = inlen - 6;

    /* Need at least 9 bytes for header: 1 algo + 4 uncomp + 4 comp */
    if (remaining < 9) {
        fprintf(stderr,
                "preg_compress_v2_parse: blob2 header too short (%zu bytes)\n",
                remaining);
        return -1;
    }

    /* Read the header fields */
    uint8_t algo = data[0];

    uint32_t uncomp_len;
    memcpy(&uncomp_len, data + 1, 4);
    uncomp_len = ntohl(uncomp_len);

    uint32_t comp_len;
    memcpy(&comp_len, data + 5, 4);
    comp_len = ntohl(comp_len);

    /* Compressed payload follows the 9-byte header */
    const uint8_t *cdata = data + 9;
    size_t cdata_avail = remaining - 9;

    if (cdata_avail < comp_len) {
        fprintf(stderr,
                "preg_compress_v2_parse: truncated compressed data "
                "(have %zu, need %u)\n", cdata_avail, comp_len);
        return -1;
    }

    /* Decompress using the specified algorithm */
    size_t decomp_len = (size_t)uncomp_len;
    uint8_t *decomp = NULL;
    bool ok;

    if (algo == PMIX_COMPRESS_ZLIB) {
        ok = pmix_zlib_decompress(cdata, comp_len, &decomp, &decomp_len);
    } else if (algo == PMIX_COMPRESS_LZ4) {
        ok = pmix_lz4_decompress(cdata, comp_len, &decomp, &decomp_len);
    } else {
        fprintf(stderr,
                "preg_compress_v2_parse: unknown algorithm %u\n", algo);
        return -1;
    }

    if (!ok) {
        fprintf(stderr,
                "preg_compress_v2_parse: decompression failed "
                "(algo=%u, header says %u uncompressed, %u compressed)\n",
                algo, uncomp_len, comp_len);
        return -1;
    }

    /* Wrap with "raw:" prefix and delegate to raw text parser */
    size_t wrapped_len = 4 + decomp_len;
    char *wrapped = (char *)malloc(wrapped_len + 1);
    if (!wrapped) {
        free(decomp);
        return -1;
    }

    memcpy(wrapped, "raw:", 4);
    memcpy(wrapped + 4, decomp, decomp_len);
    wrapped[wrapped_len] = '\0';

    int rc = preg_raw_parse(wrapped, wrapped_len, map);

    free(wrapped);
    free(decomp);
    return rc;
}
'''

with open("/app/src/preg_compress_v2.c", "w") as f:
    f.write(preg_v2_code)

print("Fix 3: implemented preg_compress_v2.c with v2 encoder/decoder")
print("All fixes applied.")
