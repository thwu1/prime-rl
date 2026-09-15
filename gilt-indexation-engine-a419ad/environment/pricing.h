#pragma once
#include "date_utils.h"
#include <string>
#include <vector>
#include <map>
#include <utility>

struct Cashflow {
    Date date;
    std::string type;
    double unindexed;
    double index_ratio;
    double indexed;
};

std::vector<Cashflow> generate_cashflows(
    const Date& effective, const Date& maturity,
    double coupon_rate, double base_rpi, int lag,
    const std::map<std::pair<int,int>, double>& rpi);

double accrued_interest(double xi, double coupon_per_period, bool ex_div);

double dirty_price_from_yield(
    double yield_rate, double coupon_rate, int n_remaining,
    double xi, int freq, bool ex_div);

double clean_price_from_yield(
    double yield_rate, double coupon_rate, int n_remaining,
    double xi, int freq, bool ex_div);

double yield_from_clean_price(
    double target_clean, double coupon_rate, int n_remaining,
    double xi, int freq, bool ex_div, double initial_guess);
