/*
 * PREG framework: dispatches PPN encoding/decoding to backend modules.
 *
 * Encoding priority: v2 compressed (blob2) -> v1 compressed (blob) -> raw
 * Parsing: dispatch based on prefix ("blob2:", "blob:", "raw:")
 */

#include "preg.h"
#include <string.h>
#include <stdio.h>

/* Backend: v2 compressed blob encoding (preg_compress_v2.c) */
extern int preg_compress_v2_generate(const pmix_proc_map_t *map,
                                     char **output, size_t *outlen);
extern int preg_compress_v2_parse(const char *input, size_t inlen,
                                  pmix_proc_map_t *map);

/* Backend: v1 compressed blob encoding (preg_compress.c) */
extern int preg_compress_generate(const pmix_proc_map_t *map,
                                  char **output, size_t *outlen);
extern int preg_compress_parse(const char *input, size_t inlen,
                               pmix_proc_map_t *map);

/* Backend: raw text encoding (preg_raw.c) */
extern int preg_raw_generate(const pmix_proc_map_t *map,
                             char **output, size_t *outlen);
extern int preg_raw_parse(const char *input, size_t inlen,
                          pmix_proc_map_t *map);

int pmix_preg_generate(const pmix_proc_map_t *map,
                       char **output, size_t *outlen)
{
    /* Try v2 compressed encoding first (dual-backend selection) */
    if (preg_compress_v2_generate(map, output, outlen) == 0) {
        return 0;
    }

    /* Fall back to v1 compressed encoding */
    if (preg_compress_generate(map, output, outlen) == 0) {
        return 0;
    }

    /* Fall back to raw text encoding */
    return preg_raw_generate(map, output, outlen);
}

int pmix_preg_parse(const char *input, size_t inlen,
                    pmix_proc_map_t *map)
{
    if (inlen > 6 && strncmp(input, "blob2:", 6) == 0) {
        return preg_compress_v2_parse(input, inlen, map);
    }
    if (inlen > 5 && strncmp(input, "blob:", 5) == 0) {
        return preg_compress_parse(input, inlen, map);
    }
    if (inlen > 4 && strncmp(input, "raw:", 4) == 0) {
        return preg_raw_parse(input, inlen, map);
    }

    fprintf(stderr, "pmix_preg_parse: unrecognized format prefix\n");
    return -1;
}
