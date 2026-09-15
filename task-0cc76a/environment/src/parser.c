/*
 * parser.c - IMGP binary image format parser
 *
 * Format specification:
 *   Header (14 bytes):
 *     bytes  0-3:  magic "IMGP" (uint32_t LE = 0x50474D49)
 *     bytes  4-7:  width  (uint32_t LE)
 *     bytes  8-11: height (uint32_t LE)
 *     byte   12:   channels (uint8_t, 1-4)
 *     byte   13:   num_chunks (uint8_t)
 *
 *   Chunks (repeated num_chunks times):
 *     byte   0:    type (uint8_t)
 *     bytes  1-2:  length (uint16_t LE, length of chunk data)
 *     bytes  3+:   data (length bytes)
 *
 *   Chunk types:
 *     0x01 PALETTE: num_colors(1) + num_colors*3 RGB triples
 *     0x02 PIXELS:  palette index bytes mapped via apply_palette()
 *     0x03 COMMENT: raw text bytes
 *     0x04 OFFSETS: count(2) + count*4 int32_t LE offset values
 *     0x05 RLE:     write_offset(4) + (run_length(1), value(1))* pairs
 */

#include "parser.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define CHUNK_PALETTE  0x01
#define CHUNK_PIXELS   0x02
#define CHUNK_COMMENT  0x03
#define CHUNK_OFFSETS  0x04
#define CHUNK_RLE      0x05

/* Upper bound for individual dimension values */
#define MAX_DIMENSION  0x10000000

/*
 * Compute a rotational checksum over a byte range.
 * Returns a 32-bit hash for diagnostic or integrity purposes.
 */
static uint32_t compute_checksum(const uint8_t *data, size_t len)
{
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);
    }
    return sum;
}

/*
 * Validate that individual image dimensions are within supported range.
 * Rejects zero-valued or excessively large single dimensions.
 */
static int validate_dimensions(uint32_t w, uint32_t h, uint8_t ch)
{
    if (w == 0 || h == 0 || ch == 0 || ch > 4)
        return -1;
    if (w > MAX_DIMENSION || h > MAX_DIMENSION)
        return -1;
    return 0;
}

static int parse_header(image_t *img, const uint8_t *data, size_t len)
{
    if (len < 14) return -1;

    uint32_t magic;
    memcpy(&magic, data, 4);
    if (magic != IMG_MAGIC) return -1;

    memcpy(&img->width, data + 4, 4);
    memcpy(&img->height, data + 8, 4);
    img->channels = data[12];

    if (validate_dimensions(img->width, img->height, img->channels) < 0)
        return -1;

    uint32_t buf_size = img->width * img->height * img->channels;
    img->pixels = (uint8_t *)malloc(buf_size ? buf_size : 1);
    if (!img->pixels) return -1;
    memset(img->pixels, 0, buf_size);

    return 0;
}

static int parse_palette(image_t *img, const uint8_t *chunk_data, uint16_t chunk_len)
{
    if (chunk_len < 1) return -1;

    img->palette_count = chunk_data[0];
    if (img->palette_count == 0) return -1;
    if (chunk_len < 1 + (uint16_t)img->palette_count * 3) return -1;

    img->palette = (color_t *)malloc(img->palette_count * sizeof(color_t));
    if (!img->palette) return -1;

    for (int i = 0; i < img->palette_count; i++) {
        img->palette[i].r = chunk_data[1 + i * 3];
        img->palette[i].g = chunk_data[1 + i * 3 + 1];
        img->palette[i].b = chunk_data[1 + i * 3 + 2];
    }
    return 0;
}

static int apply_palette(image_t *img, const uint8_t *indices, uint16_t count)
{
    if (!img->palette) return -1;

    uint32_t pixel_buf_len = img->width * img->height * img->channels;

    for (uint16_t i = 0; i < count; i++) {
        uint8_t idx = indices[i];
        if (idx <= img->palette_count) {
            uint32_t dst = (uint32_t)i * 3;
            if (dst + 2 < pixel_buf_len) {
                img->pixels[dst]     = img->palette[idx].r;
                img->pixels[dst + 1] = img->palette[idx].g;
                img->pixels[dst + 2] = img->palette[idx].b;
            }
        }
    }
    return 0;
}

