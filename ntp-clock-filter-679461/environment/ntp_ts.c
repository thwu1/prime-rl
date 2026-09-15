/*
 * ntp_ts.c - NTP timestamp parsing and arithmetic
 *
 * Implements first-order timestamp differences per RFC 5905 Section 6:
 * unsigned 64-bit subtraction yielding a signed result, converted to
 * floating-point seconds.
 *
 */

#include "ntp_ts.h"
#include <stdio.h>

ntp_ts_t
parse_ntp_ts(const char *hex)
{
    ntp_ts_t ts;
    unsigned long long val;
    sscanf(hex, "%llx", &val);
    ts.seconds  = (uint32_t)(val >> 32);
    ts.fraction = (uint32_t)(val & 0xFFFFFFFF);
    return ts;
}

double
ntp_diff(ntp_ts_t a, ntp_ts_t b)
{
    uint64_t a64 = ((uint64_t)a.seconds << 32) | a.fraction;
    uint64_t b64 = ((uint64_t)b.seconds << 32) | b.fraction;
    int64_t  diff = (int64_t)(a64 - b64);
    return (double)diff / 4294967296.0;   /* / 2^32 */
}
