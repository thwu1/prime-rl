/*
 * undead_rules.c — Reference implementation of the Undead puzzle rules.
 *
 * An Undead puzzle is played on an N*N grid. Some cells contain
 * diagonal mirrors ('/' or '\'); the remaining cells must each be
 * filled with exactly one monster: Vampire ('V'), Ghost ('G'), or
 * Zombie ('Z').
 *
 * Numeric clues along each edge of the grid indicate the number of
 * monsters visible along a sight line entering from that position.
 *
 * This file implements the sight-line tracing algorithm and
 * documents the solution verification criteria.
 */


#include <stdio.h>

#define MAX_DIM 16

/* -----------------------------------------------------------
 * Monster visibility model
 *
 * A sight line enters the grid from an edge, perpendicular to
 * that edge, and advances cell by cell. It begins in DIRECT mode.
 *
 * When the line hits a mirror:
 *   '/'  : direction (dr,dc) becomes (-dc, -dr)
 *   '\\' : direction (dr,dc) becomes ( dc,  dr)
 * After any mirror interaction, the line is in REFLECTED mode
 * for all subsequent cells (mirrors do not toggle it back).
 *
 * Monster visibility depends on the current mode:
 *   Vampire ('V') : counted only while DIRECT  (not yet reflected)
 *   Ghost   ('G') : counted only while REFLECTED
 *   Zombie  ('Z') : counted regardless of mode
 * ----------------------------------------------------------- */

int count_visible(char grid[][MAX_DIM], int n,
                  int start_row, int start_col,
                  int dr, int dc)
{
    int visible = 0;
    int is_reflected = 0;
    int r = start_row, c = start_col;

    while (r >= 0 && r < n && c >= 0 && c < n) {
        char cell = grid[r][c];

        switch (cell) {
        case '/': {
            int nr = -dc, nc = -dr;
            dr = nr; dc = nc;
            is_reflected = 1;
            break;
        }
        case '\\': {
            int nr = dc, nc = dr;
            dr = nr; dc = nc;
            is_reflected = 1;
            break;
        }
        case 'V':
            if (!is_reflected) visible++;
            break;
        case 'G':
            if (is_reflected) visible++;
            break;
        case 'Z':
            visible++;
            break;
        }

        r += dr;
        c += dc;
    }

    return visible;
}

/* -----------------------------------------------------------
 * Clue directions
 *
 * Top    edge, column c : enters at (0,   c),   direction (+1,  0)
 * Bottom edge, column c : enters at (n-1, c),   direction (-1,  0)
 * Left   edge, row r    : enters at (r,   0),   direction ( 0, +1)
 * Right  edge, row r    : enters at (r,   n-1), direction ( 0, -1)
 *
 * A valid solution satisfies all of:
 *   1. Every non-mirror cell contains exactly one of V, G, Z.
 *   2. The total count of each monster type matches the puzzle spec.
 *   3. Every edge clue equals count_visible() for that sight line.
 * ----------------------------------------------------------- */
