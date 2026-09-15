/*
 * BSP operations implementation.
 * Provides partition-plane side testing, octant-based angle computation,
 * subsector lookup, and recursive front-to-back BSP traversal.
 */


#include <stdlib.h>
#include <string.h>
#include "bsp.h"
#include "tantoangle_lut.h"

static node_t       *g_nodes       = NULL;
static int            g_num_nodes   = 0;
static subsector_t   *g_subsectors  = NULL;
static int            g_num_ss      = 0;

void bsp_set_data(node_t *nodes, int num_nodes,
                  subsector_t *subsectors, int num_subsectors)
{
    g_nodes      = nodes;
    g_num_nodes  = num_nodes;
    g_subsectors = subsectors;
    g_num_ss     = num_subsectors;
}

/*
 * SlopeDiv: compute slope ratio for tantoangle table lookup.
 * Returns an index in [0, SLOPERANGE].
 */
int SlopeDiv(unsigned int num, unsigned int den)
{
    unsigned int ans;
    if (den < 256)
        return SLOPERANGE;
    ans = (num << 3) / (den >> 8);
    return (ans <= SLOPERANGE) ? (int)ans : SLOPERANGE;
}

/*
 * R_PointOnSide: determine which side of a BSP partition line
 * the point (x,y) falls on.  Returns 0 (front) or 1 (back).
 *
 * Handles axis-aligned partitions as special cases.
 * Uses a sign-bit fast path when sign bits alone determine the result,
 * otherwise falls back to a fixed-point cross-product comparison.
 */
int R_PointOnSide(fixed_t x, fixed_t y, node_t *node)
{
    fixed_t dx, dy, left, right;

    /* Vertical partition line (dx == 0) */
    if (!node->dx) {
        if (x <= node->x)
            return node->dy > 0;
        return node->dy < 0;
    }
    /* Horizontal partition line (dy == 0) */
    if (!node->dy) {
        if (y <= node->y)
            return node->dx < 0;
        return node->dx > 0;
    }

    dx = x - node->x;
    dy = y - node->y;

    /* Sign-bit fast path: if sign bits are mixed in a way
       that makes the cross-product sign unambiguous */
    if ((node->dy ^ node->dx ^ dx ^ dy) & 0x80000000) {
        if ((node->dx ^ dy) & 0x80000000)
            return 1;   /* left cross-product is negative */
        return 0;
    }

    /* General case: compare cross-product terms */
    left  = FixedMul(node->dy >> FRACBITS, dx);
    right = FixedMul(dy, node->dx >> FRACBITS);

    if (right < left)
        return 0;   /* front side */
    return 1;       /* back side */
}

/*
 * R_PointToAngle2: compute the BAM (Binary Angle Measurement)
 * angle from (x1,y1) to (x2,y2).
 *
 * Normalises into the first octant, computes a slope index
 * via SlopeDiv, looks up in the tantoangle table, then
 * transforms back to the correct octant.
 */
angle_t R_PointToAngle2(fixed_t x1, fixed_t y1,
                        fixed_t x2, fixed_t y2)
{
    fixed_t x = x2 - x1;
    fixed_t y = y2 - y1;

    if (!x && !y)
        return 0;

    if (x >= 0) {
        if (y >= 0) {
            if (x > y)
                return tantoangle[SlopeDiv(y, x)];                 /* octant 0 */
            else
                return ANG90 - 1 - tantoangle[SlopeDiv(x, y)];    /* octant 1 */
        } else {
            y = -y;
            if (x > y)
                return (angle_t)(-tantoangle[SlopeDiv(y, x)]);     /* octant 7 */
            else
                return ANG270 + tantoangle[SlopeDiv(x, y)];        /* octant 6 */
        }
    } else {
        x = -x;
        if (y >= 0) {
            if (x > y)
                return ANG180 - 1 - tantoangle[SlopeDiv(y, x)];   /* octant 3 */
            else
                return ANG90 + tantoangle[SlopeDiv(x, y)];         /* octant 2 */
        } else {
            y = -y;
            if (x > y)
                return ANG180 + tantoangle[SlopeDiv(y, x)];        /* octant 4 */
            else
                return ANG270 + 1 + tantoangle[SlopeDiv(x, y)];   /* octant 5 */
        }
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* BSP subsector lookup                                                */
/* ------------------------------------------------------------------ */

int bsp_locate(fixed_t x, fixed_t y)
{
    if (g_num_nodes == 0)
        return 0;

    int nodenum = g_num_nodes - 1;

    while (!(nodenum & NF_SUBSECTOR)) {
        node_t *nd = &g_nodes[nodenum];
        int side   = R_PointOnSide(x, y, nd);
        nodenum    = nd->children[side];
    }

    if (nodenum == -1)
        return 0;
    return nodenum & ~NF_SUBSECTOR;
}

/* ------------------------------------------------------------------ */
/* Recursive BSP traversal (front-to-back without bbox culling)        */
/* ------------------------------------------------------------------ */

static int *trav_buf;
static int  trav_cnt;
static int  trav_max;

static void traverse_node(int bspnum, fixed_t vx, fixed_t vy)
{
    if (trav_cnt >= trav_max)
        return;

    if (bspnum & NF_SUBSECTOR) {
        int ssnum = (bspnum == -1) ? 0 : (bspnum & ~NF_SUBSECTOR);
        trav_buf[trav_cnt++] = ssnum;
        return;
    }

    node_t *bsp = &g_nodes[bspnum];
    int side = R_PointOnSide(vx, vy, bsp);

    /* Visit subtrees: back side first, then front side */
    traverse_node(bsp->children[side ^ 1], vx, vy);
    traverse_node(bsp->children[side],     vx, vy);
}

int bsp_traverse(fixed_t x, fixed_t y, int *output, int max_output)
{
    trav_buf = output;
    trav_cnt = 0;
    trav_max = max_output;

    if (g_num_nodes == 0) {
        output[0] = 0;
        return 1;
    }

    traverse_node(g_num_nodes - 1, x, y);
    return trav_cnt;
}
