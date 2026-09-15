#include "analytics.h"
#include "pricing.h"
#include <cmath>


// Risk analytics module for UK index-linked gilts.
// These functions are not yet implemented.

double modified_duration(double yield_rate, double coupon_rate, int n_remaining,
                         double xi, int freq, bool ex_div) {
    return 0.0;
}

double convexity(double yield_rate, double coupon_rate, int n_remaining,
                 double xi, int freq, bool ex_div) {
    return 0.0;
}

double bpv(double modified_dur, double dirty_price) {
    return 0.0;
}

double breakeven_inflation(double index_ratio, const Date& effective,
                           const Date& settlement) {
    return 0.0;
}
