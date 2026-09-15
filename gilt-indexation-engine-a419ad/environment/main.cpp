#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <iomanip>
#include <nlohmann/json.hpp>

#include "date_utils.h"
#include "rpi.h"
#include "schedule.h"
#include "pricing.h"
#include "analytics.h"


using json = nlohmann::json;

int main(int argc, char* argv[]) {
    if (argc != 4) {
        std::cerr << "Usage: " << argv[0]
                  << " <rpi.csv> <gilts.json> <output.json>" << std::endl;
        return 1;
    }

    auto rpi_data = load_rpi(argv[1]);

    std::ifstream gf(argv[2]);
    if (!gf.is_open()) {
        std::cerr << "Error: cannot open " << argv[2] << std::endl;
        return 1;
    }
    json gilts_json;
    gf >> gilts_json;

    json results = json::array();

    for (const auto& gilt : gilts_json["gilts"]) {
        std::string id = gilt["id"];
        Date effective = parse_date(gilt["effective"]);
        Date maturity = parse_date(gilt["maturity"]);
        double coupon_rate = gilt["coupon_rate"];
        int index_lag = gilt["index_lag"];
        Date settlement = parse_date(gilt["settlement"]);
        std::string operation = gilt["operation"];

        double base_rpi = reference_rpi(effective, index_lag, rpi_data);
        double settle_ref = reference_rpi(settlement, index_lag, rpi_data);
        double settle_ir = settle_ref / base_rpi;

        auto cashflows = generate_cashflows(effective, maturity, coupon_rate,
                                            base_rpi, index_lag, rpi_data);

        auto coupon_dates = generate_coupon_dates(effective, maturity);
        Date last_cpn = effective;
        Date next_cpn = coupon_dates[0];
        int n_remaining = (int)coupon_dates.size();

        for (size_t i = 0; i < coupon_dates.size(); i++) {
            if (coupon_dates[i] > settlement) {
                next_cpn = coupon_dates[i];
                if (i > 0) last_cpn = coupon_dates[i - 1];
                n_remaining = (int)(coupon_dates.size() - i);
                break;
            }
        }

        bool ex_div = is_ex_dividend(settlement, next_cpn);

        int r_u = days_between(last_cpn, settlement);
        int s_u = days_between(last_cpn, next_cpn);
        double xi = (double)r_u / (double)s_u;

        double coupon_pp = coupon_rate / 2.0;
        double ai = accrued_interest(xi, coupon_pp, ex_div);

        json result;
        result["id"] = id;
        result["base_rpi"] = base_rpi;
        result["settlement_ref_rpi"] = settle_ref;
        result["settlement_index_ratio"] = settle_ir;
        result["n_remaining_coupons"] = n_remaining;
        result["accrual_fraction"] = xi;
        result["ex_dividend"] = ex_div;
        result["accrued_interest"] = ai;

        json cf_arr = json::array();
        for (const auto& cf : cashflows) {
            json cj;
            cj["date"] = cf.date.to_string();
            cj["type"] = cf.type;
            cj["unindexed"] = cf.unindexed;
            cj["index_ratio"] = cf.index_ratio;
            cj["indexed"] = cf.indexed;
            cf_arr.push_back(cj);
        }
        result["cashflows"] = cf_arr;

        double real_yield = 0.0;
        double dirty = 0.0;
        double clean = 0.0;

        if (operation == "price_from_yield") {
            real_yield = gilt["real_yield"].get<double>() / 100.0;
            dirty = dirty_price_from_yield(real_yield, coupon_rate,
                                            n_remaining, xi, 2, ex_div);
            clean = clean_price_from_yield(real_yield, coupon_rate,
                                            n_remaining, xi, 2, ex_div);
        } else if (operation == "yield_from_price") {
            double target_clean = gilt["real_clean_price"].get<double>();
            real_yield = yield_from_clean_price(target_clean, coupon_rate,
                                                n_remaining, xi, 2, ex_div, 0.03);
            dirty = dirty_price_from_yield(real_yield, coupon_rate,
                                            n_remaining, xi, 2, ex_div);
            clean = clean_price_from_yield(real_yield, coupon_rate,
                                            n_remaining, xi, 2, ex_div);
        }

        result["real_yield"] = real_yield;
        result["real_dirty_price"] = dirty;
        result["real_clean_price"] = clean;
        result["indexed_dirty_price"] = dirty * settle_ir;
        result["indexed_clean_price"] = clean * settle_ir;

        double mod_dur = modified_duration(real_yield, coupon_rate, n_remaining,
                                           xi, 2, ex_div);
        double conv = convexity(real_yield, coupon_rate, n_remaining,
                                xi, 2, ex_div);
        double bp_val = bpv(mod_dur, dirty);
        double be_infl = breakeven_inflation(settle_ir, effective, settlement);

        result["modified_duration"] = mod_dur;
        result["convexity"] = conv;
        result["bpv"] = bp_val;
        result["breakeven_inflation"] = be_infl;

        results.push_back(result);
    }

    json output;
    output["results"] = results;

    std::ofstream of(argv[3]);
    of << std::setw(2) << output << std::endl;

    std::cout << "Output written to " << argv[3] << std::endl;
    return 0;
}
