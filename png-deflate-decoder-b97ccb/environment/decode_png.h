/* decode_png.h — Public API for the PNG decoder shared library */


#ifndef DECODE_PNG_H
#define DECODE_PNG_H

#include <stdint.h>
#include <stddef.h>

typedef struct {
    uint8_t  *pixels;    /* row-major, 8-bit per channel, caller frees via png_free */
    uint32_t  width;
    uint32_t  height;
    int       channels;  /* 1=G, 2=GA, 3=RGB, 4=RGBA */
} PngImage;

/* Decode PNG from a file path.  Returns 0 on success, -1 on error. */
int png_decode_file(const char *path, PngImage *img);

/* Decode PNG from an in-memory buffer.  Returns 0 on success, -1 on error. */
int png_decode_memory(const uint8_t *data, size_t len, PngImage *img);

/* Free pixel data allocated by png_decode_file / png_decode_memory. */
void png_free(PngImage *img);

#endif /* DECODE_PNG_H */
