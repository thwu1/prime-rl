#ifndef PARSER_H
#define PARSER_H

#include <stdint.h>
#include <stddef.h>

#define IMG_MAGIC 0x50474D49  /* "IMGP" in little-endian */

typedef struct {
    uint8_t r, g, b;
} color_t;

typedef struct {
    uint32_t width;
    uint32_t height;
    uint8_t channels;
    uint8_t *pixels;
    color_t *palette;
    uint8_t palette_count;
    char *comment;
    int32_t *offsets;
    uint16_t offset_count;
} image_t;

image_t *img_parse(const uint8_t *data, size_t len);
void img_free(image_t *img);

#endif /* PARSER_H */
