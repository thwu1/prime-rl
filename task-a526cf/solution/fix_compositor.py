#!/usr/bin/env python3
"""Fix the five bugs in compositor.c and write the bug report."""

import os

# The corrected compositor.c with all five bugs fixed.
COMPOSITOR_C = r'''#include "compositor.h"
#include <string.h>
#include <math.h>


/* Ported from the notcurses rendering pipeline.
 * Reference: /app/docs/channels.md, /app/docs/rendering.md
 */

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

                /* ── EGC and style ──────────────────────────────── */
                if (!egc_done && C->egc[0] != '\0') {
                    strncpy(out->egc, C->egc, sizeof(out->egc) - 1);
                    out->egc[sizeof(out->egc) - 1] = '\0';
                    out->style = C->stylemask;  /* FIX 1: was cell->stylemask */
                    egc_done = true;
                }

                /* ── Foreground channel ──────────────────────────── */
                if (!fg_locked) {
                    uint32_t fc = ch_fchannel(C->channels);
                    uint32_t fa = ch_alpha(fc);

                    if (fa == NCALPHA_TRANSPARENT) {
                        /* FIX 2: removed 'continue' — only skip fg,
                           let bg processing below proceed normally */
                    } else if (fa == NCALPHA_HIGHCONTRAST) {
                        /* FIX 3: defer — just record the flag */
                        fg_highcontrast = true;
                        fg_locked = true;
                    } else {
                        /* BLEND or OPAQUE */
                        if (!ch_default_p(fc)) {
                            int r = ch_r(fc), g = ch_g(fc), b = ch_b(fc);
                            if (fg_has_rgb) {  /* FIX 4: was (fg_has_rgb && fa == NCALPHA_BLEND) */
                                fg_r = (fg_r + r) / 2;  /* FIX 5: was (fg_r + r + 1) / 2 */
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

                /* ── Background channel ──────────────────────────── */
                if (!bg_locked) {
                    uint32_t bc = ch_bchannel(C->channels);
                    uint32_t ba = ch_alpha(bc);

                    if (ba == NCALPHA_TRANSPARENT) {
                        /* skip */
                    } else {
                        /* BLEND or OPAQUE (HIGHCONTRAST forbidden for bg) */
                        if (!ch_default_p(bc)) {
                            int r = ch_r(bc), g = ch_g(bc), b = ch_b(bc);
                            if (bg_has_rgb) {  /* FIX 4 (bg path) */
                                bg_r = (bg_r + r) / 2;  /* FIX 5 (bg path) */
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

            /* ── Deferred HIGHCONTRAST resolution (FIX 3) ───────── */
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
                    fg_r = fg_g = fg_b = 255;  /* default bg assumed dark */
                }
                fg_has_rgb = true;
            }

            /* write resolved colors to output */
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
'''

BUGFIX_REPORT = '''# Compositor Bug Report

## Bug 1: Style attribution from wrong cell

**Root cause**: In the EGC resolution block, the style is taken from
`cell->stylemask` (the raw plane cell) instead of `C->stylemask` (the
effective cell). When a cell has an empty EGC and the base cell provides
the glyph, the style should come from the base cell (C), not the empty cell.

**Affected behavior**: Any scene where a plane's actual cell is empty and the
base cell has a non-zero style mask. The output style incorrectly reflects the
empty cell's style instead of the base cell's style.

**Fix**: Changed `out->style = cell->stylemask` to `out->style = C->stylemask`.

**Verification**: Created a scene with base cell style=ITALIC (0x0010) and
empty cell style=BOLD (0x0002). Verified the output uses 0x0010.

---

## Bug 2: Transparent foreground skips background processing

**Root cause**: When the foreground channel alpha is TRANSPARENT, the code uses
`continue` to skip to the next plane. This skips not just the foreground
processing but also the background processing for the same plane.

**Affected behavior**: A plane with transparent fg but opaque bg has its bg
color ignored. The bg falls through to deeper planes instead of being locked.

**Fix**: Removed the `continue` statement. The TRANSPARENT case now simply
falls through (does nothing for fg), allowing bg processing to proceed normally.

**Verification**: Created a two-plane scene where P0 has fg=TRANSPARENT,
bg=OPAQUE(100,100,100) and P1 has bg=OPAQUE(50,50,50). Verified bg comes
from P0 (100,100,100), not P1.

---

## Bug 3: HIGHCONTRAST resolved eagerly instead of deferred

**Root cause**: The HIGHCONTRAST case computes luminance immediately using the
foreground channel's own RGB values (which are typically zeros in HIGHCONTRAST
mode). The specification requires deferring resolution until the background
color is fully resolved, then computing BT.709 luminance of the background.

**Affected behavior**: HIGHCONTRAST always produces white fg (since fg RGB is
usually 0,0,0 -> luma=0 -> white), regardless of the actual background color.
Light backgrounds should produce black fg.

**Fix**: Replaced the eager resolution with `fg_highcontrast = true;
fg_locked = true;`. Added deferred resolution block after the main loop that
computes BT.709 luminance of the resolved bg color.

**Verification**: Tested with bg=(200,200,200) which has luma 0.784 > 0.5.
Correct output: black fg. Also tested with transparent bg resolving to a
deeper plane's bright color.

---

## Bug 4: OPAQUE after BLEND replaces instead of averaging

**Root cause**: The blend condition checks `fg_has_rgb && fa == NCALPHA_BLEND`,
but per the specification, when an OPAQUE channel is reached after prior BLEND
accumulation, it must also average (blend one final time) before locking. The
condition should be just `fg_has_rgb`.

**Affected behavior**: Any BLEND-then-OPAQUE sequence. The OPAQUE color
replaces the accumulated blend instead of averaging with it, producing
incorrect results.

**Fix**: Changed `if (fg_has_rgb && fa == NCALPHA_BLEND)` to `if (fg_has_rgb)`
in both fg and bg paths.

**Verification**: BLEND(200,100,0) + OPAQUE(0,100,200) should yield (100,100,100).
Without fix: (0,100,200). With fix: (100,100,100).

---

## Bug 5: Blend uses ceiling division instead of truncating

**Root cause**: The blend arithmetic uses `(a + b + 1) / 2` (rounding up) instead
of `(a + b) / 2` (truncating integer division). The specification explicitly
states "integer division, truncating".

**Affected behavior**: Off-by-one errors when blending values whose sum is odd.
For example, (255+0)/2 should be 127 but was computed as 128.

**Fix**: Removed the `+ 1` from all six blend expressions (fg R/G/B and bg R/G/B).

**Verification**: BLEND(255,0,0) + BLEND(0,0,255) should yield fg=(127,0,127).
Without fix: (128,0,128). With fix: (127,0,127).
'''

with open('/app/compositor.c', 'w') as f:
    f.write(COMPOSITOR_C)

with open('/app/BUGFIX_REPORT.md', 'w') as f:
    f.write(BUGFIX_REPORT)

print("Fixed compositor.c and wrote BUGFIX_REPORT.md")
