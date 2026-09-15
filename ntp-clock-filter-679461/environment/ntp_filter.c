/*
 * ntp_filter.c - RFC 5905 clock filter algorithm
 *
 * Maintains an 8-stage shift register of (offset, delay, dispersion,
 * time) tuples.  Selects the best sample (lowest delay), computes
 * peer dispersion and jitter.
 *
 */

#include "ntp_filter.h"
#include <string.h>
#include <stdlib.h>
#include <math.h>

void
peer_init(peer_t *p, int id, int stratum,
          double rootdelay, double rootdisp)
{
    int i;
    memset(p, 0, sizeof(*p));
    p->id        = id;
    p->stratum   = stratum;
    p->rootdelay = rootdelay;
    p->rootdisp  = rootdisp;
    for (i = 0; i < NSTAGE; i++) {
        p->f[i].offset = 0.0;
        p->f[i].delay  = MAXDISP;
        p->f[i].disp   = MAXDISP;
        p->f[i].time   = 0.0;
    }
    p->jitter      = LOG2D(PRECISION);
    p->initialized = 0;
}

static int
cmp_delay(const void *a, const void *b)
{
    double da = ((const filter_stage_t *)a)->delay;
    double db = ((const filter_stage_t *)b)->delay;
    if (da < db) return -1;
    if (da > db) return  1;
    return 0;
}

void
clock_filter(peer_t *p, double offset, double delay,
             double disp, double current_time)
{
    filter_stage_t sorted[NSTAGE];
    int    i, n;

    /*
     * Shift register per RFC 5905 A.5.2: shift each tuple,
     * increasing dispersion since the last filter update.
     * New sample placed at index 0.
     */
    for (i = 1; i < NSTAGE; i++) {
        p->f[i] = p->f[i - 1];
        p->f[i].disp += PHI * (current_time - p->t);
    }
    p->f[0].offset = offset;
    p->f[0].delay  = delay;
    p->f[0].disp   = disp;
    p->f[0].time   = current_time;

    /* Copy to temporary list and sort by increasing delay */
    memcpy(sorted, p->f, sizeof(sorted));
    qsort(sorted, NSTAGE, sizeof(filter_stage_t), cmp_delay);

    /* Select peer variables from best (lowest delay) sample */
    p->offset = sorted[0].offset;
    p->delay  = sorted[0].delay;

    /*
     * Peer dispersion per RFC 5905 Section 10:
     *
     *            i=NSTAGE-1
     *            ----   epsilon_i
     *   disp =    \    ----------
     *             /      (i+1)
     *            ----   2
     *            i=0
     */
    p->disp = 0.0;
    for (i = 0; i < NSTAGE; i++) {
        p->disp += sorted[i].disp / (2 ^ (i + 1));
    }

    /*
     * Jitter: based on offset differences from best sample,
     * bounded below by system precision.
     */
    n = 0;
    p->jitter = 0.0;
    for (i = 1; i < NSTAGE; i++) {
        if (sorted[i].disp < MAXDISP) {
            p->jitter += SQUARE(sorted[i].offset - sorted[0].offset);
            n++;
        }
    }
    if (n > 0)
        p->jitter = p->jitter / (n + 1);
    p->jitter = fmax(p->jitter, LOG2D(PRECISION));

    /* Prime directive: never use a sample older than the latest one */
    if (sorted[0].time <= p->t && p->initialized)
        return;

    p->t           = sorted[0].time;
    p->initialized = 1;
}
