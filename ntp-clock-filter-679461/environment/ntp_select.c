/*
 * ntp_select.c - RFC 5905 peer selection pipeline
 *
 * Implements root distance computation, fitness check, and the
 * clock_select() function which should perform intersection,
 * clustering, and combining of peer offsets.
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
    (void)current_time;
    return fmax(MINDISP, p->rootdelay + p->delay) / 2.0
         + p->rootdisp
         + p->disp;
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
/*  Comparators for sorting                                            */
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
/*  clock_select  -  peer selection pipeline                           */
/*                                                                     */
/*  Should implement:                                                  */
/*    1. Build correctness intervals and run intersection algorithm    */
/*    2. Cluster survivors by pruning max-jitter outliers              */
/*    3. Combine survivor offsets via weighted average                  */
/* ------------------------------------------------------------------ */
void
clock_select(peer_t peers[], int n_peers, double current_time,
             system_vars_t *sys)
{
    int    i;
    double sum_offset    = 0.0;
    double sum_jitter_sq = 0.0;
    int    n_fit         = 0;

    /* suppress unused-function warnings for provided comparators */
    (void)cmp_edge;
    (void)cmp_metric;

    memset(sys, 0, sizeof(*sys));

    /*
     * Placeholder: select all fit peers without running the
     * intersection or clustering algorithms.
     */
    for (i = 0; i < n_peers; i++) {
        if (!peer_fit(&peers[i], current_time))
            continue;
        sys->survivor_ids[n_fit] = peers[i].id;
        sum_offset    += peers[i].offset;
        sum_jitter_sq += SQUARE(peers[i].jitter);
        n_fit++;
    }

    if (n_fit == 0) {
        sys->n_survivors = 0;
        return;
    }

    /*
     * Placeholder: simple average of offsets (not weighted).
     */
    sys->offset      = sum_offset / n_fit;
    sys->jitter      = sqrt(sum_jitter_sq / n_fit);
    sys->n_survivors = n_fit;

    /* System root variables from first fit peer */
    for (i = 0; i < n_peers; i++) {
        if (peer_fit(&peers[i], current_time)) {
            sys->stratum  = peers[i].stratum + 1;
            sys->rootdelay = peers[i].rootdelay + peers[i].delay;
            sys->rootdisp  = peers[i].rootdisp  + peers[i].disp;
            break;
        }
    }
}
