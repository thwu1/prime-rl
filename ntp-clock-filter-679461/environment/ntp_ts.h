/*
 * ntp_ts.h - NTP timestamp parsing and arithmetic
 *
 */

#ifndef NTP_TS_H
#define NTP_TS_H

#include "ntp_types.h"

ntp_ts_t parse_ntp_ts(const char *hex);
double   ntp_diff(ntp_ts_t a, ntp_ts_t b);

#endif /* NTP_TS_H */
