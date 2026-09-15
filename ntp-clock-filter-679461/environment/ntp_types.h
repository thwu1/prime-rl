/*
 * ntp_types.h - NTPv4 type definitions and constants per RFC 5905
 *
 */

#ifndef NTP_TYPES_H
#define NTP_TYPES_H

#include <stdint.h>
#include <math.h>

/* ------------------------------------------------------------------ */
/*  Constants from RFC 5905 Appendix A.1.1                            */
/* ------------------------------------------------------------------ */
#define NSTAGE      8       /* clock filter stages                    */
#define MAXDISP     16.0    /* maximum dispersion (s)                 */
#define MAXDIST     1.0     /* distance threshold (s)                 */
#define PHI         15e-6   /* frequency tolerance (15 ppm)           */
#define MINDISP     0.01    /* minimum dispersion (s)                 */
#define SGATE       3       /* spike gate                             */
#define PRECISION   -20     /* local clock precision (log2 s)         */
#define MAXSTRAT    16      /* maximum stratum                        */
#define NMAX        50      /* maximum number of peers                */
#define NSANE       1       /* minimum intersection survivors         */
#define NMIN        3       /* minimum cluster survivors              */

/* ------------------------------------------------------------------ */
/*  Conversion macros                                                 */
/* ------------------------------------------------------------------ */
#define LOG2D(a)    ((a) < 0 ? 1.0 / (1L << -(a)) : (double)(1L << (a)))
#define SQUARE(x)   ((x) * (x))

/* ------------------------------------------------------------------ */
/*  NTP 64-bit timestamp                                              */
/* ------------------------------------------------------------------ */
typedef struct {
    uint32_t seconds;       /* seconds since 1900-01-01 */
    uint32_t fraction;      /* fractional seconds       */
} ntp_ts_t;

/* ------------------------------------------------------------------ */
/*  Clock filter stage                                                */
/* ------------------------------------------------------------------ */
typedef struct {
    double offset;
    double delay;
    double disp;
    double time;            /* process arrival time */
} filter_stage_t;

/* ------------------------------------------------------------------ */
/*  Peer state                                                        */
/* ------------------------------------------------------------------ */
typedef struct {
    int      id;
    int      stratum;
    double   rootdelay;
    double   rootdisp;
    filter_stage_t f[NSTAGE];
    double   offset;
    double   delay;
    double   disp;
    double   jitter;
    double   t;             /* last update time */
    int      initialized;
} peer_t;

/* ------------------------------------------------------------------ */
/*  Chime list entry (intersection algorithm)                         */
/* ------------------------------------------------------------------ */
typedef struct {
    peer_t  *p;
    int      type;          /* +1=upper, 0=midpoint, -1=lower */
    double   edge;
} chime_entry_t;

/* ------------------------------------------------------------------ */
/*  Survivor list entry (clustering algorithm)                        */
/* ------------------------------------------------------------------ */
typedef struct {
    peer_t  *p;
    double   metric;
} survivor_t;

/* ------------------------------------------------------------------ */
/*  System variables                                                  */
/* ------------------------------------------------------------------ */
typedef struct {
    double   offset;
    double   jitter;
    double   rootdelay;
    double   rootdisp;
    int      stratum;
    int      n_survivors;
    int      survivor_ids[NMAX];
} system_vars_t;

#endif /* NTP_TYPES_H */
