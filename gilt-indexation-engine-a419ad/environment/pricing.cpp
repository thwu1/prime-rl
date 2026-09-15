#include "pricing.h"
#include "rpi.h"
#include "schedule.h"
#include <cmath>
#include <iostream>


std::vector<Cashflow> generate_cashflows(
    const Date& effective, const Date& maturity,
    double coupon_rate, double base_rpi, int lag,
    const std::map<std::pair<int,int>, double>& rpi)
{
    std::vector<Cashflow> flows;
    auto coupon_dates = generate_coupon_dates(effective, maturity);
    double coupon_per_period = coupon_rate / 2.0;

    for (const auto& cd : coupon_dates) {
        double ref = reference_rpi(cd, lag, rpi);
        double ir = ref / base_rpi;

        Cashflow cf;
        cf.date = cd;
        cf.type = "coupon";
        cf.unindexed = coupon_per_period;
        cf.index_ratio = ir;
        cf.indexed = coupon_per_period * ir;
        flows.push_back(cf);

        if (cd == maturity) {
            Cashflow rd;
            rd.date = maturity;
            rd.type = "redemption";
            rd.unindexed = 100.0;
            rd.index_ratio = ir;
            rd.indexed = 100.0 * ir;
            flows.push_back(rd);
        }
    }
    return flows;
}

double accrued_interest(double xi, double coupon_per_period, bool ex_div) {
    if (ex_div) {
        return 0.0;  // ex-div: buyer doesn't receive next coupon
    }
    return xi * coupon_per_period;
}

double dirty_price_from_yield(
    double yield_rate, double coupon_rate, int n_remaining,
    double xi, int freq, bool ex_div)
{
    double coupon = coupon_rate / (double)freq;
    double c1 = ex_div ? 0.0 : coupon;
    double v2 = 1.0 / (1.0 + yield_rate / (double)freq);

    double v1 = std::pow(v2, xi);
    double v3 = v2;

    if (n_remaining == 1) {
        return v1 * (c1 + 100.0);
    } else if (n_remaining == 2) {
        return v1 * (c1 + v3 * (coupon + 100.0));
    } else {
        double sum = c1;
        for (int i = 2; i <= n_remaining - 1; i++) {
            sum += coupon * std::pow(v2, i - 2);
        }
        sum += (coupon + 100.0) * std::pow(v2, n_remaining - 2) * v3;
        return v1 * sum;
    }
}

double clean_price_from_yield(
    double yield_rate, double coupon_rate, int n_remaining,
    double xi, int freq, bool ex_div)
{
    double dirty = dirty_price_from_yield(yield_rate, coupon_rate, n_remaining,
                                          xi, freq, ex_div);
    double coupon = coupon_rate / (double)freq;
    double ai_y = xi * coupon;
    return dirty - ai_y;
}

double yield_from_clean_price(
    double target_clean, double coupon_rate, int n_remaining,
    double xi, int freq, bool ex_div, double initial_guess)
{
    double y = initial_guess;
    const double tol = 1e-12;
    const int max_iter = 500;
    const double dy = 1e-8;

    for (int iter = 0; iter < max_iter; iter++) {
        double cp = clean_price_from_yield(y, coupon_rate, n_remaining,
                                           xi, freq, ex_div);
        double diff = cp - target_clean;

        if (std::abs(diff) < tol) break;

        double cp_up = clean_price_from_yield(y + dy, coupon_rate, n_remaining,
                                              xi, freq, ex_div);
        double deriv = (cp_up - cp) / dy;

        if (std::abs(deriv) < 1e-15) break;

        y += diff / deriv;
    }

    return y;
}
