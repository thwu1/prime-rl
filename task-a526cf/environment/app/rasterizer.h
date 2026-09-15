#ifndef RASTERIZER_H
#define RASTERIZER_H


#include "compositor.h"
#include <stddef.h>

/* Growable byte buffer for rasterizer output */
typedef struct {
    char *buf;
    size_t len;
    size_t cap;
} raster_buf_t;

/* Initialize a raster buffer (allocates initial storage). */
void raster_init(raster_buf_t *rb);

/* Free all memory owned by a raster buffer. */
void raster_free(raster_buf_t *rb);

/**
 * rasterize_full — convert a composited cell grid to ANSI escape sequences.
 *
 * Produces a byte stream that, when written to a terminal, displays the
 * visual content of the cell grid.  See /app/docs/rasterizer_spec.md.
 *
 * @param cells   Composited cell array (rows * cols elements).
 * @param rows    Grid height.
 * @param cols    Grid width.
 * @param out     Pre-initialized raster buffer; output is appended.
 */
void rasterize_full(const composited_cell_t *cells, int rows, int cols,
                    raster_buf_t *out);

/**
 * rasterize_diff — emit only the changes between two frames.
 *
 * Produces a minimal byte stream that transforms a terminal showing
 * prev into one showing curr.  See /app/docs/rasterizer_spec.md.
 *
 * @param prev    Previous frame's composited cells.
 * @param curr    Current frame's composited cells.
 * @param rows    Grid height (must match for both frames).
 * @param cols    Grid width (must match for both frames).
 * @param out     Pre-initialized raster buffer; output is appended.
 */
void rasterize_diff(const composited_cell_t *prev,
                    const composited_cell_t *curr,
                    int rows, int cols,
                    raster_buf_t *out);

#endif /* RASTERIZER_H */
