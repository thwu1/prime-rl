/*
 * Compressed PPN encoding backend.
 *
 * Wire format:
 *   "blob:" + [4-byte header: original data length, network order] + [zlib data]
 *
 * This module generates a compressed representation of the process map
 * for cases where the raw text encoding exceeds the compression threshold.
 * It first generates the raw rank string internally, compresses it, and
 * wraps the result with a "blob:" prefix and size header.
 */

#include "preg.h"
#include "compress.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <arpa/inet.h>

/* Raw backend used internally to generate the rank string */
extern int preg_raw_generate(const pmix_proc_map_t *map,
                             char **output, size_t *outlen);
extern int preg_raw_parse(const char *input, size_t inlen,
                          pmix_proc_map_t *map);

int preg_compress_generate(const pmix_proc_map_t *map,
                           char **output, size_t *outlen)
{
    char *raw_out = NULL;
    size_t raw_len = 0;
    uint8_t *cbuf = NULL;
    size_t len = 0;

    /* Step 1: generate the raw text representation */
    if (preg_raw_generate(map, &raw_out, &raw_len) != 0) {
        return -1;
    }

    /* The raw output has a "raw:" prefix; we compress only the data part */
    const uint8_t *raw_data = (const uint8_t *)(raw_out + 4);
    size_t dlen = raw_len - 4;

    /* Only attempt compression for data exceeding the threshold */
    if (dlen < PMIX_COMPRESS_LIMIT) {
        free(raw_out);
        return -1;  /* signal: try next encoding module */
    }

    /* Step 2: compress the raw rank data */
    if (!pmix_zlib_compress(raw_data, dlen, &cbuf, &len)) {
        free(raw_out);
        return -1;  /* compression not beneficial */
    }

    /*
     * Step 3: build the blob output buffer.
     *
     * Layout:
     *   bytes 0-4:   "blob:" prefix
     *   bytes 5-8:   uint32_t header — uncompressed data length (network order)
     *   bytes 9-end: zlib compressed data
     *
     * The header lets the decoder allocate the right decompression buffer
     * without trial-and-error or storing the size out-of-band.
     */
    size_t total = 5 + sizeof(uint32_t) + len;
    char *blob = (char *)malloc(total + 1);
    if (!blob) {
        free(raw_out);
        free(cbuf);
        return -1;
    }

    memcpy(blob, "blob:", 5);

    /* Store the data length in network byte order for cross-arch portability */
    uint32_t hdr = htonl((uint32_t)len);
    memcpy(blob + 5, &hdr, sizeof(uint32_t));

    memcpy(blob + 5 + sizeof(uint32_t), cbuf, len);
    blob[total] = '\0';

    *output = blob;
    *outlen = total;

    free(raw_out);
    free(cbuf);
    return 0;
}

int preg_compress_parse(const char *input, size_t inlen,
                        pmix_proc_map_t *map)
{
    /* Skip "blob:" prefix */
    const uint8_t *data = (const uint8_t *)(input + 5);
    size_t dlen = inlen - 5;

    if (dlen <= sizeof(uint32_t)) {
        fprintf(stderr,
                "preg_compress_parse: blob data too short (%zu bytes)\n", dlen);
        return -1;
    }

    /* Read the original uncompressed data length from the header */
    uint32_t orig_len;
    memcpy(&orig_len, data, sizeof(uint32_t));
    orig_len = ntohl(orig_len);

    /* The compressed payload follows the 4-byte header */
    const uint8_t *cdata = data + sizeof(uint32_t);
    size_t cdata_len = dlen - sizeof(uint32_t);

    /* Decompress into a buffer sized according to the header */
    size_t decomp_len = (size_t)orig_len;
    uint8_t *decomp = NULL;

    if (!pmix_zlib_decompress(cdata, cdata_len, &decomp, &decomp_len)) {
        fprintf(stderr,
                "preg_compress_parse: decompression failed "
                "(header says %u bytes, %zu compressed bytes)\n",
                (unsigned)orig_len, cdata_len);
        return -1;
    }

    /* Wrap the decompressed data with "raw:" prefix and delegate parsing */
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
