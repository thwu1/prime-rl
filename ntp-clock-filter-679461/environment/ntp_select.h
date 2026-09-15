/*
 * ntp_select.h - RFC 5905 peer selection algorithms interface
 *
 */

#ifndef NTP_SELECT_H
#define NTP_SELECT_H

#include "ntp_types.h"

double root_dist(peer_t *p, double current_time);
int    peer_fit(peer_t *p, double current_time);
void   clock_select(peer_t peers[], int n_peers,
                    double current_time, system_vars_t *sys);

#endif /* NTP_SELECT_H */
