#include "schedule.h"


std::vector<Date> generate_coupon_dates(const Date& effective, const Date& maturity) {
    std::vector<Date> dates;
    Date d = add_months(effective, 6);
    while (d <= maturity) {
        dates.push_back(d);
        d = add_months(d, 6);
    }
    if (dates.empty() || dates.back() != maturity) {
        dates.push_back(maturity);
    }
    return dates;
}

bool is_ex_dividend(const Date& settlement, const Date& next_coupon) {
    Date ex_div_date = subtract_business_days(next_coupon, 7);
    return settlement > ex_div_date;
}
