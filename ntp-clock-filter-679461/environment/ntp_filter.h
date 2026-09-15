/*
 * ntp_filter.h - RFC 5905 clock filter algorithm interface
 *
 */

#ifndef NTP_FILTER_H
#define NTP_FILTER_H

#include "ntp_types.h"

void peer_init(peer_t *p, int id, int stratum,
               double rootdelay, double rootdisp);
void clock_filter(peer_t *p, double offset, double delay,
                  double disp, double current_time);

#endif /* NTP_FILTER_H */
