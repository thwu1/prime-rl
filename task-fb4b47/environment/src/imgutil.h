#ifndef IMGUTIL_H
#define IMGUTIL_H

#include <stdint.h>

#define MAX_IMAGE_SIZE (1024 * 1024 * 256)

int img_validate_dimensions(unsigned int width, unsigned int height, unsigned int bpp);
int img_apply_palette(unsigned char *pixels, int num_pixels,
                      const unsigned char *palette, int palette_entries);
int img_filter_scanline(unsigned char *scanline, int length, unsigned char filter_type);
int img_parse_metadata(const char *data, int length, char *output, int output_size);
int img_validate_chunk(const unsigned char *chunk, int chunk_len);

#endif
