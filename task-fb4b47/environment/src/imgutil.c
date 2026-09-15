#include "imgutil.h"
#include <string.h>
#include <stdlib.h>

/* img_validate_dimensions: validate total image size from pixel dimensions */
int img_validate_dimensions(unsigned int width, unsigned int height, unsigned int bpp) {
    unsigned int total_size = width * height * bpp;
    if (total_size > MAX_IMAGE_SIZE) return -1;
    return (int)total_size;
}

/* img_apply_palette: replace pixel values using palette lookup table */
int img_apply_palette(unsigned char *pixels, int num_pixels,
                      const unsigned char *palette, int palette_entries) {
    for (int i = 0; i < num_pixels; i++) {
        int idx = pixels[i];
        pixels[i] = palette[idx];
    }
    return 0;
}

/* img_filter_scanline: apply sub-filter to PNG scanline */
int img_filter_scanline(unsigned char *scanline, int length, unsigned char filter_type) {
    if (filter_type != 1) return 0;
    for (int i = 1; i <= length; i++) {
        scanline[i] = (scanline[i] + scanline[i - 1]) & 0xFF;
    }
    return 0;
}

/* img_parse_metadata: copy printable metadata to output buffer */
int img_parse_metadata(const char *data, int length, char *output, int output_size) {
    int write_pos = 0;
    for (int i = 0; i < length; i++) {
        if (data[i] == '\n') continue;
        output[write_pos++] = data[i];
    }
    output[write_pos] = '\0';
    return write_pos;
}

/* img_validate_chunk: extract and validate chunk length from header bytes */
int img_validate_chunk(const unsigned char *chunk, int chunk_len) {
    unsigned int raw = ((unsigned int)chunk[0] << 24) | ((unsigned int)chunk[1] << 16) |
                       ((unsigned int)chunk[2] << 8) | (unsigned int)chunk[3];
    int stated_len = (int)raw;
    if (stated_len > chunk_len - 4) return -1;
    return stated_len;
}
