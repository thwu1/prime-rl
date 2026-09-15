
#include "region.h"
#include <stdlib.h>
#include <string.h>

static inline int imax(int a, int b) { return a > b ? a : b; }
static inline int imin(int a, int b) { return a < b ? a : b; }

int rect_subtract(Rect base, Rect occluder, Rect *out, int max_out) {
    if (base.w <= 0 || base.h <= 0) return 0;
    if (occluder.w <= 0 || occluder.h <= 0) {
        if (max_out > 0) { out[0] = base; return 1; }
        return 0;
    }

    int bx2 = base.x + base.w, by2 = base.y + base.h;
    int ox2 = occluder.x + occluder.w, oy2 = occluder.y + occluder.h;

    int ix1 = imax(base.x, occluder.x);
    int iy1 = imax(base.y, occluder.y);
    int ix2 = imin(bx2, ox2);
    int iy2 = imin(by2, oy2);

    if (ix1 >= ix2 || iy1 >= iy2) {
        if (max_out > 0) { out[0] = base; return 1; }
        return 0;
    }

    int n = 0;
    /* Top strip (full width of base) */
    if (base.y < iy1 && n < max_out)
        out[n++] = (Rect){base.x, base.y, base.w, iy1 - base.y};
    /* Bottom strip (full width of base) */
    if (iy2 < by2 && n < max_out)
        out[n++] = (Rect){base.x, iy2, base.w, by2 - iy2};
    /* Left strip (between top/bottom) */
    if (base.x < ix1 && n < max_out)
        out[n++] = (Rect){base.x, iy1, ix1 - base.x, iy2 - iy1};
    /* Right strip (between top/bottom) */
    if (ix2 < bx2 && n < max_out)
        out[n++] = (Rect){ix2, iy1, bx2 - ix2, iy2 - iy1};

    return n;
}

static int cmp_z_desc(const void *a, const void *b) {
    return ((const WindowDef *)b)->z - ((const WindowDef *)a)->z;
}

int compute_visible_regions(int screen_w, int screen_h,
                            WindowDef *windows, int nwindows,
                            OwnedRect *out, int max_out) {
    if (max_out <= 0) return 0;

    /* Sort windows by z descending (topmost first) */
    WindowDef *sorted = (WindowDef *)malloc((nwindows > 0 ? nwindows : 1) * sizeof(WindowDef));
    if (nwindows > 0) {
        memcpy(sorted, windows, nwindows * sizeof(WindowDef));
        qsort(sorted, nwindows, sizeof(WindowDef), cmp_z_desc);
    }

    int out_count = 0;
    int nocc = 0, occ_cap = 64;
    Rect *occupied = (Rect *)malloc(occ_cap * sizeof(Rect));

    for (int w = 0; w < nwindows; w++) {
        WindowDef *win = &sorted[w];

        /* Clip to screen */
        int cx1 = imax(0, win->x);
        int cy1 = imax(0, win->y);
        int cx2 = imin(screen_w, win->x + win->w);
        int cy2 = imin(screen_h, win->y + win->h);

        if (cx1 >= cx2 || cy1 >= cy2) continue;

        Rect clipped = {cx1, cy1, cx2 - cx1, cy2 - cy1};

        /* Subtract all occupied regions from this window's clipped rect */
        int vis_cap = MAX_RECTS;
        Rect *visible = (Rect *)malloc(vis_cap * sizeof(Rect));
        int nvis = 1;
        visible[0] = clipped;

        for (int o = 0; o < nocc; o++) {
            Rect *next = (Rect *)malloc(vis_cap * sizeof(Rect));
            int nnext = 0;
            for (int v = 0; v < nvis; v++) {
                Rect sub[4];
                int ns = rect_subtract(visible[v], occupied[o], sub, 4);
                for (int s = 0; s < ns && nnext < vis_cap; s++)
                    next[nnext++] = sub[s];
            }
            free(visible);
            visible = next;
            nvis = nnext;
        }

        /* Add visible rects to output */
        for (int v = 0; v < nvis && out_count < max_out; v++) {
            out[out_count++] = (OwnedRect){
                win->id, visible[v].x, visible[v].y,
                visible[v].w, visible[v].h
            };
        }

        /* Track this window's clipped rect as occupied */
        if (nocc >= occ_cap) {
            occ_cap *= 2;
            occupied = (Rect *)realloc(occupied, occ_cap * sizeof(Rect));
        }
        occupied[nocc++] = clipped;

        free(visible);
    }

    /* Background: full screen minus all window clipped rects */
    int bg_cap = MAX_RECTS;
    Rect *bg = (Rect *)malloc(bg_cap * sizeof(Rect));
    int nbg = 1;
    bg[0] = (Rect){0, 0, screen_w, screen_h};

    for (int w = 0; w < nwindows; w++) {
        int cx1 = imax(0, windows[w].x);
        int cy1 = imax(0, windows[w].y);
        int cx2 = imin(screen_w, windows[w].x + windows[w].w);
        int cy2 = imin(screen_h, windows[w].y + windows[w].h);

        if (cx1 >= cx2 || cy1 >= cy2) continue;

        Rect occ = {cx1, cy1, cx2 - cx1, cy2 - cy1};
        Rect *next_bg = (Rect *)malloc(bg_cap * sizeof(Rect));
        int next_nbg = 0;
        for (int b = 0; b < nbg; b++) {
            Rect sub[4];
            int ns = rect_subtract(bg[b], occ, sub, 4);
            for (int s = 0; s < ns && next_nbg < bg_cap; s++)
                next_bg[next_nbg++] = sub[s];
        }
        free(bg);
        bg = next_bg;
        nbg = next_nbg;
    }

    for (int b = 0; b < nbg && out_count < max_out; b++) {
        out[out_count++] = (OwnedRect){
            -1, bg[b].x, bg[b].y, bg[b].w, bg[b].h
        };
    }

    free(bg);
    free(occupied);
    free(sorted);

    return out_count;
}

int merge_regions(Rect *rects, int count) {
    if (count <= 0) return 0;

    int changed = 1;
    while (changed) {
        changed = 0;
        for (int i = 0; i < count; i++) {
            for (int j = i + 1; j < count; j++) {
                int merged = 0;

                /* Horizontal merge: same y, same h, abutting x */
                if (rects[i].y == rects[j].y && rects[i].h == rects[j].h) {
                    if (rects[i].x + rects[i].w == rects[j].x) {
                        rects[i].w += rects[j].w;
                        merged = 1;
                    } else if (rects[j].x + rects[j].w == rects[i].x) {
                        rects[i].x = rects[j].x;
                        rects[i].w += rects[j].w;
                        merged = 1;
                    }
                }

                /* Vertical merge: same x, same w, abutting y */
                if (!merged && rects[i].x == rects[j].x && rects[i].w == rects[j].w) {
                    if (rects[i].y + rects[i].h == rects[j].y) {
                        rects[i].h += rects[j].h;
                        merged = 1;
                    } else if (rects[j].y + rects[j].h == rects[i].y) {
                        rects[i].y = rects[j].y;
                        rects[i].h += rects[j].h;
                        merged = 1;
                    }
                }

                if (merged) {
                    /* Remove element j by shifting */
                    for (int k = j; k < count - 1; k++)
                        rects[k] = rects[k + 1];
                    count--;
                    changed = 1;
                    j--;
                }
            }
        }
    }
    return count;
}
