/*
 * LZ4 compression module for PMIx-style data packing.
 *
 * Provides compress/decompress wrappers around liblz4.
 * TODO: Implement using the liblz4 API (lz4.h).
 */

#include "compress.h"
#include <stdlib.h>

bool pmix_lz4_compress(const uint8_t *inbuf, size_t inlen,
                       uint8_t **outbuf, size_t *outlen)
{
    (void)inbuf; (void)inlen; (void)outbuf; (void)outlen;
    /* Not yet implemented */
    return false;
}

bool pmix_lz4_decompress(const uint8_t *inbuf, size_t inlen,
                         uint8_t **outbuf, size_t *outlen)
{
    (void)inbuf; (void)inlen; (void)outbuf; (void)outlen;
    /* Not yet implemented */
    return false;
}
