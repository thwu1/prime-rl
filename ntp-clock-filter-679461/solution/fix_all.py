#!/usr/bin/env python3
"""
Fix all bugs in the NTP pipeline and rewrite ntp_select.c with
correct intersection, cluster, and combine implementations.

"""

import os
import sys

def read_file(path):
    if not os.path.isfile(path):
        print(f"ERROR: {path} not found", file=sys.stderr)
        print(f"Contents of /app/: {os.listdir('/app/')}", file=sys.stderr)
        sys.exit(1)
    with open(path, 'r') as f:
        return f.read()

def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)

def safe_replace(code, old, new, description):
    if old not in code:
        print(f"WARNING: {description} - pattern not found, may already be fixed",
              file=sys.stderr)
        return code
    return code.replace(old, new)

# ================================================================
# Fix 1: ntp_pipeline.c - offset formula
# ================================================================
path = '/app/ntp_pipeline.c'
code = read_file(path)

code = safe_replace(code,
    'ntp_diff(t4, t3)',
    'ntp_diff(t3, t4)',
    'Fix 1: offset formula in ntp_pipeline.c')

write_file(path, code)
print("Fixed ntp_pipeline.c: offset formula", file=sys.stderr)

# ================================================================
# Fix 2-4: ntp_filter.c - three bugs
# ================================================================
path = '/app/ntp_filter.c'
code = read_file(path)

# Fix 2: Shift register direction (forward -> backward)
code = safe_replace(code,
    '    for (i = 1; i < NSTAGE; i++) {\n        p->f[i] = p->f[i - 1];',
    '    for (i = NSTAGE - 1; i >= 1; i--) {\n        p->f[i] = p->f[i - 1];',
    'Fix 2: shift register direction')

# Fix 3: XOR -> power-of-2
code = safe_replace(code,
    'p->disp += sorted[i].disp / (2 ^ (i + 1));',
    'p->disp += sorted[i].disp / (double)(1 << (i + 1));',
    'Fix 3: XOR to power-of-2')

# Fix 4: Jitter - add sqrt, fix divisor
code = safe_replace(code,
    '        p->jitter = p->jitter / (n + 1);',
    '        p->jitter = sqrt(p->jitter / n);',
    'Fix 4: jitter sqrt and divisor')

write_file(path, code)
print("Fixed ntp_filter.c: shift register, XOR, jitter", file=sys.stderr)

