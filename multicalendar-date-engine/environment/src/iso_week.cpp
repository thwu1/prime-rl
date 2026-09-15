
#include "iso_week.h"
#include "calendar_core.h"

ISOWeekDate iso_week_from_gregorian(Int y, unsigned m, unsigned d) {
    // TODO: implement ISO 8601 week date calculation
    // Week 1 contains January 4. Weeks start on Monday.
    // Weekday: 1=Mon, 2=Tue, ..., 7=Sun
    return {y, 1, 1};
}

std::tuple<Int, unsigned, unsigned> gregorian_from_iso_week(
    Int iso_year, unsigned iso_week, unsigned iso_weekday) {
    // TODO: implement reverse ISO week date conversion
    return {iso_year, 1, 1};
}
