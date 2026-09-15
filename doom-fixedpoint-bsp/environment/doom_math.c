/*
 * Doom engine arithmetic primitives implementation.
 * Processes commands from input file, writes results to output file.
 *
 * Commands: MUL, DIV, HASH, SIDE, ANGLE
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <ctype.h>
#include <limits.h>

#include "doom_math.h"
#include "tantoangle_lut.h"

/*
 * FixedMul: 16.16 fixed-point multiplication.
 * Uses 64-bit intermediate to avoid overflow in the product.
 */
fixed_t FixedMul(fixed_t a, fixed_t b)
{
    return ((int64_t)a * (int64_t)b) >> FRACBITS;
}

/*
 * FixedDiv: 16.16 fixed-point division.
 * Detects potential overflow and returns saturated values.
 */
fixed_t FixedDiv(fixed_t a, fixed_t b)
{
    if ((abs(a) >> 15) >= abs(b))
    {
        return (a ^ b) < 0 ? INT_MAX : INT_MIN;
    }
    else
    {
        int64_t result;
        result = ((int64_t)a << FRACBITS) / b;
        return (fixed_t)result;
    }
}

/*
 * W_LumpNameHash: hash function for WAD lump name lookup.
 * Processes up to 8 characters, case-insensitive.
 */
unsigned int W_LumpNameHash(const char *s)
{
    unsigned int result = 5381;
    unsigned int i;

    for (i = 0; i < 8 && s[i] != '\0'; ++i)
    {
        result = ((result << 4) ^ result) ^ toupper((unsigned char)s[i]);
    }

    return result;
}

/*
 * SlopeDiv: compute slope ratio for angle table lookup.
 * Guards against small denominators that would cause huge results.
 */
int SlopeDiv(unsigned int num, unsigned int den)
{
    unsigned ans;

    if (den < 256)
    {
        return SLOPERANGE;
    }
    else
    {
        ans = (num << 3) / (den >> 8);

        if (ans <= SLOPERANGE)
        {
            return ans;
        }
        else
        {
            return SLOPERANGE;
        }
    }
}

/*
 * R_PointOnSide: determine which side of a BSP partition line
 * a point falls on. Returns 0 for front, 1 for back.
 *
 * Handles axis-aligned partitions as special cases.
 * Uses sign-bit optimization for quick determination when possible,
 * falls back to cross-product computation.
 */
int R_PointOnSide(fixed_t x, fixed_t y,
                  fixed_t node_x, fixed_t node_y,
                  fixed_t node_dx, fixed_t node_dy)
{
    fixed_t dx;
    fixed_t dy;
    fixed_t left;
    fixed_t right;

    if (!node_dx)
    {
        if (x <= node_x)
            return node_dy > 0;

        return node_dy < 0;
    }
    if (!node_dy)
    {
        if (y <= node_y)
            return node_dx < 0;

        return node_dx > 0;
    }

    dx = (x - node_x);
    dy = (y - node_y);

    /* Try to quickly decide by looking at sign bits. */
    if ((node_dy ^ node_dx ^ dx ^ dy) & 0x80000000)
    {
        if ((node_dx ^ dy) & 0x80000000)
        {
            /* left is negative */
            return 1;
        }
        return 0;
    }

    left = FixedMul(node_dy >> FRACBITS, dx);
    right = FixedMul(dy, node_dx >> FRACBITS);

    if (right < left)
    {
        /* front side */
        return 0;
    }
    /* back side */
    return 1;
}

/*
 * R_PointToAngle2: compute the BAM (Binary Angle Measurement)
 * angle from point (x1,y1) to point (x2,y2).
 *
 * Flips coordinates into the first octant, computes a slope
 * ratio via SlopeDiv, looks up in tantoangle table, then
 * adjusts back to the correct octant.
 */
angle_t R_PointToAngle2(fixed_t x1, fixed_t y1,
                        fixed_t x2, fixed_t y2)
{
    fixed_t x = x2 - x1;
    fixed_t y = y2 - y1;

    if ((!x) && (!y))
        return 0;

    if (x >= 0)
    {
        if (y >= 0)
        {
            if (x > y)
            {
                /* octant 0 */
                return tantoangle[SlopeDiv(y, x)];
            }
            else
            {
                /* octant 1 */
                return ANG90 - 1 - tantoangle[SlopeDiv(x, y)];
            }
        }
        else
        {
            y = -y;

            if (x > y)
            {
                /* octant 7 */
                return -tantoangle[SlopeDiv(y, x)];
            }
            else
            {
                /* octant 6 */
                return ANG270 + tantoangle[SlopeDiv(x, y)];
            }
        }
    }
    else
    {
        x = -x;

        if (y >= 0)
        {
            if (x > y)
            {
                /* octant 3 */
                return ANG180 - 1 - tantoangle[SlopeDiv(y, x)];
            }
            else
            {
                /* octant 2 */
                return ANG90 + tantoangle[SlopeDiv(x, y)];
            }
        }
        else
        {
            y = -y;

            if (x > y)
            {
                /* octant 4 */
                return ANG180 + tantoangle[SlopeDiv(y, x)];
            }
            else
            {
                /* octant 5 */
                return ANG270 + 1 + tantoangle[SlopeDiv(x, y)];
            }
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 3)
    {
        fprintf(stderr, "Usage: %s <input_file> <output_file>\n", argv[0]);
        return 1;
    }

    FILE *fin = fopen(argv[1], "r");
    FILE *fout = fopen(argv[2], "w");
    if (!fin || !fout)
    {
        fprintf(stderr, "Error opening files\n");
        return 1;
    }

    char line[256];
    while (fgets(line, sizeof(line), fin))
    {
        char cmd[16];
        if (sscanf(line, "%15s", cmd) != 1)
            continue;

        if (strcmp(cmd, "MUL") == 0)
        {
            int a, b;
            sscanf(line, "%*s %d %d", &a, &b);
            fprintf(fout, "%d\n", FixedMul(a, b));
        }
        else if (strcmp(cmd, "DIV") == 0)
        {
            int a, b;
            sscanf(line, "%*s %d %d", &a, &b);
            fprintf(fout, "%d\n", FixedDiv(a, b));
        }
        else if (strcmp(cmd, "HASH") == 0)
        {
            char name[16];
            sscanf(line, "%*s %15s", name);
            fprintf(fout, "%u\n", W_LumpNameHash(name));
        }
        else if (strcmp(cmd, "SIDE") == 0)
        {
            int px, py, nx, ny, ndx, ndy;
            sscanf(line, "%*s %d %d %d %d %d %d",
                   &px, &py, &nx, &ny, &ndx, &ndy);
            fprintf(fout, "%d\n", R_PointOnSide(px, py, nx, ny, ndx, ndy));
        }
        else if (strcmp(cmd, "ANGLE") == 0)
        {
            int x1, y1, x2, y2;
            sscanf(line, "%*s %d %d %d %d", &x1, &y1, &x2, &y2);
            fprintf(fout, "%u\n", R_PointToAngle2(x1, y1, x2, y2));
        }
    }

    fclose(fin);
    fclose(fout);
    return 0;
}
