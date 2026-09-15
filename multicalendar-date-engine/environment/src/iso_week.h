
#pragma once
#include <cstdint>
#include <tuple>

using Int = int64_t;

struct ISOWeekDate {
    Int year;
    unsigned week;
    unsigned weekday;
};

ISOWeekDate iso_week_from_gregorian(Int y, unsigned m, unsigned d);

std::tuple<Int, unsigned, unsigned> gregorian_from_iso_week(
    Int iso_year, unsigned iso_week, unsigned iso_weekday);
