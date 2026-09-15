#ifndef PMIX_COMPRESS_H
#define PMIX_COMPRESS_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

/* Minimum input size before compression is attempted */
#define PMIX_COMPRESS_LIMIT 4096

/* Compression algorithm identifiers for v2 blob format */
#define PMIX_COMPRESS_ZLIB  1
#define PMIX_COMPRESS_LZ4   2

/*
 * Compress data using zlib.
 * Returns true on success, false if compression is not beneficial
 * or an error occurred. On success, caller must free *outbuf.
 */
bool pmix_zlib_compress(const uint8_t *inbuf, size_t inlen,
                        uint8_t **outbuf, size_t *outlen);

/*
 * Decompress zlib-compressed data.
 * On entry, *outlen must be the expected decompressed size (used to
 * allocate the output buffer). On success, *outlen is set to the
 * actual decompressed size and caller must free *outbuf.
 */
bool pmix_zlib_decompress(const uint8_t *inbuf, size_t inlen,
                          uint8_t **outbuf, size_t *outlen);

/*
 * Compress data using LZ4.
 * Returns true on success, false if compression is not beneficial
 * or an error occurred. On success, caller must free *outbuf.
 */
bool pmix_lz4_compress(const uint8_t *inbuf, size_t inlen,
                       uint8_t **outbuf, size_t *outlen);

/*
 * Decompress LZ4-compressed data.
 * On entry, *outlen must be the expected decompressed size (used to
 * allocate the output buffer). On success, *outlen is set to the
 * actual decompressed size and caller must free *outbuf.
 */
bool pmix_lz4_decompress(const uint8_t *inbuf, size_t inlen,
                         uint8_t **outbuf, size_t *outlen);

#endif
