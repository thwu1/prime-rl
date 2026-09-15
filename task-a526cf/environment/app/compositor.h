#ifndef COMPOSITOR_H
#define COMPOSITOR_H


#include <stdint.h>
#include <stdbool.h>

/* ===================================================================
 * Notcurses-compatible constants for 32-bit channel encoding.
 *
 * A single 32-bit channel encodes:
 *   bits 31-30 : 2-bit alpha (NCALPHA_*)
 *   bit  30    : (part of alpha)
 *   bit  29    : (part of alpha)
 *   bit  28    : NC_BGDEFAULT_MASK — set means NOT using default color
 *   bit  27    : NC_BG_PALETTE — set means palette-indexed color
 *   bits 23-16 : red component
 *   bits 15-8  : green component
 *   bits  7-0  : blue component
 *
 * A 64-bit channel PAIR packs the foreground channel in the upper 32
 * bits and the background channel in the lower 32 bits.
 * =================================================================== */

#define NCALPHA_OPAQUE        0x00000000u
#define NCALPHA_BLEND         0x10000000u
#define NCALPHA_TRANSPARENT   0x20000000u
#define NCALPHA_HIGHCONTRAST  0x30000000u

#define NC_BGDEFAULT_MASK     0x40000000u   /* set = NOT using default   */
#define NC_BG_RGB_MASK        0x00ffffffu   /* 24-bit RGB                */
#define NC_BG_PALETTE         0x08000000u   /* palette-indexed           */
#define NC_BG_ALPHA_MASK      0x30000000u   /* 2-bit alpha               */

/* Convenience: all meaningful bits in a single channel */
#define NC_CHANNEL_MASK \
    (NC_BG_ALPHA_MASK | NC_BGDEFAULT_MASK | NC_BG_PALETTE | NC_BG_RGB_MASK)

/* Style flags (subset — only those used in tests) */
#define NCSTYLE_STRUCK    0x0001u
#define NCSTYLE_BOLD      0x0002u
#define NCSTYLE_UNDERCURL 0x0004u
#define NCSTYLE_UNDERLINE 0x0008u
#define NCSTYLE_ITALIC    0x0010u

/* ===================================================================
 * Data structures
 * =================================================================== */

/* A cell within an ncplane */
typedef struct {
    char egc[8];          /* UTF-8 extended grapheme cluster ('\0' = empty) */
    uint16_t stylemask;
    uint64_t channels;    /* 64-bit channel pair: fg upper-32, bg lower-32 */
} cell_t;

/* An ncplane in the scene */
typedef struct {
    int y, x;             /* offset relative to grid origin */
    int rows, cols;       /* dimensions */
    cell_t base;          /* base cell (used when actual cell has no EGC)  */
    cell_t *cells;        /* row-major array [rows * cols] */
} plane_t;

/* A complete scene (ordered stack of planes) */
typedef struct {
    int grid_rows, grid_cols;
    int n_planes;         /* planes[0] is the topmost plane */
    plane_t *planes;
} scene_t;

/* Result of compositing a single cell */
typedef struct {
    char egc[8];
    int fg_r, fg_g, fg_b; /* -1 when fg is the default color */
    int bg_r, bg_g, bg_b; /* -1 when bg is the default color */
    bool fg_default;
    bool bg_default;
    uint16_t style;
} composited_cell_t;

/* ===================================================================
 * The function you must implement (see compositor.c)
 * =================================================================== */

/**
 * composite_scene — render a stack of planes to a flat grid.
 *
 * @param scene   Scene description (planes ordered top-to-bottom).
 * @param output  Pre-allocated array of grid_rows * grid_cols elements.
 *
 * Must implement the full notcurses z-axis compositing algorithm as
 * documented in /app/docs/rendering.md and /app/docs/channels.md.
 */
void composite_scene(const scene_t *scene, composited_cell_t *output);

#endif /* COMPOSITOR_H */
