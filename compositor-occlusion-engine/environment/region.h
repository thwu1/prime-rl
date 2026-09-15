#ifndef REGION_H
#define REGION_H

#define MAX_RECTS 16384

typedef struct {
    int x, y, w, h;
} Rect;

typedef struct {
    int id;
    int x, y, w, h;
    int z;
} WindowDef;

typedef struct {
    int owner;  /* window id, or -1 for background */
    int x, y, w, h;
} OwnedRect;

/*
 * Subtract occluder rectangle from base rectangle.
 *
 * Writes the non-overlapping remainder rectangles to out[].
 * Each output rectangle has positive area and lies entirely within base.
 * The total area of output rectangles equals base area minus the
 * intersection area of base and occluder.
 *
 * Returns the number of rectangles written (0 to 4).
 * Returns 0 when base is fully occluded.
 * Returns 1 with out[0]==base when there is no intersection.
 */
int rect_subtract(Rect base, Rect occluder, Rect *out, int max_out);

/*
 * Compute the visible region partition for a set of windows on a screen.
 *
 * Every pixel on the screen (screen_w x screen_h) is assigned to exactly
 * one owner: a window id, or -1 for background.  Higher z-values occlude
 * lower z-values.  All z-values in the input are unique.  Windows whose
 * geometry extends beyond screen boundaries are clipped.  Windows fully
 * outside the screen receive no output entries.
 *
 * The union of all output rectangles covers the full screen with no gaps
 * or overlaps, i.e. the total area equals screen_w * screen_h.
 *
 * Returns the number of OwnedRect entries written to out[].
 */
int compute_visible_regions(int screen_w, int screen_h,
                            WindowDef *windows, int nwindows,
                            OwnedRect *out, int max_out);

/*
 * Merge adjacent co-linear rectangles in-place.
 *
 * Two rectangles merge horizontally when they share the same y and h
 * and one's right edge equals the other's left edge.  They merge
 * vertically when they share the same x and w and one's bottom edge
 * equals the other's top edge.
 *
 * Iterates until no further merges are possible.
 * Returns the new count of rectangles after merging.
 */
int merge_regions(Rect *rects, int count);

#endif
