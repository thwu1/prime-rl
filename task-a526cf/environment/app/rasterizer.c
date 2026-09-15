#include "rasterizer.h"
#include <stdlib.h>
#include <string.h>


void raster_init(raster_buf_t *rb) {
    rb->cap = 1024;
    rb->buf = malloc(rb->cap);
    rb->len = 0;
}

void raster_free(raster_buf_t *rb) {
    free(rb->buf);
    rb->buf = NULL;
    rb->len = rb->cap = 0;
}

/* TODO: Implement full-frame rasterization.
 * See /app/docs/rasterizer_spec.md for the specification.
 * See /app/rasterizer.h for the API contract.
 */
void rasterize_full(const composited_cell_t *cells, int rows, int cols,
                    raster_buf_t *out) {
    (void)cells; (void)rows; (void)cols; (void)out;
}

/* TODO: Implement differential rasterization.
 * See /app/docs/rasterizer_spec.md for the specification.
 * See /app/rasterizer.h for the API contract.
 */
void rasterize_diff(const composited_cell_t *prev,
                    const composited_cell_t *curr,
                    int rows, int cols,
                    raster_buf_t *out) {
    (void)prev; (void)curr; (void)rows; (void)cols; (void)out;
}
