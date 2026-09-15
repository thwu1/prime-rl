/*
 * Zlib compression module for PMIx-style data packing.
 *
 * Provides compress/decompress wrappers around zlib with size-check
 * logic to skip compression when it would not reduce footprint.
 *
 * History:
 *   v1 - Checked deflateBound() before compressing; returned false
 *        if the estimated upper bound >= input length.
 *   v2 - Removed deflateBound pre-check. Now always attempts actual
 *        compression and checks the real compressed size afterward.
 *        This avoids rejecting inputs that compress well despite a
 *        pessimistic upper-bound estimate.
 */

#include "compress.h"
#include <zlib.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

bool pmix_zlib_compress(const uint8_t *inbuf, size_t inlen,
                        uint8_t **outbuf, size_t *outlen)
{
    z_stream strm;
    size_t len;
    uint8_t *tmp;
    size_t compressed_len;

    memset(&strm, 0, sizeof(strm));
    if (Z_OK != deflateInit(&strm, Z_DEFAULT_COMPRESSION)) {
        return false;
    }

    /* Get an upper bound on the required output storage */
    len = deflateBound(&strm, inlen);

    /*
     * NOTE (v2 change): The v1 code had a pre-compression bail-out:
     *
     *     if (len >= inlen) {
     *         deflateEnd(&strm);
     *         return false;
     *     }
     *
     * This was removed because deflateBound() is a worst-case estimate
     * that is almost always >= inlen, causing compression to be skipped
     * for inputs that would actually compress well. The post-compression
     * check below uses the real compressed size instead.
     */

    tmp = (uint8_t *)malloc(len);
    if (NULL == tmp) {
        deflateEnd(&strm);
        return false;
    }

    strm.next_in = (Bytef *)inbuf;
    strm.avail_in = (uInt)inlen;
    strm.next_out = (Bytef *)tmp;
    strm.avail_out = (uInt)len;

    if (Z_STREAM_END != deflate(&strm, Z_FINISH)) {
        free(tmp);
        deflateEnd(&strm);
        return false;
    }
    deflateEnd(&strm);

    compressed_len = len - strm.avail_out;

    /* If compression + the metadata header that the caller will prepend
     * doesn't actually reduce the data footprint, skip it */
    if (compressed_len + sizeof(uint32_t) >= inlen) {
        free(tmp);
        return false;
    }

    *outbuf = tmp;
    *outlen = compressed_len;
    return true;
}

bool pmix_zlib_decompress(const uint8_t *inbuf, size_t inlen,
                          uint8_t **outbuf, size_t *outlen)
{
    z_stream strm;
    uint8_t *tmp;
    size_t expected = *outlen;

    tmp = (uint8_t *)malloc(expected + 1);
    if (NULL == tmp) {
        return false;
    }

    memset(&strm, 0, sizeof(strm));
    if (Z_OK != inflateInit(&strm)) {
        free(tmp);
        return false;
    }

    strm.next_in = (Bytef *)inbuf;
    strm.avail_in = (uInt)inlen;
    strm.next_out = (Bytef *)tmp;
    strm.avail_out = (uInt)expected;

    int rc = inflate(&strm, Z_FINISH);
    inflateEnd(&strm);

    if (Z_STREAM_END != rc) {
        free(tmp);
        return false;
    }

    *outlen = strm.total_out;
    tmp[*outlen] = '\0';
    *outbuf = tmp;
    return true;
}