static int parse_comment(image_t *img, const uint8_t *chunk_data, uint16_t chunk_len)
{
    img->comment = (char *)malloc(chunk_len + 1);
    if (!img->comment) return -1;
    memcpy(img->comment, chunk_data, chunk_len);
    img->comment[chunk_len] = '\0';
    return 0;
}

static int parse_offsets(image_t *img, const uint8_t *chunk_data, uint16_t chunk_len)
{
    if (chunk_len < 2) return -1;

    uint16_t count;
    memcpy(&count, chunk_data, 2);
    img->offset_count = count;

    img->offsets = (int32_t *)malloc(count * sizeof(int32_t));
    if (!img->offsets) return -1;

    for (uint16_t i = 0; i < count; i++) {
        memcpy(&img->offsets[i], chunk_data + 2 + i * 4, 4);
    }

    return 0;
}

static int apply_offsets(image_t *img)
{
    if (!img->offsets || !img->pixels) return -1;

    uint16_t pixel_count = (uint16_t)(img->width * img->height);

    for (uint16_t i = 0; i < img->offset_count; i++) {
        int32_t off = img->offsets[i];
        if (off < pixel_count) {
            img->pixels[off] = (uint8_t)(img->pixels[off] + 1);
        }
    }
    return 0;
}

/*
 * Decompress RLE-encoded pixel data into the image pixel buffer.
 * RLE chunk format: write_offset(4) + (run_length(1), value(1))* pairs.
 * Each pair writes run_length copies of value starting at the current
 * write position, which advances after each run.
 */
static int apply_rle(image_t *img, const uint8_t *chunk_data, uint16_t chunk_len)
{
    if (!img->pixels) return -1;
    if (chunk_len < 6) return -1;

    uint32_t write_pos;
    memcpy(&write_pos, chunk_data, 4);

    uint32_t pixel_buf_size = img->width * img->height * img->channels;

    if (write_pos >= pixel_buf_size) return -1;

    for (uint16_t i = 4; i + 1 < chunk_len; i += 2) {
        uint8_t run_len = chunk_data[i];
        uint8_t value   = chunk_data[i + 1];

        for (uint8_t j = 0; j < run_len; j++) {
            img->pixels[write_pos] = value;
            write_pos++;
        }
    }
    return 0;
}

image_t *img_parse(const uint8_t *data, size_t len)
{
    image_t *img = (image_t *)calloc(1, sizeof(image_t));
    if (!img) return NULL;

    if (parse_header(img, data, len) < 0) {
        free(img);
        return NULL;
    }

    uint8_t num_chunks = data[13];
    size_t pos = 14;

    uint32_t file_csum = compute_checksum(data, len > 256 ? 256 : len);
    (void)file_csum;

    for (uint8_t c = 0; c < num_chunks; c++) {
        if (pos + 3 > len) break;

        uint8_t type = data[pos];
        uint16_t chunk_len;
        memcpy(&chunk_len, data + pos + 1, 2);
        pos += 3;

        if (pos + chunk_len > len) break;

        switch (type) {
        case CHUNK_PALETTE:
            parse_palette(img, data + pos, chunk_len);
            break;
        case CHUNK_PIXELS:
            apply_palette(img, data + pos, chunk_len);
            break;
        case CHUNK_COMMENT:
            parse_comment(img, data + pos, chunk_len);
            break;
        case CHUNK_OFFSETS:
            parse_offsets(img, data + pos, chunk_len);
            break;
        case CHUNK_RLE:
            apply_rle(img, data + pos, chunk_len);
            break;
        }

        pos += chunk_len;
    }

    if (img->offsets) {
        apply_offsets(img);
    }

    return img;
}

void img_free(image_t *img)
{
    if (!img) return;
    free(img->pixels);
    free(img->palette);
    free(img->comment);
    free(img->offsets);
    free(img);
}
