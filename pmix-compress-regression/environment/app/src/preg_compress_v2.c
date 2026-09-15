/*
 * v2 Compressed PPN encoding backend.
 *
 * v2 wire format (all multi-byte fields in network byte order):
 *   "blob2:" prefix (6 bytes)
 *   1-byte algorithm identifier (PMIX_COMPRESS_ZLIB=1 or PMIX_COMPRESS_LZ4=2)
 *   4-byte uncompressed data length
 *   4-byte compressed data length
 *   compressed data bytes
 *
 * The v2 encoder should try both zlib and LZ4 compression on the raw
 * rank string, then select whichever produces the smaller output.
 * If neither compression is beneficial (v2 encoding >= raw encoding),
 * return -1 to fall through to the next encoding module.
 *
 * TODO: Implement generate and parse functions.
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
    (void)map; (void)output; (void)outlen;
    /* Not yet implemented */
    return -1;
}

int preg_compress_v2_parse(const char *input, size_t inlen,
                           pmix_proc_map_t *map)
{
    (void)input; (void)inlen; (void)map;
    /* Not yet implemented */
    return -1;
}
