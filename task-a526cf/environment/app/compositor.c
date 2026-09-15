#include "compositor.h"
#include <string.h>
#include <math.h>


/* ── Channel helpers ────────────────────────────────────────────────── */

static uint32_t ch_bchannel(uint64_t channels) {
    return (uint32_t)(channels & 0xffffffffu) &
           (NC_BG_ALPHA_MASK | NC_BGDEFAULT_MASK | NC_BG_PALETTE | NC_BG_RGB_MASK);
}

static uint32_t ch_fchannel(uint64_t channels) {
    return ch_bchannel(channels >> 32u);
}

static uint32_t ch_alpha(uint32_t c) {
    return c & NC_BG_ALPHA_MASK;
}

static bool ch_default_p(uint32_t c) {
    return !(c & NC_BGDEFAULT_MASK);
}

static int ch_r(uint32_t c) { return (int)((c >> 16u) & 0xffu); }
static int ch_g(uint32_t c) { return (int)((c >>  8u) & 0xffu); }
static int ch_b(uint32_t c) { return (int)( c         & 0xffu); }

/* ── Compositing ────────────────────────────────────────────────────── */

void composite_scene(const scene_t *scene, composited_cell_t *output) {
    for (int gy = 0; gy < scene->grid_rows; gy++) {
        for (int gx = 0; gx < scene->grid_cols; gx++) {
            composited_cell_t *out = &output[gy * scene->grid_cols + gx];

            out->egc[0]    = '\0';
            out->fg_r      = out->fg_g = out->fg_b = -1;
            out->bg_r      = out->bg_g = out->bg_b = -1;
            out->fg_default = true;
            out->bg_default = true;
            out->style      = 0;

            bool egc_done       = false;
            bool fg_locked      = false;
            bool bg_locked      = false;
            bool fg_has_rgb     = false;
            bool bg_has_rgb     = false;
            bool fg_highcontrast = false;

            int fg_r = 0, fg_g = 0, fg_b = 0;
            int bg_r = 0, bg_g = 0, bg_b = 0;

            for (int p = 0; p < scene->n_planes; p++) {
                const plane_t *pl = &scene->planes[p];
                int ly = gy - pl->y;
                int lx = gx - pl->x;
                if (ly < 0 || ly >= pl->rows || lx < 0 || lx >= pl->cols)
                    continue;

                const cell_t *cell = &pl->cells[ly * pl->cols + lx];
                const cell_t *C = (cell->egc[0] == '\0') ? &pl->base : cell;

                /* ── EGC ─────────────────────────────────────────── */
                if (!egc_done && C->egc[0] != '\0') {
                    strncpy(out->egc, C->egc, sizeof(out->egc) - 1);
                    out->egc[sizeof(out->egc) - 1] = '\0';
                    out->style = C->stylemask;
                    egc_done = true;
                }

                /* ── Foreground ───────────────────────────────────── */
                if (!fg_locked) {
                    uint32_t fc = ch_fchannel(C->channels);
                    uint32_t fa = ch_alpha(fc);

                    if (fa == NCALPHA_TRANSPARENT) {
                        /* skip fg only — fall through to bg */
                    } else if (fa == NCALPHA_HIGHCONTRAST) {
                        fg_highcontrast = true;
                        fg_locked = true;
                    } else { /* BLEND or OPAQUE */
                        if (!ch_default_p(fc)) {
                            int r = ch_r(fc), g = ch_g(fc), b = ch_b(fc);
                            if (fg_has_rgb) {
                                fg_r = (fg_r + r) / 2;
                                fg_g = (fg_g + g) / 2;
                                fg_b = (fg_b + b) / 2;
                            } else {
                                fg_r = r; fg_g = g; fg_b = b;
                                fg_has_rgb = true;
                            }
                        }
                        if (fa == NCALPHA_OPAQUE)
                            fg_locked = true;
                    }
                }

                /* ── Background ───────────────────────────────────── */
                if (!bg_locked) {
                    uint32_t bc = ch_bchannel(C->channels);
                    uint32_t ba = ch_alpha(bc);

                    if (ba == NCALPHA_TRANSPARENT) {
                        /* skip */
                    } else { /* BLEND or OPAQUE */
                        if (!ch_default_p(bc)) {
                            int r = ch_r(bc), g = ch_g(bc), b = ch_b(bc);
                            if (bg_has_rgb) {
                                bg_r = (bg_r + r) / 2;
                                bg_g = (bg_g + g) / 2;
                                bg_b = (bg_b + b) / 2;
                            } else {
                                bg_r = r; bg_g = g; bg_b = b;
                                bg_has_rgb = true;
                            }
                        }
                        if (ba == NCALPHA_OPAQUE)
                            bg_locked = true;
                    }
                }

                if (egc_done && fg_locked && bg_locked)
                    break;
            }

            /* ── Deferred HIGHCONTRAST ──────────────────────────── */
            if (fg_highcontrast) {
                if (bg_has_rgb) {
                    double luma = (0.2126 * bg_r + 0.7152 * bg_g +
                                   0.0722 * bg_b) / 255.0;
                    if (luma > 0.5) {
                        fg_r = fg_g = fg_b = 0;
                    } else {
                        fg_r = fg_g = fg_b = 255;
                    }
                } else {
                    fg_r = fg_g = fg_b = 255;
                }
                fg_has_rgb = true;
            }

            if (fg_has_rgb) {
                out->fg_r = fg_r; out->fg_g = fg_g; out->fg_b = fg_b;
                out->fg_default = false;
            }
            if (bg_has_rgb) {
                out->bg_r = bg_r; out->bg_g = bg_g; out->bg_b = bg_b;
                out->bg_default = false;
            }

            if (out->egc[0] == '\0') {
                out->egc[0] = ' ';
                out->egc[1] = '\0';
            }
        }
    }
}
