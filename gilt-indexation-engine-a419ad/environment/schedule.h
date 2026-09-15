#pragma once
#include "date_utils.h"
#include <vector>

std::vector<Date> generate_coupon_dates(const Date& effective, const Date& maturity);
bool is_ex_dividend(const Date& settlement, const Date& next_coupon);
