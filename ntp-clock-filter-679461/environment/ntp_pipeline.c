/*
 * ntp_pipeline.c - NTPv4 multi-peer clock synchronization pipeline
 *
 * Reads peer definitions and exchange records from an input file,
 * processes each exchange through the clock filter, then runs peer
 * selection to produce system clock variables.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "ntp_types.h"
#include "ntp_ts.h"
#include "ntp_filter.h"
#include "ntp_select.h"

#define MAX_PEERS  20

static double process_time = 0.0;

int
main(int argc, char *argv[])
{
    peer_t        peers[MAX_PEERS];
    int           n_peers = 0;
    char          line[1024];
    FILE         *fin, *fout;
    system_vars_t sys;
    int           i, j;

    if (argc != 3) {
        fprintf(stderr, "Usage: %s <input> <output>\n", argv[0]);
        return 1;
    }

    fin = fopen(argv[1], "r");
    if (!fin) { perror(argv[1]); return 1; }
    fout = fopen(argv[2], "w");
    if (!fout) { perror(argv[2]); fclose(fin); return 1; }

    while (fgets(line, sizeof(line), fin)) {
        if (line[0] == '#' || line[0] == '\n')
            continue;

        if (strncmp(line, "PEER ", 5) == 0) {
            int    id, strat;
            double rd, rdisp;
            if (sscanf(line, "PEER %d %d %lf %lf",
                       &id, &strat, &rd, &rdisp) == 4) {
                peer_init(&peers[n_peers], id, strat, rd, rdisp);
                n_peers++;
            }
        } else if (strncmp(line, "XCHG ", 5) == 0) {
            int    pid;
            char   h1[20], h2[20], h3[20], h4[20];
            int    sprec;
            double poll;

            if (sscanf(line, "XCHG %d %19s %19s %19s %19s %d %lf",
                       &pid, h1, h2, h3, h4, &sprec, &poll) == 7) {
                peer_t  *p = NULL;
                for (i = 0; i < n_peers; i++) {
                    if (peers[i].id == pid) { p = &peers[i]; break; }
                }
                if (!p) continue;

                ntp_ts_t t1 = parse_ntp_ts(h1);
                ntp_ts_t t2 = parse_ntp_ts(h2);
                ntp_ts_t t3 = parse_ntp_ts(h3);
                ntp_ts_t t4 = parse_ntp_ts(h4);

                process_time += poll;

                /*
                 * Clock offset per RFC 5905 Section 8:
                 *   theta = 1/2 * [(T2 - T1) + (T4 - T3)]
                 */
                double offset = (ntp_diff(t2, t1)
                               + ntp_diff(t4, t3)) / 2.0;

                /*
                 * Round-trip delay:
                 *   delta = (T4 - T1) - (T3 - T2)
                 */
                double delay = ntp_diff(t4, t1) - ntp_diff(t3, t2);
                delay = fmax(delay, LOG2D(PRECISION));

                /*
                 * Sample dispersion:
                 *   epsilon = 2^prec_server + 2^prec_local
                 *           + PHI * |T4 - T1|
                 */
                double disp = LOG2D(sprec) + LOG2D(PRECISION)
                            + PHI * fabs(ntp_diff(t4, t1));

                clock_filter(p, offset, delay, disp, process_time);
            }
        }
    }
    fclose(fin);

    /* Run peer selection pipeline */
    clock_select(peers, n_peers, process_time, &sys);

    /* Output per-peer results */
    for (i = 0; i < n_peers; i++) {
        int selected = 0;
        for (j = 0; j < sys.n_survivors; j++) {
            if (sys.survivor_ids[j] == peers[i].id) {
                selected = 1;
                break;
            }
        }
        fprintf(fout, "PEER %d %.9f %.9f %.9f %.9f %.9f %s\n",
                peers[i].id,
                peers[i].offset,
                peers[i].delay,
                peers[i].disp,
                peers[i].jitter,
                root_dist(&peers[i], process_time),
                selected ? "selected" : "rejected");
    }

    /* Output system variables */
    fprintf(fout, "SYSTEM %.9f %.9f %.9f %.9f %d\n",
            sys.offset, sys.jitter,
            sys.rootdelay, sys.rootdisp,
            sys.n_survivors);

    fclose(fout);
    return 0;
}
