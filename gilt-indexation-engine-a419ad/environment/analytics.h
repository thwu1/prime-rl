#pragma once
#include "date_utils.h"

double modified_duration(double yield_rate, double coupon_rate, int n_remaining,
                         double xi, int freq, bool ex_div);

double convexity(double yield_rate, double coupon_rate, int n_remaining,
                 double xi, int freq, bool ex_div);

double bpv(double modified_dur, double dirty_price);

double breakeven_inflation(double index_ratio, const Date& effective,
                           const Date& settlement);
