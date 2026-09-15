#ifndef LZ4_BLOCK_H
#define LZ4_BLOCK_H

#include <stdint.h>

/*
 * LZ4 Block Format Compressor/Decompressor
 *
 * These functions work with raw LZ4 block format data
 * as described in the LZ4 Block Format Specification.
 * They do NOT handle the LZ4 Frame Format (magic numbers,
 * frame descriptors, checksums, etc.)
 */

/* Compress src_size bytes from src into dst buffer.
 * dst_capacity must be >= lz4_compress_bound(src_size).
 * Returns: number of compressed bytes written to dst,
 *          or 0 on failure (insufficient output space). */
int lz4_block_compress(const uint8_t* src, uint8_t* dst,
                       int src_size, int dst_capacity);

/* Decompress compressed data from src into dst buffer.
 * src_size is the exact size of the compressed block.
 * dst_capacity is the maximum decompressed size.
 * Returns: number of decompressed bytes written to dst,
 *          or negative error code on failure. */
int lz4_block_decompress(const uint8_t* src, uint8_t* dst,
                         int src_size, int dst_capacity);

/* Returns maximum possible compressed output size for a given
 * input size. Use this to allocate the dst buffer. */
int lz4_compress_bound(int input_size);

#endif /* LZ4_BLOCK_H */