# ================================================================
# Fix 5-8: Rewrite ntp_select.c with correct implementations
# ================================================================
correct_select = r'''/*
 * ntp_select.c - RFC 5905 peer selection pipeline (corrected)
 *
 * Implements root distance, fitness check, intersection algorithm,
 * cluster algorithm, and weighted combine.
 *
 */

#include "ntp_select.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

/* ------------------------------------------------------------------ */
/*  root_dist  -  root synchronization distance (RFC 5905 A.5.5.2)    */
/* ------------------------------------------------------------------ */
double
root_dist(peer_t *p, double current_time)
{
    return fmax(MINDISP, p->rootdelay + p->delay) / 2.0
         + p->rootdisp
         + p->disp
         + PHI * (current_time - p->t)
         + p->jitter;
}

/* ------------------------------------------------------------------ */
/*  peer_fit  -  is this peer acceptable for synchronization?          */
/* ------------------------------------------------------------------ */
int
peer_fit(peer_t *p, double current_time)
{
    if (p->stratum >= MAXSTRAT)
        return 0;
    if (root_dist(p, current_time) > MAXDIST + PHI * LOG2D(6))
        return 0;
    if (!p->initialized)
        return 0;
    return 1;
}

/* ------------------------------------------------------------------ */
/*  Comparators                                                        */
/* ------------------------------------------------------------------ */
static int
cmp_edge(const void *a, const void *b)
{
    double ea = ((const chime_entry_t *)a)->edge;
    double eb = ((const chime_entry_t *)b)->edge;
    if (ea < eb) return -1;
    if (ea > eb) return  1;
    return 0;
}

static int
cmp_metric(const void *a, const void *b)
{
    double ma = ((const survivor_t *)a)->metric;
    double mb = ((const survivor_t *)b)->metric;
    if (ma < mb) return -1;
    if (ma > mb) return  1;
    return 0;
}

/* ------------------------------------------------------------------ */
/*  clock_select  -  full peer selection pipeline                      */
/* ------------------------------------------------------------------ */
void
clock_select(peer_t peers[], int n_peers, double current_time,
             system_vars_t *sys)
{
    chime_entry_t chime_list[3 * NMAX];
    survivor_t    survivors[NMAX];
    int           n_chime = 0;
    int           n_fit   = 0;
    int           n_survivors;
    int           i, j;
    double        low, high;
    int           allow, found, chime_val;

    memset(sys, 0, sizeof(*sys));

    /* ---------------------------------------------------------- */
    /* Step 1: Build chime list from fit peers                     */
    /* ---------------------------------------------------------- */
    for (i = 0; i < n_peers; i++) {
        if (!peer_fit(&peers[i], current_time))
            continue;

        double rd = root_dist(&peers[i], current_time);

        chime_list[n_chime].p    = &peers[i];
        chime_list[n_chime].type = -1;
        chime_list[n_chime].edge = peers[i].offset - rd;
        n_chime++;

        chime_list[n_chime].p    = &peers[i];
        chime_list[n_chime].type = 0;
        chime_list[n_chime].edge = peers[i].offset;
        n_chime++;

        chime_list[n_chime].p    = &peers[i];
        chime_list[n_chime].type = +1;
        chime_list[n_chime].edge = peers[i].offset + rd;
        n_chime++;

        n_fit++;
    }

    if (n_fit < NSANE) {
        sys->n_survivors = 0;
        return;
    }

    /* Sort chime list by edge value */
    qsort(chime_list, n_chime, sizeof(chime_entry_t), cmp_edge);

    /* ---------------------------------------------------------- */
    /* Step 2: Intersection algorithm (Marzullo variant)           */
    /* ---------------------------------------------------------- */
    low  = -2e9;
    high = 2e9;

    for (allow = 0; 2 * allow < n_fit; allow++) {
        found     = 0;
        chime_val = 0;

        /* Forward scan: find lower endpoint */
        for (i = 0; i < n_chime; i++) {
            chime_val -= chime_list[i].type;
            if (chime_val >= n_fit - allow) {
                low = chime_list[i].edge;
                break;
            }
            if (chime_list[i].type == 0)
                found++;
        }

        /* Backward scan: find upper endpoint */
        chime_val = 0;
        for (i = n_chime - 1; i >= 0; i--) {
            chime_val += chime_list[i].type;
            if (chime_val >= n_fit - allow) {
                high = chime_list[i].edge;
                break;
            }
            if (chime_list[i].type == 0)
                found++;
        }

        if (found > allow)
            continue;
        if (high > low)
            break;
    }

    if (high <= low) {
        sys->n_survivors = 0;
        return;
    }

    /* ---------------------------------------------------------- */
    /* Step 3: Select truechimers (midpoints within [low, high])   */
    /* ---------------------------------------------------------- */
    n_survivors = 0;
    for (i = 0; i < n_chime; i++) {
        if (chime_list[i].type != 0)
            continue;
        if (chime_list[i].edge >= low && chime_list[i].edge <= high) {
            survivors[n_survivors].p = chime_list[i].p;
            survivors[n_survivors].metric =
                MAXDIST * chime_list[i].p->stratum
                + root_dist(chime_list[i].p, current_time);
            n_survivors++;
        }
    }

    if (n_survivors < NSANE) {
        sys->n_survivors = 0;
        return;
    }

    /* Sort survivors by metric (stratum dominates, then root_dist) */
    qsort(survivors, n_survivors, sizeof(survivor_t), cmp_metric);

    /* ---------------------------------------------------------- */
    /* Step 4: Cluster algorithm                                   */
    /* ---------------------------------------------------------- */
    while (n_survivors > NMIN) {
        double max_sel_jitter  = -1.0;
        double min_peer_jitter = 1e9;
        int    max_idx         = 0;

        for (i = 0; i < n_survivors; i++) {
            if (survivors[i].p->jitter < min_peer_jitter)
                min_peer_jitter = survivors[i].p->jitter;

            double sj = 0.0;
            for (j = 0; j < n_survivors; j++) {
                sj += SQUARE(survivors[i].p->offset
                           - survivors[j].p->offset);
            }
            sj = sqrt(sj);

            if (sj > max_sel_jitter) {
                max_sel_jitter = sj;
                max_idx = i;
            }
        }

        if (max_sel_jitter < min_peer_jitter)
            break;

        /* Remove survivor at max_idx */
        for (i = max_idx; i < n_survivors - 1; i++)
            survivors[i] = survivors[i + 1];
        n_survivors--;
    }

    /* ---------------------------------------------------------- */
    /* Step 5: Combine algorithm (weighted average by root_dist)   */
    /* ---------------------------------------------------------- */
    {
        double y = 0.0, z = 0.0, w = 0.0;
        for (i = 0; i < n_survivors; i++) {
            double x = root_dist(survivors[i].p, current_time);
            y += 1.0 / x;
            z += survivors[i].p->offset / x;
            w += SQUARE(survivors[i].p->offset
                      - survivors[0].p->offset) / x;
        }

        sys->offset   = z / y;
        sys->jitter   = sqrt(w / y);
        sys->stratum  = survivors[0].p->stratum + 1;
        sys->rootdelay = survivors[0].p->rootdelay
                       + survivors[0].p->delay;
        sys->rootdisp  = survivors[0].p->rootdisp
                       + survivors[0].p->disp;
    }

    sys->n_survivors = n_survivors;
    for (i = 0; i < n_survivors; i++)
        sys->survivor_ids[i] = survivors[i].p->id;
}
'''

write_file('/app/ntp_select.c', correct_select)
print("Rewrote ntp_select.c with correct implementations", file=sys.stderr)

print("\nAll fixes applied successfully.", file=sys.stderr)
